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
