"""Toyota and Lexus Japan — `manual.toyota.jp` and `manual.lexus.jp`, the Japanese car portals that
still publish real PDFs.

`toyota.jp/ownersmanual/<slug>/index.html` redirects to `manual.toyota.jp/<slug>/`, and that page is
plain server-rendered HTML listing every handbook Toyota has ever published for the model, newest
first. The 91 slugs are read out of toyota.jp's own sitemaps rather than typed here, so a model
Toyota adds appears on the next crawl.

Lexus is the same portal with a different skin - 22 models listed on `manual.lexus.jp/` itself, and
`/pdf/rx/RX300_OM_JP_M48G57_2_1912.pdf` files behind the same production-month labels.

Both pages are the same three things in sequence, which is what the parser walks rather than any
one site's class names:

    a heading            the document's name        <h5>…</h5>  /  <p class="mp-unit_title">…</p>
    生産年月：2013年02月～2014年11月   the production months it covers
    the next <a href>    the file                   .pdf is kept, the HTML viewer twin is skipped

**Years come from the production range, not the file name.** `生産年月：2013年02月～2014年11月` covers
model years 2013 *and* 2014, and a row that claimed only 2013 would leave the 2014 car with nothing.
An open-ended newest range (`2026年07月～`) runs to next model year, which is as far as Toyota sells.

**What is and is not the handbook.** Toyota has moved to an HTML manual plus a printed *abridged*
edition, so the newest PDFs say 抜粋版 ("excerpt edition"). Those are filed as `quickstart`, the
older complete books as `owner`, and navigation/display-audio books as `infotainment`; `_pick()`
then prefers a complete handbook wherever one exists. Nothing is dropped - an excerpt is still the
manufacturer's own book for that car.

Japanese, so these never reach unattended English ingest; they exist for the language fallback.

**Checked at the same time and not indexed** (so nobody re-walks them): Mazda Japan
(`mazda.co.jp/owner_support/manual/<model>/`) and Subaru Japan
(`subaru.jp/dealerservice/ownersmanual/<model>/`) both have a per-model page and both serve an HTML
viewer only - Mazda's links are `www2.mazda.co.jp/carlife/owner/manual/...index.html`, Subaru's page
renders its list client-side with no document url in the markup. Nissan Japan and Suzuki Japan
declare a sitemap with no manual tree at all. Honda Japan publishes `/ownersmanual/HondaMotor/auto/`
(see `honda_jp.py`) and `/ownersmanual/HondaMotor/power/` - power equipment, not vehicles - and
**no motorcycle portal**: those two are the only entries in its sitemap.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable, Iterator

from ..models import RegistryEntry
from ._http import Throttle, client, get_text, keep_lang, log, name_families, plausible_years, pmap, pretty_slug, slug

TOYOTA = "manual.toyota.jp"
LEXUS = "manual.lexus.jp"
INDEX = "https://toyota.jp/robots.txt"  # Toyota's own sitemaps are the model list
MARKET = "JP"
LANG = "ja"

SITEMAP = re.compile(r"(?im)^\s*sitemap:\s*(\S+)")
LOC = re.compile(r"<loc>([^<]+)</loc>")
MODEL = re.compile(r"toyota\.jp/ownersmanual/([a-z0-9_-]+)/index\.html", re.I)
LEXUS_MODEL = re.compile(r'href="/([a-z0-9]{2,12})/"')
# One scanner for both skins: a heading, a production-month label, or a link, in document order.
EVENT = re.compile(
    r"<h5[^>]*>(?P<h5>.*?)</h5>"
    r"|<p[^>]*mp-unit_title[^>]*>(?P<title>.*?)</p>"
    r"|生産年月[：:]\s*(?P<date>.*?)</p>"
    r"|<a[^>]+href=\"(?P<href>[^\"]+)\"",
    re.S,
)
YEAR = re.compile(r"(\d{4})\s*年")
TAGS = re.compile(r"<[^>]+>")

SPELLING = {"phv": "PHV", "hev": "HEV", "ev": "EV", "bb": "bB", "iq": "iQ", "cpod": "C+pod", "cwalkt": "C+walk T"}
THROTTLE = Throttle(2.0)


def _kind(title: str) -> str:
    if "ナビ" in title or "ディスプレイオーディオ" in title or "オーディオ" in title:
        return "infotainment"
    if "抜粋" in title:
        return "quickstart"  # the printed excerpt edition, not the complete book
    if "取扱説明書" in title or "オーナーズマニュアル" in title:
        return "owner"
    return "supplement"


def _years(text: str, newest: bool) -> list[int]:
    """`2013年02月～2014年11月` -> [2013, 2014]. An open-ended newest range runs to next model year."""
    found = [int(y) for y in YEAR.findall(text)]
    if not found:
        return []
    start, end = min(found), max(found)
    if newest and "～" in text and len(found) == 1:
        end = datetime.date.today().year + 1
    return plausible_years(range(start, end + 1))


def toyota_slugs() -> list[str]:
    """Toyota's own sitemap is the model list; nothing here is a kept list of nameplates."""
    with client() as c:
        robots = get_text(c, INDEX) or ""
        found: set[str] = set()
        for sitemap in SITEMAP.findall(robots)[:6]:
            body = get_text(c, sitemap) or ""
            children = LOC.findall(body)[:14] if "<sitemapindex" in body[:400] else []
            for child in children or [None]:
                found |= set(MODEL.findall((get_text(c, child) if child else body) or ""))
    return sorted(found)


def lexus_slugs() -> list[str]:
    """Lexus lists its 22 models on the portal's own front page."""
    with client() as c:
        return sorted(set(LEXUS_MODEL.findall(get_text(c, f"https://{LEXUS}/") or "")))


def _text(raw: str) -> str:
    return " ".join(TAGS.sub(" ", raw or "").split())


def documents(html: str) -> Iterator[tuple[str, str, str, bool]]:
    """(heading, production months, href, is the newest under this heading) in document order."""
    title = ""
    pending = ""
    first: set[str] = set()
    for hit in EVENT.finditer(html):
        if hit.group("h5") is not None or hit.group("title") is not None:
            title = _text(hit.group("h5") if hit.group("h5") is not None else hit.group("title"))
            pending = ""
        elif hit.group("date") is not None:
            pending = _text(hit.group("date"))
        elif pending:
            href = hit.group("href")
            yield title, pending, href, title not in first
            first.add(title)
            pending = ""


def _model(make: str, host: str, name: str, model_slug: str) -> list[RegistryEntry]:
    THROTTLE.wait()
    with client() as c:
        html = get_text(c, f"https://{host}/{model_slug}/")
    if not html:
        return []
    out: list[RegistryEntry] = []
    seen: set[str] = set()
    for title, when, href, newest in documents(html):
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue  # the HTML viewer twin of the same book
        years = _years(when, newest=newest)
        url = href if href.startswith("http") else f"https://{host}{href}"
        if not years or url in seen:
            continue
        seen.add(url)
        out.append(
            RegistryEntry(
                id=slug(host, model_slug, years[0], url.rsplit("/", 1)[-1][:40], LANG, "owner"),
                make=make,
                model=name,
                years=years,
                market=MARKET,
                type="owner",
                lang=LANG,
                url=url,
                access="free",
                site=host,
                title=f"{years[0]} {make} {name} {title}".strip(),
                docKind=_kind(title),
                kind="car",
            )
        )
    return out


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang(LANG):
        return
    yield from _portal("Toyota", TOYOTA, toyota_slugs(), pretty=True)
    yield from _portal("Lexus", LEXUS, lexus_slugs(), pretty=False)


def _portal(make: str, host: str, found: list[str], pretty: bool) -> Iterator[RegistryEntry]:
    if not found:
        log.warning("cars_toyota_jp: no models for %s", host)
        return
    known = name_families(found)
    # Lexus model slugs are codes, not words: `rx`, `lbx`, `nx`. Upper-casing them is the whole job.
    names = {s: (pretty_slug(s, known, SPELLING) if pretty else s.upper()) for s in found}
    total = 0
    for group in pmap(lambda s: _model(make, host, names[s], s), found):
        total += len(group)
        yield from group
    log.info("cars_toyota_jp: %s %d rows over %d models", make, total, len(found))
