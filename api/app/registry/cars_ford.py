"""Ford and Lincoln. The whole library is public HTML; the PDFs sit on an Akamai host with one quirk.

`ford.com/support/owner-manuals-details/owner-manuals-library` lists every model year Ford still
publishes for - 786 of them for Ford, back to 1996. Each
`/support/owner-manuals-details/{model}/{year}/` page ships its document list as escaped JSON in the
server-rendered HTML (`"title": ..., "link": ..., "category": ..., "secondaryCategory": "PDF"`), so no
browser and no VIN are needed; the VIN box is only a shortcut to the same pages.

The PDFs live on `www.fordservicecontent.com/Ford_Content/Catalog/owner_information/*.pdf`.

The quirk, and it is the opposite of everywhere else (checked 2026-09-20): Akamai serves those files
to a *plain* client and drops the connection - a silent read timeout, not a 403 - for anything sending
a Chrome or Googlebot User-Agent. Our own crawler UA works, curl's default works, Chrome's does not.
So this adapter must NOT set `needsUa`; leaving it unset is what makes the ingest fetch succeed.

`.../vdirsnet/OwnerManual/Home/Index?Variantid=...` rows are the HTML reader for the same manual and
are skipped: `_is_pdf()` would reject them anyway.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from ..models import RegistryEntry
from ._http import Throttle, client, get_text, log, pmap, slug

BRANDS = {"Ford": "https://www.ford.com", "Lincoln": "https://www.lincoln.com"}
LIBRARY = "{base}/support/owner-manuals-details/owner-manuals-library"
DETAIL = "{base}/support/owner-manuals-details/{model}/{year}/"
SITE = "fordservicecontent.com"

PAIR = re.compile(r"owner-manuals-details/([a-z0-9][a-z0-9-]*)/((?:19|20)\d{2})")
DOC = re.compile(r'title\\":\\"(.*?)\\",\\"link\\":\\"(https://[^\\"]+?\.pdf)\\"', re.I)
# Warranty booklets and roadside guides ride along on the same pages and are not the owner's manual.
SKIP_TITLE = re.compile(r"warranty|roadside|scheduled maintenance|emission", re.I)
THROTTLE = Throttle(2.0)


def _pretty(model: str) -> str:
    """'super-duty' -> 'Super Duty', 'f-150' -> 'F-150', 'e-transit' -> 'E-Transit'."""

    def word(w: str) -> str:
        return w.upper() if any(c.isdigit() for c in w) or len(w) == 1 else w.capitalize()

    return " ".join("-".join(word(p) for p in tok.split("-")) for tok in model.split())


def _clean(title: str) -> str:
    return title.replace("\\u0026", "&").replace("�", "'").replace("\\/", "/").strip()


def _detail(make: str, base: str, model: str, year: int) -> list[RegistryEntry]:
    THROTTLE.wait()
    with client() as c:
        html = get_text(c, DETAIL.format(base=base, model=model, year=year))
    if not html:
        return []
    name = _pretty(model)
    out: list[RegistryEntry] = []
    seen: set[str] = set()
    for hit in DOC.finditer(html):
        title = _clean(hit.group(1))
        url = hit.group(2).replace("\\u0026", "&")
        if SKIP_TITLE.search(title) or url in seen:
            continue
        seen.add(url)
        out.append(
            RegistryEntry(
                id=slug(SITE, make, name, year, "us", "en", "owner", url.rsplit("/", 1)[-1][:60]),
                make=make,
                model=name,
                years=[year],
                market="US",
                type="owner",
                lang="en",
                url=url,
                access="free",
                site=SITE,
                title=f"{year} {make} {name} {title}",
                kind="car",
            )
        )
    return out


def _brand(make: str, base: str) -> Iterator[RegistryEntry]:
    with client() as c:
        library = get_text(c, LIBRARY.format(base=base))
    if not library:
        log.warning("ford: %s library unreachable", make)
        return
    pairs = sorted({(m.group(1), int(m.group(2))) for m in PAIR.finditer(library)})
    log.info("ford: %s %d model years", make, len(pairs))
    for group in pmap(lambda p: _detail(make, base, p[0], p[1]), pairs):
        yield from group


def rows() -> Iterable[RegistryEntry]:
    seen: set[str] = set()
    for make, base in BRANDS.items():
        for entry in _brand(make, base):
            if entry.id not in seen:
                seen.add(entry.id)
                yield entry
    log.info("ford: %d rows", len(seen))
