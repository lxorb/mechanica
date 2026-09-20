/**
 * How many catalog rows actually get a photo, and which models still do not.
 *
 *   node web/tools/images-coverage.mjs                 # measure, print the summary
 *   node web/tools/images-coverage.mjs --write         # also write docs/qa/images-gaps.md
 *   node web/tools/images-coverage.mjs --before        # measure the old exact+VARIANT lookup too
 *   node web/tools/images-coverage.mjs --top 200       # how many gaps to list (default 30)
 *   node web/tools/images-coverage.mjs --keys --top 200  # print "Make|Model" lines instead, for
 *                                                        # api/tools/images2.py --only
 *
 * Reads the same two files the counter reads (web/store/bike-images.json wins every key it shares
 * with bike-images-2.json) and the same catalog the bundled roster is built from
 * (api/data/bikes.json - see web/tools/catalog.mjs). The lookup under test is ttm.js's own
 * `lookupImage`, imported, so this can never drift from what the app does.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { lookupImage } from "../counter/js/ttm.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const GAPS = resolve(ROOT, "docs", "qa", "images-gaps.md");
/** --top N, default 30. The gap list is the highest-yield lane an image pass has: each
 *  entry stands for every catalog row of that model, so a photo near the top of this
 *  list is worth twenty from the open queue. */
const argOf = (flag, fallback) => {
  const at = process.argv.indexOf(flag);
  const value = at >= 0 ? Number(process.argv[at + 1]) : NaN;
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
};
const TOP_GAPS = argOf("--top", 30);

const json = (path) => JSON.parse(readFileSync(resolve(ROOT, path), "utf8"));

/** The counter's own merge: the first file wins every key the two share. */
function imageMap() {
  const one = json("web/store/bike-images.json");
  const two = json("web/store/bike-images-2.json");
  return { map: { ...two, ...one }, sizes: [Object.keys(one).length, Object.keys(two).length] };
}

/* --- the lookup as it was before the ladder, for the before/after ----------------------------- */

const OLD_VARIANT = /[\s-]+(abs|r|s|se|le|sp|gt|rs|rr|x|eu|us|a|dct)$/i;
const oldPart = (v) =>
  String(v ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "");

function oldLookup(map, make, model) {
  let name = String(model ?? "");
  for (let i = 0; i < 4; i++) {
    const hit = map[`${oldPart(make)}|${oldPart(name)}`];
    if (hit) return hit;
    const shorter = name.replace(OLD_VARIANT, "");
    if (shorter === name || !shorter) return null;
    name = shorter;
  }
  return null;
}

/* --- measure ---------------------------------------------------------------------------------- */

function measure(rows, map, lookup) {
  let rowsHit = 0;
  const models = new Map(); // "Make|Model" -> {make, model, rows, hit}
  for (const b of rows) {
    if (!b || !b.make || !b.model) continue;
    const key = `${b.make}|${b.model}`;
    let entry = models.get(key);
    if (!entry) {
      entry = { make: b.make, model: b.model, rows: 0, hit: Boolean(lookup(map, b.make, b.model)) };
      models.set(key, entry);
    }
    entry.rows += 1;
    if (entry.hit) rowsHit += 1;
  }
  const hitModels = [...models.values()].filter((m) => m.hit).length;
  return { rows: rows.length, rowsHit, models: models.size, hitModels, table: models };
}

const pct = (a, b) => (b ? `${((a / b) * 100).toFixed(1)}%` : "-");

function line(label, m) {
  return `${label}: ${m.rowsHit}/${m.rows} rows (${pct(m.rowsHit, m.rows)}), ${m.hitModels}/${m.models} models (${pct(m.hitModels, m.models)})`;
}

const { map, sizes } = imageMap();
const rows = json("api/data/bikes.json");
// --keys is meant to be piped straight into `images2.py --only`, so it prints the
// keys and nothing else.
const KEYS = process.argv.includes("--keys");
const say = (...parts) => {
  if (!KEYS) console.log(...parts);
};
say(`images: ${sizes[0]} + ${sizes[1]} -> ${Object.keys(map).length} merged keys`);

if (process.argv.includes("--before")) {
  say(line("before", measure(rows, map, oldLookup)));
}
const after = measure(rows, map, lookupImage);
say(line("after ", after));

const gaps = [...after.table.values()].filter((m) => !m.hit).sort((a, b) => b.rows - a.rows);
const gapRows = gaps.reduce((n, m) => n + m.rows, 0);

/**
 * Gaps where the image set does have a photo filed under a LONGER name of the same make and the
 * same displacement - "V-STAR 650" against "v-star-650-classic". The ladder only ever shortens a
 * name, on purpose: lengthening one would also hand Land Rover Discovery the Discovery Sport's
 * photo and Ford Explorer the Explorer Sport Trac's, which are different vehicles. Counted here so
 * the size of that trade is known rather than guessed at.
 */
function longerNames() {
  const flat = new Map();
  for (const key of Object.keys(map)) {
    const [mk, md] = key.split("|");
    const f = `${mk.replace(/-/g, "")}|${md.replace(/-/g, "")}`;
    if (!flat.has(f)) flat.set(f, key);
  }
  const bare = (v) => String(v ?? "").toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replace(/[^a-z0-9]+/g, "");
  const digits = (v) => (String(v).match(/\d+/g) || []).join("-");
  let n = 0;
  for (const g of gaps) {
    const mk = bare(g.make);
    const md = bare(g.model);
    for (const [f, key] of flat) {
      const [fm, fd] = f.split("|");
      if (fm !== mk || !fd.startsWith(md) || fd === md) continue;
      if (digits(key.split("|")[1]) !== digits(g.model)) continue;
      n += 1;
      break;
    }
  }
  return n;
}
if (KEYS) {
  // Registry documents that arrived as catalog rows. Not vehicles; never photographable.
  const NOT_A_VEHICLE = /parts listing|shop dope|service bulletin|oper\.\/maint/i;
  console.log(
    gaps
      .filter((m) => !NOT_A_VEHICLE.test(m.model))
      .slice(0, TOP_GAPS)
      .map((m) => `${m.make}|${m.model}`)
      .join("\n")
  );
  process.exit(0);
}
say(`uncovered: ${gaps.length} models over ${gapRows} rows`);
say(
  gaps
    .slice(0, TOP_GAPS)
    .map((m) => `  ${String(m.rows).padStart(4)}  ${m.make} ${m.model}`)
    .join("\n")
);

if (process.argv.includes("--write")) {
  const today = new Date().toISOString().slice(0, 10);
  const body = [
    "# Vehicle photo gaps",
    "",
    `Generated ${today} by \`node web/tools/images-coverage.mjs --write\`. Re-run it after an image pass.`,
    "",
    `Coverage: **${after.rowsHit}/${after.rows}** catalog rows (${pct(after.rowsHit, after.rows)}) and ` +
      `**${after.hitModels}/${after.models}** distinct models (${pct(after.hitModels, after.models)}) ` +
      `resolve to a photo through \`lookupImage\` in web/counter/js/ttm.js.`,
    "",
    `Still uncovered: ${gaps.length} models over ${gapRows} rows. The ${TOP_GAPS} worth shooting first,`,
    "by how many catalog rows go without a picture:",
    "",
    "| rows | make | model |",
    "| ---: | --- | --- |",
    ...gaps.slice(0, TOP_GAPS).map((m) => `| ${m.rows} | ${m.make} | ${m.model} |`),
    "",
    "## What this list is and is not",
    "",
    "A model here has no key in web/store/bike-images.json or bike-images-2.json that the ladder can",
    "reach - not a spelling the ladder misses, but a photo nobody has taken yet. The ladder never",
    "crosses a digit run, so a size with no photo of its own stays on this list rather than borrowing",
    "its sibling's: a YZF-R6 never gets the R1's picture and a CB500F never gets the CB650's.",
    "",
    `Of the ${gaps.length}, **${longerNames()}** do have a photo filed under a *longer* name of the same make and`,
    "the same displacement - \"V-STAR 650\" against `yamaha|v-star-650-classic`. The ladder shortens a",
    "name but never lengthens one, because the same rule would hand Land Rover Discovery the Discovery",
    "Sport's photo and Ford Explorer the Explorer Sport Trac's. Renaming those keys in the image files",
    "is the safe way to collect them.",
    "",
    "A few rows near the top are not vehicles at all (Harley-Davidson \"Parts Listing\", \"Shop Dope/Service",
    "Bulletins\"): registry documents that came in as catalog rows. They want deleting, not photographing.",
    "",
  ].join("\n");
  mkdirSync(dirname(GAPS), { recursive: true });
  writeFileSync(GAPS, body, "utf8");
  console.log(`wrote ${GAPS}`);
}
