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

import re
from collections import Counter
from collections.abc import Iterable
from typing import NamedTuple

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
# The handbook channel and nothing else. Quick-reference, warranty, infotainment and vehicle-reference
# files are real PDFs on the same model year, and `pdf_index()` has no way to rank them below the
# manual, so letting one in means a rider sometimes opens a 20-page booklet instead of the manual.
CHANNELS = {"OWNERS_MANUALS_BROWSE"}
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
NOISE.update({"FUEL", "COMMERCIAL", "OWNER'S-MANUAL", "OWNERS-MANUAL", "INFOTAINMENT_SYSTEM"})
NOISE_WORDS = ("MYLINK", "INTELLILINK", "CUE", "ONSTAR", "NAVIGATION", "ADVISOR", "-NAV", "INFOTAINMENT", "CRUISE")


def _is_year(key: str) -> bool:
    return key.isdigit() and 1980 < int(key) < 2035


# GM names its files `<yy>_<BRAND>_<Model>_OM_...pdf`. MUL means the file covers several brands.
FILE_BRAND = {
    "CHEV": "Chevrolet",
    "CHEVY": "Chevrolet",
    "CAD": "Cadillac",
    "GMC": "GMC",
    "BUICK": "Buick",
    "BUI": "Buick",
    "PONT": "Pontiac",
    "OLDS": "Oldsmobile",
    "SAT": "Saturn",
    "HUM": "Hummer",
    "HOL": "Holden",
}


MAX_MAKES = 2  # a Tahoe/Yukon manual is shared by two brands; anything wider is a fleet-wide insert
# Inserts and supplements filed in the handbook channel. They are real PDFs for the same model years,
# so one would otherwise be offered as if it were the manual.
SKIP_TITLE = re.compile(r"\b(supplement|supplemental|insert|warranty information|addendum|information for)\b", re.I)


def _makes(keys: list[str], title: str, url: str) -> list[str]:
    """Which brand(s) this file belongs to. `category_key` alone is not enough: a Tahoe/Yukon manual
    lists CHEVROLET and GMC, so picking the first would file a Corvette under Buick. The title names
    one brand and the file name carries a brand code; both are believed before the category list, and
    a document claiming more than two brands is a fleet-wide insert, not anybody's handbook."""
    found = list(dict.fromkeys(MAKES[k.upper()] for k in keys if k.upper() in MAKES))
    # "2027 Cadillac Escalade …" names one; "2006 Chevrolet Silverado and GMC Sierra …" names two and
    # both are real - _pairs() decides which model goes with which.
    named = [make for make in found if re.search(rf"\b{re.escape(make)}\b", title, re.I)]
    if named:
        return named
    code = url.rsplit("/", 1)[-1].split("_")
    brand = FILE_BRAND.get(code[1].upper()) if len(code) > 1 else None
    if brand and brand in found:
        return [brand]
    return found if len(found) <= MAX_MAKES else []


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


class _Doc(NamedTuple):
    url: str
    title: str
    lang: str
    market: str
    years: list[int]
    makes: list[str]
    models: list[str]


def _parse(doc: dict) -> _Doc | None:
    url = str(doc.get("path") or "")
    locale = str(doc.get("locale") or "")
    if doc.get("source") != "aem" or doc.get("file_type") != "application/pdf" or not url.startswith("http"):
        return None
    if doc.get("channel") not in CHANNELS or not locale.startswith("en"):
        return None
    title = str(doc.get("title_en") or doc.get("title_ordered") or "").strip()
    if SKIP_TITLE.search(title):
        return None
    keys = [str(k) for k in doc.get("category_key") or []]
    names = [str(n) for n in doc.get("category_translated") or []]
    names += [""] * (len(keys) - len(names))
    lang = locale.split("_")[0].lower()
    makes = _makes(keys, title, url)
    years = sorted({int(k) for k in keys if _is_year(k)})
    models = list(dict.fromkeys(m for m in (_model(k, n) for k, n in zip(keys, names)) if m))
    if not makes or not years or not models or not keep_lang(lang):
        return None
    return _Doc(url, title, lang, MARKET.get(locale, locale.split("_")[-1].upper()), years, makes, models)


def _divisions(docs: list[_Doc]) -> dict[str, str]:
    """model -> the division that actually sells it, learned from the files that name one brand.

    GM shares a manual across two divisions (Silverado/Sierra, Tahoe/Yukon) and files it under both
    makes and both models, so pairing every make with every model invents a Chevrolet Sierra. The
    2,087 single-brand files settle each model on their own, no hand-kept table needed."""
    votes: dict[str, Counter[str]] = {}
    for doc in docs:
        if len(doc.makes) != 1:
            continue
        for model in doc.models:
            votes.setdefault(model.lower(), Counter())[doc.makes[0]] += 1
    return {model: tally.most_common(1)[0][0] for model, tally in votes.items()}


def _pairs(doc: _Doc, division: dict[str, str]) -> list[tuple[str, str]]:
    """make/model pairs this document should produce. A shared file usually spells the pairing out in
    its own title ("2006 Chevrolet Silverado and GMC Sierra Owner Manual"), which is believed first;
    otherwise the division learned from the single-brand files decides; only when neither knows does
    the model go out under every brand on the file."""
    out: list[tuple[str, str]] = []
    for model in doc.models:
        named = [mk for mk in doc.makes if re.search(rf"\b{re.escape(mk)}\b[\s/-]{{0,3}}{re.escape(model)}\b", doc.title, re.I)]
        owner = division.get(model.lower())
        if named:
            out += [(named[0], model)]
        elif owner:
            # The division is known. If it is not on this file, the model is cross-filed here (a
            # Silverado manual whose categories also list SIERRA) and this file is not its manual.
            out += [(owner, model)] if owner in doc.makes else []
        else:
            out += [(mk, model) for mk in doc.makes]
    return out


def rows() -> Iterable[RegistryEntry]:
    docs = [d for d in (_parse(raw) for raw in _docs()) if d]
    division = _divisions(docs)
    seen: set[str] = set()
    kept = 0
    for doc in docs:
        url, title, lang, market, years = doc.url, doc.title, doc.lang, doc.market, doc.years
        for make, model in _pairs(doc, division):
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
