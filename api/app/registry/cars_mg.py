"""MG Australia — the one MG market that publishes its handbooks as plain files.

`mgmotor.com.au/owners-manuals` links every current handbook straight off the page, as English PDFs
on the site's own `/brochures/` path (the folder name is the site's, not a description: these are
`*_Owners_Handbook.pdf`, not brochures). 18 files covering the whole current range.

The model is read off the file name, which is the only place MG prints it in a machine-readable
form: `MG_HS_Plus_EV_Owners_Handbook.pdf` -> `HS Plus EV`, `MGS5_EV_Owners_Handbook.pdf` -> `S5 EV`,
`IM5_Owners_Handbook.pdf` -> `IM5`. A trailing year is a model year (`MG_ZS_Owners_Handbook_2025`).

**The undated files.** Twelve of the eighteen carry no year, and MG's server sends **no
`Last-Modified`** (checked with HEAD and with a ranged GET — the header simply is not there), so
there is no date to read. Those rows are dated to the year they were crawled and titled "current
handbook", which is the only thing that can honestly be said about them: this is the book MG
Australia publishes for that model today. It is an approximation and it is marked as one, the same
way Royal Alloy falls back to its upload year. Re-crawling next year adds a row rather than moving
one, which is correct: MG will have published a new edition by then.

Checked at the same time and **not** indexed, so nobody re-walks them: `mgmotor.co.uk` and
`mg.co.uk` declare a sitemap with no manual tree; every other MG market site redirects into one of
those two. MG's Australian importer is the only one that publishes the files.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable, Iterator

from ..models import RegistryEntry
from ._http import client, get_text, keep_lang, log, slug

SITE = "mgmotor.com.au"
PAGE = f"https://{SITE}/owners-manuals"
MARKET = "AU"
LANG = "en"

PDF = re.compile(r"https?://[^\s\"'<>]*mgmotor\.com\.au/[^\s\"'<>]+\.pdf", re.I)
# MG_HS_Plus_EV_Owners_Handbook_2025.pdf -> stem "MG_HS_Plus_EV", year 2025
STEM = re.compile(r"(?i)[_-]*owner'?s?[_-]*(?:handbook|manual)[_-]*(?P<year>(?:19|20)\d{2})?\s*$")
# "MG3", "MGS5", "MG_HS" and plain "IM5" are all MG's own spellings of the same prefix.
BADGE = re.compile(r"(?i)^MG[_-]?")


def _model(url: str) -> str:
    stem = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    name = STEM.sub("", stem)
    name = BADGE.sub("", name) or stem
    return " ".join(name.replace("_", " ").replace("-", " ").split())


def _year(url: str) -> tuple[int, bool]:
    """(model year, whether MG printed it). An unprinted year is this year - see the module note."""
    stem = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    hit = STEM.search(stem)
    if hit and hit.group("year"):
        return int(hit.group("year")), True
    return datetime.date.today().year, False


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang(LANG):
        return
    yield from _rows()


def _rows() -> Iterator[RegistryEntry]:
    with client() as c:
        html = get_text(c, PAGE)
    if not html:
        log.warning("cars_mg: %s unreachable", PAGE)
        return
    seen: set[str] = set()
    count = 0
    for url in sorted(set(PDF.findall(html))):
        model = _model(url)
        year, printed = _year(url)
        if not model:
            log.info("cars_mg: no model in %s", url)
            continue
        eid = slug(SITE, model, year, LANG, "owner")
        if eid in seen:
            continue
        seen.add(eid)
        count += 1
        yield RegistryEntry(
            id=eid,
            make="MG",
            model=model,
            years=[year],
            market=MARKET,
            type="owner",
            lang=LANG,
            url=url,
            access="free",
            site=SITE,
            title=f"{year} MG {model} Owner's Handbook" if printed else f"MG {model} Owner's Handbook (current edition)",
            kind="car",
        )
    log.info("cars_mg: %d rows", count)
