"""Suzuki has no single portal. Germany runs a CMS with one page per model year (German handbooks),
Australia publishes the current line-up as WordPress uploads, and India puts its manuals on a flat
CDN. suzukicycles.com (US) sells them, and bikes.suzuki.co.uk hides them behind a VIN form, so
neither is indexable."""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_json, get_text, log, pmap, published_year, slug

BASE = "https://motorrad.suzuki.de"
API = f"{BASE}/cms/api/delivery/de/GLOBAL/page"
SITE = "motorrad.suzuki.de"
YEARS = range(2016, 2027)

AU = "https://suzukimotorcycles.com.au/owners/manuals/"
AU_SITE = "suzukimotorcycles.com.au"
AU_MODEL = re.compile(r"\?t=([a-z0-9-]+)&(?:amp;)?v=([a-z0-9-]+)")
AU_UPLOAD = re.compile(r"/uploads/((?:19|20)\d{2})/\d{2}/")

IN_PAGE = "https://www.suzukimotorcycle.co.in/User-Manual"
IN_SITE = "suzukimotorcycle.co.in"
IN_PDF = re.compile(r"https://cdn\.suzukimotorcycle\.co\.in/[^\"'<> ]*/user-manual/[^\"'<> ]+\.pdf", re.I)
PDF_HREF = re.compile(r"https?://[^\"'<> ]+\.pdf", re.I)
BROWSER_HEADERS = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"}


def _widgets(node, out: list) -> None:
    if isinstance(node, dict):
        if node.get("type") == "LinkListWidget":
            out.append(node)
        for v in node.values():
            _widgets(v, out)
    elif isinstance(node, list):
        for v in node:
            _widgets(v, out)


def suzuki_de() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:  # the CMS answers 400 to anything that is not a browser

        def page(year: int):
            url = f"{BASE}/informationen/dokumente/fahrerhandbuecher/{year}"
            return year, get_json(c, API, params={"url": url})

        seen: set[str] = set()
        for year, payload in pmap(page, YEARS):
            if not isinstance(payload, dict) or not payload.get("success"):
                continue
            widgets: list = []
            _widgets(payload.get("body"), widgets)
            for w in widgets:
                for item in (w.get("content") or {}).get("items") or []:
                    model = (item.get("text") or "").strip()
                    rel = (((item.get("download_file") or {}).get("de") or {}).get("full")) or ""
                    if not model or not rel:
                        continue
                    eid = slug(SITE, model, year, "DE", "de", "owner")
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Suzuki",
                        model=model,
                        years=[year],
                        market="DE",
                        type="owner",
                        lang="de",
                        url=rel if rel.startswith("http") else BASE + rel,
                        access="free",
                        site=SITE,
                        title=f"{model} {year} Fahrerhandbuch",
                    )
        log.info("suzuki_de: %d entries", len(seen))


def _australia(c) -> Iterable[RegistryEntry]:
    index = get_text(c, AU, headers=BROWSER_HEADERS) or ""
    cats = sorted({m for m in re.findall(r"manuals/\?t=([a-z0-9-]+)", index)})
    pairs: set[tuple[str, str]] = set(AU_MODEL.findall(index))
    for page in pmap(lambda cat: get_text(c, f"{AU}?t={cat}", headers=BROWSER_HEADERS) or "", cats):
        pairs |= set(AU_MODEL.findall(page))

    def manual(pair: tuple[str, str]):
        cat, slug_ = pair
        html = get_text(c, f"{AU}?t={cat}&v={slug_}", headers=BROWSER_HEADERS) or ""
        hit = PDF_HREF.search(html)
        return (slug_, hit.group(0)) if hit else None

    seen: set[str] = set()
    for slug_, url in pmap(manual, sorted(pairs)):
        model = slug_.replace("-", " ").upper()
        year = AU_UPLOAD.search(url)
        years = [int(year.group(1))] if year else []
        eid = slug(AU_SITE, model, years[0] if years else "", "AU", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Suzuki",
            model=model,
            years=years,  # the line-up has no year axis; the upload year dates the handbook
            market="AU",
            type="owner",
            lang="en",
            url=htmllib.unescape(url),
            access="free",
            site=AU_SITE,
            title=f"{model} Owner's Manual (Australia)",
        )
    log.info("suzuki_en AU: %d entries from %d models", len(seen), len(pairs))


def _india(c) -> Iterable[RegistryEntry]:
    html = get_text(c, IN_PAGE, headers=BROWSER_HEADERS) or ""
    seen: set[str] = set()
    for url in sorted(set(IN_PDF.findall(html))):
        stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
        model = re.sub(r"[-_]?(OM|User[-_]?Manual)[-_]?", " ", stem.replace("%20", " ")).replace("-", " ").strip()
        year = published_year(c, url)
        eid = slug(IN_SITE, model, year or "", "IN", "en", "owner")
        if not model or eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Suzuki",
            model=model,
            years=[year] if year else [],
            market="IN",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=IN_SITE,
            title=f"{model} Owner's Manual (India)",
        )
    log.info("suzuki_en IN: %d entries", len(seen))


def suzuki_en() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        yield from _australia(c)
        yield from _india(c)
