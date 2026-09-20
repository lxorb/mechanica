"""The Indian volume makers publish their owner's manuals as plain files: Hero ships a JSON model
behind its AEM page, TVS and Bajaj simply link the PDFs. All three print English."""

from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_json, get_text, log, published_year, slug, years_in

HERO_JSON = "https://www.heromotocorp.com/content/hero-aem-website/in/en-in/services/owner-manual.model.json"
HERO_PDF = "https://www.heromotocorp.com/content/dam/hero-aem-website/in/service-owner-manual/{}"
HERO_SITE = "heromotocorp.com"

TVS_PAGE = "https://www.tvsmotor.com/our-service/user-manual"
TVS_SITE = "tvsmotor.com"
TVS_PDF = re.compile(r"(?:https://www\.tvsmotor\.com)?(/-/media/Feature/Owners/[^\"'<> ]+\.pdf)", re.I)

BAJAJ_PAGE = "https://www.bajajauto.com/customer-service/owners-manual"
BAJAJ_SITE = "bajajauto.com"
BAJAJ_PDF = re.compile(r"https://cdn\.bajajauto\.com/[^\"'<> ]+\.pdf", re.I)


def _title(stem: str) -> str:
    name = re.sub(r"[-_]+", " ", stem.replace("%20", " ")).strip()
    name = re.sub(r"(?i)\b(owners?|user)?\s*manual\b", "", name).strip()
    return re.sub(r"\s{2,}", " ", name).title()


def _find(node, key: str):
    """First value stored under `key` anywhere in the AEM page model."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


def hero() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        page = get_json(c, HERO_JSON)
    raw = _find(page, "ownermanualjson")
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        rows = None
    if not isinstance(rows, list):
        log.warning("hero: no owner manual list")
        return
    seen: set[str] = set()
    for row in rows:
        name = str((row or {}).get("Model_Name") or "").strip()
        file = str((row or {}).get("English_Version") or "").strip()
        if not name or not file:
            continue
        years = years_in(str(row.get("Year") or "")) or years_in(file)
        eid = slug(HERO_SITE, name, years[0] if years else "", "IN", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Hero",
            model=name,
            years=years,
            market="IN",
            type="owner",
            lang="en",
            url=HERO_PDF.format(file.lstrip("/")),
            access="free",
            site=HERO_SITE,
            title=f"{name} Owner's Manual {row.get('Month') or ''} {row.get('Year') or ''}".strip(),
        )
    log.info("hero: %d entries", len(seen))


def _scrape(c, page_url: str, site: str, make: str, pattern: re.Pattern[str], base: str = "") -> Iterable[RegistryEntry]:
    html = get_text(c, page_url) or ""
    seen: set[str] = set()
    for hit in sorted({m if isinstance(m, str) else m[0] for m in pattern.findall(html)}):
        url = htmllib.unescape(base + hit if hit.startswith("/") else hit)
        stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
        model = _title(stem)
        if not model:
            continue
        years = years_in(url) or [y for y in [published_year(c, url)] if y]
        eid = slug(site, model, years[0] if years else "", "IN", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make=make,
            model=model,
            years=years,
            market="IN",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=site,
            title=f"{model} Owner's Manual",
        )
    log.info("%s: %d entries", make.lower(), len(seen))


def tvs() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        yield from _scrape(c, TVS_PAGE, TVS_SITE, "TVS", TVS_PDF, base="https://www.tvsmotor.com")


def bajaj() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        yield from _scrape(c, BAJAJ_PAGE, BAJAJ_SITE, "Bajaj", BAJAJ_PDF)
