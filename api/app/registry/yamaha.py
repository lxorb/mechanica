"""Yamaha: Europe publishes one JSON feed with a CDN PDF per manual; the rest of the world sits in
the global Owner's Manual Library (parts.yamaha-motor.co.jp, POST JSON), which is keyed by a
distributor base code and hands out direct PDFs back to the late nineties.

yamahapubs.com / yamaha-owners-manuals.com are deliberately not used: their eBook delivery is an
HTML viewer (and currently 404/500), never a PDF."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_json, keep_lang, log, pmap, post_json, slug

EU_API = "https://www.yamaha-motor.eu/services/api/owner-manuals"
EU_SITE = "yamaha-motor.eu"

OMB = "https://parts.yamaha-motor.co.jp/ypec_b2c/services/omb2c/"
OM_SITE = "library.ymcapps.net"
OM_HEADERS = {"Content-Type": "application/json", "Origin": "https://library.ymcapps.net", "Referer": "https://library.ymcapps.net/"}
MOTORCYCLES = "10"
ENGLISH = "02"
# base code -> market. Every English-language Yamaha distributor with a motorcycle catalogue.
BASE_CODES = {"6150": "US", "6210": "CA", "6726": "AU", "7306": "GB"}
DISPLACEMENTS = [str(i) for i in range(1, 11)]


def yamaha_eu() -> Iterable[RegistryEntry]:
    with client() as c:
        rows = get_json(c, EU_API, params={"category": "Motorcycles"})
    if not isinstance(rows, list):
        return
    seen: set[str] = set()
    for row in rows:
        url = (row or {}).get("cdnUrl")
        if not url:
            continue
        years = sorted({int(y) for y in (row.get("years") or []) if str(y).isdigit()})
        models = row.get("modelNames") or []
        codes = {(lg or {}).get("languageCode", "").lower() for lg in (row.get("languages") or [])}
        codes = {c2 for c2 in codes if c2}
        for lang in sorted(codes) or ["en"]:
            if not keep_lang(lang):
                continue
            for model in models or [row.get("manualId", "")]:
                eid = slug(EU_SITE, model, years[0] if years else "", lang, "owner", row.get("manualId", "")[:8])
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Yamaha",
                    model=str(model),
                    years=years,
                    market="EU",
                    type="owner",
                    lang=lang,
                    url=url,
                    access="free",
                    site=EU_SITE,
                    title=f"{model} {row.get('segmentName') or ''}".strip(),
                )
    log.info("yamaha_eu: %d entries", len(seen))


def _library(c, base: str, market: str, seen: set[str], published: set[tuple[str, str, str]]) -> Iterable[RegistryEntry]:
    root = post_json(c, OMB + "product_list", json={"baseCode": base, "langId": ENGLISH}, headers=OM_HEADERS)
    ctx = ((root or {}).get("userContext") or {}) if isinstance(root, dict) else {}
    if not ctx:
        log.warning("yamaha_us: base %s has no user context", base)
        return

    def names(disp: str) -> list[dict]:
        body = {"baseCode": base, "langId": ENGLISH, "productId": MOTORCYCLES, "displacementType": disp}
        out = post_json(c, OMB + "model_name_list", json=body, headers=OM_HEADERS)
        return [m for m in ((out or {}).get("modelNameDataCollection") or []) if isinstance(m, dict)]

    models: dict[tuple[str, str], dict] = {}
    for group in pmap(names, DISPLACEMENTS):
        for m in group:
            models[(m.get("modelName") or "", m.get("nickname") or "")] = m

    def manuals(model: dict) -> tuple[dict, list[dict]]:
        body = {
            "baseCode": base,
            "langId": ENGLISH,
            "productId": MOTORCYCLES,
            "calledCode": "1",
            "modelName": model.get("modelName") or "",
            "nickname": model.get("nickname") or "",
            "modelYear": "",  # every model year in one call
            "publicationLang": ENGLISH,
            "userGroupCode": ctx.get("userGroupCode") or "",
            "destination": ctx.get("destination") or "",
            "destGroupCode": ctx.get("destGroupCode") or "",
        }
        out = post_json(c, OMB + "model_list", json=body, headers=OM_HEADERS)
        return model, [r for r in ((out or {}).get("modelDataCollection") or []) if isinstance(r, dict)]

    found = 0
    for model, rows in pmap(manuals, list(models.values())):
        name = (model.get("dispModelName") or model.get("modelName") or model.get("nickname") or "").strip()
        for row in rows:
            url = (row.get("pdffileURL") or "").strip()
            year = str(row.get("modelYear") or "")
            if not url or row.get("publicationLangId") != ENGLISH:
                continue
            url = "https:" + url if url.startswith("//") else url
            key = (str(row.get("publicationNo") or url), name.lower(), year)
            if key in published:  # the same publication is shared by several distributors
                continue
            published.add(key)
            eid = slug(OM_SITE, name, year, market, "en", "owner", str(row.get("publicationNo") or "")[:16])
            if eid in seen:
                continue
            seen.add(eid)
            found += 1
            yield RegistryEntry(
                id=eid,
                make="Yamaha",
                model=name,
                years=[int(year)] if year.isdigit() else [],
                market=market,
                type="owner",
                lang="en",
                url=url,
                access="free",
                site=OM_SITE,
                title=f"{year} {row.get('dispModelName') or name} Owner's Manual ({row.get('litNo') or row.get('publicationNo')})".strip(),
            )
    log.info("yamaha_us %s: %d models, %d manuals", market, len(models), found)


def yamaha_us() -> Iterable[RegistryEntry]:
    """The global OM library, one pass per English-speaking distributor."""
    with client(ua=BROWSER_UA) as c:
        seen: set[str] = set()
        published: set[tuple[str, str, str]] = set()
        for base, market in BASE_CODES.items():
            yield from _library(c, base, market, seen, published)
