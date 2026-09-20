import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../ttm.js";
import { cachedRatio, pageRatio, preloadPage, renderPage, releaseCanvas } from "../pdf.js";

const SVG = "http://www.w3.org/2000/svg";
const SWIPE = 48;
const TAP = 10;
const PINCH_MAX = 4;
const LANDSCAPE = 1 / 1.2;
const BORDER = 6;
const STAGGER = 60;

const els = {};
const ratioCache = new Map();

let live = false;
let job = null;
let manualRec = null;
let fileUrl = "";
let steps = [];
let marks = new Map();
let index = 0;
let ratio = 1.4142;
let fit = "width";
let chromeOn = true;
let frameW = 0;
let frameH = 0;
let contentW = 0;
let contentH = 0;
let scale = 1;
let tx = 0;
let ty = 0;
let enterGen = 0;
let showGen = 0;

const pointers = new Map();
let pinch0 = 1;
let scale0 = 1;
let pinchContent = { x: 0, y: 0 };
let pan0 = { x: 0, y: 0 };
let pt0 = { x: 0, y: 0 };
let didPinch = false;

/* ---------- helpers ---------- */

function glyph(...ds) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of ds) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "3");
    path.setAttribute("stroke-linecap", "square");
    path.setAttribute("stroke-linejoin", "miter");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function bounce() {
  const dest = state.bikeId ? "book" : "identify";
  queueMicrotask(() => go(dest, { replace: true }));
}

function pageOf(step) {
  if (step == null) return null;
  if (typeof step === "number") return step;
  const n = Number(step.page);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function stepsOf(rec) {
  const list = (rec.steps || []).filter((step) => pageOf(step) != null);
  if (list.length) return list;
  return (rec.pages || []).filter((n) => Number(n) > 0).map((page) => ({ page: Number(page) }));
}

function markMap(rec) {
  const map = new Map();
  for (const h of rec.highlights || []) {
    const n = Number(h && h.page);
    if (!Number.isFinite(n)) continue;
    const list = map.get(n);
    if (list) list.push(h);
    else map.set(n, [h]);
  }
  return map;
}

/* ---------- printed page numbers ---------- */

function tocPagesOf(manual) {
  const out = [];
  for (const row of (manual && manual.toc) || []) {
    const n = Number(row && row.page);
    if (Number.isFinite(n)) out.push(n);
  }
  out.sort((a, z) => a - z);
  return out;
}

function tocSpanContains(tocPages, n) {
  if (n == null) return { start: null, end: Infinity };
  let start = tocPages[0] ?? n;
  let end = Infinity;
  for (const page of tocPages) {
    if (page <= n) start = page;
    if (page > n) {
      end = page;
      break;
    }
  }
  return { start, end };
}

function printedLabel(pdfIndex) {
  if (pdfIndex == null || !job) return null;
  const raw = job.printedPage;
  const base = job.pages && job.pages[0];
  if (raw == null || String(raw).trim() === "" || base == null) return null;
  const printed = String(raw).trim();
  if (/^\d+$/.test(printed)) return String(pdfIndex - Number(base) + Number(printed));
  if (pdfIndex === Number(base)) return printed;
  const sec = printed.match(/^(\d+)-(\d+)$/);
  if (!sec) return null;
  const here = tocSpanContains(tocPagesOf(manualRec), Number(base));
  if (pdfIndex < here.start || pdfIndex >= here.end) return null;
  return `${sec[1]}-${Number(sec[2]) + (pdfIndex - Number(base))}`;
}

function stampText(n) {
  const label = printedLabel(n);
  return label ? `p.${label}` : n != null ? `p.${n}` : "";
}

function writeStamp(node, n) {
  const text = stampText(n);
  node.textContent = text;
  node.hidden = !text;
  return text;
}

/* ---------- page media ---------- */

function isLandscape() {
  return ratio < LANDSCAPE;
}

function probeImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img.naturalWidth ? img.naturalHeight / img.naturalWidth : null);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function resolveRatio(page) {
  const key = `${job.manualId}|${page}`;
  if (ratioCache.has(key)) return ratioCache.get(key);
  const url = Q.pageUrl(job.manualId, page);
  let found = null;
  if (url) found = await probeImage(url);
  else if (fileUrl) found = await pageRatio(fileUrl, page).catch(() => null);
  const value = found || (fileUrl ? cachedRatio(fileUrl, page) : 1.4142);
  ratioCache.set(key, value);
  return value;
}

/** Draws a page into an {img, canvas} pair. Resolves once the pixels are there. */
async function paintInto(pair, page, width) {
  const url = Q.pageUrl(job.manualId, page);
  if (url) {
    pair.canvas.hidden = true;
    pair.img.hidden = false;
    pair.img.alt = stampText(page);
    if (pair.img.getAttribute("src") !== url) {
      pair.img.src = url;
      await new Promise((resolve) => {
        pair.img.onload = resolve;
        pair.img.onerror = resolve;
      });
    }
    if (pair.img.naturalWidth) return true;
  }
  if (!fileUrl) return false;
  pair.img.hidden = true;
  pair.canvas.hidden = false;
  return renderPage(fileUrl, page, Math.max(120, Math.round(width)), pair.canvas).catch(() => false);
}

function ink(box, page) {
  box.replaceChildren();
  const list = marks.get(page) || [];
  const frag = document.createDocumentFragment();
  list.forEach((h, i) => {
    const m = document.createElement("i");
    m.className = "mark";
    m.style.left = `${Number(h.x) * 100}%`;
    m.style.top = `${Number(h.y) * 100}%`;
    m.style.width = `${Number(h.w) * 100}%`;
    m.style.height = `${Number(h.h) * 100}%`;
    m.style.animationDelay = `${i * STAGGER}ms`;
    frag.append(m);
  });
  box.append(frag);
}

/* ---------- zoom / pan ---------- */

function resetZoom() {
  scale = 1;
  tx = 0;
  ty = 0;
  pointers.clear();
  didPinch = false;
  chromeOn = true;
  if (els.zoom) els.zoom.style.transform = "";
  if (els.root) els.root.classList.remove("is-reading");
}

function framePoint(clientX, clientY) {
  const rect = els.frame.getBoundingClientRect();
  const cs = getComputedStyle(els.frame);
  return {
    x: clientX - rect.left - (parseFloat(cs.borderLeftWidth) || 0),
    y: clientY - rect.top - (parseFloat(cs.borderTopWidth) || 0),
  };
}

function clampPan() {
  const sw = contentW * scale;
  const sh = contentH * scale;
  if (sw <= frameW) tx = (frameW - sw) / 2;
  else tx = Math.min(0, Math.max(frameW - sw, tx));
  if (sh <= frameH) ty = (frameH - sh) / 2;
  else ty = Math.min(0, Math.max(frameH - sh, ty));
}

function paintIndicator() {
  const sw = contentW * scale;
  const canX = sw > frameW + 1;
  els.frame.classList.toggle("is-pan-x", canX);
  if (!canX) return;
  const track = els.ind.clientWidth || Math.max(0, frameW - 16);
  const thumbW = Math.max(20, (frameW / sw) * track);
  const maxTx = sw - frameW;
  const t = maxTx <= 0 ? 0 : Math.min(1, Math.max(0, -tx / maxTx));
  els.indThumb.style.width = `${thumbW}px`;
  els.indThumb.style.transform = `translateX(${t * (track - thumbW)}px)`;
}

function applyZoom(opts) {
  if (!els.zoom) return;
  els.zoom.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
  const zoomed = scale > 1.02;
  if (opts && opts.fromZoom) chromeOn = !zoomed;
  if (!zoomed) chromeOn = true;
  els.root.classList.toggle("is-reading", zoomed && !chromeOn);
  paintIndicator();
}

function measureAvailH() {
  const ticket = document.querySelector("header.ticket");
  const rail = document.querySelector("ol.rail");
  const main = document.querySelector("main");
  const cs = main ? getComputedStyle(main) : null;
  const pad = cs ? parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) : 44;
  const ticketH = ticket ? ticket.getBoundingClientRect().height : 0;
  const railH = rail ? rail.getBoundingClientRect().height : 0;
  const progressH = els.progress ? els.progress.offsetHeight : 0;
  const relatedH = els.related && !els.related.hidden ? els.related.offsetHeight : 0;
  const partH = els.partBtn ? els.partBtn.offsetHeight : 0;
  const gap = els.root ? parseFloat(getComputedStyle(els.root).gap) || 10 : 10;
  const items = 3 + (els.related && !els.related.hidden ? 1 : 0);
  const used = ticketH + railH + pad + progressH + relatedH + partH + (items - 1) * gap;
  return Math.max(160, window.innerHeight - used);
}

function layout() {
  if (!els.frame) return;
  const ar = 1 / ratio;
  els.frame.style.setProperty("--page-ar", String(ar));
  els.frame.classList.add("is-sized");

  const availH = measureAvailH();
  const stageW = els.stage.clientWidth || els.root.clientWidth || 366;
  const useHeight = isLandscape() && fit === "height";
  els.frame.classList.toggle("is-fit-height", useHeight);
  els.frame.classList.toggle("is-fit-width", !useHeight);

  const innerMaxW = Math.max(80, stageW - BORDER);
  const innerMaxH = Math.max(80, availH - BORDER);
  let innerW;
  let innerH;

  if (useHeight) {
    innerH = innerMaxH;
    contentH = innerH;
    contentW = innerH * ar;
    innerW = Math.min(innerMaxW, contentW);
  } else {
    innerW = innerMaxW;
    innerH = innerW / ar;
    if (innerH > innerMaxH) {
      innerH = innerMaxH;
      innerW = innerH * ar;
    }
    contentW = innerW;
    contentH = innerH;
  }

  frameW = innerW;
  frameH = innerH;
  els.frame.style.setProperty("--stage-w", `${innerW + BORDER}px`);
  els.frame.style.setProperty("--stage-h", `${innerH + BORDER}px`);
  els.zoom.style.width = `${contentW}px`;
  els.zoom.style.height = `${contentH}px`;
  clampPan();
  applyZoom();
}

function zoomAt(clientX, clientY, nextScale) {
  const pt = framePoint(clientX, clientY);
  const newScale = Math.min(PINCH_MAX, Math.max(1, nextScale));
  const cx = (pt.x - tx) / scale;
  const cy = (pt.y - ty) / scale;
  scale = newScale;
  tx = pt.x - cx * scale;
  ty = pt.y - cy * scale;
  clampPan();
  applyZoom({ fromZoom: true });
}

function capturePinch() {
  const pts = [...pointers.values()];
  if (pts.length < 2) return;
  const [a, b] = pts;
  pinch0 = Math.hypot(a.x - b.x, a.y - b.y) || 1;
  scale0 = scale;
  const pt = framePoint((a.x + b.x) / 2, (a.y + b.y) / 2);
  pinchContent = { x: (pt.x - tx) / scale, y: (pt.y - ty) / scale };
  didPinch = true;
}

function onTap() {
  if (scale > 1.02) {
    chromeOn = !chromeOn;
    applyZoom();
    return;
  }
  if (!isLandscape()) return;
  fit = fit === "height" ? "width" : "height";
  resetZoom();
  layout();
  repaint();
}

/* ---------- related ---------- */

function closeOverlay() {
  if (!els.overlay || els.overlay.hidden) return;
  els.overlay.hidden = true;
  els.overImg.removeAttribute("src");
  els.overImg.alt = "";
  releaseCanvas(els.overCanvas);
}

async function openOverlay(page) {
  els.overlay.hidden = false;
  els.closeBtn.focus();
  await paintInto({ img: els.overImg, canvas: els.overCanvas }, page, els.overlay.clientWidth);
}

function paintRelated() {
  const list = Array.isArray(job.related) ? job.related : [];
  els.related.replaceChildren();
  if (!list.length) {
    els.related.hidden = true;
    return;
  }
  els.related.hidden = false;
  for (const item of list) {
    const page = pageOf(item);
    if (page == null) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "related-item";
    btn.addEventListener("click", () => openOverlay(page));

    const thumb = Q.thumbUrl(job.manualId, page);
    const text = stampText(page);
    if (thumb) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = text;
      img.src = thumb;
      img.addEventListener("load", () => {
        if (img.naturalWidth && img.naturalHeight) {
          btn.style.setProperty("--thumb-ar", String(img.naturalWidth / img.naturalHeight));
        }
      });
      btn.append(img);
    } else {
      btn.classList.add("is-plain");
      const n = document.createElement("b");
      n.textContent = String(page);
      btn.append(n);
      btn.setAttribute("aria-label", text);
    }

    const tag = document.createElement("span");
    tag.className = "tag";
    tag.setAttribute("aria-hidden", "true");
    tag.textContent = text;
    tag.hidden = !text || btn.classList.contains("is-plain");
    btn.append(tag);
    els.related.append(btn);
  }
}

/* ---------- steps ---------- */

function paintDots() {
  const n = steps.length;
  const row = els.dots;
  while (row.childNodes.length > n) row.removeChild(row.lastChild);
  while (row.childNodes.length < n) {
    const dot = document.createElement("i");
    dot.className = "dot";
    row.append(dot);
  }
  row.childNodes.forEach((dot, i) => {
    dot.classList.toggle("done", i < index);
    dot.classList.toggle("now", i === index);
  });
}

function publish(page) {
  set({ page });
  emit("page", { n: page });
}

function repaint() {
  const page = pageOf(steps[index]);
  if (page == null) return;
  paintInto({ img: els.pageImg, canvas: els.pageCanvas }, page, contentW);
}

async function show() {
  const my = ++showGen;
  const page = pageOf(steps[index]);
  const n = steps.length;

  els.indexStamp.textContent = `${index + 1} / ${n}`;
  writeStamp(els.pageStamp, page);
  els.marks.replaceChildren();
  paintDots();
  els.prevBtn.disabled = index <= 0;
  els.nextBtn.disabled = index >= n - 1;
  resetZoom();

  ratio = await resolveRatio(page);
  if (my !== showGen || !live) return;
  fit = isLandscape() ? "height" : "width";
  layout();

  const ok = await paintInto({ img: els.pageImg, canvas: els.pageCanvas }, page, contentW);
  if (my !== showGen || !live) return;
  if (ok) ink(els.marks, page);
  publish(page);

  const next = pageOf(steps[index + 1]);
  if (next == null) return;
  const url = Q.pageUrl(job.manualId, next);
  if (url) {
    const im = new Image();
    im.decoding = "async";
    im.src = url;
  } else if (fileUrl) {
    preloadPage(fileUrl, next, Math.max(120, Math.round(contentW)));
  }
}

function goStep(delta) {
  closeOverlay();
  const next = index + delta;
  if (next < 0 || next >= steps.length) return;
  index = next;
  show();
}

/* ---------- input ---------- */

function onKey(event) {
  if (!live) return;
  if (event.key === "Escape") {
    if (!els.overlay.hidden) {
      event.preventDefault();
      closeOverlay();
    }
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    goStep(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    goStep(1);
  }
}

function onResize() {
  if (!live) return;
  layout();
  repaint();
}

function onPointerDown(event) {
  if (!live || !els.overlay.hidden) return;
  if (event.button && event.button !== 0) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  try {
    els.frame.setPointerCapture(event.pointerId);
  } catch {
    /* ignore */
  }
  if (pointers.size === 1) {
    pt0 = { x: event.clientX, y: event.clientY };
    pan0 = { x: tx, y: ty };
    didPinch = false;
  } else if (pointers.size >= 2) {
    capturePinch();
  }
}

function onPointerMove(event) {
  if (!pointers.has(event.pointerId)) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size >= 2) {
    const [a, b] = [...pointers.values()];
    const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
    const pt = framePoint((a.x + b.x) / 2, (a.y + b.y) / 2);
    scale = Math.min(PINCH_MAX, Math.max(1, scale0 * (dist / pinch0)));
    tx = pt.x - pinchContent.x * scale;
    ty = pt.y - pinchContent.y * scale;
    clampPan();
    applyZoom({ fromZoom: true });
    didPinch = true;
    return;
  }
  if (scale > 1.01 || contentW * scale > frameW + 1 || contentH * scale > frameH + 1) {
    tx = pan0.x + (event.clientX - pt0.x);
    ty = pan0.y + (event.clientY - pt0.y);
    clampPan();
    applyZoom();
  }
}

function onPointerUp(event) {
  if (!pointers.has(event.pointerId)) return;
  pointers.delete(event.pointerId);
  try {
    els.frame.releasePointerCapture(event.pointerId);
  } catch {
    /* ignore */
  }
  if (pointers.size === 0) {
    if (!didPinch) {
      const dx = event.clientX - pt0.x;
      const dy = event.clientY - pt0.y;
      if (Math.hypot(dx, dy) < TAP) {
        onTap();
      } else if (scale <= 1.01 && Math.abs(dx) >= SWIPE && Math.abs(dx) > Math.abs(dy)) {
        const sw = contentW * scale;
        const atLeft = tx >= -2;
        const atRight = tx <= frameW - sw + 2;
        if (fit === "width" || sw <= frameW + 1 || (dx < 0 && atRight) || (dx > 0 && atLeft)) {
          goStep(dx < 0 ? 1 : -1);
        }
      }
    }
    if (scale < 1.02) {
      scale = 1;
      clampPan();
      applyZoom();
    }
    return;
  }
  const rest = [...pointers.values()][0];
  pt0 = { x: rest.x, y: rest.y };
  pan0 = { x: tx, y: ty };
  if (pointers.size >= 2) capturePinch();
}

function onWheel(event) {
  if (!live || !els.overlay.hidden) return;
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    zoomAt(event.clientX, event.clientY, scale * (event.deltaY < 0 ? 1.12 : 0.9));
    return;
  }
  if (contentW * scale > frameW + 1) {
    event.preventDefault();
    tx -= event.deltaX || event.deltaY;
    clampPan();
    applyZoom();
  }
}

/* ---------- screen ---------- */

registerScreen("follow", {
  mount(root) {
    const progress = document.createElement("div");
    progress.className = "sheet follow-progress";
    const indexStamp = document.createElement("span");
    indexStamp.className = "stamp";
    const dots = document.createElement("div");
    dots.className = "dots";
    dots.setAttribute("aria-hidden", "true");
    const pageStamp = document.createElement("span");
    pageStamp.className = "stamp";
    progress.append(indexStamp, dots, pageStamp);

    const stage = document.createElement("div");
    stage.className = "stage";
    const frame = document.createElement("div");
    frame.className = "stage-frame";
    const zoom = document.createElement("div");
    zoom.className = "stage-zoom";

    const pageCanvas = document.createElement("canvas");
    pageCanvas.className = "page-canvas";
    pageCanvas.hidden = true;
    const pageImg = document.createElement("img");
    pageImg.className = "page-img";
    pageImg.decoding = "async";
    pageImg.alt = "";
    const marks = document.createElement("div");
    marks.className = "page-marks";
    marks.setAttribute("aria-hidden", "true");
    zoom.append(pageCanvas, pageImg, marks);

    const ind = document.createElement("div");
    ind.className = "pan-ind";
    ind.setAttribute("aria-hidden", "true");
    const indThumb = document.createElement("i");
    ind.append(indThumb);
    frame.append(zoom, ind);

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "btn btn-icon nav-prev";
    prevBtn.setAttribute("aria-label", "Prev");
    prevBtn.append(glyph("M14.5 5 8 12l6.5 7"));
    prevBtn.addEventListener("click", () => goStep(-1));

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "btn btn-icon nav-next";
    nextBtn.setAttribute("aria-label", "Next");
    nextBtn.append(glyph("M9.5 5 16 12l-6.5 7"));
    nextBtn.addEventListener("click", () => goStep(1));

    const overlay = document.createElement("div");
    overlay.className = "overlay card";
    overlay.hidden = true;
    const overCanvas = document.createElement("canvas");
    overCanvas.className = "page-canvas";
    overCanvas.hidden = true;
    const overImg = document.createElement("img");
    overImg.className = "page-img";
    overImg.decoding = "async";
    overImg.alt = "";
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "btn btn-icon overlay-close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.append(glyph("M5 5l14 14M19 5 5 19"));
    closeBtn.addEventListener("click", closeOverlay);
    overlay.append(overCanvas, overImg, closeBtn);

    stage.append(frame, prevBtn, nextBtn, overlay);

    const related = document.createElement("div");
    related.className = "related";
    related.hidden = true;

    const partBtn = document.createElement("button");
    partBtn.type = "button";
    partBtn.className = "btn btn-primary part-btn";
    partBtn.textContent = "Parts";
    partBtn.addEventListener("click", () => go("invoice"));

    root.append(progress, stage, related, partBtn);

    Object.assign(els, {
      root,
      progress,
      indexStamp,
      dots,
      pageStamp,
      stage,
      frame,
      zoom,
      pageImg,
      pageCanvas,
      marks,
      ind,
      indThumb,
      prevBtn,
      nextBtn,
      overlay,
      overImg,
      overCanvas,
      closeBtn,
      related,
      partBtn,
    });

    frame.addEventListener("pointerdown", onPointerDown);
    frame.addEventListener("pointermove", onPointerMove);
    frame.addEventListener("pointerup", onPointerUp);
    frame.addEventListener("pointercancel", onPointerUp);
    frame.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", onResize);
  },

  async enter(params) {
    if (!live) window.addEventListener("keydown", onKey);
    live = true;
    closeOverlay();

    if (state.jobId == null || state.jobId === "") {
      bounce();
      return;
    }

    const my = ++enterGen;
    const rec = await Q.jobById(state.jobId);
    if (my !== enterGen || !live) return;
    if (!rec) {
      bounce();
      return;
    }

    const list = stepsOf(rec);
    if (!list.length) {
      bounce();
      return;
    }

    job = rec;
    manualRec = (await Q.manual(rec.manualId)) || {};
    if (my !== enterGen || !live) return;
    fileUrl = manualRec.file ? Q.asset(manualRec.file) : "";
    steps = list;
    marks = markMap(rec);

    const wanted = Number(params && params.step);
    index = Number.isFinite(wanted) ? Math.max(0, Math.min(list.length - 1, Math.trunc(wanted))) : 0;

    paintRelated();
    await show();
  },

  leave() {
    live = false;
    showGen += 1;
    closeOverlay();
    resetZoom();
    pointers.clear();
    window.removeEventListener("keydown", onKey);
  },
});
