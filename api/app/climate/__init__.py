"""Climate Fit: the manual already printed a rule that depends on where the vehicle lives; we
resolve it against the measured climate there and show the manufacturer's own line.

The only thing the API imports is `fit()`. Everything under this package that touches the network -
isd.py, openaq.py, rules.py - is build-time and is imported lazily, so a half-written builder can
never take the API down. Same defence as app/registry/__init__.py.
"""

from __future__ import annotations

import time

from .models import ClimateFit, ClimateRule, ClimateVerdict, StationClimate
from .stations import (
    MAX_KM,
    anomalies,
    by_name,
    climatology,
    dedupe,
    evaluate,
    manuals_with_rules,
    nearest,
    rules_for,
    station_model,
)

__all__ = [
    "ClimateFit", "ClimateRule", "ClimateVerdict", "StationClimate",
    "fit", "station_at", "station_named", "rules_for", "anomalies", "manuals_with_rules", "MAX_KM",
]

_STATUS_ORDER = {"breached": 0, "borderline": 1, "ok": 2, "unknown": 3}


def station_at(lat: float, lon: float) -> StationClimate | None:
    row, km = nearest(lat, lon)
    return station_model(row, km) if row else None


def station_named(query: str) -> StationClimate | None:
    row = by_name(query)
    return station_model(row, 0.0) if row else None


def fit(manual_id: str, lat: float, lon: float, bike_id: str | None = None) -> ClimateFit | None:
    """Every environment-conditional rule this manual prints, resolved against the nearest station.

    Pure computation over two in-memory tables: no model call, no network, no cost.
    """
    started = time.perf_counter()
    row, km = nearest(lat, lon)
    if row is None:
        return None
    rules = dedupe(rules_for(manual_id))
    verdicts = [evaluate(rule, row, km) for rule in rules]
    verdicts.sort(key=lambda v: (_STATUS_ORDER.get(v.status, 9), v.rule.page))
    return ClimateFit(
        manualId=manual_id,
        bikeId=bike_id,
        station=station_model(row, km),
        verdicts=verdicts,
        breached=sum(1 for v in verdicts if v.status == "breached"),
        checked=sum(1 for v in verdicts if v.status != "unknown"),
        ms=round((time.perf_counter() - started) * 1000, 2),
    )
