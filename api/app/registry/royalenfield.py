"""Royal Enfield: the owner's-manual page embeds the PDF path on each download button. No model year
is printed anywhere on the site, so the year is taken from the slug when it carries one and from the
asset's Last-Modified date otherwise - these are the manuals for the bikes currently on sale."""

from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_text, keep_lang, log, published_year, slug, years_in

# market page -> (market, manual language). Only these paths exist; /xx/en 404s for the non-English
# markets, and Portugal files its manuals under after-sales instead of support.
PAGES: dict[str, tuple[str, str]] = {
    "us/en": ("US", "en"),
    "in/en": ("IN", "en"),
    "uk/en": ("GB", "en"),
    "au/en": ("AU", "en"),
    "ca/en": ("CA", "en"),
    "sg/en": ("SG", "en"),
    "ph/en": ("PH", "en"),
    "my/en": ("MY", "en"),
    "ae/en": ("AE", "en"),
    "za/en": ("ZA", "en"),
    "fr/fr": ("FR", "fr"),
    "es/es": ("ES", "es"),
    "it/it": ("IT", "it"),
    "de/de": ("DE", "de"),
    "mx/es": ("MX", "es"),
    "co/es": ("CO", "es"),
    "ar/es": ("AR", "es"),
    "br/pt": ("BR", "pt"),
    "th/th": ("TH", "th"),
    "tr/tr": ("TR", "tr"),
    "jp/ja": ("JP", "ja"),
}
AFTER_SALES = {"pt/pt": ("PT", "pt")}
BASE = "https://www.royalenfield.com"
SITE = "royalenfield.com"
BUTTON = re.compile(r"<button[^>]*id=\"manual-download\"[^>]*>", re.I)
ATTR = re.compile(r"(data-asset-url|data-json|data-pagepath)=\"([^\"]*)\"", re.I)
HEADING = re.compile(r"<h[23][^>]*>([^<]{2,60})</h[23]>", re.I)


def _model(head: str, pagepath: str, url: str) -> str:
    if pagepath:
        tail = pagepath.rstrip("/").rsplit("/", 1)[-1]
        if tail and tail not in ("en", "motorcycles"):
            return tail.replace("-", " ").title()
    heads = HEADING.findall(head)
    if heads:
        return htmllib.unescape(heads[-1]).strip()
    stem = url.rsplit("/", 1)[-1].removesuffix(".pdf")
    return re.sub(r"[-_]?(royal[-_]enfield|owners?[-_]manual|english|usa?|uk|india|eu)[-_]?", " ", stem).strip().title()


def royal_enfield() -> Iterable[RegistryEntry]:
    seen: set[str] = set()
    with client() as c:
        for path, (market, lang) in {**PAGES, **AFTER_SALES}.items():
            if not keep_lang(lang):
                continue
            section = "after-sales" if path in AFTER_SALES else "support"
            page = get_text(c, f"{BASE}/{path}/{section}/owners-manual/")
            if not page:
                continue
            found = 0
            for m in BUTTON.finditer(page):
                attrs = {k.lower(): htmllib.unescape(v) for k, v in ATTR.findall(m.group(0))}
                urls: list[tuple[str, str]] = []
                if attrs.get("data-asset-url"):
                    urls.append((attrs["data-asset-url"], ""))
                if attrs.get("data-json"):
                    try:
                        for item in json.loads(attrs["data-json"]):
                            if item.get("pdfAssetPath"):
                                urls.append((item["pdfAssetPath"], item.get("dropdownText") or ""))
                    except Exception:
                        pass
                head = page[max(0, m.start() - 1500) : m.start()]
                for rel, variant in urls:
                    url = rel if rel.startswith("http") else BASE + rel
                    model = _model(head, attrs.get("data-pagepath", ""), url)
                    eid = slug(SITE, model, market, lang, "owner", variant)
                    if eid in seen:
                        continue
                    seen.add(eid)
                    found += 1
                    years = years_in(url.rsplit("/", 1)[-1]) or [y for y in [published_year(c, url)] if y]
                    yield RegistryEntry(
                        id=eid,
                        make="Royal Enfield",
                        model=model,
                        years=years,
                        market=market,
                        type="owner",
                        lang=lang,
                        url=url,
                        access="free",
                        site=SITE,
                        title=f"{model} Owner's Manual {variant}".strip(),
                    )
            log.info("royal_enfield %s (%s): %d entries", market, lang, found)
