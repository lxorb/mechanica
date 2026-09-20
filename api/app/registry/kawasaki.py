"""Kawasaki: the KTIVS publication service behind kawasaki.com. Inertia JSON, session-scoped filters.

Most rows are `is_ebook` flipbooks: the proxy serves index.html and 403s every other path inside the
package, and the CDN zip behind it holds page images, not a PDF. Those rows are still indexed (the
viewer is where the manual lives) but only the real `.pdf` files are ingestable."""

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
CATEGORIES = ("1",)


def _page(c, page: int, category: str):
    params = {"searchMode": "model", "showAll": "1", "productCategory": category, "per_page": "100", "page": str(page)}
    payload = get_json(c, API, params=params, headers=INERTIA)
    return ((payload or {}).get("props") or {}).get("pagination") or {}


def _url(doc: dict) -> str:
    """The proxy link when it really is a PDF, else the CDN file, else the flipbook viewer."""
    redirect = doc.get("redirect_url") or ""
    direct = doc.get("download_url") or ""
    if redirect.lower().endswith(".pdf"):
        return HOST + redirect if redirect.startswith("/") else redirect
    if direct.lower().endswith(".pdf"):
        return direct
    return HOST + redirect if redirect.startswith("/") else (redirect or direct)


def kawasaki() -> Iterable[RegistryEntry]:
    with client() as c:
        seen: set[str] = set()
        pdfs = 0
        for category in CATEGORIES:
            _page(c, 1, category)  # the first call only plants showAll/searchMode in the session
            first = _page(c, 1, category)
            last = int((first.get("meta") or {}).get("last_page") or 1)
            for page in range(1, last + 1):
                block = first if page == 1 else _page(c, page, category)
                for row in block.get("data") or []:
                    lang = LANG.get(str(row.get("language") or "").strip().lower(), "")
                    if not lang or not keep_lang(lang):
                        continue
                    year = str(row.get("year") or "")
                    series = str(row.get("series_name") or "").strip()
                    model = series or str(row.get("model_name") or "").strip()
                    kind = "service" if "service" in str(row.get("manual_type") or "").lower() else "owner"
                    for doc in row.get("manuals") or []:
                        url = _url(doc)
                        if not url:
                            continue
                        part = doc.get("part_number") or ""
                        eid = slug(SITE, model, year, "US", lang, kind, part)
                        if eid in seen:
                            continue
                        seen.add(eid)
                        pdfs += url.lower().endswith(".pdf")
                        note = (doc.get("description") or "").strip() or ("flipbook" if doc.get("is_ebook") else "")
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
                            title=" ".join(x for x in (year, model, row.get("manual_type") or "", note) if x),
                        )
        log.info("kawasaki: %d entries, %d of them real PDFs", len(seen), pdfs)
