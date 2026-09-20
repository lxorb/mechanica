"""Triumph: model names, the model years behind each name, the model code behind each model year, and
finally the documents. Owner handbooks download as PDF from /documents/{id}/pdf with no product
context; every sibling endpoint (/file, /content, /download) answers 403. Workshop manuals stay a
per-bike subscription (see service.py).

The API throttles hard (20 requests / 10 s), so this adapter is rate limited, not parallel."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import Throttle, client, get_json, keep_lang, log, slug

API = "https://api.triumphtechnicalinformation.com"
PDF = API + "/documents/{}/pdf"
SITE = "triumphtechnicalinformation.com"
HEADERS = {"Origin": "https://www.triumphtechnicalinformation.com", "Referer": "https://www.triumphtechnicalinformation.com/"}
LIMIT = Throttle(1.8)
KINDS = {"Owner Handbook": "owner", "Owner Handbook Addendum": "owner"}
MARKET = {"en-us": "US", "en-gb": "GB", "en-au": "AU", "en-in": "IN"}


def _years(c, name: str) -> list[tuple[str, str]]:
    rows = get_json(c, f"{API}/handbooks/products/model-years", params={"modelName": name}, headers=HEADERS, throttle=LIMIT)
    return [(str((r or {}).get("_id") or ""), str((r or {}).get("modelYear") or "")) for r in rows or [] if (r or {}).get("_id")]


def _code(c, model_year_id: str) -> tuple[str, str]:
    row = get_json(c, f"{API}/handbooks/product-details/{model_year_id}", headers=HEADERS, throttle=LIMIT)
    row = row if isinstance(row, dict) else {}
    return str(row.get("modelCode") or ""), str(row.get("displayName") or "")


def _docs(c, code: str, year: str) -> list[dict]:
    params = {"modelCode": code, "modelYear": year, "state": "published", "onlyValid": "true", "handbook": "true"}
    rows = get_json(c, f"{API}/handbooks/documents", params=params, headers=HEADERS, throttle=LIMIT)
    return [r for r in rows or [] if isinstance(r, dict)]


def triumph() -> Iterable[RegistryEntry]:
    with client(headers=HEADERS) as c:
        names = get_json(c, f"{API}/handbooks/products/model-names", headers=HEADERS, throttle=LIMIT)
        if not isinstance(names, list):
            log.warning("triumph: no model names")
            return
        seen: set[str] = set()
        docs_for: dict[tuple[str, str], list[dict]] = {}
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            model = name.strip()
            for my_id, year in _years(c, name):
                code, _display = _code(c, my_id)
                if not code or not year:
                    continue
                key = (code, year)
                if key not in docs_for:
                    docs_for[key] = _docs(c, code, year)
                for doc in docs_for[key]:
                    kind = KINDS.get(((doc.get("metadata") or {}).get("docType") or {}).get("systemTitle") or "")
                    lang_tag = str(doc.get("language") or "").lower()
                    lang = lang_tag.split("-")[0]
                    doc_id = str(doc.get("_id") or "")
                    if not kind or not doc_id or doc.get("format") != "application/pdf" or not keep_lang(lang):
                        continue
                    market = MARKET.get(lang_tag, "GB")
                    eid = slug(SITE, model, year, market, lang, kind, doc_id[-8:])
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Triumph",
                        model=model,
                        years=[int(year)] if year.isdigit() else [],
                        market=market,
                        type=kind,
                        lang=lang,
                        url=PDF.format(doc_id),
                        access="free",
                        site=SITE,
                        title=f"{year} {model} {doc.get('title') or 'Owner Handbook'}".strip(),
                    )
        log.info("triumph: %d entries from %d model names, %d model-year codes", len(seen), len(names), len(docs_for))
