"""Climate Fit builder. Everything expensive happens here, offline; the API only reads what this wrote.

    api/.venv/Scripts/python -m tools.climate_build --stations
    api/.venv/Scripts/python -m tools.climate_build --isd --years 2024 --limit 1500 --threads 32
    api/.venv/Scripts/python -m tools.climate_build --climatology
    api/.venv/Scripts/python -m tools.climate_build --rules            # pass A + C, no model
    api/.venv/Scripts/python -m tools.climate_build --rules --model    # + pass B, capped at $15
    api/.venv/Scripts/python -m tools.climate_build --anomalies
    api/.venv/Scripts/python -m tools.climate_build --ablation --limit 300
    api/.venv/Scripts/python -m tools.climate_build --openaq --years 2024

Flag names mirror Voloridge's own s3://voloridge-hack-mit-2026/src/noaa-isd/fetch.py (--list,
--country, --max-size-gb) so a judge can swap one fetcher for the other.

Nothing raw is ever stored: a station-year is streamed, reduced in the stream and thrown away. The
committed artefacts are the reduced rows.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.climate import isd  # noqa: E402
from app.climate.paths import climate_dir  # noqa: E402

# The demo and the negative controls. These station-years are fetched first so the demo is green
# even when the sweep is stopped early, and the four negative controls are always present.
DEMO_CITIES: dict[str, tuple[float, float]] = {
    "Minneapolis": (44.98, -93.26),
    "International Falls MN": (48.60, -93.40),
    "Zurich": (47.38, 8.54),
    "Phoenix": (33.45, -112.07),
    "Munich": (48.14, 11.58),
    "Boston": (42.36, -71.06),
    "Denver": (39.74, -104.98),
    "Fargo ND": (46.88, -96.79),
    "Oslo": (59.91, 10.75),
    "Anchorage": (61.22, -149.90),
    "Winnipeg": (49.90, -97.14),
    # negative controls - a cold rule that fires in any of these means the join or the comparator
    # is broken, and these four run in the test suite.
    "Bangkok": (13.75, 100.50),
    "Dubai": (25.20, 55.27),
    "Miami": (25.76, -80.19),
    "Delhi": (28.61, 77.21),
}

SWEEP_SEED = 11  # the seed behind the sampled breach share; keep it to reproduce
MIN_OBS = 2000  # a station-year with fewer quality-passed readings is too thin to judge


def _log(*parts) -> None:
    print(*parts, flush=True)


def stations_path() -> Path:
    return climate_dir() / "stations.json"


def year_path(year: int) -> Path:
    return climate_dir() / f"isd-{year}.jsonl"


def build_stations() -> list[dict]:
    """isd-history.csv -> the 12,776 stations that still report. 2.9 MB in, ~1.2 MB out."""
    rows = isd.fetch_history()
    live = isd.active(rows)
    out = [isd.station_row(r) for r in live]
    path = stations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _log(f"stations: {len(rows)} in isd-history.csv, {len(out)} still reporting -> {path} "
         f"({path.stat().st_size / 1e6:.2f} MB)")
    return out


def load_stations() -> list[dict]:
    path = stations_path()
    if not path.exists():
        return build_stations()
    return json.loads(path.read_text(encoding="utf-8"))


def nearest_station(rows: list[dict], lat: float, lon: float) -> tuple[dict, float]:
    best, best_d = rows[0], 1e18
    for r in rows:
        dy = r["lat"] - lat
        dx = (r["lon"] - lon) * 0.9  # crude cos() stand-in; refined by haversine below
        d = dy * dy + dx * dx
        if d < best_d:
            best_d, best = d, r
    return best, isd.haversine(lat, lon, best["lat"], best["lon"])


def sweep_order(rows: list[dict], country: str | None) -> list[dict]:
    """Demo and control stations first, then a seeded shuffle of the rest.

    The shuffle matters: a sweep that is stopped early must still be an unbiased sample of the
    station list, or every number derived from partial coverage is alphabetical nonsense.
    """
    pool = [r for r in rows if not country or r["ctry"] == country.upper()]
    by_id = {r["id"]: r for r in pool}
    first: list[dict] = []
    seen: set[str] = set()
    for _city, (lat, lon) in DEMO_CITIES.items():
        st, _km = nearest_station(pool or rows, lat, lon)
        if st["id"] not in seen:
            seen.add(st["id"])
            first.append(st)
    rest = [r for rid, r in by_id.items() if rid not in seen]
    random.Random(SWEEP_SEED).shuffle(rest)
    return first + rest


def done_ids(year: int) -> set[str]:
    path = year_path(year)
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.add(json.loads(line)["id"])
        except Exception:
            continue
    return out


def sweep(years: list[int], limit: int, threads: int, country: str | None, max_gb: float) -> None:
    rows = load_stations()
    order = sweep_order(rows, country)
    for year in years:
        have = done_ids(year)
        todo = [r for r in order if r["id"] not in have][:limit]
        _log(f"isd {year}: {len(have)} already reduced, {len(todo)} to stream, {threads} threads")
        path = year_path(year)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        started = time.time()
        stats = {"ok": 0, "miss": 0, "bytes": 0, "obs": 0}
        stop = threading.Event()
        handle = path.open("a", encoding="utf-8")

        def work(station: dict) -> None:
            if stop.is_set():
                return
            row = isd.reduce_station_year(station["id"], year)
            with lock:
                if row is None:
                    stats["miss"] += 1
                else:
                    stats["ok"] += 1
                    stats["bytes"] += row["bytes"]
                    stats["obs"] += row["obs"]
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                n = stats["ok"] + stats["miss"]
                if n % 100 == 0:
                    rate = stats["bytes"] / max(1e-6, time.time() - started) / 1e6
                    _log(f"  {n}/{len(todo)}  ok={stats['ok']} miss={stats['miss']} "
                         f"{stats['bytes'] / 1e6:.0f} MB streamed  {rate:.2f} MB/s")
                    handle.flush()
                if max_gb and stats["bytes"] / 1e9 >= max_gb:
                    stop.set()

        try:
            with ThreadPoolExecutor(max_workers=threads) as pool:
                list(pool.map(work, todo))
        finally:
            handle.close()
        secs = time.time() - started
        _log(f"isd {year}: {stats['ok']} station-years, {stats['miss']} with no file, "
             f"{stats['bytes'] / 1e6:.1f} MB streamed, {stats['obs']:,} observations, {secs:.0f}s")


def build_climatology() -> None:
    """Merge every reduced station-year into the one file the runtime reads."""
    rows = load_stations()
    by_id = {r["id"]: r for r in rows}
    per_station: dict[str, list[dict]] = {}
    years: set[int] = set()
    for path in sorted(climate_dir().glob("isd-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            per_station.setdefault(row["id"], []).append(row)
            years.add(row["year"])
    out = []
    thin = 0
    for sid, group in per_station.items():
        meta = by_id.get(sid)
        if not meta:
            continue
        merged = isd.merge_years(group)
        if merged["obs"] < MIN_OBS:
            thin += 1
            continue
        out.append({**meta, **merged})
    out.sort(key=lambda r: r["id"])
    path = climate_dir() / "climatology.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _log(f"climatology: {len(out)} stations over years {sorted(years)} "
         f"({thin} dropped for < {MIN_OBS} readings) -> {path} ({path.stat().st_size / 1e6:.2f} MB)")


def ablation(limit: int, threads: int) -> None:
    """Re-reduce station-years with the quality filter disabled and publish the diff.

    The honest version is more convincing than an exaggerated one, so this ships as a report.
    """
    rows = []
    for path in sorted(climate_dir().glob("isd-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    random.Random(SWEEP_SEED).shuffle(rows)
    rows = rows[:limit]
    moved, flipped, readings, flagged = 0, [], 0, 0

    def work(row: dict):
        raw = isd.fetch_year(row["id"], row["year"])
        if raw is None:
            return None
        loose = isd.reduce_stream(raw, drop_bad_quality=False)
        return row, loose

    with ThreadPoolExecutor(max_workers=threads) as pool:
        pairs = [x for x in pool.map(work, rows) if x and x[1]]
    for strict, loose in pairs:
        readings += loose["obs"]
        flagged += loose["obs"] - strict["obs"]
        if abs(loose["minC"] - strict["minC"]) > 0.05:
            moved += 1
            if (loose["minC"] < -25.0) != (strict["minC"] < -25.0):
                flipped.append({"id": strict["id"], "year": strict["year"],
                                "strictMinC": strict["minC"], "looseMinC": loose["minC"]})
    report = {
        "stationYears": len(pairs),
        "readings": readings,
        "flaggedReadings": flagged,
        "flaggedShare": round(flagged / readings, 6) if readings else 0.0,
        "minimumMoved": moved,
        "minimumMovedShare": round(moved / len(pairs), 4) if pairs else 0.0,
        "verdictFlipped": flipped,
    }
    path = climate_dir() / "quality_ablation.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    _log(f"ablation: {len(pairs)} station-years, {report['flaggedShare'] * 100:.2f}% of readings "
         f"flagged, {moved} minima moved, {len(flipped)} verdicts flipped -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stations", action="store_true", help="isd-history.csv -> stations.json")
    ap.add_argument("--isd", action="store_true", help="stream and reduce station-years")
    ap.add_argument("--climatology", action="store_true", help="merge reduced years -> climatology.json")
    ap.add_argument("--rules", action="store_true", help="extract the rulebook from the manual corpus")
    ap.add_argument("--model", action="store_true", help="with --rules: also run pass B (costs money)")
    ap.add_argument("--anomalies", action="store_true", help="group the rulebook -> anomalies.json")
    ap.add_argument("--openaq", action="store_true", help="OpenAQ discovery + reduce -> air.json")
    ap.add_argument("--ablation", action="store_true", help="quality-code ablation report")
    ap.add_argument("--list", action="store_true", help="print the sweep order and exit")
    ap.add_argument("--years", default="2024", help="2024 or 2019:2024")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--threads", type=int, default=32)
    ap.add_argument("--country", default=None, help="ISO country code from isd-history.csv")
    ap.add_argument("--max-size-gb", type=float, default=0.0, help="stop the sweep after this much")
    ap.add_argument("--manual", default=None, help="with --rules: one manual id only")
    ap.add_argument("--budget", type=float, default=15.0, help="with --model: hard USD cap")
    args = ap.parse_args()

    if ":" in args.years:
        lo, hi = args.years.split(":")
        years = list(range(int(lo), int(hi) + 1))
    else:
        years = [int(y) for y in args.years.split(",")]

    did = False
    if args.stations:
        build_stations()
        did = True
    if args.list:
        for r in sweep_order(load_stations(), args.country)[: args.limit]:
            print(f'{r["id"]}\t{r["ctry"]}\t{r["lat"]:.3f}\t{r["lon"]:.3f}\t{r["name"]}')
        return 0
    if args.isd:
        sweep(years, args.limit, args.threads, args.country, args.max_size_gb)
        did = True
    if args.climatology:
        build_climatology()
        did = True
    if args.ablation:
        ablation(args.limit if args.limit < 100000 else 300, args.threads)
        did = True
    if args.rules:
        from app.climate import rules as rules_mod

        rules_mod.build(use_model=args.model, only=args.manual, budget=args.budget, log=_log)
        did = True
    if args.anomalies:
        from app.climate import anomalies as anomalies_mod

        anomalies_mod.build(log=_log)
        did = True
    if args.openaq:
        from app.climate import openaq as openaq_mod

        openaq_mod.build(years=years, threads=args.threads, limit=args.limit, log=_log)
        did = True
    if not did:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
