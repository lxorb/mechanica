"""Every part a mechanic would search for on one bike - not just the ten the manual printed a spec for.

  catalog(manual_id, bike) -> CatalogResult

Three sources, merged into one Part-compatible list:

  1. api/data/parts-taxonomy.json - a curated standard catalogue of wear/service/replacement parts,
     295 entries across motorcycles and cars, each narrowed by `applies` to the vehicles it exists on
     (a chain and two sprockets are not on a shaft-drive GS; a thermostat is not on an air-cooled twin;
     a carburettor is not on a 2024 EFI bike). The vehicle profile - kind, type, drive, cooling, fuel -
     is inferred from make/model/year by the same name rules web/counter/js/vehicle-type.js uses, ported
     below so the two files answer alike.
  2. the manual's own parts (ingest/assemble.py), which carry the printed spec, the OEM number and the
     page. A manual part that IS a taxonomy entry keeps its own id, spec and OEM - the printed number is
     always the better thing to shop for - and gains the group and the illustration.
  3. a mentions pass: where does this manual talk about this part? Section titles, section keywords and
     the page text are scanned for the entry's synonyms; every hit contributes {page, quote} and, when
     the line next to it prints a value ("16 Nm (11.8 lbf ft)"), that line becomes the entry's spec.
     No model is called for this - it is the manual's own words, matched.

Offers work for every row: /parts/offers falls back to standard_part() when the id is not one of the
manual's own, and builds the fitment-exact query from the entry's searchHint plus make/model/year.

Cost: zero. The optional map_ambiguous() (route "parts.map", one cheap structured call per manual) can
tie leftover manual parts to taxonomy ids; it is only ever run by api/tools/parts_catalog.py and its
answer is cached in the same blob.

Cache: parts_catalog/{manualId}.json in whichever store is configured. What is cached is the
bike-independent half - the mentions and the manual-part -> taxonomy-entry map - so one blob serves
every bike the manual covers and the per-bike applicability filter runs fresh on each request.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from .config import ROOT
from .ingest.assemble import links
from .models import Bike, Manual, Part, Section

TAXONOMY_PATH = ROOT / "data" / "parts-taxonomy.json"
CACHE_VERSION = 2
MAX_MENTIONS = 3
QUOTE_LEN = 180

# ---------------------------------------------------------------- vehicle rules
# Ported from web/counter/js/vehicle-type.js. Same order, same regexes: the first rule that matches
# wins, so a CRF450R is a motocrosser before it is a CRF, and a car never falls into a bike bucket.

TYPES = (
    "motocross", "enduro", "supermoto", "sportbike", "naked", "adventure", "touring",
    "cruiser", "scooter", "classic", "trial", "minibike", "car",
)
FALLBACK_TYPE = "naked"

BIKE_MAKES = {
    "yamaha", "honda", "kawasaki", "suzuki", "ktm", "harley-davidson", "harley", "triumph", "bmw",
    "ducati", "aprilia", "husqvarna", "gasgas", "gas-gas", "indian", "moto-guzzi", "royal-enfield",
    "hero", "mv-agusta", "victory", "can-am", "zero", "sherco", "kove", "tvs", "bajaj", "cake",
    "kymco", "vmoto", "qj-motor", "voge", "niu", "vespa", "piaggio", "benelli", "beta", "cfmoto",
    "sym", "lambretta", "norton", "buell", "bimota", "ural", "jawa", "rieju", "fantic", "swm",
}

RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern))
    for kind, pattern in (
        ("car", r"\b(corvette|stingray|camaro|mustang|porsche|ferrari|lamborghini|tesla|model [sy3x]\b)"),
        ("car", r"\b(chevrolet|chevy|ford|toyota|volkswagen|audi|mercedes|nissan|mazda|volvo|skoda|"
                r"renault|opel|fiat|jeep|dodge|chrysler|subaru|hyundai|kia|lexus|jaguar|land rover|"
                r"mini cooper|cupra)\b"),
        ("minibike", r"\b(grom|monkey|dax|msx ?125|z125|pw ?50|pw ?80|tt ?r ?50|crf ?50|crf ?110|kx ?65|"
                     r"mini ?moto|pocket ?bike|pit ?bike|ruckus|navi|trail ?125|ct ?125|super ?cub|sur ?ron|talaria)\b"),
        ("trial", r"\b(trial|txt ?racing|txt ?gp|cota|evo ?\d{3}$|raga|4rt|scorpa|beta evo)\b"),
        ("supermoto", r"\b(smc|supermoto|super ?motard|motard|hypermotard|husqvarna 701 supermoto|"
                      r"sm ?[rct]?\b|701 sm|dr ?z ?400 ?sm|fs ?450|sxv|rxv)\b"),
        ("motocross", r"\b(sx ?f?|yz ?\d{2,3}f?|kx ?\d{2,3}f?|rm ?z|cr ?f? ?\d{3} ?r|crf ?\d{3} ?r|"
                      r"mc ?\d{2,3}|fc ?\d{3}|tc ?\d{2,3}|mx ?\d|motocross|cross)\b(?! ?country)"),
        ("enduro", r"\b(exc|xc ?w|xcw|xc ?f?\b|wr ?\d{2,3}f?|wrf|crf ?\d{3} ?[xl]|fe ?\d{3}|te ?\d{3}|"
                   r"tx ?\d{3}|ec ?\d{3}|enduro|dr ?z|klx|ttr|xr ?\d{3}|tw ?200|serow|xt ?\d{3}|ec ?f|"
                   r"se ?\d ?f|beta rr|rr ?\d{3} ?racing|romeo|sef|sm ?r)\b"),
        ("scooter", r"\b(vespa|x ?max|xmax|n ?max|nmax|burgman|pcx|forza|sh ?\d{2,3}|tricity|tmax|t ?max|"
                    r"scooter|scoot|dio|activa|jupiter|beat|vario|lead|zoomer|metropolis|liberty|primavera|"
                    r"sprint|gts ?\d{3}|gtv|medley|beverly|typhoon|fly ?\d|agility|like ?\d|people|downtown|"
                    r"ak ?550|xciting|silver ?wing|majesty|kymco|piaggio|sym|lambretta|"
                    r"peugeot ?(kisbee|django|tweet)|c ?\d00 ?(gt|x)|ce ?0[24]|nqi|mqi|ujet|seat mo|moped|"
                    r"scarabeo|sr ?\d{2,3}|habana|mojito|rs ?\d ?scoot)\b"),
        ("adventure", r"\b(adventure|advent|\bgs\b|gsa|tenere|ténéré|africa twin|crf ?\d{4} ?l|versys|"
                      r"v ?strom|vstrom|dl ?\d{3,4}|tiger|multistrada|desert ?x|tuareg|klr|himalayan|scram|"
                      r"super ?adventure|norden|rally|transalp|varadero|caponord|stelvio|dominar|rx ?\d ?adv|"
                      r"nc ?\d{3} ?x|cb ?\d{3} ?x|tracer|f ?\d{3} ?gs|r ?\d{4} ?gs)\b"),
        ("touring", r"\b(gold ?wing|goldwing|k ?1600|fjr|\brt\b|glide|road ?king|roadmaster|pursuit|"
                    r"chieftain|challenger|voyager|vaquero|concours|trophy|st ?1300|nt ?\d{3,4}|tour|ltd|"
                    r"c ?650 ?gt|spyder|ryker|can ?am rt)\b"),
        ("cruiser", r"\b(rebel|vulcan|bolt|sportster|softail|dyna|fat ?boy|fatboy|breakout|low ?rider|"
                    r"street ?bob|nightster|forty ?eight|iron ?\d{3}|chief|scout|shadow|intruder|boulevard|"
                    r"marauder|vstar|v ?star|dragstar|bobber|speedmaster|rocket ?3|thunderbird|meteor|"
                    r"super ?meteor|shotgun|eliminator|vn ?\d{3,4}|c ?\d{2}b?|vt ?\d{3,4}|vtx|valkyrie|"
                    r"cruiser|chopper|diavel|xdiavel|x ?diavel|m ?109|volusia|savage|stryker|raider|"
                    r"roadstar|road ?star|phantom|aero|spirit|sabre|interstate|stateline|fury)\b"),
        ("classic", r"\b(bonneville|thruxton|scrambler|street ?twin|speed ?twin|t ?100|t ?120|classic|"
                    r"continental gt|interceptor|bullet|hunter ?350|cafe|caf[eé] ?racer|retro|vintage|"
                    r"w ?\d{3}|z ?\d{3} ?rs|xsr|sr ?400|sr ?500|gb ?\d{3}|cl ?\d{3}|v7|v9|nevada|envy|"
                    r"guzzi california|commando|le ?mans|bobber ?black)\b"),
        ("sportbike", r"\b(r ?[1367]\b|r ?1m|yzf|cbr|zx ?\d{1,2} ?r?|ninja|gsx ?r|gsxr|panigale|superleggera|"
                      r"supersport|rsv ?4|rsv|rs ?\d{3}|s ?1000 ?rr|f3 ?\d{3}|f4|rr\b|daytona|fireblade|"
                      r"hayabusa|gsx ?\d{4} ?r|zzr|sport|rc ?\d{3}|rc ?\d{2}|cbr ?\d{3,4}|ninja ?h2|h2 ?r|"
                      r"v4 ?s|superbike)\b"),
        ("naked", r"\b(mt ?\d{2}|mt ?\d{1,2}|\bz ?\d{3,4}\b|cb ?\d{3,4}|duke|street ?triple|speed ?triple|"
                  r"trident|monster|svartpilen|vitpilen|fz ?\d{1,2}|fz ?\d{3}|hornet|brutale|dragster|rivale|"
                  r"tuono|shiver|dorsoduro|naked|street ?fighter|streetfighter|gsx ?s|gs ?\d{3} ?s|"
                  r"\bs ?\d{3}\b|nk\b|cf ?\d{3}|vitesse|er ?\d n?|z ?h2|vmax|v ?max|ns ?\d{3}|pulsar|apache|"
                  r"raider ?125|gixxer|fz ?s)\b"),
    )
)

MAKE_DEFAULT = {
    "harley-davidson": "cruiser", "harley": "cruiser", "indian": "cruiser", "victory": "cruiser",
    "vespa": "scooter", "piaggio": "scooter", "kymco": "scooter", "sym": "scooter",
    "lambretta": "scooter", "niu": "scooter", "vmoto": "scooter", "can-am": "touring",
    "gasgas": "enduro", "gas-gas": "enduro", "sherco": "trial", "beta": "enduro", "rieju": "enduro",
    "royal-enfield": "classic", "moto-guzzi": "classic", "norton": "classic", "jawa": "classic",
    "ural": "classic", "husqvarna": "enduro", "ktm": "naked", "mv-agusta": "sportbike",
    "hero": "naked", "tvs": "naked", "bajaj": "naked", "chevrolet": "car",
}

# --- how the vehicle is driven, cooled and fed. Not in vehicle-type.js: it decides which taxonomy
# entries exist on this bike at all, which is a parts question rather than a silhouette question.

SHAFT = re.compile(
    r"\b(gold ?wing|goldwing|valkyrie|st ?1300|st ?1100|nt ?\d{3,4}|ctx ?\d{3,4}|vfr ?1200|"
    r"fjr ?\d{3,4}|xt ?1200|super ?t[eé]n[eé]r[eé]|vmax|v ?max|gtr ?\d{3,4}|concours|"
    r"boulevard c\d|m ?109|intruder|c ?50|c ?90|"
    r"r ?\d{2,4}\b|k ?\d{3,4}\b|ural|cardan|shaft ?drive|guzzi)\b"
)
BELT = re.compile(
    r"\b(softail|sportster|dyna|glide|road ?king|fat ?boy|fatboy|breakout|low ?rider|street ?bob|"
    r"nightster|forty ?eight|iron ?\d{3}|pan ?america|chief|scout|roadmaster|chieftain|challenger|"
    r"vulcan ?1700|vulcan ?900|v ?star|vstar|dragstar|road ?star|roadstar|stryker|raider|"
    r"buell|zero ?s|zero ?ds|zero ?sr|belt ?drive)\b"
)
AIR_COOLED = re.compile(
    r"\b(nine ?t|r ?12\b|r ?12 ?g|r ?18|r ?nine|grom|monkey|dax|super ?cub|ct ?125|trail ?125|navi|"
    r"sr ?400|sr ?500|w ?800|w ?650|bullet|classic ?350|meteor ?350|hunter ?350|super ?meteor|shotgun|"
    r"interceptor ?650|continental ?gt ?650|scrambler ?icon|monster ?797|sportster|softail|dyna|"
    r"fat ?boy|fatboy|road ?king|street ?bob|forty ?eight|iron ?\d{3}|ural|jawa|xt ?\d{3}|tw ?200|"
    r"serow|sr ?125|gn ?125|cg ?125|air ?cooled)\b"
)
WATER_COOLED_OVERRIDE = re.compile(r"\b(pan ?america|revolution|v ?rod|vrod|live ?wire|himalayan ?450|rally ?450)\b")
DIESEL = re.compile(r"\b(tdi|tdci|hdi|cdi|dci|crdi|d4d|bluetec|blue ?motion|diesel|jtd|multijet|dci|xdi)\b")

EFI_FROM = 2008  # a road bike sold new after this is fuel injected, near enough for a parts list


def fold(value: str | None) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[\s-]+", "-", str(value or "").lower()))


def flat(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


class Profile(BaseModel):
    """What the taxonomy is filtered against."""

    kind: str = "motorcycle"
    type: str = FALLBACK_TYPE
    drive: str = "chain"
    cooling: str = "liquid"
    fuel: list[str] = []


def type_of(bike: Bike | None) -> str:
    """Same answer as vehicle-type.js typeOf() for the name heuristics and the make default."""
    if bike is None:
        return FALLBACK_TYPE
    make = fold(bike.make)
    text = flat(f"{bike.make} {bike.model}")
    is_bike_make = make in BIKE_MAKES
    for kind, pattern in RULES:
        if kind == "car" and is_bike_make:
            continue
        if pattern.search(text):
            return kind
    return MAKE_DEFAULT.get(make, FALLBACK_TYPE)


def profile_of(bike: Bike | None) -> Profile:
    if bike is None:
        return Profile(fuel=["efi", "petrol"])
    vehicle = type_of(bike)
    kind = (bike.kind or ("car" if vehicle == "car" else "motorcycle")).lower()
    text = flat(f"{bike.make} {bike.model}")
    make = fold(bike.make)

    if kind == "car":
        fuel = ["diesel", "efi"] if DIESEL.search(text) else ["petrol", "efi"]
        return Profile(kind="car", type="car", drive="shaft", cooling="liquid", fuel=fuel)

    if vehicle == "scooter":
        drive = "belt"
    elif BELT.search(text) or make in {"harley-davidson", "harley", "indian", "victory"}:
        drive = "belt"
    elif SHAFT.search(text) and make in {"bmw", "moto-guzzi", "honda", "yamaha", "suzuki", "kawasaki", "ural"}:
        drive = "shaft"
    else:
        drive = "chain"

    if WATER_COOLED_OVERRIDE.search(text):
        cooling = "liquid"
    elif AIR_COOLED.search(text) or make in {"ural", "jawa"}:
        cooling = "air"
    else:
        cooling = "liquid"

    fuel = ["efi"] if (bike.year or 0) >= EFI_FROM else ["carb"]
    return Profile(kind="motorcycle", type=vehicle, drive=drive, cooling=cooling, fuel=[*fuel, "petrol"])


# ---------------------------------------------------------------- taxonomy


class Applies(BaseModel):
    kind: str
    types: list[str] | None = None
    notTypes: list[str] | None = None
    drive: list[str] | None = None
    cooling: list[str] | None = None
    fuel: list[str] | None = None


class TaxonomyPart(BaseModel):
    id: str
    name: str
    group: str
    icon: str
    applies: Applies
    searchHint: str
    synonyms: list[str] = []


class Taxonomy(BaseModel):
    version: int = 1
    note: str = ""
    groups: list[dict]
    parts: list[TaxonomyPart]


_taxonomy: Taxonomy | None = None
_by_id: dict[str, TaxonomyPart] = {}


_fingerprint = ""


def taxonomy() -> Taxonomy:
    global _taxonomy, _fingerprint
    if _taxonomy is None:
        raw = TAXONOMY_PATH.read_text(encoding="utf-8")
        _taxonomy = Taxonomy.model_validate(json.loads(raw))
        _fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        _by_id.clear()
        _by_id.update({p.id: p for p in _taxonomy.parts})
    return _taxonomy


def fingerprint() -> str:
    """Which taxonomy a cached scan was made against: edit the file and every cache is stale."""
    taxonomy()
    return _fingerprint


def entry(part_id: str) -> TaxonomyPart | None:
    taxonomy()
    return _by_id.get(part_id)


def group_order() -> list[str]:
    return [g["id"] for g in taxonomy().groups]


def group_label(group_id: str) -> str:
    return next((g["label"] for g in taxonomy().groups if g["id"] == group_id), group_id.title())


def applicable(part: TaxonomyPart, profile: Profile) -> bool:
    rule = part.applies
    if rule.kind != profile.kind:
        return False
    if rule.types and profile.type not in rule.types:
        return False
    if rule.notTypes and profile.type in rule.notTypes:
        return False
    if rule.drive and profile.drive not in rule.drive:
        return False
    if rule.cooling and profile.cooling not in rule.cooling:
        return False
    if rule.fuel and not set(rule.fuel) & set(profile.fuel):
        return False
    return True


def parts_for(profile: Profile) -> list[TaxonomyPart]:
    return [p for p in taxonomy().parts if applicable(p, profile)]


# The icon rules of web/counter/js/particons.js, for the rows the taxonomy has no entry for. Ordered:
# the specific reading of a word sits above the loose one ("chain lube" above "chain").
_ICON_RULES: tuple[tuple[str, str], ...] = (
    ("chain-lube", r"chain ?(?:lube|spray|lubricant)|chainlube"),
    ("cleaner-spray", r"clean(?:er|ing)|degreas"),
    ("brake-fluid", r"brake fluid|\bdot ?[45]"),
    ("brake-pads", r"brake (?:pad|lining|shoe)"),
    ("brake-disc", r"brake (?:disc|disk|rotor)"),
    ("brake-caliper", r"calip|master cylinder"),
    ("clutch-cable", r"clutch cable"),
    ("clutch-lever", r"clutch"),
    ("throttle-cable", r"throttle|twist ?grip|bowden"),
    ("oil-filter", r"oil filter|oil screen|oil strainer"),
    ("fork-oil", r"fork oil"),
    ("gear-oil", r"gear oil|final drive oil|transmission oil"),
    ("engine-oil", r"engine oil|motor oil|oil"),
    ("air-filter", r"air (?:filter|cleaner|box)"),
    ("fuel-filter", r"fuel filter"),
    ("spark-plug", r"spark ?plug"),
    ("front-fork", r"\bforks?\b|telescopic|stanchion"),
    ("rear-shock", r"shock|suspension|damper|preload"),
    ("swingarm", r"swing ?arm"),
    ("sprocket", r"sprocket|chain ?wheel"),
    ("chain", r"\bchains?\b"),
    ("tire", r"\btyres?\b|\btires?\b|tread"),
    ("wheel", r"\bwheels?\b|\brims?\b|spoke"),
    ("bearing", r"bearing|steering head"),
    ("battery", r"batter|charger|\bagm\b"),
    ("fuse", r"\bfuses?\b"),
    ("bulb-headlight", r"head ?(?:light|lamp)|\bbulbs?\b|beam"),
    ("taillight", r"tail ?(?:light|lamp)|indicator|flasher|plate light"),
    ("coolant", r"coolant|antifreeze"),
    ("radiator", r"radiator|\bcooler\b|\bfans?\b"),
    ("fuel-tank", r"\bfuel\b|petrol|gasolin|filler cap|\btanks?\b"),
    ("exhaust", r"exhaust|muffler|silencer|catalyt"),
    ("mirror", r"mirror"),
    ("handlebar", r"handle ?bar|\bgrips?\b|bar end"),
    ("seat", r"\bseats?\b|saddle|pillion"),
    ("footpeg", r"foot ?(?:peg|rest|board)"),
    ("grease", r"\bgrease\b|lubricat"),
    ("threadlock", r"loctite|thread ?lock|locking compound"),
    ("bolt-torque", r"torque|\bscrews?\b|\bbolts?\b|\bnuts?\b|fastener"),
    ("tool-kit", r"\btools?\b|repair kit"),
)
_ICON_PATTERNS = tuple((icon, re.compile(pattern, re.I)) for icon, pattern in _ICON_RULES)


def icon_for(text: str) -> str:
    haystack = flat(text)
    for icon, pattern in _ICON_PATTERNS:
        if pattern.search(haystack):
            return icon
    return "generic-part"


def group_of_icon(icon: str) -> str:
    """Whichever group the taxonomy files that illustration under; consumables when nothing does."""
    return next((p.group for p in taxonomy().parts if p.icon == icon), "consumables")


# ---------------------------------------------------------------- the mentions pass

_STOP = {
    "the", "of", "and", "for", "to", "in", "on", "with", "a", "an", "at", "is", "or", "front",
    "rear", "left", "right", "upper", "lower", "set", "kit", "new", "one", "two",
}
_VALUE = re.compile(
    r"\d[\d.,]*\s*(?:nm|lbf|ft ?lb|bar|psi|kpa|mm|cm|in\b|l\b|ml|qt|fl|oz|v\b|ah|a\b|w\b|"
    r"km|mi|kg|lb|°c|°f|%)",
    re.I,
)
# A torque is worth quoting and worthless to shop by: "M6 11 Nm" must never become a search query.
_TORQUE = re.compile(r"\b(?:nm|lbf|ft ?lbs?)\b", re.I)
# What a part is actually bought by when the manual prints it: a grade, a size, a capacity.
_GRADE = re.compile(
    r"\b(?:sae|jaso|dot ?[45]|api ?s[a-z]|\d{1,2}w[-/ ]?\d{2}|\d{3}/\d{2} ?[a-z]{1,2} ?r ?\d{2}|"
    r"\d+(?:[.,]\d+)? ?(?:l|ml|qt|fl|bar|psi|v|ah|a|w|mm)\b)",
    re.I,
)
# Table-of-contents leaders: "Exhaust system.............. 42" is a page number, not a spec.
_LEADERS = re.compile(r"\.{4,}|·{4,}|_{4,}")
_WORD = re.compile(r"[a-z0-9]+")


_compiled: dict[str, tuple[re.Pattern[str], set[str]]] = {}


def matcher(part: TaxonomyPart) -> tuple[re.Pattern[str], set[str]]:
    """(regex, probe words) for one entry, built once and kept - warming 500 manuals compiles 295
    regexes, not 147,500."""
    hit = _compiled.get(part.id)
    if hit is None:
        hit = _compiled[part.id] = (_pattern(part), _probes(part))
    return hit


def _pattern(part: TaxonomyPart) -> re.Pattern[str]:
    """One alternation per entry: every synonym, whitespace-tolerant, plural-tolerant, word-bounded."""
    alts = []
    for phrase in part.synonyms:
        words = [w for w in re.split(r"[^a-z0-9]+", phrase.lower()) if w]
        if not words:
            continue
        body = r"[\s\-/]+".join(re.escape(w) for w in words)
        if not words[-1].endswith("s") and len(words[-1]) > 2:
            body += "s?"
        alts.append(body)
    if not alts:
        alts = [re.escape(part.name.lower())]
    return re.compile(r"\b(?:" + "|".join(sorted(set(alts), key=len, reverse=True)) + r")\b", re.I)


def _probes(part: TaxonomyPart) -> set[str]:
    """The words that must appear somewhere on the page before its regex is worth running."""
    out: set[str] = set()
    for phrase in part.synonyms:
        for word in re.split(r"[^a-z0-9]+", phrase.lower()):
            if len(word) > 2 and word not in _STOP:
                out.add(word)
    return out


class Mention(BaseModel):
    page: int
    quote: str


def _quote(lines: list[str], index: int) -> tuple[str, str | None]:
    """The matched line plus the value line under it, and - separately - that value when it is
    something to buy by rather than a tightening torque."""
    head = lines[index].strip()
    value: str | None = None
    tail: list[str] = []
    for line in lines[index + 1 : index + 4]:
        clean = line.strip()
        if not clean or len(clean) > 60:
            break
        tail.append(clean)
        if _VALUE.search(clean):
            value = " ".join(tail)
            break
    if value is None and _VALUE.search(head):
        value = head
    quote = re.sub(r"\s+", " ", f"{head} {' '.join(tail)}" if tail else head).strip()
    spec = value if value and not _TORQUE.search(value) and _GRADE.search(value) else None
    return quote[:QUOTE_LEN], (spec[:120] if spec else None)


def _section_text(section: Section) -> str:
    return " ".join([section.title, section.chapter, *section.keywords])


def scan(manual: Manual, pages: list) -> dict[str, dict]:
    """{taxonomyId: {"mentions": [...], "spec": str|None, "sectionIds": [...]}} for every entry the
    manual names. Bike-independent on purpose: one scan serves every bike the manual covers."""
    taxonomy()
    corpus = []
    for page in pages:
        text = getattr(page, "text", "") or ""
        corpus.append((int(getattr(page, "page", 0) or 0), text, set(_WORD.findall(text.lower()))))
    sections = []
    for section in manual.sections:
        text = _section_text(section)
        sections.append((section, text, set(_WORD.findall(text.lower()))))

    out: dict[str, dict] = {}
    for part in taxonomy().parts:
        pattern, probes = matcher(part)
        if not probes:
            continue
        mentions: list[Mention] = []
        spec: str | None = None
        section_ids: list[str] = []

        for section, text, words in sections:
            if not probes & words:
                continue
            if pattern.search(text):
                section_ids.append(section.id)
                if len(mentions) < MAX_MENTIONS:
                    mentions.append(Mention(page=section.pageStart, quote=section.title[:QUOTE_LEN]))

        # Two filters before any line work: the page's word set, then one regex over the whole page.
        # Without them this is 300 entries x 140 pages x 60 lines of regex per manual.
        for page_no, text, words in corpus:
            if len(mentions) >= MAX_MENTIONS and spec:
                break
            if not probes & words or not pattern.search(text):
                continue
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if _LEADERS.search(line) or not pattern.search(line):
                    continue  # a contents entry names the part and says nothing about it
                quote, found = _quote(lines, index)
                if found and not spec:
                    spec = found
                if len(mentions) < MAX_MENTIONS and not any(m.quote == quote for m in mentions):
                    mentions.append(Mention(page=page_no, quote=quote))
                if len(mentions) >= MAX_MENTIONS and spec:
                    break

        if mentions:
            out[part.id] = {
                "mentions": [m.model_dump() for m in mentions],
                "spec": spec,
                "sectionIds": section_ids[:6],
            }
    return out


# --- tying the manual's own parts to taxonomy ids ------------------------


MIN_MATCH = 4  # "oil" alone is not enough to call a part an entry


def _match_manual_part(part: Part, candidates: Iterable[TaxonomyPart]) -> str | None:
    """A manual part IS a taxonomy entry when one of the entry's synonyms is written in its name.
    The longest thing matched wins, so "Fork oil (SAE 5)" is the fork oil and not the engine oil."""
    haystack = flat(f"{part.name} {part.spec}")
    best: tuple[int, str] | None = None
    for candidate in candidates:
        found = matcher(candidate)[0].search(haystack)
        if found is None or len(found.group(0)) < MIN_MATCH:
            continue
        score = len(found.group(0))
        if best is None or score > best[0]:
            best = (score, candidate.id)
    return best[1] if best else None


def map_parts(manual: Manual, kind: str = "motorcycle") -> dict[str, str]:
    """{manualPartId: taxonomyId}. Only the half of the taxonomy this vehicle kind uses is offered:
    "engine oil" is written the same in both, and a bike must never land on the car entry."""
    candidates = [p for p in taxonomy().parts if p.applies.kind == kind]
    return {
        part.id: found
        for part in manual.parts
        if (found := _match_manual_part(part, candidates)) is not None
    }


class _Mapping(BaseModel):
    pairs: list[str] = []  # "manualPartId=taxonomyId"


def map_ambiguous(manual: Manual, known: dict[str, str]) -> dict[str, str]:
    """Optional: one cheap structured call (route "parts.map") for the manual parts no synonym caught.
    Only ever called by api/tools/parts_catalog.py; the route never pays for it."""
    from . import llm
    from .config import settings

    left = [p for p in manual.parts if p.id not in known]
    if not left:
        return {}
    catalogue = "\n".join(f"{p.id}\t{p.name}" for p in taxonomy().parts)
    unknown = "\n".join(f"{p.id}\t{p.name}\t{p.spec[:80]}" for p in left)
    result = llm.structured(
        "parts.map",
        settings.model_struct,
        _Mapping,
        "Match each manual part to the one standard catalogue part that is the same physical thing. "
        "Answer with lines 'manualPartId=catalogueId'. Skip a manual part that is not in the catalogue - "
        "never guess.",
        f"CATALOGUE\n{catalogue}\n\nMANUAL PARTS\n{unknown}",
    )
    out: dict[str, str] = {}
    ids = {p.id for p in left}
    for pair in result.pairs:
        left_id, _, right_id = pair.partition("=")
        if left_id.strip() in ids and entry(right_id.strip()):
            out[left_id.strip()] = right_id.strip()
    return out


# ---------------------------------------------------------------- cache


def _cache_name(manual_id: str) -> str:
    return f"parts_catalog/{manual_id}.json"


def cache_read(store, manual_id: str) -> dict | None:
    reader = getattr(store, "_read_json", None)  # BlobStore
    if callable(reader):
        try:
            return reader(_cache_name(manual_id), None)
        except Exception:
            return None
    root = getattr(store, "root", None)  # FileStore
    if root is not None:
        path = Path(root) / "parts_catalog" / f"{manual_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except Exception:
            return None
    db = getattr(store, "db", None)  # MongoStore
    if db is not None:
        try:
            return db["parts_catalog"].find_one({"_id": manual_id})
        except Exception:
            return None
    return None


def cache_write(store, manual_id: str, data: dict) -> None:
    writer = getattr(store, "_write_json", None)
    if callable(writer):
        try:
            writer(_cache_name(manual_id), data)
        except Exception:
            pass
        return
    root = getattr(store, "root", None)
    if root is not None:
        path = Path(root) / "parts_catalog" / f"{manual_id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass
        return
    db = getattr(store, "db", None)
    if db is not None:
        try:
            db["parts_catalog"].replace_one({"_id": manual_id}, {**data, "_id": manual_id}, upsert=True)
        except Exception:
            pass


def scanned(manual: Manual, store=None, refresh: bool = False) -> dict:
    """The cached bike-independent half: the mentions and the manual-part -> taxonomy map."""
    if store is None:
        from .store import get_store

        store = get_store()
    if not refresh:
        cached = cache_read(store, manual.id)
        if cached and cached.get("version") == CACHE_VERSION and cached.get("taxonomy") == fingerprint():
            return cached
    # one manual covers one vehicle kind, so the map is still bike-independent
    first = store.bike(manual.bikeIds[0]) if manual.bikeIds else None
    data = {
        "version": CACHE_VERSION,
        "taxonomy": fingerprint(),
        "manualId": manual.id,
        "builtAt": time.time(),
        "mentions": scan(manual, store.pages(manual.id)),
        "map": map_parts(manual, profile_of(first).kind),
    }
    cache_write(store, manual.id, data)
    return data


# ---------------------------------------------------------------- the catalogue


class CatalogPart(Part):
    group: str
    groupLabel: str
    icon: str
    standard: bool
    searchHint: str | None = None
    sectionIds: list[str] | None = None
    mentions: list[Mention] = []


class CatalogGroup(BaseModel):
    id: str
    label: str
    count: int


class CatalogResult(BaseModel):
    manualId: str
    bikeId: str | None = None
    profile: Profile
    groups: list[CatalogGroup]
    parts: list[CatalogPart]
    standard: int = 0
    fromManual: int = 0


def _query_for(hint: str, bike: Bike | None) -> str:
    ride = f"{bike.make} {bike.model} {bike.year}" if bike else ""
    return re.sub(r"\s+", " ", f"{hint} {ride}").strip()


def standard_part(part_id: str, bike: Bike | None) -> Part | None:
    """A Part for a taxonomy id, so /parts/offers can shop for a row the manual never printed."""
    found = entry(part_id)
    if found is None:
        return None
    return Part(
        id=found.id,
        name=found.name,
        spec=found.searchHint,
        page=0,
        oem=None,
        links=links(_query_for(found.searchHint, bike)),
    )


def _merge(
    manual: Manual,
    bike: Bike | None,
    profile: Profile,
    data: dict,
) -> list[CatalogPart]:
    mentions: dict[str, dict] = data.get("mentions") or {}
    mapping: dict[str, str] = data.get("map") or {}
    wanted = {p.id: p for p in parts_for(profile)}
    # a manual part mapped to an entry that this bike cannot have (a carburettor on an EFI bike the
    # manual is shared with) still belongs in the list: the manual printed it for this bike.
    taken: dict[str, Part] = {}
    for part in manual.parts:
        target = mapping.get(part.id)
        if target and target not in taken:
            taken[target] = part

    out: list[CatalogPart] = []
    used: set[str] = set()
    for entry_id, part in taken.items():
        found = entry(entry_id)
        if found is None:
            continue
        hit = mentions.get(entry_id) or {}
        out.append(
            CatalogPart(
                **part.model_dump(),
                group=found.group,
                groupLabel=group_label(found.group),
                icon=found.icon,
                standard=True,
                searchHint=found.searchHint,
                sectionIds=hit.get("sectionIds") or None,
                mentions=[Mention.model_validate(m) for m in hit.get("mentions", [])],
            )
        )
        used.add(part.id)

    for found in wanted.values():
        if found.id in taken:
            continue
        hit = mentions.get(found.id) or {}
        rows = [Mention.model_validate(m) for m in hit.get("mentions", [])]
        # empty unless the manual printed something to buy by: offers then shops on the searchHint
        spec = hit.get("spec") or ""
        out.append(
            CatalogPart(
                id=found.id,
                name=found.name,
                spec=spec,
                page=rows[0].page if rows else 0,
                oem=None,
                links=links(_query_for(found.searchHint, bike)),
                group=found.group,
                groupLabel=group_label(found.group),
                icon=found.icon,
                standard=True,
                searchHint=found.searchHint,
                sectionIds=hit.get("sectionIds") or None,
                mentions=rows,
            )
        )

    # whatever the manual named that the taxonomy has no entry for - a MOTOREX chain cleaner, a
    # dealer-only charger. Never dropped: the manual printed it for this bike.
    for part in manual.parts:
        if part.id in used:
            continue
        icon = icon_for(f"{part.name} {part.spec}")
        out.append(
            CatalogPart(
                **part.model_dump(),
                group=group_of_icon(icon),
                groupLabel=group_label(group_of_icon(icon)),
                icon=icon,
                standard=False,
                searchHint=None,
                sectionIds=None,
                mentions=[],
            )
        )
    return out


def catalog(manual_id: str, bike: Bike | None, store=None, refresh: bool = False) -> CatalogResult:
    if store is None:
        from .store import get_store

        store = get_store()
    manual = store.manual(manual_id)
    if manual is None:
        raise ValueError(f"manual {manual_id} not found")
    if bike is None and manual.bikeIds:
        bike = store.bike(manual.bikeIds[0])

    profile = profile_of(bike)
    data = scanned(manual, store, refresh=refresh)
    rows = _merge(manual, bike, profile, data)

    order = {g: i for i, g in enumerate(group_order())}
    manual_ids = {p.id for p in manual.parts}
    rows.sort(
        key=lambda p: (
            order.get(p.group, 99),
            0 if p.id in manual_ids else 1,  # what the manual itself printed comes first
            0 if p.mentions else 1,          # then what it at least talks about
            p.name.lower(),
        )
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.group] = counts.get(row.group, 0) + 1
    return CatalogResult(
        manualId=manual_id,
        bikeId=bike.id if bike else None,
        profile=profile,
        groups=[
            CatalogGroup(id=g, label=group_label(g), count=counts[g])
            for g in group_order()
            if counts.get(g)
        ],
        parts=rows,
        standard=sum(1 for r in rows if r.standard),
        fromManual=len(manual_ids),
    )
