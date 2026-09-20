/**
 * How many catalog rows actually get a photo, and which models still do not.
 *
 *   node web/tools/images-coverage.mjs                 # measure, print the summary
 *   node web/tools/images-coverage.mjs --write         # also write docs/qa/images-gaps.md
 *   node web/tools/images-coverage.mjs --before        # measure the old exact+VARIANT lookup too
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
const TOP_GAPS = 30;

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
console.log(`images: ${sizes[0]} + ${sizes[1]} -> ${Object.keys(map).length} merged keys`);

if (process.argv.includes("--before")) {
  console.log(line("before", measure(rows, map, oldLookup)));
}
const after = measure(rows, map, lookupImage);
console.log(line("after ", after));

const gaps = [...after.table.values()].filter((m) => !m.hit).sort((a, b) => b.rows - a.rows);
const gapRows = gaps.reduce((n, m) => n + m.rows, 0);
console.log(`uncovered: ${gaps.length} models over ${gapRows} rows`);
console.log(
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
    "A model here has no key in web/store/bike-images.json or bike-images-2.json that the ladder can",
    "reach - not a spelling the ladder misses, but a photo nobody has taken yet. The ladder never",
    "crosses a digit run, so a size that has no photo of its own stays on this list rather than",
    "borrowing its sibling's.",
    "",
  ].join("\n");
  mkdirSync(dirname(GAPS), { recursive: true });
  writeFileSync(GAPS, body, "utf8");
  console.log(`wrote ${GAPS}`);
}
