"""The Chinese and Taiwanese makers whose handbooks are actually downloadable.

Three of them run WordPress and answer `wp-json/wp/v2/media?media_type=application`, which lists every
PDF on the site with its upload date — that beats scraping the marketing pages, and the upload year is
the only model year these brands print.

* **Kove** — kovemoto.com, English manuals for the whole ADV/RR/Rally line.
* **Voge** (Loncin) — the EU sites are unreachable from outside their region, but vogeitaly.it carries
  the same English `*-Owner-manual.pdf` files Loncin ships worldwide.
* **QJ Motor** — qjmotor.eu and benelli.com are unreachable from outside their region; the Spanish
  importer (qjmotor.es, also WordPress) carries the same manuals, in Spanish, which is the only
  language QJ publishes at all.
* **Sinnis** — sinnismotorcycles.com links its manuals on Dropbox; `?dl=0` is a preview page, so the
  row stores `?dl=1`, which serves the PDF itself.

Walked and found nothing free to index (kept here so the next pass does not repeat the walk):
CFMOTO (see cfmoto.py), Benelli and QJ's own EU site (both time out from outside their CDN region), Zontes
(403 on every locale), Benda and Lifan (no manual section), Keeway (marketing only, manuals sit in the
dealer area), Hyosung and Daelim (US/KR sites carry no PDF), Lexmoto (dealer portal), SYM (the files
exist under `/storage/system/products/<class>/<code>/Manual/…` but nothing public enumerates them and
the names are not derivable), Kymco outside the US (kymco.com is a distributor directory; the US
uploads are already covered by kymco.py).
"""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_json, get_text, log, slug, years_in

KOVE_SITE = "kovemoto.com"
KOVE_API = "https://www.kovemoto.com/wp-json/wp/v2/media"
VOGE_SITE = "vogeitaly.it"
VOGE_API = "https://vogeitaly.it/wp-json/wp/v2/media"
QJ_SITE = "qjmotor.es"
QJ_API = "https://qjmotor.es/wp-json/wp/v2/media"
QJ_MANUAL = re.compile(r"(?i)manual[-_ ]*(de[-_ ]*)?usuario")
QJ_NOISE = re.compile(r"(?i)\b(manual|de|del|usuario|user|espanol|español|esp|es|qj|motor|web|final|v\d+)\b")

SINNIS_PAGE = "https://sinnismotorcycles.com/sinnis-manuals/"
SINNIS_SITE = "sinnismotorcycles.com"
SINNIS_LINK = re.compile(r'<a[^>]+href="(https://www\.dropbox\.com/[^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)

MANUAL = re.compile(r"(?i)(owner|user|instruction|operation)s?[-_ ]*(s)?[-_ ]*manual|manual[-_ ]*(book)?|handbook")
NOT_MANUAL = re.compile(r"(?i)warranty|service[-_ ]schedule|maintenance[-_ ]schedule|price|listino|catalog|promo|garanzia|app|brochure|tavola|atv[-_ ]?\d|utv|quad")
TAIL = re.compile(r"(?i)[-_ ]*(?:[a-z'‘’]{2,12})?[-_ ]*manual(?:e|s)?\b.*$")
throttle = Throttle(2.0)


def _media(c: httpx.Client, api: str, pages: int = 6) -> Iterator[dict[str, Any]]:
    """Every PDF the WordPress media library knows about, newest first."""
    for page in range(1, pages + 1):
        batch = get_json(c, api, throttle=throttle, params={"media_type": "application", "per_page": 100, "page": page})
        if not isinstance(batch, list) or not batch:
            return
        for item in batch:
            if isinstance(item, dict) and str(item.get("source_url", "")).lower().endswith(".pdf"):
                yield item
        if len(batch) < 100:
            return


def _model(stem: str) -> str:
    name = htmllib.unescape(stem).replace("%20", " ")
    name = TAIL.sub("", name)
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\b(v?\d+\.\d+|\d{6,8}|en|eng|english|web|final)\b", " ", name, flags=re.I)
    name = re.sub(r"[　-鿿＀-￯]+", " ", name)  # the odd CJK-titled file
    name = re.sub(r"(?i)\s+\S*manual\S*\s*$", "", name)  # "…-MANUALEN", "…_manual_250224"
    name = re.sub(r"(?i)\s+(instruction|operation|owner|user|use|uesrs)s?\s*$", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" -_.")


def _wp_rows(c: httpx.Client, api: str, site: str, make: str, market: str) -> Iterator[RegistryEntry]:
    seen: set[str] = set()
    for item in _media(c, api):
        url = str(item["source_url"])
        stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
        if not MANUAL.search(stem) or NOT_MANUAL.search(stem):
            continue
        model = _model(stem)
        if not model or len(model) > 48:
            continue
        years = years_in(stem) or years_in(str(item.get("date") or ""))
        eid = slug(site, make, model, years[0] if years else "", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make=make,
            model=model,
            years=years,
            market=market,
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=site,
            title=f"{make} {model} Owner's Manual",
        )
    log.info("%s: %d entries", make.lower(), len(seen))


def kove() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        yield from _wp_rows(c, KOVE_API, KOVE_SITE, "Kove", "EU")


def voge() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        yield from _wp_rows(c, VOGE_API, VOGE_SITE, "Voge", "EU")


def qj_motor() -> Iterator[RegistryEntry]:
    """QJ Motor prints no English: qjmotor.eu and benelli.com both refuse the connection from
    outside their region, so the Spanish importer's library is the only reachable copy."""
    with client(ua=BROWSER_UA) as c:
        seen: set[str] = set()
        for item in _media(c, QJ_API):
            url = str(item["source_url"])
            stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
            if not QJ_MANUAL.search(stem) or NOT_MANUAL.search(stem):
                continue
            model = re.sub(r"[-_]+", " ", htmllib.unescape(stem))
            model = QJ_NOISE.sub(" ", model)
            model = re.sub(r"\b(19|20)\d{2}\b", " ", model)
            model = re.sub(r"\s{2,}", " ", model).strip(" -_.")
            if not model or len(model) > 48:
                continue
            years = years_in(stem) or years_in(str(item.get("date") or ""))
            eid = slug(QJ_SITE, "QJ Motor", model, years[0] if years else "", "es", "owner")
            if eid in seen:
                continue
            seen.add(eid)
            yield RegistryEntry(
                id=eid,
                make="QJ Motor",
                model=model,
                years=years,
                market="EU",
                type="owner",
                lang="es",
                url=url,
                access="free",
                site=QJ_SITE,
                title=f"QJ Motor {model} Manual de Usuario",
            )
        log.info("qj-motor: %d entries", len(seen))


def sinnis() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        html = get_text(c, SINNIS_PAGE, throttle=throttle) or ""
    seen: set[str] = set()
    done: set[str] = set()
    for href, label in SINNIS_LINK.findall(html):
        url = htmllib.unescape(href).replace("?dl=0", "?dl=1")
        if "dl=" not in url:
            url += ("&" if "?" in url else "?") + "dl=1"
        if url in done:  # each manual is linked twice, from its picture and from its caption
            continue
        done.add(url)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", label)).strip()
        stem = url.split("?")[0].rsplit("/", 1)[-1].removesuffix(".pdf").replace("%20", " ")
        years = years_in(stem) or years_in(text)
        # the file name is "Sinnis <model> Manual.pdf"; the caption is marketing ("THE EXPLORER")
        model = _model(re.sub(r"(?i)^sinnis[-_ ]*", "", stem))
        model = re.sub(r"^((?:19|20)\d{2})\s+", "", model).strip()
        if not model:
            continue
        eid = slug(SINNIS_SITE, "Sinnis", model, years[0] if years else "", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Sinnis",
            model=model,
            years=years,
            market="GB",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=SINNIS_SITE,
            title=f"Sinnis {model} Manual",
        )
    log.info("sinnis: %d entries", len(seen))


def rows() -> Iterable[RegistryEntry]:
    yield from kove()
    yield from voge()
    yield from qj_motor()
    yield from sinnis()
