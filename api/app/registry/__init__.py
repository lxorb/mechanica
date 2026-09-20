"""Index every handbook without copying it.

One adapter per OEM portal returning RegistryEntry rows (where the official manual lives, free or not).
crawl() stores them; bikes_from_registry() derives catalog Bikes; free_owner_manuals() lists ingestable PDFs.
"""

import importlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from ..models import Bike, RegistryEntry
from ..store import get_store
from ._http import BROWSER_UA, GOOGLEBOT_UA, UA, client, log, request, slug

# adapter name -> (module in this package, function). Imported one by one rather than with a plain
# `from .x import y`: several agents write modules in here at once, and one broken file must not take
# the package - and with it the API - down. Whatever imports is registered; the rest is logged.
BUILTIN: dict[str, tuple[str, str]] = {
    "ktm": ("pierer", "ktm"),
    "husqvarna": ("pierer", "husqvarna"),
    "gasgas": ("pierer", "gasgas"),
    "bmw": ("bmw", "bmw"),
    "yamaha-eu": ("yamaha", "yamaha_eu"),
    "yamaha-us": ("yamaha", "yamaha_us"),
    "honda-us": ("honda", "honda_us"),
    "honda-eu": ("honda", "honda_eu"),
    "kawasaki": ("kawasaki", "kawasaki"),
    "triumph": ("triumph", "triumph"),
    "royal-enfield": ("royalenfield", "royal_enfield"),
    "suzuki-de": ("suzuki", "suzuki_de"),
    "suzuki-en": ("suzuki", "suzuki_en"),
    "zero": ("zero", "zero"),
    "hero": ("india", "hero"),
    "tvs": ("india", "tvs"),
    "bajaj": ("india", "bajaj"),
    "mv-agusta": ("mvagusta", "mv_agusta"),
    "kymco": ("kymco", "kymco"),
    "service": ("service", "service_manuals"),
}

ADAPTERS: dict[str, Callable[[], Iterable[RegistryEntry]]] = {}

for _name, (_module, _attr) in BUILTIN.items():
    try:
        ADAPTERS[_name] = getattr(importlib.import_module(f".{_module}", __name__), _attr)
    except Exception as _exc:  # a module another agent is mid-edit on, or one that lost its function
        log.warning("adapter %s unavailable (%s.%s): %s: %s", _name, _module, _attr, type(_exc).__name__, _exc)

# Hosts that serve a PDF from a URL without a .pdf suffix. Every entry here was verified with a
# magic-byte sample (python -m tools.registry stats --verify); nothing is whitelisted on faith.
PDF_HOSTS: tuple[str, ...] = (
    "zeromotorcycles.learnupon.com",
    "api.triumphtechnicalinformation.com",
    "operatorsguides.brp.com",  # /readguide/<id> streams the Can-Am operator's guide as application/pdf
)

UA_HEADER = {"googlebot": GOOGLEBOT_UA, "browser": BROWSER_UA}
MARKET_FALLBACK = ("EU", "US", "GB", "WW", "IN")


def discover() -> list[str]:
    """Register the adapters other agents drop into this package: any module here exposing a rows()
    callable becomes an adapter named after the module. A module that fails to import is skipped, so
    one half-written file never takes the crawl down."""
    added: list[str] = []
    for path in sorted(Path(__file__).parent.glob("*.py")):
        name = path.stem.replace("_", "-")
        if path.stem.startswith("_") or path.stem == "dynamic" or name in ADAPTERS:
            continue
        try:
            module = importlib.import_module(f".{path.stem}", __name__)
        except Exception as exc:
            log.warning("registry module %s does not import: %s: %s", path.stem, type(exc).__name__, exc)
            continue
        fn = getattr(module, "rows", None)
        if callable(fn):
            ADAPTERS[name] = fn
            added.append(name)
    if added:
        log.info("discovered adapters: %s", ", ".join(added))
    return added


def select(brands: list[str] | None) -> list[str]:
    discover()
    if not brands:
        return list(ADAPTERS)
    wanted: list[str] = []
    for brand in brands:
        key = brand.strip().lower().replace("_", "-")
        wanted += [name for name in ADAPTERS if name == key or name.startswith(key + "-")]
    return list(dict.fromkeys(wanted))


def crawl(brands: list[str] | None = None) -> int:
    """Run the selected adapters, store what they found, return the number of entries stored."""
    store = get_store()
    total = 0
    for name in select(brands):
        try:
            entries = [e for e in ADAPTERS[name]() if e.url]
        except Exception as exc:
            log.exception("adapter %s failed: %s", name, exc)
            continue
        if entries:
            store.put_registry(entries)
            total += len(entries)
        log.info("%s: stored %d", name, len(entries))
    return total


def _is_pdf(url: str) -> bool:
    """True when fetching this url yields a PDF: the path ends .pdf, or the host is a verified one."""
    head = url.split("?", 1)[0].split("#", 1)[0].lower()
    return head.endswith(".pdf") or any(h in head for h in PDF_HOSTS)


def _ingestable(e: RegistryEntry) -> bool:
    return e.type == "owner" and e.access == "free" and e.lang.lower().startswith("en") and _is_pdf(e.url)


def pdf_index() -> dict[str, list[RegistryEntry]]:
    """bike id -> every free English owner's-manual PDF covering it, best market first."""
    found: dict[str, list[RegistryEntry]] = {}
    for e in get_store().registry():
        if not _ingestable(e) or not e.model or e.model == "All models":
            continue
        for year in e.years:
            found.setdefault(slug(e.make, e.model, year), []).append(e)
    for rows in found.values():
        rows.sort(key=lambda e: (_market_rank(e.market), _supplement(e)))
    return found


def _supplement(e: RegistryEntry) -> int:
    """Addenda, specification sheets and connectivity guides are real PDFs but not the handbook."""
    return int(bool(re.search(r"addendum|supplement|specification|connectivity", e.title or "", re.I)))


def _pick(rows: list[RegistryEntry], market: str) -> RegistryEntry:
    """The bike's own market wins; otherwise the first of the fallback order (EU, US, GB, WW, IN)."""
    return next((e for e in rows if e.market.upper() == market.upper()), rows[0])


def _market_rank(market: str) -> int:
    try:
        return MARKET_FALLBACK.index(market.upper())
    except ValueError:
        return len(MARKET_FALLBACK)


def bikes_from_registry() -> list[Bike]:
    """One Bike per make/model/year seen in the registry, plus a manualUrl on every catalog bike a free
    PDF covers. Merged into the store: manualId, vins and cues set by other passes are kept."""
    store = get_store()
    manuals = pdf_index()
    known = {b.id: b for b in store.bikes()}  # re-read late: other passes write manualId concurrently
    out: dict[str, Bike] = {}
    for e in store.registry():
        if e.type != "owner" or not e.years or not e.model or e.model == "All models":
            continue
        for year in e.years:
            bid = slug(e.make, e.model, year)
            if bid in out:
                continue
            old = known.get(bid)
            out[bid] = Bike(
                id=bid,
                make=e.make,
                model=e.model,
                year=year,
                market=old.market if old else e.market,
                manualId=old.manualId if old else None,
                manualUrl=None,
                vins=old.vins if old else None,
                cues=old.cues if old else None,
            )
    for bid, bike in known.items():  # seed-catalog bikes the registry never produced can still have a PDF
        if bid not in out and bid in manuals:
            out[bid] = bike.model_copy()
    for bid, bike in out.items():
        rows = manuals.get(bid)
        bike.manualUrl = _pick(rows, bike.market).url if rows else (known[bid].manualUrl if bid in known else None)
    bikes = list(out.values())
    if bikes:
        store.put_bikes(bikes)
    return bikes


def free_owner_manuals(make: str | None = None, limit: int = 20) -> list[RegistryEntry]:
    """Free English owner's manuals the ingest pipeline can fetch directly, newest model years first."""
    entries = [e for e in get_store().registry(make=make) if _ingestable(e)]
    entries.sort(key=lambda e: (-(max(e.years) if e.years else 0), e.make.lower(), e.model.lower()))
    return entries[: max(0, limit)]


def verify(entries: Iterable[RegistryEntry]) -> list[tuple[RegistryEntry, bool, str]]:
    """Fetch the first bytes of each url and say whether a PDF really comes back. Honours needsUa."""
    out: list[tuple[RegistryEntry, bool, str]] = []
    for e in entries:
        ua = UA_HEADER.get((e.needsUa or "").lower(), UA)
        with client(ua=ua) as c:
            r = request(c, "GET", e.url, headers={"Range": "bytes=0-1023", "Accept-Encoding": "identity"})
        if r is None:
            out.append((e, False, "unreachable"))
            continue
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        ok = r.content[:5] == b"%PDF-" or ctype == "application/pdf"
        out.append((e, ok, f"{r.status_code} {ctype or '?'} {r.content[:5]!r}"))
    return out
