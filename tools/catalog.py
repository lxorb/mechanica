"""Build the bundled search catalog.

    python tools/catalog.py [--input api/data/bikes.json] [--output src/data/catalog.json]

Reads the registry catalog (a Bike[] JSON array) and writes one compact row per make+model:

    [{"make": "KTM", "model": "390 Duke", "years": [2023, 2024], "manuals": {"2024": "ktm-390-duke-2024-om-en"}}]

Rerun it whenever api/data/bikes.json changes. src/data/index.ts expands the rows back into Bike[]
and lets the hand-made src/data/bikes.json rows (ids, manuals, vins, cues) win.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "api" / "data" / "bikes.json"
OUTPUT = ROOT / "src" / "data" / "catalog.json"
OVERRIDES = ROOT / "src" / "data" / "bikes.json"
SEED_CSV = ROOT / "api" / "data" / "seeds" / "all_bikez_curated.csv"
DEFAULT_MARKET = "WW"
MIN_YEAR = 1970
MAX_YEAR = 2030
VOWELS = set("aeiou")
SKIP_CATEGORIES = {"atv", "prototype / concept model", "unspecified category"}

MAKES = {
    "ktm": "KTM",
    "husqvarna": "Husqvarna",
    "gas gas": "GasGas",
    "bmw": "BMW",
    "yamaha": "Yamaha",
    "honda": "Honda",
    "kawasaki": "Kawasaki",
    "suzuki": "Suzuki",
    "triumph": "Triumph",
    "enfield": "Royal Enfield",
    "royal enfield": "Royal Enfield",
    "ducati": "Ducati",
    "aprilia": "Aprilia",
    "moto guzzi": "Moto Guzzi",
    "harley-davidson": "Harley-Davidson",
    "harley davidson": "Harley-Davidson",
    "mv agusta": "MV Agusta",
    "benelli": "Benelli",
    "cfmoto": "CFMoto",
    "cf moto": "CFMoto",
    "indian": "Indian",
    "zero": "Zero",
    "piaggio": "Piaggio",
    "vespa": "Vespa",
    "beta": "Beta",
    "sherco": "Sherco",
    "sym": "SYM",
    "kymco": "Kymco",
    "voge": "Voge",
    "qj motor": "QJ Motor",
    "keeway": "Keeway",
    "mash": "Mash",
    "fantic": "Fantic",
    "rieju": "Rieju",
    "brixton": "Brixton",
    "bullit": "Bullit",
    "niu": "NIU",
    "super soco": "Super Soco",
    "segway": "Segway",
    "can-am": "Can-Am",
    "can am": "Can-Am",
    "norton": "Norton",
    "bimota": "Bimota",
    "mondial": "Mondial",
    "swm": "SWM",
    "ural": "Ural",
    "jawa": "Jawa",
    "hero": "Hero",
    "bajaj": "Bajaj",
    "tvs": "TVS",
    "lambretta": "Lambretta",
    "italjet": "Italjet",
    "macbor": "Macbor",
    "orcal": "Orcal",
    "peugeot": "Peugeot",
    "aeon": "Aeon",
    "daelim": "Daelim",
    "hyosung": "Hyosung",
}


def slug(*parts: object) -> str:
    raw = "-".join(str(p) for p in parts if p not in (None, ""))
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", raw.lower())).strip("-")


def key(make: str, model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", f"{make}{model}".lower())


def pretty_make(raw: str) -> str:
    low = " ".join(raw.split()).lower()
    if low in MAKES:
        return MAKES[low]
    return " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in low.split())


def pretty_model(raw: str) -> str:
    out = []
    for token in " ".join(raw.split()).split():
        core = "".join(ch for ch in token if ch.isalpha())
        upper = any(ch.isdigit() for ch in token) or (core and not set(core.lower()) & VOWELS)
        out.append(token.upper() if upper else token[:1].upper() + token[1:])
    return " ".join(out)


def read_bikes(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("make") or not r.get("model"):
            continue
        try:
            year = int(r["year"])
        except (KeyError, TypeError, ValueError):
            continue
        if MIN_YEAR <= year <= MAX_YEAR:
            out.append(r)
    return out


def read_seed(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8", errors="ignore", newline="") as handle:
        for row in csv.DictReader(handle):
            brand = (row.get("Brand") or "").strip()
            model = (row.get("Model") or "").strip()
            year = (row.get("Year") or "").strip()
            if not brand or not model or not year.isdigit():
                continue
            if (row.get("Category") or "").strip().lower() in SKIP_CATEGORIES:
                continue
            n = int(year)
            if n < MIN_YEAR or n > MAX_YEAR:
                continue
            rows.append({"make": pretty_make(brand), "model": pretty_model(model), "year": n, "market": "EU"})
    return rows


def build(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for bike in rows:
        make = str(bike["make"]).strip()
        model = str(bike["model"]).strip()
        try:
            year = int(bike["year"])
        except (TypeError, ValueError):
            continue
        group = groups.setdefault(key(make, model), {"make": make, "model": model, "names": {}, "years": set(), "manuals": {}, "market": {}})
        group["names"][model] = group["names"].get(model, 0) + 1
        group["years"].add(year)
        manual = bike.get("manualId")
        if manual:
            group["manuals"][str(year)] = manual
        market = bike.get("market")
        if market and market != DEFAULT_MARKET:
            group["market"][str(year)] = market

    out: list[dict] = []
    for group in groups.values():
        name = max(group["names"].items(), key=lambda kv: (len(kv[0]), kv[1]))[0]
        row: dict = {"make": group["make"], "model": name, "years": sorted(group["years"])}
        if group["manuals"]:
            row["manuals"] = {y: group["manuals"][y] for y in sorted(group["manuals"])}
        markets = set(group["market"].values())
        if len(markets) == 1 and len(group["market"]) == len(row["years"]):
            row["market"] = markets.pop()
        elif group["market"]:
            row["markets"] = {y: group["market"][y] for y in sorted(group["market"])}
        out.append(row)
    out.sort(key=lambda r: (r["make"].lower(), r["model"].lower()))
    return out


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
    path.write_text(f"[\n{body}\n]\n" if rows else "[]\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--seed", type=Path, nargs="?", const=SEED_CSV, default=None)
    args = parser.parse_args()

    rows = read_bikes(args.input)
    seeded = 0
    if args.seed:
        seed = read_seed(args.seed)
        if seed:
            known = {(key(r["make"], r["model"]), int(r["year"])) for r in rows}
            extra = [r for r in seed if (key(r["make"], r["model"]), r["year"]) not in known]
            seeded = len(extra)
            rows += extra
    rows += read_bikes(OVERRIDES)

    catalog = build(rows)
    write(args.output, catalog)
    models = len(catalog)
    variants = sum(len(r["years"]) for r in catalog)
    makes = len({r["make"] for r in catalog})
    size = args.output.stat().st_size
    print(f"{args.input} -> {args.output}")
    print(f"{makes} makes, {models} models, {variants} model years, {seeded} from seed, {size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
