import { state, set, emit, go, back as popBack, openOverlay, registerScreen } from "../bus.js";
import * as Q from "../ttm.js";
import { loadAsk, ask, fetchJobPages, contextWindow } from "../ask.js";
import {
  cachedRatio,
  pageCount,
  pageRatio,
  preloadPage,
  renderPage,
  releaseCanvas,
} from "../pdf.js";
import { agentId as voiceAgent, start as voiceStart } from "../voice.js";

const STAGGER = 60;
const MAX_W = 900;
const ZOOM_MIN = 1;
const ZOOM_MAX = 3;
const ZOOM_DOUBLE = 2;
const TAP_MS = 320;
const TAP_PX = 28;
const TAP_HOLD = 500;
const NEAR = "120% 0px";
const SVG = "http://www.w3.org/2000/svg";
const DRAW_MS = 70;
/** Above this many sheets the column is virtualised: far canvases are handed back. */
const VIRTUAL_MIN = 12;
const MODE_KEY = "hb.pages.";

/* ---------- module state ---------- */

let rootEl = null;
let coverEl = null;
let titleEl = null;
let stampEl = null;
let backBtn = null;
let modeBtn = null;
let partsBtn = null;
let micBtn = null;
let askBtn = null;
let barEl = null;
let viewEl = null;
let padEl = null;
let colEl = null;
let stripEl = null;
let outlineEl = null;
let askSheet = null;
let askInput = null;
let askBar = null;
let askBarFill = null;
let askHits = null;

let jobRec = null;
let manualRec = null;
let hasThumb = false;
let fileUrl = "";
let outline = [];
let marks = new Map();
let readList = [];
let totalPages = 0;
let mode = "relevant";
let pages = [];
let sheets = new Map();
let chips = new Map();
let visited = new Set();
let ratios = new Map();
let baseRatio = 1.4142;
let sheetW = 0;
let current = null;
let enterGen = 0;
let nearIo = null;
let seenIo = null;
let ro = null;
let seenAmount = new Map();
let drawTimer = 0;

let zoom = ZOOM_MIN;
let zoomW = 0;
let pinch0 = 0;
let pinchBase = ZOOM_MIN;
let tapAt = 0;
let tapX = 0;
let tapY = 0;
let downX = 0;
let downY = 0;
let downAt = 0;
let touchAt = 0;
let tapTimer = 0;
let immersive = false;

let voiceId = null;
let session = null;
let askPages = [];
let askFetchTok = 0;
let askRunTok = 0;
let askBusy = false;
let askFlashTimer = 0;

/* ---------- small helpers ---------- */

function el(tag, attrs) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
  }
  return node;
}

function glyph(width, ...ds) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of ds) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", String(width));
    path.setAttribute("stroke-linecap", "square");
    path.setAttribute("stroke-linejoin", "miter");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function bounce(id) {
  queueMicrotask(() => go(id));
}

/* ---------- manual shape ---------- */

function outlineNodes(manual) {
  if (Array.isArray(manual.outline) && manual.outline.length) return manual.outline;
  return (Array.isArray(manual.toc) ? manual.toc : [])
    .map((row) => ({
      title: String(row && row.title ? row.title : ""),
      page: Number(row && row.page),
      children: (row && row.children) || null,
    }))
    .filter((row) => row.title && Number.isFinite(row.page));
}

function flatten(nodes, depth, out) {
  for (const node of nodes || []) {
    const page = Number(node.page);
    if (node.title && Number.isFinite(page)) out.push({ title: node.title, page, depth });
    if (node.children) flatten(node.children, depth + 1, out);
  }
  return out;
}

function trailFor(nodes, page) {
  let best = [];
  const walk = (list, path) => {
    for (const node of list || []) {
      if (Number(node.page) > page) continue;
      const next = [...path, node.title];
      best = next;
      if (node.children) walk(node.children, next);
    }
  };
  walk(nodes, []);
  return best;
}

function readingPages(job) {
  const out = [];
  const seen = new Set();
  const add = (raw) => {
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0 || seen.has(n)) return;
    seen.add(n);
    out.push(n);
  };
  const own = (job.pages || []).map(Number).filter(Number.isFinite).sort((a, z) => a - z);
  for (const n of own) add(n);
  for (const row of job.related || []) add(row && typeof row === "object" ? row.page : row);
  return out;
}

function markMap(job) {
  const map = new Map();
  for (const h of job.highlights || []) {
    const n = Number(h && h.page);
    if (!Number.isFinite(n)) continue;
    const list = map.get(n);
    if (list) list.push(h);
    else map.set(n, [h]);
  }
  return map;
}

function ratioOf(n) {
  return ratios.get(n) || baseRatio;
}

/* ---------- build ---------- */

function build(root) {
  rootEl = root;
  root.replaceChildren();

  barEl = el("header", { class: "book-bar" });

  backBtn = el("button", { class: "bar-btn bar-back", type: "button", "aria-label": "Back", text: "←" });
  coverEl = el("button", { class: "bar-btn book-cover", type: "button", "aria-label": "Contents" });
  coverEl.append(el("img", { width: "24", height: "30", alt: "", loading: "lazy", decoding: "async" }));
  titleEl = el("p", { class: "book-title" });
  stampEl = el("span", { class: "book-stamp" });

  modeBtn = el("button", {
    class: "bar-btn bar-word book-all",
    type: "button",
    "aria-pressed": "false",
    "aria-label": "All pages",
    text: "All",
    hidden: true,
  });
  micBtn = el("button", {
    class: "bar-btn book-mic",
    type: "button",
    "aria-label": "Voice",
    "aria-pressed": "false",
    hidden: true,
  });
  micBtn.append(
    glyph(2.4, "M9 4.5a3 3 0 0 1 6 0V11a3 3 0 0 1-6 0Z", "M5 11a7 7 0 0 0 14 0", "M12 18v2.5"),
  );
  askBtn = el("button", { class: "bar-btn book-ask", type: "button", "aria-label": "Ask", hidden: true });
  askBtn.append(
    glyph(2.4, "M15 15 20 20", "M8.4 8.6c0-1.1.9-1.9 1.8-1.9s1.8.8 1.8 1.8c0 1.1-1.8 1.3-1.8 2.6", "M10.2 14.6v.2"),
  );
  const lens = document.createElementNS(SVG, "circle");
  lens.setAttribute("cx", "10");
  lens.setAttribute("cy", "10");
  lens.setAttribute("r", "6");
  lens.setAttribute("fill", "none");
  lens.setAttribute("stroke", "currentColor");
  lens.setAttribute("stroke-width", "2.4");
  askBtn.querySelector("svg").append(lens);

  partsBtn = el("button", {
    class: "bar-btn bar-word book-parts",
    type: "button",
    "aria-label": "Parts",
    text: "Parts",
  });

  barEl.append(backBtn, coverEl, titleEl, stampEl, modeBtn, micBtn, askBtn, partsBtn);

  viewEl = el("div", { class: "page-view" });
  padEl = el("div", { class: "page-pad" });
  colEl = el("div", { class: "page-col" });
  padEl.append(colEl);
  viewEl.append(padEl);

  stripEl = el("nav", { class: "page-strip", "aria-label": "Pages" });
  outlineEl = el("div", { class: "book-outline", hidden: true });

  askSheet = el("div", { class: "sheet ask-sheet", hidden: true, role: "dialog", "aria-label": "Ask" });
  askInput = el("input", {
    class: "ask-q",
    type: "search",
    placeholder: "torque",
    autocomplete: "off",
    enterkeyhint: "search",
  });
  askBar = el("div", { class: "ask-bar", hidden: true });
  askBarFill = el("i");
  askBar.append(askBarFill);
  askHits = el("div", { class: "ask-hits" });
  askSheet.append(askInput, askBar, askHits);

  root.append(barEl, viewEl, stripEl, outlineEl, askSheet);

  backBtn.addEventListener("click", onBack);
  coverEl.addEventListener("click", onContents);
  modeBtn.addEventListener("click", toggleMode);
  partsBtn.addEventListener("click", () => openOverlay("invoice"));
  micBtn.addEventListener("click", onMic);
  askBtn.addEventListener("click", onAskToggle);
  askInput.addEventListener("keydown", onAskKey);
  window.addEventListener("keydown", onEsc);
  window.addEventListener("resize", measure);

  viewEl.addEventListener("touchstart", onTouchStart, { passive: true });
  viewEl.addEventListener("touchmove", onTouchMove, { passive: false });
  viewEl.addEventListener("touchend", onTouchEnd, { passive: false });
  viewEl.addEventListener("wheel", onWheel, { passive: false });
  viewEl.addEventListener("dblclick", onDouble);
  viewEl.addEventListener("click", onClick);

  ro = new ResizeObserver(() => measure());
  ro.observe(viewEl);
}

/** Same step as the shell's header Back: this screen's own layers first, then history. */
function onBack() {
  popBack();
}

/* ---------- immersive ---------- */

function setImmersive(on) {
  immersive = Boolean(on);
  if (rootEl) rootEl.classList.toggle("immersive", immersive);
  emit("substate", { screen: "book", on: immersive });
  measure();
}

function toggleImmersive() {
  if (askSheet && !askSheet.hidden) {
    closeAsk();
    return;
  }
  setImmersive(!immersive);
}

function armTap() {
  if (tapTimer) window.clearTimeout(tapTimer);
  tapTimer = window.setTimeout(() => {
    tapTimer = 0;
    toggleImmersive();
  }, TAP_MS + 40);
}

function cancelTap() {
  if (!tapTimer) return;
  window.clearTimeout(tapTimer);
  tapTimer = 0;
}

/* ---------- page mode ---------- */

function readMode(manualId) {
  try {
    return window.localStorage.getItem(MODE_KEY + manualId) === "all" ? "all" : "relevant";
  } catch {
    return "relevant";
  }
}

function writeMode(manualId, value) {
  try {
    window.localStorage.setItem(MODE_KEY + manualId, value);
  } catch {
    /* private mode: the toggle still works, it just does not stick */
  }
}

function allList() {
  const n = Number(totalPages) || 0;
  if (n <= 0) return readList.slice();
  const out = [];
  for (let p = 1; p <= n; p++) out.push(p);
  return out;
}

function nearestRelevant(n) {
  if (!readList.length) return null;
  if (n == null) return readList[0];
  let best = readList[0];
  for (const p of readList) if (Math.abs(p - n) < Math.abs(best - n)) best = p;
  return best;
}

function paintModeBtn() {
  const on = mode === "all";
  modeBtn.hidden = !(totalPages > 1 && readList.length > 0);
  modeBtn.setAttribute("aria-pressed", on ? "true" : "false");
  modeBtn.classList.toggle("is-on", on);
}

function toggleMode() {
  if (!(totalPages > 1)) return;
  const at = current;
  mode = mode === "all" ? "relevant" : "all";
  writeMode(jobRec && jobRec.manualId, mode);
  paintModeBtn();
  if (mode === "all") setPages(allList(), { strip: readList, at: at || readList[0] });
  else setPages(readList.slice(), { strip: readList, at: nearestRelevant(at) });
}

/* ---------- paint ---------- */

async function paint(job) {
  const my = enterGen;
  jobRec = job;
  manualRec = (await Q.manual(job.manualId)) || {};
  if (my !== enterGen) return;
  fileUrl = manualRec.file ? Q.asset(manualRec.file) : "";
  outline = flatten(outlineNodes(manualRec), 0, []);
  marks = markMap(job);
  readList = readingPages(job);
  totalPages = Number(manualRec.pages) || 0;
  mode = totalPages > 1 ? readMode(job.manualId) : "relevant";

  titleEl.textContent = manualRec.title || "";
  const cover = coverEl.firstElementChild;
  const thumb = Q.thumbUrl(job.manualId, 1);
  hasThumb = Boolean(thumb);
  coverEl.classList.toggle("is-plain", !hasThumb);
  if (thumb) cover.src = thumb;
  cover.alt = manualRec.title || "";

  paintModeBtn();
  setPages(mode === "all" ? allList() : readList.slice(), {
    strip: readList,
    at: readList[0],
  });
  syncVoice(job);
  syncAsk(job);

  // A manual that never carried a page count still gets the all-pages toggle.
  if (!(totalPages > 0) && fileUrl) {
    pageCount(fileUrl)
      .then((n) => {
        if (my !== enterGen || !(n > 0)) return;
        totalPages = n;
        paintModeBtn();
        setCurrent(current || readList[0]);
      })
      .catch(() => {});
  }
}

function setPages(list, opts) {
  releaseSheets();
  pages = list;
  const stripSrc = (opts && opts.strip) || list;
  const own = new Set(list);
  const strip = stripSrc.filter((n) => own.has(n));
  visited = new Set();
  seenAmount = new Map();
  current = null;
  resetZoom();

  const empty = pages.length === 0;
  outlineEl.hidden = !empty;
  viewEl.hidden = empty;
  stripEl.hidden = empty || strip.length === 0;
  coverEl.classList.toggle("is-back", outline.length > 0);
  coverEl.hidden = !hasThumb && outline.length === 0;
  if (empty) {
    paintOutline();
    stampEl.hidden = true;
    titleEl.textContent = manualRec.title || "";
    titleEl.setAttribute("title", manualRec.title || "");
    return;
  }

  baseRatio = fileUrl ? cachedRatio(fileUrl, pages[0]) : 1.4142;
  ratios = new Map();
  paintSheets();
  paintStrip(strip);
  measure();
  observe();
  const at = opts && opts.at != null && own.has(opts.at) ? opts.at : pages[0];
  setCurrent(at);
  if (at !== pages[0]) {
    const rec = sheets.get(at);
    if (rec) rec.host.scrollIntoView({ block: "start" });
  }
  if (fileUrl) {
    pageRatio(fileUrl, pages[0])
      .then((r) => {
        baseRatio = r;
        for (const rec of sheets.values()) {
          if (!ratios.has(rec.page)) rec.host.style.aspectRatio = `1 / ${r}`;
        }
        measure();
      })
      .catch(() => {});
  }
}

function paintOutline() {
  outlineEl.replaceChildren();
  outline.forEach((entry, i) => {
    const hit = /^([\d.]+)\s+(\S.*)$/.exec(entry.title);
    const row = el("button", { class: "toc-row", type: "button" });
    row.style.paddingLeft = `${12 + entry.depth * 14}px`;
    if (entry.depth > 0) row.classList.add("sub");
    if (hit) row.append(el("b", { class: "toc-n", text: hit[1] }));
    row.append(el("span", { class: "toc-t", text: hit ? hit[2] : entry.title }));
    row.append(el("span", { class: "stamp", text: `p.${entry.page}` }));
    row.addEventListener("click", () => openChapter(i));
    outlineEl.append(row);
  });
}

function openChapter(i) {
  const here = outline[i];
  const start = here.page;
  if (mode === "all") {
    setPages(allList(), { strip: readList, at: start });
    return;
  }
  // A parent entry owns its children: the chapter ends at the next entry of the same rank.
  const after = outline
    .slice(i + 1)
    .find((entry) => entry.depth <= here.depth && entry.page > start);
  const total = Number(manualRec.pages) || start;
  const last = Math.max(start, Math.min(total, (after ? after.page : total + 1) - 1));
  const list = [];
  for (let p = start; p <= last; p++) list.push(p);
  setPages(list, { strip: list });
}

function onContents() {
  if (!outline.length) return;
  if (pages.length) setPages([]);
  else setPages(mode === "all" ? allList() : readList.slice(), { strip: readList, at: readList[0] });
}

function releaseSheets() {
  if (nearIo) nearIo.disconnect();
  if (seenIo) seenIo.disconnect();
  if (drawTimer) {
    window.clearTimeout(drawTimer);
    drawTimer = 0;
  }
  for (const rec of sheets.values()) releaseCanvas(rec.canvas);
  sheets = new Map();
  chips = new Map();
  if (colEl) colEl.replaceChildren();
  if (stripEl) stripEl.replaceChildren();
}

function paintSheets() {
  const frag = document.createDocumentFragment();
  for (const n of pages) {
    const host = el("article", { class: "page-sheet", "data-page": String(n) });
    host.style.aspectRatio = `1 / ${ratioOf(n)}`;
    const canvas = el("canvas", { class: "page-canvas" });
    const img = el("img", { class: "page-img", alt: "", decoding: "async", hidden: true });
    const box = el("div", { class: "page-marks", "aria-hidden": "true" });
    host.append(canvas, img, box);
    frag.append(host);
    const rec = {
      page: n,
      host,
      canvas,
      img,
      box,
      near: false,
      inked: false,
      failed: false,
      src: "",
      drawn: 0,
    };
    img.addEventListener("load", () => onImgLoad(rec));
    img.addEventListener("error", () => onImgError(rec));
    sheets.set(n, rec);
  }
  colEl.append(frag);
}

function paintStrip(list) {
  const frag = document.createDocumentFragment();
  for (const n of list) {
    const chip = el("button", {
      class: "strip-chip",
      type: "button",
      "data-page": String(n),
      "aria-label": `p. ${n}`,
      text: String(n),
    });
    chip.addEventListener("click", () => jump(n));
    frag.append(chip);
    chips.set(n, chip);
  }
  stripEl.append(frag);
}

function observe() {
  nearIo = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const rec = sheets.get(Number(entry.target.getAttribute("data-page")));
        if (!rec) continue;
        rec.near = entry.isIntersecting;
        if (!rec.near) drop(rec);
      }
      queueDraw();
    },
    { root: viewEl, rootMargin: NEAR },
  );

  seenIo = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        seenAmount.set(Number(entry.target.getAttribute("data-page")), entry.intersectionRatio);
      }
      let best = 0;
      let top = 0;
      for (const [page, amount] of seenAmount) {
        if (amount > best) {
          best = amount;
          top = page;
        }
      }
      if (top > 0 && top !== current) setCurrent(top);
    },
    { root: viewEl, threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] },
  );

  for (const rec of sheets.values()) {
    nearIo.observe(rec.host);
    seenIo.observe(rec.host);
  }
}

/* ---------- render ---------- */

function webpFor(n) {
  const url = Q.pageUrl(jobRec.manualId, n);
  return url ? url : "";
}

/**
 * One deferred pass over whatever is near. A fast flick through a 366-page manual fires
 * hundreds of intersections; only the sheets still near when the pass runs are rasterised.
 */
function queueDraw() {
  if (drawTimer) return;
  drawTimer = window.setTimeout(() => {
    drawTimer = 0;
    for (const rec of sheets.values()) if (rec.near) draw(rec);
  }, DRAW_MS);
}

function draw(rec) {
  if (!rec.near || !(sheetW > 0)) return;
  const url = rec.failed ? "" : webpFor(rec.page);
  if (!url) {
    drawPdf(rec);
    return;
  }
  if (rec.src === url) return;
  rec.src = url;
  rec.img.hidden = false;
  rec.img.src = url;
}

/** Hand back a sheet that scrolled far away; the aspect-ratio box keeps the scroll height. */
function drop(rec) {
  if (pages.length <= VIRTUAL_MIN) return;
  if (!rec.drawn && !rec.src && !rec.inked) return;
  releaseCanvas(rec.canvas);
  rec.drawn = 0;
  rec.host.classList.remove("is-ready");
  if (rec.src) {
    rec.img.hidden = true;
    rec.img.removeAttribute("src");
    rec.src = "";
  }
  if (rec.inked) {
    rec.box.replaceChildren();
    rec.inked = false;
  }
}

async function drawPdf(rec) {
  if (!fileUrl) return;
  const want = Math.round(sheetW);
  if (rec.drawn === want) return;
  rec.drawn = want;
  const my = enterGen;
  try {
    const r = await pageRatio(fileUrl, rec.page);
    if (my !== enterGen) return;
    if (ratios.get(rec.page) !== r) {
      ratios.set(rec.page, r);
      rec.host.style.aspectRatio = `1 / ${r}`;
    }
    if (!rec.near) {
      rec.drawn = 0;
      return;
    }
    const ok = await renderPage(fileUrl, rec.page, want, rec.canvas);
    if (my !== enterGen || !ok) return;
    if (!rec.near) {
      drop(rec);
      return;
    }
    rec.host.classList.add("is-ready");
    ink(rec);
  } catch {
    rec.drawn = 0;
  }
}

function onImgLoad(rec) {
  if (rec.img.naturalWidth && rec.img.naturalHeight) {
    const r = rec.img.naturalHeight / rec.img.naturalWidth;
    ratios.set(rec.page, r);
    rec.host.style.aspectRatio = `1 / ${r}`;
    if (rec.page === pages[0] && Math.abs(baseRatio - r) > 0.001) {
      baseRatio = r;
      measure();
    }
  }
  rec.host.classList.add("is-ready");
  ink(rec);
}

function onImgError(rec) {
  rec.failed = true;
  rec.img.hidden = true;
  rec.img.removeAttribute("src");
  rec.src = "";
  drawPdf(rec);
}

function ink(rec) {
  if (rec.inked) return;
  rec.inked = true;
  const list = marks.get(rec.page) || [];
  if (!list.length) return;
  const frag = document.createDocumentFragment();
  list.forEach((h, i) => {
    const m = el("i", { class: "mark" });
    m.style.left = `${Number(h.x) * 100}%`;
    m.style.top = `${Number(h.y) * 100}%`;
    m.style.width = `${Number(h.w) * 100}%`;
    m.style.height = `${Number(h.h) * 100}%`;
    m.style.animationDelay = `${i * STAGGER}ms`;
    frag.append(m);
  });
  rec.box.append(frag);
}

/* ---------- layout ---------- */

function measure() {
  if (!viewEl || pages.length === 0) return;
  const boxW = viewEl.clientWidth;
  const boxH = viewEl.clientHeight;
  if (boxW <= 0) return;
  const next = Math.max(
    120,
    Math.min(boxW - 8, Math.floor((boxH - 12) / baseRatio) || MAX_W, MAX_W),
  );
  if (next === sheetW) return;
  sheetW = next;
  colEl.style.setProperty("--sheet-w", `${sheetW}px`);
  for (const rec of sheets.values()) if (rec.near) draw(rec);
}

/* ---------- current page ---------- */

function setCurrent(n) {
  if (n == null) return;
  current = n;
  visited.add(n);
  for (const [page, chip] of chips) {
    const now = page === n;
    chip.classList.toggle("now", now);
    chip.classList.toggle("seen", !now && visited.has(page));
    if (now) chip.setAttribute("aria-current", "true");
    else chip.removeAttribute("aria-current");
  }
  const chip = chips.get(n);
  if (chip) {
    stripEl.scrollTo({
      left: chip.offsetLeft - stripEl.clientWidth / 2 + chip.offsetWidth / 2,
      behavior: "smooth",
    });
  }

  stampEl.hidden = false;
  stampEl.replaceChildren(
    el("span", { class: "p", text: "p." }),
    el("b", { text: String(n) }),
    el("span", { class: "m", text: `/${totalPages || pages[pages.length - 1]}` }),
  );

  const trail = trailFor(outlineNodes(manualRec), n);
  titleEl.textContent = trail.length ? trail[trail.length - 1] : manualRec.title || "";
  titleEl.setAttribute("title", trail.length ? trail.join(" · ") : manualRec.title || "");

  set({ page: n });
  emit("page", { n });

  const next = pages[pages.indexOf(n) + 1];
  if (next != null && sheetW > 0) {
    const url = webpFor(next);
    if (url) {
      const im = new Image();
      im.decoding = "async";
      im.src = url;
    } else if (fileUrl) {
      preloadPage(fileUrl, next, Math.round(sheetW));
    }
  }
}

function jump(n) {
  const rec = sheets.get(n);
  if (!rec) return;
  applyZoom(ZOOM_MIN, 0, 0);
  rec.host.scrollIntoView({ behavior: "smooth", block: "start" });
  setCurrent(n);
}

/* ---------- zoom ---------- */

function applyZoom(next, px, py) {
  if (!viewEl || !padEl || !colEl) return;
  const from = zoom;
  const to = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
  if (Math.abs(to - from) < 0.001) return;
  if (from === ZOOM_MIN) zoomW = colEl.offsetWidth;
  const rect = viewEl.getBoundingClientRect();
  const cx = (viewEl.scrollLeft + px - rect.left) / from;
  const cy = (viewEl.scrollTop + py - rect.top) / from;
  zoom = to;
  if (to === ZOOM_MIN) {
    colEl.style.transform = "";
    colEl.style.width = "";
    padEl.style.width = "";
    padEl.style.height = "";
  } else {
    colEl.style.width = `${zoomW}px`;
    colEl.style.transform = `scale(${to})`;
    padEl.style.width = `${zoomW * to}px`;
    padEl.style.height = `${colEl.offsetHeight * to}px`;
  }
  viewEl.classList.toggle("zoomed", to > ZOOM_MIN);
  viewEl.scrollLeft = cx * to - (px - rect.left);
  viewEl.scrollTop = cy * to - (py - rect.top);
}

function resetZoom() {
  if (!viewEl) return;
  const rect = viewEl.getBoundingClientRect();
  applyZoom(ZOOM_MIN, rect.left + rect.width / 2, rect.top);
}

function gap(a, b) {
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

function onTouchStart(e) {
  touchAt = Date.now();
  if (e.touches.length === 1) {
    downX = e.touches[0].clientX;
    downY = e.touches[0].clientY;
    downAt = touchAt;
    return;
  }
  cancelTap();
  if (e.touches.length !== 2) return;
  pinch0 = gap(e.touches[0], e.touches[1]);
  pinchBase = zoom;
}

function onTouchMove(e) {
  if (e.touches.length !== 2 || pinch0 <= 0) return;
  e.preventDefault();
  cancelTap();
  const now = gap(e.touches[0], e.touches[1]);
  applyZoom(
    (pinchBase * now) / pinch0,
    (e.touches[0].clientX + e.touches[1].clientX) / 2,
    (e.touches[0].clientY + e.touches[1].clientY) / 2,
  );
}

function onTouchEnd(e) {
  touchAt = Date.now();
  if (e.touches.length < 2) pinch0 = 0;
  if (e.touches.length > 0 || e.changedTouches.length !== 1) return;
  const touch = e.changedTouches[0];
  const at = Date.now();
  const still =
    Math.hypot(touch.clientX - downX, touch.clientY - downY) < TAP_PX && at - downAt < TAP_HOLD;
  if (!still) {
    cancelTap();
    tapAt = 0;
    return;
  }
  if (at - tapAt < TAP_MS && Math.hypot(touch.clientX - tapX, touch.clientY - tapY) < TAP_PX) {
    e.preventDefault();
    cancelTap();
    applyZoom(zoom > ZOOM_MIN ? ZOOM_MIN : ZOOM_DOUBLE, touch.clientX, touch.clientY);
    tapAt = 0;
    return;
  }
  tapAt = at;
  tapX = touch.clientX;
  tapY = touch.clientY;
  armTap();
}

/** Mouse only: a touch tap already ran through onTouchEnd. */
function onClick(e) {
  if (Date.now() - touchAt < 700) return;
  if (e.detail > 1) {
    cancelTap();
    return;
  }
  armTap();
}

function onWheel(e) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  cancelTap();
  applyZoom(zoom * (1 - e.deltaY / 240), e.clientX, e.clientY);
}

/** Mouse only: a double tap is already zoomed by onTouchEnd, and dblclick follows it. */
function onDouble(e) {
  cancelTap();
  if (Date.now() - touchAt < 700) return;
  applyZoom(zoom > ZOOM_MIN ? ZOOM_MIN : ZOOM_DOUBLE, e.clientX, e.clientY);
}

/* ---------- voice ---------- */

async function syncVoice(job) {
  endVoice();
  micBtn.hidden = true;
  const my = enterGen;
  voiceId = await voiceAgent();
  if (my !== enterGen || !voiceId) return;
  micBtn.hidden = false;
  const bike = Q.bike(job.bikeId);
  micBtn.dataset.bike = bike ? `${bike.make} ${bike.model} ${bike.year}` : "";
  micBtn.dataset.manual = job.manualId || "";
}

function endVoice() {
  if (session) session.end();
  session = null;
  if (micBtn) micBtn.setAttribute("aria-pressed", "false");
}

async function onMic() {
  if (session) {
    endVoice();
    return;
  }
  micBtn.setAttribute("aria-pressed", "true");
  const handle = await voiceStart({
    id: voiceId,
    dynamicVariables: {
      bike_name: micBtn.dataset.bike || "",
      manual_id: micBtn.dataset.manual || "",
    },
    onPage: (n) => jump(n),
    onStatus: (status) => {
      if (status === "disconnected") endVoice();
    },
  });
  if (!handle) {
    micBtn.setAttribute("aria-pressed", "false");
    return;
  }
  session = handle;
}

/* ---------- ask ---------- */

function setAskBar(pct) {
  const n = Math.max(0, Math.min(1, Number(pct) || 0));
  askBarFill.style.width = `${Math.round(n * 100)}%`;
}

function onAskProgress(info) {
  if (!info) return;
  if (info.status === "progress" && Number(info.total) > 0) {
    askBar.hidden = false;
    setAskBar(Number(info.loaded) / Number(info.total));
    return;
  }
  if (info.status === "progress_total" && Number.isFinite(Number(info.progress))) {
    askBar.hidden = false;
    setAskBar(Number(info.progress) / 100);
    return;
  }
  if (info.status === "done" || info.status === "ready") setAskBar(1);
}

async function syncAsk(job) {
  askPages = [];
  askFetchTok += 1;
  const token = askFetchTok;
  askBtn.hidden = true;
  closeAsk();
  if (manualRec.ocr === false) return;
  const list = await fetchJobPages(job).catch(() => []);
  if (token !== askFetchTok) return;
  // Rows with no text still carry the manual id, and /ask answers with section titles.
  askPages = list;
  askBtn.hidden = list.length === 0;
}

function openAsk() {
  if (askBtn.hidden) return;
  if (immersive) setImmersive(false);
  askSheet.hidden = false;
  askSheet.classList.add("open");
  askSheet.dataset.state = "idle";
  askBtn.setAttribute("aria-expanded", "true");
  askInput.value = "";
  askInput.focus();
  askHits.replaceChildren();
  askBar.hidden = false;
  setAskBar(0);
  loadAsk(onAskProgress)
    .then(() => {
      setAskBar(1);
      window.setTimeout(() => {
        askBar.hidden = true;
      }, 120);
    })
    .catch(() => {
      askBar.hidden = true;
    });
}

function closeAsk() {
  if (!askSheet) return;
  askSheet.hidden = true;
  askSheet.classList.remove("open");
  askSheet.dataset.state = "";
  askBtn.setAttribute("aria-expanded", "false");
  askHits.replaceChildren();
  askBar.hidden = true;
  askBusy = false;
}

function onAskToggle() {
  if (askSheet.hidden) openAsk();
  else closeAsk();
}

function onEsc(e) {
  if (e.key !== "Escape") return;
  if (!askSheet.hidden) {
    closeAsk();
    return;
  }
  if (immersive) setImmersive(false);
}

function onAskKey(e) {
  if (e.key !== "Enter") return;
  e.preventDefault();
  runAsk();
}

function flash(n) {
  const rec = sheets.get(n);
  if (!rec) return;
  if (askFlashTimer) window.clearTimeout(askFlashTimer);
  rec.host.classList.remove("ask-flash");
  void rec.host.offsetWidth;
  rec.host.classList.add("ask-flash");
  askFlashTimer = window.setTimeout(() => {
    rec.host.classList.remove("ask-flash");
    askFlashTimer = 0;
  }, 900);
}

function paintAskHits(rows) {
  askHits.replaceChildren();
  for (const row of rows || []) {
    const pageText = (askPages.find((p) => p.n === row.page) || {}).text || "";
    const win = contextWindow(pageText, row.start, row.end, 160);
    const btn = el("button", { class: "card ask-hit", type: "button" });
    const ctx = el("p", { class: "ask-ctx" });
    const before = win.text.slice(0, Math.max(0, win.start));
    const mid = win.text.slice(Math.max(0, win.start), Math.max(0, win.end));
    const after = win.text.slice(Math.max(0, win.end));
    if (before) ctx.append(document.createTextNode(before));
    const bold = el("b", { class: "ask-span" });
    bold.textContent = mid || row.answer;
    ctx.append(bold);
    if (after) ctx.append(document.createTextNode(after));
    btn.append(ctx, el("span", { class: "stamp", text: `p.${row.page}` }));
    btn.addEventListener("click", () => {
      goToPage(row.page);
      closeAsk();
    });
    askHits.append(btn);
  }
}

/** An answer can sit on a page the reading list never carried: fall back to all pages. */
function goToPage(n) {
  if (sheets.has(n)) {
    jump(n);
    flash(n);
    return;
  }
  if (!(totalPages > 1)) return;
  mode = "all";
  writeMode(jobRec && jobRec.manualId, mode);
  paintModeBtn();
  setPages(allList(), { strip: readList, at: n });
  flash(n);
}

async function runAsk() {
  if (askBusy) return;
  const q = String(askInput.value || "").trim();
  if (!q || !askPages.length) {
    askHits.replaceChildren();
    askSheet.dataset.state = "done";
    return;
  }
  askBusy = true;
  askRunTok += 1;
  const token = askRunTok;
  askSheet.dataset.state = "run";
  askHits.replaceChildren();
  askBar.hidden = false;
  setAskBar(0.15);
  let rows = [];
  try {
    rows = await ask(q, askPages);
  } catch {
    rows = [];
  }
  if (token !== askRunTok) return;
  askBusy = false;
  askBar.hidden = true;
  paintAskHits(rows);
  askSheet.dataset.state = "done";
}

/* ---------- screen ---------- */

registerScreen("book", {
  mount(root) {
    build(root);
  },

  async enter() {
    if (!state.bikeId) {
      bounce("identify");
      return;
    }
    if (!state.jobId) {
      bounce("pick");
      return;
    }
    const my = ++enterGen;
    setImmersive(false);
    const job = await Q.jobById(state.jobId);
    if (my !== enterGen) return;
    if (!job) {
      bounce("pick");
      return;
    }
    await paint(job);
  },

  /** Back pops the reader's own layers first, so no tap can strand the Back affordance. */
  back() {
    if (!askSheet.hidden) {
      closeAsk();
      return true;
    }
    if (immersive) {
      setImmersive(false);
      return true;
    }
    return false;
  },

  leave() {
    enterGen += 1;
    cancelTap();
    endVoice();
    closeAsk();
    setImmersive(false);
    resetZoom();
  },
});
