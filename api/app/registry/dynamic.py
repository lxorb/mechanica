"""Dynamic manual resolvers for OEM portals that only hand out a manual per VIN or per live lookup.

Owner of this file: registry agents (append RESOLVERS entries; keep the signature).
Called by app.ondemand.ensure(bike_id, vin) when the catalog/registry has no static PDF for the bike.
A resolver returns a RegistryEntry with a direct, fetchable PDF url (access "free") or None.
Keys are lowercase make names. Must be fast (< 10 s), polite (UA, timeouts) and never raise.
"""

from collections.abc import Callable

from ..models import Bike, RegistryEntry

RESOLVERS: dict[str, Callable[[Bike, str | None], RegistryEntry | None]] = {}


def resolve(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    fn = RESOLVERS.get(bike.make.lower())
    if not fn:
        return None
    try:
        return fn(bike, vin)
    except Exception:
        return None


# --- registry agent R1 ---------------------------------------------------------------------------
# Two portals hand out nothing without a chassis number, so neither can be crawled into the registry:
#   Suzuki GB  bikes.suzuki.co.uk  -> HandbookLocator/GetHandbook?vin=, no model index exists at all.
#   Kawasaki   pws.ktivs.net       -> POST /vin-search, open to guests, and the one way to reach a
#                                     manual the U.S. guest catalogue does not carry.
# Imported lazily: a resolver must never take the package down if its portal's module changes.


def _suzuki(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    from .suzuki_intl import resolve_uk

    return resolve_uk(bike, vin)


def _kawasaki(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    from .kawasaki_pdf import resolve_vin

    return resolve_vin(bike, vin)


RESOLVERS.setdefault("suzuki", _suzuki)
RESOLVERS.setdefault("kawasaki", _kawasaki)


# --- registry agent R3 ---------------------------------------------------------------------------
# Indian, Victory and Can-Am are crawlable (see americas.py), so these resolvers exist only for the
# gap between the catalog's spelling of a model and the portal's: polaris.com answers per model year
# and BRP per model page, both without a VIN, so a miss costs a handful of requests and no login.


def _polaris(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    from .americas import resolve_polaris

    return resolve_polaris(bike, vin)


def _brp(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    from .americas import resolve_brp

    return resolve_brp(bike, vin)


RESOLVERS.setdefault("indian", _polaris)
RESOLVERS.setdefault("victory", _polaris)
RESOLVERS.setdefault("can-am", _brp)
