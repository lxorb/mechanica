"""Harley-Davidson. Two different doors, and only one of them is open.

**The catalogue.** H-D publishes its whole literature list as a SIP document - "H-D Technical
Publications Search Tool", document `2143353093339770523`. `/sip/content/document/view?id=<doc>`
redirects to the latest revision and the page's `<iframe>` points at
`/sip/service/archive/<revision>/index`, a little static app whose `data/simple.xml` is the list
itself: 7,648 items in five categories, **5,177 of them owner's manuals**, each with part number,
model year (sometimes a range like `2019-2025`), title and language, back to the 1980s. The archive
needs the `Referer` of its own index page; with it, no session and no login.

**The files.** `/api/documents/{id}` is public - it answers 200 with `links.pdfSnapshots[].link`,
a `document-pdf-print` URL carrying a guest `viewToken` that downloads the real PDF (verified: 206
`application/pdf`, `%PDF-1`). When a document has been revised it answers 303 with
`supersedingDocumentId` in the body, which this module follows.

**The gap.** Nothing public maps a part number to a document id. `/api/documents/lookup?reference=`,
`/api/document-groups/{id}` and `/api/vehicles/{vin}/groups` all answer 401 - from httpx and from a
real browser alike - and the SPA only gets a token through the dealer SAML login. `/sip/…/archive/…`
has no index of documents either. So the literature rows point at the portal's own lookup page (the
URL the official search tool links to, built by `_lookup_url` exactly as its `buildSIPUrl` does), and
the direct-PDF rows come from `SEED_DOCUMENTS` - document ids that are published on the open web -
resolved live through `/api/documents/{id}`.

**The VIN.** `/api/vehicles/{vin}` is public and needs no session: it answers `productVariantId`,
`year` and a printed name such as `2001 FAT BOY (FLSTF)` for a real VIN, and 404 for one that does
not exist. `resolve_vin` uses it to pin the bike, then hands back a seeded manual that covers that
model year and model family - or None, which is the honest answer for most VINs until an id index
turns up.
"""

from __future__ import annotations

import html as htmllib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from ..models import Bike, RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_json, log, request, slug

SITE = "serviceinfo.harley-davidson.com"
BASE = "https://" + SITE
LIT_DOC = "2143353093339770523"  # "H-D Technical Publications Search Tool"
VIEW = BASE + "/sip/content/document/view?id={}"
ARCHIVE = BASE + "/sip/service/archive/{}/"
LOOKUP = BASE + "/documents/lookup?reference={}"
API_DOC = BASE + "/api/documents/{}"
API_VIN = BASE + "/api/vehicles/{}"
LIMIT = Throttle(1.5)
IFRAME = re.compile(r'<iframe[^>]+src="/sip/service/archive/(\d+)/index"', re.I)
KEEP = {"Harley-Davidson Owner's Manuals", "Harley-Davidson Antique Manuals"}

# Straight out of the literature list's own app.js. Anything not here keeps its printed name and is
# emitted without a locale, exactly as the official tool does.
LOCALE = {
    "Arabic": "ar_SA", "Bulgarian": "bg_BG", "Chinese - Simplified": "zh_CN", "Chinese - Traditional": "zh_TW",
    "Croatian": "hr_HR", "Czech": "cs_CZ", "Danish": "da_DK", "Dutch": "nl_NL", "Estonian": "et_EE",
    "Finnish": "fi_FI", "French - Canadian": "fr_CA", "French - France": "fr_FR", "German": "de_DE",
    "Greek": "el_GR", "Hebrew": "iw_IL", "Hungarian": "hu_HU", "Indonesian": "in_ID", "Italian": "it_IT",
    "Japanese": "ja_JP", "Kazakh": "kk_KZ", "Korean": "ko_KR", "Latvian": "lv_LV", "Lithuanian": "lt_LT",
    "Malay": "ms_MY", "Maltese": "mt_MT", "Norwegian": "no_NO", "Polish": "pl_PL",
    "Portuguese - Brazilian": "pt_BR", "Portuguese - European": "pt_PT", "Romanian": "ro_RO",
    "Russian": "ru_RU", "Serbian": "sr_RS", "Slovak": "sk_SK", "Slovenian": "sl_SI",
    "Spanish - Mexico": "es_MX", "Spanish - Spain": "es_ES", "Spanish - Latin America": "es_ES",
    "Swedish": "sv_SE", "Tagalog": "tl_PH", "Thai": "th_TH", "Turkish": "tr_TR", "Ukrainian": "uk_UA",
    "Vietnamese": "vi_VN",
}
ENGLISH = {"English", "English - USA", "English - ROW"}

# SIP document ids that are published on the open web. Each is resolved live through /api/documents,
# so a superseded id still lands on the current revision and the title/year come from the portal.
SEED_DOCUMENTS = (
    "2189606049489551055",  # 2024 Softail
    "2002619033030595027",  # 2022 Softail
    "1952431857243129260",  # 2022 Sportster XL
    "1952428595076987306",  # 2022 Touring
    "1988672709839610317",  # 2025 FLHX / FLTRX
    "1996731879607425494",  # 2023 Touring
    "1813332900876539255",  # 2023 Touring
    "2193115001952353996",  # 2018 Touring
    "1807544128336925046",  # 2022 Touring
    "2171646486957299382",  # 2022 Touring
    "2193089816641572559",  # 2021 Touring
    "2209382997265015528",  # 2020 Touring
    "1996733376332304853",  # 2021 Touring
    "1465741334683008265",  # 2019 Touring
    "2143491773565139606",
)

YEAR = re.compile(r"(19|20)\d{2}")
TRAILING = re.compile(r"\s*owner'?s?\s+manual\s*$", re.I)


def _headers(referer: str) -> dict[str, str]:
    return {"Referer": referer, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _revision(c) -> str | None:
    """The literature list's current revision id, read off the viewer's own iframe."""
    r = request(c, "GET", VIEW.format(LIT_DOC), throttle=LIMIT)
    hit = IFRAME.search(r.text) if r is not None else None
    return hit.group(1) if hit else None


def _items(c, revision: str) -> list[tuple[str, dict[str, str]]]:
    """(category title, item attributes) for every row of data/simple.xml."""
    root = ARCHIVE.format(revision)
    r = request(c, "GET", root + "data/simple.xml", headers=_headers(root + "index"), throttle=LIMIT)
    if r is None:
        return []
    try:
        tree = ET.fromstring(r.content)
    except ET.ParseError as exc:
        log.warning("harley: literature list will not parse: %s", exc)
        return []
    return [((cat.get("title") or ""), dict(item.attrib)) for cat in tree.iter("category") for item in cat.findall("item")]


def _years(raw: str) -> list[int]:
    """'2019-2025' -> every year in the range; '2026' -> [2026]; anything else -> []."""
    found = [int(m.group(0)) for m in YEAR.finditer(raw or "")]
    if len(found) == 2 and found[1] > found[0] and found[1] - found[0] <= 40:
        return list(range(found[0], found[1] + 1))
    return sorted(set(found))


def _lookup_url(pn: str, lang: str, years: list[int]) -> str:
    """The URL the official search tool links to. Port of its buildSIPUrl(), suffix rules and all."""
    revisioned = bool(years) and min(years) < 2018
    ref, locale = pn, ""
    if lang in ENGLISH:
        if pn.endswith("US"):
            ref, locale = pn[:-2], "en_US"
        elif pn.endswith("EN"):
            ref, locale = pn[:-2], "en_GB"
    else:
        hit = re.match(r"^(.*\d)([A-Za-z]+)$", pn)
        if hit:
            base, suffix = hit.group(1), hit.group(2)
            if not revisioned or suffix.upper() == "FRCN":
                ref = base
            elif len(suffix) >= 3 or (len(suffix) == 2 and suffix[-1].upper() in "ABC"):
                ref = base + suffix[-1]
            elif len(suffix) == 1 and suffix.upper() in "ABC":
                ref = base + suffix
            else:
                ref = base
        locale = LOCALE.get(lang, "")
    url = LOOKUP.format(ref)
    return f"{url}&locale={locale}" if locale else url


def _market(locale: str) -> str:
    region = (locale.split("_")[-1] or "").upper()
    return region if len(region) == 2 and region.isalpha() else "US"


def _model(title: str) -> str:
    """The model out of a printed title, in both shapes the portal uses.

    '2026 FLHXLSE CVO Street Glide Limited Owner's Manual'        -> 'FLHXLSE CVO Street Glide Limited'
    "2024 HARLEY-DAVIDSON(R) OWNER'S MANUAL: SOFTAIL(R) MODELS"   -> 'SOFTAIL'
    """
    name = htmllib.unescape(title or "").replace("®", "").replace("™", "").strip()
    name = re.sub(r"^(19|20)\d{2}(\s*[-–]\s*(19|20)\d{2})?\s*", "", name)
    name = re.sub(r"^HARLEY-DAVIDSON\W+", "", name, flags=re.I)
    name = re.sub(r"^owner'?s?\s+manual\s*[:\-]\s*", "", name, flags=re.I)
    name = TRAILING.sub("", name)
    name = re.sub(r"\s+MODELS?\s*$", "", name, flags=re.I)
    return re.sub(r"\s{2,}", " ", name).strip(" :-")


def _document(c, doc_id: str, hops: int = 3) -> dict | None:
    """The live document record.

    A superseded id answers 303 with `supersedingDocumentId` in the *body* and no Location header,
    so this cannot go through `request()`/`get_json()` - their `raise_for_status()` treats any
    non-2xx as a failure and the pointer is lost. The status is read here instead."""
    for attempt in range(3):
        try:
            LIMIT.wait()
            r = c.get(API_DOC.format(doc_id), headers={"Accept": "application/json"})
            break
        except Exception:
            if attempt == 2:
                return None
    else:  # pragma: no cover - the loop always breaks or returns
        return None
    try:
        got = r.json()
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    if got.get("supersedingDocumentId") and hops:
        return _document(c, str(got["supersedingDocumentId"]), hops - 1)
    doc = got.get("document")
    return doc if isinstance(doc, dict) else None


def _pdf(doc: dict) -> str | None:
    """The downloadable snapshot, WORLD first.

    Two things the API's own link gets wrong for a registry row. The `viewToken` on it is a guest
    token that goes stale, and the bare `/document-pdf-print/{id}/{snapshot}/file` serves the same
    PDF cold - no token, no cookie, no session (checked: 206 `application/pdf`) - so it is dropped.
    And the last path segment is a free-form filename the server ignores (`file`, `x.xml` and
    `anything.pdf` all return the same bytes), so it is rewritten to the document's own reference
    with a `.pdf` on the end and the URL reads as, and is, a PDF."""
    snaps = ((doc.get("links") or {}).get("pdfSnapshots")) or []
    by_market = {str(s.get("market") or ""): s.get("link") for s in snaps if s.get("link")}
    link = by_market.get("WORLD") or by_market.get("DOM") or next(iter(by_market.values()), None)
    if not link:
        return None
    stem = link.split("?", 1)[0].rsplit("/", 1)[0]
    name = slug(doc.get("reference") or doc.get("id") or "manual")
    return f"{stem}/{name}.pdf"


def _seed_rows(c) -> Iterable[RegistryEntry]:
    seen: set[str] = set()
    for doc_id in SEED_DOCUMENTS:
        doc = _document(c, doc_id)
        url = _pdf(doc) if doc else None
        if not doc or not url:
            log.info("harley: seed %s has no public snapshot", doc_id)
            continue
        title = str(doc.get("title") or "")
        years = _years(title)
        locale = str(doc.get("language") or "en_US")
        eid = slug(SITE, _model(title), years[0] if years else "", _market(locale), locale.split("_")[0], "owner", str(doc.get("id"))[-8:])
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Harley-Davidson",
            model=_model(title),
            years=years,
            market=_market(locale),
            type="owner",
            lang=locale.split("_")[0].lower(),
            url=url,
            access="free",
            site=SITE,
            title=title,
        )


def rows() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        for entry in _seed_rows(c):
            yield entry
        revision = _revision(c)
        if not revision:
            log.warning("harley: literature list viewer gave no revision")
            return
        items = _items(c, revision)
        seen: set[str] = set()
        kept = 0
        for category, item in items:
            if category not in KEEP:
                continue
            pn, lang = (item.get("pn") or "").strip(), (item.get("lang") or "").strip()
            title = (item.get("title") or "").strip()
            if not pn or not title:
                continue
            years = _years(item.get("modYear") or "")
            locale = "en_US" if lang in ENGLISH else LOCALE.get(lang, "")
            url = _lookup_url(pn, lang, years)
            eid = slug(SITE, pn, years[0] if years else "", lang, "owner")
            if eid in seen:
                continue
            seen.add(eid)
            kept += 1
            yield RegistryEntry(
                id=eid,
                make="Harley-Davidson",
                model=_model(title),
                years=years,
                market=_market(locale),
                type="owner",
                lang=(locale.split("_")[0] or "en").lower(),
                url=url,
                access="free",
                site=SITE,
                title=f"{item.get('modYear') or ''} {title} ({pn})".strip(),
                needsUa="browser",
            )
        log.info("harley: %d literature rows from %d archive items (revision %s)", kept, len(items), revision)


# --- VIN -----------------------------------------------------------------------------------------

VIN_OK = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def vehicle(vin: str) -> dict | None:
    """What H-D itself says a VIN is. Public, no session; 404 when the VIN is not one of theirs."""
    if not VIN_OK.match((vin or "").upper()):
        return None
    with client(ua=BROWSER_UA) as c:
        got = get_json(c, API_VIN.format(vin.upper()), throttle=LIMIT, headers={"Accept": "application/json"})
    rows_ = (got or {}).get("vehicles") if isinstance(got, dict) else None
    first = rows_[0] if isinstance(rows_, list) and rows_ else None
    return first if isinstance(first, dict) else None


def resolve_vin(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    """VIN -> the owner's manual PDF, when a seeded document covers that model year and family.

    The VIN call itself always works; the manual only comes back when SEED_DOCUMENTS happens to
    carry the right book, because H-D publishes no public part-number -> document-id index."""
    found = vehicle(vin) if vin else None
    year = int(found.get("year") or 0) if found else (bike.year or 0)
    name = str((found or {}).get("name") or f"{bike.year} {bike.model}")
    words = {w for w in re.findall(r"[A-Za-z]{4,}", name.upper()) if w not in {"HARLEY", "DAVIDSON", "MODELS"}}
    with client(ua=BROWSER_UA) as c:
        for entry in _seed_rows(c):
            if year and year not in entry.years:
                continue
            title = (entry.title or "").upper()
            if words and not any(w in title for w in words):
                continue
            return entry
    return None
