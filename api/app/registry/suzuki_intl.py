"""Suzuki outside Germany, Australia and India - which is almost entirely Japan.

Suzuki has no global manual portal, so every national site had to be checked one at a time. The
result of that sweep, so nobody repeats it:

  * **www1.suzuki.co.jp** - the one real find. `/motor/support/owners_manual/dl/` is a three-step
    dropdown (displacement, model, model year) rendered server-side: fetching
    `index.html?modelname=<name>` returns every model year for that model as
    `parts_catalog_search_result_block` anchors, each pointing at a direct PDF under
    `/motor/support/owners_manual_manage/files/`. 61 models, manuals back to the 2000s, verified as
    PDFs by magic bytes. Japanese.
  * **motorrad.suzuki.de** - `suzuki.py` walks 2016-2026; the CMS also answers for 2027 and will for
    later years, so this module re-walks a wider window with the *same* row ids, which merges.
    2015 and earlier 404: 2016 really is the first year.
  * **bikes.suzuki.co.uk** - VIN only. The page says so itself ("We currently only have Owners
    Manuals available to download for GSX800RQM4 and DL650AM4"), there is no model endpoint, and the
    lookup is `HandbookLocator/GetHandbook?vin=` on cars-services.suzuki.co.uk. It is registered in
    `dynamic.RESOLVERS` instead of being crawled.
  * Nothing to index: suzukicycles.com (US) sells manuals through genuinesuzukimanuals.com;
    suzuki.co.nz, suzuki.ca, globalsuzuki.com, suzuki.co.id, suzuki.com.my, suzuki.com.vn,
    suzuki.com.co/.pe/.cl publish none; suzuki.nl and suzuki.dk have handbook *pages* whose lists
    are drawn client-side with no URL in the document; suzuki.co.th's manual list is cars only; and
    the German CMS (`/cms/api/delivery/…`) is not mirrored on suzuki.at, suzuki.ch or suzuki.lu.

Japanese model names are romanised before they become rows. `slug()` strips non-ASCII, so `アドレス125`
and `アヴェニス125` would both collapse to the bike id `suzuki-125-<year>`; ROMAJI maps every katakana
name in the dropdown to the Latin name Suzuki itself sells the model under (Address, Avenis, Burgman,
V-Strom, …). A name that still has no ASCII letter after that is dropped rather than guessed at."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from ..models import Bike, RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_json, get_text, keep_lang, log, pmap, slug

JP = "https://www1.suzuki.co.jp"
JP_DL = f"{JP}/motor/support/owners_manual/dl/"
JP_SITE = "suzuki.co.jp"
JP_MODEL = re.compile(r'<option value="index\.html\?bikedisp=(?:&amp;|&)modelname=([^"&]+)"')
JP_BLOCK = re.compile(
    r'<a href="(/motor/support/owners_manual_manage/files/[^"]+\.pdf)"[^>]*>\s*<span>\s*機種名:\s*([^<]*?)\s*<br\s*/?>\s*年式:\s*([0-9]{4})',
    re.S,
)

DE = "https://motorrad.suzuki.de"
DE_API = f"{DE}/cms/api/delivery/de/GLOBAL/page"
DE_SITE = "motorrad.suzuki.de"
DE_YEARS = range(2016, 2031)  # 2015 and earlier 404; the tail is a no-cost look ahead

UK_API = "https://cars-services.suzuki.co.uk/api/HandbookLocator/GetHandbook"
UK_SITE = "bikes.suzuki.co.uk"
# The credentials the handbook page hands to every browser that loads it (publicRuntimeConfig in
# __NEXT_DATA__). Sent exactly as the site's own front end sends them, for the same read-only call.
UK_AUTH = ("SuzukiApiServiceV1", "AKJDH!#@!@##$u412h4kjNH*)!@U$!RNj1ndnLKJNUQHI!@H#J!")

THROTTLE_JP = Throttle(2.0)
THROTTLE_DE = Throttle(2.0)
BROWSER_HEADERS = {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"}
HAS_LETTER = re.compile(r"[a-z]")

# Every katakana fragment the www1.suzuki.co.jp dropdown prints, in the Latin name Suzuki sells the
# model under. Longest first: スカイウェイブ must win before ウェイブ could.
ROMAJI: tuple[tuple[str, str], ...] = (
    ("イントルーダークラシック", "Intruder Classic "),
    ("キャストホイール仕様", " Cast Wheel"),
    ("バーグマンストリート", "Burgman Street "),
    ("グラストラッカー", "Grasstracker "),
    ("スカイウェイブ", "Skywave "),
    ("フラットシート仕様", " Flat Seat"),
    ("レッツバスケット", "Let's Basket"),
    ("グラディウス", "Gladius "),
    ("ビッグボーイ", " Big Boy"),
    ("ストローム", "-Strom "),
    ("ブルバード", "Boulevard "),
    ("バーグマン", "Burgman "),
    ("アヴェニス", "Avenis "),
    ("スウィッシュ", "Swish"),
    ("リミテッド", " Limited"),
    ("バーディー", "Birdie "),
    ("アドレス", "Address "),
    ("ジクサー", "Gixxer "),
    ("タイプ", " Type "),
    ("レッツ", "Let's"),
    ("ベーシック", " Basic"),
    ("ラブ", "Love "),
)


def _romanise(name: str) -> str:
    for katakana, latin in ROMAJI:
        name = name.replace(katakana, latin)
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", " / ", name)).strip()


def _japan(c: httpx.Client) -> Iterator[RegistryEntry]:
    index = get_text(c, JP_DL, headers=BROWSER_HEADERS, throttle=THROTTLE_JP) or ""
    names = list(dict.fromkeys(JP_MODEL.findall(index)))
    if not names:
        log.warning("suzuki_intl JP: no model dropdown")
        return

    def page(name: str) -> tuple[str, str]:
        url = JP_DL + "index.html?bikedisp=&modelname=" + urllib.parse.quote(name, safe="")
        return name, get_text(c, url, headers=BROWSER_HEADERS, throttle=THROTTLE_JP) or ""

    seen: set[str] = set()
    dropped = 0
    for _name, html in pmap(page, names):
        for href, printed, year in JP_BLOCK.findall(html):
            model = _romanise(printed)
            if not HAS_LETTER.search(slug(model)):  # a katakana name ROMAJI does not know
                log.info("suzuki_intl JP: no Latin name for %r", printed)
                dropped += 1
                continue
            eid = slug(JP_SITE, model, year, "JP", "ja", "owner", href.rsplit("/", 1)[-1][:24])
            if eid in seen:
                continue
            seen.add(eid)
            yield RegistryEntry(
                id=eid,
                make="Suzuki",
                model=model,
                years=[int(year)],
                market="JP",
                type="owner",
                lang="ja",
                url=JP + href,
                access="free",
                site=JP_SITE,
                title=f"{printed} {year} オーナーズマニュアル (Japan)",
            )
    log.info("suzuki_intl JP: %d models, %d manuals, %d dropped for an unromanisable name", len(names), len(seen), dropped)


def _link_lists(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "LinkListWidget":
            out.append(node)
        for value in node.values():
            _link_lists(value, out)
    elif isinstance(node, list):
        for value in node:
            _link_lists(value, out)


def _germany(c: httpx.Client) -> Iterator[RegistryEntry]:
    def page(year: int) -> tuple[int, Any]:
        url = f"{DE}/informationen/dokumente/fahrerhandbuecher/{year}"
        return year, get_json(c, DE_API, params={"url": url}, throttle=THROTTLE_DE)

    seen: set[str] = set()
    for year, payload in pmap(page, DE_YEARS):
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        widgets: list[dict] = []
        _link_lists(payload.get("body"), widgets)
        for widget in widgets:
            for item in (widget.get("content") or {}).get("items") or []:
                model = (item.get("text") or "").strip()
                rel = ((item.get("download_file") or {}).get("de") or {}).get("full") or ""
                if not model or not rel:
                    continue
                eid = slug(DE_SITE, model, year, "DE", "de", "owner")  # same shape as suzuki.py: overlap merges
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
                    url=rel if rel.startswith("http") else DE + rel,
                    access="free",
                    site=DE_SITE,
                    title=f"{model} {year} Fahrerhandbuch",
                )
    log.info("suzuki_intl DE: %d entries over %d..%d", len(seen), DE_YEARS.start, DE_YEARS.stop - 1)


def resolve_uk(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    """bikes.suzuki.co.uk hands out a handbook per VIN and has no model index at all."""
    if not vin or len(vin.strip()) != 17:
        return None
    vin = vin.strip().upper()
    with client(ua=BROWSER_UA, headers={"Referer": f"https://{UK_SITE}/owners/service-maintenance/owners-manuals/"}) as c:
        payload = get_json(c, UK_API, params={"vin": vin}, auth=UK_AUTH)
    url = (payload or {}).get("HandbookUrl") if isinstance(payload, dict) else None
    if not url or (payload or {}).get("isError"):
        return None
    return RegistryEntry(
        id=slug(UK_SITE, bike.make, bike.model, bike.year, "en", "owner", vin[-8:]),
        make=bike.make,
        model=bike.model,
        years=[bike.year],
        market="GB",
        type="owner",
        lang="en",
        url=str(url),
        access="free",
        site=UK_SITE,
        title=f"{bike.model} Owner's Manual (UK, VIN {vin[-6:]})",
    )


def rows() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:  # the German CMS answers 400 to anything that is not a browser
        if keep_lang("ja"):
            yield from _japan(c)
        if keep_lang("de"):
            yield from _germany(c)
