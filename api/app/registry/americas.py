"""The American brands that still publish a free handbook.

* **Polaris** (Indian Motorcycle, Victory) — polaris.com fronts three small endpoints behind
  Cloudflare: `api/owners-manual/brand/<b>/years`, `.../years/<year>` (model list) and a POST to
  `api/v2/owners-manual/brand/<b>` with the model numbers. The challenge is passed by fetching the
  owner's-manuals page first with browser headers and reusing the cookie jar, and the API call needs
  `Sec-Fetch-Site: same-origin` plus the page as `Referer`. Manuals come in a dozen languages, as a
  direct PDF on `cdn.polarisportal.com` and as an HTML twin; the PDF wins.
* **Can-Am** (BRP) — `operatorsguides.brp.com` is a plain PHP tree: category → model year → model →
  guide. `/readguide/<id>` answers `application/pdf` (it copies the file into `/public/tmp/` on the
  fly, so the tmp url it redirects to is *not* stable and must not be stored). The host therefore has
  to sit in `registry.PDF_HOSTS` for `free_owner_manuals()` to queue these.
* **LiveWire** — livewire.com/resources links every manual, but the document itself lives in
  Harley's SIP viewer (`/documents/lookup?reference=…`), an Angular app behind an OAuth login. The
  row records the free lookup page, not a PDF.
* **Buell** — buellmotorcycle.com puts owner support behind `ownersupport-login`; the pre-2010
  handbooks are on Harley's paid portal. Nothing free to index, so no rows.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable, Iterator

import httpx

from ..models import Bike, RegistryEntry
from ._http import BROWSER_UA, Throttle, client, get_json, get_text, keep_lang, log, pmap, request, slug, years_in

POLARIS = "https://www.polaris.com/en-us"
POLARIS_PAGE = f"{POLARIS}/owners-manuals/"
POLARIS_SITE = "polaris.com"
POLARIS_BRANDS = {"ind": "Indian", "vic": "Victory"}
API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": POLARIS_PAGE,
}
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
EU_REGIONS = {"DE", "FR", "IT", "ES", "NL", "FI", "SE", "NO", "DK", "PL", "PT", "GB", "IE", "AT", "CH", "BE"}
DROP_MODEL = re.compile(r"^(?:19|20)\d{2}\s|^(?:indian|victory)\s*(?:motorcycles?)?$", re.I)

BRP_SITE = "operatorsguides.brp.com"
BRP = f"https://{BRP_SITE}"
BRP_CATEGORIES = {"5": "Can-Am", "14": "Can-Am"}  # 3-Wheel Vehicles, Motorcycle
BRP_LINK = re.compile(r'<a href="(/[A-Za-z]+/\d+)"[^>]*>(?:\s|<[^>]*>)*<span class="text">([^<]*)</span>', re.S)
BRP_GUIDE = re.compile(r'<a href="(/readguide/\d+)"[^>]*>(?:\s|<[^>]*>)*<span class="text">([^<]*)</span>', re.S)
BRP_LANG = re.compile(r"^([A-Z]{2})\s*-")
BRP_NOISE = (
    re.compile(r"^\s*(?:19|20)\d{2}\s+|\s*,?\s*(?:19|20)\d{2}\s*$"),  # "2008 Spyder", "Ryker Series, 2023"
    re.compile(r"(?i)\s*\(?ce\)?\s*homologated\s*s?\s*$"),  # the EU homologation twin of the same guide
    re.compile(r"(?i)\s+series\b"),
    re.compile(r"(?i)^can[- ]?am\s+"),
)

LIVEWIRE_PAGE = "https://www.livewire.com/resources"
LIVEWIRE_SITE = "livewire.com"
LIVEWIRE_ROW = re.compile(r"<td>([^<]{6,120})</td>\s*<td[^>]*>\s*<a href=\"([^\"]*documents/lookup[^\"]+)\"", re.I)

throttle = Throttle(2.0)


# --- Polaris (Indian, Victory) -------------------------------------------------------------------


def _market(culture: str) -> str:
    region = (culture.split("-") + [""])[1].upper()
    if region == "US":
        return "US"
    return "EU" if region in EU_REGIONS else "WW"


def _models(name: str) -> list[str]:
    """'Victory Hammer / Vegas / High-Ball' -> three models; drop the make and the INTL suffix."""
    out: list[str] = []
    for part in str(name or "").split("/"):
        part = re.sub(r"\s+", " ", part).strip()
        part = re.sub(r"^(Indian|Victory)\s+(?=\S)", "", part, flags=re.I)
        part = re.sub(r"\s+INTL$", "", part, flags=re.I).strip()
        if part and not DROP_MODEL.match(part):
            out.append(part)
    return out


def _polaris_manuals(c: httpx.Client, brand: str, numbers: list[str]) -> list[dict]:
    r = request(c, "POST", f"{POLARIS}/api/v2/owners-manual/brand/{brand}", throttle=throttle, headers=API_HEADERS, content=json.dumps(numbers))
    if r is None:
        return []
    try:
        return [d for d in (r.json() or []) if isinstance(d, dict)]
    except Exception:
        return []


def _best(docs: list[dict]) -> list[dict]:
    """One document per language: the PDF if there is one, else the HTML twin. English always kept."""
    by_lang: dict[str, dict] = {}
    for d in docs:
        lang = (d.get("mediaCulture") or "en-US").split("-")[0].lower()
        old = by_lang.get(lang)
        if old is None or (old.get("mediaExtension") != "pdf" and d.get("mediaExtension") == "pdf"):
            by_lang[lang] = d
    english = {k: v for k, v in by_lang.items() if k == "en"}
    return list((english or by_lang).values()) + [v for k, v in by_lang.items() if k != "en" and english and keep_lang(k)]


def polaris() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA, headers=PAGE_HEADERS) as c:
        if request(c, "GET", POLARIS_PAGE, throttle=throttle) is None:
            log.warning("polaris: the owners-manuals page did not answer; skipping")
            return
        seen: set[str] = set()
        for brand, make in POLARIS_BRANDS.items():
            years = get_json(c, f"{POLARIS}/api/owners-manual/brand/{brand}/years", throttle=throttle, headers=API_HEADERS) or []
            jobs: list[tuple[int, str, str]] = []
            for year in sorted({int(y) for y in years if str(y).isdigit()}):
                models = get_json(c, f"{POLARIS}/api/owners-manual/brand/{brand}/years/{year}", throttle=throttle, headers=API_HEADERS) or []
                for m in models:
                    numbers = str((m or {}).get("ModelNumber") or "")
                    label = str((m or {}).get("ModelDescription") or "")
                    if numbers and label:
                        jobs.append((year, label, numbers))
            log.info("polaris %s: %d model years", brand, len(jobs))

            def fetch(job: tuple[int, str, str], brand: str = brand) -> tuple[tuple[int, str, str], list[dict]]:
                return job, _polaris_manuals(c, brand, job[2].split(","))

            count = 0
            for (year, label, _), docs in pmap(fetch, jobs):
                for doc in _best(docs):
                    url = (doc.get("mediaSourceURI") or "").strip()
                    if not url:
                        continue
                    lang = (doc.get("mediaCulture") or "en-US").split("-")[0].lower()
                    market = _market(doc.get("mediaCulture") or "en-US")
                    for model in _models(label):
                        eid = slug(POLARIS_SITE, make, model, year, lang, "owner")
                        if eid in seen:
                            continue
                        seen.add(eid)
                        count += 1
                        yield RegistryEntry(
                            id=eid,
                            make=make,
                            model=model,
                            years=[year],
                            market=market,
                            type="owner",
                            lang=lang,
                            url=url,
                            access="free",
                            site=POLARIS_SITE,
                            title=(doc.get("mediaTitle") or f"{year} {make} {model} Owner's Manual").replace(" (HTML)", "").replace(" (PDF)", ""),
                        )
            log.info("polaris %s: %d entries", brand, count)


# --- Can-Am (BRP operator's guides) --------------------------------------------------------------


def _brp_links(c: httpx.Client, path: str, pattern: re.Pattern[str] = BRP_LINK) -> list[tuple[str, str]]:
    html = get_text(c, BRP + path, throttle=throttle) or ""
    out: list[tuple[str, str]] = []
    for href, text in pattern.findall(html):
        label = htmllib.unescape(re.sub(r"\s+", " ", text)).strip()
        if label and label.lower() != "back":
            out.append((href, label))
    return out


def can_am() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        seen: set[str] = set()
        for category, make in BRP_CATEGORIES.items():
            for year_href, year_label in _brp_links(c, f"/P/{category}"):
                years = years_in(year_label)
                if not years:  # "Accessories", "Warranty Booklet"
                    continue
                for model_href, model_label in _brp_links(c, year_href):
                    model = model_label
                    for noise in BRP_NOISE:
                        model = noise.sub(" ", model)
                    model = re.sub(r"\s{2,}", " ", model).strip(" ,").title()
                    if not model or re.search(r"(?i)trailer|remorque|accessor", model_label):
                        continue
                    guides = _brp_links(c, model_href, BRP_GUIDE)
                    langs = {}
                    for guide_href, guide_label in guides:
                        hit = BRP_LANG.match(guide_label)
                        lang = (hit.group(1).lower() if hit else "en")
                        langs.setdefault(lang, (guide_href, guide_label))
                    wanted = [(k, v) for k, v in langs.items() if k == "en"] or list(langs.items())
                    wanted += [(k, v) for k, v in langs.items() if k != "en" and "en" in langs and keep_lang(k)]
                    for lang, (guide_href, guide_label) in wanted:
                        eid = slug(BRP_SITE, make, model, years[0], lang, "owner")
                        if eid in seen:
                            continue
                        seen.add(eid)
                        yield RegistryEntry(
                            id=eid,
                            make=make,
                            model=model,
                            years=years,
                            market="US",
                            type="owner",
                            lang=lang,
                            url=BRP + guide_href,
                            access="free",
                            site=BRP_SITE,
                            title=f"{years[0]} Can-Am {model} Operator's Guide",
                        )
        log.info("can-am: %d entries", len(seen))


# --- LiveWire --------------------------------------------------------------------------------------


def livewire() -> Iterator[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        html = get_text(c, LIVEWIRE_PAGE, throttle=throttle) or ""
    seen: set[str] = set()
    for title, url in LIVEWIRE_ROW.findall(html):
        label = htmllib.unescape(re.sub(r"\s+", " ", title)).replace("’", "'").strip()
        if "OWNER" not in label.upper() or "MANUAL" not in label.upper():
            continue
        years = years_in(label)
        model = re.sub(r"(?i)\s*models?$", "", label.split(":")[-1]).strip().title() or "All models"
        model = re.sub(r"(?i)^livewire\s+", "", model).strip() or "One"
        eid = slug(LIVEWIRE_SITE, "LiveWire", model, years[0] if years else "", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="LiveWire",
            model=model,
            years=years,
            market="US",
            type="owner",
            lang="en",
            url=htmllib.unescape(url),
            access="free",
            site=LIVEWIRE_SITE,
            title=label.title(),
        )
    log.info("livewire: %d entries", len(seen))


def rows() -> Iterable[RegistryEntry]:
    yield from polaris()
    yield from can_am()
    yield from livewire()


# --- live resolvers (registry.dynamic) -----------------------------------------------------------
# Both portals are crawlable, so these only cover what the crawl could not name: a trim the catalog
# spells differently, or a model year added after the last crawl. VIN is unused: neither endpoint
# takes one without a signed-in garage.


def _match(want: str, label: str) -> bool:
    names = [slug(n) for n in _models(label)] or [slug(label)]
    return any(n == want or want in n or n in want for n in names if n)


def resolve_polaris(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    brand = next((b for b, make in POLARIS_BRANDS.items() if make.lower() == bike.make.lower()), None)
    if not brand or not bike.year:
        return None
    with client(ua=BROWSER_UA, headers=PAGE_HEADERS) as c:
        if request(c, "GET", POLARIS_PAGE, throttle=throttle) is None:
            return None
        models = get_json(c, f"{POLARIS}/api/owners-manual/brand/{brand}/years/{bike.year}", throttle=throttle, headers=API_HEADERS) or []
        want = slug(bike.model)
        hit = next((m for m in models if _match(want, str((m or {}).get("ModelDescription") or ""))), None)
        if not hit:
            return None
        docs = _polaris_manuals(c, brand, str(hit.get("ModelNumber") or "").split(","))
    pdf = next((d for d in docs if d.get("mediaExtension") == "pdf" and str(d.get("mediaCulture", "")).lower().startswith("en")), None)
    if not pdf or not pdf.get("mediaSourceURI"):
        return None
    return RegistryEntry(
        id=slug(POLARIS_SITE, bike.make, bike.model, bike.year, "en", "owner"),
        make=bike.make,
        model=bike.model,
        years=[bike.year],
        market=bike.market or "US",
        type="owner",
        lang="en",
        url=str(pdf["mediaSourceURI"]),
        access="free",
        site=POLARIS_SITE,
        title=str(pdf.get("mediaTitle") or "").replace(" (PDF)", "") or f"{bike.year} {bike.make} {bike.model} Owner's Manual",
    )


def resolve_brp(bike: Bike, vin: str | None = None) -> RegistryEntry | None:
    if bike.make.lower() not in {"can-am", "can am", "canam", "brp"} or not bike.year:
        return None
    want = slug(bike.model)
    with client(ua=BROWSER_UA) as c:
        for category in BRP_CATEGORIES:
            year_href = next((h for h, label in _brp_links(c, f"/P/{category}") if str(bike.year) in label), None)
            if not year_href:
                continue
            for model_href, model_label in _brp_links(c, year_href):
                if want not in slug(model_label) and slug(model_label) not in want:
                    continue
                guide = next((h for h, label in _brp_links(c, model_href, BRP_GUIDE) if (BRP_LANG.match(label) or [None]) and label.upper().startswith("EN")), None)
                if not guide:
                    continue
                return RegistryEntry(
                    id=slug(BRP_SITE, bike.make, bike.model, bike.year, "en", "owner"),
                    make=bike.make,
                    model=bike.model,
                    years=[bike.year],
                    market=bike.market or "US",
                    type="owner",
                    lang="en",
                    url=BRP + guide,
                    access="free",
                    site=BRP_SITE,
                    title=f"{bike.year} Can-Am {bike.model} Operator's Guide",
                )
    return None
