import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../query.js";

const SVG = "http://www.w3.org/2000/svg";
const SWIPE = 48;
const TAP = 10;
const PINCH_MAX = 4;
const LANDSCAPE_AR = 1.2;
const BORDER = 6;
const els = {};

const MANUAL_RASTER = {
  "honda-cb650r-2021-om": [1400, 994],
  "yamaha-mt-07-2021-om": [1400, 985],
  "kawasaki-z650-2020-om": [1400, 993],
  "suzuki-sv650-2019-om": [1400, 1991],
};

const sizeCache = new Map();

let live = false;
let job = null;
let manualRec = null;
let steps = [];
let index = 0;
let cropped = true;
let fit = "width";
let chromeOn = true;
let pageW = 1400;
let pageH = 994;
let frameW = 0;
let frameH = 0;
let contentW = 0;
let contentH = 0;
let scale = 1;
let tx = 0;
let ty = 0;
const pointers = new Map();
let pinch0 = 1;
let scale0 = 1;
let pinchContent = { x: 0, y: 0 };
let pan0 = { x: 0, y: 0 };
let pt0 = { x: 0, y: 0 };
let didPinch = false;
let didPan = false;
let enterGen = 0;

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

function preload(src) {
  if (!src) return;
  const img = new Image();
  img.decoding = "async";
  img.src = src;
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

function cropOf(step) {
  const raw = step && step.crop;
  if (!Array.isArray(raw) || raw.length !== 4) return null;
  const [x, y, w, h] = raw.map(Number);
  if (![x, y, w, h].every((n) => Number.isFinite(n))) return null;
  if (w <= 0 || h <= 0) return null;
  return [x, y, w, h];
}

function stepsOf(rec) {
  return (rec.steps || []).filter((step) => pageOf(step) != null);
}

function tocPagesOf(manual) {
  const out = [];
  for (const row of (manual && manual.toc) || []) {
    const n = Number(row && row.page);
    if (!Number.isFinite(n)) continue;
    out.push(n);
  }
  out.sort((a, b) => a - b);
  return out;
}

function tocSpanContains(tocPages, n) {
  if (n == null) return { start: null, end: Infinity };
  let start = tocPages[0] ?? n;
  let end = Infinity;
  for (let i = 0; i < tocPages.length; i++) {
    if (tocPages[i] <= n) start = tocPages[i];
    if (tocPages[i] > n) {
      end = tocPages[i];
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
  if (/^\d+$/.test(printed)) {
    return String(pdfIndex - Number(base) + Number(printed));
  }
  if (pdfIndex === Number(base)) return printed;
  const sec = printed.match(/^(\d+)-(\d+)$/);
  if (!sec) return null;
  const tocPages = tocPagesOf(manualRec);
  const here = tocSpanContains(tocPages, Number(base));
  if (pdfIndex < here.start || pdfIndex >= here.end) return null;
  return `${sec[1]}-${Number(sec[2]) + (pdfIndex - Number(base))}`;
}

function stampText(n) {
  const label = printedLabel(n);
  return label ? `p.${label}` : "";
}

function writeStamp(node, n) {
  const text = stampText(n);
  node.textContent = text;
  node.hidden = !text;
  return text;
}

function isLandscape() {
  return pageW / pageH > LANDSCAPE_AR;
}

function rememberSize(w, h, manualId) {
  if (!w || !h) return;
  pageW = w;
  pageH = h;
  if (manualId) sizeCache.set(manualId, { w, h });
  if (els.frame) els.frame.style.setProperty("--page-ar", String(w / h));
}

function applyKnownRaster(manualId) {
  const cached = sizeCache.get(manualId);
  if (cached) {
    rememberSize(cached.w, cached.h, manualId);
    return true;
  }
  const pair = MANUAL_RASTER[manualId];
  if (pair) {
    rememberSize(pair[0], pair[1], manualId);
    return true;
  }
  return false;
}

function probePage(manualId, page) {
  applyKnownRaster(manualId);
  const src = Q.pageUrl(manualId, page);
  const known = sizeCache.has(manualId) || MANUAL_RASTER[manualId];
  const img = new Image();
  img.decoding = "async";
  const apply = () => {
    if (img.naturalWidth && img.naturalHeight) {
      rememberSize(img.naturalWidth, img.naturalHeight, manualId);
    }
  };
  if (img.complete && img.naturalWidth) {
    apply();
    return Promise.resolve();
  }
  img.src = src;
  if (img.complete && img.naturalWidth) {
    apply();
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    img.onload = () => {
      apply();
      resolve();
    };
    img.onerror = () => resolve();
    if (known) resolve();
  });
}

function resetZoom() {
  scale = 1;
  tx = 0;
  ty = 0;
  pointers.clear();
  didPinch = false;
  didPan = false;
  chromeOn = true;
  if (els.zoom) els.zoom.style.transform = "";
  if (els.root) els.root.classList.remove("is-reading");
}

function framePoint(clientX, clientY) {
  const rect = els.frame.getBoundingClientRect();
  const cs = getComputedStyle(els.frame);
  const bl = parseFloat(cs.borderLeftWidth) || 0;
  const bt = parseFloat(cs.borderTopWidth) || 0;
  return { x: clientX - rect.left - bl, y: clientY - rect.top - bt };
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
  if (!els.ind || !els.indThumb) return;
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
  if (els.root) els.root.classList.toggle("is-reading", zoomed && !chromeOn);
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
  if (!els.frame || !els.zoom || !els.stage) return;
  const ar = pageW / pageH;
  els.frame.style.setProperty("--page-ar", String(ar));

  if (els.frame.classList.contains("is-crop")) {
    els.frame.classList.remove("is-sized", "is-fit-height", "is-fit-width", "is-pan-x");
    els.frame.style.removeProperty("--stage-w");
    els.frame.style.removeProperty("--stage-h");
    els.zoom.style.width = "";
    els.zoom.style.height = "";
    requestAnimationFrame(() => {
      frameW = els.frame.clientWidth;
      frameH = els.frame.clientHeight;
      contentW = frameW;
      contentH = frameH;
      clampPan();
      applyZoom();
    });
    return;
  }

  const availH = measureAvailH();
  const stageW = els.stage.clientWidth || els.root.clientWidth || 366;
  const useHeight = isLandscape() && fit === "height";
  els.frame.classList.toggle("is-fit-height", useHeight);
  els.frame.classList.toggle("is-fit-width", !useHeight);
  els.frame.classList.add("is-sized");

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
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const pt = framePoint(mid.x, mid.y);
  pinchContent = {
    x: (pt.x - tx) / scale,
    y: (pt.y - ty) / scale,
  };
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
}

function closeOverlay() {
  if (!els.overlay || els.overlay.hidden) return;
  els.overlay.hidden = true;
  els.overImg.removeAttribute("src");
  els.overImg.alt = "";
}

function openOverlay(page) {
  const src = Q.pageUrl(job.manualId, page);
  els.overImg.loading = "lazy";
  els.overImg.decoding = "async";
  els.overImg.alt = stampText(page);
  els.overImg.src = src;
  els.overlay.hidden = false;
  els.closeBtn.focus();
}

function publish(step) {
  const n = pageOf(step);
  set({ page: n });
  emit("page", { n });
}

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

    const img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    const text = stampText(page);
    img.alt = text;
    img.src = Q.thumbUrl(job.manualId, page);
    img.addEventListener("load", () => {
      if (img.naturalWidth && img.naturalHeight) {
        btn.style.setProperty("--thumb-ar", String(img.naturalWidth / img.naturalHeight));
      }
    });

    const tag = document.createElement("span");
    tag.className = "tag";
    tag.setAttribute("aria-hidden", "true");
    tag.textContent = text;
    tag.hidden = !text;

    btn.append(img, tag);
    els.related.append(btn);
  }
}

function applyCrop(step) {
  const crop = cropped ? cropOf(step) : null;
  els.frame.classList.toggle("is-crop", Boolean(crop));
  els.cropBtn.hidden = !cropOf(step);
  els.cropBtn.setAttribute("aria-pressed", crop ? "true" : "false");
  if (crop) {
    const [x, y, w, h] = crop;
    els.frame.style.setProperty("--cx", String(x));
    els.frame.style.setProperty("--cy", String(y));
    els.frame.style.setProperty("--cw", String(w));
    els.frame.style.setProperty("--ch", String(h));
  } else {
    els.frame.style.removeProperty("--cx");
    els.frame.style.removeProperty("--cy");
    els.frame.style.removeProperty("--cw");
    els.frame.style.removeProperty("--ch");
  }
}

function show() {
  const step = steps[index];
  const page = pageOf(step);
  const n = steps.length;
  const src = Q.pageUrl(job.manualId, page);

  applyKnownRaster(job.manualId);

  els.indexStamp.textContent = `${index + 1} / ${n}`;
  writeStamp(els.pageStamp, page);
  els.pageImg.alt = stampText(page);
  applyCrop(step);
  paintDots();

  els.prevBtn.disabled = index <= 0;
  els.nextBtn.disabled = index >= n - 1;

  resetZoom();
  fit = isLandscape() ? "height" : "width";
  els.pageImg.src = src;
  if (els.pageImg.complete && els.pageImg.naturalWidth) {
    rememberSize(els.pageImg.naturalWidth, els.pageImg.naturalHeight, job.manualId);
  }
  layout();
  publish(step);

  const next = steps[index + 1];
  if (next) preload(Q.pageUrl(job.manualId, pageOf(next)));
}

function goStep(delta) {
  closeOverlay();
  const next = index + delta;
  if (next < 0 || next >= steps.length) return;
  index = next;
  cropped = true;
  show();
}

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
    didPan = false;
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
    const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const next = Math.min(PINCH_MAX, Math.max(1, scale0 * (dist / pinch0)));
    const pt = framePoint(mid.x, mid.y);
    scale = next;
    tx = pt.x - pinchContent.x * scale;
    ty = pt.y - pinchContent.y * scale;
    clampPan();
    applyZoom({ fromZoom: true });
    didPinch = true;
    return;
  }
  const canPan =
    scale > 1.01 || contentW * scale > frameW + 1 || contentH * scale > frameH + 1;
  if (canPan) {
    const ndx = event.clientX - pt0.x;
    const ndy = event.clientY - pt0.y;
    if (Math.hypot(ndx, ndy) >= TAP) didPan = true;
    tx = pan0.x + ndx;
    ty = pan0.y + ndy;
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
      const dist = Math.hypot(dx, dy);
      if (dist < TAP) {
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
    const next = scale * (event.deltaY < 0 ? 1.12 : 0.9);
    zoomAt(event.clientX, event.clientY, next);
    return;
  }
  if (contentW * scale > frameW + 1) {
    event.preventDefault();
    tx -= event.deltaX || event.deltaY;
    clampPan();
    applyZoom();
  }
}

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

    const pageImg = document.createElement("img");
    pageImg.loading = "lazy";
    pageImg.decoding = "async";
    pageImg.alt = "";
    pageImg.addEventListener("load", () => {
      if (pageImg.naturalWidth && pageImg.naturalHeight) {
        rememberSize(pageImg.naturalWidth, pageImg.naturalHeight, job && job.manualId);
        if (live) layout();
      }
    });

    zoom.append(pageImg);

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

    const cropBtn = document.createElement("button");
    cropBtn.type = "button";
    cropBtn.className = "btn btn-icon crop-btn";
    cropBtn.setAttribute("aria-label", "Crop");
    cropBtn.hidden = true;
    cropBtn.append(glyph("M3 9V3h6", "M21 9V3h-6", "M3 15v6h6", "M21 15v6h-6"));
    cropBtn.addEventListener("click", () => {
      cropped = !cropped;
      applyCrop(steps[index]);
      resetZoom();
      layout();
    });

    const overlay = document.createElement("div");
    overlay.className = "overlay card";
    overlay.hidden = true;

    const overImg = document.createElement("img");
    overImg.loading = "lazy";
    overImg.decoding = "async";
    overImg.alt = "";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "btn btn-icon overlay-close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.append(glyph("M5 5l14 14M19 5 5 19"));
    closeBtn.addEventListener("click", closeOverlay);

    overlay.append(overImg, closeBtn);
    stage.append(frame, prevBtn, nextBtn, cropBtn, overlay);

    const related = document.createElement("div");
    related.className = "related";
    related.hidden = true;

    const partBtn = document.createElement("button");
    partBtn.type = "button";
    partBtn.className = "btn btn-primary part-btn";
    partBtn.textContent = "Part";
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
      ind,
      indThumb,
      prevBtn,
      nextBtn,
      cropBtn,
      overlay,
      overImg,
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

    const rec = Q.jobById(state.jobId);
    if (!rec) {
      bounce();
      return;
    }

    const list = stepsOf(rec);
    if (!list.length) {
      bounce();
      return;
    }

    const my = ++enterGen;
    job = rec;
    manualRec = Q.manual(rec.manualId) || {};
    steps = list;
    cropped = true;

    const raw = params && params.step;
    const wanted = Number(raw);
    index = Number.isFinite(wanted) ? Math.max(0, Math.min(list.length - 1, Math.trunc(wanted))) : 0;

    applyKnownRaster(rec.manualId);
    paintRelated();
    await probePage(rec.manualId, pageOf(list[index]));
    if (my !== enterGen || !live) return;
    show();
  },

  leave() {
    live = false;
    closeOverlay();
    resetZoom();
    pointers.clear();
    window.removeEventListener("keydown", onKey);
  },
});
