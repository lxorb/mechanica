/**
 * Remote Query layer adapter — same function names as query.js, backed by /api/*.
 * Lookups that hit /api/* are async (fetch). pageUrl / thumbUrl / asset are sync
 * and use the same path rules as query.js. loadCatalog fetches GET /api/catalog
 * and resolves true; catalog() then returns {bikes, systems, parts, manuals}
 * (no jobs) so Q.catalog()?.bikes works for Identify.
 *
 * On 503 or network failure, list helpers return [] and single-record helpers
 * return undefined — they never throw. Do not import this from query.js.
 *
 * Later integration switch (counter/js/app.js, not this task):
 *   const query = (await import("./store-remote.js").then((m) => m.isRemoteAvailable()).then((ok) => ok ? import("./store-remote.js") : import("./query.js")));
 */

const API = "/api";
const DEFAULT_PAGES_DIR = (manualId) => `store/manuals/${manualId}/pages/`;

function padPage(n) {
  return String(n).padStart(4, "0");
}

function pagesDirOf(manualId) {
  return DEFAULT_PAGES_DIR(manualId);
}

export function asset(path) {
  if (path == null || path === "") return path;
  const value = String(path);
  if (/^(?:[a-z]+:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)) return value;
  if (value.startsWith("/") || value.startsWith("../")) return value;
  return `../${value.replace(/^\.\//, "")}`;
}

export function pageUrl(manualId, n) {
  return asset(`${pagesDirOf(manualId)}p-${padPage(n)}.webp`);
}

export function thumbUrl(manualId, n) {
  return asset(`${pagesDirOf(manualId)}t-${padPage(n)}.webp`);
}

const EMPTY_CATALOG = Object.freeze({
  bikes: [],
  systems: [],
  parts: [],
  manuals: [],
});

let cachedCatalog;
let loadPromise;

function catalogShape(body) {
  if (!body || typeof body !== "object") return { ...EMPTY_CATALOG };
  return {
    bikes: Array.isArray(body.bikes) ? body.bikes : [],
    systems: Array.isArray(body.systems) ? body.systems : [],
    parts: Array.isArray(body.parts) ? body.parts : [],
    manuals: Array.isArray(body.manuals) ? body.manuals : [],
  };
}

export async function loadCatalog(_url) {
  if (!loadPromise) {
    loadPromise = (async () => {
      cachedCatalog = catalogShape(await api(`${API}/catalog`));
      return true;
    })().catch(() => {
      cachedCatalog = { ...EMPTY_CATALOG };
      loadPromise = undefined;
      return true;
    });
  }
  return loadPromise;
}

export function catalog() {
  return cachedCatalog;
}

function emptyFor(list) {
  return list ? [] : undefined;
}

async function api(path, { list = false } = {}) {
  const fallback = emptyFor(list);
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (res.status === 503) {
      try {
        await res.json();
      } catch {
        /* ignore */
      }
      return fallback;
    }
    if (res.status === 404) return fallback;
    if (!res.ok) return fallback;
    const body = await res.json();
    if (list) return Array.isArray(body) ? body : [];
    return body;
  } catch {
    return fallback;
  }
}

export async function isRemoteAvailable() {
  try {
    const res = await fetch(`${API}/bikes?q=`, { headers: { Accept: "application/json" } });
    if (!res.ok) return false;
    const body = await res.json();
    return Array.isArray(body);
  } catch {
    return false;
  }
}

export async function findBikes(text) {
  const q = encodeURIComponent(text ?? "");
  const rows = await api(`${API}/bikes?q=${q}`, { list: true });
  return Array.isArray(rows) ? rows : [];
}

export async function bike(id) {
  if (id == null || id === "") return undefined;
  return api(`${API}/bikes/${encodeURIComponent(id)}`);
}

export async function manual(id) {
  if (id == null || id === "") return undefined;
  const bikes = await findBikes("");
  const row = bikes.find((b) => b?.manualId === id || b?.manual?.id === id);
  return row?.manual;
}

export async function systems(bikeId) {
  if (bikeId == null || bikeId === "") return [];
  const rows = await api(`${API}/bikes/${encodeURIComponent(bikeId)}/systems`, { list: true });
  return Array.isArray(rows) ? rows : [];
}

export async function partsFor(bikeId, systemId) {
  if (bikeId == null || bikeId === "") return [];
  const q = systemId ? `?system=${encodeURIComponent(systemId)}` : "";
  const rows = await api(`${API}/bikes/${encodeURIComponent(bikeId)}/parts${q}`, { list: true });
  return Array.isArray(rows) ? rows : [];
}

export async function part(id) {
  if (id == null || id === "") return undefined;
  return api(`${API}/parts/${encodeURIComponent(id)}`);
}

export async function job(bikeId, partId) {
  if (bikeId == null || partId == null || bikeId === "" || partId === "") return undefined;
  return api(`${API}/jobs/${encodeURIComponent(bikeId)}/${encodeURIComponent(partId)}`);
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
  if (id == null || id === "") return undefined;
  const parts = splitJobId(id);
  if (!parts) return undefined;
  return job(parts[0], parts[1]);
}
