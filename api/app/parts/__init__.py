"""Classify a motorcycle part photo into the 30 labels of AswinG5/moto-parts-30cls.

Default path: zero-shot with the vision model. Set PART_MODEL=yolo to use the real
checkpoint instead (ultralytics + torch are not installed by default; the import is
lazy and any failure falls back to zero-shot).
"""

import os

from pydantic import BaseModel

from .. import llm
from ..config import settings
from ..models import PartClass
from .labels import LABELS, QUERY, Label, described, query

__all__ = ["LABELS", "QUERY", "Label", "classify", "query"]

ROUTE = "identify.part"

SYSTEM = (
    "You name the motorcycle part in the photo. Answer only with labels from this list:\n"
    f"{described()}\n"
    "Rank up to 3 labels, most likely first, with a confidence 0..1 each. "
    "If the photo shows a whole bike, pick the part that fills most of the frame. "
    "Never invent a label that is not in the list."
)


class PartGuess(BaseModel):
    label: Label
    confidence: float


class PartTop(BaseModel):
    top: list[PartGuess]


def _clamp(x: float) -> float:
    return round(min(1.0, max(0.0, float(x))), 3)


def _zero_shot(image: bytes, mime: str) -> list[PartClass]:
    out = llm.structured(
        ROUTE,
        settings.model_vision,
        PartTop,
        SYSTEM,
        [llm.text_part("Which part is this?"), llm.image_part(image, mime, "auto")],
    )
    seen: set[str] = set()
    top: list[PartClass] = []
    for g in out.top:
        if g.label in seen:
            continue
        seen.add(g.label)
        top.append(PartClass(label=g.label, confidence=_clamp(g.confidence)))
    return top[:3]


def classify(image: bytes, mime: str) -> list[PartClass]:
    if os.getenv("PART_MODEL", "").strip().lower() == "yolo":
        try:
            from .yolo import classify as yolo_classify

            top = yolo_classify(image)
            if top:
                return top
        except Exception:
            pass
    return _zero_shot(image, mime)
