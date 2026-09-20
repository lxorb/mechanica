"""Data contracts. Field names are camelCase on purpose: the JSON must be byte-compatible with src/types.ts."""

from typing import Literal

from pydantic import BaseModel


class Bike(BaseModel):
    id: str
    make: str
    model: str
    year: int
    market: str
    manualId: str | None = None
    manualUrl: str | None = None
    vins: list[str] | None = None
    cues: list[str] | None = None


class OutlineNode(BaseModel):
    title: str
    page: int
    children: list["OutlineNode"] | None = None


class Highlight(BaseModel):
    page: int
    x: float
    y: float
    w: float
    h: float


class Section(BaseModel):
    id: str
    title: str
    chapter: str
    pageStart: int
    pageEnd: int
    keywords: list[str]
    highlights: list[Highlight]
    partIds: list[str] | None = None
    related: list[str] | None = None


class Link(BaseModel):
    shop: str
    url: str


class Part(BaseModel):
    id: str
    name: str
    spec: str
    page: int
    oem: str | None = None
    links: list[Link]


class Manual(BaseModel):
    id: str
    bikeIds: list[str]
    file: str
    pages: int
    title: str
    source: str
    outline: list[OutlineNode]
    sections: list[Section]
    parts: list[Part]


class Match(BaseModel):
    section: Section
    score: float


class Candidate(BaseModel):
    bikeId: str
    confidence: float


# backend only


class Block(BaseModel):
    text: str
    x: float
    y: float
    w: float
    h: float


class Page(BaseModel):
    manualId: str
    page: int
    width: float
    height: float
    text: str
    blocks: list[Block]


class Spec(BaseModel):
    sectionId: str
    name: str
    kind: Literal["torque", "capacity", "clearance", "pressure", "grade", "size", "electrical", "other"]
    value: str
    unit: str | None = None
    page: int
    quote: str


class RegistryEntry(BaseModel):
    id: str
    make: str
    model: str
    years: list[int]
    market: str
    type: Literal["owner", "service"]
    lang: str
    url: str
    access: Literal["free", "paid", "subscription", "dealer"]
    price: str | None = None
    site: str
    title: str | None = None
    needsUa: str | None = None  # fetcher hint: "googlebot" or "browser" when the host rejects the default UA


class AskRequest(BaseModel):
    manualId: str
    query: str


class AskResponse(BaseModel):
    matches: list[Match]
    intent: str | None = None
    usd: float = 0.0


class VinRequest(BaseModel):
    vin: str


class IdentifyResponse(BaseModel):
    candidates: list[Candidate]
    bike: Bike | None = None


class PartClass(BaseModel):
    label: str
    confidence: float


class IngestRequest(BaseModel):
    url: str
    make: str
    model: str
    year: int
    market: str = "EU"


class IngestJob(BaseModel):
    id: str
    manualId: str
    status: Literal["queued", "running", "done", "error"]
    pages: int = 0
    done: int = 0
    error: str | None = None
    stage: str | None = None


class CostEvent(BaseModel):
    ts: float
    route: str
    model: str
    inputTokens: int
    cachedTokens: int
    outputTokens: int
    usd: float


class CostSummary(BaseModel):
    total: float
    count: int
    byRoute: dict[str, float]
    byModel: dict[str, float]
    naivePerAsk: float
    asks: int
