"""Toyota, Lexus and Scion. One public JSON endpoint on toyota.com answers for all three.

    https://www.toyota.com/service/tcom/downloadableManuals/{series}/{year}

It is the call the `clientlib-tomanualswarranties` bundle makes on
`toyota.com/owners/warranty-owners-manuals/vehicle/{series}/{year}/` - no login, no VIN, no token.
The response is `data.{ownerManuals,navigationManuals,warrantyGuides,...}[].documents[]`, each with a
`contentLink` straight to `assets.sipb.toyota.com/publications/en/om-s/{CODE}/pdf/{CODE}.pdf`. That
host is plain static hosting: httpx gets the PDF with no headers at all.

Lexus shares the backend. `drivers.lexus.com` is a React shell whose manual page sits behind sign-in
and exposes no endpoint, but `downloadableManuals/rx350/2023` on **toyota.com** returns the Lexus
files (`L-MMS-…`, `Lexus 2023 RX350 …`). So Lexus needs no portal of its own, only its series slugs.

There is no series index anywhere - `globalnav/v2/vehicledata/en` lists only the 32 series on sale
today - so SERIES below is a hand-kept list and every (series, year) pair is asked. An unknown pair
answers 200 with an empty `data`, which costs one cheap request and nothing else. Years 1996-2028.

`om-x` links are the HTML reader for the same manual and drop out on the `.pdf` test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import Throttle, client, get_json, log, pmap, slug

API = "https://www.toyota.com/service/tcom/downloadableManuals/{series}/{year}"
SITE = "assets.sipb.toyota.com"
YEARS = range(1996, 2029)
# The handbook buckets only. `navigationManuals` (multimedia), `warrantyGuides` and `driversExcerpts`
# are real PDFs for the same model year and `pdf_index()` cannot rank them below the manual, so one of
# them would sometimes be served instead of it.
BUCKETS = ("ownerManuals", "omotaOwnersManualOverTheAir")
SKIP_TITLE = re.compile(r"warranty|maintenance guide|services guide|roadside|quick guide|quick reference|excerpt|pocket reference|propietario|solo para", re.I)
THROTTLE = Throttle(2.0)

TOYOTA = """4runner 4runnerhybrid avalon avalonhybrid bz bz4x bzwoodland camry camryhybrid camrysolara
celica c-hr chr corolla corollacross corollacrosshybrid corollahatchback corollahybrid corollaim
crown crownsignia echo fjcruiser grandhighlander grandhighlanderhybrid gr86 86 grcorolla grsupra
supra highlander highlanderhybrid landcruiser matrix mirai mr2 mr2spyder previa prius priusc priusv
priusprime priuspluginhybrid rav4 rav4hybrid rav4prime rav4pluginhybrid sequoia sequoiahybrid sienna
solara tacoma tacomahybrid tercel toyotacrown toyotacrownsignia tundra tundrahybrid venza yaris
yarishatchback yarisia yarisliftback t100 paseo pickup""".split()

LEXUS = """ct200h es250 es300 es300h es330 es350 gs200t gs300 gs350 gs430 gs450h gs460 gsf gx460 gx470
gx550 hs250h is200t is250 is300 is350 isc isf lc500 lc500h ls400 ls430 ls460 ls500 ls500h ls600h lfa
lx450 lx470 lx570 lx600 lx700h nx200t nx250 nx300 nx300h nx350 nx350h nx450h rc200t rc300 rc350 rcf
rx300 rx330 rx350 rx350h rx350l rx400h rx450h rx450hl rx500h rz300e rz450e sc300 sc400 sc430 tx350
tx500h tx550h ux200 ux250h ux300h lm500h""".split()

# The title names the brand reliably. It does NOT name the model reliably: Toyota folds the production
# window into it ("2003 4Runner From Apr. 2003 Prod."), so the model comes off the series slug instead.
MAKE = re.compile(r"^(Toyota|Lexus|Scion)\b", re.I)
# Slugs whose display name a rule cannot reach. Everything else falls out of _display().
NAMES = {
    "4runner": "4Runner",
    "4runnerhybrid": "4Runner Hybrid",
    "86": "86",
    "bz": "bZ",
    "bz4x": "bZ4X",
    "bzwoodland": "bZ Woodland",
    "c-hr": "C-HR",
    "fjcruiser": "FJ Cruiser",
    "gr86": "GR86",
    "grcorolla": "GR Corolla",
    "grsupra": "GR Supra",
    "landcruiser": "Land Cruiser",
    "lfa": "LFA",
    "mr2": "MR2",
    "mr2spyder": "MR2 Spyder",
    "pickup": "Pickup",
    "priusc": "Prius c",
    "priusv": "Prius v",
    "priusprime": "Prius Prime",
    "priuspluginhybrid": "Prius Plug-in Hybrid",
    "rav4": "RAV4",
    "rav4hybrid": "RAV4 Hybrid",
    "rav4prime": "RAV4 Prime",
    "rav4pluginhybrid": "RAV4 Plug-in Hybrid",
    "t100": "T100",
    "toyotacrown": "Crown",
    "toyotacrownsignia": "Crown Signia",
    "yarisia": "Yaris iA",
    "camrysolara": "Camry Solara",
    "corollaim": "Corolla iM",
    "chr": "C-HR",
    "isc": "IS C",
    "86": "86",
    "scion86": "86",
}
# corollacross -> Corolla Cross, tacomahybrid -> Tacoma Hybrid: the suffix is a trim, not a new model.
SUFFIX = ("hybrid", "hatchback", "cross", "signia", "liftback", "prime", "spyder", "highlander")
LEXUS_CODE = re.compile(r"^([a-z]{2})(\d{3})([a-z]{0,2})$")  # es350, nx300h, rz450e
LEXUS_F = re.compile(r"^([a-z]{2})f$")  # gsf -> GS F


def _display(series: str) -> str:
    if series in NAMES:
        return NAMES[series]
    if series in LEXUS:
        hit = LEXUS_CODE.match(series)
        if hit:
            return f"{hit.group(1).upper()} {hit.group(2)}{hit.group(3)}"
        f = LEXUS_F.match(series)
        if f:
            return f"{f.group(1).upper()} F"
        return series.upper()
    for tail in SUFFIX:
        if series.endswith(tail) and len(series) > len(tail):
            return f"{_display(series[: -len(tail)])} {tail.capitalize()}"
    return series.capitalize()


def _make(title: str, series: str) -> str:
    hit = MAKE.match(title or "")
    return hit.group(1).title() if hit else ("Lexus" if series in LEXUS else "Toyota")


def _fetch(job: tuple[str, int]) -> list[RegistryEntry]:
    series, year = job
    THROTTLE.wait()
    with client() as c:
        payload = get_json(c, API.format(series=series, year=year))
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    out: list[RegistryEntry] = []
    for bucket in BUCKETS:
        for pub in data.get(bucket) or []:
            if not isinstance(pub, dict):
                continue
            lang = str(pub.get("language") or "en").lower()
            for doc in pub.get("documents") or []:
                if not isinstance(doc, dict):
                    continue
                url = str(doc.get("contentLink") or "")
                title = str(doc.get("title") or pub.get("pubTitle") or "").strip()
                if doc.get("format") != "PDF" or not url.lower().endswith(".pdf") or SKIP_TITLE.search(title):
                    continue
                make, model = _make(title, series), _display(series)
                out.append(
                    RegistryEntry(
                        id=slug(SITE, make, model, year, "us", lang, "owner", url.rsplit("/", 1)[-1][:40]),
                        make=make,
                        model=model,
                        years=[year],
                        market="US",
                        type="owner",
                        lang=lang,
                        url=url,
                        access="free",
                        site=SITE,
                        title=title,
                        kind="car",
                    )
                )
    return out


def rows() -> Iterable[RegistryEntry]:
    jobs = [(s, y) for s in TOYOTA + LEXUS for y in YEARS]
    log.info("toyota: %d series years", len(jobs))
    seen: set[str] = set()
    for group in pmap(_fetch, jobs):
        for entry in group:
            if entry.id not in seen:
                seen.add(entry.id)
                yield entry
    log.info("toyota: %d rows", len(seen))
