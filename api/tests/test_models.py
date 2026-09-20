"""The contract. Every model round-trips through JSON unchanged, and the shared
models still carry exactly the camelCase field names src/types.ts declares."""

import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app import models as M

ROOT = Path(__file__).resolve().parents[2]
TYPES_TS = ROOT / "src" / "types.ts"
UI_MANUALS = sorted((ROOT / "src" / "data" / "manuals").glob("*.json"))
API_MANUALS = sorted((ROOT / "api" / "data" / "manuals").glob("*.json"))
SEEDED = {"ktm-390-duke-2024-om-en", "bmw-r12gs-2025-rm-en"}

HIGHLIGHT = M.Highlight(page=1, x=0.1, y=0.2, w=0.3, h=0.4)
LINK = M.Link(shop="RevZilla", url="https://example.com/x")
SECTION = M.Section(
    id="front-brake-pads",
    title="Checking brake pad thickness, front brakes",
    chapter="13 BRAKE SYSTEM",
    pageStart=166,
    pageEnd=167,
    keywords=["brake pads", "wear limit"],
    highlights=[HIGHLIGHT],
    partIds=["brake-fluid"],
    related=["brake-fluid-front"],
)
PART = M.Part(id="engine-oil", name="Engine oil", spec="SAE 15W-50", page=213, oem="83 12 2 405 918", links=[LINK])
OUTLINE = M.OutlineNode(title="13 BRAKE SYSTEM", page=166, children=[M.OutlineNode(title="Front", page=166)])
MANUAL = M.Manual(
    id="demo-om-en",
    bikeIds=["demo-2025"],
    file="/manuals/demo-om-en.pdf",
    pages=268,
    title="RIDER'S MANUAL",
    source="https://example.com/demo.pdf",
    outline=[OUTLINE],
    sections=[SECTION],
    parts=[PART],
)
SPEC = M.Spec(
    sectionId="td-wheels-tyres",
    name="Tyre pressure, front",
    kind="pressure",
    value="2.3 bar",
    unit="bar",
    page=172,
    quote="Tyre pressure, front 2.3 bar",
)

SAMPLES: list[BaseModel] = [
    M.Bike(id="ktm-390-duke-2024", make="KTM", model="390 Duke", year=2024, market="US",
           manualId="ktm-390-duke-2024-om-en", vins=["VBKJSA40"], cues=["orange trellis frame"]),
    M.Bike(id="ktm-390-duke-2023", make="KTM", model="390 Duke", year=2023, market="US", manualId=None),
    OUTLINE,
    HIGHLIGHT,
    SECTION,
    LINK,
    PART,
    MANUAL,
    M.Match(section=SECTION, score=0.9),
    M.Candidate(bikeId="ktm-390-duke-2024", confidence=1.0),
    M.Block(text="Tyre pressure, front", x=0.1, y=0.2, w=0.3, h=0.02),
    M.Page(manualId="demo-om-en", page=172, width=595.0, height=842.0, text="Tyre pressure",
           blocks=[M.Block(text="Tyre pressure", x=0.1, y=0.2, w=0.3, h=0.02)]),
    SPEC,
    M.RegistryEntry(id="bmw-r12gs-2025-rm-en", make="BMW", model="R 12 G/S", years=[2025], market="EU",
                    type="owner", lang="en", url="https://example.com/m.pdf", access="free",
                    price=None, site="bmw-motorrad.com", title="Rider's Manual"),
    M.AskRequest(manualId="demo-om-en", query="change the oil"),
    M.AskResponse(matches=[M.Match(section=SECTION, score=1.0)], intent="procedure", usd=0.000123),
    M.VinRequest(vin="VBKJSA40XR1234567"),
    M.IdentifyResponse(candidates=[M.Candidate(bikeId="ktm-390-duke-2024", confidence=1.0)], bike=None),
    M.PartClass(label="brake lever", confidence=0.71),
    M.IngestRequest(url="https://example.com/m.pdf", make="BMW", model="R 12 G/S", year=2025, market="EU"),
    M.IngestJob(id="abc123", manualId="demo-om-en", status="done", pages=268, done=268, error=None),
    M.CostEvent(ts=1758300000.0, route="ask.router", model="gpt-5.6-luna",
                inputTokens=1200, cachedTokens=1024, outputTokens=80, usd=0.000123),
    M.CostSummary(total=0.5, count=3, byRoute={"ask.router": 0.2}, byModel={"gpt-5.6-luna": 0.2},
                  naivePerAsk=1.144, asks=2),
]


def _model_classes() -> list[type[BaseModel]]:
    return [
        v
        for v in vars(M).values()
        if isinstance(v, type) and issubclass(v, BaseModel) and v is not BaseModel and v.__module__ == M.__name__
    ]


def test_every_model_has_a_sample():
    covered = {type(s).__name__ for s in SAMPLES}
    declared = {c.__name__ for c in _model_classes()}
    assert declared - covered == set(), f"models without a round-trip sample: {sorted(declared - covered)}"


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_json_round_trip(sample: BaseModel):
    text = sample.model_dump_json()
    back = type(sample).model_validate(json.loads(text))
    assert back == sample
    assert back.model_dump_json() == text


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_dump_keys_are_camel_case(sample: BaseModel):
    for key in sample.model_dump().keys():
        assert "_" not in key, f"{type(sample).__name__}.{key} is not camelCase"


def _ts_interfaces() -> dict[str, set[str]]:
    text = TYPES_TS.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for name, body in re.findall(r"export interface (\w+) \{(.*?)\n\}", text, re.S):
        fields: set[str] = set()
        for line in body.splitlines():
            line = re.sub(r"//.*$", "", line)
            line = re.sub(r"\{[^{}]*\}", "object", line).strip()
            for field in re.findall(r"(?:^|;\s*)([A-Za-z_]\w*)\??\s*:", line):
                fields.add(field)
        out[name] = fields
    return out


@pytest.mark.parametrize("name", ["Bike", "OutlineNode", "Highlight", "Section", "Part", "Manual", "Match", "Candidate"])
def test_fields_match_types_ts(name: str):
    ts = _ts_interfaces()
    assert name in ts, f"{name} missing from src/types.ts"
    py = set(getattr(M, name).model_fields.keys())
    assert py == ts[name], f"{name}: python {sorted(py)} vs types.ts {sorted(ts[name])}"


@pytest.mark.parametrize("path", UI_MANUALS + API_MANUALS, ids=lambda p: f"{p.parent.parent.parent.name}/{p.stem}")
def test_seeded_manual_json_is_byte_compatible(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    manual = M.Manual.model_validate(raw)
    assert manual.model_dump(exclude_none=True) == raw
    assert manual.id == path.stem
    assert manual.sections and manual.parts
    for section in manual.sections:
        assert 1 <= section.pageStart <= section.pageEnd <= manual.pages
        for hl in section.highlights:
            assert section.pageStart <= hl.page <= section.pageEnd


@pytest.mark.parametrize("path", [p for p in UI_MANUALS + API_MANUALS if p.stem in SEEDED],
                        ids=lambda p: f"{p.parent.parent.parent.name}/{p.stem}")
def test_seeded_manual_highlights_are_page_fractions(path: Path):
    """src/types.ts: x/y/w/h are fractions of page width/height, origin top-left. The viewer
    draws the marker straight from these, so anything outside 0..1 lands off the sheet."""
    manual = M.Manual.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for section in manual.sections:
        for hl in section.highlights:
            assert 0.0 <= hl.x <= 1.0 and 0.0 <= hl.y <= 1.0, (section.id, hl)
            assert 0.0 < hl.w <= 1.0 and 0.0 < hl.h <= 1.0, (section.id, hl)
            assert hl.x + hl.w <= 1.001 and hl.y + hl.h <= 1.001, (section.id, hl)


def test_seeded_manuals_exist():
    """Other agents ingest more manuals into api/data/manuals; these two are the fixtures the
    rest of the suite pins to, so assert they are present rather than counting the directory."""
    assert SEEDED <= {p.stem for p in UI_MANUALS}
    assert SEEDED <= {p.stem for p in API_MANUALS}
