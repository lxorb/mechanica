"""OpenAQ: turn "service more often in dusty conditions" into a number.

Build-time only, and deliberately two separate steps:

  discovery  one offline pass against the OpenAQ v3 API (free key, header `X-API-Key`) writes
             api/data/climate/aq_locations.json - id, name, lat, lon, country, parameters. It is
             committed, so THE RUNTIME NEVER NEEDS THE KEY. The archive bucket has no location
             index, which is the whole reason this step exists.
  reduce     for each location with pm10 or pm25, stream `year=YYYY` days out of
             s3://openaq-data-archive (anonymous, plain HTTPS like NOAA) and reduce to
             pm10P50/P90, pm25P50/P90, dustyDays, days, sensors -> air.json.
  join       nearest OpenAQ location within 25 km of each ISD station (haversine). Further than
             that and the station gets aqLocationId: null, and the dust rules answer `unknown`
             instead of guessing.

Layout, verified against the registry entry:
    records/csv.gz/locationid={id}/year={YYYY}/month={MM}/location-{id}-{YYYYMMDD}.csv.gz
    columns: location_id, sensors_id, location, datetime, lat, lon, parameter, units, value

`dustyDays` counts days whose pm10 daily mean exceeds 50 ug/m3 - the WHO 2021 interim target-1
24-hour level. Named constant, not a literal in a loop.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import statistics
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .isd import haversine
from .paths import climate_dir

BUCKET = "https://openaq-data-archive.s3.amazonaws.com"
API = "https://api.openaq.org/v3/locations"
UA = "mechanica-climate-fit/1.0 (+https://mechanica.emilvinu.ch)"

PM10_DUSTY = 50.0  # WHO interim target-1, 24-hour mean, ug/m3
MIN_DAYS = 60  # a location reporting fewer days than this is dropped, and the drop is counted
JOIN_KM = 25.0  # a sensor further away than this is not this station's air
TIMEOUT_S = 30


def _get(url: str, headers: dict | None = None) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def discover(api_key: str, limit: int = 100000, log: Callable[..., None] = print) -> list[dict]:
    """One offline pass over the v3 API -> aq_locations.json. Needs a free key; the runtime does not."""
    out: list[dict] = []
    page = 1
    while len(out) < limit:
        raw = _get(f"{API}?limit=1000&page={page}", {"X-API-Key": api_key})
        if raw is None:
            break
        try:
            body = json.loads(raw)
        except Exception:
            break
        rows = body.get("results") or []
        if not rows:
            break
        for row in rows:
            coords = row.get("coordinates") or {}
            if coords.get("latitude") is None or coords.get("longitude") is None:
                continue
            out.append({
                "id": row.get("id"),
                "name": row.get("name") or "",
                "lat": coords["latitude"],
                "lon": coords["longitude"],
                "country": ((row.get("country") or {}).get("code") or ""),
                "parameters": sorted({(s.get("parameter") or {}).get("name")
                                      for s in (row.get("sensors") or [])
                                      if (s.get("parameter") or {}).get("name")}),
            })
        log(f"  openaq discovery page {page}: {len(out)} locations")
        page += 1
    path = climate_dir() / "aq_locations.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"openaq: {len(out)} locations -> {path}")
    return out


def day_url(location_id: int, day: date) -> str:
    return (f"{BUCKET}/records/csv.gz/locationid={location_id}/year={day.year}/"
            f"month={day.month:02d}/location-{location_id}-{day:%Y%m%d}.csv.gz")


def reduce_location(location_id: int, year: int) -> dict | None:
    """Stream one location-year of daily CSVs and keep one row. Nothing raw is written."""
    pm10_daily: list[float] = []
    pm25_daily: list[float] = []
    sensors: set[str] = set()
    days = 0
    cursor = date(year, 1, 1)
    end = date(year, 12, 31)
    while cursor <= end:
        raw = _get(day_url(location_id, cursor))
        cursor += timedelta(days=1)
        if raw is None:
            continue
        try:
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
        except Exception:
            continue
        pm10: list[float] = []
        pm25: list[float] = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                value = float(row.get("value") or "")
            except ValueError:
                continue
            if value < 0:
                continue
            parameter = (row.get("parameter") or "").lower()
            if parameter == "pm10":
                pm10.append(value)
            elif parameter == "pm25":
                pm25.append(value)
            else:
                continue
            if row.get("sensors_id"):
                sensors.add(row["sensors_id"])
        if pm10 or pm25:
            days += 1
        if pm10:
            pm10_daily.append(statistics.fmean(pm10))
        if pm25:
            pm25_daily.append(statistics.fmean(pm25))
    if days < MIN_DAYS:
        return None

    def q(values: list[float], p: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 1)

    return {
        "id": location_id, "year": year, "days": days, "sensors": len(sensors),
        "pm10P50": q(pm10_daily, 0.5), "pm10P90": q(pm10_daily, 0.9),
        "pm25P50": q(pm25_daily, 0.5), "pm25P90": q(pm25_daily, 0.9),
        "dustyDays": sum(1 for v in pm10_daily if v > PM10_DUSTY),
    }


def join_to_stations(air_rows: list[dict], locations: list[dict],
                     log: Callable[..., None] = print) -> int:
    """Write aqLocationId / aqKm onto climatology.json. Further than 25 km stays null."""
    path = climate_dir() / "climatology.json"
    if not path.exists():
        return 0
    stations = json.loads(path.read_text(encoding="utf-8"))
    usable = {row["id"] for row in air_rows}
    points = [loc for loc in locations if loc["id"] in usable]
    joined = 0
    for station in stations:
        best, best_km = None, 1e18
        for loc in points:
            km = haversine(station["lat"], station["lon"], loc["lat"], loc["lon"])
            if km < best_km:
                best_km, best = km, loc
        if best is not None and best_km <= JOIN_KM:
            station["aqLocationId"] = best["id"]
            station["aqKm"] = round(best_km, 1)
            joined += 1
        else:
            station.pop("aqLocationId", None)
            station.pop("aqKm", None)
    path.write_text(json.dumps(stations, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"openaq join: {joined}/{len(stations)} stations have a sensor within {JOIN_KM:g} km")
    return joined


def build(years: list[int], threads: int = 16, limit: int = 100000,
          log: Callable[..., None] = print) -> dict:
    """--openaq. Discovery runs only when OPENAQ_API_KEY is set; the reduce needs no key."""
    year = years[-1]
    path = climate_dir() / "aq_locations.json"
    key = os.environ.get("OPENAQ_API_KEY", "").strip()
    if not path.exists():
        if not key:
            log("openaq: no aq_locations.json and no OPENAQ_API_KEY - discovery skipped. "
                "The bucket has no location index, so the reduce cannot start without it. "
                "Dust verdicts stay `unknown`, which is the honest answer.")
            return {"locations": 0, "reduced": 0, "joined": 0, "skipped": "no key"}
        discover(key, log=log)
    locations = json.loads(path.read_text(encoding="utf-8"))
    wanted = [loc for loc in locations
              if {"pm10", "pm25"} & set(loc.get("parameters") or [])][:limit]
    log(f"openaq: reducing {len(wanted)} locations for {year} at {threads} threads")
    with ThreadPoolExecutor(max_workers=threads) as pool:
        rows = [r for r in pool.map(lambda loc: reduce_location(loc["id"], year), wanted) if r]
    dropped = len(wanted) - len(rows)
    out = climate_dir() / "air.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"openaq: {len(rows)} locations kept, {dropped} dropped for < {MIN_DAYS} reporting days "
        f"-> {out}")
    joined = join_to_stations(rows, locations, log=log)
    return {"locations": len(wanted), "reduced": len(rows), "dropped": dropped, "joined": joined}
