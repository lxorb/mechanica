"""Kawasaki: the KTIVS publication service behind kawasaki.com. Inertia JSON, session-scoped filters."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_json, keep_lang, log, slug

API = "https://pws.ktivs.net/manuals"
HOST = "https://pws.ktivs.net"
SITE = "kawasaki.com"
# no Accept: application/json here - that routes the request to the API guard and answers 401.
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "6abeec43027f0163af2754f52f2d8af8"}
LANG = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it", "dutch": "nl", "portuguese": "pt"}


def _page(c, page: int):
    params = {"searchMode": "model", "showAll": "1", "productCategory": "1", "per_page": "100", "page": str(page)}
    payload = get_json(c, API, params=params, headers=INERTIA)
    return ((payload or {}).get("props") or {}).get("pagination") or {}


def kawasaki() -> Iterable[RegistryEntry]:
    with client() as c:
        _page(c, 1)  # the first call only plants showAll/searchMode in the session; the second answers
        first = _page(c, 1)
        last = int((first.get("meta") or {}).get("last_page") or 1)
        seen: set[str] = set()
        for page in range(1, last + 1):
            block = first if page == 1 else _page(c, page)
            for row in block.get("data") or []:
                lang = LANG.get(str(row.get("language") or "").strip().lower(), "")
                if not lang or not keep_lang(lang):
                    continue
                year = str(row.get("year") or "")
                series = str(row.get("series_name") or "").strip()
                model = series or str(row.get("model_name") or "").strip()
                kind = "service" if "service" in str(row.get("manual_type") or "").lower() else "owner"
                for doc in row.get("manuals") or []:
                    url = doc.get("redirect_url")
                    url = HOST + url if url and url.startswith("/") else (doc.get("download_url") or "")
                    if not url:
                        continue
                    eid = slug(SITE, model, year, "US", lang, kind, doc.get("part_number") or "")
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Kawasaki",
                        model=model,
                        years=[int(year)] if year.isdigit() else [],
                        market="US",
                        type=kind,
                        lang=lang,
                        url=url,
                        access="free",
                        site=SITE,
                        title=f"{year} {model} {row.get('manual_type') or ''}".strip(),
                    )
        log.info("kawasaki: %d entries over %d pages", len(seen), last)
