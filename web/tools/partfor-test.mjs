/**
 * Regression table for partFor(). Owner: vehicle-models agent.
 *
 *   node web/tools/partfor-test.mjs           # the built-in table — the one that must stay green
 *   node web/tools/partfor-test.mjs --live    # + every section title of four real manuals
 *   node web/tools/partfor-test.mjs --live --all   # ...printing all of them, not just surprises
 *
 * Why this file exists: "Brake fluid level" on a Yamaha MT-09 highlighted the front wheel. Two
 * separate bugs made that possible — a FALLBACK table in viewer3d.js that quietly substituted the
 * wheel when a model had no brake mesh, and rules loose enough to match on incidental words. The
 * table below is the contract that came out of fixing them:
 *
 *   brake anything  -> front-brake / rear-brake, never a wheel
 *   chain, sprocket -> chain / sprocket, never a wheel
 *   tyre, rim       -> wheel
 *   oil, filter     -> engine
 *   anything whose title names no component at all -> null
 *
 * Null is a pass, not a gap. The Pick screen explodes the model and highlights nothing, which is
 * the truthful answer when the manual heading does not name a part.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = pathToFileURL(resolve(HERE, "..", "counter", "js", "viewer3d.js")).href;
const API = process.env.TTM_API || "https://mechanica.emilvinu.ch/api";

/** title -> expected key. `null` means "must not guess". */
const TABLE = [
  // the founder's report, and its whole family
  ["Brake fluid level", "front-brake"],
  ["Checking the front brake fluid level", "front-brake"],
  ["Rear brake fluid reservoir", "rear-brake"],
  ["Brake pad wear", "front-brake"],
  ["Replacing the rear brake pads", "rear-brake"],
  ["Brake disc inspection", "front-brake"],
  ["Brake lever free play", "front-brake"],
  ["Rear brake pedal position", "rear-brake"],
  ["Brake caliper", "front-brake"],

  // chain and final drive must never be a wheel
  ["Drive chain slack", "chain"],
  ["Chain lubrication", "chain"],
  ["Cleaning and lubricating the drive chain", "chain"],
  ["Sprocket wear", "sprocket"],

  // wheels and tyres
  ["Tyre pressure", "front-wheel"],
  ["Checking the tyres", "front-wheel"],
  ["Rear wheel removal", "rear-wheel"],
  ["Front wheel bearing", "front-wheel"],
  ["Tread depth", "front-wheel"],

  // engine and its consumables
  ["Engine oil change", "engine"],
  ["Engine oil and oil filter", "engine"],
  ["Checking the engine oil level", "engine"],
  ["Valve clearance", "engine"],
  ["Coolant level", "radiator"],
  ["Radiator cap", "radiator"],
  ["Spark plug", "spark-plug"],
  ["Air filter element", "air-filter"],

  // electrics
  ["Battery", "battery"],
  ["Charging the battery", "battery"],
  ["Replacing a fuse", "fuse"],
  ["Headlight beam adjustment", "headlight"],
  ["Replacing the tail light bulb", "taillight"],
  ["Turn signal", "taillight"],

  // chassis
  ["Front fork oil", "front-fork"],
  ["Rear shock preload", "rear-shock"],
  ["Adjusting the rear suspension", "rear-shock"],
  ["Swingarm pivot", "swingarm"],
  ["Side stand", "footpeg"],
  ["Mirrors", "mirrors"],
  ["Clutch lever free play", "clutch"],
  ["Seat removal", "seat"],
  ["Fuel tank capacity", "fuel-tank"],
  ["Exhaust system", "exhaust"],
  ["Windscreen", "fairing"],

  // and the ones that must NOT guess
  ["Before every ride", null],
  ["Checking the front", null],
  ["General maintenance", null],
  ["Periodic maintenance chart", null],
  ["Safety information", null],
  ["Specifications", null],
  ["Warranty", null],
  ["Left and right", null],
  ["Replacement parts", null],
  ["How to use this manual", null],
];

/** The four the founder named. /manuals/ is keyed on manualId, which the catalog carries. */
const BIKES = ["ktm-390-duke-2024", "bmw-r-1300-gs-2025", "yamaha-mt-09-2025", "honda-cbr650r-2024"];

async function manualIds() {
  const res = await fetch(`${API}/catalog`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`catalog ${res.status}`);
  const rows = await res.json();
  const byId = new Map(rows.map((r) => [r.id, r]));
  const out = [];
  for (const id of BIKES) {
    const row = byId.get(id);
    if (row && row.manualId) { out.push([id, row.manualId]); continue; }
    // the exact year may not be seeded; take any year of the same make+model that has a manual
    const stem = id.replace(/-\d{4}$/, "");
    const near = rows.find((r) => r.id.startsWith(stem) && r.manualId);
    if (near) out.push([near.id, near.manualId]);
    else console.log(`  ! ${id}: no manual in the catalog`);
  }
  return out;
}

async function live(partFor, showAll) {
  const buckets = new Map();
  let total = 0;
  for (const [id, manualId] of await manualIds()) {
    let manual;
    try {
      const res = await fetch(`${API}/manuals/${manualId}`, { headers: { Accept: "application/json" } });
      if (!res.ok) { console.log(`  ! ${id} (${manualId}): ${res.status}`); continue; }
      manual = await res.json();
    } catch (error) {
      console.log(`  ! ${id}: ${error.message}`);
      continue;
    }
    const titles = new Set();
    for (const row of manual.sections || manual.toc || []) if (row && row.title) titles.add(row.title);
    for (const row of manual.jobs || []) if (row && row.title) titles.add(row.title);
    console.log(`\n== ${id}  ${titles.size} titles`);
    for (const title of titles) {
      const key = partFor(title);
      total += 1;
      const bucket = buckets.get(key || "null") || [];
      bucket.push(title);
      buckets.set(key || "null", bucket);
      if (showAll) console.log(`   ${String(key || "-").padEnd(12)} ${title.slice(0, 80)}`);
    }
  }
  console.log(`\n${total} live titles by key:`);
  for (const [key, list] of [...buckets].sort((a, b) => b[1].length - a[1].length)) {
    console.log(`  ${String(list.length).padStart(4)} ${key.padEnd(12)} ${list.slice(0, 3).map((t) => t.slice(0, 34)).join(" · ")}`);
  }
  // the specific confusion the founder reported, checked against real titles
  const brakeTitles = [...buckets.entries()].flatMap(([key, list]) =>
    list.filter((t) => /brake/i.test(t) && !/^(front|rear)-brake$/.test(key)).map((t) => `${key}: ${t}`));
  console.log(brakeTitles.length
    ? `\n${brakeTitles.length} brake titles NOT mapped to a brake:\n  ${brakeTitles.slice(0, 12).join("\n  ")}`
    : "\nevery live title containing \"brake\" maps to a brake");
}

async function main() {
  const { partFor } = await import(VIEWER);
  let bad = 0;
  for (const [title, want] of TABLE) {
    const got = partFor(title);
    if (got !== want) {
      bad += 1;
      console.log(`  FAIL ${title.padEnd(42)} got ${String(got)}  want ${String(want)}`);
    }
  }
  console.log(`${TABLE.length - bad}/${TABLE.length} table cases pass${bad ? ` — ${bad} FAILED` : ""}`);
  if (process.argv.includes("--live")) await live(partFor, process.argv.includes("--all"));
  process.exitCode = bad ? 1 : 0;
}

main().catch((error) => { console.error(error); process.exit(1); });
