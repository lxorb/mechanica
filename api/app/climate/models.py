"""Climate Fit contracts. camelCase on purpose, same rule as app/models.py: the JSON is what the
browser reads, byte-compatible with what web/counter/js/climate.js expects."""

from typing import Literal

from pydantic import BaseModel

RuleType = Literal[
    "antifreeze_floor",
    "oil_grade_band",
    "dust_interval",
    "wet_interval",
    "salt_wash",
    "cold_start",
    "altitude",
    "heat_limit",
]

Comparator = Literal["below", "at_or_below", "above", "at_or_above", "always"]


class ClimateRule(BaseModel):
    id: str  # sha1(manualId + page + ruleType + value)[:12]
    manualId: str
    ruleType: RuleType
    name: str  # the manual's own label, e.g. "Antifreeze protection"
    comparator: Comparator | None = None
    thresholdC: float | None = None  # normalised to Celsius
    thresholdM: float | None = None  # metres, for altitude rules
    value: str | None = None  # "SAE 5W/40", "10000 km", "-25 °C" - the printed string
    intervalKm: int | None = None
    page: int
    quote: str  # character-for-character from the page text layer
    sectionId: str | None = None
    source: Literal["regex", "model"] = "regex"


class StationClimate(BaseModel):
    id: str  # "727470-14918"
    name: str
    ctry: str
    lat: float
    lon: float
    elevM: float | None = None
    years: list[int] = []
    obs: int = 0
    minC: float = 0.0
    maxC: float = 0.0
    meanC: float = 0.0
    hoursBelow: dict[str, float] = {}  # mean hours per year, derived from the share of readings
    hoursAbove: dict[str, float] = {}
    shareBelow: dict[str, float] = {}  # share of quality-passed readings, 0..1 - the measured thing
    readingsBelow: dict[str, int] = {}
    worstMinC: float = 0.0  # coldest single observation in the window
    freezeThawPerYear: float = 0.0
    p01C: float | None = None
    p99C: float | None = None
    km: float | None = None  # filled by the nearest-station join, not by the builder
    aqLocationId: int | None = None
    aqKm: float | None = None
    pm10P90: float | None = None
    dustyDays: int | None = None


class ClimateVerdict(BaseModel):
    rule: ClimateRule
    status: Literal["ok", "borderline", "breached", "unknown"]
    claim: str  # the manual's own line, shortened - never prose
    evidence: str  # "108 readings below -25 C (~63 h) at FALLS INTERNATIONAL, 2024"
    magnitude: float | None = None  # hours/year, or percent of year
    stationId: str
    stationKm: float


class ClimateFit(BaseModel):
    manualId: str
    bikeId: str | None = None
    station: StationClimate
    verdicts: list[ClimateVerdict]
    breached: int
    checked: int
    ms: float = 0.0


class ClimateAnomaly(BaseModel):
    ruleType: RuleType
    name: str
    values: list[tuple[str, int]]  # printed value -> manuals printing it
    manuals: int
    markets: dict[str, int]
    makes: dict[str, int]
    spread: float  # 0.0 = every manual prints the same number
