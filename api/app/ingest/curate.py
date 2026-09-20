"""Curation pass over an ingested Manual: drop what no rider ever asks for, put rider tasks first. Ids never change."""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

from ..models import Highlight, Manual, Page, Section
from ..store import get_store

log = logging.getLogger("curate")

MIN_PAGE_CHARS = 25
MIN_SIDE = 0.002

STOP = tuple(
    re.compile(p, re.I)
    for p in (
        r"declarations?\s+of\s+conformity",
        r"\bec\s+declaration",
        r"conformity\s+declaration",
        r"^\s*work\s+rules?\s*$",
        r"symbols?\s+used",
        r"used\s+symbols?",
        r"means\s+of\s+representation",
        r"service\s+and\s+warranty",
        r"warranty\s+and\s+service",
        r"^\s*warranty\b",
        r"table\s+of\s+contents",
        r"^\s*contents?\s*$",
        r"^\s*index\s*$",
        r"^\s*imprint\s*$",
        r"^\s*notes?\s*$",
        r"^\s*foreword\s*$",
        r"^\s*preface\s*$",
        r"^\s*copyright\b",
        r"^\s*disclaimer\b",
    )
)

GROUPS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\boils?\b|\blubricat|\boil\s+filter\b",
        r"\bchains?\b|\bsprocket",
        r"\bbrak(e|ing)\b|\bbrake\s+fluid\b|\bbrake\s+pad",
        r"\btyres?\b|\btires?\b|\btread\b",
        r"\bcoolant\b|\bradiator\b|\bcooling\s+system\b|\bantifreeze\b",
        r"\bbatter(y|ies)\b|\bcharg(e|ing)\b",
        r"\bfuses?\b|\bfuse\s+box\b",
        r"\bbulbs?\b|\bhead\s?light\b|\btail\s?light\b|\blamp\b",
        r"\bclutch\b",
        r"\bwheels?\b|\bspokes?\b|\baxle\b|\bspindle\b",
        r"\bspark\s+plugs?\b",
        r"\bair\s+filter\b|\bair\s+cleaner\b|\bair\s+box\b",
        r"\bsuspension\b|\bpreload\b|\bdamping\b|\bshock\s+absorber\b|\bfork\b|\brebound\b|\bcompression\b",
        r"\bservice\s+(schedule|interval|plan)\b|\bmaintenance\s+(schedule|interval|chart|plan)\b|\bperiodic\s+maintenance\b",
        r"\btightening\s+torque|\btorque\s+(value|setting|spec)",
        r"\btechnical\s+data\b|\bspecification",
    )
)

OTHER = 2 * len(GROUPS)


class Curated(NamedTuple):
    manual: Manual
    dropped: list[str]
    clamped: int
    discarded: int


def fit(highlights: list[Highlight]) -> tuple[list[Highlight], int, int]:
    """The viewer multiplies these by the rendered page, so nothing may leave 0..1."""
    kept: list[Highlight] = []
    clamped = discarded = 0
    for h in highlights:
        x = min(max(h.x, 0.0), 1.0)
        y = min(max(h.y, 0.0), 1.0)
        w = min(max(h.w, 0.0), 1.0 - x)
        hh = min(max(h.h, 0.0), 1.0 - y)
        if (x, y, w, hh) != (h.x, h.y, h.w, h.h):
            clamped += 1
        if w < MIN_SIDE or hh < MIN_SIDE:
            discarded += 1
            continue
        kept.append(h.model_copy(update={"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(hh, 4)}))
    return kept, clamped, discarded


def stopped(title: str) -> bool:
    text = " ".join(title.split())
    return any(rx.search(text) for rx in STOP)


def rank(section: Section) -> int:
    title = " ".join(section.title.split())
    for i, rx in enumerate(GROUPS):
        if rx.search(title):
            return i
    blob = " ".join(section.keywords)
    for i, rx in enumerate(GROUPS):
        if rx.search(blob):
            return len(GROUPS) + i
    return OTHER


def _thin(section: Section, text: dict[int, str]) -> bool:
    if not text:
        return False
    span = range(section.pageStart, max(section.pageEnd, section.pageStart) + 1)
    return sum(len(text.get(p, "")) for p in span) < MIN_PAGE_CHARS


def curate(manual: Manual, pages: list[Page]) -> Curated:
    text = {p.page: " ".join((p.text or "").split()) for p in pages}
    kept: list[Section] = []
    dropped: list[str] = []
    for section in manual.sections:
        if stopped(section.title) or _thin(section, text):
            dropped.append(section.title)
        else:
            # BUG-17: the manual cache holds these Section objects; the clamp loop below must edit copies
            kept.append(section.model_copy(deep=True))

    alive = {s.id for s in kept}
    clamped = discarded = 0
    for section in kept:
        if section.related:
            section.related = [r for r in section.related if r in alive] or None
        section.highlights, bent, gone = fit(section.highlights)
        clamped += bent
        discarded += gone
    if clamped or discarded:
        log.warning("%s: %d highlights outside 0..1 clamped, %d discarded", manual.id, clamped, discarded)

    order = {s.id: i for i, s in enumerate(kept)}
    kept.sort(key=lambda s: (rank(s), s.pageStart, order[s.id]))
    return Curated(manual.model_copy(update={"sections": kept}), dropped, clamped, discarded)


def apply(manual: Manual) -> Curated:
    store = get_store()
    result = curate(manual, store.pages(manual.id))
    Manual.model_validate(result.manual.model_dump(exclude_none=True))
    store.put_manual(result.manual)
    return result
