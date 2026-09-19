"""BMW Motorrad: one Nav.xml lists every rider's manual PDF. NAV-MODELL > MODELLJAHR > BA-SPRACHE."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, keep_lang, log, request, slug, years_in

NAV = "https://manuals.bmw-motorrad.com/manuals/BA-Extern/IN/BA-INTERNET-COM/01/Nav.xml"
PDF = "https://manuals.bmw-motorrad.com/manuals/BA-Extern/IN/BA-INTERNET-COM/PDF/{}"
SITE = "manuals.bmw-motorrad.com"
# Only the two BA-SPRACHE codes whose language is confirmed; the rest are skipped rather than guessed.
LANG = {"00": "de", "01": "en"}
MARKET = {"EUR": "EU", "USA": "US"}


def bmw() -> Iterable[RegistryEntry]:
    with client() as c:
        r = request(c, "GET", NAV)
    if r is None:
        return
    root = ET.fromstring(r.content)
    seen: set[str] = set()
    for node in root.iter("NAV-MODELL"):
        name = node.find("NAME")
        model = (node.get("T-BEZ") or (name.text if name is not None else "") or "").strip()
        if not model:
            continue
        market = MARKET.get(node.get("MARKT") or "", (node.get("MARKT") or "EU").upper())
        for period in node.findall("MODELLJAHR"):
            label = (period.find("NAME").text if period.find("NAME") is not None else "") or ""
            years = years_in(label)
            for sprache in period.findall("BA-SPRACHE"):
                lang = LANG.get(sprache.get("LANGUAGE") or "")
                filename = sprache.get("FILENAME")
                if not lang or not filename or not keep_lang(lang):
                    continue
                eid = slug(SITE, model, years[0] if years else "", market, lang, "owner", filename.rsplit(".", 1)[0])
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="BMW",
                    model=model,
                    years=years,
                    market=market,
                    type="owner",
                    lang=lang,
                    url=PDF.format(filename),
                    access="free",
                    site=SITE,
                    title=f"{model} {label}".strip(),
                )
    log.info("bmw: %d entries", len(seen))
