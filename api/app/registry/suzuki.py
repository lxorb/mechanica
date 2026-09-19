"""Suzuki Germany: one CMS page per model year, each a link list of German rider's-handbook PDFs."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_json, log, pmap, slug

BASE = "https://motorrad.suzuki.de"
API = f"{BASE}/cms/api/delivery/de/GLOBAL/page"
SITE = "motorrad.suzuki.de"
YEARS = range(2016, 2026)


def _widgets(node, out: list) -> None:
    if isinstance(node, dict):
        if node.get("type") == "LinkListWidget":
            out.append(node)
        for v in node.values():
            _widgets(v, out)
    elif isinstance(node, list):
        for v in node:
            _widgets(v, out)


def suzuki() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:  # the CMS answers 400 to anything that is not a browser

        def page(year: int):
            url = f"{BASE}/informationen/dokumente/fahrerhandbuecher/{year}"
            return year, get_json(c, API, params={"url": url})

        seen: set[str] = set()
        for year, payload in pmap(page, YEARS):
            if not isinstance(payload, dict) or not payload.get("success"):
                continue
            widgets: list = []
            _widgets(payload.get("body"), widgets)
            for w in widgets:
                for item in (w.get("content") or {}).get("items") or []:
                    model = (item.get("text") or "").strip()
                    rel = (((item.get("download_file") or {}).get("de") or {}).get("full")) or ""
                    if not model or not rel:
                        continue
                    eid = slug(SITE, model, year, "DE", "de", "owner")
                    if eid in seen:
                        continue
                    seen.add(eid)
                    yield RegistryEntry(
                        id=eid,
                        make="Suzuki",
                        model=model,
                        years=[year],
                        market="DE",
                        type="owner",
                        lang="de",
                        url=rel if rel.startswith("http") else BASE + rel,
                        access="free",
                        site=SITE,
                        title=f"{model} {year} Fahrerhandbuch",
                    )
        log.info("suzuki: %d entries", len(seen))
