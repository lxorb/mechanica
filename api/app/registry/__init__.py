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
from .doctype import classify_doc

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

# Hosts that answer 403 to the default UA but serve the PDF to a browser one. Checked by magic-byte
# sample; merge_ua() stamps the hint on rows that arrive without one so the fetcher gets it right.
UA_BY_HOST = {"contentdelivery.ext.gm.com": "browser", "cdn.powersports.honda.com": "googlebot"}

# Hosts whose urls look like PDFs but do not serve one. kiatechinfo.com answers 200 with an empty
# body and no content-type to every request shape tried (2026-09-20); drop the host once it works.
BROKEN_HOSTS = ("kiatechinfo.com",)
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


def _fetchable(e: RegistryEntry) -> bool:
    """A free official owner's manual our fetcher can take, in any language."""
    if any(h in e.url for h in BROKEN_HOSTS):
        return False
    return e.type == "owner" and e.access == "free" and _is_pdf(e.url)


def _ingestable(e: RegistryEntry) -> bool:
    """...and in English, which is the only thing `/ingest` queues unattended."""
    return _fetchable(e) and e.lang.lower().startswith("en")


def merge_ua(entries: Iterable[RegistryEntry]) -> list[RegistryEntry]:
    """Stamp the derived metadata adapters written elsewhere do not set: the User-Agent hint and the
    document kind. Both are additive - no existing field is touched."""
    rows = list(entries)
    for e in rows:
        if not e.docKind:
            e.docKind = classify_doc(e.url, e.title)
        if not e.needsUa:
            host = e.url.split("/")[2].lower() if "//" in e.url else ""
            hint = UA_BY_HOST.get(host)
            if hint:
                e.needsUa = hint
    return rows


ALIAS_MIN = 3
NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def alias_key(make: str, model: str, year: object) -> str:
    """The same vehicle with the punctuation rubbed out: `Multistrada V4 S` and `Multistrada V4S`,
    `FC 250` and `FC250`, `R nineT` and `R Nine T`, `R&G` and `R and G` all collapse to one key.

    This can only ever merge spellings, never model families: what is left after the rub-out is the
    model's whole alphanumeric sequence in order, so two genuinely different models cannot collide -
    `CB500F` and `CB500X` stay apart, and so do `RS 660` and `RS 457`. The make and the year are
    part of the key, so an alias never reaches across either. A stub shorter than three characters
    gets no key at all, because `R` would match far too much."""
    core = NOT_ALNUM.sub("", (model or "").lower().replace("&", " and "))
    if len(core) < ALIAS_MIN:
        return ""
    return f"{NOT_ALNUM.sub('', (make or '').lower())}|{core}|{year}"


def _index(rows: Iterable[RegistryEntry], keyed: Callable[[RegistryEntry, int], str]) -> dict[str, list[RegistryEntry]]:
    found: dict[str, list[RegistryEntry]] = {}
    for e in rows:
        if not e.model or e.model.strip().lower() == "all models":
            continue
        for year in e.years:
            key = keyed(e, year)
            if key:
                found.setdefault(key, []).append(e)
    for group in found.values():
        group.sort(key=lambda e: (_supplement(e), _lang_rank(e.lang), _market_rank(e.market)))
    return found


def pdf_index() -> dict[str, list[RegistryEntry]]:
    """bike id -> every free English owner's-manual PDF covering it, best market first."""
    return _index((e for e in get_store().registry() if _ingestable(e)), lambda e, y: slug(e.make, e.model, y))


def alias_index() -> dict[str, list[RegistryEntry]]:
    """The same thing keyed by `alias_key()`, for vehicles whose model name is spelled differently
    in the catalogue than on the OEM's portal."""
    return _index((e for e in get_store().registry() if _ingestable(e)), lambda e, y: alias_key(e.make, e.model, y))


def foreign_index() -> dict[str, list[RegistryEntry]]:
    """Free official handbooks that are **not** in English, keyed both ways. Used only for vehicles
    no English manual covers: a German Betriebsanleitung is the manufacturer's own book for that
    bike, and offering it beats offering nothing. Never queued for unattended ingest."""
    rows = [e for e in get_store().registry() if _fetchable(e) and not e.lang.lower().startswith("en")]
    both = _index(rows, lambda e, y: slug(e.make, e.model, y))
    for key, group in _index(rows, lambda e, y: alias_key(e.make, e.model, y)).items():
        both.setdefault(key, group)
    return both


# What a vehicle should link to, best first. A brochure is a real free PDF and stays in the registry,
# it just never wins over a handbook.
DOC_RANK = ("owner", "service", "quickstart", "supplement", "spec", "infotainment", "brochure", "warranty")


def doc_kind(e: RegistryEntry) -> str:
    """The row's docKind, classified on the spot when it was indexed before the field existed."""
    return e.docKind or classify_doc(e.url, e.title)


def _supplement(e: RegistryEntry) -> int:
    try:
        return DOC_RANK.index(doc_kind(e))
    except ValueError:
        return len(DOC_RANK)


def kind_of(item: Bike | RegistryEntry) -> str:
    """Vehicle kind, with the historical default: a row that predates the field is a motorcycle."""
    return (item.kind or "motorcycle").lower()


def _pick(rows: list[RegistryEntry], market: str, kind: str = "motorcycle") -> RegistryEntry:
    """Never hand a car's manual to a motorcycle: same kind first, then the bike's own market, then
    the fallback order (EU, US, GB, WW, IN)."""
    same = [e for e in rows if kind_of(e) == kind] or rows
    best = min(_supplement(e) for e in same)
    same = [e for e in same if _supplement(e) == best]  # a handbook beats a brochure, whatever its market
    return next((e for e in same if e.market.upper() == market.upper()), same[0])


# When a vehicle has no English manual at all, this is the order the other languages are offered in:
# the big European printings first, then the maker's home languages. Anything unlisted comes last.
LANG_FALLBACK = ("de", "fr", "es", "it", "nl", "pt", "ja", "sv", "da", "no", "fi", "pl")


def _lang_rank(lang: str) -> int:
    code = (lang or "").lower().split("-")[0]
    if code.startswith("en"):
        return -1  # English always first; the foreign index never contains one
    try:
        return LANG_FALLBACK.index(code)
    except ValueError:
        return len(LANG_FALLBACK)


def _market_rank(market: str) -> int:
    try:
        return MARKET_FALLBACK.index(market.upper())
    except ValueError:
        return len(MARKET_FALLBACK)


def bikes_from_registry() -> list[Bike]:
    """One Bike per make/model/year seen in the registry, plus a manualUrl on every catalog vehicle a
    free PDF covers. The registry row's `kind` carries over, so a car row derives a car; a vehicle
    already in the catalog keeps its kind when the row has none. Merged into the store: manualId,
    vins and cues set by other passes are kept."""
    store = get_store()
    manuals = pdf_index()
    aliases = alias_index()
    foreign = foreign_index()
    hits: list[tuple[str, str, str, str]] = []  # (how, make, catalogue model, registry model)
    known = {b.id: b for b in store.bikes()}  # re-read late: other passes write manualId concurrently
    out: dict[str, Bike] = {}
    for e in store.registry():
        if e.type != "owner" or not e.years or not e.model or e.model.strip().lower() == "all models":
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
                kind=e.kind or (old.kind if old else None),  # a car's registry row must derive a car
                lang=None,  # recomputed below, like manualUrl
                vins=old.vins if old else None,
                cues=old.cues if old else None,
            )
    for bid, bike in known.items():  # seed-catalog bikes the registry never produced can still have a PDF
        if bid in out:
            continue
        key = alias_key(bike.make, bike.model, bike.year)
        if bid in manuals or bid in foreign or (key and (key in aliases or key in foreign)):
            out[bid] = bike.model_copy()
    for bid, bike in out.items():
        # Three passes, each strictly worse than the one before, and never mixed: the exact id, then
        # the same model spelled differently, then the manufacturer's own book in another language.
        # manualUrl stays a pure function of the registry - no covering row means no offer, so a
        # retracted row stops being advertised instead of lingering as a link nothing can fetch.
        key = alias_key(bike.make, bike.model, bike.year)
        rows = manuals.get(bid)
        how = "exact"
        if not rows and key:
            rows = aliases.get(key)
            how = "alias"
        if not rows:
            rows = foreign.get(bid) or (foreign.get(key) if key else None)
            how = "foreign"
        if not rows:
            bike.manualUrl, bike.lang = None, None
            continue
        best = _pick(rows, bike.market, kind_of(bike))
        bike.manualUrl = best.url
        # `lang` is set only when the offer is not English, so a reader can be told before they open it.
        bike.lang = None if best.lang.lower().startswith("en") else best.lang
        if how != "exact" and best.model.lower() != bike.model.lower():
            hits.append((how, bike.make, bike.model, best.model))
        elif how == "foreign":
            hits.append((how, bike.make, bike.model, best.lang))
    if hits:
        pairs = sorted({h for h in hits})
        log.info("bikes: %d vehicle(s) matched by alias or language fallback, %d distinct pairing(s)", len(hits), len(pairs))
        for how, make, catalogue, other in pairs[:40]:
            log.info("  %-7s %-16s %-32s -> %s", how, make, catalogue[:32], other)
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
