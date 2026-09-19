"""Honda: the US Sitecore downloads API (Akamai, wants a crawler UA) and the European Motopub portal."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import GOOGLEBOT_UA, client, get_json, get_text, log, pmap, post_json, slug, years_in

US = "https://powersports.honda.com"
US_SITE = "powersports.honda.com"
MOTORCYCLE_SEGMENT = "3"
BATCH = 25

EU = "https://www.hondamotopub.com"
EU_SITE = "hondamotopub.com"
EU_REGION = "HMEE"  # the English edition of the European portal
PDF_HREF = re.compile(r'href="(https://[^"]+\.pdf)"', re.I)


def _token(c) -> str:
    payload = get_json(c, f"{US}/api/csrf/token")
    raw = (payload or {}).get("token", "") if isinstance(payload, dict) else ""
    hit = re.search(r'value="([^"]+)"', raw)
    return hit.group(1) if hit else ""


def honda_us() -> Iterable[RegistryEntry]:
    with client(ua=GOOGLEBOT_UA) as c:
        payload = get_json(c, f"{US}/api/sitecore/Downloads/GetOwnersManualFilters", params={"sc_site": "powersports"})
        result = (payload or {}).get("result") if isinstance(payload, dict) else None
        if not result:
            log.warning("honda_us: filters unavailable (Akamai?)")
            return
        wanted: list[dict] = []
        for seg in result.get("segments", []):
            if seg.get("id") != MOTORCYCLE_SEGMENT:
                continue
            for cat in seg.get("categories", []):
                for fam in cat.get("families", []):
                    for trim in fam.get("trims", []):
                        for m in trim.get("models", []):
                            wanted.append(
                                {
                                    "key": {"segment": seg["id"], "category": cat["id"], "family": fam["id"], "model": m["id"]},
                                    "family": fam.get("name") or trim.get("name") or m.get("brandLineName") or m["id"],
                                    "year": m.get("year"),
                                }
                            )
        token = _token(c)
        chunks = [wanted[i : i + BATCH] for i in range(0, len(wanted), BATCH)]

        def load(chunk: list[dict]):
            body = {"models": [m["key"] for m in chunk]}
            out = post_json(
                c,
                f"{US}/api/sitecore/Downloads/LoadOwnersManualsForTrims",
                json=body,
                headers={"__RequestVerificationToken": token, "Referer": f"{US}/owners/manuals"},
            )
            listing = ((out or {}).get("result") or {}).get("listing") or []
            return list(zip(chunk, listing))

        seen: set[str] = set()
        for pairs in pmap(load, chunks):
            for meta, block in pairs:
                trim = (block or {}).get("trimName") or f"{meta['year']} {meta['family']}"
                years = years_in(str(meta.get("year") or "")) or years_in(trim)
                model = re.sub(r"^\s*(?:19|20)\d{2}\s*", "", trim).strip() or meta["family"]
                for doc in (block or {}).get("listing", []):
                    url = (doc or {}).get("url")
                    if not url:
                        continue
                    eid = slug(US_SITE, model, years[0] if years else "", "en", "owner", url.rsplit("/", 1)[-1][:24])
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Honda",
                        model=model,
                        years=years,
                        market="US",
                        type="owner",
                        lang="en",
                        url=url,
                        access="free",
                        site=US_SITE,
                        title=doc.get("name") or trim,
                    )
        log.info("honda_us: %d entries", len(seen))


def honda_eu() -> Iterable[RegistryEntry]:
    with client() as c:
        get_text(c, EU + "/")  # the ajax endpoints answer empty without the portal cookie
        xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{EU}/{EU_REGION}"}
        models = get_json(c, f"{EU}/ajax/get_model_names/{EU_REGION}/all", headers=xhr)
        if not isinstance(models, list) or not models:
            log.warning("honda_eu: no models")
            return

        def pairs(model: str) -> list[tuple[str, str]]:
            years = get_json(c, f"{EU}/ajax/get_model_years/{EU_REGION}/{urllib.parse.quote(model)}", headers=xhr)
            return [(model, str(y)) for y in (years or []) if str(y).isdigit()]

        todo = [p for group in pmap(pairs, models) for p in group]

        def manual(pair: tuple[str, str]):
            model, year = pair
            page = f"{EU}/om/{EU_REGION}/{urllib.parse.quote(model)}/{year}"
            html = get_text(c, page, headers={"Referer": f"{EU}/{EU_REGION}"})
            hit = PDF_HREF.search(html or "")
            return (model, year, hit.group(1) if hit else page)

        seen: set[str] = set()
        for model, year, url in pmap(manual, todo):
            eid = slug(EU_SITE, model, year, "en", "owner")
            if eid in seen:
                continue
            seen.add(eid)
            yield RegistryEntry(
                id=eid,
                make="Honda",
                model=model,
                years=[int(year)],
                market="EU",
                type="owner",
                lang="en",
                url=url,
                access="free",
                site=EU_SITE,
                title=f"{model} {year} Owner's Manual",
            )
        log.info("honda_eu: %d entries", len(seen))
