"""The merged parts catalogue as plain rows, for api/app/offers.py.

`offers.resolve()` reaches for `app.parts.catalog` by name to answer "what is part X of manual Y"
for an id that is not one of the manual's own printed parts - a standard catalogue row such as
`m-fork-seals`, which the manual never printed a spec for but the bike certainly has. Every row
carries a `searchHint`: what to append to make/model/year to make the shop query fitment-exact.

The real work lives in api/app/parts_catalog.py. This module is the thin, import-light adapter so
that importing it (and with it the `app.parts` package identify uses) costs nothing until called.
"""

from __future__ import annotations


def catalog(manual_id: str, bike_id: str | None = None) -> list[dict]:
    """Every part this bike takes, as dicts: id, name, spec, page, oem, links, searchHint, group,
    icon, standard, mentions. Empty list when the manual is unknown - never raises at the caller."""
    from .. import parts_catalog
    from ..store import get_store

    store = get_store()
    bike = store.bike(bike_id) if bike_id else None
    try:
        result = parts_catalog.catalog(manual_id, bike, store=store)
    except ValueError:
        return []
    return [row.model_dump() for row in result.parts]


# offers.py tries `parts`, `catalog` then `rows`; all three mean the same thing here.
parts = catalog
rows = catalog
