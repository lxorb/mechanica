"""Index every handbook without copying it.

One adapter per OEM portal returning RegistryEntry rows (where the official manual lives, free or not).
crawl() stores them; bikes_from_registry() derives catalog Bikes; free_owner_manuals() lists ingestable PDFs.
"""

from collections.abc import Callable, Iterable

from ..models import Bike, RegistryEntry
from ..store import get_store
from ._http import log, slug
from .bmw import bmw
from .honda import honda_eu, honda_us
from .kawasaki import kawasaki
from .pierer import gasgas, husqvarna, ktm
from .royalenfield import royal_enfield
from .service import service_manuals
from .suzuki import suzuki
from .triumph import triumph
from .yamaha import yamaha

ADAPTERS: dict[str, Callable[[], Iterable[RegistryEntry]]] = {
    "ktm": ktm,
    "husqvarna": husqvarna,
    "gasgas": gasgas,
    "bmw": bmw,
    "yamaha": yamaha,
    "honda-us": honda_us,
    "honda-eu": honda_eu,
    "kawasaki": kawasaki,
    "triumph": triumph,
    "royal-enfield": royal_enfield,
    "suzuki": suzuki,
    "service": service_manuals,
}

DIRECT_HOSTS = (
    "azwecdnepstoragewebsiteuploads.azureedge.net",
    "cdn.powersports.honda.com",
    "cdn2.yamaha-motor.eu",
    "manuals.bmw-motorrad.com",
    "pws.ktivs.net",
    "2rom-prd-data.hondamotopub.com",
)


def select(brands: list[str] | None) -> list[str]:
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


def bikes_from_registry() -> list[Bike]:
    """One Bike per make/model/year seen in the registry, merged into the store (manualId is kept)."""
    store = get_store()
    known = {b.id: b for b in store.bikes()}
    made: dict[str, Bike] = {}
    for e in store.registry():
        if e.type != "owner" or not e.years or not e.model or e.model == "All models":
            continue
        for year in e.years:
            bid = slug(e.make, e.model, year)
            if bid in made:
                continue
            old = known.get(bid)
            made[bid] = Bike(
                id=bid,
                make=e.make,
                model=e.model,
                year=year,
                market=e.market,
                manualId=old.manualId if old else None,
                vins=old.vins if old else None,
                cues=old.cues if old else None,
            )
    bikes = list(made.values())
    if bikes:
        store.put_bikes(bikes)
    return bikes


def _is_pdf(url: str) -> bool:
    head = url.split("?", 1)[0].split("#", 1)[0].lower()
    return head.endswith(".pdf") or any(h in url for h in DIRECT_HOSTS)


def free_owner_manuals(make: str | None = None, limit: int = 20) -> list[RegistryEntry]:
    """Free English owner's manuals the ingest pipeline can fetch directly, newest model years first."""
    entries = [
        e
        for e in get_store().registry(make=make)
        if e.type == "owner" and e.access == "free" and e.lang.lower().startswith("en") and _is_pdf(e.url)
    ]
    entries.sort(key=lambda e: (-(max(e.years) if e.years else 0), e.make.lower(), e.model.lower()))
    return entries[: max(0, limit)]
