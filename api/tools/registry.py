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
from app.registry import (
    ADAPTERS,
    _ingestable,
    _pick,
    bikes_from_registry,
    crawl,
    discover,
    doc_kind,
    free_owner_manuals,
    kind_of,
    merge_ua,
    pdf_index,
    select,
    verify,
)
from app.registry._http import MODEL_YEARS, client, request, slug
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


def by_kind(entries: list[RegistryEntry], bikes: list[Bike]) -> None:
    """Motorcycles and cars share one registry; every headline number is reported per kind."""
    print(f"  {'kind':<12}{'rows':>8}{'free en pdf':>13}{'distinct':>10}{'vehicles':>10}{'with pdf':>10}")
    for kind in ("motorcycle", "car"):
        rows = [e for e in entries if kind_of(e) == kind]
        free = [e for e in rows if _ingestable(e)]
        mine = [b for b in bikes if kind_of(b) == kind]
        print(
            f"  {kind:<12}{len(rows):>8}{len(free):>13}{len({e.url for e in free}):>10}"
            f"{len(mine):>10}{sum(1 for b in mine if b.manualUrl):>10}"
        )


def _bad_years(entry: RegistryEntry) -> list[object]:
    """The year values on this row that cannot be a model year: anything outside MODEL_YEARS
    (1885 .. this year + 2), which is also what catches a truncated one - Yamaha EU has shipped
    "201" next to 2011-2016, and Honda's Motopub answers "5019" for a 19YM file. Both portals print
    these; a year that survives here is one a vehicle id can be built from.

    The floor is 1885 and not 1950 on purpose: Harley's archive publishes handbooks back to 1903,
    and those seven rows are the oldest genuine manuals in the registry."""
    return [y for y in entry.years if not isinstance(y, int) or y not in MODEL_YEARS]


def _read_fragment(path: Path) -> tuple[dict[str, RegistryEntry], int, list[tuple[str, str, list[object], bool]]]:
    """Validated rows of one fragment, keyed by id, the count that failed validation, and the rows
    refused for carrying an impossible model year.

    A refused row is never folded in and never silently discarded: it is returned so the merge can
    name it, because an out-of-range year mints a catalog vehicle nothing will ever match (a
    "Yamaha XJ6F 201") and the fix belongs in the adapter that parsed it, not here."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  {path.name:<28} unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}, 0, []
    items = raw.get("entries") if isinstance(raw, dict) else raw
    rows: dict[str, RegistryEntry] = {}
    bad = 0
    refused: list[tuple[str, str, list[object], bool]] = []
    for item in items if isinstance(items, list) else []:
        try:
            entry = RegistryEntry.model_validate(item)
        except ValidationError:
            bad += 1
            continue
        if not entry.url:
            continue
        off = _bad_years(entry)
        if off:
            # Reject the value, not the row: three of the four Yamaha rows that carried a truncated
            # "201" also carried six good years, and dropping them whole cost real coverage.
            refused.append((entry.site, entry.id, off, len(entry.years) > len(off)))
            entry.years = [y for y in entry.years if y not in off]
            if not entry.years:
                continue  # nothing left to file it under; the adapter has to be fixed
        rows[entry.id] = entry
    return rows, bad, refused


def _rewrite(store, entries: list[RegistryEntry] | None = None, bikes: list[Bike] | None = None) -> None:
    """Delete by rewriting the whole file: put_registry/put_bikes only ever merge. FileStore only -
    a hosted backend has no wholesale-replace call, and guessing one would be worse than refusing."""
    root = getattr(store, "root", None)
    if root is None:
        raise SystemExit(f"retraction needs the file store; {type(store).__name__} is active")
    for name, rows in (("registry.json", entries), ("bikes.json", bikes)):
        if rows is None:
            continue
        path = root / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps([r.model_dump(exclude_none=True) for r in rows], ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _retract(store, drop: set[str], print_line: bool = True) -> list[RegistryEntry]:
    """Remove rows by id and tidy the vehicles they produced. Returns the rows that were removed."""
    rows = store.registry()
    gone = [e for e in rows if e.id in drop]
    if not gone:
        return []
    _rewrite(store, entries=[e for e in rows if e.id not in drop])
    left = {e.id for e in store.registry()}
    touched = {slug(e.make, e.model, year) for e in gone for year in e.years}
    dead_urls = {e.url for e in gone} - {e.url for e in store.registry()}
    alive = {slug(e.make, e.model, y) for e in store.registry() if e.type == "owner" for y in e.years}
    bikes = store.bikes()
    keep: list[Bike] = []
    removed = 0
    for b in bikes:
        if b.id in touched and b.id not in alive and not b.manualId:
            removed += 1  # a vehicle only the retracted rows ever produced, never ingested
            continue
        if b.manualUrl in dead_urls:
            b.manualUrl = None  # bikes_from_registry re-points it if another row still covers the bike
        keep.append(b)
    if removed or len(keep) != len(bikes):
        _rewrite(store, bikes=keep)
    if print_line:
        print(f"  retracted {len(gone)} row(s), removed {removed} vehicle(s), {len(left)} rows left")
    return gone


def cmd_merge_fragments(args: argparse.Namespace) -> int:
    """Fold api/data/registry-fragments/*.json into the registry. Other agents own those files; this
    is the only writer of registry.json and bikes.json, so nothing races over the merge.

    Retraction, because a rewritten fragment cannot un-say a row on its own:
      <name>.drop.json   a JSON list of registry ids to delete
      --replace <name>   the fragment is the whole truth for the (site, kind) pairs it covers, so
                         every row in that scope whose id it no longer lists is deleted. An id that
                         changed because the URL did (http/https) is therefore dropped and re-added
                         under the new id, which is what "prefer the new URL" means."""
    FRAGMENTS.mkdir(parents=True, exist_ok=True)
    store = get_store()
    before = {e.id for e in store.registry()}
    merged: list[tuple[str, int, int, int]] = []
    incoming: dict[str, RegistryEntry] = {}
    fragments: dict[str, dict[str, RegistryEntry]] = {}
    rejected: list[tuple[str, str, str, list[object], bool]] = []
    absent: dict[str, set[tuple[str, str]]] = {}  # skipped fragment -> the scopes it would have covered
    skip = {s.strip().lower().removesuffix(".json") for s in (args.skip or [])}
    replace = {s.strip().lower().removesuffix(".json") for s in (args.replace or [])}
    for path in sorted(FRAGMENTS.glob("*.json")):
        if path.name.startswith(".") or path.name.endswith(".drop.json"):
            continue
        if path.stem.lower() in skip:
            # Read it anyway, and merge nothing: what it covers decides whether another fragment is
            # allowed to replace a scope they share. A skipped co-owner makes that scope unsafe.
            absent_rows, _bad, _off = _read_fragment(path)
            absent[path.stem.lower()] = {(e.site, kind_of(e)) for e in absent_rows.values()}
            print(f"  {path.name:<28} skipped ({len(absent_rows)} rows, {len(absent[path.stem.lower()])} scope(s) held back)")
            continue
        rows, bad, refused = _read_fragment(path)
        fresh = sum(1 for eid in rows if eid not in before and eid not in incoming)
        fragments[path.stem.lower()] = rows
        incoming.update(rows)
        merged.append((path.name, len(rows), fresh, bad))
        rejected += [(path.name, *r) for r in refused]

    known_rows = store.registry()
    # Which fragments write into each (site, kind) scope. Two adapters can share one site - triumph.py
    # and triumph_pdf.py both write triumphtechnicalinformation.com - and then one fragment does NOT
    # own the scope: replacing it would delete the other's rows. Merged together nothing is lost,
    # merged apart everything the absent one holds is. So a shared scope is only ever replaced with
    # every co-owner present, and what it keeps is the union of all of them.
    scopes_of = {name: {(e.site, kind_of(e)) for e in rows.values()} for name, rows in fragments.items()}
    owners: dict[tuple[str, str], set[str]] = {}
    for name, scopes in scopes_of.items():
        for one in scopes:
            owners.setdefault(one, set()).add(name)
    held: dict[tuple[str, str], set[str]] = {}
    for name, scopes in absent.items():
        for one in scopes:
            held.setdefault(one, set()).add(name)

    for name, rows in sorted(fragments.items()):  # a wholesale re-key reads as an addition otherwise
        if name in replace or not rows:
            continue
        fresh_ids = sum(1 for eid in rows if eid not in before)
        if fresh_ids <= len(rows) // 10:
            continue
        scope = scopes_of[name]
        shared = {s: owners[s] | held.get(s, set()) for s in scope if len(owners[s] | held.get(s, set())) > 1}
        if shared:
            where = "; ".join(f"{s[0]} with {', '.join(sorted(o - {name}))}" for s, o in sorted(shared.items()))
            print(f"  {name}: {fresh_ids}/{len(rows)} ids new but no new files - NOT replacing, it shares a scope ({where})")
            continue  # the heuristic is a guess; it must never be the thing that deletes a sibling
        indexed = {e.url for e in known_rows if (e.site, kind_of(e)) in scope}
        if indexed and not ({e.url for e in rows.values()} - indexed):
            replace.add(name)  # new ids, no new files: the fragment re-keyed what it already had
            print(f"  {name}: {fresh_ids}/{len(rows)} ids new but no new files -> replacing its scope")

    drop: set[str] = set()
    for name in sorted(replace):
        rows = fragments.get(name)
        if not rows:
            print(f"  --replace {name}: no such fragment, nothing retracted", file=sys.stderr)
            continue
        scope = set()
        for one in scopes_of[name]:
            missing = held.get(one, set())
            if missing:  # a co-owner of this scope was held back, so its rows are not in `keep`
                print(
                    f"  --replace {name}: refusing scope {one[0]} ({one[1]}) - also written by "
                    f"{', '.join(sorted(missing))}, which this merge skipped",
                    file=sys.stderr,
                )
                continue
            scope.add(one)
        # Every present fragment that writes into these scopes is part of the truth for them.
        keep = {eid for other in sorted({n for s in scope for n in owners[s]}) for eid in fragments[other]}
        stale = {e.id for e in store.registry() if (e.site, kind_of(e)) in scope and e.id not in keep}
        co = sorted({n for s in scope for n in owners[s]} - {name})
        print(
            f"  --replace {name}: {len(keep)} row(s) own {len(scope)} site/kind scope(s), {len(stale)} superseded"
            + (f" (scope shared with {', '.join(co)}, all present)" if co else "")
        )
        drop |= stale
    for path in sorted(FRAGMENTS.glob("*.drop.json")):
        try:
            ids = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  {path.name:<28} unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        listed = {str(i) for i in ids} if isinstance(ids, list) else set()
        still = len(listed & set(incoming))
        for eid in listed:  # an explicit drop list is the owner retracting the row, so it outranks
            incoming.pop(eid, None)  # a fragment that still happens to carry it
        print(f"  {path.name:<28} {len(listed):>6} id(s) to drop" + (f" ({still} also still in a fragment)" if still else ""))
        drop |= listed
    if drop:
        _retract(store, drop)

    if incoming:
        store.put_registry(merge_ua(incoming.values()))  # one write for every fragment, not one each
    pending = store.registry()
    if args.restamp:  # the classifier improved: re-label every row from its url and title
        for e in pending:
            e.docKind = None
    else:
        pending = [e for e in pending if not e.docKind or not e.needsUa]
    stamped = [e for e in merge_ua(pending) if e.docKind or e.needsUa]
    if stamped:  # rows indexed before docKind existed, or before their host was known to need a UA
        store.put_registry(stamped)
        print(f"  stamped {len(stamped)} row(s) with docKind / User-Agent metadata")
    docs = {}
    for e in store.registry():
        docs.setdefault(e.site, {}).setdefault(doc_kind(e), 0)
        docs[e.site][doc_kind(e)] += 1
    mixed = {site: kinds for site, kinds in docs.items() if set(kinds) - {"owner"}}
    if mixed:
        print("  docKind by site (sites publishing more than handbooks):")
        for site, kinds in sorted(mixed.items(), key=lambda kv: -sum(kv[1].values())):
            spread = "  ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
            print(f"    {site:<34}{spread}")
    if rejected:
        kept = sum(1 for r in rejected if r[4])
        print(f"  IMPOSSIBLE MODEL YEAR on {len(rejected)} row(s) (outside {MODEL_YEARS.start}-{MODEL_YEARS.stop - 1}): "
              f"the value is dropped, {kept} row(s) keep their other years, {len(rejected) - kept} row(s) had none left")
        for name, site, eid, off, survives in rejected[:40]:
            print(f"    {site:<30} {off!s:<18} {'kept' if survives else 'DROPPED':<8} {eid[:52]:<52} {name}")
        if len(rejected) > 40:
            print(f"    ... and {len(rejected) - 40} more")
        print("    the raw value comes from the site named above - fix that adapter, this check only contains it.")
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
    by_kind(entries, bikes)
    by_make: dict[str, int] = {}
    for e in free:
        by_make[e.make] = by_make.get(e.make, 0) + 1
    print("  " + "  ".join(f"{make} {n}" for make, n in sorted(by_make.items(), key=lambda kv: -kv[1])))
    return 0


def weak_vehicles(store) -> list[tuple[Bike, RegistryEntry, str]]:
    """Vehicles whose best free English PDF is a brochure, quick guide, warranty insert or spec sheet."""
    index = pdf_index()
    out = []
    for b in store.bikes():
        rows = index.get(b.id)
        if not rows:
            continue
        best = _pick(rows, b.market, kind_of(b))
        kind = doc_kind(best)
        if kind != "owner":
            out.append((b, best, kind))
    return out


def cmd_enrich(args: argparse.Namespace) -> int:
    """Re-ask the OEM's own manual endpoint for the vehicles that only have a brochure or a quick
    guide, and write whatever new PDF it names as a fragment. Adds rows, never edits or deletes one:
    the brochure stays indexed, it just stops being the best answer for that vehicle."""
    store = get_store()
    weak = weak_vehicles(store)
    by_site: dict[str, int] = {}
    for _b, e, _k in weak:
        by_site[e.site] = by_site.get(e.site, 0) + 1
    print(f"{len(weak)} vehicle(s) have no owner's manual; by site: " + ", ".join(f"{s} {n}" for s, n in sorted(by_site.items(), key=lambda kv: -kv[1])))
    for b, e, kind in sorted(weak, key=lambda w: (w[0].make, w[0].model, w[0].year))[: args.list]:
        print(f"    {b.make:<12}{b.model[:26]:<26}{b.year}  {kind:<11}{e.site}")
    if not args.brand:  # re-querying every OEM would be a full crawl, so an adapter must be named
        print("pass --brand <adapter> to re-query one of those sites")
        return 0
    names = select(args.brand)
    known = {e.url for e in store.registry()}
    wanted = {(b.make.lower(), b.model.lower()) for b, _e, _k in weak}
    FRAGMENTS.mkdir(parents=True, exist_ok=True)
    for name in names:
        try:
            rows = [e for e in ADAPTERS[name]() if e.url]
        except Exception as exc:
            print(f"  {name}: adapter failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        fresh = [e for e in rows if e.url not in known and doc_kind(e) == "owner"]
        hits = [e for e in fresh if (e.make.lower(), e.model.lower()) in wanted]
        if not fresh:
            print(f"  {name}: {len(rows)} rows, nothing the registry was missing")
            continue
        merge_ua(fresh)
        site = fresh[0].site
        path = FRAGMENTS / f"enrich-{site}.json"
        path.write_text(json.dumps([e.model_dump(exclude_none=True) for e in fresh], ensure_ascii=False), encoding="utf-8")
        print(f"  {name}: {len(fresh)} new owner PDF(s) -> {path.name} ({len(hits)} for a vehicle that had none)")
    print("run merge-fragments to fold them in")
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
    print(f"\ncatalog: {len(bikes)} vehicles, {offered} with a free PDF, {linked} already ingested")
    by_kind(entries, bikes)
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

    c7 = sub.add_parser("enrich", help="re-ask an OEM endpoint for vehicles that only have a brochure")
    c7.add_argument("--brand", action="append")
    c7.add_argument("--list", type=int, default=20, help="how many of the affected vehicles to print")
    c7.set_defaults(fn=cmd_enrich)

    c6 = sub.add_parser("merge-fragments", help="fold data/registry-fragments/*.json into the registry")
    c6.add_argument("--skip", action="append", help="fragment to leave out, by file name (repeatable)")
    c6.add_argument("--replace", action="append", help="fragment that owns its site/kind scope: rows it no longer lists are deleted")
    c6.add_argument("--restamp", action="store_true", help="re-classify docKind on every row, not just the unstamped ones")
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
