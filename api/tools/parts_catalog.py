"""Check, warm and illustrate the standard parts catalogue.

  api/.venv/Scripts/python api/tools/parts_catalog.py --check
      validates api/data/parts-taxonomy.json: unique ids, known groups, known applicability values,
      and whether every icon it names has an illustration in web/store/icons-parts-3d/.

  api/.venv/Scripts/python api/tools/parts_catalog.py --report ktm-390-duke-2024 bmw-r-1300-gs-2025
      builds the catalogue for those bikes and prints counts per group plus example mentions.

  api/.venv/Scripts/python api/tools/parts_catalog.py --warm --limit 50 [--llm]
      precomputes and caches the bike-independent scan for that many manuals, so the first request
      per manual is already warm. --llm adds the one cheap "parts.map" call per manual that ties the
      manual's leftover parts to catalogue ids; without it nothing costs anything.

  api/.venv/Scripts/python api/tools/parts_catalog.py --art [--budget 6] [--quality medium]
      renders an illustration for every icon the taxonomy names that has none yet, through
      api/tools/part_illustrations.py - same style prompt, same camera, same set - and rewrites
      web/store/icons-parts-3d/index.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app import parts_catalog as pc  # noqa: E402
from app.store import get_store  # noqa: E402

ART_DIR = ROOT / "web" / "store" / "icons-parts-3d"

KINDS = {"motorcycle", "car"}
DRIVES = {"chain", "belt", "shaft"}
COOLINGS = {"liquid", "air"}
FUELS = {"efi", "carb", "petrol", "diesel"}

# What each icon the taxonomy adds actually is. Same shape as part_illustrations.SUBJECTS: the
# camera, the light and the orange come from that file, only the object changes.
SUBJECTS: dict[str, str] = {
    "valve-shim": "set of three valve adjustment shims, thin polished steel discs stacked in a short step",
    "gasket": "engine valve cover gasket, a moulded rubber-coated steel gasket ring with an orange bead",
    "clutch-plates": "short stack of clutch friction plates, toothed steel discs with cork friction "
    "material, offset so the stack reads as several plates",
    "clutch-spring": "set of four coil clutch springs standing upright in a row, orange powder coated",
    "water-pump": "engine water pump, aluminium housing with an impeller and a pulley flange",
    "thermostat": "engine cooling thermostat, a brass and steel valve disc on a wax capsule body",
    "radiator-cap": "radiator pressure cap, chromed steel cap with an orange rubber seal and a lever",
    "hose": "short length of reinforced black rubber coolant hose, curved, with two orange spring clamps",
    "cush-drive": "set of rubber cush drive dampers, five wedge-shaped black rubber blocks arranged in a fan",
    "drive-belt": "toothed final drive belt, a black rubber belt in a wide open loop showing the tooth profile",
    "final-drive": "shaft final drive housing, cast aluminium bevel gear casing with an output flange",
    "brake-line": "braided stainless steel brake line with orange anodised banjo fittings at both ends",
    "master-cylinder": "brake master cylinder with its fluid reservoir, machined aluminium body",
    "seal-kit": "brake caliper seal kit, three rubber seal rings and a dust boot laid in a small group",
    "fork-seal": "pair of fork oil seals, black rubber rings with a steel spine, one leaning on the other",
    "fork-oil": "one litre bottle of fork oil, plain unlabelled bottle with an orange cap and a narrow neck",
    "fork-spring": "single fork coil spring, long orange powder coated coil standing upright",
    "inner-tube": "motorcycle inner tube coiled into a neat black ring with a metal valve stem",
    "valve-stem": "pair of tyre valve stems, chromed metal stems with orange caps",
    "regulator": "voltage regulator rectifier, finned aluminium block with a multi-pin connector",
    "stator": "alternator stator ring, copper windings on a laminated steel core with an orange lead",
    "relay": "automotive starter relay, black cube body with four spade terminals and an orange label band",
    "starter-motor": "electric starter motor, cylindrical steel body with a pinion gear and a terminal post",
    "ignition-coil": "ignition coil stick, black moulded body with an orange connector and a spring contact",
    "plug-cap": "spark plug cap, black rubber right-angle boot with an orange band",
    "grips": "pair of motorcycle handlebar grips, ribbed black rubber with orange end collars",
    "bar-end": "pair of handlebar bar end weights, machined orange anodised aluminium cylinders",
    "brake-pedal": "motorcycle rear brake pedal, forged steel arm with a knurled foot tip",
    "gear-lever": "motorcycle gear shift lever, forged aluminium arm with an orange folding toe piece",
    "side-stand": "motorcycle side stand, folded steel leg with a foot plate and an orange return spring",
    "indicator": "motorcycle turn indicator, amber lens in a short black stalk housing",
    "windscreen": "motorcycle windscreen, a clear curved acrylic screen in a slim orange edge trim",
    "mudguard": "motorcycle front mudguard, a curved painted plastic fender seen from the side",
    "fairing": "motorcycle fairing side panel, a curved painted plastic body panel with mounting bosses",
    "fuel-cap": "fuel tank filler cap, machined aluminium cap with an orange anodised ring and a keyhole",
    "brake-shoes": "pair of drum brake shoes, curved steel shoes with friction lining, arranged as a circle",
    "fuel-pump": "in-tank fuel pump module, cylindrical body with a hose spigot and an electrical connector",
    "injector": "fuel injector, slim body with an orange o-ring at the nozzle and a two-pin connector",
    "carburettor": "motorcycle carburettor, aluminium body with a float bowl, throttle lever and idle screw",
    "sensor": "automotive threaded sensor, steel hex body with a short lead and an orange connector",
    "horn": "automotive disc horn, black spiral housing with a mounting bracket and two spade terminals",
    "cabin-filter": "cabin pollen filter, a rectangular pleated white filter panel in an orange frame",
    "wiper-blade": "windscreen wiper blade, a flat beam blade with a rubber edge and an orange adapter clip",
    "timing-belt": "toothed timing belt, black rubber belt in an open loop showing the tooth profile",
    "serpentine-belt": "v-ribbed serpentine drive belt, a multi-rib black belt in an open loop",
    "control-arm": "car lower control arm wishbone, a forged steel arm with a ball joint and two bushings",
    "tie-rod": "car track rod end, a threaded steel rod with a ball joint and an orange rubber boot",
    "ball-joint": "car suspension ball joint, a tapered steel stud in a housing with an orange rubber boot",
    "cv-boot": "constant velocity joint boot, a black ribbed rubber bellows with two orange clamps",
    "alternator": "car alternator, aluminium housing with a pulley, fan vents and a terminal post",
    "washer-fluid": "one litre bottle of windscreen washer fluid, translucent bottle with a blue liquid "
    "and an orange cap",
    "hydraulic-fluid": "small bottle of hydraulic fluid, plain silver bottle with an orange cap and a spout",
    "ignition-lead": "set of spark plug ignition leads, three black cables with orange boots, loosely coiled",
    "strut": "car suspension strut, a damper body with an orange coil spring and a top mount plate",
}


def taxonomy_icons() -> set[str]:
    return {p.icon for p in pc.taxonomy().parts}


def have_art() -> set[str]:
    index = ART_DIR / "index.json"
    if not index.exists():
        return set()
    return set(json.loads(index.read_text(encoding="utf-8")))


def check() -> int:
    tax = pc.taxonomy()
    groups = {g["id"] for g in tax.groups}
    ids, bad = set(), []
    for part in tax.parts:
        if part.id in ids:
            bad.append(f"duplicate id {part.id}")
        ids.add(part.id)
        if part.group not in groups:
            bad.append(f"{part.id}: unknown group {part.group}")
        if part.applies.kind not in KINDS:
            bad.append(f"{part.id}: unknown kind {part.applies.kind}")
        for field, allowed in (("types", set(pc.TYPES)), ("notTypes", set(pc.TYPES)),
                               ("drive", DRIVES), ("cooling", COOLINGS), ("fuel", FUELS)):
            values = getattr(part.applies, field) or []
            unknown = set(values) - allowed
            if unknown:
                bad.append(f"{part.id}: unknown {field} {sorted(unknown)}")
        if not part.searchHint.strip():
            bad.append(f"{part.id}: empty searchHint")
        if not part.synonyms:
            bad.append(f"{part.id}: no synonyms")

    per_kind = {k: sum(1 for p in tax.parts if p.applies.kind == k) for k in sorted(KINDS)}
    icons, art = taxonomy_icons(), have_art()
    print(f"{len(tax.parts)} entries {per_kind}, {len(groups)} groups, {len(icons)} icons")
    missing = sorted(icons - art)
    print(f"illustrations: {len(icons & art)} present, {len(missing)} missing")
    if missing:
        print("  missing:", ", ".join(missing))
    no_subject = sorted(i for i in missing if i not in SUBJECTS)
    if no_subject:
        bad.append(f"icons with no subject line in this tool: {no_subject}")
    for problem in bad:
        print("FAIL", problem)
    return 1 if bad else 0


def report(bike_ids: list[str]) -> int:
    store = get_store()
    for bike_id in bike_ids:
        bike = store.bike(bike_id)
        if bike is None or not bike.manualId:
            print(f"{bike_id}: no bike or no manual")
            continue
        result = pc.catalog(bike.manualId, bike, store=store, refresh=True)
        p = result.profile
        print(f"\n== {bike.make} {bike.model} {bike.year}  [{p.type}, {p.drive} drive, {p.cooling}-cooled, "
              f"{'/'.join(p.fuel)}]  manual {bike.manualId}")
        print(f"   {len(result.parts)} parts, {result.fromManual} printed by the manual, "
              f"{sum(1 for r in result.parts if r.mentions)} mentioned in it")
        print("   " + "  ".join(f"{g.label}:{g.count}" for g in result.groups))
        shown = 0
        for row in result.parts:
            if row.mentions and not row.oem:
                first = row.mentions[0]
                print(f"   - {row.name} (p.{first.page}): {first.quote[:90]}")
                shown += 1
            if shown >= 5:
                break
    return 0


def warm(limit: int, use_llm: bool) -> int:
    store = get_store()
    summaries = getattr(store, "manual_summaries", None)
    ids = [m["id"] for m in summaries()] if summaries else [m.id for m in store.manuals()]
    done = 0
    for manual_id in ids[:limit]:
        manual = store.manual(manual_id)
        if manual is None:
            continue
        data = pc.scanned(manual, store, refresh=True)
        if use_llm:
            extra = pc.map_ambiguous(manual, data["map"])
            if extra:
                data["map"].update(extra)
                pc.cache_write(store, manual_id, data)
        done += 1
        print(f"  {manual_id}: {len(data['mentions'])} mentioned, {len(data['map'])} mapped")
    print(f"{done} manuals warmed")
    return 0


def art(budget: float, quality: str, model: str | None) -> int:
    import part_illustrations as art_tool

    missing = sorted(taxonomy_icons() - have_art())
    unknown = [i for i in missing if i not in SUBJECTS]
    if unknown:
        raise SystemExit(f"no subject line for: {unknown}")
    # The catalogue's ids live here, not in part_illustrations.SUBJECTS, so that file stays the
    # parts-art agent's. Injecting them means its manifest() writes the whole set - and re-running
    # this command is how the set is restored if a plain part_illustrations.py run ever drops them.
    art_tool.SUBJECTS.update(SUBJECTS)
    chosen = model or art_tool.settings.model_image
    spent, failed = 0.0, []

    if missing:
        per = art_tool.IMAGE_TOKENS[quality] * art_tool.IMAGE_USD_PER_MTOK.get(chosen, 40.0) / 1_000_000
        print(f"{len(missing)} to render at ~${per:.3f} each, ~${per * len(missing):.2f} total, "
              f"budget ${budget:.2f}")
        if per * len(missing) > budget:
            raise SystemExit("over budget")

        from concurrent.futures import ThreadPoolExecutor

        def one(icon_id: str):
            try:
                png, usd = art_tool.render(icon_id, chosen, quality)
                art_tool.write(icon_id, png)
                return icon_id, usd, ""
            except Exception as exc:  # one bad id must not cost the other fifty
                return icon_id, 0.0, repr(exc)[:160]

        with ThreadPoolExecutor(max_workers=art_tool.WORKERS) as pool:
            for icon_id, usd, error in pool.map(one, missing):
                spent += usd
                if error:
                    failed.append(icon_id)
                print(f"  {'FAIL' if error else 'ok  '} {icon_id:<18} ${spent:.2f} {error}")
                if spent > budget:
                    print("budget reached, stopping")
                    break
    else:
        print("every taxonomy icon already has an illustration")

    every = art_tool.icon_ids()
    art_tool.manifest(every, chosen, quality)
    art_tool.sheet(every)
    print(f"{len(missing) - len(failed)} rendered, ${spent:.2f} spent")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", nargs="*", metavar="BIKE_ID")
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--llm", action="store_true", help="one cheap parts.map call per manual")
    parser.add_argument("--art", action="store_true")
    parser.add_argument("--budget", type=float, default=6.0)
    parser.add_argument("--quality", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    if args.art:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return art(args.budget, args.quality, args.model)
    if args.report is not None:
        return report(args.report or ["ktm-390-duke-2024", "bmw-r-1300-gs-2025"])
    if args.warm:
        return warm(args.limit, args.llm)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
