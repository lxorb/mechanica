/**
 * Trust-the-manual backend adapter for the Handy Book counter app.
 * Owner: adapter agent. Screens import ONLY this module: `import * as Q from "../ttm.js"`.
 *
 * DECISION (point 3 of the brief). ttm.js is the single store module. It picks its own
 * backing at boot — `loadCatalog()` probes `${apiBase()}/health` with a 2.5 s timeout and
 * either (a) runs REMOTE against our FastAPI, or (b) runs LOCAL by delegating every
 * query.js-shaped call to ./query.js and merging the bundled roster on top so Identify
 * still searches 17.8k bikes offline. app.js only awaits `loadCatalog()` and publishes
 * `window.Q`; it never branches on which store won. query.js itself is untouched, so
 * ask.js (which imports pageTextUrl from it) keeps working.
 *
 * Every async function resolves; none of them reject on a network fault. List helpers
 * return [], single-record helpers return undefined/null. `ask` falls back to a local
 * keyword search so the UI never dead-ends. The two exceptions that DO reject are
 * `ingest` and `ensureManual`, because a screen has to show the user that the upload or
 * the on-demand index failed.
 *
 * Every async call awaits loadCatalog() itself, so a screen can call systems()/jobsFor()
 * without booting the store first. The sync helpers — bike, bikes, catalog, findBikes,
 * hasManual, manualState, part, pageUrl, asset — only answer after that promise settles
 * (app.js awaits it before importing screens). part(id) in REMOTE mode resolves against
 * whatever manuals this session has loaded, so call partsFor()/manual() first.
 *
 * Roster: the bundled web/store/ttm-catalog.json paints first (312 KB, ~150 ms) and
 * GET /catalog (2.4 MB, 1.5-4 s) refreshes it in the background, firing a window
 * "ttm:catalog" event if it actually changed anything. window.TTM_CATALOG = "api" waits
 * for the API instead. Duplicate rows (same make+model+year, two ids — the seeded one
 * with the manual and the registry slug without) are merged, keeping the row that has the
 * manual; the other id stays in `idAliases` and resolves through bike().
 *
 * Mapping of our backend (api/app/models.py) onto the Handy Book model the screens use:
 *   Bike    -> bike     {id, make, model, year, market, aliases[], manualId|null, manualUrl?,
 *                        idAliases[], thumb:null, image:null}
 *   Manual  -> manual   {id, bikeId, bikeIds[], title, kind:"owner", publisher, file (PDF url),
 *                        pages, pagesDir:null, toc[{title,page,level}], outline, sections, parts,
 *                        systems[], jobs[]}
 *   chapter -> system   {id, name, chapter, manualId, count}   (distinct Section.chapter in
 *                        section order; reference chapters — technical data, appendix,
 *                        general instructions, engineering details — sort to the back)
 *   Part    -> part     {id, systemId, name, spec, page, oem, links[{shop,url}], manualId}
 *   Section -> job      {id: bikeId+"/"+sectionId, bikeId, sectionId, manualId, systemId,
 *                        partId, partIds[], title, chapter, pages[pageStart..pageEnd],
 *                        page, printedPage:null, steps[{page}], related[{id,page,title}],
 *                        highlights[{page,x,y,w,h}], keywords[], oem, links[]}
 *
 * What our API does NOT have, and what screens therefore must not read:
 *   - page images: `pageUrl`/`thumbUrl`/`pageTextUrl` return "" in REMOTE mode. Render the
 *     PDF at `manual.file` with ./pdf.js (renderPage) and place `job.highlights` (fractions
 *     of the page box) over the canvas.
 *   - commerce: job.price / ship / days / from / used / alts / new are null or []. Part
 *     `links` (RevZilla / Partzilla / Amazon search urls) and `oem` are the only shopping
 *     data that exists.
 *   - `printedPage`, system `image`/`thumb`, part `image`/`thumb`. Bike `image`/`thumb`
 *     come from web/store/bike-images.json when that file exists, with `credit` alongside;
 *     they are relative paths, so wrap them in asset() like store/catalog.json's.
 *
 * Beyond query.js: ask, identifyPhoto/Vin/Part, partPhrase, ingest, ensureManual,
 * manualState, jobsFor, cost, voiceConfig, deepgramToken, apiBase, online, storeMode.
 */

import { highlight, search as searchIndex, tokens, fold } from "./search.js";
import { aliasesOf, bikeId as slugId, decorate, expandBundle, forceIndex, scheduleIndex } from "./index-data.js";

export { highlight, aliasesOf };

const PUBLIC_API = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";
const BUNDLE_URL = "../store/ttm-catalog.json";
const IMAGES_URL = "../store/bike-images.json";
const HEALTH_MS = 2500;
const CATALOG_MS = 25000;
const MANUAL_MS = 25000;
const ASK_MS = 12000;
const INGEST_POLL_MS = 1000;
const INGEST_MAX_MS = 15 * 60 * 1000;
const SECTIONS_POLL_MS = 2000;
const SECTIONS_MAX_MS = 3 * 60 * 1000;
const MAX_JOB_PAGES = 40;

/** Chapters that are reference material, not something a rider does at the counter. */
const TAIL = /technical data|specification|appendix|\bindex\b|general instruction|engineering detail|means of representation|warranty|safety advice|important notes/i;

/**
 * Part label -> the phrase we send to /ask. The ten the brief names, verbatim; the rest
 * come from api/app/parts/labels.py QUERY, which beats "underscores to spaces" at finding
 * the right section. Anything unknown still falls back to underscores to spaces.
 */
const PART_PHRASE = {
  brake_pad: "brake pads",
  chain: "chain tension",
  spark_plug: "spark plug",
  battery_terminal: "battery",
  fuse_box: "fuses",
  disc: "brake disc",
  forks: "front fork",
  radiator: "coolant",
  shock_absorbers: "rear suspension",
  brake_oil_reservoir: "brake fluid",
  cylinder_head: "cylinder head",
  alternator: "alternator",
  clutch_plate: "clutch",
  chain_sprocket: "sprocket wear",
  cylinder_block: "cylinder",
  piston: "piston",
  crankshaft: "crankshaft",
  camshaft: "camshaft",
  air_fin: "engine cooling fins",
  motorcycle_frame: "frame number",
  swingarm: "swingarm",
  gear_box: "gearbox oil",
  handlebar: "handlebar",
  brake_clutch_lever: "lever adjustment",
  brake_clutch_cable: "clutch cable play",
  brake_light_switch: "brake light",
  gear_lever: "gear lever",
  brake_pedal: "rear brake pedal",
  carburetor: "carburetor",
  fuel_tank: "fuel tank",
};

// ---------------------------------------------------------------- module state

let mode = null; // "remote" | "local"
let base = null; // resolved API base, once /health answered
let healthy = false;
let bootPromise = null;
let local = null; // the query.js module, LOCAL mode only

let roster = [];
let catalogView = null;
let imageMap; // undefined = not fetched yet, null = no file
let bikeIndex = new Map(); // id (and id alias) -> bike
let manualSummaries = [];
const manualCache = new Map(); // manualId -> mapped manual
const manualInflight = new Map();
const partIndex = new Map(); // partId and manualId/partId -> part

// ---------------------------------------------------------------- plumbing

function meta(name) {
  if (typeof document === "undefined") return "";
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? el.getAttribute("content") || "" : "";
}

function stored(key) {
  try {
    return globalThis.localStorage?.getItem(key) || "";
  } catch {
    return "";
  }
}

/**
 * window.TTM_API, else <meta name="ttm-api">, else localStorage "ttm.api", else "/api".
 * Once /health answers we remember the winner, so this is also the "which host are we
 * really talking to" accessor after boot.
 */
export function apiBase() {
  if (base) return base;
  const wanted = (globalThis.TTM_API || meta("ttm-api") || stored("ttm.api") || "/api").trim();
  return wanted.replace(/\/+$/, "") || "/api";
}

export function online() {
  return healthy;
}

/** "remote" | "local" | null before loadCatalog(). Debug aid, not part of query.js. */
export function storeMode() {
  return mode;
}

function timeout(ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  return { signal: c.signal, done: () => clearTimeout(t) };
}

async function http(path, opts = {}) {
  const { method = "GET", body, json, form, ms = 15000, base: override } = opts;
  const root = override ?? apiBase();
  const url = path.startsWith("http") ? path : `${root}${path}`;
  const guard = timeout(ms);
  const headers = { Accept: "application/json" };
  let payload = body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(json);
  }
  if (form !== undefined) payload = form;
  try {
    const res = await fetch(url, { method, headers, body: payload, signal: guard.signal });
    if (!res.ok) {
      const err = new Error(`${method} ${url} -> ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } finally {
    guard.done();
  }
}

async function quiet(path, opts, fallback) {
  try {
    return await http(path, opts);
  } catch {
    return fallback;
  }
}

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

async function probe(candidate) {
  try {
    const body = await http("/health", { ms: HEALTH_MS, base: candidate });
    return body && body.ok ? candidate : null;
  } catch {
    return null;
  }
}

/**
 * Probes the configured base and, when that is the bare "/api" default (no proxy in front
 * of `npx serve web`), the public deployment too. First one to answer wins.
 */
async function pickBase() {
  const wanted = apiBase();
  const candidates = wanted === "/api" ? [wanted, PUBLIC_API] : [wanted];
  const results = await Promise.all(candidates.map(probe));
  return results.find(Boolean) ?? null;
}

// ---------------------------------------------------------------- catalog

function normKey(bike) {
  return `${fold(bike.make)}|${fold(bike.model)}|${bike.year}`;
}

/**
 * The catalog can carry two rows for one bike — a seeded row with the manual
 * (`bmw-r12gs-2025`) and the registry slug with a null manual (`bmw-r-12-g-s-2025`).
 * Keep the row that has the manual (then the one with manualUrl), and keep the loser's id
 * as an alias so a VIN or photo result resolves either way.
 */
function mergeDuplicates(bikes) {
  const by = new Map();
  for (const b of bikes) {
    if (!b || typeof b.id !== "string") continue;
    const key = normKey(b);
    const seen = by.get(key);
    if (!seen) {
      by.set(key, b);
      continue;
    }
    const rank = (x) => (x.manualId ? 2 : x.manualUrl ? 1 : 0);
    const [win, lose] = rank(b) > rank(seen) ? [b, seen] : [seen, b];
    win.idAliases = [...new Set([...(win.idAliases ?? []), ...(lose.idAliases ?? []), lose.id])];
    if (!win.manualId && lose.manualId) win.manualId = lose.manualId;
    if (!win.manualUrl && lose.manualUrl) win.manualUrl = lose.manualUrl;
    by.set(key, win);
  }
  return [...by.values()];
}

function indexBikes(bikes) {
  const next = new Map();
  for (const b of bikes) {
    next.set(b.id, b);
    // The registry slug is a second id the API can hand back (identify, ingest), even when
    // this row carries the hand-written one. Index it so either string resolves.
    const slug = slugId(b.make, b.model, b.year);
    if (slug && slug !== b.id) {
      if (!b.idAliases?.includes(slug)) b.idAliases = [...(b.idAliases ?? []), slug];
    }
    for (const alias of b.idAliases ?? []) if (!next.has(alias)) next.set(alias, b);
  }
  bikeIndex = next;
  roster = bikes;
}

async function loadBundle() {
  try {
    const res = await fetch(BUNDLE_URL, { headers: { Accept: "application/json" } });
    if (!res.ok) return [];
    return expandBundle(await res.json());
  } catch {
    return [];
  }
}

/** "KTM", "390 Duke" -> "ktm|390-duke": the key shape of web/store/bike-images.json. */
function imageKey(make, model) {
  const part = (v) =>
    String(v ?? "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .replace(/[\s-]+/g, "-")
      .replace(/^-+|-+$/g, "");
  return `${part(make)}|${part(model)}`;
}

/** Trailing variant words an image set rarely distinguishes: "F 900 R ABS" -> "F 900 R". */
const VARIANT = /[\s-]+(abs|r|s|se|le|sp|gt|rs|rr|x|eu|us|a|dct)$/i;

function lookupImage(map, make, model) {
  let name = String(model ?? "");
  for (let i = 0; i < 4; i++) {
    const hit = map[imageKey(make, name)];
    if (hit) return hit;
    const shorter = name.replace(VARIANT, "");
    if (shorter === name || !shorter) return null;
    name = shorter;
  }
  return null;
}

/**
 * web/store/bike-images.json (another agent's file): {"make|model": {image, thumb, title,
 * author, license, source}}. Best effort — a missing file just leaves thumb/image null so
 * the roster shows its placeholder tile. Paths stay relative, like store/catalog.json:
 * screens must wrap them in Q.asset(). `credit` carries the attribution the licence needs.
 */
async function applyImages(bikes) {
  if (imageMap === undefined) {
    imageMap = null;
    try {
      const res = await fetch(IMAGES_URL, { headers: { Accept: "application/json" } });
      if (res.ok) imageMap = await res.json();
    } catch {
      imageMap = null;
    }
  }
  const map = imageMap;
  for (const b of bikes) {
    if (b.image || b.thumb) continue; // query.js rows ship their own art
    const hit = map ? lookupImage(map, b.make, b.model) : null;
    b.image = hit?.image ?? null;
    b.thumb = hit?.thumb ?? null;
    if (hit) b.credit = { title: hit.title, author: hit.author, license: hit.license, source: hit.source };
  }
  return bikes;
}

/**
 * GET /catalog is 2.4 MB and measured 1.5-4 s off the Azure container, which is dead time
 * in front of the Identify screen. The bundled roster expands to the same 17.8k ids in
 * ~150 ms, so it renders first and /catalog refreshes it in the background — the API stays
 * the source of truth within the session, it just no longer blocks the first screen.
 * Set window.TTM_CATALOG = "api" to skip the bundle and wait for the API instead.
 */
async function bootRemote() {
  const bundled = globalThis.TTM_CATALOG === "api" ? [] : await loadBundle();
  if (bundled.length) {
    indexBikes(await applyImages(mergeDuplicates(bundled)));
    scheduleIndex(roster);
    refreshRoster().catch(() => {});
  } else {
    const bikes = (await quiet("/catalog", { ms: CATALOG_MS }, [])) ?? [];
    indexBikes(await applyImages(mergeDuplicates(decorate(bikes))));
    scheduleIndex(roster);
  }
  // GET /manuals lists every indexed document and measured 5 s; nothing on the first
  // screen needs it, so it lands in the background and catalog() picks it up when it does.
  quiet("/manuals", { ms: CATALOG_MS }, []).then((rows) => {
    if (Array.isArray(rows) && rows.length) manualSummaries = rows;
  });
}

/**
 * Adopt GET /catalog when it carries bikes or manuals the bundle does not. Fires
 * window "ttm:catalog" so a screen that has already painted a roster can repaint.
 * Rerun `node web/tools/catalog.mjs --api <base>` to make this a no-op again.
 */
async function refreshRoster() {
  const bikes = await quiet("/catalog", { ms: CATALOG_MS }, null);
  if (!Array.isArray(bikes) || !bikes.length) return;
  const stale = bikes.some((b) => {
    const known = bikeIndex.get(b.id);
    return !known || (b.manualId && !known.manualId) || (b.manualUrl && !known.manualUrl);
  });
  if (!stale) return;
  const next = mergeDuplicates(decorate(bikes));
  for (const b of next) {
    const known = bikeIndex.get(b.id);
    if (known?.manualId && !b.manualId) b.manualId = known.manualId; // keep what ingest added
    if (known?.manualUrl && !b.manualUrl) b.manualUrl = known.manualUrl;
  }
  indexBikes(await applyImages(next));
  scheduleIndex(roster);
  globalThis.dispatchEvent?.(new CustomEvent("ttm:catalog", { detail: { bikes: roster.length } }));
}

async function bootLocal(url, collectionUrl) {
  try {
    local = await import("./query.js");
    await local.loadCatalog(url, collectionUrl);
  } catch {
    local = local ?? null;
  }
  const known = local?.bikes?.() ?? [];
  const seen = new Set(known.map((b) => b.id));
  const extra = [];
  for (const b of await loadBundle()) {
    if (seen.has(b.id)) continue;
    // Offline the bundled manualId points at a manual only the API can serve.
    extra.push({ ...b, manualId: local?.manual?.(b.manualId) ? b.manualId : null });
  }
  indexBikes(await applyImages(mergeDuplicates([...known, ...extra])));
  manualSummaries = local?.catalog?.()?.manuals ?? [];
  scheduleIndex(roster);
}

export function loadCatalog(url, collectionUrl) {
  if (bootPromise) return bootPromise;
  bootPromise = (async () => {
    const found = await pickBase();
    if (found) {
      base = found;
      healthy = true;
      mode = "remote";
      await bootRemote();
    } else {
      mode = "local";
      healthy = false;
      await bootLocal(url, collectionUrl);
    }
    return catalog();
  })().catch(() => {
    mode = mode ?? "local";
    return catalog();
  });
  return bootPromise;
}

/**
 * {bikes, manuals, systems, parts, jobs} so `Q.catalog()?.bikes` works like query.js.
 * systems/parts/jobs are per-manual on our backend, so they are empty here — use
 * systems(bikeId) / partsFor() / jobsFor(), which are async.
 */
export function catalog() {
  if (!catalogView || catalogView.bikes !== roster || catalogView.manuals !== manualSummaries) {
    catalogView = { bikes: roster, manuals: manualSummaries, systems: [], parts: [], jobs: [] };
  }
  return catalogView;
}

export function bikes() {
  return roster;
}

export function bike(id) {
  if (id == null || id === "") return undefined;
  return bikeIndex.get(String(id));
}

export function hasManual(id) {
  const b = typeof id === "object" ? id : bike(id);
  return !!(b && b.manualId);
}

/** "ready" = indexed now, "ondemand" = a free official PDF we can index on request. */
export function manualState(input) {
  const b = typeof input === "object" && input ? input : bike(input);
  if (!b) return "none";
  if (b.manualId) return "ready";
  if (b.manualUrl) return "ondemand";
  return "none";
}

/** Forces the idle-scheduled index if the first keystroke beat it. Sync, like query.js. */
export function findBikes(text, opts) {
  forceIndex(roster);
  return searchIndex(text, opts);
}

export function asset(path) {
  if (path == null || path === "") return path;
  const value = String(path);
  if (/^(?:[a-z]+:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)) return value;
  if (value.startsWith("/") || value.startsWith("../")) return value;
  return `../${value.replace(/^\.\//, "")}`;
}

// ---------------------------------------------------------------- manual mapping

function flattenOutline(nodes, level = 0, out = []) {
  for (const node of nodes ?? []) {
    if (!node) continue;
    out.push({ title: String(node.title ?? ""), page: Number(node.page) || 1, level });
    if (Array.isArray(node.children) && node.children.length) flattenOutline(node.children, level + 1, out);
  }
  return out;
}

function chapterSlug(chapter) {
  return String(chapter ?? "")
    .replace(/^\s*\d+(?:\.\d+)*\s+/, "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Manuals shout their chapters ("18 SERVICE WORK ON THE ENGINE"); screens want a label. */
function chapterName(chapter) {
  const raw = String(chapter ?? "").replace(/^\s*\d+(?:\.\d+)*\s+/, "").trim();
  if (!raw) return "";
  if (/[a-z]/.test(raw)) return raw;
  const low = raw.toLowerCase();
  return low.charAt(0).toUpperCase() + low.slice(1);
}

function pagesOf(section) {
  const from = Math.max(1, Number(section.pageStart) || 1);
  const to = Math.max(from, Number(section.pageEnd) || from);
  const span = Math.min(to - from + 1, MAX_JOB_PAGES);
  const out = new Array(span);
  for (let i = 0; i < span; i++) out[i] = from + i;
  return out;
}

function buildSystems(manual) {
  const order = [];
  const byChapter = new Map();
  const used = new Set();
  for (const section of manual.sections ?? []) {
    const chapter = String(section.chapter ?? "");
    let row = byChapter.get(chapter);
    if (!row) {
      let id = chapterSlug(chapter) || "section";
      let n = 2;
      while (used.has(id)) id = `${chapterSlug(chapter) || "section"}-${n++}`;
      used.add(id);
      row = { id, name: chapterName(chapter), chapter, manualId: manual.id, count: 0, tail: TAIL.test(chapter) ? 1 : 0 };
      byChapter.set(chapter, row);
      order.push(row);
    }
    row.count += 1;
  }
  const systems = order.slice().sort((a, z) => a.tail - z.tail || order.indexOf(a) - order.indexOf(z));
  return { systems, byChapter };
}

function buildJobs(manual, bikeId, byChapter) {
  const sectionsById = new Map((manual.sections ?? []).map((s) => [s.id, s]));
  const partsById = new Map((manual.parts ?? []).map((p) => [p.id, p]));
  const jobs = [];
  for (const section of manual.sections ?? []) {
    const pages = pagesOf(section);
    const partIds = Array.isArray(section.partIds) ? section.partIds.filter((id) => partsById.has(id)) : [];
    const head = partIds.length ? partsById.get(partIds[0]) : null;
    jobs.push({
      id: `${bikeId}/${section.id}`,
      bikeId,
      sectionId: section.id,
      manualId: manual.id,
      systemId: byChapter.get(String(section.chapter ?? ""))?.id ?? null,
      chapter: section.chapter,
      title: section.title,
      partId: partIds[0] ?? null,
      partIds,
      pages,
      page: pages[0],
      pageStart: pages[0],
      pageEnd: pages[pages.length - 1],
      printedPage: null,
      steps: pages.map((page) => ({ page })),
      related: (section.related ?? [])
        .map((id) => {
          const hit = sectionsById.get(id);
          return hit ? { id, page: hit.pageStart, title: hit.title } : null;
        })
        .filter(Boolean),
      highlights: section.highlights ?? [],
      keywords: section.keywords ?? [],
      oem: head?.oem ?? null,
      links: head?.links ?? [],
      price: null,
      ship: null,
      days: null,
      from: null,
      used: [],
      alts: [],
      new: null,
    });
  }
  return jobs;
}

function mapManual(raw) {
  const bikeIds = Array.isArray(raw.bikeIds) && raw.bikeIds.length ? raw.bikeIds : [];
  const owner = bikeIds[0] ?? raw.id;
  const { systems, byChapter } = buildSystems(raw);

  const systemByPart = new Map();
  for (const section of raw.sections ?? []) {
    const systemId = byChapter.get(String(section.chapter ?? ""))?.id ?? null;
    for (const partId of section.partIds ?? []) if (!systemByPart.has(partId)) systemByPart.set(partId, systemId);
  }
  const parts = (raw.parts ?? []).map((p) => ({
    ...p,
    systemId: systemByPart.get(p.id) ?? null,
    manualId: raw.id,
    image: null,
    thumb: null,
  }));
  for (const p of parts) {
    partIndex.set(`${raw.id}/${p.id}`, p);
    partIndex.set(p.id, p);
  }

  const made = {
    id: raw.id,
    bikeId: owner,
    bikeIds,
    title: raw.title ?? raw.id,
    kind: /(?:^|[-_])(?:sm|service)(?:[-_]|$)/i.test(raw.id) ? "service" : "owner",
    publisher: bike(owner)?.make ?? "",
    file: raw.file ?? "",
    pages: Number(raw.pages) || 0,
    pagesDir: null,
    textDir: null,
    source: raw.source ?? "",
    outline: raw.outline ?? [],
    toc: flattenOutline(raw.outline),
    sections: raw.sections ?? [],
    parts,
    systems,
  };
  made.jobs = buildJobs(made, owner, byChapter);
  made.jobsById = new Map(made.jobs.map((j) => [j.id, j]));
  made.byChapter = byChapter;
  return made;
}

function manualIdFor(id) {
  if (id == null || id === "") return null;
  const value = String(id);
  if (manualCache.has(value)) return value;
  const hit = bike(value);
  if (hit?.manualId) return hit.manualId;
  if (manualSummaries.some((m) => m && m.id === value)) return value;
  return value;
}

/** GET /manuals/{id}, cached and mapped. `fresh` skips the cache (used while ingesting). */
export async function manual(id, { fresh = false } = {}) {
  await loadCatalog();
  const manualId = manualIdFor(id);
  if (!manualId) return undefined;
  if (mode === "local") return local?.manual?.(manualId);
  if (!fresh && manualCache.has(manualId)) return manualCache.get(manualId);
  if (!fresh && manualInflight.has(manualId)) return manualInflight.get(manualId);

  const task = (async () => {
    const raw = await quiet(`/manuals/${encodeURIComponent(manualId)}`, { ms: MANUAL_MS }, null);
    if (!raw) return undefined;
    const made = mapManual(raw);
    manualCache.set(manualId, made);
    return made;
  })().finally(() => manualInflight.delete(manualId));

  manualInflight.set(manualId, task);
  return task;
}

/** The manual a bike id points at, mapped. undefined when the bike has no indexed manual. */
async function manualForBike(bikeId) {
  const hit = bike(bikeId);
  const manualId = hit?.manualId ?? manualIdFor(bikeId);
  if (!manualId) return undefined;
  return manual(manualId);
}

function ownerId(bikeId, made) {
  return bike(bikeId) ? String(bikeId) : made.bikeId;
}

function jobsOfManual(made, bikeId) {
  const owner = ownerId(bikeId, made);
  if (owner === made.bikeId) return made.jobs;
  return made.jobs.map((j) => ({ ...j, id: `${owner}/${j.sectionId}`, bikeId: owner }));
}

// ---------------------------------------------------------------- query.js surface

/** LOCAL mode: accept a manual id where a bike id is expected, like REMOTE mode does. */
function localBikeId(id) {
  if (bike(id)) return String(id);
  const rows = local?.catalog?.()?.bikes ?? [];
  return rows.find((b) => b.manualId === id)?.id ?? String(id ?? "");
}

export async function systems(bikeId) {
  await loadCatalog();
  if (mode === "local") return local?.systems?.(localBikeId(bikeId)) ?? [];
  const made = await manualForBike(bikeId);
  return made ? made.systems : [];
}

export async function jobsFor(bikeId, systemId) {
  await loadCatalog();
  if (mode === "local") {
    const owner = localBikeId(bikeId);
    const rows = (local?.catalog?.()?.jobs ?? []).filter((j) => j.bikeId === owner);
    if (!systemId) return rows;
    const wanted = new Set((local?.partsFor?.(owner, systemId) ?? []).map((p) => p.id));
    return rows.filter((j) => wanted.has(j.partId));
  }
  const made = await manualForBike(bikeId);
  if (!made) return [];
  const all = jobsOfManual(made, bikeId);
  return systemId ? all.filter((j) => j.systemId === systemId) : all;
}

export async function partsFor(bikeId, systemId) {
  await loadCatalog();
  if (mode === "local") {
    const owner = localBikeId(bikeId);
    if (systemId) return local?.partsFor?.(owner, systemId) ?? [];
    // query.js has no "all systems" mode; REMOTE mode has one, so build it.
    const out = [];
    for (const sys of local?.systems?.(owner) ?? []) out.push(...(local?.partsFor?.(owner, sys.id) ?? []));
    return out;
  }
  const made = await manualForBike(bikeId);
  if (!made) return [];
  if (!systemId) return made.parts;
  const wanted = new Set();
  for (const job of made.jobs) if (job.systemId === systemId) for (const id of job.partIds) wanted.add(id);
  const hits = made.parts.filter((p) => wanted.has(p.id));
  // A chapter can be pure procedure (no part named in any of its sections). Showing the
  // manual's whole part list beats showing an empty screen.
  return hits.length ? hits : made.parts;
}

export async function job(bikeId, partId) {
  await loadCatalog();
  if (mode === "local") return local?.job?.(localBikeId(bikeId), partId);
  const made = await manualForBike(bikeId);
  if (!made) return undefined;
  const all = jobsOfManual(made, bikeId);
  return all.find((j) => j.partIds.includes(partId)) ?? all.find((j) => j.sectionId === partId);
}

function splitJobId(id) {
  const value = String(id);
  const dunder = value.indexOf("__");
  if (dunder >= 1) return [value.slice(0, dunder), value.slice(dunder + 2)];
  const slash = value.indexOf("/");
  if (slash >= 1) return [value.slice(0, slash), value.slice(slash + 1)];
  return null;
}

export async function jobById(id) {
  await loadCatalog();
  if (id == null || id === "") return undefined;
  if (mode === "local") return local?.jobById?.(id);
  const split = splitJobId(id);
  if (!split) return undefined;
  const [bikeId, sectionId] = split;
  const made = await manualForBike(bikeId);
  if (!made) return undefined;
  return jobsOfManual(made, bikeId).find((j) => j.sectionId === sectionId);
}

/** Sync, like query.js: resolves against every manual loaded this session. */
export function part(id) {
  if (id == null || id === "") return undefined;
  if (mode === "local") return local?.part?.(id);
  return partIndex.get(String(id));
}

export function pageUrl(manualId, n) {
  if (mode === "local") return local?.pageUrl?.(manualId, n) ?? "";
  void manualId;
  void n;
  return ""; // PDF-only: render manual.file with ./pdf.js renderPage()
}

export function thumbUrl(manualId, n) {
  if (mode === "local") return local?.thumbUrl?.(manualId, n) ?? "";
  void manualId;
  void n;
  return "";
}

export function pageTextUrl(manualId, n) {
  if (mode === "local") return local?.pageTextUrl?.(manualId, n) ?? "";
  void manualId;
  void n;
  return ""; // unsupported: our sections carry keywords + highlights instead of page text
}

// ---------------------------------------------------------------- ask

const STOP = new Set(["the", "a", "an", "is", "are", "do", "does", "how", "what", "where", "when", "my", "it", "to", "of", "on", "in", "for", "and", "or", "i", "can", "should", "with", "at", "be"]);

function askTokens(query) {
  return tokens(query).filter((t) => t.length > 1 && !STOP.has(t));
}

function scoreSection(section, qTokens, phrase) {
  const hay = `${section.title} ${section.chapter} ${(section.keywords ?? []).join(" ")}`.toLowerCase();
  let score = 0;
  for (const keyword of section.keywords ?? []) {
    const k = String(keyword).toLowerCase();
    if (k === phrase) score += 6;
    else if (phrase && (k.includes(phrase) || phrase.includes(k))) score += 3;
  }
  if (phrase && section.title.toLowerCase().includes(phrase)) score += 5;
  const hayTokens = new Set(tokens(hay));
  let hit = 0;
  for (const t of qTokens) if (hayTokens.has(t)) hit += 1;
  if (!hit && !score) return 0;
  score += (hit / Math.max(1, qTokens.length)) * 4;
  return score;
}

/** Keyword search over section titles/keywords. Used when /ask is down or we are offline. */
function localMatches(made, query, limit = 6) {
  const phrase = String(query ?? "").trim().toLowerCase();
  const qTokens = askTokens(query);
  const scored = [];
  for (const section of made.sections ?? []) {
    const score = scoreSection(section, qTokens, phrase);
    if (score > 0) scored.push({ section, score });
  }
  scored.sort((a, z) => z.score - a.score);
  const top = scored.slice(0, limit);
  const best = top[0]?.score || 1;
  return top.map((m) => ({ section: m.section, score: Math.min(1, m.score / best) }));
}

/** LOCAL mode: the same keyword scoring over query.js jobs, which have no sections. */
function localJobAsk(manualOrBikeId, query) {
  const rows = local?.catalog?.()?.jobs ?? [];
  const owner = bike(manualOrBikeId)
    ? String(manualOrBikeId)
    : (rows.find((j) => j.manualId === manualOrBikeId)?.bikeId ?? null);
  const phrase = String(query ?? "").trim().toLowerCase();
  const qTokens = askTokens(query);
  const scored = [];
  for (const row of rows) {
    if (owner && row.bikeId !== owner) continue;
    const name = local?.part?.(row.partId)?.name ?? "";
    const faux = {
      id: row.id,
      title: `${row.title} ${name}`.trim(),
      chapter: "",
      keywords: [name, row.title].filter(Boolean),
    };
    const score = scoreSection(faux, qTokens, phrase);
    if (score > 0) scored.push({ section: faux, score, job: row });
  }
  scored.sort((a, z) => z.score - a.score);
  const top = scored.slice(0, 6);
  const best = top[0]?.score || 1;
  return {
    jobs: top.map((m) => m.job),
    matches: top.map((m) => ({ section: m.section, score: Math.min(1, m.score / best) })),
    intent: null,
    usd: 0,
    source: "local",
  };
}

/**
 * POST /ask (12 s). Resolves to {jobs, matches, intent, usd, source}. `jobs` is empty when
 * the question is out of the manual's scope — that is an answer, not a failure. On a
 * network fault it degrades to the local keyword search and reports source:"local".
 */
export async function ask(manualOrBikeId, query) {
  await loadCatalog();
  if (mode === "local") return localJobAsk(manualOrBikeId, query);
  const made = await manual(manualOrBikeId).catch(() => undefined);
  const target = made ?? (await manualForBike(manualOrBikeId));
  if (!target) return { jobs: [], matches: [], intent: null, usd: 0, source: "none" };

  const asBike = bike(manualOrBikeId) ? String(manualOrBikeId) : target.bikeId;
  const byId = new Map(jobsOfManual(target, asBike).map((j) => [j.sectionId, j]));
  const shape = (matches, intent, usd, source) => ({
    jobs: matches.map((m) => byId.get(m.section.id)).filter(Boolean),
    matches,
    intent: intent ?? null,
    usd: usd ?? 0,
    source,
  });

  if (mode === "remote") {
    try {
      const body = await http("/ask", { method: "POST", json: { manualId: target.id, query: String(query ?? "") }, ms: ASK_MS });
      return shape(body.matches ?? [], body.intent, body.usd, "api");
    } catch {
      /* fall through to the local index */
    }
  }
  return shape(localMatches(target, query), null, 0, "local");
}

// ---------------------------------------------------------------- identify

function withBike(candidates) {
  return (candidates ?? [])
    .map((c) => ({ bikeId: c.bikeId, bike: bike(c.bikeId), confidence: c.confidence }))
    .filter((c) => c.bike);
}

export async function identifyPhoto(file) {
  await loadCatalog();
  if (mode !== "remote" || !file) return [];
  const form = new FormData();
  form.append("file", file, file.name || "photo.jpg");
  const body = await quiet("/identify/photo", { method: "POST", form, ms: 45000 }, null);
  return body ? withBike(body.candidates) : [];
}

export async function identifyVin(vin) {
  await loadCatalog();
  const empty = { bike: null, candidates: [] };
  if (mode !== "remote" || !vin) return empty;
  const body = await quiet("/identify/vin", { method: "POST", json: { vin: String(vin) }, ms: 20000 }, null);
  if (!body) return empty;
  return { bike: body.bike ? (bike(body.bike.id) ?? body.bike) : null, candidates: withBike(body.candidates) };
}

export function partPhrase(label) {
  const key = String(label ?? "");
  return PART_PHRASE[key] ?? key.replace(/_/g, " ");
}

export async function identifyPart(file) {
  await loadCatalog();
  if (mode !== "remote" || !file) return [];
  const form = new FormData();
  form.append("file", file, file.name || "part.jpg");
  const rows = await quiet("/identify/part", { method: "POST", form, ms: 45000 }, []);
  return (rows ?? []).map((r) => ({ label: r.label, confidence: r.confidence, phrase: partPhrase(r.label) }));
}

// ---------------------------------------------------------------- ingest

function report(onProgress, patch) {
  if (typeof onProgress === "function") {
    try {
      onProgress(patch);
    } catch {
      /* a screen throwing must not stop the poll */
    }
  }
}

async function pollJob(jobId, onProgress, title) {
  const deadline = Date.now() + INGEST_MAX_MS;
  let last = null;
  while (Date.now() < deadline) {
    const job = await quiet(`/ingest/${encodeURIComponent(jobId)}`, { ms: 10000 }, null);
    if (job) {
      last = job;
      report(onProgress, { status: job.status, done: job.done ?? 0, pages: job.pages ?? 0, title });
      if (job.status === "done") return job;
      if (job.status === "error") throw new Error(job.error || "ingest failed");
    }
    await sleep(INGEST_POLL_MS);
  }
  throw new Error(`ingest timed out (last status ${last?.status ?? "unknown"})`);
}

/**
 * A finished job can publish the manual before the LLM pass fills `sections` — the outline
 * is there first. Poll until sections arrive or 3 minutes pass; return whatever we have.
 */
async function waitForSections(manualId, onProgress, title) {
  const deadline = Date.now() + SECTIONS_MAX_MS;
  let made = await manual(manualId, { fresh: true });
  while (Date.now() < deadline && (!made || !made.sections.length)) {
    report(onProgress, { status: "structuring", done: made?.toc?.length ?? 0, pages: made?.pages ?? 0, title });
    await sleep(SECTIONS_POLL_MS);
    made = await manual(manualId, { fresh: true });
  }
  return made;
}

function adoptManual(bikeId, manualId) {
  const hit = bike(bikeId);
  if (hit && manualId) hit.manualId = manualId;
}

/**
 * Index a manual. `fileOrUrl` is a File/Blob (POST /ingest/upload, multipart) or a URL
 * string (POST /ingest, json). meta = {make, model, year, market}. onProgress gets
 * {status, done, pages, title} about once a second. Resolves to the mapped manual.
 */
export async function ingest(fileOrUrl, meta = {}, onProgress) {
  await loadCatalog();
  if (mode !== "remote") throw new Error("ingest needs the API");
  const make = String(meta.make ?? "");
  const model = String(meta.model ?? "");
  const year = Number(meta.year ?? 0);
  const market = String(meta.market ?? "EU");
  if (!make || !model || !year) throw new Error("ingest needs make, model and year");
  const title = meta.title ?? `${make} ${model} ${year}`;

  let job;
  if (typeof fileOrUrl === "string") {
    job = await http("/ingest", { method: "POST", json: { url: fileOrUrl, make, model, year, market }, ms: 30000 });
  } else if (fileOrUrl) {
    // FastAPI declares make/model/year/market next to File(...), so they are QUERY params.
    const qs = new URLSearchParams({ make, model, year: String(year), market });
    const form = new FormData();
    form.append("file", fileOrUrl, fileOrUrl.name || "manual.pdf");
    job = await http(`/ingest/upload?${qs}`, { method: "POST", form, ms: 180000 });
  } else {
    throw new Error("ingest needs a file or a url");
  }

  report(onProgress, { status: job.status, done: 0, pages: 0, title });
  await pollJob(job.id, onProgress, title);
  const made = await waitForSections(job.manualId, onProgress, title);
  if (made) {
    adoptManual(made.bikeId, made.id);
    if (!manualSummaries.some((m) => m && m.id === made.id)) {
      manualSummaries = [...manualSummaries, { id: made.id, title: made.title, bikeIds: made.bikeIds, pages: made.pages, sections: made.sections.length }];
    }
    report(onProgress, { status: "done", done: made.pages, pages: made.pages, title: made.title });
  }
  return made;
}

/**
 * Index-on-demand for a bike whose official PDF we know but have not processed
 * (manualState === "ondemand"). POST /manuals/ensure {bikeId, vin?} ->
 * {status:"ready"|"running"|"none", manualId, jobId?, done?, pages?}. `opts.vin` is the VIN
 * the bike was identified by (bus state.vin); it is sent only when present, so the API can
 * pin the market variant. When the endpoint is not deployed yet we fall back to POST /ingest
 * with the bike's manualUrl, which is the same pipeline. Resolves to the mapped manual, or
 * null when nothing can be indexed.
 */
export async function ensureManual(bikeId, onProgress, opts) {
  await loadCatalog();
  const hit = bike(bikeId);
  if (!hit) return null;
  if (hit.manualId) return manual(hit.manualId);
  if (!hit.manualUrl && mode !== "remote") return null; // nothing to index, and no API anyway
  if (mode !== "remote") throw new Error("indexing a manual needs the API");
  const title = `${hit.make} ${hit.model} ${hit.year}`;
  const vin = typeof opts?.vin === "string" && opts.vin.trim() ? opts.vin.trim().toUpperCase() : null;

  let body = null;
  try {
    const json = vin ? { bikeId: hit.id, vin } : { bikeId: hit.id };
    body = await http("/manuals/ensure", { method: "POST", json, ms: 30000 });
  } catch (err) {
    if (err?.status !== 404 && err?.status !== 405) throw err;
    if (!hit.manualUrl) return null;
    report(onProgress, { status: "queued", done: 0, pages: 0, title });
    return ingest(hit.manualUrl, { make: hit.make, model: hit.model, year: hit.year, market: hit.market }, onProgress);
  }

  if (!body || body.status === "none") {
    report(onProgress, { status: "none", reason: body?.reason ?? "no free manual known", done: 0, pages: 0, title });
    return null;
  }
  report(onProgress, { status: body.status, done: body.done ?? 0, pages: body.pages ?? 0, title });

  if (body.status === "ready" && body.manualId) {
    adoptManual(hit.id, body.manualId);
    return manual(body.manualId);
  }
  if (body.jobId) await pollJob(body.jobId, onProgress, title);
  const made = await waitForSections(body.manualId, onProgress, title);
  if (made) adoptManual(hit.id, made.id);
  return made ?? null;
}

// ---------------------------------------------------------------- ops

export async function cost() {
  await loadCatalog();
  if (mode !== "remote") return null;
  return quiet("/cost", { ms: 15000 }, null);
}

export async function voiceConfig() {
  await loadCatalog();
  if (mode !== "remote") return { elevenlabsAgentId: null, deepgram: false };
  return quiet("/voice/config", { ms: 10000 }, { elevenlabsAgentId: null, deepgram: false });
}

export async function deepgramToken() {
  await loadCatalog();
  if (mode !== "remote") return null;
  return quiet("/voice/deepgram-token", { method: "POST", ms: 20000 }, null);
}

