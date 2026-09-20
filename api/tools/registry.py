"""Registry CLI. Run from api/:

    python -m tools.registry crawl [--brand ktm --brand bmw]
    python -m tools.registry seed-catalog
    python -m tools.registry list-free --make ktm --limit 20
    python -m tools.registry ingest-free --make ktm --limit 3
    python -m tools.registry merge-fragments
    python -m tools.registry stats --sites --verify 2
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import random
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.models import Bike, IngestJob, RegistryEntry
from app.registry import ADAPTERS, _ingestable, bikes_from_registry, crawl, discover, free_owner_manuals, select, verify
from app.registry._http import client, request, slug
from app.store import get_store

BIKEZ = "https://raw.githubusercontent.com/AtharvBeDiff/AI-MECHANIC/main/all_bikez_curated.csv"
SEEDS = settings.data_dir / "seeds"
FRAGMENTS = settings.data_dir / "registry-fragments"
SEED_FILE = SEEDS / "all_bikez_curated.csv"
SEED_CAP = 15_000
MIN_YEAR = 2000
VOWELS = set("aeiou")

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
    "ducati": "Ducati",
    "aprilia": "Aprilia",
    "moto guzzi": "Moto Guzzi",
    "harley-davidson": "Harley-Davidson",
}


def pretty(model: str) -> str:
    """bikez ships lowercase names. Upper-case what reads as a code, capitalise what reads as a word."""

    def one(part: str) -> str:
        core = "".join(ch for ch in part if ch.isalpha())
        return part.upper() if any(ch.isdigit() for ch in part) or (core and not set(core) & VOWELS) else part.capitalize()

    return " ".join("-".join(one(p) for p in token.split("-")) for token in model.split())


def cmd_crawl(args: argparse.Namespace) -> int:
    names = select(args.brand)
    print(f"adapters: {', '.join(names)}")
    stored = crawl(args.brand)
    store = get_store()
    by_make: dict[str, int] = {}
    for e in store.registry():
        by_make[e.make] = by_make.get(e.make, 0) + 1
    bikes = bikes_from_registry()
    print(f"stored {stored} entries this run; registry now {sum(by_make.values())} rows")
    for make, n in sorted(by_make.items(), key=lambda kv: -kv[1]):
        print(f"  {make:<16} {n}")
    print(f"bikes from registry: {len(bikes)}")
    print(f"free english owner pdfs: {len(free_owner_manuals(limit=10**9))}")
    return 0


def cmd_seed_catalog(args: argparse.Namespace) -> int:
    SEEDS.mkdir(parents=True, exist_ok=True)
    gitignore = SEEDS / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.csv\n*.json\n!.gitignore\n", encoding="utf-8")
    if args.refresh or not SEED_FILE.exists():
        with client() as c:
            r = request(c, "GET", BIKEZ)
        if r is None:
            print("bikez dump unavailable", file=sys.stderr)
            return 1
        SEED_FILE.write_bytes(r.content)
    text = SEED_FILE.read_text(encoding="utf-8", errors="replace")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        brand = (row.get("Brand") or "").strip().lower()
        year = (row.get("Year") or "").strip()
        model = (row.get("Model") or "").strip()
        if brand not in MAKES or not model or not year.isdigit() or int(year) < MIN_YEAR:
            continue
        rows.append((MAKES[brand], pretty(model), int(year)))
    rows.sort(key=lambda r: (-r[2], r[0], r[1]))
    store = get_store()
    known = {b.id: b for b in store.bikes()}
    bikes: dict[str, Bike] = {}
    for make, model, year in rows:
        bid = slug(make, model, year)
        if bid in bikes or len(bikes) >= SEED_CAP:
            continue
        old = known.get(bid)
        bikes[bid] = old or Bike(id=bid, make=make, model=model, year=year, market="WW")
    store.put_bikes(list(bikes.values()))
    print(f"seed rows kept {len(rows)}, bikes merged {len(bikes)}, catalog now {len(store.bikes())}")
    print(f"seed file: {SEED_FILE} ({SEED_FILE.stat().st_size / 1e6:.1f} MB, gitignored)")
    return 0


def cmd_merge_fragments(args: argparse.Namespace) -> int:
    """Fold api/data/registry-fragments/*.json into the registry. Other agents own those files; this
    is the only writer of registry.json and bikes.json, so nothing races over the merge."""
    FRAGMENTS.mkdir(parents=True, exist_ok=True)
    store = get_store()
    before = {e.id for e in store.registry()}
    merged: list[tuple[str, int, int, int]] = []
    incoming: dict[str, RegistryEntry] = {}
    for path in sorted(FRAGMENTS.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  {path.name:<28} unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        items = raw.get("entries") if isinstance(raw, dict) else raw
        rows: dict[str, RegistryEntry] = {}
        bad = 0
        for item in items if isinstance(items, list) else []:
            try:
                entry = RegistryEntry.model_validate(item)
            except ValidationError:
                bad += 1
                continue
            if entry.url:
                rows[entry.id] = entry
        fresh = sum(1 for eid in rows if eid not in before and eid not in incoming)
        incoming.update(rows)
        merged.append((path.name, len(rows), fresh, bad))
    if incoming:
        store.put_registry(list(incoming.values()))  # one write for every fragment, not one each
    for name, kept, fresh, bad in merged:
        print(f"  {name:<28} {kept:>6} rows, {fresh:>6} new" + (f", {bad} invalid" if bad else ""))
    if not merged:
        print("  no fragments yet")
    found = discover()
    if found:
        print(f"  adapters discovered: {', '.join(found)}")
    bikes = bikes_from_registry()
    entries = store.registry()
    free = [e for e in entries if _ingestable(e)]
    with_url = sum(1 for b in bikes if b.manualUrl)
    files = len({e.url for e in free})
    print(f"registry {len(entries)} rows, {len(free)} free english owner pdfs ({files} distinct files); bikes {len(bikes)}, {with_url} with a free PDF")
    by_make: dict[str, int] = {}
    for e in free:
        by_make[e.make] = by_make.get(e.make, 0) + 1
    print("  " + "  ".join(f"{make} {n}" for make, n in sorted(by_make.items(), key=lambda kv: -kv[1])))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Per-brand coverage: rows indexed, free English owner's-manual PDFs, bikes those PDFs cover."""
    store = get_store()
    entries = store.registry()
    rows: dict[str, list[int]] = {}
    sites: dict[str, list[int]] = {}
    for e in entries:
        ok = _ingestable(e)
        rows.setdefault(e.make, [0, 0])[0] += 1
        rows[e.make][1] += ok
        sites.setdefault(e.site, [0, 0])[0] += 1
        sites[e.site][1] += ok
    bikes = store.bikes()
    linked = sum(1 for b in bikes if b.manualId)
    offered = sum(1 for b in bikes if b.manualUrl)
    print(f"{'make':<16}{'rows':>8}{'free en pdf':>13}")
    for make, (n, free) in sorted(rows.items(), key=lambda kv: -kv[1][1]):
        print(f"{make:<16}{n:>8}{free:>13}")
    print(f"{'TOTAL':<16}{len(entries):>8}{sum(v[1] for v in rows.values()):>13}")
    print(f"{'distinct files':<16}{'':>8}{len({e.url for e in entries if _ingestable(e)}):>13}  (one PDF often covers several model years)")
    if args.sites:
        print()
        for site, (n, free) in sorted(sites.items(), key=lambda kv: -kv[1][1]):
            print(f"  {site:<34}{n:>8}{free:>13}")
    print(f"\ncatalog: {len(bikes)} bikes, {offered} with a free PDF, {linked} already ingested")
    if args.verify:
        print(f"\nverifying {args.verify} per site ...")
        by_site: dict[str, list] = {}
        for e in entries:
            if _ingestable(e):
                by_site.setdefault(e.site, []).append(e)
        bad = 0
        for site, group in sorted(by_site.items()):
            sample = random.sample(group, min(args.verify, len(group)))
            for e, ok, note in verify(sample):
                bad += not ok
                print(f"  {'ok ' if ok else 'BAD'} {site:<34}{note:<34}{e.url[:70]}")
        print(f"{'all sampled urls are PDFs' if not bad else str(bad) + ' urls are not PDFs'}")
    return 0


def cmd_list_free(args: argparse.Namespace) -> int:
    for e in free_owner_manuals(args.make, args.limit):
        years = "/".join(str(y) for y in e.years) or "-"
        print(f"{e.make:<14} {e.model[:28]:<28} {years:<9} {e.market:<3} {e.site:<32} {e.url}")
    return 0


def cmd_ingest_free(args: argparse.Namespace) -> int:
    from app import ingest as ingest_mod

    store = get_store()
    done: set[str] = set()
    for e in free_owner_manuals(args.make, args.limit):
        year = max(e.years) if e.years else 0
        manual_id = slug(e.make, e.model, year or "", e.market, e.lang, "om")
        bike_id = slug(e.make, e.model, year or "")
        if manual_id in done:
            continue
        done.add(manual_id)
        job = IngestJob(id=uuid.uuid4().hex[:12], manualId=manual_id, status="queued")
        store.put_job(job)
        print(f"-> {manual_id}  {e.url}")
        try:
            ingest_mod.run(job.id, e.url, manual_id, [bike_id], e.make, e.model, year)
        except NotImplementedError:
            print("   app.ingest.run is not implemented yet (ingest agent owns it)")
            return 0
        except Exception as exc:
            print(f"   failed: {type(exc).__name__}: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="tools.registry")
    sub = p.add_subparsers(dest="cmd", required=True)

    c1 = sub.add_parser("crawl", help=f"adapters: {', '.join(ADAPTERS)}")
    c1.add_argument("--brand", action="append")
    c1.set_defaults(fn=cmd_crawl)

    c2 = sub.add_parser("seed-catalog")
    c2.add_argument("--refresh", action="store_true")
    c2.set_defaults(fn=cmd_seed_catalog)

    c6 = sub.add_parser("merge-fragments", help="fold data/registry-fragments/*.json into the registry")
    c6.set_defaults(fn=cmd_merge_fragments)

    c5 = sub.add_parser("stats", help="per-brand rows and free-PDF totals")
    c5.add_argument("--sites", action="store_true", help="also break the totals down per site")
    c5.add_argument("--verify", type=int, default=0, help="fetch N urls per site and check they are really PDFs")
    c5.set_defaults(fn=cmd_stats)

    c3 = sub.add_parser("list-free")
    c3.add_argument("--make")
    c3.add_argument("--limit", type=int, default=20)
    c3.set_defaults(fn=cmd_list_free)

    c4 = sub.add_parser("ingest-free")
    c4.add_argument("--make")
    c4.add_argument("--limit", type=int, default=3)
    c4.set_defaults(fn=cmd_ingest_free)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
