/**
 * Catalog data helpers for ttm.js — bundle expansion, aliases, and the search index schedule.
 * Owner: adapter agent. No network here: ttm.js fetches, this module only shapes.
 *
 * Why a bundle: GET /catalog is 17.8k rows / 2.5 MB. We cannot ship that next to the app,
 * so web/store/ttm-catalog.json ships the *grouped* form (one row per make+model, 312 KB)
 * and we expand it back here. Ids are rebuilt with the same slug the API uses, so an
 * offline bike id is byte-identical to the online one (17801 of 17803 live ids; the 2
 * misses are the API's own duplicate rows for BMW R 12 G/S 2025 and BMW R 12 2024).
 *
 * Why the index is scheduled: search.js buildIndex over 17.8k bikes costs ~250-400 ms and
 * ~90-125 MB (measured in node). Boot must not pay that before first paint, so it runs on
 * an idle callback and findBikes() forces it if a keystroke arrives first.
 */

import { buildIndex, indexedCount } from "./search.js";

const DEFAULT_MARKET = "WW";

/** Same slug as api/app/main.py slug() and src/data/index.ts bikeId(). */
export function bikeId(make, model, year) {
  return `${make} ${model} ${year}`
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function compact(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "");
}

/**
 * The aliases search.js indexes: the model alone, make + model, and the compact forms of
 * both. search.js already derives most of these from make/model, so the array is deduped
 * hard; carrying it anyway keeps the row shape identical to store/catalog.json, which is
 * what the Identify screen reads.
 */
export function aliasesOf(make, model) {
  const out = new Set();
  const m = String(model ?? "").trim().toLowerCase();
  const mk = String(make ?? "").trim().toLowerCase();
  if (m) {
    out.add(m);
    out.add(compact(m));
  }
  if (m && mk) {
    out.add(`${mk} ${m}`);
    out.add(compact(`${mk}${m}`));
  }
  const words = m.split(/\s+/).filter(Boolean);
  if (words.length === 2) out.add(`${words[1]} ${words[0]}`); // "duke 390" for "390 Duke"
  out.delete("");
  return [...out];
}

/** Add `aliases` (and nothing else) to API bike rows, in place. */
export function decorate(bikes) {
  for (const b of bikes) {
    if (!b || typeof b !== "object") continue;
    if (!Array.isArray(b.aliases)) b.aliases = aliasesOf(b.make, b.model);
  }
  return bikes;
}

function yearsOf(packed) {
  if (Array.isArray(packed)) return packed;
  if (packed && Array.isArray(packed.r)) {
    const [from, to] = packed.r;
    const out = new Array(to - from + 1);
    for (let i = 0; i < out.length; i++) out[i] = from + i;
    return out;
  }
  return [];
}

function marketOf(packed, year) {
  if (!packed) return DEFAULT_MARKET;
  if (typeof packed === "string") return packed;
  return packed[year] ?? DEFAULT_MARKET;
}

/**
 * web/store/ttm-catalog.json -> Bike[] with aliases.
 * Row: [make, model, years, manuals, market, ids?, urls?] — see web/tools/catalog.mjs.
 */
export function expandBundle(bundle) {
  const rows = bundle && Array.isArray(bundle.rows) ? bundle.rows : [];
  const out = [];
  const seen = new Set();
  for (const row of rows) {
    const [make, model, years, manuals, market, ids, urls] = row;
    const aliases = aliasesOf(make, model);
    for (const year of yearsOf(years)) {
      const id = (ids && ids[year]) || bikeId(make, model, year);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({
        id,
        make,
        model,
        year,
        market: marketOf(market, year),
        manualId: (manuals && manuals[year]) || null,
        manualUrl: (urls && urls[year]) || null,
        aliases,
      });
    }
  }
  return out;
}

let indexed = null;
let indexPromise = null;

function idle(fn) {
  if (typeof requestIdleCallback === "function") requestIdleCallback(fn, { timeout: 2500 });
  else setTimeout(fn, 250);
}

/** Build the search.js index now. Cheap no-op when the same roster is already indexed. */
export function forceIndex(bikes) {
  if (indexed === bikes && indexedCount() === bikes.length) return;
  buildIndex(bikes);
  indexed = bikes;
}

/** Build it when the main thread is free; resolves once built. findBikes() forces it early. */
export function scheduleIndex(bikes) {
  if (indexed === bikes) return Promise.resolve();
  indexPromise = new Promise((done) => {
    idle(() => {
      forceIndex(bikes);
      done();
    });
  });
  return indexPromise;
}

export function indexReady() {
  return indexed !== null;
}
