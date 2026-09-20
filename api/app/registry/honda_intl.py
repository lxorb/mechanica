"""Honda, the distributors `honda.py` does not know about.

Motopub (`hondamotopub.com`) is one site per Honda distributor, and the codes are not discoverable
from an index: the portal's front page lists 31 of them, `honda.py` carries 37 (the extra ten are
the HMEE language twins, HMEG/HMEF/HMES/…), and `/ajax/get_model_names/<CODE>/all` answers 200 with
an empty list for a code that does not exist — so a code either comes off the front page or is
found by trying. Four working codes are on neither list:

    HMSI      Honda Motorcycle & Scooter India        English
    INDUMOT   Indumot, Ecuador                        Spanish
    FAHONDA   FA Honda, Guatemala                     Spanish
    MAKPETROL Makpetrol, North Macedonia              Macedonian

The search for more was exhaustive rather than lucky: 479 candidate codes were tried - HM/H/AH/HMC
prefixed and suffixed with all 92 ISO-3166 country codes Honda sells in, the HMEE language twins for
the rest of Europe (HMEFi, HMESv, HMEDa, HMENo, HMEHu, HMERo, HMEBg, HMEHr, HMESl, HMEEt, HMELv,
HMELt, HMERu, HMETr, HMEUk), and the named subsidiaries. Eleven answered with models and every one
was already known except the four above, so `honda.py`'s 37 plus these 4 are the complete portal.
AMTC (Jordan) is listed on the front page but publishes nothing.

Everything else was checked and is not a second source: powersports.honda.ca, motorcycles.honda.com.au
and honda.co.uk publish no manual files at all (their "owners" sections are warranty and servicing
pages), and honda2wheelersindia.com renders its list client-side with no URL in the document — its
manuals are the HMSI rows below. Honda US stays in `honda.py`; its CDN answers 403 to everything but
a Googlebot User-Agent, which is why `needsUa` exists.

The flow per region is the portal's own: model names, the model years behind each name, then the
PDF href on `/om/<CODE>/<model>/<year>`, which is a direct file on 2rom-prd-data.hondamotopub.com
(verified by magic bytes for HMSI, INDUMOT, FAHONDA and MAKPETROL)."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Iterator

import httpx

from ..models import RegistryEntry
from ._http import Throttle, client, get_json, get_text, keep_lang, log, pmap, slug

BASE = "https://www.hondamotopub.com"
SITE = "hondamotopub.com"
PDF_HREF = re.compile(r'href="(https://[^"]+\.pdf)"', re.I)
THROTTLE = Throttle(2.0)

# distributor code -> (market, manual language, label). Languages read off a sample manual per region.
REGIONS: dict[str, tuple[str, str, str]] = {
    "HMSI": ("IN", "en", "India"),
    "INDUMOT": ("EC", "es", "Ecuador"),
    "FAHONDA": ("GT", "es", "Guatemala"),
    "MAKPETROL": ("MK", "mk", "North Macedonia"),
}


def _region(c: httpx.Client, code: str) -> Iterator[RegistryEntry]:
    market, lang, label = REGIONS[code]
    xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/{code}"}
    models = get_json(c, f"{BASE}/ajax/get_model_names/{code}/all", headers=xhr, throttle=THROTTLE)
    if not isinstance(models, list) or not models:
        log.info("honda_intl %s: no models", code)
        return

    def years(model: str) -> list[tuple[str, str]]:
        quoted = urllib.parse.quote(str(model), safe="")
        found = get_json(c, f"{BASE}/ajax/get_data_model_code/{code}//{quoted}//om", headers=xhr, throttle=THROTTLE)
        seen = {str((r or {}).get("model_year") or "") for r in found or []}
        return [(str(model), y) for y in sorted(seen) if y.isdigit()]

    todo = [pair for group in pmap(years, models) for pair in group]

    def manual(pair: tuple[str, str]) -> tuple[str, str, str] | None:
        model, year = pair
        page = f"{BASE}/om/{code}/{urllib.parse.quote(model, safe='')}/{year}"
        hit = PDF_HREF.search(get_text(c, page, headers={"Referer": f"{BASE}/{code}"}, throttle=THROTTLE) or "")
        return (model, year, hit.group(1)) if hit else None

    found = 0
    for model, year, url in pmap(manual, todo):
        found += 1
        yield RegistryEntry(
            id=slug(SITE, code, model, year, lang, "owner"),
            make="Honda",
            model=model,
            years=[int(year)],
            market=market,
            type="owner",
            lang=lang,
            url=url,
            access="free",
            site=SITE,
            title=f"{model} {year} Owner's Manual ({label})",
        )
    log.info("honda_intl %s: %d models, %d model years, %d PDFs", code, len(models), len(todo), found)


def rows() -> Iterable[RegistryEntry]:
    with client() as c:
        get_text(c, BASE + "/")  # the ajax endpoints answer empty without the portal cookie
        for code, (_market, lang, _label) in REGIONS.items():
            if keep_lang(lang):
                yield from _region(c, code)
