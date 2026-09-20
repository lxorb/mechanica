"""Honda: the US Sitecore downloads API (Akamai, wants a crawler UA) and the Motopub portal, which is
one site per Honda distributor - 37 region codes, each with its own model list and manual language."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import (
    GOOGLEBOT_UA,
    client,
    get_json,
    get_text,
    keep_lang,
    log,
    plausible_years,
    pmap,
    post_json,
    slug,
    years_in,
)

US = "https://powersports.honda.com"
US_SITE = "powersports.honda.com"
MOTORCYCLE_SEGMENT = "3"
BATCH = 25

EU = "https://www.hondamotopub.com"
EU_SITE = "hondamotopub.com"
PDF_HREF = re.compile(r'href="(https://[^"]+\.pdf)"', re.I)

# distributor code -> (market, manual language, label). The languages were read off a sample manual
# per region, not guessed: HPI/BSH/HMK/HMN/BWH/HSAF print English, HTW Chinese, MCT Hebrew, THM Thai.
REGIONS: dict[str, tuple[str, str, str]] = {
    "HMEE": ("EU", "en", "Europe"),
    "AHM": ("US", "en", "United States"),
    "HPI": ("PH", "en", "Philippines"),
    "BSH": ("MY", "en", "Malaysia"),
    "HSAF": ("ZA", "en", "South Africa"),
    "HMK": ("KE", "en", "Kenya"),
    "HMN": ("NG", "en", "Nigeria"),
    "BWH": ("NZ", "en", "New Zealand"),
    "HRCE": ("US", "en", "HRC Europe/US"),
    "HMEG": ("DE", "de", "Europe (German)"),
    "HMEF": ("FR", "fr", "Europe (French)"),
    "HMES": ("ES", "es", "Europe (Spanish)"),
    "HMEI": ("IT", "it", "Europe (Italian)"),
    "HMED": ("NL", "nl", "Europe (Dutch)"),
    "HMEPt": ("PT", "pt", "Europe (Portuguese)"),
    "HMEPl": ("PL", "pl", "Europe (Polish)"),
    "HMECz": ("CZ", "cs", "Europe (Czech)"),
    "HMESk": ("SK", "sk", "Europe (Slovak)"),
    "HMEGR": ("GR", "el", "Europe (Greek)"),
    "HTR": ("TR", "tr", "Turkey"),
    "MCT": ("IL", "he", "Israel"),
    "HTW": ("TW", "zh", "Taiwan"),
    "HKO": ("KR", "ko", "Korea"),
    "THM": ("TH", "th", "Thailand"),
    "HVN": ("VN", "vi", "Vietnam"),
    "AHJ": ("ID", "id", "Indonesia"),
    "NCXCA": ("KH", "km", "Cambodia"),
    "NCXMM": ("MM", "my", "Myanmar"),
    "HAR": ("AR", "es", "Argentina"),
    "FNA": ("CO", "es", "Colombia"),
    "HDP": ("PE", "es", "Peru"),
    "HMDC": ("CL", "es", "Chile"),
    "DIESA": ("PY", "es", "Paraguay"),
    "NANVEL": ("UY", "es", "Uruguay"),
    "VISAL": ("BO", "es", "Bolivia"),
    "HMJ": ("JP", "ja", "Japan"),
    "HRC": ("JP", "ja", "HRC Japan"),
}


def _token(c) -> str:
    payload = get_json(c, f"{US}/api/csrf/token")
    raw = (payload or {}).get("token", "") if isinstance(payload, dict) else ""
    hit = re.search(r'value="([^"]+)"', raw)
    return hit.group(1) if hit else ""


def honda_us() -> Iterable[RegistryEntry]:
    with client(ua=GOOGLEBOT_UA) as c:
        payload = get_json(c, f"{US}/api/sitecore/Downloads/GetOwnersManualFilters", params={"sc_site": "powersports"})
        result = (payload or {}).get("result") if isinstance(payload, dict) else None
        if not result:
            log.warning("honda_us: filters unavailable (Akamai?)")
            return
        wanted: list[dict] = []
        for seg in result.get("segments", []):
            if seg.get("id") != MOTORCYCLE_SEGMENT:
                continue
            for cat in seg.get("categories", []):
                for fam in cat.get("families", []):
                    for trim in fam.get("trims", []):
                        for m in trim.get("models", []):
                            wanted.append(
                                {
                                    "key": {"segment": seg["id"], "category": cat["id"], "family": fam["id"], "model": m["id"]},
                                    "family": fam.get("name") or trim.get("name") or m.get("brandLineName") or m["id"],
                                    "year": m.get("year"),
                                }
                            )
        token = _token(c)
        chunks = [wanted[i : i + BATCH] for i in range(0, len(wanted), BATCH)]

        def load(chunk: list[dict]):
            body = {"models": [m["key"] for m in chunk]}
            out = post_json(
                c,
                f"{US}/api/sitecore/Downloads/LoadOwnersManualsForTrims",
                json=body,
                headers={"__RequestVerificationToken": token, "Referer": f"{US}/owners/manuals"},
            )
            listing = ((out or {}).get("result") or {}).get("listing") or []
            return list(zip(chunk, listing))

        seen: set[str] = set()
        for pairs in pmap(load, chunks):
            for meta, block in pairs:
                trim = (block or {}).get("trimName") or f"{meta['year']} {meta['family']}"
                years = plausible_years(years_in(str(meta.get("year") or "")) or years_in(trim))
                model = re.sub(r"^\s*(?:19|20)\d{2}\s*", "", trim).strip() or meta["family"]
                for doc in (block or {}).get("listing", []):
                    url = (doc or {}).get("url")
                    if not url:
                        continue
                    eid = slug(US_SITE, model, years[0] if years else "", "en", "owner", url.rsplit("/", 1)[-1][:24])
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Honda",
                        model=model,
                        years=years,
                        market="US",
                        type="owner",
                        lang="en",
                        url=url,
                        access="free",
                        site=US_SITE,
                        title=doc.get("name") or trim,
                        needsUa="googlebot",  # the CDN answers 403 to every other User-Agent
                    )
        log.info("honda_us: %d entries", len(seen))


# Motopub is Honda's whole powersports catalogue, so a distributor also lists ATVs and side-by-sides.
# The product is motorcycles and cars, so those never become rows - see honda_intl.NOT_A_MOTORCYCLE,
# which is the same pattern for the same portal.
NOT_A_MOTORCYCLE = re.compile(
    r"(?i)(?:^|)(?:trx\d|fourtrax|four\s*trax|rancher|foreman|rubicon|recon|rincon|sportrax|"
    r"pioneer|talon|big\s*red|muv\d|sxs\d|atc\d|atv|utv|side\s*by\s*side)"
)


def _region(c, code: str) -> Iterable[RegistryEntry]:
    """One Motopub distributor: model names, the model years behind each, then the PDF on each page."""
    market, lang, label = REGIONS[code]
    xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{EU}/{code}"}
    models = get_json(c, f"{EU}/ajax/get_model_names/{code}/all", headers=xhr)
    if not isinstance(models, list) or not models:
        log.info("honda_eu %s: no models", code)
        return

    def years(model: str) -> list[tuple[str, str]]:
        quoted = urllib.parse.quote(str(model), safe="")
        rows = get_json(c, f"{EU}/ajax/get_data_model_code/{code}//{quoted}//om", headers=xhr)
        found = {str((r or {}).get("model_year") or "") for r in rows or []}
        # Motopub prints its own typos: AHM filed a 19YM guide under model year 5019. An impossible
        # year is skipped rather than guessed at - it would mint a catalog vehicle for year 5019.
        return [(str(model), str(y)) for y in plausible_years(found)]

    quads = [m for m in models if NOT_A_MOTORCYCLE.search(str(m))]
    if quads:
        log.info("honda_eu %s: skipping %d non-motorcycle model(s): %s", code, len(quads), ", ".join(map(str, quads[:8])))
    models = [m for m in models if not NOT_A_MOTORCYCLE.search(str(m))]
    todo = [p for group in pmap(years, models) for p in group]

    def manual(pair: tuple[str, str]):
        model, year = pair
        page = f"{EU}/om/{code}/{urllib.parse.quote(model, safe='')}/{year}"
        html = get_text(c, page, headers={"Referer": f"{EU}/{code}"})
        hit = PDF_HREF.search(html or "")
        return (model, year, hit.group(1)) if hit else None

    found = 0
    for model, year, url in pmap(manual, todo):
        found += 1
        yield RegistryEntry(
            id=slug(EU_SITE, code, model, year, lang, "owner"),
            make="Honda",
            model=model,
            years=[int(year)],
            market=market,
            type="owner",
            lang=lang,
            url=url,
            access="free",
            site=EU_SITE,
            title=f"{model} {year} Owner's Manual ({label})",
        )
    log.info("honda_eu %s: %d models, %d model years, %d PDFs", code, len(models), len(todo), found)


def honda_eu() -> Iterable[RegistryEntry]:
    """Every Motopub distributor whose manuals are in a language we keep."""
    with client() as c:
        get_text(c, EU + "/")  # the ajax endpoints answer empty without the portal cookie
        for code, (_market, lang, _label) in REGIONS.items():
            if keep_lang(lang):
                yield from _region(c, code)
