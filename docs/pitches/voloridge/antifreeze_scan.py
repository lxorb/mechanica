#!/usr/bin/env python3
"""Reproduce Finding 1: every manual in the corpus that prints an antifreeze floor prints -25 C.

    api/.venv/Scripts/python docs/pitches/voloridge/antifreeze_scan.py

Measured 2026-09-20 over api/data/specs/*.json (508 files, 107,452 spec rows):

    distinct antifreeze floors: [('-25', 206)]
    by market: eu 100, us 69, ww 26, rw 4, ar 3, jp 1, ph 1, cn 1, br 1

206 manuals. 9 markets. 4 makes. 3 model years. Zero variance. That single number is what the
Climate Fit feature checks against the NOAA ISD climatology for wherever the vehicle actually is;
see docs/pitches/voloridge/spec.md section 7 and isd_probe.py for the other half.

Note the minus sign: the PDFs print U+2212 MINUS SIGN and U+2013 EN DASH, not ASCII hyphen. A scan
that only looks for "-25" finds a fraction of them - one of several places in this corpus where the
text layer is not the character you would type.
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

SPECS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "api", "data", "specs")

# "Antifreeze protection to at least -25 °C (-13.0 °F)" - hyphen, minus sign or en dash.
FLOOR = re.compile(r"[Aa]ntifreeze protection[^\n]{0,60}?[-−–]\s?(\d{2})\s?°C")
MARKET = re.compile(r"-(\w{2})-om$")


def main() -> int:
    if not os.path.isdir(SPECS):
        print(f"no spec corpus at {SPECS}", file=sys.stderr)
        return 1
    os.chdir(SPECS)
    values: collections.Counter = collections.Counter()
    by_market: collections.Counter = collections.Counter()
    broken = 0
    for path in glob.glob("*.json"):
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except Exception:
            broken += 1   # yamaha-tracer-9-gt-2025-eu-om-90739a.json has trailing bytes; known
            continue
        market = MARKET.search(path[:-5])
        found = set()
        for row in rows:
            hit = FLOOR.search(row.get("quote") or "")
            if hit:
                found.add("-" + hit.group(1))
        for value in found:
            values[value] += 1
            if market:
                by_market[(market.group(1), value)] += 1
    print("distinct antifreeze floors:", values.most_common())
    print("by market:", by_market.most_common())
    if broken:
        print(f"({broken} spec file(s) unreadable and skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
