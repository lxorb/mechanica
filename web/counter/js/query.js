import { buildIndex, search as instantSearch, highlight } from "./search.js";

const DEFAULT_URL = "../store/catalog.json";
const DEFAULT_COLLECTION_URL = "../store/collection.json";
const TOP_KEYS = ["bikes", "manuals", "systems", "parts", "jobs"];

let loadPromise;
let data = null;
let roster = [];
let bikeIndex = new Map();
let manualIndex = new Map();
let systemIndex = new Map();
let partIndex = new Map();
let jobIndex = new Map();

export { highlight };

function resetIndexes() {
  bikeIndex = new Map();
  manualIndex = new Map();
  systemIndex = new Map();
  partIndex = new Map();
  jobIndex = new Map();
  roster = [];
  buildIndex([]);
}

function indexRows(rows, key) {
  const next = new Map();
  for (const row of rows) {
    if (!row || typeof row !== "object" || typeof row.id !== "string") {
      throw new Error(`loadCatalog: ${key} row is missing a string id`);
    }
    next.set(row.id, row);
  }
  return next;
}

function mergeBikes(collectionBikes, catalogBikes) {
  const catalogById = new Map();
  for (const row of catalogBikes) {
    if (row && typeof row === "object" && typeof row.id === "string") catalogById.set(row.id, row);
  }
  const seen = new Set();
  const out = [];
  const source = Array.isArray(collectionBikes) ? collectionBikes : [];
  for (const row of source) {
    if (!row || typeof row !== "object" || typeof row.id !== "string") continue;
    seen.add(row.id);
    const over = catalogById.get(row.id);
    out.push(over ? { ...row, ...over } : row);
  }
  for (const row of catalogBikes) {
    if (!row || typeof row !== "object" || typeof row.id !== "string") continue;
    if (!seen.has(row.id)) out.push(row);
  }
  return out;
}

function indexCatalog(catalog, mergedBikes) {
  const nextBikes = indexRows(mergedBikes, "bikes");
  const nextManuals = indexRows(catalog.manuals, "manuals");
  const nextSystems = indexRows(catalog.systems, "systems");
  const nextParts = indexRows(catalog.parts, "parts");
  const nextJobs = indexRows(catalog.jobs, "jobs");
  bikeIndex = nextBikes;
  manualIndex = nextManuals;
  systemIndex = nextSystems;
  partIndex = nextParts;
  jobIndex = nextJobs;
  roster = mergedBikes;
  buildIndex(mergedBikes);
}

function validateCatalog(catalog) {
  if (!catalog || typeof catalog !== "object") {
    throw new Error("loadCatalog: catalog is not an object");
  }
  for (const key of TOP_KEYS) {
    if (!(key in catalog)) throw new Error(`loadCatalog: missing ${key}`);
    if (!Array.isArray(catalog[key])) throw new Error(`loadCatalog: ${key} is not an array`);
  }
}

function padPage(n) {
  return String(n).padStart(4, "0");
}

function pagesDirOf(manualId) {
  const dir = manualIndex.get(manualId)?.pagesDir;
  if (dir) {
    const value = String(dir);
    return value.endsWith("/") ? value : `${value}/`;
  }
  return `store/manuals/${manualId}/pages/`;
}

function textDirOf(manualId) {
  const dir = manualIndex.get(manualId)?.textDir;
  if (dir) {
    const value = String(dir);
    return value.endsWith("/") ? value : `${value}/`;
  }
  return `store/manuals/${manualId}/text/`;
}

function fetchCollection(url) {
  return fetch(url)
    .then((res) => {
      if (!res.ok) return null;
      return res.json().then((json) => {
        if (!json || !Array.isArray(json.bikes)) return null;
        return json.bikes;
      });
    })
    .catch(() => null);
}

export function asset(path) {
  if (path == null || path === "") return path;
  const value = String(path);
  if (/^(?:[a-z]+:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)) return value;
  if (value.startsWith("/") || value.startsWith("../")) return value;
  return `../${value.replace(/^\.\//, "")}`;
}

export function loadCatalog(url = DEFAULT_URL, collectionUrl = DEFAULT_COLLECTION_URL) {
  if (!loadPromise) {
    loadPromise = fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`loadCatalog: ${res.status} ${url}`);
        return res.json();
      })
      .then((catalog) => {
        validateCatalog(catalog);
        return fetchCollection(collectionUrl).then((collectionBikes) => {
          const merged = mergeBikes(collectionBikes ?? catalog.bikes, catalog.bikes);
          indexCatalog(catalog, merged);
          data = catalog;
          return catalog;
        });
      })
      .catch((err) => {
        data = null;
        resetIndexes();
        loadPromise = undefined;
        throw err;
      });
  }
  return loadPromise;
}

export function catalog() {
  return data;
}

export function bikes() {
  return roster;
}

export function findBikes(text, opts) {
  return instantSearch(text, opts);
}

export function bike(id) {
  return bikeIndex.get(id);
}

export function hasManual(id) {
  const rec = bikeIndex.get(id);
  return !!(rec && rec.manualId);
}

export function manual(id) {
  return manualIndex.get(id);
}

export function part(id) {
  return partIndex.get(id);
}

export function jobById(id) {
  return jobIndex.get(id);
}

export function job(bikeId, partId) {
  return (data?.jobs ?? []).find((row) => row.bikeId === bikeId && row.partId === partId);
}

export function systems(bikeId) {
  const wanted = new Set();
  for (const row of data?.jobs ?? []) {
    if (row.bikeId !== bikeId) continue;
    const p = partIndex.get(row.partId);
    if (p?.systemId) wanted.add(p.systemId);
  }
  return (data?.systems ?? []).filter((row) => wanted.has(row.id));
}

export function partsFor(bikeId, systemId) {
  const wanted = new Set();
  for (const row of data?.jobs ?? []) {
    if (row.bikeId !== bikeId) continue;
    const p = partIndex.get(row.partId);
    if (p?.systemId === systemId) wanted.add(p.id);
  }
  return (data?.parts ?? []).filter((row) => wanted.has(row.id));
}

export function pageUrl(manualId, n) {
  return asset(`${pagesDirOf(manualId)}p-${padPage(n)}.webp`);
}

export function thumbUrl(manualId, n) {
  return asset(`${pagesDirOf(manualId)}t-${padPage(n)}.webp`);
}

export function pageTextUrl(manualId, n) {
  return asset(`${textDirOf(manualId)}p-${padPage(n)}.txt`);
}
