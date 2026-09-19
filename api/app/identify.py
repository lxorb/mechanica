"""Bike from a photo or a VIN, part from a photo. Owner: identify agent.

photo(): vision model constrained to the catalog -> fuzzy match -> Candidate[].
vin():   bikes.json mock prefixes, then NHTSA vPIC DecodeVinValues -> catalog bike.
part():  app/parts, zero-shot on the vision model (PART_MODEL=yolo for the checkpoint).
"""

import io
import re
from difflib import SequenceMatcher

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
CATALOG_LIMIT = 400
MATCH_FLOOR = 0.80
VIN_FLOOR = 0.88
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


def _catalog_prompt(bikes: list[Bike]) -> str:
    seen: list[str] = []
    for b in bikes:
        name = f"{b.make} {b.model}"
        if name not in seen:
            seen.append(name)
    return "\n".join(f"- {n}" for n in seen[:CATALOG_LIMIT]) or "- (empty)"


def photo(image: bytes, mime: str) -> IdentifyResponse:
    data, m = downscale(image, mime)
    bikes = get_store().bikes()
    system = (
        "You identify motorcycles from a photo. Name the make, the model and the model generation "
        "(the year range that body shape was sold, not the year of the photo).\n"
        "These models are in our manual catalog:\n"
        f"{_catalog_prompt(bikes)}\n"
        "Prefer one of these, spelled exactly as listed, when it plausibly matches the bike in the photo. "
        "Otherwise name the real bike, whatever it is.\n"
        "cues: 2-6 short visual details you used, lowercase, no sentences. "
        "alternatives: up to 3 other plausible bikes, most likely first, empty if you are sure. "
        "confidence: 0..1 for the main answer."
    )
    guess = llm.structured(
        "identify.photo",
        settings.model_vision,
        PhotoGuess,
        system,
        [llm.text_part("Which motorcycle is this?"), llm.image_part(data, m, "auto")],
    )
    scores: dict[str, float] = {}
    group, score = _find(guess.make, guess.model, bikes)
    if group:
        _add(scores, group, _clamp(guess.confidence) * score, guess.generation)
    for alt in guess.alternatives[:3]:
        alt_group, alt_score = _find(alt.make, alt.model, bikes)
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


def _decode(vin: str) -> tuple[str, str, int]:
    try:
        r = httpx.get(VPIC.format(vin=vin), timeout=8.0)
        r.raise_for_status()
        row = (r.json().get("Results") or [{}])[0]
    except Exception:
        return "", "", 0
    year = re.sub(r"[^0-9]", "", str(row.get("ModelYear") or ""))
    return str(row.get("Make") or "").strip(), str(row.get("Model") or "").strip(), int(year) if year else 0


def vin(vin: str) -> IdentifyResponse:
    value = normalize_vin(vin)
    bikes = get_store().bikes()
    hit = _mock(value, bikes)
    if hit:
        return IdentifyResponse(candidates=[Candidate(bikeId=hit.id, confidence=1.0)], bike=hit)
    if len(value) != 17:
        raise HTTPException(422, "vin must be 17 characters")
    make, model, year = _decode(value)
    if not make:
        return IdentifyResponse(candidates=[], bike=None)
    same_make = [b for b in bikes if _norm(b.make) == _norm(make)]
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
