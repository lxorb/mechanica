"""NOAA Integrated Surface Database: stream one station-year, keep one row.

Build-time only. Nothing here is imported by the API at runtime - the runtime reads the reduced
artefacts in api/data/climate. Lifted from docs/pitches/voloridge/isd_probe.py, which is the version
that was measured on 2026-09-20; the parse below is character-for-character the same.

s3://noaa-isd-pds is public and anonymous and also answers on plain HTTPS, so there is no boto3, no
AWS account and no key anywhere in this pipeline.

Fixed-width control section, 1-based positions from the ISD format document:
    5-10   USAF        11-15  WBAN       16-23  date YYYYMMDD    24-27  time HHMM
    88-92  air temp, signed tenths of degrees C, "+9999" = missing
    93     air temp quality code; 2,3,6,7,9 = suspect or erroneous and must be dropped
    94-98  dew point, same shape, 99 = quality
"""

from __future__ import annotations

import csv
import gzip
import io
import math
import time
import urllib.error
import urllib.request

BASE = "https://noaa-isd-pds.s3.amazonaws.com"
HISTORY_URL = f"{BASE}/isd-history.csv"
UA = "mechanica-climate-fit/1.0 (+https://mechanica.emilvinu.ch)"

# Quality codes that mean "do not use this reading". Keep this a constant, never a literal in a loop.
BAD_QUALITY = "23679"
MISSING = "+9999"

# Every threshold the rulebook can ask about, in degrees C. A station-year is reduced once; a new
# rule threshold must land on one of these or the verdict interpolates from the histogram.
COLD_THRESHOLDS: tuple[int, ...] = (5, 0, -5, -10, -15, -20, -25, -30, -35, -40)
HOT_THRESHOLDS: tuple[int, ...] = (30, 35, 40, 45)
HOURS_PER_YEAR = 8766.0

# Stations whose END is before this are historical: a nearest-station join that lands on one of them
# silently answers with weather from 1994.
ACTIVE_SINCE = "20250101"

# Politeness. The bucket is a public S3 endpoint with no published rate limit, but we are a guest:
# one retry with a backoff, a short pause between misses, and a capped thread count at the call site.
RETRIES = 2
BACKOFF_S = 1.5
TIMEOUT_S = 60


def _open(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def fetch_history() -> list[dict]:
    """isd-history.csv: USAF, WBAN, STATION NAME, CTRY, STATE, ICAO, LAT, LON, ELEV(M), BEGIN, END."""
    text = _open(HISTORY_URL).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def num(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (TypeError, ValueError, KeyError):
        return None


def active(rows: list[dict], since: str = ACTIVE_SINCE) -> list[dict]:
    """Stations still reporting. 12,776 of 29,661 as of 2026-09-20; the rest are historical."""
    out = []
    for r in rows:
        lat, lon = num(r, "LAT"), num(r, "LON")
        if lat is None or lon is None or (lat == 0 and lon == 0):
            continue
        if (r.get("END") or "") < since:
            continue
        out.append(r)
    return out


def station_id(row: dict) -> str:
    return f'{row["USAF"]}-{row["WBAN"]}'


def station_row(row: dict) -> dict:
    return {
        "id": station_id(row),
        "name": (row.get("STATION NAME") or "").strip(),
        "ctry": (row.get("CTRY") or "").strip(),
        "state": (row.get("STATE") or "").strip() or None,
        "icao": (row.get("ICAO") or "").strip() or None,
        "lat": num(row, "LAT"),
        "lon": num(row, "LON"),
        "elevM": num(row, "ELEV(M)"),
    }


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Kilometres. Used for the station <-> OpenAQ join, where 25 km is a hard gate."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def reduce_stream(raw: bytes, drop_bad_quality: bool = True) -> dict | None:
    """One station-year of gzipped fixed-width records -> one row. The 600 GB -> 4 MB trick.

    `drop_bad_quality=False` exists for the shipped ablation report, not for production.
    """
    n = 0
    total = 0.0
    mn, mx = 999.0, -999.0
    below = {t: 0 for t in COLD_THRESHOLDS}
    above = {t: 0 for t in HOT_THRESHOLDS}
    hist: dict[int, int] = {}
    day_min: dict[str, float] = {}
    day_max: dict[str, float] = {}
    try:
        with gzip.open(io.BytesIO(raw), "rt", encoding="latin-1") as fh:
            for line in fh:
                if len(line) < 93:
                    continue
                value, quality = line[87:92], line[92:93]
                if value == MISSING:
                    continue
                if drop_bad_quality and quality in BAD_QUALITY:
                    continue
                try:
                    c = int(value) / 10.0
                except ValueError:
                    continue
                n += 1
                total += c
                if c < mn:
                    mn = c
                if c > mx:
                    mx = c
                bucket = int(round(c))
                hist[bucket] = hist.get(bucket, 0) + 1
                for t in COLD_THRESHOLDS:
                    if c < t:
                        below[t] += 1
                for t in HOT_THRESHOLDS:
                    if c > t:
                        above[t] += 1
                day = line[15:23]
                if day not in day_min or c < day_min[day]:
                    day_min[day] = c
                if day not in day_max or c > day_max[day]:
                    day_max[day] = c
    except (OSError, EOFError, gzip.BadGzipFile):
        return None
    if not n:
        return None
    cycles = sum(1 for d in day_min if day_min[d] < 0.0 <= day_max.get(d, -99.0))
    return {
        "obs": n,
        "minC": round(mn, 1),
        "maxC": round(mx, 1),
        "meanC": round(total / n, 2),
        "below": {str(t): below[t] for t in COLD_THRESHOLDS},
        "above": {str(t): above[t] for t in HOT_THRESHOLDS},
        "days": len(day_min),
        "freezeThaw": cycles,
        "p01C": percentile(hist, n, 0.01),
        "p99C": percentile(hist, n, 0.99),
    }


def percentile(hist: dict[int, int], n: int, q: float) -> float:
    """Percentile off the 1 degree histogram. Exact to the bin, which is all the UI ever shows."""
    target = q * n
    seen = 0
    for bucket in sorted(hist):
        seen += hist[bucket]
        if seen >= target:
            return float(bucket)
    return float(max(hist) if hist else 0)


def fetch_year(sid: str, year: int) -> bytes | None:
    """Stream one station-year. Never written to disk: the reduced row is the artefact."""
    url = f"{BASE}/data/{year}/{sid}-{year}.gz"
    for attempt in range(RETRIES + 1):
        try:
            return _open(url)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None  # the station did not report that year; isd-inventory would say so too
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF_S * (attempt + 1))
        except Exception:
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF_S * (attempt + 1))
    return None


def reduce_station_year(sid: str, year: int, drop_bad_quality: bool = True) -> dict | None:
    raw = fetch_year(sid, year)
    if raw is None:
        return None
    row = reduce_stream(raw, drop_bad_quality=drop_bad_quality)
    if row is None:
        return None
    row["id"] = sid
    row["year"] = year
    row["bytes"] = len(raw)
    return row


def merge_years(rows: list[dict]) -> dict:
    """Several station-years -> the one record the runtime reads.

    Observations are NOT hourly: Minneapolis reports one every ~38 minutes and a thin station six a
    day. So the stored quantity is the SHARE of quality-passed readings below each threshold, and
    hours are only ever derived as share x 8,766 at render time.
    """
    obs = sum(r["obs"] for r in rows)
    years = sorted({r["year"] for r in rows})
    below: dict[str, int] = {}
    above: dict[str, int] = {}
    for r in rows:
        for k, v in r["below"].items():
            below[k] = below.get(k, 0) + v
        for k, v in r["above"].items():
            above[k] = above.get(k, 0) + v
    share_below = {k: (v / obs if obs else 0.0) for k, v in below.items()}
    share_above = {k: (v / obs if obs else 0.0) for k, v in above.items()}
    return {
        "years": years,
        "obs": obs,
        "minC": min(r["minC"] for r in rows),
        "maxC": max(r["maxC"] for r in rows),
        "meanC": round(sum(r["meanC"] * r["obs"] for r in rows) / obs, 2) if obs else 0.0,
        "shareBelow": {k: round(v, 6) for k, v in share_below.items()},
        "shareAbove": {k: round(v, 6) for k, v in share_above.items()},
        "readingsBelow": below,
        "readingsAbove": above,
        "hoursBelow": {k: round(v * HOURS_PER_YEAR, 1) for k, v in share_below.items()},
        "hoursAbove": {k: round(v * HOURS_PER_YEAR, 1) for k, v in share_above.items()},
        "worstMinC": min(r["minC"] for r in rows),
        "freezeThawPerYear": round(sum(r["freezeThaw"] for r in rows) / len(years), 1),
        "p01C": min(r["p01C"] for r in rows),
        "p99C": max(r["p99C"] for r in rows),
    }
