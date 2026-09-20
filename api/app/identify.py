"""Bike from a photo or a VIN, part from a photo. Owner: identify agent.

photo(): vision model reads the machine -> catalog ranking in Python -> Candidate[].
vin():   bikes.json mock prefixes, then NHTSA vPIC DecodeVinValues -> catalog bike.
part():  app/parts, zero-shot on the vision model (PART_MODEL=yolo for the checkpoint).

Why photo() looks the way it does. It used to paste 400 catalog names into the prompt and
ask the model to pick one; with 8.5k distinct models in the store those 400 names were 200
KTM dirt bikes and 200 Acuras, cost ~2.6k input tokens a photo, and the model ignored them
anyway - a 390 Duke came back as a "KTM 690 Duke" (which was not even in the list) and every
one of the eight candidates was another model year of that same wrong bike.

So the two steps were separated. The model now only reports what is visible - the badge text
printed on the machine, the displacement, the cylinder count, the family, the year band -
and the catalog constraint is applied here, in Python, where it is free and deterministic:
the make picks the pool, then every model of that make is scored on the name the model gave
it, corrected by the badge and the displacement. 390 vs 690 is decided by the "390 DUKE"
decal on the tank and by ~390 cc, not by which name the model felt like writing.

The answer carries the best year of each of the top three models, interleaved, so the
Confirm screen's alternatives strip offers three real models to correct to instead of eight
model years of one wrong guess.
"""

import io
import re
from difflib import SequenceMatcher
from typing import Literal

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import llm
from .config import settings
from .models import Bike, Candidate, IdentifyResponse, PartClass
from .parts import classify
from .store import get_store

MAX_PX = 1024
JPEG_QUALITY = 85
MATCH_FLOOR = 0.80
VIN_FLOOR = 0.88
MAKE_FLOOR = 0.62  # below this the vision step named a make the catalog does not have
MODEL_FLOOR = 0.30  # below this a catalog model is not worth offering as an alternative
TOP_MODELS = 3  # distinct models in the answer: what the Confirm strip can correct to
YEARS_PER_MODEL = 3
MAX_CANDIDATES = 8
BONUS = 0.45  # how far the badge and the displacement may move a name-only score
VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"


class Generation(BaseModel):
    yearFrom: int
    yearTo: int


class Alternative(BaseModel):
    make: str
    model: str
    confidence: float


class PhotoGuess(BaseModel):
    make: str
    model: str
    generation: Generation
    confidence: float
    cues: list[str]
    alternatives: list[Alternative]
    kind: Literal["motorcycle", "car"] = "motorcycle"
    badge: str = ""  # copied off the machine, never inferred: "390 DUKE", "GSX-R750"
    family: str = ""  # the model line without size or trim: Duke, YZF-R, Ninja, GS
    displacementCc: int = 0  # 0 = could not tell
    cylinders: int = 0  # 0 = could not tell


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def downscale(image: bytes, mime: str) -> tuple[bytes, str]:
    """<= MAX_PX on the long side, JPEG q85. Cuts vision tokens on phone photos."""
    try:
        img = Image.open(io.BytesIO(image))
        img = ImageOps.exif_transpose(img) or img
        if img.mode != "RGB":
            img = img.convert("RGB")
    except Exception:
        raise HTTPException(422, "unreadable image")
    if max(img.size) > MAX_PX:
        scale = MAX_PX / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "image/jpeg"


def _key(s: str) -> str:
    """Order-insensitive: "Duke 390" and "390 Duke" collapse to the same string."""
    return "".join(sorted(re.findall(r"[a-z]+|[0-9]+", (s or "").lower())))


def _groups(bikes: list[Bike]) -> dict[tuple[str, str], list[Bike]]:
    out: dict[tuple[str, str], list[Bike]] = {}
    for b in bikes:
        out.setdefault((_norm(b.make), _norm(b.model)), []).append(b)
    return out


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _make_ratio(a: str, b: str) -> float:
    if len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
        return 1.0
    return _ratio(a, b)


def _score(make: str, model: str, mk: str, md: str) -> float:
    m = max(_ratio(_norm(model), md), _ratio(_key(_norm(model)), _key(md)))
    a, b = set(re.findall(r"\d+", model or "")), set(re.findall(r"\d+", md))
    if a and b and a.isdisjoint(b):
        m = min(m, 0.5)  # CB650R is not CBR600RR, MT-07 is not MT-09
    return 0.35 * _make_ratio(_norm(make), mk) + 0.65 * m


def _find(make: str, model: str, bikes: list[Bike], floor: float = MATCH_FLOOR) -> tuple[list[Bike], float]:
    best: list[Bike] = []
    score = 0.0
    for (mk, md), group in _groups(bikes).items():
        s = _score(make, model, mk, md)
        if s > score:
            best, score = group, s
    return (best, score) if score >= floor else ([], score)


def _year_weight(year: int, gen: Generation | None) -> float:
    if gen is None or not gen.yearFrom:
        return 1.0
    lo, hi = sorted((gen.yearFrom, gen.yearTo or gen.yearFrom))
    if lo <= year <= hi:
        return 1.0
    d = min(abs(year - lo), abs(year - hi))
    if d <= 1:
        return 0.7
    if d <= 3:
        return 0.4
    return 0.15


def _add(out: dict[str, float], bikes: list[Bike], base: float, gen: Generation | None) -> None:
    for b in bikes:
        c = round(_clamp(base * _year_weight(b.year, gen)), 3)
        if c > out.get(b.id, 0.0):
            out[b.id] = c


def _kind(b: Bike) -> str:
    return (b.kind or "motorcycle").lower()


# --- what the photo itself says, scored against one catalog model name ----------------------

SYSTEM = (
    "You identify one vehicle from a photo, for a workshop counter. Report what is on the machine, "
    "not what the brand is famous for - the mechanic is holding the wrong-sized sibling half the time.\n"
    "badge: the model text printed on the machine itself - tank decal, side panel, fairing, tail unit, "
    "boot lid, tailgate - copied exactly as printed, e.g. '390 DUKE', 'GSX-R750', 'R 1250 GS'. Empty "
    "string when none is legible. Never write a badge you inferred from the shape.\n"
    "displacementCc: engine size in cc. Take it from the badge when the badge states one, otherwise "
    "read it off the engine: cylinder count, cylinder and radiator width against the frame, wheel and "
    "disc diameter against the tyre, the size of the whole machine around the engine. 0 when unsure.\n"
    "cylinders: 1, 2, 3, 4 or 6, else 0.\n"
    "family: the model line without the size or the trim - Duke, YZF-R, Ninja, GS, Golf, Corvette.\n"
    "make and model: the full name the maker writes, e.g. 'KTM' / '390 Duke'.\n"
    "generation: the year range that body shape was sold, not the year of the photo.\n"
    "kind: 'car' for any car, SUV, pickup or van; 'motorcycle' for any motorcycle, scooter or ATV.\n"
    "cues: 2-6 short lowercase details you used, no sentences. Prefer the ones that separate this "
    "machine from its bigger and its smaller sibling.\n"
    "alternatives: up to 3 other vehicles this could be, most likely first, each with its own "
    "confidence. When two sizes of one model line look alike, the other size belongs here.\n"
    "confidence: 0..1 for the main answer."
)

DIGITS = re.compile(r"\d+")
SIZE = re.compile(r"\d{2,4}")


def _displacement(md: str) -> int | None:
    """The cc a normalised model name prints: "390duke" -> 390, "r1250gs" -> 1250, "mt07" -> 700.
    A lone digit is a series number, not a size ("yzfr7" is a 689 cc twin), so it is not read."""
    runs = [int(r) for r in SIZE.findall(md)]
    if not runs:
        return None
    best = max(runs)
    if best < 50:  # "07", "09": the hundreds shorthand Yamaha writes on the side panel
        return best * 100
    return best if best <= 2500 else None


def _badge_term(badge: str, md: str) -> float | None:
    """-1 .. 1. The decal on the tank is the one piece of evidence a vision model cannot talk its
    way around, so it is weighted hardest."""
    b = _norm(badge)
    if len(b) < 2:
        return None
    if b == md or (len(md) >= 3 and md in b) or (len(b) >= 3 and b in md):
        return 1.0
    a, c = set(DIGITS.findall(b)), set(DIGITS.findall(md))
    if a and c and a.isdisjoint(c):
        return -1.0  # "390 DUKE" is not the 690, whatever name the model felt like writing
    return round(2 * max(_ratio(b, md), _ratio(_key(b), _key(md))) - 1, 3)


def _size_term(cc: int, md: str, kind: str) -> float | None:
    """-1 .. 1. Cars do not print their displacement in the model name, so this is bikes only."""
    if kind != "motorcycle" or not 50 <= cc <= 2500:
        return None
    want = _displacement(md)
    if want is None:
        return None
    off = abs(want - cc) / max(want, cc)
    if off <= 0.10:
        return 1.0
    if off <= 0.22:
        return 0.4
    return -0.4 if off <= 0.40 else -1.0


def _family_term(family: str, md: str) -> float | None:
    f = _norm(family)
    if len(f) < 3:
        return None
    if f in md:
        return 1.0
    return -0.3 if _ratio(f, md) < 0.3 else 0.0


# Badge first: it is read, not inferred. The family name is the weakest of the three, because
# every sibling in the pool shares it.
WEIGHTS = ((1.0, "badge"), (0.8, "size"), (0.35, "family"))


def _evidence(guess: PhotoGuess, md: str) -> float:
    """-1 .. 1: the weighted mean of whichever of the three the photo actually supplied."""
    terms = {
        "badge": _badge_term(guess.badge, md),
        "size": _size_term(int(guess.displacementCc or 0), md, guess.kind),
        "family": _family_term(guess.family, md),
    }
    total = sum(w for w, key in WEIGHTS if terms[key] is not None)
    if not total:
        return 0.0
    return sum(w * terms[key] for w, key in WEIGHTS if terms[key] is not None) / total


def _model_ratio(model: str, md: str) -> float:
    """How close the name the vision step wrote is to one normalised catalog model name."""
    m = max(_ratio(_norm(model), md), _ratio(_key(_norm(model)), _key(md)))
    a, b = set(DIGITS.findall(model or "")), set(DIGITS.findall(md))
    if a and b and a.isdisjoint(b):
        m = min(m, 0.5)  # CB650R is not CBR600RR, MT-07 is not MT-09
    return m


def _make_pool(make: str, pool: list[Bike]) -> list[Bike]:
    """Rows of the one make the vision step named. This is the catalog constraint that used to be
    400 names in the prompt: a KTM photo is ranked against KTM's 479 models and nothing else. A make
    the catalog does not carry leaves the pool whole rather than emptying it."""
    want = _norm(make)
    if not want:
        return pool
    best, score = "", 0.0
    for mk in {_norm(b.make) for b in pool}:
        s = _make_ratio(want, mk)
        if s > score:
            best, score = mk, s
    if score < MAKE_FLOOR:
        return pool
    return [b for b in pool if _norm(b.make) == best] or pool


def _rank(guess: PhotoGuess, pool: list[Bike]) -> list[tuple[float, list[Bike]]]:
    """The top TOP_MODELS distinct catalog models, best first. Every reading the vision step gave
    us - its own answer and each of its alternatives - picks its own make pool and scores every
    model in it; the photo's evidence then moves that name score by up to BONUS either way."""
    readings = [(guess.make, guess.model, _clamp(guess.confidence), 1.0)]
    readings += [(a.make, a.model, _clamp(a.confidence), 0.85) for a in guess.alternatives[:3]]
    best: dict[tuple[str, str], tuple[float, list[Bike]]] = {}
    for mk_name, md_name, conf, weight in readings:
        if not (md_name or "").strip():
            continue
        for (mk, md), group in _groups(_make_pool(mk_name, pool)).items():
            named = _model_ratio(md_name, md) * max(conf, 0.35) * weight
            score = _clamp(named * (1.0 + BONUS * _evidence(guess, md)))
            if score >= MODEL_FLOOR and score > best.get((mk, md), (0.0,))[0]:
                best[(mk, md)] = (score, group)
    return sorted(best.values(), key=lambda row: -row[0])[:TOP_MODELS]


def _spread(ranked: list[tuple[float, list[Bike]]], gen: Generation | None) -> list[Candidate]:
    """Round robin across the models, best year of each first. The second and the third card on the
    Confirm screen are therefore a different model, not another model year of the first one."""
    lanes: list[list[Candidate]] = []
    for score, group in ranked:
        rows = sorted(group, key=lambda b: (-_year_weight(b.year, gen), -b.year))
        lanes.append(
            [
                Candidate(bikeId=b.id, confidence=round(_clamp(score * _year_weight(b.year, gen)), 3))
                for b in rows[:YEARS_PER_MODEL]
            ]
        )
    out: list[Candidate] = []
    for depth in range(YEARS_PER_MODEL):
        out += [lane[depth] for lane in lanes if depth < len(lane)]
    return out[:MAX_CANDIDATES]


def photo(image: bytes, mime: str) -> IdentifyResponse:
    data, m = downscale(image, mime)
    bikes = get_store().bikes()
    system = (
        "You identify vehicles (motorcycles and cars) from a photo. Name the make, the model and the "
        "model generation (the year range that body shape was sold, not the year of the photo).\n"
        "These models are in our manual catalog:\n"
        f"{_catalog_prompt(bikes)}\n"
        "Prefer one of these, spelled exactly as listed, when it plausibly matches the vehicle in the photo. "
        "Otherwise name the real vehicle, whatever it is.\n"
        "kind: 'car' for any car, SUV, pickup or van; 'motorcycle' for any motorcycle, scooter or ATV. "
        "cues: 2-6 short visual details you used, lowercase, no sentences. "
        "alternatives: up to 3 other plausible vehicles, most likely first, empty if you are sure. "
        "confidence: 0..1 for the main answer."
    )
    guess = llm.structured(
        "identify.photo",
        settings.model_vision,
        PhotoGuess,
        system,
        [llm.text_part("Which vehicle is this?"), llm.image_part(data, m, "auto")],
    )
    # A car photo must not come back as a motorcycle: match inside the kind the model named, and only
    # fall back to the whole catalog when that kind is not represented at all.
    pool = [b for b in bikes if _kind(b) == guess.kind] or bikes
    scores: dict[str, float] = {}
    group, score = _find(guess.make, guess.model, pool)
    if group:
        _add(scores, group, _clamp(guess.confidence) * score, guess.generation)
    for alt in guess.alternatives[:3]:
        alt_group, alt_score = _find(alt.make, alt.model, pool)
        if alt_group:
            _add(scores, alt_group, _clamp(alt.confidence) * alt_score * 0.8, None)
    candidates = [Candidate(bikeId=i, confidence=c) for i, c in sorted(scores.items(), key=lambda kv: -kv[1])]
    return IdentifyResponse(candidates=candidates[:8], bike=None)


def normalize_vin(vin: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (vin or "").upper())


def _mock(vin: str, bikes: list[Bike]) -> Bike | None:
    for b in bikes:
        for prefix in b.vins or []:
            p = normalize_vin(prefix)
            if p and len(vin) >= len(p) and vin.startswith(p):
                return b
    return None


def _vpic_kind(row: dict) -> str | None:
    """vPIC decodes the vehicle type for almost every VIN even when it cannot name the model, and that
    is the one thing that keeps a Civic VIN from coming back as a list of Rebels."""
    blob = f"{row.get('VehicleType') or ''} {row.get('BodyClass') or ''}".upper()
    if re.search(r"MOTORCYCLE|SCOOTER|MOPED|ALL TERRAIN|ATV", blob):
        return "motorcycle"
    if re.search(r"PASSENGER CAR|TRUCK|MULTIPURPOSE|MPV|VAN|BUS|SEDAN|COUPE|HATCHBACK|WAGON|PICKUP|SPORT UTILITY|SUV", blob):
        return "car"
    return None


def _decode(vin: str) -> tuple[str, str, int, str | None]:
    try:
        r = httpx.get(VPIC.format(vin=vin), timeout=8.0)
        r.raise_for_status()
        row = (r.json().get("Results") or [{}])[0]
    except Exception:
        return "", "", 0, None
    year = re.sub(r"[^0-9]", "", str(row.get("ModelYear") or ""))
    make = str(row.get("Make") or "").strip()
    model = str(row.get("Model") or "").strip()
    return make, model, int(year) if year else 0, _vpic_kind(row)


def vin(vin: str) -> IdentifyResponse:
    value = normalize_vin(vin)
    bikes = get_store().bikes()
    hit = _mock(value, bikes)
    if hit:
        return IdentifyResponse(candidates=[Candidate(bikeId=hit.id, confidence=1.0)], bike=hit)
    if len(value) != 17:
        raise HTTPException(422, "vin must be 17 characters")
    make, model, year, kind = _decode(value)
    if not make:
        return IdentifyResponse(candidates=[], bike=None)
    same_make = [b for b in bikes if _norm(b.make) == _norm(make)]
    if kind:  # Honda sells both; a Civic's VIN must not come back as a list of Rebels
        same_make = [b for b in same_make if _kind(b) == kind] or same_make
    group, _ = _find(make, model, same_make, VIN_FLOOR) if model else ([], 0.0)
    if not group:
        # vPIC decodes Make for almost every motorcycle but Model for almost none.
        rest = [b for b in same_make if b.year == year] if year else []
        return IdentifyResponse(candidates=[Candidate(bikeId=b.id, confidence=0.4) for b in rest], bike=None)
    exact = next((b for b in group if b.year == year), None)
    if exact:
        return IdentifyResponse(candidates=[Candidate(bikeId=exact.id, confidence=1.0)], bike=exact)
    return IdentifyResponse(
        candidates=[Candidate(bikeId=b.id, confidence=0.5) for b in sorted(group, key=lambda b: -b.year)],
        bike=None,
    )


def part(image: bytes, mime: str) -> list[PartClass]:
    data, m = downscale(image, mime)
    return classify(data, m)
