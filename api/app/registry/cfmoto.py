"""CFMOTO publishes every handbook and blocks every way of reading it from here.

Three official sources exist, and all three were verified dead from outside their own region on
2026-09-19:

* `cfmoto-motorcycle.eu/en/service/user-manual` — the European motorcycle site, one PDF per model.
  It resets the TLS connection (httpx, curl and a hosted fetcher all get `ECONNRESET`), so it is
  geo- or fingerprint-gated rather than merely rate-limited.
* `cfmotousa.com/owners-manuals` and its `assets/cfmoto/images/owners_manuals/*.pdf` — Cloudflare
  answers 403 text/html to every user agent, Googlebot included (zero.py records the same finding).
* `cfmoto.com.au`, `cfmoto.ca`, `cfmoto.co.nz` 403; `cfmoto.co.uk` serves an sgcaptcha interstitial.
  The open European distributor sites (cfmoto.it, cfmoto.pl, cfmoto.cz) carry ATV and side-by-side
  manuals only — no motorcycles.

So this adapter is a live attempt, not a guess: it walks the European manual page when the host lets
it through (a crawl from an EU address, or with `REGISTRY_UA` set to something the WAF likes) and
yields nothing, loudly, when it does not. Nothing here is hard-coded from a search engine: a row is
only ever emitted for a link this crawl actually saw.
"""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_text, log, slug, years_in

PAGE = "https://cfmoto-motorcycle.eu/en/service/user-manual"
SITE = "cfmoto-motorcycle.eu"
LINK = re.compile(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
TAIL = re.compile(r"(?i)[-_ ]*(?:owner|user|operation)?[-_ '‘’s]*manual\b.*$")
throttle = Throttle(2.0)


def cfmoto() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        html = get_text(c, PAGE, throttle=throttle)
    if not html:
        log.warning("cfmoto: %s is unreachable from this network (see the module docstring)", SITE)
        return
    seen: set[str] = set()
    for href, label in LINK.findall(html):
        url = urljoin(PAGE, htmllib.unescape(href))
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", label)).strip()
        stem = url.split("?")[0].rsplit("/", 1)[-1].removesuffix(".pdf").replace("%20", " ")
        model = TAIL.sub("", text or stem)
        model = re.sub(r"(?i)^cf\s*moto[-_ ]*", "", re.sub(r"[-_]+", " ", model)).strip()
        if not model or len(model) > 48:
            continue
        years = years_in(text) or years_in(stem)
        eid = slug(SITE, "CFMoto", model, years[0] if years else "", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="CFMoto",
            model=model,
            years=years,
            market="EU",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=SITE,
            title=f"CFMOTO {model} Owner's Manual",
        )
    log.info("cfmoto: %d entries", len(seen))


def rows() -> Iterable[RegistryEntry]:
    yield from cfmoto()
