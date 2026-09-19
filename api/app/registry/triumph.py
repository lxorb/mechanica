"""Triumph: model names, then the model years behind each name. Handbooks are free in the online
viewer; workshop manuals are a per-bike subscription (see service.py).

The API throttles hard (20 requests / 10 s), so this adapter is rate limited, not parallel."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import Throttle, client, get_json, log, slug

API = "https://api.triumphtechnicalinformation.com"
VIEWER = "https://www.triumphtechnicalinformation.com/handbooks/{}"
SITE = "triumphtechnicalinformation.com"
LIMIT = Throttle(1.8)


def triumph() -> Iterable[RegistryEntry]:
    with client() as c:
        names = get_json(c, f"{API}/handbooks/products/model-names", throttle=LIMIT)
        if not isinstance(names, list):
            log.warning("triumph: no model names")
            return
        seen: set[str] = set()
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            rows = get_json(c, f"{API}/handbooks/products/model-years", params={"modelName": name}, throttle=LIMIT)
            for row in rows or []:
                year = str((row or {}).get("modelYear") or "")
                pid = (row or {}).get("_id")
                if not pid:
                    continue
                eid = slug(SITE, name, year, "GB", "en", "owner")
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Triumph",
                    model=name.strip(),
                    years=[int(year)] if year.isdigit() else [],
                    market="GB",
                    type="owner",
                    lang="en",
                    url=VIEWER.format(pid),
                    access="free",
                    site=SITE,
                    title=f"{year} {name} Owner's Handbook".strip(),
                )
        log.info("triumph: %d entries from %d model names", len(seen), len(names))
