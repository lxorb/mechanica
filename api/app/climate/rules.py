"""The rulebook: every environment-conditional clause the manuals already print.

Build-time only. Three passes, and the third one is the reason this is a feature and not a liability:

  Pass A  deterministic candidate finder. One regex family per rule type over the page text layer.
          No model, no cost. For `antifreeze_floor` and `oil_grade_band` the regex also parses the
          value, so the demo path costs exactly $0.
  Pass B  structuring. Only the candidate windows Pass A could not parse are sent to the model, one
          cheap call per window - never per page. Route "climate.extract", model gpt-5.6-luna,
          structured output, hard USD cap.
  Pass C  grounding, mandatory, applied to every rule from either pass. The quote must be a
          character-for-character substring of the page's own text layer under the same whitespace
          and dash folding app/ingest/ground.py uses. An invented threshold is a seized engine.

Watch the minus sign: these PDFs print U+2212 MINUS SIGN and U+2013 EN DASH, never ASCII hyphen, and
they print U+2265 for "at least". Every pattern here spells the whole family out.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from ..store import get_store
from .models import ClimateRule
from .paths import climate_dir, rules_dir

try:  # the same gate, the same code path as the ingest highlights
    from ..ingest.ground import fold, norm
except Exception:  # pragma: no cover - pymupdf missing in a lean environment
    _WS = re.compile(r"\s+")
    _FOLD = {0x00AD: "", 0x200B: "", 0x00A0: " ", 0x2010: "-", 0x2011: "-", 0x2012: "-",
             0x2013: "-", 0x2014: "-", 0x2212: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"',
             0x201D: '"', 0x02BC: "'"}

    def fold(text: str) -> str:
        return _WS.sub(" ", text.translate(_FOLD)).strip()

    def norm(text: str) -> str:
        return fold(text).lower()


EXTRACT_ROUTE = "climate.extract"
EXTRACT_MODEL = "gpt-5.6-luna"
WINDOW = 400  # +/- characters handed to pass B, never a whole page
MAX_QUOTE = 240

# --- character classes the text layer actually uses ------------------------------------------------
MINUS = r"[-‐‑‒–—―−]"
NUM = rf"{MINUS}?\s?\d{{1,3}}(?:[.,]\d)?"
DEG = r"\s*°\s*"
GE = r"≥|>=|at least|min\.|from"
LE = r"≤|<=|max\.|up to"

_DEGREE = re.compile(rf"({NUM})\s*°\s*([CF])")
_SAE = re.compile(r"SAE\s*\d{1,2}\s*W\s*[-/]\s*\d{2}", re.I)
_INTERVAL = re.compile(r"(\d[\d.,]*)\s*(km|mi|miles|hours?|h|months?)\b", re.I)
# "-25 … -45 °C": a printed range where only the second end carries the unit.
_RANGE = re.compile(rf"({NUM})\s*(?:…|\.{{2,3}}|to|bis)\s*({NUM})\s*°\s*([CF])", re.I)

# --- pass A: one family per rule type ---------------------------------------------------------------
# "Antifreeze protection to at least: -25 C (-13.0 F)". Also the four non-English spellings that
# appear in this corpus, because 43 languages ship the same clause.
ANTIFREEZE = re.compile(
    rf"(?is)\b(antifreeze|anti-freeze|frost\s?protection|frostschutz|antigel|anticongelante)\b"
    rf".{{0,70}}?({NUM}){DEG}(C|F)"
)

# "Ambient temperature: >=0 C (>=32.0 F) / engine oil (SAE 10W/50)" - the grade and the band are on
# two different lines, which is why this one crosses newlines.
OIL_BAND = re.compile(
    rf"(?is)\b(ambient\s+temperatures?|outside\s+temperatures?|umgebungstemperatur)\b\s*[:\-]?\s*"
    rf"({GE}|{LE}|<|>|below|above|under|over)?\s*({NUM}){DEG}(C|F)"
    rf".{{0,140}}?({_SAE.pattern})"
)

DUST = re.compile(r"(?is)\b(dust|dusty|sandy|sand)\b")
WET = re.compile(r"(?is)\b(wet|muddy|mud|rain|rainy)\b")
SALT = re.compile(r"(?is)\b(road salt|salted road|salt[- ]?spread|sea air|coastal|salt water|ocean)\b")
SALT_VERB = re.compile(r"(?is)\b(clean|wash|rinse|lubricat|corros|protect)\w*")
COLD = re.compile(rf"(?is)\b(below\s*{NUM}\s*°\s*[CF]|freezing|cold weather|low temperatures?)\b")
COLD_NEAR = re.compile(r"(?is)\b(start|starting|warm[- ]?up|battery|idle)\b")
ALTITUDE = re.compile(r"(?is)\baltitudes?\s+(of|above|over|exceeding|higher than)\b.{0,40}?(\d[\d.,]*)\s*(m|meters?|metres?|ft|feet)\b")
HEAT = re.compile(rf"(?is)\b(above\s*{NUM}\s*°\s*[CF]|high ambient|extreme heat|hot weather)\b")
HEAT_NEAR = re.compile(r"(?is)\b(display|battery|charging|coolant|overheat|cooling)\w*")
MORE_OFTEN = re.compile(r"(?is)\bmore\s+(frequently|often)\b|\bshorten\w*\s+the\s+interval|severe\s+(operating\s+)?conditions")

# Rule types pass A parses on its own. Everything else is a candidate for pass B.
DETERMINISTIC = ("antifreeze_floor", "oil_grade_band", "altitude")

LABELS = {
    "antifreeze_floor": "Antifreeze protection",
    "oil_grade_band": "Engine oil grade",
    "dust_interval": "Dusty conditions",
    "wet_interval": "Wet conditions",
    "salt_wash": "Road salt / sea air",
    "cold_start": "Cold start",
    "altitude": "High altitude",
    "heat_limit": "High ambient temperature",
}


def to_c(value: float, unit: str) -> float:
    return round((value - 32.0) * 5.0 / 9.0, 1) if unit.upper() == "F" else value


def parse_number(raw: str) -> float | None:
    cleaned = re.sub(r"\s+", "", raw).replace(",", ".")
    for ch in "‐‑‒–—―−":
        cleaned = cleaned.replace(ch, "-")
    try:
        return float(cleaned)
    except ValueError:
        return None


def comparator_of(token: str | None) -> str:
    if not token:
        return "always"
    t = token.strip().lower()
    if t in ("≥", ">=", "at least", "min.", "from"):
        return "at_or_above"
    if t in ("≤", "<=", "max.", "up to"):
        return "at_or_below"
    if t in (">", "above", "over"):
        return "above"
    if t in ("<", "below", "under"):
        return "below"
    return "always"


def line_span(text: str, start: int, end: int, pad: int = 0) -> tuple[int, int]:
    """Grow a match to whole lines so the quote is a printed line, not a fragment."""
    a = text.rfind("\n", 0, max(0, start - pad))
    b = text.find("\n", min(len(text), end + pad))
    return (a + 1 if a >= 0 else 0), (b if b >= 0 else len(text))


def rule_id(manual_id: str, page: int, rule_type: str, value: str) -> str:
    return hashlib.sha1(f"{manual_id}|{page}|{rule_type}|{value}".encode()).hexdigest()[:12]


def grounded(quote: str, page_text: str) -> bool:
    """Pass C. Character-for-character after the same folding the ingest highlights use."""
    needle = norm(quote)
    return len(needle) >= 8 and needle in norm(page_text)


def floor_of(quote: str, first: float) -> float:
    """A frost-protection clause is often printed as a RANGE: "-45 C ... -25 C" is the mixing window,
    not a promise of -45. The guaranteed floor is the weakest end, so take the value closest to zero.
    Any Fahrenheit twin on the same line converts to the same number and changes nothing."""
    values = []
    for m in _RANGE.finditer(quote):  # "-25 ... -45 C": the first end carries no unit of its own
        v = parse_number(m.group(1))
        if v is not None and -60 <= to_c(v, m.group(3)) <= 10:
            values.append(to_c(v, m.group(3)))
    for m in _DEGREE.finditer(quote):
        v = parse_number(m.group(1))
        if v is None:
            continue
        c = to_c(v, m.group(2))
        if -60 <= c <= 10:
            values.append(c)
    return max(values) if values else first


def _clip(text: str, start: int, end: int) -> str:
    quote = text[start:end].strip()
    if len(quote) > MAX_QUOTE:
        quote = quote[:MAX_QUOTE].rsplit(" ", 1)[0]
    return re.sub(r"\s*\n\s*", " ", quote).strip(" :;-–−")


def pass_a(manual_id: str, page: int, text: str, types: tuple[str, ...]) -> tuple[list[ClimateRule], list[dict]]:
    """Deterministic pass. Returns (parsed rules, candidate windows for pass B)."""
    rules: list[ClimateRule] = []
    windows: list[dict] = []

    def add(rule_type: str, value: str, quote: str, **kw) -> None:
        if not quote:
            return
        rules.append(ClimateRule(
            id=rule_id(manual_id, page, rule_type, value),
            manualId=manual_id, ruleType=rule_type, name=LABELS[rule_type],
            value=value, page=page, quote=quote, source="regex", **kw,
        ))

    if "antifreeze_floor" in types:
        for m in ANTIFREEZE.finditer(text):
            value = parse_number(m.group(2))
            if value is None or not (-60 <= value <= 10):
                continue
            a, b = line_span(text, m.start(), m.end())
            quote = _clip(text, a, b)
            c = floor_of(quote, to_c(value, m.group(3)))
            add("antifreeze_floor", f"{c:g} °C", quote, comparator="at_or_below", thresholdC=c)

    if "oil_grade_band" in types:
        for m in OIL_BAND.finditer(text):
            value = parse_number(m.group(3))
            if value is None or not (-60 <= value <= 60):
                continue
            c = to_c(value, m.group(4))
            grade = re.sub(r"\s+", "", m.group(5)).upper()
            a, b = line_span(text, m.start(), m.end())
            add("oil_grade_band", grade, _clip(text, a, b),
                comparator=comparator_of(m.group(2)), thresholdC=c)

    if "altitude" in types:
        for m in ALTITUDE.finditer(text):
            value = parse_number(m.group(2))
            if value is None:
                continue
            metres = round(value * 0.3048) if m.group(3).lower().startswith("f") else value
            if not (300 <= metres <= 8000):
                continue
            a, b = line_span(text, m.start(), m.end())
            add("altitude", f"{metres:g} m", _clip(text, a, b),
                comparator="at_or_above", thresholdM=float(metres))

    # candidate windows for pass B: a trigger plus its co-trigger, nothing else
    def window(rule_type: str, m: re.Match) -> None:
        a, b = line_span(text, max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW))
        qa, qb = line_span(text, m.start(), m.end())
        windows.append({
            "manualId": manual_id, "ruleType": rule_type, "page": page,
            "window": re.sub(r"\s*\n\s*", " ", text[a:b]).strip(),
            "hint": _clip(text, qa, qb),
        })

    def near(a: re.Match, other: re.Pattern, span: int) -> bool:
        lo, hi = max(0, a.start() - span), min(len(text), a.end() + span)
        return bool(other.search(text, lo, hi))

    for rule_type, trigger, co, span in (
        ("dust_interval", DUST, MORE_OFTEN, 200),
        ("wet_interval", WET, MORE_OFTEN, 200),
        ("salt_wash", SALT, SALT_VERB, 200),
        ("cold_start", COLD, COLD_NEAR, 160),
        ("heat_limit", HEAT, HEAT_NEAR, 160),
    ):
        if rule_type not in types:
            continue
        for m in trigger.finditer(text):
            if co is MORE_OFTEN and not (near(m, MORE_OFTEN, span) or near(m, _INTERVAL, span)):
                continue
            if co is not MORE_OFTEN and not near(m, co, span):
                continue
            window(rule_type, m)
            break  # one candidate window per rule type per page; the clause repeats within a page

    return rules, windows


# --- pass B -----------------------------------------------------------------------------------------

class ExtractedRule(BaseModel):
    applies: bool
    name: str
    comparator: str | None = None
    thresholdC: float | None = None
    thresholdM: float | None = None
    value: str | None = None
    intervalKm: int | None = None
    quote: str


SYSTEM = (
    "You turn one clause from a vehicle owner's manual into one typed rule. "
    "The clause is conditional on the environment the vehicle lives in. "
    "`quote` MUST be copied character-for-character from the text you are given - never reworded, "
    "never completed, never translated. If the text carries no such rule, set applies=false. "
    "Never invent a threshold: if the manual does not print a number, leave the number null. "
    "comparator is one of below, at_or_below, above, at_or_above, always."
)


class CostMeter:
    """Spend on this route, read back from the cost store the LLM door already writes."""

    def __init__(self, cap: float):
        self.cap = cap
        self.path = self._costs_path()
        self.offset = self.path.stat().st_size if self.path and self.path.exists() else 0
        self.spent = 0.0

    @staticmethod
    def _costs_path() -> Path | None:
        root = getattr(get_store(), "root", None)
        return Path(root) / "costs.jsonl" if root else None

    def refresh(self) -> float:
        if self.path and self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                fh.seek(self.offset)
                total = 0.0
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("route") == EXTRACT_ROUTE:
                        total += float(event.get("usd") or 0.0)
                self.spent = total
        else:  # a blob-backed store: re-read the route total, which is what /cost shows anyway
            self.spent = sum(e.usd for e in get_store().costs() if e.route == EXTRACT_ROUTE)
        return self.spent

    def exhausted(self) -> bool:
        return self.refresh() >= self.cap


def pass_b(candidate: dict, cache: dict, meter: CostMeter) -> ClimateRule | None:
    """One cheap structured call per candidate window. Cached by sha256(window) so a rerun is free."""
    from .. import llm

    key = hashlib.sha256(f'{candidate["ruleType"]}|{candidate["window"]}'.encode()).hexdigest()
    hit = cache.get(key)
    if hit is None:
        if meter.exhausted():
            raise BudgetReached(meter.spent)
        out = llm.structured(
            EXTRACT_ROUTE, EXTRACT_MODEL, ExtractedRule, SYSTEM,
            f'rule type: {candidate["ruleType"]}\npage: {candidate["page"]}\n'
            f'clause:\n{candidate["window"]}',
        )
        hit = out.model_dump()
        cache[key] = hit
    if not hit.get("applies") or not hit.get("quote"):
        return None
    value = hit.get("value") or (f'{hit["thresholdC"]:g} °C' if hit.get("thresholdC") is not None else "more often")
    comparator = hit.get("comparator")
    if comparator not in ("below", "at_or_below", "above", "at_or_above", "always", None):
        comparator = None
    return ClimateRule(
        id=rule_id(candidate["manualId"], candidate["page"], candidate["ruleType"], str(value)),
        manualId=candidate["manualId"], ruleType=candidate["ruleType"],
        name=(hit.get("name") or LABELS[candidate["ruleType"]])[:80],
        comparator=comparator, thresholdC=hit.get("thresholdC"), thresholdM=hit.get("thresholdM"),
        value=str(value)[:60], intervalKm=hit.get("intervalKm"),
        page=candidate["page"], quote=fold(hit["quote"])[:MAX_QUOTE], source="model",
    )


class BudgetReached(RuntimeError):
    def __init__(self, spent: float):
        super().__init__(f"extraction budget reached at ${spent:.2f}")
        self.spent = spent


# --- driver -----------------------------------------------------------------------------------------

def manual_ids(store) -> list[str]:
    root = getattr(store, "root", None)
    if root:
        folder = Path(root) / "pages"
        if folder.exists():
            return sorted(p.stem for p in folder.glob("*.json"))
    summaries = getattr(store, "manual_summaries", None)
    if summaries:
        return sorted(s["id"] for s in summaries())
    return sorted(m.id for m in store.manuals())


def cache_path() -> Path:
    return climate_dir() / "extract_cache.json"


def build(use_model: bool = False, only: str | None = None, budget: float = 15.0,
          log: Callable[..., None] = print) -> dict:
    """Write api/data/climate/rules/{manualId}.json and rules_report.json."""
    store = get_store()
    ids = [only] if only else manual_ids(store)
    types = tuple(LABELS) if use_model else DETERMINISTIC
    out_dir = rules_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = json.loads(cache_path().read_text(encoding="utf-8")) if cache_path().exists() else {}
    meter = CostMeter(budget)
    started = time.time()

    report = {"manuals": 0, "withRules": 0, "rules": 0, "rulesDropped": 0, "pages": 0,
              "candidates": 0, "modelRules": 0, "byType": {}, "usd": 0.0, "budget": budget,
              "budgetReached": False, "model": EXTRACT_MODEL if use_model else None,
              "perManual": {}}
    stopped = False
    for i, manual_id in enumerate(ids):
        try:
            pages = store.pages(manual_id)
        except Exception as exc:
            log(f"  {manual_id}: pages unreadable ({type(exc).__name__})")
            continue
        report["manuals"] += 1
        report["pages"] += len(pages)
        rules: list[ClimateRule] = []
        dropped = 0
        windows: list[dict] = []
        for page in pages:
            got, cands = pass_a(manual_id, page.page, page.text or "", types)
            for rule in got:
                if grounded(rule.quote, page.text or ""):
                    rules.append(rule)
                else:
                    dropped += 1
            windows.extend(cands)
        report["candidates"] += len(windows)
        if use_model and not stopped:
            by_page = {p.page: (p.text or "") for p in pages}
            for cand in windows:
                try:
                    rule = pass_b(cand, cache, meter)
                except BudgetReached as exc:
                    log(f"budget cap reached at ${exc.spent:.2f} - stopping pass B")
                    report["budgetReached"] = True
                    stopped = True
                    break
                except Exception as exc:
                    log(f"  {manual_id} p.{cand['page']}: {type(exc).__name__}: {exc}")
                    continue
                if rule is None:
                    continue
                if grounded(rule.quote, by_page.get(rule.page, "")):
                    rules.append(rule)
                    report["modelRules"] += 1
                else:
                    dropped += 1
        seen: set[str] = set()
        unique = [r for r in rules if not (r.id in seen or seen.add(r.id))]
        if unique:
            report["withRules"] += 1
            (out_dir / f"{manual_id}.json").write_text(
                json.dumps([r.model_dump(exclude_none=True) for r in unique], ensure_ascii=False),
                encoding="utf-8")
        report["rules"] += len(unique)
        report["rulesDropped"] += dropped
        for r in unique:
            report["byType"][r.ruleType] = report["byType"].get(r.ruleType, 0) + 1
        report["perManual"][manual_id] = {"rules": len(unique), "dropped": dropped}
        if (i + 1) % 100 == 0:
            log(f"  {i + 1}/{len(ids)} manuals, {report['rules']} rules, {report['rulesDropped']} dropped")

    if use_model:
        cache_path().write_text(json.dumps(cache), encoding="utf-8")
    report["usd"] = round(meter.refresh(), 4)
    report["seconds"] = round(time.time() - started, 1)
    (climate_dir() / "rules_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    log(f"rules: {report['rules']} from {report['withRules']}/{report['manuals']} manuals, "
        f"{report['pages']} pages, {report['rulesDropped']} dropped by grounding, "
        f"${report['usd']:.4f} on {EXTRACT_ROUTE}")
    log(f"  by type: {report['byType']}")
    return report
