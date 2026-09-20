"""Runtime half of Climate Fit. Two in-memory tables, no model call, no network, no cost.

Tables are read once per process and re-read when the file's mtime moves - the same trick
app/registry uses. A verdict is pure arithmetic over a station record and a printed rule, which is
why /climate/fit answers in tens of milliseconds and adds $0 to a question that already costs
$0.0003.

The stored quantity is the SHARE of quality-passed readings below each threshold, never a count of
hours: ISD observations are not hourly. Hours are derived as share x 8,766 at render time, and the
UI says "108 readings below -25 C (~63 h)" so the reader can see which number was measured.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from .isd import COLD_THRESHOLDS, HOT_THRESHOLDS, HOURS_PER_YEAR, haversine
from .models import ClimateRule, ClimateVerdict, StationClimate
from .paths import climate_dir, rules_dir

# A verdict from a station further away than this is not a verdict. It renders grey.
MAX_KM = 50.0
# Shares, not counts: a band that fires for less than this is "borderline", not "action needed".
BAND_SHARE = 0.05
FIRE_SHARE = 0.01
BORDERLINE_C = 3.0  # within 3 C of the printed floor is borderline, not ok

_lock = threading.RLock()
_cache: dict[str, tuple[float, object]] = {}


def _load(name: str, default):
    path = climate_dir() / name
    with _lock:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return default
        hit = _cache.get(name)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
        _cache[name] = (stamp, data)
        return data


def climatology() -> list[dict]:
    return _load("climatology.json", [])


def stations() -> list[dict]:
    return _load("stations.json", [])


def air() -> dict[str, dict]:
    rows = _load("air.json", [])
    return {str(r["id"]): r for r in rows} if isinstance(rows, list) else {}


def anomalies() -> list[dict]:
    return _load("anomalies.json", [])


def rules_for(manual_id: str) -> list[ClimateRule]:
    path = rules_dir() / f"{manual_id}.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [ClimateRule.model_validate(r) for r in rows]


def manuals_with_rules() -> list[str]:
    folder: Path = rules_dir()
    return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []


# --- nearest station --------------------------------------------------------------------------------

def nearest(lat: float, lon: float) -> tuple[dict | None, float]:
    """Nearest station that actually has a reduced climatology. Equirectangular first, haversine last."""
    rows = climatology()
    if not rows:
        return None, 0.0
    cos = math.cos(math.radians(lat))
    best, best_d = None, 1e18
    for r in rows:
        dy = r["lat"] - lat
        dx = (r["lon"] - lon) * cos
        d = dy * dy + dx * dx
        if d < best_d:
            best_d, best = d, r
    return best, round(haversine(lat, lon, best["lat"], best["lon"]), 1)


def by_name(query: str) -> dict | None:
    """A typed city, resolved against the station table itself - no external geocoder, ever."""
    needle = "".join(ch for ch in query.lower() if ch.isalnum())
    if not needle:
        return None
    rows = climatology()
    best = None
    for r in rows:
        hay = "".join(ch for ch in r["name"].lower() if ch.isalnum())
        if not hay:
            continue
        if hay == needle:
            return r
        if needle in hay and (best is None or len(hay) < len(best["name"])):
            best = r
    return best


def station_model(row: dict, km: float | None = None) -> StationClimate:
    aq = air().get(str(row.get("aqLocationId"))) if row.get("aqLocationId") is not None else None
    return StationClimate(
        id=row["id"], name=row["name"], ctry=row.get("ctry") or "", lat=row["lat"], lon=row["lon"],
        elevM=row.get("elevM"), years=row.get("years") or [], obs=row.get("obs") or 0,
        minC=row.get("minC", 0.0), maxC=row.get("maxC", 0.0), meanC=row.get("meanC", 0.0),
        hoursBelow=row.get("hoursBelow") or {}, hoursAbove=row.get("hoursAbove") or {},
        shareBelow=row.get("shareBelow") or {}, readingsBelow=row.get("readingsBelow") or {},
        worstMinC=row.get("worstMinC", row.get("minC", 0.0)),
        freezeThawPerYear=row.get("freezeThawPerYear", 0.0),
        p01C=row.get("p01C"), p99C=row.get("p99C"), km=km,
        aqLocationId=row.get("aqLocationId"), aqKm=row.get("aqKm"),
        pm10P90=(aq or {}).get("pm10P90"), dustyDays=(aq or {}).get("dustyDays"),
    )


# --- verdicts ---------------------------------------------------------------------------------------

def _bucket(thresholds: tuple[int, ...], value: float) -> int:
    return min(thresholds, key=lambda t: abs(t - value))


def _years(row: dict) -> str:
    years = row.get("years") or []
    if not years:
        return ""
    return str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"


def _share_below(row: dict, c: float) -> tuple[float, int, int]:
    """(share, readings, the stored threshold that answered). Stored buckets are 5 C apart."""
    t = _bucket(COLD_THRESHOLDS, c)
    return float((row.get("shareBelow") or {}).get(str(t), 0.0)), int((row.get("readingsBelow") or {}).get(str(t), 0)), t


def _share_above(row: dict, c: float) -> tuple[float, int]:
    t = _bucket(HOT_THRESHOLDS, c)
    share = float((row.get("shareAbove") or {}).get(str(t), 0.0))
    return share, t


def _hours(share: float) -> float:
    return round(share * HOURS_PER_YEAR, 0)


def _unknown(rule: ClimateRule, row: dict, km: float, why: str) -> ClimateVerdict:
    return ClimateVerdict(rule=rule, status="unknown", claim=rule.quote, evidence=why,
                          stationId=row.get("id", ""), stationKm=km)


def evaluate(rule: ClimateRule, row: dict, km: float) -> ClimateVerdict:
    """One printed rule against one station record. No model, no network."""
    name = row.get("name") or row.get("id", "")
    years = _years(row)
    base = {"rule": rule, "stationId": row.get("id", ""), "stationKm": km, "claim": rule.quote}

    if km > MAX_KM:
        return _unknown(rule, row, km, f"no station within {MAX_KM:.0f} km")

    if rule.ruleType == "antifreeze_floor" and rule.thresholdC is not None:
        share, readings, bucket = _share_below(row, rule.thresholdC)
        worst = row.get("worstMinC", row.get("minC", 0.0))
        if worst < rule.thresholdC:
            status = "breached"
        elif worst < rule.thresholdC + BORDERLINE_C:
            status = "borderline"
        else:
            status = "ok"
        exact = "" if bucket == rule.thresholdC else f" (nearest measured step {bucket} °C)"
        evidence = (f"{readings:,} readings below {bucket} °C (~{_hours(share):.0f} h/yr), "
                    f"low {worst:g} °C at {name}, {years}{exact}")
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=_hours(share))

    if rule.ruleType == "oil_grade_band" and rule.thresholdC is not None:
        cold = rule.comparator in ("below", "at_or_below")
        if cold:
            share, readings, bucket = _share_below(row, rule.thresholdC)
            status = "breached" if share >= BAND_SHARE else ("borderline" if share > 0 else "ok")
            evidence = (f"{share * 100:.1f}% of readings below {bucket} °C "
                        f"(~{_hours(share):.0f} h/yr) at {name}, {years}")
        else:
            share_below, _readings, bucket = _share_below(row, rule.thresholdC)
            share = 1.0 - share_below
            status = "ok" if share >= BAND_SHARE else "borderline"
            evidence = (f"{share * 100:.1f}% of readings at or above {bucket} °C at {name}, {years}")
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=round(share * 100, 1))

    if rule.ruleType == "cold_start" and rule.thresholdC is not None:
        share, readings, bucket = _share_below(row, rule.thresholdC)
        status = "breached" if share >= FIRE_SHARE else ("borderline" if share > 0 else "ok")
        evidence = (f"{readings:,} readings below {bucket} °C (~{_hours(share):.0f} h/yr) "
                    f"at {name}, {years}")
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=_hours(share))

    if rule.ruleType == "heat_limit" and rule.thresholdC is not None:
        share, bucket = _share_above(row, rule.thresholdC)
        status = "breached" if share >= FIRE_SHARE else ("borderline" if share > 0 else "ok")
        evidence = (f"{share * 100:.1f}% of readings above {bucket} °C (~{_hours(share):.0f} h/yr) "
                    f"at {name}, {years}")
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=_hours(share))

    if rule.ruleType == "altitude" and rule.thresholdM is not None:
        elev = row.get("elevM")
        if elev is None:
            return _unknown(rule, row, km, f"{name} reports no elevation")
        status = "breached" if elev >= rule.thresholdM else "ok"
        evidence = f"{name} sits at {elev:g} m, {years}"
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=float(elev))

    if rule.ruleType == "salt_wash":
        share, _readings, _b = _share_below(row, 0)
        cycles = row.get("freezeThawPerYear", 0.0)
        if share < FIRE_SHARE:
            return _unknown(rule, row, km,
                            f"no freezing readings at {name}; coastal exposure is not measured")
        status = "breached"
        evidence = (f"{share * 100:.1f}% of readings below 0 °C and {cycles:g} freeze-thaw days/yr "
                    f"at {name}, {years}")
        return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=cycles)

    if rule.ruleType in ("dust_interval", "wet_interval"):
        aq = air().get(str(row.get("aqLocationId"))) if row.get("aqLocationId") is not None else None
        if rule.ruleType == "dust_interval":
            if not aq:
                return _unknown(rule, row, km, "no air-quality station within 25 km")
            p90 = aq.get("pm10P90")
            dusty = aq.get("dustyDays")
            if p90 is None:
                return _unknown(rule, row, km, f"{aq.get('name', 'nearest sensor')} reports no PM10")
            status = "breached" if (dusty or 0) >= 30 else ("borderline" if (dusty or 0) > 0 else "ok")
            evidence = (f"PM10 p90 {p90:g} µg/m³, {dusty} days over 50 µg/m³ at "
                        f"{aq.get('name', '')}, {aq.get('km', row.get('aqKm'))} km")
            return ClimateVerdict(**base, status=status, evidence=evidence, magnitude=float(p90))
        return _unknown(rule, row, km, "precipitation is not in the reduced ISD record")

    return _unknown(rule, row, km, "no measurement for this rule type")


# --- one page, every verdict -------------------------------------------------------------------------

def dedupe(rules: list[ClimateRule]) -> list[ClimateRule]:
    """The same clause is printed on several pages. Keep it once, on the page that prints the most
    of this manual's rule types - which is how the demo lands on the technical-specifications page
    that carries both the antifreeze floor and the oil band, rather than on a service page that
    carries only one."""
    per_page: dict[int, set[str]] = {}
    for r in rules:
        per_page.setdefault(r.page, set()).add(r.ruleType)
    def score(page: int) -> tuple[int, int]:
        return (-len(per_page.get(page, ())), page)
    best: dict[tuple, ClimateRule] = {}
    for r in rules:
        key = (r.ruleType, r.comparator, r.thresholdC, r.thresholdM, r.value)
        cur = best.get(key)
        if cur is None or score(r.page) < score(cur.page):
            best[key] = r
    order = {"antifreeze_floor": 0, "oil_grade_band": 1, "cold_start": 2, "salt_wash": 3,
             "dust_interval": 4, "wet_interval": 5, "altitude": 6, "heat_limit": 7}
    return sorted(best.values(), key=lambda r: (order.get(r.ruleType, 9), r.page, r.value or ""))
