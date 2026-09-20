/**
 * Builds web/store/bike-types.json from api/data/seeds/all_bikez_curated.csv. Owner: vehicle-models.
 *
 *   node web/tools/bike-types.mjs          # rebuild the lookup
 *   node web/tools/bike-types.mjs --check  # classify every bike in api/data/bikes.json, print the
 *                                          # distribution and a sample per type (the unit test)
 *
 * The CSV carries a Category column for 38k bikez rows; the app's own roster (api/data/bikes.json)
 * has no type at all. This folds the CSV onto the same "make|model" key shape ttm.js uses for
 * web/store/bike-images.json, so one lookup answers both. Where a make+model spans several
 * categories across years (a model name reused on a different bike), the most common wins.
 *
 * Two things keep the shipped file small and honest:
 *   - every key the RULES in vehicle-type.js already answer is DROPPED, because the names beat
 *     bikez wherever both have an opinion (a Grom is filed under "Sport" over there). What ships
 *     is the gap list, not a second copy of the rules.
 *   - the type is written as its one-letter TYPE_CODE.
 * 554 KB of make|model -> type becomes ~60 KB of corrections that way.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const CSV = join(ROOT, "api", "data", "seeds", "all_bikez_curated.csv");
const BIKES = join(ROOT, "api", "data", "bikes.json");
const OUT = join(ROOT, "web", "store", "bike-types.json");

/** bikez Category -> our type. Anything not here falls through to the name heuristics. */
const FROM_CATEGORY = {
  "cross / motocross": "motocross",
  "minibike, cross": "minibike",
  "minibike, sport": "minibike",
  "enduro / offroad": "enduro",
  "super motard": "supermoto",
  sport: "sportbike",
  "sport touring": "sportbike",
  "naked bike": "naked",
  allround: "naked",
  "custom / cruiser": "cruiser",
  touring: "touring",
  scooter: "scooter",
  classic: "classic",
  trial: "trial",
  speedway: "motocross",
  atv: "atv",
  "unspecified category": "",
  "prototype / concept model": "",
};

/* --------------------------------------------------------------- the same fold as ttm.js */

export const foldPart = (value) =>
  String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "");

export const typeKey = (make, model) => `${foldPart(make)}|${foldPart(model)}`;

/* --------------------------------------------------------------- csv */

/** Minimal RFC4180 reader — the bikez export quotes fields that contain commas. */
function* rows(text) {
  let field = "";
  let row = [];
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false;
      } else field += c;
      continue;
    }
    if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); yield row; row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field || row.length) { row.push(field); yield row; }
}

async function build() {
  const { typeOf, CODE_OF } = await import("../counter/js/vehicle-type.js");
  const text = readFileSync(CSV, "utf8");
  const iterator = rows(text);
  const header = iterator.next().value.map((h) => h.trim());
  const iBrand = header.indexOf("Brand");
  const iModel = header.indexOf("Model");
  const iCategory = header.indexOf("Category");
  const votes = new Map();
  const names = new Map();
  let seen = 0;
  for (const row of iterator) {
    if (row.length < header.length - 2) continue;
    seen += 1;
    const type = FROM_CATEGORY[(row[iCategory] || "").trim().toLowerCase()];
    if (!type || type === "atv") continue;
    const key = typeKey(row[iBrand], row[iModel]);
    if (key === "|") continue;
    names.set(key, { make: row[iBrand], model: row[iModel] });
    const tally = votes.get(key) || (votes.set(key, new Map()), votes.get(key));
    tally.set(type, (tally.get(type) || 0) + 1);
  }
  const out = {};
  let covered = 0;
  for (const [key, tally] of votes) {
    let best = "";
    let top = 0;
    for (const [type, n] of tally) if (n > top) { top = n; best = type; }
    if (!best) continue;
    // the names already answer for this one, and they answer better — drop it
    const { make, model } = names.get(key);
    if (typeOf({ make, model }, null, { explain: true }).via === "heuristic") { covered += 1; continue; }
    out[key] = CODE_OF[best] || best;
  }
  const sorted = Object.fromEntries(Object.keys(out).sort().map((k) => [k, out[k]]));
  writeFileSync(OUT, JSON.stringify(sorted));
  const dist = {};
  for (const c of Object.values(sorted)) dist[c] = (dist[c] || 0) + 1;
  const back = Object.fromEntries(Object.entries(CODE_OF).map(([t, c]) => [c, t]));
  console.log(`${seen} csv rows -> ${votes.size} make|model keys, ${covered} already answered by the name rules`);
  console.log(`${Object.keys(sorted).length} corrections kept -> ${OUT} (${(JSON.stringify(sorted).length / 1024).toFixed(0)} KB)`);
  console.log(Object.entries(dist).sort((a, b) => b[1] - a[1]).map(([c, n]) => `  ${String(n).padStart(5)} ${back[c] || c}`).join("\n"));
  return sorted;
}

/* --------------------------------------------------------------- the unit test */

async function check() {
  const { typeOf, TYPES, exactModelFor, genericModelFor } = await import("../counter/js/vehicle-type.js");
  const table = JSON.parse(readFileSync(OUT, "utf8"));
  const bikes = JSON.parse(readFileSync(BIKES, "utf8"));
  const dist = new Map(TYPES.map((t) => [t, 0]));
  const source = { table: 0, heuristic: 0, make: 0, fallback: 0 };
  const samples = new Map(TYPES.map((t) => [t, []]));
  const byMake = new Map();
  for (const bike of bikes) {
    const { type, via } = typeOf(bike, table, { explain: true });
    dist.set(type, (dist.get(type) || 0) + 1);
    source[via] = (source[via] || 0) + 1;
    const list = samples.get(type);
    if (list && list.length < 6) list.push(`${bike.make} ${bike.model}`);
    const make = byMake.get(bike.make) || (byMake.set(bike.make, new Map()), byMake.get(bike.make));
    make.set(type, (make.get(type) || 0) + 1);
  }
  console.log(`\n${bikes.length} bikes in api/data/bikes.json`);
  console.log(`source: ${source.table} from bike-types.json · ${source.heuristic} from name heuristics · ${source.fallback} fallback\n`);
  for (const [type, n] of [...dist].sort((a, b) => b[1] - a[1])) {
    const pct = ((n / bikes.length) * 100).toFixed(1).padStart(5);
    console.log(`${String(n).padStart(6)} ${pct}%  ${type.padEnd(11)} ${(samples.get(type) || []).slice(0, 4).join(" · ")}`);
  }
  console.log("\nper make (top type):");
  for (const [make, tally] of [...byMake].sort((a, b) => [...b[1].values()].reduce((x, y) => x + y, 0) - [...a[1].values()].reduce((x, y) => x + y, 0)).slice(0, 14)) {
    const line = [...tally].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([t, n]) => `${t} ${n}`).join(", ");
    console.log(`  ${make.padEnd(16)} ${line}`);
  }
  const spot = [
    ["KTM", "450 SX-F", "motocross"], ["KTM", "390 Duke", "naked"], ["KTM", "500 EXC-F", "enduro"],
    ["KTM", "690 SMC R", "supermoto"], ["Yamaha", "YZF-R7", "sportbike"], ["Yamaha", "YZ250F", "motocross"],
    ["Yamaha", "Ténéré 700", "adventure"], ["Honda", "CBR650R", "sportbike"], ["Honda", "Gold Wing", "touring"],
    ["Honda", "Grom", "minibike"], ["Honda", "Africa Twin", "adventure"], ["Vespa", "Primavera 150", "scooter"],
    ["Harley-Davidson", "Softail Standard", "cruiser"], ["Chevrolet", "Corvette Stingray", "car"],
    ["BMW", "R 1250 GS", "adventure"], ["BMW", "S 1000 RR", "sportbike"], ["Kawasaki", "Ninja ZX-10R", "sportbike"],
    ["Kawasaki", "Z900", "naked"], ["Triumph", "Bonneville Bobber", "cruiser"], ["Ducati", "Panigale V4", "sportbike"],
    ["Ducati", "Monster", "naked"], ["Royal Enfield", "Classic 350", "classic"], ["GasGas", "TXT Racing 300", "trial"],
    ["Suzuki", "Burgman 400", "scooter"], ["Husqvarna", "FE 350", "enduro"], ["Indian", "Chief Bobber", "cruiser"],
  ];
  let bad = 0;
  console.log("\nspot checks:");
  for (const [make, model, want] of spot) {
    const got = typeOf({ make, model }, table);
    const exact = exactModelFor({ make, model });
    const mark = got === want ? "ok  " : "FAIL";
    if (got !== want) bad += 1;
    console.log(`  ${mark} ${(`${make} ${model}`).padEnd(30)} ${got.padEnd(11)} ${want === got ? "" : `want ${want}`}${exact ? `  exact:${exact}` : ""}`);
  }
  console.log(`\ngeneric keys: ${TYPES.map((t) => `${t}->${genericModelFor(t)}`).join(" ")}`);
  console.log(bad ? `\n${bad} spot check(s) FAILED` : "\nall spot checks pass");
  process.exitCode = bad ? 1 : 0;
}

if (process.argv.includes("--check")) await check();
else await build();
