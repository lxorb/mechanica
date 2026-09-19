"""KTM, Husqvarna, GasGas: one AEM component, three sites. Free owner's-manual PDFs on the KTM CDN."""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_json, keep_lang, log, pmap, slug, split_year

BRANDS = {
    "ktm": ("KTM", "ktm.com", "https://www.ktm.com/en-us/service/manuals/_jcr_content/root/responsivegrid_1_col/bikemanuals"),
    "husqvarna": (
        "Husqvarna",
        "husqvarna-motorcycles.com",
        "https://www.husqvarna-motorcycles.com/en-us/service/user-manuals/_jcr_content/root/responsivegrid_1_col/bikemanuals",
    ),
    "gasgas": ("GasGas", "gasgas.com", "https://www.gasgas.com/en-us/service/manuals/_jcr_content/root/responsivegrid_1_col/bikemanuals"),
}

TITLE = re.compile(r"\s([A-Z]{2})\s\(([a-z]{2}(?:-[a-z]{2})?)\)")
FILE_LANG = re.compile(r"_([A-Za-z]{2})_(OM|RM|SM)\.pdf$", re.I)
MARKET_RANK = {"EU": 0, "US": 1, "GB": 2}


def _names(c, base: str) -> list[str]:
    found: set[str] = set()
    for bikes in pmap(lambda q: (get_json(c, f"{base}.suggestions.json", params={"query": q}) or {}), string.digits + string.ascii_lowercase):
        data = bikes.get("data") if isinstance(bikes, dict) else None
        for b in (data or {}).get("bikes", []) if isinstance(data, dict) else []:
            name = (b or {}).get("name")
            if name:
                found.add(name)
    return sorted(found)


def _rows(c, base: str, make: str, site: str, name: str) -> list[RegistryEntry]:
    payload = get_json(c, f"{base}.manuals.json", params={"modelName": name})
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    manuals = (data or {}).get("manuals", []) if isinstance(data, dict) else []
    model, years = split_year(name)
    best: dict[tuple[str, str], tuple[str, str]] = {}
    for m in manuals:
        link, title = (m or {}).get("link"), (m or {}).get("title") or ""
        if not link:
            continue
        hit = TITLE.search(title)
        lang = (hit.group(2) if hit else "").lower()
        if not lang:
            fl = FILE_LANG.search(link)
            lang = fl.group(1).lower() if fl else "en"
        if not keep_lang(lang):
            continue
        market = hit.group(1) if hit else "EU"
        key = (link, lang)
        prev = best.get(key)
        if prev is None or MARKET_RANK.get(market, 9) < MARKET_RANK.get(prev[0], 9):
            best[key] = (market, title)
    out: list[RegistryEntry] = []
    for (link, lang), (market, title) in best.items():
        kind = "service" if re.search(r"_(RM|SM)\.pdf$", link, re.I) else "owner"
        out.append(
            RegistryEntry(
                id=slug(site, model, years[0] if years else "", market, lang, kind),
                make=make,
                model=model,
                years=years,
                market=market,
                type=kind,
                lang=lang,
                url=link,
                access="free",
                site=site,
                title=title or name,
            )
        )
    return out


def _fetch(brand: str) -> Iterable[RegistryEntry]:
    make, site, base = BRANDS[brand]
    with client() as c:
        names = _names(c, base)
        log.info("%s: %d model years", brand, len(names))
        seen: set[str] = set()
        for rows in pmap(lambda n: _rows(c, base, make, site, n), names):
            for e in rows:
                if e.id not in seen:
                    seen.add(e.id)
                    yield e


def ktm() -> Iterable[RegistryEntry]:
    return _fetch("ktm")


def husqvarna() -> Iterable[RegistryEntry]:
    return _fetch("husqvarna")


def gasgas() -> Iterable[RegistryEntry]:
    return _fetch("gasgas")
