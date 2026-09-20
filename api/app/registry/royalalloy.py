"""Royal Alloy - the British-Taiwanese scooter maker, and the only one of that cluster with a
public manual list.

royalalloy.com runs WordPress and answers `wp-json/wp/v2/media?media_type=application`, so every
document on the site comes back in one call with its upload date - the same trick `china.py` uses
for Kove, Voge and QJ. 39 files: the English operation / user manuals for the GP, GT and TG ranges,
two maintenance manuals, and the rest brochures, spec sheets and postcards that are filtered out
here rather than indexed as handbooks.

Two things the file names make necessary:
  * **the model year is in the document, not in WordPress.** Every manual is stamped with the date
    it was issued (`20200805`, `2018.7.26`, `APRIL 2023`); the whole library was re-uploaded on
    2024-08-10, so the WP date says nothing. ISSUE_DATE reads the stamp and falls back to the
    upload year only when there is none.
  * **one file covers several displacements.** `RA GP125S 200S Operation manual`,
    `GP125:200s MAINTENANCE MANUAL` and `GP125150180EFI20181215` each cover a whole range, so the
    scanner walks the name left to right, remembers the last family seen (GP/GT/TG) and emits one
    row per displacement it recognises. Displacements are matched against the sizes Royal Alloy
    actually sells (50/125/150/180/200/300) so a date can never be read as a model.

Sister brands checked at the same time and not indexed: Scomadi (no manual page, no sitemap),
Lambretta (WordPress, but its 18 documents are scooter *catalogues* - brochures, no handbook) and
Motron (WordPress, 4 documents, all for products it no longer lists). Written down so the next pass
skips them."""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable, Iterator
from typing import Any

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_json, keep_lang, log, slug

SITE = "royalalloy.com"
MEDIA = f"https://www.{SITE}/wp-json/wp/v2/media?media_type=application&per_page=100&page={{page}}"
MARKET = "GB"

FAMILIES = ("GP", "GT", "TG")
SIZES = ("300", "200", "180", "150", "125", "50")
SUFFIX = re.compile(r"^(SP|SE|S|AC|4V)\b", re.I)
# A handbook says so in its own name; everything else on the site is a brochure or a spec sheet.
IS_MANUAL = re.compile(r"(?:operation|user|owner'?s?|instruction|maintenance)[\s_-]*manual", re.I)
IS_SERVICE = re.compile(r"maintenance|workshop|service", re.I)
# 20200805 / 2018.7.26 / APRIL 2023 - the date the manual was issued, which is its model year.
ISSUE_DATE = re.compile(r"\b((?:19|20)\d{2})(?:[.\-/]?\d{1,2}[.\-/]?\d{1,2})?\b")
NOISE = re.compile(r"(?i)\b(euro\s*\d|eu\d|a5|efi|web|rev|v\d+|english|chinese|row)\b")
TOKEN = re.compile(r"(GP|GT|TG)|(\d{2,})|([A-Za-z]+)", re.I)


def _clean(title: str) -> str:
    text = htmllib.unescape(title or "")
    text = re.sub(r"[\uff08\uff09\u3001()\[\]]", " ", text)  # fullwidth and ASCII brackets
    text = re.sub(r"[^\x00-\x7f]+", " ", text)  # the CJK "\u82f1\u6587" (= "English") stamps
    return re.sub(r"\s{2,}", " ", NOISE.sub(" ", text)).strip()


def _models(title: str) -> list[str]:
    """Left to right: a family sticks until the next one, and a number is only a displacement if
    Royal Alloy sells that size. '20231107' therefore contributes nothing, 'GP125150180' three."""
    found: list[str] = []
    family = ""
    for fam, digits, word in TOKEN.findall(title):
        if fam:
            family = fam.upper()
            continue
        if word or not digits or not family:
            continue
        rest = digits
        while rest:
            for size in SIZES:
                if rest.startswith(size):
                    found.append(f"{family}{size}")
                    rest = rest[len(size) :]
                    break
            else:
                break  # a date or a part number, not a displacement list
    return list(dict.fromkeys(found))


def _year(title: str, uploaded: str) -> int | None:
    years = [int(y) for y in ISSUE_DATE.findall(title) if 1990 <= int(y) <= 2030]
    if years:
        return max(years)
    try:
        return int((uploaded or "")[:4])
    except ValueError:
        return None


def _documents() -> Iterator[dict[str, Any]]:
    with client(ua=BROWSER_UA) as c:
        for page in range(1, 6):
            items = get_json(c, MEDIA.format(page=page))
            if not isinstance(items, list) or not items:
                return
            yield from items
            if len(items) < 100:
                return


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang("en"):
        return
    seen: set[str] = set()
    count = 0
    # WordPress kept four uploads of some manuals ("...-1.pdf", "...-2.pdf"); the shortest url is
    # the original, so sorting by length makes the canonical copy the one that wins the id.
    for item in sorted(_documents(), key=lambda i: len(i.get("source_url") or "")):
        url = (item.get("source_url") or "").strip()
        title = _clean(item.get("title", {}).get("rendered", "") if isinstance(item.get("title"), dict) else "")
        if not url.lower().endswith(".pdf") or not IS_MANUAL.search(title):
            continue
        models = _models(title)
        year = _year(title, item.get("date") or "")
        if not models or not year:
            log.info("royalalloy: no model/year in %r", title)
            continue
        kind = "service" if IS_SERVICE.search(title) else "owner"
        for model in models:
            eid = slug(SITE, "royal-alloy", model, year, "en", kind)
            if eid in seen:
                continue
            seen.add(eid)
            count += 1
            yield RegistryEntry(
                id=eid,
                make="Royal Alloy",
                model=model,
                years=[year],
                market=MARKET,
                type=kind,
                lang="en",
                url=url,
                access="free",
                site=SITE,
                title="Royal Alloy %s %s Manual" % (model, "Maintenance" if kind == "service" else "Owner's"),
            )
    log.info("royalalloy: %d rows", count)
