"""India, after india.py — which in the end is a standby, not a source.

**Yamaha India** is the one Indian portal this pass found that india.py misses: base code `6C97`
(`destination: IND`) of Yamaha's Owner's Manual Library (parts.yamaha-motor.co.jp, POST JSON), four
calls deep — product list -> model names per displacement class -> model years -> the manual, a
direct PDF on library.ymcapps.net. 197 rows, all verified as PDFs. Then `yamaha_intl.py` landed
mid-flight with the same base code in its `BASES` table, so emitting them here would file the same
documents twice under different ids. `yamaha_india()` therefore checks for that module first and
stands down; it fills in only if the wider walk ever stops covering India.

Every other Indian maker is either already indexed or publishes nothing fetchable:
  * Hero, TVS, Bajaj — india.py. Royal Enfield — royalenfield.py. KTM India — pierer.py ships the
    same PDFs. Honda 2Wheelers India — honda_intl.py reaches it as motopub code `HMSI`; the
    honda2wheelersindia.com page itself is Sitecore XM Cloud that fetches its list client-side per
    model year and frame number, with nothing public to enumerate.
  * Suzuki India — suzukimotorcycle.co.in answers 403 on its sitemap and links no manual anywhere.
  * Jawa and Yezdi — Cloudflare 403 on every path, browser and Googlebot UA alike.
  * Ather, Ola, Revolt, Ultraviolette, Vida — the manual is inside the phone app; no PDF on the web.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, log, pmap, post_json, slug, years_in

OMB = "https://parts.yamaha-motor.co.jp/ypec_b2c/services/omb2c/"
OM_SITE = "library.ymcapps.net"
OM_HEADERS = {"Content-Type": "application/json", "Origin": "https://library.ymcapps.net", "Referer": "https://library.ymcapps.net/"}
INDIA = {"baseCode": "6C97", "langId": "02"}  # the Indian distributor, UI language English
MOTORCYCLES = "10"
ENGLISH = "02"
DISPLACEMENTS = [str(i) for i in range(1, 11)]


throttle = Throttle(2.0)


def _clean(name: str) -> str:
    return re.sub(r"\s{2,}", " ", re.sub(r"[_\s]+", " ", str(name or ""))).strip()


def _owned_by_yamaha_intl() -> bool:
    """yamaha_intl.py (another agent, landed mid-flight) walks the same library by base code. If it
    already lists India, these rows would be the same PDFs under different ids, so stand down."""
    try:
        from . import yamaha_intl
    except Exception:
        return False
    return "6C97" in getattr(yamaha_intl, "BASES", {})


def yamaha_india() -> Iterator[RegistryEntry]:
    if _owned_by_yamaha_intl():
        log.info("yamaha-india: skipped, yamaha_intl.py already covers base 6C97")
        return
    with client(ua=BROWSER_UA, headers=OM_HEADERS) as c:
        root = post_json(c, OMB + "product_list/", throttle=throttle, json=INDIA)
        context = (root or {}).get("userContext") or {}
        if not context:
            log.warning("yamaha-india: no user context")
            return
        models: dict[tuple[str, str], str] = {}
        for disp in DISPLACEMENTS:
            body = {"productId": MOTORCYCLES, "displacementType": disp, **INDIA}
            found = post_json(c, OMB + "model_name_list/", throttle=throttle, json=body) or {}
            for row in found.get("modelNameDataCollection") or []:
                models[(str(row.get("modelName") or ""), str(row.get("nickname") or ""))] = str(row.get("dispModelName") or "")
        log.info("yamaha-india: %d models", len(models))

        def years_of(key: tuple[str, str]) -> tuple[tuple[str, str], list[str]]:
            body = {
                "productId": MOTORCYCLES,
                "modelName": key[0],
                "nickname": key[1],
                "userGroupCode": context.get("userGroupCode"),
                "destination": context.get("destination"),
                "destGroupCode": context.get("destGroupCode"),
                **INDIA,
            }
            found = post_json(c, OMB + "model_year_list/", throttle=throttle, json=body) or {}
            return key, [str(y.get("modelYear")) for y in found.get("modelYearDataCollection") or [] if y.get("modelYear")]

        jobs: list[tuple[tuple[str, str], str]] = []
        for key, found in pmap(years_of, list(models)):
            jobs += [(key, year) for year in found]

        def manuals(job: tuple[tuple[str, str], str]) -> tuple[tuple[tuple[str, str], str], list[dict[str, Any]]]:
            key, year = job
            body = {
                "productId": MOTORCYCLES,
                "calledCode": "1",
                "modelName": key[0],
                "nickname": key[1],
                "modelYear": year,
                "publicationLang": ENGLISH,
                **context,
                **INDIA,
            }
            found = post_json(c, OMB + "model_list/", throttle=throttle, json=body) or {}
            return job, [d for d in (found.get("modelDataCollection") or []) if isinstance(d, dict)]

        seen: set[str] = set()
        for (key, year), docs in pmap(manuals, jobs):
            for doc in docs:
                url = str(doc.get("pdffileURL") or "").strip()
                if not url:
                    continue
                if url.startswith("//"):
                    url = "https:" + url
                model = _clean(models.get(key) or doc.get("dispModelName") or key[1] or key[0])
                model = re.sub(r"\s*-\s*[A-Z0-9]+$", "", model).strip() or model
                years = years_in(year)
                eid = slug(OM_SITE, "Yamaha", model, years[0] if years else "", "en", "owner")
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Yamaha",
                    model=model,
                    years=years,
                    market="IN",
                    type="owner",
                    lang="en",
                    url=url,
                    access="free",
                    site=OM_SITE,
                    title=f"Yamaha {_clean(doc.get('dispModelName') or model)} {year} Owner's Manual",
                )
        log.info("yamaha-india: %d entries from %d model years", len(seen), len(jobs))



def rows() -> Iterable[RegistryEntry]:
    yield from yamaha_india()
