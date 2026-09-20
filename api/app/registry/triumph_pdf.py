"""Triumph, the whole handbook shelf. `triumph.py` walks the 304 names the picker offers and keeps
English; this walks the product table itself and keeps every language and every free document type.

What the viewer actually does (checked 2026-09-20 against api.triumphtechnicalinformation.com):

* `GET /handbooks/products/model-years` **with no modelName** returns the entire product table -
  1,076 model-year records, ids only. That is the real root of the catalogue, so nothing that is
  missing from the model-name picker can be missed here.
* `GET /handbooks/product-details/{modelYearId}` -> `{modelCode, modelName, modelYear, displayName}`.
* `GET /handbooks/documents?modelCode&modelYear&state=published&onlyValid=true&handbook=true` -> the
  documents for that one model year. Drop `state`/`onlyValid` and the filter collapses: the API then
  answers with all 13,901 documents it holds, which is how the doc-type census below was taken.
* `GET /documents/{id}/pdf` -> the file. `/file`, `/content` and `/download` answer 403 and the bare
  `/documents/{id}` answers JSON metadata, so `/pdf` is the only way in - and it needs no session.

Only three of the fifteen PDF doc types come out without a subscription; the other twelve answer 404
on `/pdf` (sampled one of each):

    Owner Handbook 1043  ok      Circuit Diagrams 1604  404     Service Manual 175  404
    Owner Handbook Addendum 66  ok      Recall 757  404         Technical Bulletin 655  404
    Connectivity Guide 22  ok           Service Bulletin 755  404    ... and the rest 404

Ids are deliberately byte-identical to `triumph.py`'s for the rows both produce, so the store's
id-keyed merge folds them together instead of listing the same handbook twice.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from typing import Any

from ..models import RegistryEntry
from ._http import Throttle, client, get_json, keep_lang, log, slug

API = "https://api.triumphtechnicalinformation.com"
PDF = API + "/documents/{}/pdf"
SITE = "triumphtechnicalinformation.com"
HEADERS = {"Origin": "https://www.triumphtechnicalinformation.com", "Referer": "https://www.triumphtechnicalinformation.com/"}
# The API allows 20 requests / 10 s. 1.8/s rides the edge of that window and loses ~15% of the walk
# to 429s that outlive _http's three short retries; 1.2/s plus the long cool-down below loses none.
LIMIT = Throttle(float(os.getenv("TRIUMPH_RATE", "1.2")))
COOLDOWN = 8.0  # longer than the portal's own 10 s window, so a 429 streak clears before we retry
PATIENCE = 4
# doc type -> registry type. Everything else on this portal needs the GBP 5.99/month bike subscription.
KINDS = {"Owner Handbook": "owner", "Owner Handbook Addendum": "owner", "Connectivity Guide": "owner"}
DOC_PARAMS = {"state": "published", "onlyValid": "true", "handbook": "true"}
# triumph.py's mapping, kept so the shared rows collide; every other tag falls back to its own region.
MARKET = {"en-us": "US", "en-gb": "GB", "en-au": "AU", "en-in": "IN"}


def _json(c, url: str, **kw: Any) -> Any:
    """get_json, but a rate-limited miss waits out the portal's whole window instead of 0.5 s."""
    for attempt in range(PATIENCE):
        got = get_json(c, url, headers=HEADERS, throttle=LIMIT, **kw)
        if got is not None:
            return got
        if attempt < PATIENCE - 1:
            time.sleep(COOLDOWN)
    log.warning("triumph_pdf: gave up on %s", url[:120])
    return None


def _market(tag: str) -> str:
    if tag in MARKET:
        return MARKET[tag]
    region = tag.split("-")[-1].upper()
    return region if len(region) == 2 and region.isalpha() else "GB"


def _catalog(c) -> list[str]:
    """Every model-year id Triumph publishes, straight from the product table."""
    rows = _json(c, f"{API}/handbooks/products/model-years")
    return [str((r or {}).get("_id")) for r in rows or [] if isinstance(r, dict) and r.get("_id")]


def _product(c, model_year_id: str) -> tuple[str, str, str] | None:
    row = _json(c, f"{API}/handbooks/product-details/{model_year_id}")
    if not isinstance(row, dict):
        return None
    code = str(row.get("modelCode") or "").strip()
    name = str(row.get("displayName") or row.get("modelName") or "").strip()
    year = str(row.get("modelYear") or "").strip()
    return (code, name, year) if code and name and year.isdigit() else None


def _docs(c, code: str, year: str) -> list[dict]:
    params = {"modelCode": code, "modelYear": year, **DOC_PARAMS}
    rows = _json(c, f"{API}/handbooks/documents", params=params)
    return [r for r in rows or [] if isinstance(r, dict)]


def rows() -> Iterable[RegistryEntry]:
    with client(headers=HEADERS) as c:
        ids = _catalog(c)
        if not ids:
            log.warning("triumph_pdf: empty product table")
            return
        products: list[tuple[str, str, str]] = []
        for mid in ids:
            got = _product(c, mid)
            if got:
                products.append(got)
        log.info("triumph_pdf: %d model years, %d resolved to a model code", len(ids), len(products))

        cache: dict[tuple[str, str], list[dict]] = {}
        seen: set[str] = set()
        for code, name, year in products:
            key = (code, year)
            if key not in cache:
                cache[key] = _docs(c, code, year)
            for doc in cache[key]:
                kind = KINDS.get(((doc.get("metadata") or {}).get("docType") or {}).get("systemTitle") or "")
                doc_id = str(doc.get("_id") or "")
                tag = str(doc.get("language") or "").lower()
                lang = tag.split("-")[0]
                if not kind or not doc_id or doc.get("format") != "application/pdf" or not lang or not keep_lang(lang):
                    continue
                market = _market(tag)
                eid = slug(SITE, name, year, market, lang, kind, doc_id[-8:])
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Triumph",
                    model=name,
                    years=[int(year)],
                    market=market,
                    type=kind,
                    lang=lang,
                    url=PDF.format(doc_id),
                    access="free",
                    site=SITE,
                    title=f"{year} {name} {doc.get('title') or 'Owner Handbook'}".strip(),
                )
        log.info("triumph_pdf: %d entries over %d model-year/code pairs", len(seen), len(cache))
