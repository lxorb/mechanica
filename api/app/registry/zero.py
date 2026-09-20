"""Zero Motorcycles: the owners page is a Prismic document whose "manuals" slice lists every model
year since 2014. Both manuals are free PDFs served by Zero's LMS; one PDF usually covers a family
("s-x-my21, sr-x-my21, ds-x-my21"), so each model in the group gets its own row.

CFMoto is deliberately absent: cfmotousa.com sits behind a Cloudflare managed challenge (its PDFs
answer 403 text/html) and the EU sites drop the connection, so there is nothing to index."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_json, log, slug

CDN = "https://zero-cms-disco.cdn.prismic.io/api/v2"
SITE = "zeromotorcycles.com"
QUERY = '[[at(document.type,"owners_resources")]]'
NAMES = {"srf": "SR/F", "srs": "SR/S", "dsrx": "DSR/X", "fxe": "FXE", "fxs": "FXS", "xb": "XB", "xe": "XE"}
BIKE = re.compile(r"^([a-z]+)-[a-z0-9]+-my(\d{2})$")


def _model(code: str) -> str:
    return NAMES.get(code, code.upper())


def zero() -> Iterable[RegistryEntry]:
    with client() as c:
        root = get_json(c, CDN)
        ref = ((root or {}).get("refs") or [{}])[0].get("ref")
        if not ref:
            log.warning("zero: no prismic ref")
            return
        found = get_json(c, f"{CDN}/documents/search", params={"ref": ref, "pageSize": 100, "q": QUERY})
        results = (found or {}).get("results") or []
        seen: set[str] = set()
        for doc in results:
            for slice_ in ((doc.get("data") or {}).get("body") or []):
                if slice_.get("slice_type") != "manuals":
                    continue
                for item in slice_.get("items") or []:
                    for kind, key in (("owner", "owner_manual"), ("service", "service_manual")):
                        url = ((item.get(key) or {}).get("url") or "").strip()
                        if not url:
                            continue
                        for raw in str(item.get("bike_ids") or "").split(","):
                            hit = BIKE.match(raw.strip().lower())
                            if not hit:
                                continue
                            model, year = _model(hit.group(1)), 2000 + int(hit.group(2))
                            eid = slug(SITE, model, year, "US", "en", kind)
                            if eid in seen:
                                continue
                            seen.add(eid)
                            yield RegistryEntry(
                                id=eid,
                                make="Zero",
                                model=model,
                                years=[year],
                                market="US",
                                type=kind,
                                lang="en",
                                url=url,
                                access="free",
                                site=SITE,
                                title=f"Zero {model} {year} {'Owner' if kind == 'owner' else 'Service'} Manual",
                            )
        log.info("zero: %d entries", len(seen))
