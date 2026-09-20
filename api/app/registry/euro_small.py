"""The small European makers. Thirteen brands were checked; three publish something a crawler can
reach, and the other ten publish nothing at all - which is worth writing down once so nobody spends
an afternoon on them again.

| brand | what is there |
|---|---|
| **Sherco** | `sherco.com/en/download-documentation/manuals` - one page, every model year since 2001, ~93 PDFs on its own WordPress uploads. Owner's manuals and workshop manuals side by side, so the type is read off the file name. |
| **Benelli** | `benelli.com/int-en/manuals` - the current range, PDFs on `cdn.keeway.com`. The page is a Nuxt payload whose model names are index references, so the model is read off the file name (`EU5_LEONCINO800_USERMANUAL_WEB.pdf`), which carries it anyway. |
| **Beta** | `betamotor.com/en/manuals/` - VIN only, no index. `POST /wp-admin/admin-ajax.php action=vin_checker` with the page's nonce answers `{"success":true,"data":{"has_data":…,"html":…}}`; the html holds the document links for that one bike. Hence `resolve_vin` and no rows. |
| Moto Morini, Brixton, Ural, Janus, Norton, Mash, CCM, SWM, Fantic | nothing. Home page, every plausible `/manuals`, `/downloads`, `/owners`, `/support` path, and the sitemap where one exists - checked 2026-09-20, not one owner's-manual PDF between them. SWM answers 202 to everything (a WAF holding page), Fantic's `.it` domain 404s and its `.com` sitemap has 2,011 urls and no manual, CCM serves a 114-byte placeholder. |

Aprilia, Moto Guzzi, Vespa and Piaggio have their own module; see `piaggio.py`.
"""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable

from ..models import Bike, RegistryEntry
from ._http import BROWSER_UA, client, get_text, keep_lang, log, post_json, published_year, request, slug, years_in

# --- Sherco ---------------------------------------------------------------------------------------

SHERCO = "sherco.com"
SHERCO_PAGE = "https://www.sherco.com/en/download-documentation/manuals"
# <div id="manual-year-2018"> … <a href="…pdf"><h3>125 SE<span>200 pages</span></h3></a> …
SHERCO_BLOCK = re.compile(r'id="manual-year-(\d{4})"(.*?)(?=id="manual-year-\d{4}"|\Z)', re.S)
SHERCO_LINK = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>\s*<h3>([^<]*?)(?:<span>|</h3>)', re.I | re.S)
SERVICE = re.compile(r"service|workshop|atelier|werkstatt|maintenance|tech", re.I)

# --- Benelli --------------------------------------------------------------------------------------

BENELLI = "benelli.com"
BENELLI_PAGE = "https://www.benelli.com/int-en/manuals"
BENELLI_PDF = re.compile(r'https://cdn\.keeway\.com/[^"\'\s]+\.pdf', re.I)
# EU5_2020_USER_MANUAL_LEONCINO500_LEONCINO500TRAIL_WEB_v.01.pdf -> LEONCINO500 LEONCINO500TRAIL
BENELLI_NOISE = re.compile(r"(EU\d\+?|USER|MANUAL|USERMANUAL|WEB|v?\d+\.\d+|CBS|OWNERS?)", re.I)
MODEL_SPLIT = re.compile(r"(?<=[A-Za-z])(?=\d)")

# --- Beta -----------------------------------------------------------------------------------------

BETA = "betamotor.com"
BETA_PAGE = "https://www.betamotor.com/en/manuals/"
BETA_AJAX = "https://www.betamotor.com/wp-admin/admin-ajax.php?lang=en"
BETA_NONCE = re.compile(r'id="qtheme-search-vin-form_nonce"[^>]*value="([^"]+)"')
HREF = re.compile(r'href="([^"]+)"', re.I)
VIN_OK = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")


def _title(raw: str) -> str:
    return re.sub(r"\s{2,}", " ", htmllib.unescape(raw or "")).strip()


def _alive(c, url: str) -> bool:
    """Both pages link files that are no longer there - Sherco has a handful of 404s on its own
    archive and Benelli one. A registry row that 404s is worse than a missing one, so every URL is
    HEADed before it is emitted."""
    return request(c, "HEAD", url) is not None


def _sherco() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        page = get_text(c, SHERCO_PAGE)
        if not page:
            log.warning("sherco: manuals page unreachable")
            return
        seen: set[str] = set()
        for year, block in SHERCO_BLOCK.findall(page):
            for url, label in SHERCO_LINK.findall(block):
                model = _title(label)
                if not model or not url.lower().endswith(".pdf"):
                    continue
                kind = "service" if SERVICE.search(url.rsplit("/", 1)[-1]) else "owner"
                what = "Workshop Manual" if kind == "service" else "Owner's Manual"
                eid = slug(SHERCO, model, year, "eu", "en", kind)
                if eid in seen or not _alive(c, url):
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Sherco",
                    model=model,
                    years=[int(year)],
                    market="EU",
                    type=kind,
                    lang="en",
                    url=url,
                    access="free",
                    site=SHERCO,
                    title=f"{year} Sherco {model} {what}",
                )
        log.info("sherco: %d entries", len(seen))


def _benelli_model(url: str) -> str:
    """'…/EU5_2020_USER_MANUAL_LEONCINO500_LEONCINO500TRAIL_WEB_v.01.pdf' -> 'Leoncino 500'."""
    stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
    parts = [p for p in re.split(r"[_\-+]", stem) if p and not BENELLI_NOISE.fullmatch(p) and not re.fullmatch(r"(19|20)\d{2}", p)]
    if not parts:
        return ""
    spaced = MODEL_SPLIT.sub(" ", parts[0])
    return " ".join(w.capitalize() if w.isalpha() and len(w) > 3 else w.upper() for w in spaced.split())


def _benelli() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        page = get_text(c, BENELLI_PAGE)
        if not page:
            log.warning("benelli: manuals page unreachable")
            return
        seen: set[str] = set()
        for url in sorted(set(BENELLI_PDF.findall(page))):
            model = _benelli_model(url)
            if not model:
                continue
            if not _alive(c, url):
                continue
            years = years_in(url.rsplit("/", 1)[-1]) or [y for y in [published_year(c, url)] if y]
            eid = slug(BENELLI, model, years[0] if years else "", "eu", "en", "owner")
            if eid in seen:
                continue
            seen.add(eid)
            yield RegistryEntry(
                id=eid,
                make="Benelli",
                model=model,
                years=years,
                market="EU",
                type="owner",
                lang="en",
                url=url,
                access="free",
                site=BENELLI,
                title=f"Benelli {model} User Manual",
            )
        log.info("benelli: %d entries", len(seen))


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang("en"):
        return
    yield from _sherco()
    yield from _benelli()


# --- Beta, which is VIN only ----------------------------------------------------------------------


def beta_documents(vin: str) -> list[tuple[str, str]]:
    """(label, url) for every document Beta files against this frame number.

    Two calls: the manuals page carries a one-shot WordPress nonce, then `vin_checker` answers
    `{"success":true,"data":{"has_data":false,"vin":…,"html":""}}` for a frame number it does not
    know and the same shape with the document links in `html` for one it does."""
    if not VIN_OK.match((vin or "").upper()):
        return []
    with client(ua=BROWSER_UA) as c:
        page = get_text(c, BETA_PAGE)
        nonce = BETA_NONCE.search(page or "")
        if not nonce:
            log.warning("beta: no vin nonce on the manuals page")
            return []
        got = post_json(
            c,
            BETA_AJAX,
            data={"action": "vin_checker", "vin": vin.upper(), "qtheme-search-vin-form_nonce": nonce.group(1), "nonce": nonce.group(1)},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": BETA_PAGE},
        )
    body = (got or {}).get("data") if isinstance(got, dict) else None
    if not isinstance(body, dict) or not body.get("has_data"):
        return []
    markup = str(body.get("html") or "")
    out: list[tuple[str, str]] = []
    for href in HREF.findall(markup):
        if href.lower().split("?")[0].endswith(".pdf"):
            label = _title(re.sub(r"<[^>]+>", " ", markup.split(href, 1)[-1][:160]))
            out.append((label, href if href.startswith("http") else "https://www.betamotor.com" + href))
    return out


def resolve_beta(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    """Beta publishes no model index at all, so the frame number is the only key there is."""
    for label, url in beta_documents(vin or ""):
        if SERVICE.search(url) or SERVICE.search(label):
            continue
        return RegistryEntry(
            id=slug(BETA, bike.make, bike.model, bike.year, "en", "owner", (vin or "")[-6:]),
            make="Beta",
            model=bike.model,
            years=[bike.year] if bike.year else [],
            market=bike.market or "EU",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=BETA,
            title=label or f"Beta {bike.model} Owner's Manual",
        )
    return None
