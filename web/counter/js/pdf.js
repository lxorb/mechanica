/**
 * pdf.js — pdf.js from a CDN, rendered to canvas at devicePixelRatio (capped at 2),
 * with an LRU of rasterised sheets so a page that scrolls back into view is instant.
 * Owner: reader agent (book).
 */

const PDFJS_SRC = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.min.mjs";
const PDFJS_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.worker.min.mjs";
const PDFJS_FONTS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/standard_fonts/";
const PDFJS_CMAPS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/cmaps/";

const MAX_DPR = 2;
const MAX_SHEETS = 12;
export const DEFAULT_RATIO = 1.4142;

let pdfjsMod = null;
let pdfjsLoading = null;

const docs = new Map();
const ratios = new Map();
const sheets = new Map();
const jobs = new Map();
const wanted = new WeakMap();

/**
 * One record per manual file: "idle" | "loading" | "ready" | "failed", plus the bytes pdf.js
 * reports while the file comes down. The reader draws its progress ring straight off this, so
 * a manual that is still downloading looks like a download and not like a broken page.
 */
const states = new Map();
const watchers = new Map();

export function docStatus(url) {
  return states.get(url) || { status: "idle", loaded: 0, total: 0 };
}

function setStatus(url, patch) {
  const next = Object.assign(docStatus(url), patch);
  states.set(url, next);
  const set = watchers.get(url);
  if (set) for (const fn of [...set]) fn(next);
}

/** Subscribe to a file's load state. Fires once immediately; returns the unsubscribe. */
export function onDoc(url, fn) {
  if (!url || typeof fn !== "function") return () => {};
  let set = watchers.get(url);
  if (!set) watchers.set(url, (set = new Set()));
  set.add(fn);
  fn(docStatus(url));
  return () => set.delete(fn);
}

/** Drop a failed document so the next getDocument() retries it from scratch. */
export function forget(url) {
  docs.delete(url);
  states.delete(url);
  for (const key of [...sheets.keys()]) if (key.startsWith(`${url}|`)) sheets.delete(key);
  setStatus(url, { status: "idle", loaded: 0, total: 0 });
}

function dpr() {
  const raw = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  return Math.min(raw, MAX_DPR);
}

function sheetKey(url, page, cssWidth) {
  return `${url}|${page}|${Math.round(cssWidth)}|${dpr()}`;
}

function remember(url, page, ratio) {
  ratios.set(`${url}|${page}`, ratio);
  if (!ratios.has(url)) ratios.set(url, ratio);
  return ratio;
}

function loadPdfjs() {
  if (pdfjsMod) return Promise.resolve(pdfjsMod);
  if (!pdfjsLoading) {
    pdfjsLoading = import(PDFJS_SRC)
      .then((mod) => {
        mod.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        pdfjsMod = mod;
        return mod;
      })
      .catch((err) => {
        pdfjsLoading = null;
        throw err;
      });
  }
  return pdfjsLoading;
}

export function getDocument(url) {
  const open = docs.get(url);
  if (open) return open;
  setStatus(url, { status: "loading", loaded: 0, total: 0 });
  const job = loadPdfjs().then((pdfjs) => {
    const task = pdfjs.getDocument({
      url,
      withCredentials: false,
      standardFontDataUrl: PDFJS_FONTS,
      cMapUrl: PDFJS_CMAPS,
      cMapPacked: true,
    });
    // pdf.js only reports a total when the server sends Content-Length; without one the
    // reader shows the indeterminate ring rather than inventing a percentage.
    task.onProgress = ({ loaded, total }) => {
      if (docs.get(url) !== job) return;
      setStatus(url, { status: "loading", loaded: Number(loaded) || 0, total: Number(total) || 0 });
    };
    return task.promise;
  });
  docs.set(url, job);
  job.then(
    () => setStatus(url, { status: "ready" }),
    () => {
      docs.delete(url);
      setStatus(url, { status: "failed" });
    },
  );
  return job;
}

export function cachedRatio(url, page) {
  return ratios.get(`${url}|${page}`) ?? ratios.get(url) ?? DEFAULT_RATIO;
}

export async function pageRatio(url, page) {
  const hit = ratios.get(`${url}|${page}`);
  if (hit) return hit;
  const doc = await getDocument(url);
  const view = (await doc.getPage(page)).getViewport({ scale: 1 });
  return remember(url, page, view.height / view.width);
}

export async function pageCount(url) {
  const doc = await getDocument(url);
  return doc.numPages;
}

function trim() {
  for (const key of sheets.keys()) {
    if (sheets.size <= MAX_SHEETS) break;
    const stale = sheets.get(key);
    if (stale) {
      stale.width = 0;
      stale.height = 0;
    }
    sheets.delete(key);
  }
}

function rasterize(url, page, cssWidth) {
  const key = sheetKey(url, page, cssWidth);
  const hit = sheets.get(key);
  if (hit) {
    sheets.delete(key);
    sheets.set(key, hit);
    return Promise.resolve(hit);
  }
  const running = jobs.get(key);
  if (running) return running;

  const job = (async () => {
    const doc = await getDocument(url);
    const proxy = await doc.getPage(page);
    const base = proxy.getViewport({ scale: 1 });
    remember(url, page, base.height / base.width);
    const viewport = proxy.getViewport({ scale: (Math.round(cssWidth) * dpr()) / base.width });
    const sheet = document.createElement("canvas");
    sheet.width = Math.round(viewport.width);
    sheet.height = Math.round(viewport.height);
    const ctx = sheet.getContext("2d", { alpha: false });
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, sheet.width, sheet.height);
    await proxy.render({ canvasContext: ctx, canvas: sheet, viewport }).promise;
    sheets.set(key, sheet);
    trim();
    return sheet;
  })();

  jobs.set(key, job);
  job.then(
    () => jobs.delete(key),
    () => jobs.delete(key),
  );
  return job;
}

export function preloadPage(url, page, cssWidth) {
  if (!url || !page || !(cssWidth > 0)) return Promise.resolve(null);
  return rasterize(url, page, cssWidth).catch(() => null);
}

export async function renderPage(url, page, cssWidth, canvas) {
  const key = sheetKey(url, page, cssWidth);
  wanted.set(canvas, key);
  const sheet = await rasterize(url, page, cssWidth);
  if (wanted.get(canvas) !== key) return false;
  canvas.width = sheet.width;
  canvas.height = sheet.height;
  canvas.getContext("2d", { alpha: false })?.drawImage(sheet, 0, 0);
  return true;
}

export function releaseCanvas(canvas) {
  if (!canvas) return;
  wanted.set(canvas, "");
  canvas.width = 0;
  canvas.height = 0;
}
