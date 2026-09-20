#!/usr/bin/env python3
"""Regenerate the two Climate Fit findings from the BUILT artefacts, as markdown tables.

    api/.venv/Scripts/python docs/pitches/voloridge/findings.py

Writes docs/pitches/voloridge/findings.md. Nothing here is typed by hand: every number comes out of
api/data/climate/rules/*.json (the extracted rulebook) and api/data/climate/isd-2024.jsonl (the
reduced NOAA station-years), both of which are committed.

  Finding 1  every manual in the corpus that prints an antifreeze floor prints the same number.
             This is the page-text version of docs/pitches/voloridge/antifreeze_scan.py, which
             scans the 508 spec files instead of the 529 page files and therefore counts fewer
             manuals. Both are in the repo; they disagree only about the denominator.
  Finding 2  how often that number is wrong, from the reduced station-years. Two numbers: the
             seeded 260-station sample the pitch quotes (seed 11, the same draw isd_probe.py makes)
             and the whole population, which this build now has and the probe did not.
"""

from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIMATE = ROOT / "api" / "data" / "climate"
RULES = CLIMATE / "rules"
OUT = Path(__file__).resolve().parent / "findings.md"

SEED = 11  # the seed behind the 22.9% in the pitch - keep it to reproduce
SAMPLE = 260
MIN_OBS = 2000
FLOOR_C = -25.0
MARKET_SUFFIX = 2


def market_of(manual_id: str) -> str:
    parts = manual_id.split("-")
    for i, token in enumerate(parts):
        if token in ("om", "rm", "sm") and i and len(parts[i - 1]) == MARKET_SUFFIX:
            return parts[i - 1]
    return "??"


def make_of(manual_id: str) -> str:
    return manual_id.split("-", 1)[0]


def finding_one() -> list[str]:
    by_value: collections.Counter = collections.Counter()
    by_market: collections.Counter = collections.Counter()
    by_make: collections.Counter = collections.Counter()
    by_year: collections.Counter = collections.Counter()
    pages = 0
    for path in sorted(RULES.glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        floors = {r["thresholdC"] for r in rows if r["ruleType"] == "antifreeze_floor"}
        if not floors:
            continue
        pages += len({r["page"] for r in rows if r["ruleType"] == "antifreeze_floor"})
        manual_id = path.stem
        for value in floors:
            by_value[value] += 1
        by_market[market_of(manual_id)] += 1
        by_make[make_of(manual_id)] += 1
        years = [t for t in manual_id.split("-") if t.isdigit() and len(t) == 4 and 1990 <= int(t) <= 2100]
        if years:  # "ktm-1390-super-adventure-r-2026-us-om": the LAST one is the model year
            by_year[years[-1]] += 1
    total = sum(by_value.values())
    lines = [
        "## Finding 1 — one number, every market",
        "",
        f"**{total} manuals in the corpus print an antifreeze floor. "
        f"{'They all print the same number.' if len(by_value) == 1 else 'They do not agree.'}**",
        "",
        "| printed floor | manuals |",
        "|---|---:|",
    ]
    for value, count in by_value.most_common():
        lines.append(f"| {value:g} °C | {count} |")
    lines += ["", f"Printed on {pages} distinct pages across those manuals.", "",
              "| market | manuals |", "|---|---:|"]
    for market, count in by_market.most_common():
        lines.append(f"| {market} | {count} |")
    lines += ["", "| make | manuals |", "|---|---:|"]
    for make, count in by_make.most_common():
        lines.append(f"| {make} | {count} |")
    lines += ["", "| model year | manuals |", "|---|---:|"]
    for year, count in sorted(by_year.items()):
        lines.append(f"| {year} | {count} |")
    return lines


def load_years() -> dict[str, dict]:
    out = {}
    for path in sorted(CLIMATE.glob("isd-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["id"]] = row
    return out


def breach_table(rows: list[dict]) -> list[str]:
    usable = [r for r in rows if r["obs"] >= MIN_OBS]
    lines = ["| threshold | station-years below it | share |", "|---|---:|---:|"]
    for t in (-20, -25, -30, -35, -40):
        hit = sum(1 for r in usable if r["minC"] < t)
        lines.append(f"| {t} °C | {hit} / {len(usable)} | **{100 * hit / len(usable):.1f}%** |")
    return lines


def finding_two() -> list[str]:
    reduced = load_years()
    stations = json.loads((CLIMATE / "stations.json").read_text(encoding="utf-8"))
    everything = [r for r in reduced.values() if r["obs"] >= MIN_OBS]
    picked_ids = {s["id"] for s in random.Random(SEED).sample(stations, SAMPLE)}
    sampled = [r for sid, r in reduced.items() if sid in picked_ids]

    by_country = collections.Counter()
    ids_to_ctry = {s["id"]: s["ctry"] for s in stations}
    elev = {s["id"]: s.get("elevM") for s in stations}
    high = []
    for r in everything:
        if r["minC"] < FLOOR_C:
            by_country[ids_to_ctry.get(r["id"], "??")] += 1
            metres = elev.get(r["id"])
            if metres and metres > 1500:
                high.append((r["id"], ids_to_ctry.get(r["id"], "??"), metres, r["minC"]))

    usable_all = len(everything)
    breached_all = sum(1 for r in everything if r["minC"] < FLOOR_C)
    usable_sample = [r for r in sampled if r["obs"] >= MIN_OBS]
    breached_sample = sum(1 for r in usable_sample if r["minC"] < FLOOR_C)

    lines = [
        "## Finding 2 — how often that number is wrong",
        "",
        f"Every currently-reporting NOAA ISD station, 2024, reduced in the stream: "
        f"**{len(reduced):,} station-years**, {usable_all:,} with at least {MIN_OBS:,} "
        f"quality-passed readings.",
        "",
        f"**{breached_all:,} of {usable_all:,} ({100 * breached_all / usable_all:.1f}%) recorded a "
        f"temperature below {FLOOR_C:g} °C in 2024** — the floor all "
        "of those manuals print.",
        "",
        "### Whole population",
        "",
        *breach_table(everything),
        "",
        f"### Seeded sample (seed {SEED}, {SAMPLE} stations — the draw `isd_probe.py sample "
        f"{SAMPLE}` makes)",
        "",
        f"{len(usable_sample)} of the {SAMPLE} drawn stations reduced to a usable 2024 file; "
        f"**{breached_sample} of them ({100 * breached_sample / len(usable_sample):.1f}%) went "
        f"below {FLOOR_C:g} °C.**",
        "",
        *breach_table(usable_sample),
        "",
        "### Who breaches it",
        "",
        "Raw `CTRY` codes from `isd-history.csv`, not country names: NOAA's own column collides - "
        "`CH` covers both ZUERICH-FLUNTERN and WUDAOLIANG (4,613 m, Tibetan plateau). We print the "
        "code the archive prints rather than guess at the country.",
        "",
        "| isd-history CTRY | station-years below " + f"{FLOOR_C:g} °C |",
        "|---|---:|",
    ]
    for country, count in by_country.most_common(12):
        lines.append(f"| {country} | {count} |")
    lines += [
        "",
        f"And it is not only latitude: **{len(high)} of the breaching stations sit above 1,500 m**. "
        "The single printed number fails on altitude as well, which is why `altitude` is its own "
        "rule type in the extractor.",
        "",
        "| station | CTRY | elevation | 2024 minimum |",
        "|---|---|---:|---:|",
    ]
    for sid, ctry, metres, low in sorted(high, key=lambda x: -x[2])[:8]:
        lines.append(f"| `{sid}` | {ctry} | {metres:g} m | {low:g} °C |")
    return lines


def main() -> int:
    if not RULES.exists() or not any(CLIMATE.glob("isd-*.jsonl")):
        print("build the artefacts first: python -m tools.climate_build --stations --isd --rules",
              file=sys.stderr)
        return 1
    lines = [
        "# Climate Fit — the two findings, regenerated",
        "",
        "Generated by `docs/pitches/voloridge/findings.py` from the committed artefacts. Do not "
        "edit by hand; rerun the script.",
        "",
        *finding_one(),
        "",
        *finding_two(),
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
