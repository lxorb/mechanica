"""Kawasaki: the rows of the KTIVS catalogue that are really downloadable PDFs, proved one by one.

`kawasaki.py` indexes all 1,262 KTIVS rows, flipbooks included, because the viewer is where those
manuals live. This module indexes only what `/ingest` can actually fetch: every file whose bytes
come back `%PDF-` from `pws.ktivs.net/proxy/...`, checked with a ranged GET at crawl time rather
than inferred from the extension. 60 of the ~1,328 files qualify - the `99814-*-tws-*.pdf` owner's
manuals for the newest model years and the `99888-*` specification sheets (kept, and labelled,
because `_supplement()` in the package ranks them below a real handbook). The `99803-*` family is
*not* a second PDF family: every one of them is an `_ebook.zip`. Everything else is `is_ebook` too.

Why the flipbooks cannot be turned into PDFs, so this is not re-attempted:
  * the package *does* contain per-page PDFs (the viewer template links `{bookpath}pdf/{page}.pdf`),
    but the proxy serves only `html5/` and `flipper3js/` assets and answers 403 for `pdf/`,
    `html5/data/` and the ebook `.zip` itself, with or without a session cookie and Referer;
  * the `download_url` bucket (`khi-new.sgp1.[cdn.]digitaloceanspaces.com`) is private - the
    non-CDN name answers 403 and the `cdn.` name does not resolve - so the zip is not reachable
    around the proxy either;
  * `/download/{id}` and `/stream-file/{id}` are dealer routes and answer 500/404 for a guest.

Region: a KTIVS guest is pinned to the U.S.A. (`country_id` 24, territory 15). The country comes
from the guest record, not the request - `countryRegion`/`country` query parameters are ignored,
and Accept-Language, X-Forwarded-For and CF-IPCountry change nothing; only the dealer login form
takes a country. kawasaki.eu, kawasaki.com.au, kawasaki.ca, kawasaki-india.com and
kawasaki-motors.com all link to this same `pws.ktivs.net`, and none of them hosts a manual file, so
the U.S. catalogue is the whole reachable set. `resolve_vin` below is the way to a non-US manual:
`POST /vin-search` is open to guests and answers per chassis number.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from typing import Any

import httpx

from ..models import Bike, RegistryEntry
from ._http import Throttle, client, get_json, log, pmap, post_json, request, slug

HOST = "https://pws.ktivs.net"
API = f"{HOST}/manuals"
SITE = "pws.ktivs.net"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "6abeec43027f0163af2754f52f2d8af8"}
MOTORCYCLE = "1"
PER_PAGE = "100"
THROTTLE = Throttle(2.0)
LANGS = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it", "dutch": "nl", "portuguese": "pt"}


def _page(c: httpx.Client, page: int) -> dict[str, Any]:
    params = {"searchMode": "model", "showAll": "1", "productCategory": MOTORCYCLE, "per_page": PER_PAGE, "page": str(page)}
    payload = get_json(c, API, params=params, headers=INERTIA, throttle=THROTTLE)
    block = ((payload or {}).get("props") or {}).get("pagination") or {}
    return block if isinstance(block, dict) else {}


def _proxy(doc: dict) -> str | None:
    """The proxy URL for a file that claims to be a PDF. The CDN behind it is not public."""
    for raw in (doc.get("redirect_url") or "", doc.get("download_url") or ""):
        head = raw.split("?", 1)[0].lower()
        if head.endswith(".pdf"):
            return HOST + raw if raw.startswith("/") else raw
    return None


def _is_pdf(c: httpx.Client, url: str) -> bool:
    r = request(c, "GET", url, throttle=THROTTLE, headers={"Range": "bytes=0-1023", "Accept-Encoding": "identity"})
    if r is None:
        return False
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    return r.content[:5] == b"%PDF-" or ctype == "application/pdf"


def rows() -> Iterable[RegistryEntry]:
    with client() as c:
        _page(c, 1)  # the first call only plants showAll/searchMode in the guest session
        first = _page(c, 1)
        last = int((first.get("meta") or {}).get("last_page") or 1)
        found: list[tuple[dict, dict, str]] = []
        for page in range(1, last + 1):
            block = first if page == 1 else _page(c, page)
            for row in block.get("data") or []:
                for doc in row.get("manuals") or []:
                    url = _proxy(doc)
                    if url:
                        found.append((row, doc, url))

        checked = {url: ok for url, ok in pmap(lambda u: (u, _is_pdf(c, u)), sorted({u for _r, _d, u in found}))}
        seen: set[str] = set()
        for row, doc, url in found:
            if not checked.get(url):
                continue
            lang = LANGS.get(str(doc.get("language") or row.get("language") or "").strip().lower(), "en")
            year = str(row.get("year") or "").strip()[:4]
            model = str(row.get("series_name") or row.get("model_name") or "").strip()
            kind = "service" if "service" in str(row.get("manual_type") or "").lower() else "owner"
            part = str(doc.get("part_number") or "")
            eid = slug(SITE, model, year, "US", lang, kind, part)
            if not model or eid in seen:
                continue
            seen.add(eid)
            note = (doc.get("description") or "").strip()
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
                title=" ".join(x for x in (year, model, row.get("manual_type") or "", note, f"({part})" if part else "") if x),
            )
        log.info("kawasaki_pdf: %d candidates, %d distinct files, %d really PDFs, %d rows", len(found), len(checked), sum(checked.values()), len(seen))


def _vin_rows(c: httpx.Client, vin: str) -> list[dict]:
    page = request(c, "GET", HOST + "/")
    hit = re.search(r'name="csrf-token" content="([^"]+)"', page.text) if page is not None else None
    token = hit.group(1) if hit else ""
    xsrf = urllib.parse.unquote(c.cookies.get("XSRF-TOKEN") or "")
    out = post_json(
        c,
        HOST + "/vin-search",
        data={"vin": vin, "_token": token},
        headers={"X-XSRF-TOKEN": xsrf, "X-Requested-With": "XMLHttpRequest", "Referer": API, **INERTIA},
        throttle=THROTTLE,
    )
    if isinstance(out, dict):
        props = (out.get("props") or {}) if "props" in out else out
        for key in ("pagination", "manuals", "data", "result"):
            value = props.get(key)
            if isinstance(value, dict) and isinstance(value.get("data"), list):
                return value["data"]
            if isinstance(value, list):
                return value
    return []


def resolve_vin(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    """KTIVS answers `POST /vin-search` for a guest; a real chassis number returns that bike's files,
    including the ones its own market publishes rather than the U.S. catalogue's."""
    if not vin or len(vin.strip()) < 11:
        return None
    vin = vin.strip().upper()
    with client() as c:
        for row in _vin_rows(c, vin):
            if not isinstance(row, dict):
                continue
            for doc in row.get("manuals") or [row]:
                url = _proxy(doc if isinstance(doc, dict) else {})
                if url and _is_pdf(c, url):
                    year = str(row.get("year") or bike.year)[:4]
                    return RegistryEntry(
                        id=slug(SITE, bike.make, bike.model, bike.year, "en", "owner", vin[-8:]),
                        make=bike.make,
                        model=str(row.get("series_name") or bike.model),
                        years=[int(year)] if year.isdigit() else [bike.year],
                        market=bike.market or "US",
                        type="owner",
                        lang="en",
                        url=url,
                        access="free",
                        site=SITE,
                        title=f"{bike.model} Owner's Manual (KTIVS, VIN {vin[-6:]})",
                    )
    return None
