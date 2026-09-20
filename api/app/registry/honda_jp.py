"""Honda Japan's own owner's-manual portal — 119 nameplates, 668 model years, back to 1982.

`honda.co.jp/manual/` redirects to `/ownersmanual/HondaMotor/auto/`, whose search page loads its
whole catalogue from one static file: `./data/search.json`. That is the source of truth — the page
is only a renderer — and it needs no session, no VIN and no browser:

    CarCategoryMaster  2 entries (passenger / commercial)
    DocCategoryMaster  36 document kinds, each with IsViewPDF / IsViewWebOM / IsViewLink
    CarModelData       119 models -> ModelYears[] -> Docs[] {DocCategoryId, PDFFileName, PDFParameter}

`search.js` builds a document url as `#PDF_BASE + "/" + carModel.FolderName + "/" + doc.PDFFileName`
with `#PDF_BASE = "../../pdf/auto"`, i.e. `honda.co.jp/ownersmanual/pdf/auto/<folder>/<file>`. The
`PDFParameter` query string is analytics and is kept because the site sends it, not because the file
needs it. Verified by magic bytes.

**Model names.** Every name in the JSON is Japanese (`アヴァンシア`), and `slug()` strips non-ASCII, so
a Japanese name would collapse every model to the same empty id. `FolderName` is the romanisation
Honda itself uses (`avancier`, `accordtourer`, `civictyper`) and is unique per model, so the model
name is built from that. The split is data-driven rather than guessed: the base is the longest
*other* folder name that is a strict prefix (`accordtourer` -> `accord` + `tourer`), widened by the
prefixes two folders share (`acty` from `actytruck`/`actyvan`, `clarity` from `clarityphev`), so the
family always comes out of Honda's own list rather than a list somebody typed. SPELLING only fixes
how a remainder reads; a folder nothing splits stays one capitalised word.

These names are romanised Honda Japan nameplates and are not expected to match the US catalogue:
a JP `Fit` is not the US `Fit`s model year, and `alias_key()` will only ever join them where the
spelling genuinely agrees.

**Document kinds.** All 36 categories publish a PDF, and most of them are equipment booklets - ETC
transponder, wheelchair conversions, ACC/LKAS, the Internavi head unit. Only `オーナーズマニュアル`
and `オーナーズガイド` are the handbook, so DOC_KIND maps the categories explicitly and everything
unrecognised is a `supplement`: filed, searchable, and ranked below a real handbook by `_pick()`.

Japanese, so these never reach unattended English ingest - they exist for the language fallback,
which is the only offer 500-odd Honda Japan nameplates will ever have.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from ..models import RegistryEntry
from ._http import client, get_json, keep_lang, log, name_families, plausible_years, pretty_slug, slug

SITE = "honda.co.jp"
SEARCH = "https://www.honda.co.jp/ownersmanual/HondaMotor/auto/data/search.json"
PDF_BASE = "https://www.honda.co.jp/ownersmanual/pdf/auto"
MARKET = "JP"
LANG = "ja"

# Japanese category name -> docKind. Matched as a substring, first hit wins, so the order matters:
# "インターナビシステム（デジタルオーナーズマニュアル）" is the navigation book, not the handbook.
DOC_KIND: tuple[tuple[str, str], ...] = (
    ("簡単", "quickstart"),
    ("ナビ", "infotainment"),
    ("CONNECT", "infotainment"),
    ("ディスプレイ", "infotainment"),
    ("エンターテインメント", "infotainment"),
    ("追補", "supplement"),
    ("オーナーズマニュアル", "owner"),
    ("オーナーズガイド", "owner"),
)

# How a folder-name remainder is spelled once it has been split off its base. Spelling only.
SPELLING = {
    "typer": "Type R",
    "typereuro": "Type R Euro",
    "limitededition": "Limited Edition",
    "ehev": "e:HEV",
    "efcev": "e:FCEV",
    "phev": "PHEV",
    "plug-inhybrid": "Plug-in Hybrid",
    "fuelcell": "Fuel Cell",
    "delsol": "del Sol",
    "hatchback": "Hatchback",
    "sportscr-x": "Sports CR-X",
}
def families(folders: set[str]) -> set[str]:
    """Honda's folder list plus the families two folders share. See `_http.name_families`."""
    return name_families(folders)


def model_name(folder: str, known: set[str]) -> str:
    """`accordtourer` -> `Accord Tourer`, using Honda's own folder list to find the family."""
    return pretty_slug(folder, known, SPELLING)


def _kind(name: str) -> str:
    for needle, kind in DOC_KIND:
        if needle in name:
            return kind
    return "supplement"


def _catalogue() -> dict[str, Any] | None:
    with client() as c:
        data = get_json(c, SEARCH)
    if not isinstance(data, dict) or not data.get("CarModelData"):
        log.warning("honda_jp: search.json missing or empty")
        return None
    return data


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang(LANG):
        return
    data = _catalogue()
    if not data:
        return
    kinds = {c.get("Id"): _kind(str(c.get("Name") or "")) for c in data.get("DocCategoryMaster") or []}
    models = data["CarModelData"]
    folders = {str(m.get("FolderName") or "") for m in models} - {""}
    yield from _walk(models, families(folders), kinds)


def _walk(models: list[dict], known: set[str], kinds: dict[str, str]) -> Iterator[RegistryEntry]:
    seen: set[str] = set()
    count = 0
    for entry in models:
        folder = str(entry.get("FolderName") or "")
        if not folder:
            continue
        name = model_name(folder, known)
        for model_year in entry.get("ModelYears") or []:
            years = plausible_years([model_year.get("Year")])
            if not years:
                continue
            for doc in model_year.get("Docs") or []:
                file = str(doc.get("PDFFileName") or "")
                if not file.lower().endswith(".pdf"):
                    continue  # an IsViewLink row: an accessories page, not a document
                url = f"{PDF_BASE}/{folder}/{file}"
                param = str(doc.get("PDFParameter") or "")
                kind = kinds.get(doc.get("DocCategoryId"), "supplement")
                eid = slug(SITE, folder, years[0], doc.get("DocNo") or file[:20], LANG, "owner")
                if eid in seen:
                    continue
                seen.add(eid)
                count += 1
                yield RegistryEntry(
                    id=eid,
                    make="Honda",
                    model=name,
                    years=years,
                    market=MARKET,
                    type="owner",
                    lang=LANG,
                    url=f"{url}?{param}" if param else url,
                    access="free",
                    site=SITE,
                    title=f"{years[0]} Honda {name} {doc.get('DocNo') or ''}".strip(),
                    docKind=kind,
                    kind="car",
                )
    log.info("honda_jp: %d rows over %d nameplates", count, len(models))
