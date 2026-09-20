"""General Motors North America: Chevrolet, GMC, Buick, Cadillac, Hummer, Pontiac, Oldsmobile, Saturn.

One Solr core holds the whole owner-literature library and it is open to anyone (checked 2026-09-20):

    https://contentdelivery.ext.gm.com/bypass/gma-search-api/searchapi/solr/gma-public/select

The URL is not guessed. `chevrolet.com/support/vehicle/manuals-guides` renders a
`<gma-cs-mmy-selector-v3 solrAPI="...">` element; its bundle
(`contentdelivery.ext.gm.com/.../gma-cs-mmy-selector-v3.js`) queries that core with
`fq=channel:*MANUALS*&fq=source:aem&fq=file_type:application/pdf` and uses the `path` field verbatim
as the download href. So `source:aem` is exactly the set GM itself hands out, and `path` is already a
direct `contentdelivery.ext.gm.com/content/dam/cope/...pdf` link - no token, no cookie, no login.

20,609 documents, of which 5,914 are AEM PDFs; 4,144 of those are in an English locale, covering model
years 1993-2027. `category_key` carries the year, the make and one entry per model the file covers
(a Tahoe/Suburban manual is filed under both), so one PDF legitimately becomes several rows.

Gotchas:
  * The bypass proxy 403s our normal crawler UA and 500s on `sort=`, so this sends a browser UA and
    pages with plain `start`/`rows`.
  * `fl=` is not optional: every document carries its full extracted text, so an unfiltered page of
    500 rows is ~300 MB.
  * The other 11k rows are `source:inquira-live`, whose `path` is an internal staging path on a host
    that does not resolve outside GM. Checked, not reachable, left alone.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_json, keep_lang, log, slug

SITE = "contentdelivery.ext.gm.com"
SOLR = "https://contentdelivery.ext.gm.com/bypass/gma-search-api/searchapi/solr/gma-public/select"
FIELDS = "id,path,source,channel,locale,file_type,category_key,category_translated,title_en,title_ordered"
PAGE = 500

# The picker's own brand list, plus Holden: GM Australia's manuals sit in the same core under en_AU.
MAKES = {
    "CHEVROLET": "Chevrolet",
    "GMC": "GMC",
    "BUICK": "Buick",
    "CADILLAC": "Cadillac",
    "HUMMER": "Hummer",
    "PONTIAC": "Pontiac",
    "OLDSMOBILE": "Oldsmobile",
    "SATURN": "Saturn",
    "BRIGHTDROP": "BrightDrop",
    "HOLDEN": "Holden",
}
# Owner's manual and vehicle-reference channels only. Quick-reference, warranty and infotainment
# guides are real PDFs but not the handbook, and letting them in would let one outrank it.
CHANNELS = {"OWNERS_MANUALS_BROWSE", "USER_MANUALS_BROWSE"}
MARKET = {"en_US": "US", "en_CA": "CA", "en_AU": "AU", "en_GB": "GB"}
# Category keys that are neither a year, a make nor a model: advisor groups, infotainment systems,
# folder names. Anything here would otherwise be emitted as if it were a car.
NOISE = {
    "CAC",
    "CAC_ADVISOR",
    "DOCUMENTS",
    "CANADA_MODELS",
    "WARRANTY_MANUAL",
    "OWNERS_MANUALS_BROWSE",
    "USER_MANUALS_BROWSE",
    "QUICK_REFERENCE_MANUALS_BROWSE",
    "WARRANTY_MANUALS_BROWSE",
    "INFOTAINMENT_MANUALS_BROWSE",
    "ORDER_REFERENCE_GUIDE_MANUALS_BROWSE",
    "MANUALS",
}
NOISE.update({"SAFETY", "CRUISE", "SUPER_CRUISE", "AV", "NAV", "GL_GLX", "GL GLX", "DIESEL", "HYBRID", "ELECTRIC"})
NOISE_WORDS = ("MYLINK", "INTELLILINK", "CUE", "ONSTAR", "NAVIGATION", "ADVISOR", "-NAV")


def _is_year(key: str) -> bool:
    return key.isdigit() and 1980 < int(key) < 2035


def _model(key: str, name: str) -> str | None:
    up = key.upper()
    if up in NOISE or up in MAKES or _is_year(up) or any(w in up for w in NOISE_WORDS):
        return None
    pretty = (name or key).replace("_", " ").split("(")[0].strip()
    return pretty if 2 <= len(pretty) <= 40 else None


def _docs() -> Iterable[dict]:
    """Every document in the core, 500 at a time. Browser UA: the bypass proxy 403s anything else."""
    throttle = Throttle(2.0)
    start, total = 0, 1
    with client(ua=BROWSER_UA) as c:
        while start < total:
            throttle.wait()
            payload = get_json(c, SOLR, params={"q": "*:*", "rows": PAGE, "start": start, "fl": FIELDS})
            body = (payload or {}).get("response") or {}
            docs = body.get("docs") or []
            if not docs:
                return
            total = int(body.get("numFound") or 0)
            yield from docs
            start += PAGE


def rows() -> Iterable[RegistryEntry]:
    seen: set[str] = set()
    kept = 0
    for doc in _docs():
        url = str(doc.get("path") or "")
        locale = str(doc.get("locale") or "")
        if doc.get("source") != "aem" or doc.get("file_type") != "application/pdf" or not url.startswith("http"):
            continue
        if doc.get("channel") not in CHANNELS or not locale.startswith("en"):
            continue
        keys = doc.get("category_key") or []
        names = doc.get("category_translated") or []
        names = list(names) + [""] * (len(keys) - len(names))
        make = next((MAKES[k.upper()] for k in keys if k.upper() in MAKES), None)
        years = sorted({int(k) for k in keys if _is_year(str(k))})
        models = [m for m in (_model(str(k), str(n)) for k, n in zip(keys, names)) if m]
        lang = locale.split("_")[0].lower()
        if not make or not years or not models or not keep_lang(lang):
            continue
        title = str(doc.get("title_en") or doc.get("title_ordered") or "").strip()
        market = MARKET.get(locale, locale.split("_")[-1].upper())
        for model in models:
            eid = slug(SITE, make, model, years[0], market, lang, "owner", url.rsplit("/", 1)[-1][:60])
            if eid in seen:
                continue
            seen.add(eid)
            kept += 1
            yield RegistryEntry(
                id=eid,
                make=make,
                model=model,
                years=years,
                market=market,
                type="owner",
                lang=lang,
                url=url,
                access="free",
                site=SITE,
                title=title or f"{years[0]} {make} {model} Owner Manual",
                needsUa="browser",  # the CDN 403s our crawler UA on the PDFs too, not only on the API
                kind="car",
            )
    log.info("gm: %d rows", kept)
