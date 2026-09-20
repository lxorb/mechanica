"""Yamaha, the rest of the world: the same Owner's Manual Library behind library.ymcapps.net, but
every distributor, not just the four English ones `yamaha.py` walks.

How the portal is keyed (all of this is read off the site, nothing guessed):
  * `library/om/app/index.js` ships an `isEuroSite` list of base codes and loads
    `library/om/app/assets/database.xlsx`, whose sheets `リンク元パラメータ` (base code + UI language +
    the entry URL) and `langData` (per base and product, the languages its manuals are printed in)
    are the authoritative distributor table. Both were parsed, and every 4-character base code in
    the `拠点コード` sheet (344 of them) was probed: exactly 30 carry product "10",
    Motorcycles & Scooters. `yamaha.py` already covers four of them in English
    (6150 US, 6210 CA, 6726 AU, 7306 GB), so this module covers the other 26 plus 6210 in French.
  * A manual's file name is deterministic:
    `//library.ymcapps.net/library/om/contents/pdf/<productId>/<publicationNo>_<publicationLangId>.pdf`
    — the publication number is the manual number the site's third search tab asks for. The rows
    come back straight from `model_list`, so nothing has to be enumerated by hand; verified as a
    real PDF by magic bytes on samples from India, Ireland and New Zealand.

`publicationLang` must be an exact language id — "" and "ALL" return nothing — so every base is
asked for its own languages *and* for English (02), which is what makes a Greek or Finnish
distributor useful to an English catalogue. Languages are filtered through `keep_lang` before the
request, so the default REGISTRY_LANGS=en costs one pass per base.

Rows are deduplicated on (url, model, year): a publication shared by several distributors is one
document, and the first market in BASES wins it."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from ..models import RegistryEntry
from ._http import BROWSER_UA, Throttle, client, keep_lang, log, pmap, post_json, slug

OMB = "https://parts.yamaha-motor.co.jp/ypec_b2c/services/omb2c/"
SITE = "library.ymcapps.net"
HEADERS = {"Content-Type": "application/json", "Origin": "https://library.ymcapps.net", "Referer": "https://library.ymcapps.net/"}
MOTORCYCLES = "10"
ENGLISH = "02"
THROTTLE = Throttle(2.0)  # one host for every distributor; stay under 2 req/s

# langId -> ISO code, from the `言語区分` sheet of the portal's own database.xlsx.
LANGS: dict[str, str] = {
    "01": "ja",
    "02": "en",
    "03": "fr",
    "04": "es",
    "05": "de",
    "06": "pt",
    "07": "id",
    "09": "ar",
    "10": "sv",
    "11": "fi",
    "12": "it",
    "13": "nl",
    "14": "no",
    "15": "el",
    "16": "zh",
    "17": "zh",
    "18": "da",
    "19": "th",
    "20": "vi",
    "21": "fa",
    "22": "ko",
    "23": "km",
    "24": "tr",
    "25": "ru",
    "26": "ms",
    "29": "hu",
    "30": "cs",
    "32": "pl",
}

# base code -> (market, UI language id, the languages its motorcycle manuals are printed in).
# English is appended to every entry by _wanted(); order decides which market keeps a shared manual.
BASES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "6C97": ("IN", "02", ()),  # IYM India
    "6852": ("NZ", "02", ()),  # YMNZ
    "7309": ("IE", "02", ()),  # Danfay, Ireland
    "745E": ("CZ", "02", ()),  # YME Czech Republic
    "7426": ("HU", "02", ()),  # YME Hungary
    "C81E": ("RO", "02", ()),  # Motodynamics Romania
    "C87E": ("BG", "02", ()),  # Motodynamics Bulgaria
    "6979": ("GR", "15", ()),  # Motodynamics Greece - prints English
    "7085": ("TR", "24", ()),  # YMTR Turkey - prints English
    "7318": ("DK", "18", ()),  # Yamaha Motor Danmark - prints English
    "7363": ("NO", "14", ()),  # YME Norge - prints English
    "821K": ("FI", "11", ("11",)),  # YME Finland
    "C813": ("PL", "32", ()),  # YME Poland - prints English
    "7370": ("SE", "10", ("10",)),  # YME Sverige
    "7319": ("DE", "05", ("05",)),  # Yamaha Motor Deutschland
    "7355": ("AT", "05", ("05",)),  # YME Osterreich
    "7338": ("CH", "05", ("05", "03")),  # Hostettler, Swiss - German and French UIs
    "7390": ("FR", "03", ("03",)),  # YME France
    "7324": ("BE", "03", ("03", "13")),  # D'Ieteren, Belgium
    "7305": ("NL", "13", ("13",)),  # YME Nederland
    "7316": ("IT", "12", ("12",)),  # YME Italia
    "807P": ("ES", "04", ("04",)),  # YME Espana
    "7323": ("PT", "06", ("06",)),  # YME Portugal
    "6210": ("CA", "03", ("03",)),  # Yamaha Motor Canada - the French half; yamaha.py has the English
    "65TW": ("TH", "19", ("19",)),  # TYM Thailand
    "666N": ("VN", "20", ("20",)),  # YMVN Vietnam
    "6548": ("ID", "07", ("07",)),  # YIMM Indonesia
}


def _post(c: httpx.Client, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    out = post_json(c, OMB + endpoint, json=body, headers=HEADERS, throttle=THROTTLE)
    return out if isinstance(out, dict) else {}


def _wanted(base: str) -> list[str]:
    """The publication language ids to ask this distributor for, English always included."""
    own = BASES[base][2]
    return [lang for lang in dict.fromkeys((*own, ENGLISH)) if keep_lang(LANGS.get(lang, lang))]


def _models(c: httpx.Client, base: str, ui: str, disp: list[str]) -> dict[tuple[str, str], dict]:
    def names(d: str) -> list[dict]:
        body = {"baseCode": base, "langId": ui, "productId": MOTORCYCLES, "displacementType": d}
        return [m for m in (_post(c, "model_name_list", body).get("modelNameDataCollection") or []) if isinstance(m, dict)]

    found: dict[tuple[str, str], dict] = {}
    for group in pmap(names, disp):
        for m in group:
            found[(m.get("modelName") or "", m.get("nickname") or "")] = m
    return found


def _base(c: httpx.Client, base: str, seen: set[tuple[str, str, str]]) -> Iterator[RegistryEntry]:
    market, ui, _own = BASES[base]
    langs = _wanted(base)
    if not langs:
        return
    root = _post(c, "product_list", {"baseCode": base, "langId": ui})
    ctx = root.get("userContext") or {}
    if not ctx:
        log.warning("yamaha_intl %s: no user context", base)
        return
    disp = [d.get("displacementType") for d in (root.get("displacementDataCollection") or []) if d.get("productId") == MOTORCYCLES]
    models = _models(c, base, ui, [d for d in disp if d])
    if not models:
        log.info("yamaha_intl %s (%s): no models", base, market)
        return

    def manuals(job: tuple[dict, str]) -> tuple[dict, list[dict]]:
        model, publang = job
        body = {
            "baseCode": base,
            "langId": ui,
            "productId": MOTORCYCLES,
            "calledCode": "1",
            "modelName": model.get("modelName") or "",
            "nickname": model.get("nickname") or "",
            "modelYear": "",  # every model year in one call
            "publicationLang": publang,
            "userGroupCode": ctx.get("userGroupCode") or "",
            "destination": ctx.get("destination") or "",
            "destGroupCode": ctx.get("destGroupCode") or "",
        }
        return model, [r for r in (_post(c, "model_list", body).get("modelDataCollection") or []) if isinstance(r, dict)]

    found = 0
    for model, rows in pmap(manuals, [(m, lang) for m in models.values() for lang in langs]):
        name = (model.get("dispModelName") or model.get("modelName") or model.get("nickname") or "").strip()
        for row in rows:
            url = (row.get("pdffileURL") or "").strip()
            if not url or not name:
                continue
            url = "https:" + url if url.startswith("//") else url
            year = str(row.get("modelYear") or "")
            lang = LANGS.get(str(row.get("publicationLangId") or ""), "")
            if not lang or not keep_lang(lang):
                continue
            key = (url, name.lower(), year)
            if key in seen:  # the same publication is handed out by several distributors
                continue
            seen.add(key)
            found += 1
            pub = str(row.get("publicationNo") or "")
            yield RegistryEntry(
                id=slug(SITE, name, year, market, lang, "owner", pub[:16]),
                make="Yamaha",
                model=name,
                years=[int(year)] if year.isdigit() else [],
                market=market,
                type="owner",
                lang=lang,
                url=url,
                access="free",
                site=SITE,
                title=f"{year} {row.get('dispModelName') or name} Owner's Manual ({pub or row.get('litNo') or market})".strip(),
            )
    log.info("yamaha_intl %s (%s): %d models x %s -> %d manuals", base, market, len(models), langs, found)


def rows() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        seen: set[tuple[str, str, str]] = set()
        for base in BASES:
            yield from _base(c, base, seen)
        log.info("yamaha_intl: %d manuals over %d distributors", len(seen), len(BASES))
