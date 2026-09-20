#!/usr/bin/env python3
"""NOAA ISD probe — the verified core of the Climate Fit reducer.

Run and measured 2026-09-20 on this machine; every number in docs/pitches/voloridge.md that mentions
a station came out of this file. It exists so the implementing agent starts from working code instead
of from the format document.

What it proves:
  * s3://noaa-isd-pds is readable anonymously over plain HTTPS - no boto3, no AWS account, no key.
      https://noaa-isd-pds.s3.amazonaws.com/isd-history.csv           2.9 MB, 29,661 stations
      https://noaa-isd-pds.s3.amazonaws.com/data/2024/{USAF}-{WBAN}-2024.gz
  * the fixed-width parse: air temperature is 1-based chars 88-92 (so Python [87:92]), signed,
    tenths of a degree C, "+9999" = missing, and char 93 ([92:93]) is the quality code - 2,3,6,7,9
    are erroneous/suspect and must be dropped or the minima are junk.
  * a whole station-year is ~0.1-1.0 MB gzipped and reduces to one row.

Usage:
    python isd_probe.py cities            # nearest-station join for the demo cities
    python isd_probe.py sample 260        # random global sample -> breach rate for the -25C floor
"""

from __future__ import annotations

import csv
import gzip
import io
import math
import os
import random
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://noaa-isd-pds.s3.amazonaws.com"
YEAR = 2024
CACHE = "isd"

# The one number 206 manuals in our corpus print, in all 9 markets. See spec.md section 7.
ANTIFREEZE_FLOOR_C = -25.0

DEMO_CITIES = {
    "Munich": (48.14, 11.58),
    "Zurich": (47.38, 8.54),
    "Minneapolis": (44.98, -93.26),
    "Fargo ND": (46.88, -96.79),
    "International Falls MN": (48.60, -93.40),
    "Denver": (39.74, -104.98),
    "Boston": (42.36, -71.06),
    "Oslo": (59.91, 10.75),
    "Anchorage": (61.22, -149.90),
    "Winnipeg": (49.90, -97.14),
    "Phoenix": (33.45, -112.07),
    "Delhi": (28.61, 77.21),
    "Bangkok": (13.75, 100.5),
}


def history() -> list[dict]:
    """isd-history.csv: USAF, WBAN, STATION NAME, CTRY, STATE, ICAO, LAT, LON, ELEV(M), BEGIN, END."""
    path = "isd-history.csv"
    if not os.path.exists(path):
        urllib.request.urlretrieve(f"{BASE}/isd-history.csv", path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def num(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (TypeError, ValueError, KeyError):
        return None


def active(rows: list[dict], since: str = "20250101") -> list[dict]:
    """Stations still reporting. 12,774 of 29,661 as of 2026-09-20 - the rest are historical."""
    return [
        r for r in rows
        if r["END"] >= since and num(r, "LAT") is not None and num(r, "LON") is not None
        and not (num(r, "LAT") == 0 and num(r, "LON") == 0)
    ]


def nearest(rows: list[dict], lat: float, lon: float) -> tuple[dict, float]:
    """Equirectangular nearest station. Good enough under ~500 km; swap for a KD-tree at scale."""
    best, best_d = None, 1e18
    for r in rows:
        dy = num(r, "LAT") - lat
        dx = (num(r, "LON") - lon) * math.cos(math.radians(lat))
        d = dy * dy + dx * dx
        if d < best_d:
            best_d, best = d, r
    return best, math.sqrt(best_d) * 111.0


def fetch(station_id: str, year: int = YEAR) -> str | None:
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{station_id}-{year}.gz"
    if not os.path.exists(path):
        try:
            urllib.request.urlretrieve(f"{BASE}/data/{year}/{station_id}-{year}.gz", path)
        except Exception:
            return None
    return path


def reduce_station(path: str) -> dict | None:
    """One station-year -> one row. This is the whole 600 GB -> 4 MB trick, in fifteen lines."""
    n = 0
    mn, mx = 999.0, -999.0
    buckets = {t: 0 for t in (0, -10, -20, -25, -30, -35)}
    hot = {35: 0, 40: 0}
    try:
        with gzip.open(path, "rt", encoding="latin-1") as fh:
            for line in fh:
                if len(line) < 93:
                    continue
                raw, quality = line[87:92], line[92:93]
                if raw == "+9999" or quality in "23679":  # missing, erroneous or suspect
                    continue
                try:
                    c = int(raw) / 10.0
                except ValueError:
                    continue
                n += 1
                mn = min(mn, c)
                mx = max(mx, c)
                for t in buckets:
                    if c < t:
                        buckets[t] += 1
                for t in hot:
                    if c > t:
                        hot[t] += 1
    except (OSError, EOFError):
        return None
    if not n:
        return None
    return {"obs": n, "minC": mn, "maxC": mx, "below": buckets, "above": hot}


def cmd_cities() -> None:
    rows = active(history())
    print(f"{len(rows)} stations reporting into 2025\n")
    for city, (lat, lon) in DEMO_CITIES.items():
        st, km = nearest(rows, lat, lon)
        sid = f'{st["USAF"]}-{st["WBAN"]}'
        path = fetch(sid)
        red = reduce_station(path) if path else None
        if not red or red["obs"] < 1000:
            print(f"{city:24s} {sid} {st['STATION NAME'][:28]:28s} {km:5.1f} km  (thin/no data)")
            continue
        n = red["obs"]
        print(
            f"{city:24s} {sid} {st['STATION NAME'][:28]:28s} {km:5.1f} km "
            f"obs={n:6d} min={red['minC']:6.1f} max={red['maxC']:5.1f} "
            f"<0C={100 * red['below'][0] / n:5.1f}% <-25C={100 * red['below'][-25] / n:5.2f}%"
        )


def cmd_sample(k: int) -> None:
    rows = active(history())
    random.seed(11)  # the seed behind the 22.6% in the pitch - keep it to reproduce
    picked = random.sample(rows, k)

    def work(r: dict):
        sid = f'{r["USAF"]}-{r["WBAN"]}'
        path = fetch(sid)
        if not path:
            return None
        red = reduce_station(path)
        if not red:
            return None
        return sid, r["CTRY"], red, os.path.getsize(path)

    with ThreadPoolExecutor(24) as pool:
        res = [x for x in pool.map(work, picked) if x]
    usable = [x for x in res if x[2]["obs"] >= 2000]
    breach = [x for x in usable if x[2]["minC"] < ANTIFREEZE_FLOOR_C]
    print(f"sampled {k}; {len(res)} had a {YEAR} file; {len(usable)} with >=2000 good observations")
    print(f"downloaded {sum(x[3] for x in res) / 1e6:.1f} MB, "
          f"parsed {sum(x[2]['obs'] for x in res):,} observations")
    print(f"minimum below {ANTIFREEZE_FLOOR_C} C: {len(breach)}/{len(usable)} = "
          f"{100 * len(breach) / len(usable):.1f}%")
    for t in (-20, -25, -30, -35):
        c = sum(1 for x in usable if x[2]["minC"] < t)
        print(f"  below {t} C: {c}/{len(usable)} = {100 * c / len(usable):.1f}%")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    args = sys.argv[1:] or ["cities"]
    if args[0] == "sample":
        cmd_sample(int(args[1]) if len(args) > 1 else 260)
    else:
        cmd_cities()
