"""Royal Enfield: the owner's-manual page embeds the PDF path on each download button. No model year
is published, so years stay empty; the seed catalog supplies the model years."""

from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_text, log, slug

PAGES = {"us/en": "US", "in/en": "IN", "uk/en": "GB"}
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
        for path, market in PAGES.items():
            page = get_text(c, f"{BASE}/{path}/support/owners-manual/")
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
                    eid = slug(SITE, model, market, "en", "owner", variant)
                    if eid in seen:
                        continue
                    seen.add(eid)
                    found += 1
                    yield RegistryEntry(
                        id=eid,
                        make="Royal Enfield",
                        model=model,
                        years=[],
                        market=market,
                        type="owner",
                        lang="en",
                        url=url,
                        access="free",
                        site=SITE,
                        title=f"{model} Owner's Manual {variant}".strip(),
                    )
            log.info("royal_enfield %s: %d entries", market, found)
