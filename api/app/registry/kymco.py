"""Kymco USA: one page of owner's-manual uploads. The global site publishes catalogues only, and the
upload folder dates the manual because no model year is printed."""

from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_text, log, slug, years_in

PAGE = "https://kymcousa.com/manuals/owners/"
SITE = "kymcousa.com"
PDF = re.compile(r"https://kymcousa\.com/wp-content/uploads/[^\"'<> ]+\.pdf", re.I)
UPLOAD = re.compile(r"/uploads/((?:19|20)\d{2})/\d{2}/")
NOISE = re.compile(r"^(dealer_\d+_file_\d+_?)|[-_ ]*(owners?[-_ ]?manual|om)[-_ ]*\d*$", re.I)


def kymco() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        html = get_text(c, PAGE) or ""
    seen: set[str] = set()
    for url in sorted({htmllib.unescape(u) for u in PDF.findall(html)}):
        stem = NOISE.sub("", url.rsplit("/", 1)[-1].removesuffix(".pdf").replace("%20", " "))
        model = re.sub(r"[-_]+", " ", stem).strip()
        if not model or not model.isascii():
            continue
        upload = UPLOAD.search(url)
        years = years_in(model) or ([int(upload.group(1))] if upload else [])
        eid = slug(SITE, model, years[0] if years else "", "US", "en", "owner")
        if eid in seen:
            continue
        seen.add(eid)
        yield RegistryEntry(
            id=eid,
            make="Kymco",
            model=model,
            years=years,
            market="US",
            type="owner",
            lang="en",
            url=url,
            access="free",
            site=SITE,
            title=f"Kymco {model} Owner's Manual",
        )
    log.info("kymco: %d entries", len(seen))
