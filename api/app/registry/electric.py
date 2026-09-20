"""The electric makers that publish a handbook as a plain file.

* **NIU** — global.niu.com/downloads ships its whole manual table as a JS literal
  (`{ id, eyebrow, title, coverage, languages:[{code,label,url}] }`), every url a PDF on the Sanity
  CDN. No model year is printed, so the year comes from the file's `Last-Modified`.
* **Cake** — ridecake.com has one "<family>-manuals-and-videos" page per family; the user manuals are
  plain `<a>` links to the Sanity CDN with the model in the link text.
* **Vmoto / Super Soco** — vmoto.com/manuals links a PDF per model straight off the site.
* **Energica**, **Sur-Ron**, **Talaria**, **Stark Future** and **Segway Powersports** publish nothing
  free and fetchable: Energica's owners area is a login, Segway hides its manual list behind a
  `javascript:;` menu with no JSON behind it, surron.com/talaria.bike refuse the connection from
  outside their CDN region, and Stark ships only policy PDFs. They are listed here so the next pass
  does not re-walk them.
"""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin

import httpx

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_text, keep_lang, log, published_year, slug, years_in

NIU_PAGE = "https://global.niu.com/downloads"
NIU_SITE = "niu.com"
NIU_BLOCK = re.compile(r"\{\s*id:\s*'([^']+)'.*?title:\s*'([^']*)'.*?category:\s*'([^']*)'.*?coverage:\s*'([^']*)'.*?languages:\s*\[(.*?)\]", re.S)
NIU_LANG = re.compile(r"\{\s*code:\s*'([a-z-]+)'[^}]*?url:\s*'([^']+)'", re.S)

CAKE_INDEX = "https://ridecake.com/en-GB/manuals-and-instructions"
CAKE_SITE = "ridecake.com"
CAKE_FAMILY = re.compile(r'href="(/en-GB/[a-z0-9-]+-manuals-and-videos)"', re.I)
CAKE_LINK = re.compile(r'<a[^>]+href="(https://cdn\.sanity\.io/files/[^"]+\.pdf)"[^>]*>(.*?)</a>', re.S | re.I)
CAKE_KEEP = re.compile(r"(?i)user manual")
CAKE_DROP = re.compile(r"(?i)\b(fork|shock|suspension|charger|preload|spring|rack|size guide|unboxing|assembly|battery)\b")

VMOTO_PAGE = "https://vmoto.com/manuals"
VMOTO_SITE = "vmoto.com"
VMOTO_LINK = re.compile(r'<a[^>]+href="([^"]*/Manuals/[^"]+\.pdf)"[^>]*>(.*?)</a>', re.S | re.I)

throttle = Throttle(2.0)


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _year(c: httpx.Client, url: str) -> list[int]:
    got = published_year(c, url)
    return [got] if got else []


def niu() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        page = get_text(c, NIU_PAGE, throttle=throttle) or ""
        seen: set[str] = set()
        for _id, title, category, coverage, langs in NIU_BLOCK.findall(page):
            model = re.sub(r"(?i)\s*user manual\s*$", "", title).strip()
            if not model:
                continue
            docs = NIU_LANG.findall(langs)
            english = [(code, url) for code, url in docs if code.startswith("en")]
            wanted = english or docs
            wanted += [(code, url) for code, url in docs if not code.startswith("en") and english and keep_lang(code)]
            for code, url in wanted:
                lang = code.split("-")[0].lower()
                years = _year(c, url)
                eid = slug(NIU_SITE, "NIU", model, years[0] if years else "", lang, "owner")
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="NIU",
                    model=model,
                    years=years,
                    market="EU",
                    type="owner",
                    lang=lang,
                    url=url,
                    access="free",
                    site=NIU_SITE,
                    title=f"NIU {title}" + (f" ({coverage})" if coverage else ""),
                )
        log.info("niu: %d entries (%s)", len(seen), "motorcycles and mopeds")


def cake() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        index = get_text(c, CAKE_INDEX, throttle=throttle) or ""
        families = sorted({urljoin(CAKE_INDEX, p) for p in CAKE_FAMILY.findall(index)})
        seen: set[str] = set()
        for family in families:
            html = get_text(c, family, throttle=throttle) or ""
            for url, label in CAKE_LINK.findall(html):
                text = _text(label)
                if not CAKE_KEEP.search(text) or CAKE_DROP.search(text):
                    continue
                model = re.sub(r"(?i)\s*user manuals?.*$", "", text).strip()
                model = re.sub(r"(?i)\s*\(.*$", "", model).strip()
                model = re.sub(r"(?i)\s*manuals?$", "", model).strip()
                if not model or len(model) > 60:
                    continue
                years = _year(c, url)
                eid = slug(CAKE_SITE, "Cake", model, years[0] if years else "", "en", "owner")
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Cake",
                    model=model,
                    years=years,
                    market="EU",
                    type="owner",
                    lang="en",
                    url=url,
                    access="free",
                    site=CAKE_SITE,
                    title=f"Cake {text}",
                )
        log.info("cake: %d entries from %d families", len(seen), len(families))


def vmoto() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        html = get_text(c, VMOTO_PAGE, throttle=throttle) or ""
        seen: set[str] = set()
        for href, label in VMOTO_LINK.findall(html):
            url = urljoin(VMOTO_PAGE, htmllib.unescape(href))
            stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
            model = _text(label) or re.sub(r"[-_]+", " ", stem)
            model = re.sub(r"(?i)\s*(user|owner'?s?)\s*manual.*$", "", model).strip()
            model = re.sub(r"[-_]+", " ", model).strip()
            if not model or not model.isascii():
                continue
            years = years_in(model) or _year(c, url)
            eid = slug(VMOTO_SITE, "Vmoto", model, years[0] if years else "", "en", "owner")
            if eid in seen:
                continue
            seen.add(eid)
            yield RegistryEntry(
                id=eid,
                make="Vmoto",
                model=model,
                years=years,
                market="EU",
                type="owner",
                lang="en",
                url=url,
                access="free",
                site=VMOTO_SITE,
                title=f"Vmoto Super Soco {model} User Manual",
            )
        log.info("vmoto: %d entries", len(seen))


def rows() -> Iterable[RegistryEntry]:
    yield from niu()
    yield from cake()
    yield from vmoto()
