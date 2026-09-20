import { state, set, go, registerScreen } from "../bus.js";
import * as Q from "../query.js";

const SVG = "http://www.w3.org/2000/svg";
const PINCH_MAX = 4;
const TAP = 10;
const COVER_PAGE = 1;
const els = {};

let live = false;
let ovScale = 1;
let ovTx = 0;
let ovTy = 0;
let ovFrameW = 0;
let ovFrameH = 0;
let ovContentW = 0;
let ovContentH = 0;
const ovPointers = new Map();
let ovPinch0 = 1;
let ovScale0 = 1;
let ovPinchContent = { x: 0, y: 0 };
let ovPan0 = { x: 0, y: 0 };
let ovPt0 = { x: 0, y: 0 };
let ovDidPinch = false;
let ovDidPan = false;
let ovFocus = null;

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

function bookGlyph() {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const spine = document.createElementNS(SVG, "path");
  spine.setAttribute("fill", "currentColor");
  spine.setAttribute("d", "M3 5h4v14H3z");
  const cover = document.createElementNS(SVG, "path");
  cover.setAttribute("fill", "currentColor");
  cover.setAttribute("d", "M8 4h13v16H8z");
  svg.append(spine, cover);
  return svg;
}

function preload(src) {
  if (!src) return;
  const img = new Image();
  img.decoding = "async";
  img.src = src;
}

function bounce() {
  queueMicrotask(() => go("identify", { replace: true }));
}

function bikeOf(id) {
  const rec = Q.bike(id);
  if (rec) return rec;
  const bag = globalThis.HandyInjectBikes;
  if (bag && typeof bag === "object" && bag[id]) return bag[id];
  const one = globalThis.HandyInjectBike;
  if (one && one.id === id) return one;
  return null;
}

function manualIdOf(rec) {
  const mid = rec && rec.manualId;
  if (mid == null || mid === "") return null;
  return mid;
}

function bikeHasManual(id, rec) {
  if (typeof Q.hasManual === "function" && Q.bike(id)) return Boolean(Q.hasManual(id));
  const mid = manualIdOf(rec);
  if (!mid) return false;
  return Boolean(Q.manual(mid));
}

function diagramIndex(man) {
  const n = Number(man && man.diagramPage);
  if (Number.isFinite(n) && n >= 1) return Math.trunc(n);
  return COVER_PAGE;
}

function diagramSrcOf(rec) {
  const mid = manualIdOf(rec);
  if (!mid) return "";
  return Q.pageUrl(mid, diagramIndex(Q.manual(mid)));
}

function ovReset() {
  ovScale = 1;
  ovTx = 0;
  ovTy = 0;
  ovPointers.clear();
  ovDidPinch = false;
  ovDidPan = false;
  if (els.overZoom) els.overZoom.style.transform = "";
}

function ovPoint(clientX, clientY) {
  const rect = els.overFrame.getBoundingClientRect();
  return { x: clientX - rect.left, y: clientY - rect.top };
}

function ovClamp() {
  const sw = ovContentW * ovScale;
  const sh = ovContentH * ovScale;
  if (sw <= ovFrameW) ovTx = (ovFrameW - sw) / 2;
  else ovTx = Math.min(0, Math.max(ovFrameW - sw, ovTx));
  if (sh <= ovFrameH) ovTy = (ovFrameH - sh) / 2;
  else ovTy = Math.min(0, Math.max(ovFrameH - sh, ovTy));
}

function ovApply() {
  if (!els.overZoom) return;
  els.overZoom.style.transform = `translate(${ovTx}px, ${ovTy}px) scale(${ovScale})`;
}

function ovLayout() {
  if (!els.overFrame || !els.overlay || els.overlay.hidden) return;
  ovFrameW = els.overFrame.clientWidth;
  ovFrameH = els.overFrame.clientHeight;
  const nw = els.overImg.naturalWidth || 1;
  const nh = els.overImg.naturalHeight || 1;
  const fit = Math.min(ovFrameW / nw, ovFrameH / nh);
  ovContentW = Math.max(1, nw * fit);
  ovContentH = Math.max(1, nh * fit);
  els.overZoom.style.width = `${ovContentW}px`;
  els.overZoom.style.height = `${ovContentH}px`;
  ovClamp();
  ovApply();
}

function closeOverlay() {
  if (!els.overlay || els.overlay.hidden) return;
  els.overlay.hidden = true;
  els.overImg.removeAttribute("src");
  els.overImg.alt = "";
  ovReset();
  const back = ovFocus;
  ovFocus = null;
  if (back && typeof back.focus === "function") back.focus();
}

function openOverlay() {
  const src = els.refImg.getAttribute("src");
  if (!src) return;
  ovFocus = document.activeElement;
  els.overImg.loading = "lazy";
  els.overImg.decoding = "async";
  els.overImg.alt = els.refCap.textContent || "";
  els.overImg.src = src;
  ovReset();
  els.overlay.hidden = false;
  if (els.overImg.complete && els.overImg.naturalWidth) ovLayout();
  els.closeBtn.focus();
}

function ovCapturePinch() {
  const pts = [...ovPointers.values()];
  if (pts.length < 2) return;
  const [a, b] = pts;
  ovPinch0 = Math.hypot(a.x - b.x, a.y - b.y) || 1;
  ovScale0 = ovScale;
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const pt = ovPoint(mid.x, mid.y);
  ovPinchContent = {
    x: (pt.x - ovTx) / ovScale,
    y: (pt.y - ovTy) / ovScale,
  };
  ovDidPinch = true;
}

function onOvPointerDown(event) {
  if (!live || els.overlay.hidden) return;
  if (event.button && event.button !== 0) return;
  ovPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  try {
    els.overFrame.setPointerCapture(event.pointerId);
  } catch {
    /* ignore */
  }
  if (ovPointers.size === 1) {
    ovPt0 = { x: event.clientX, y: event.clientY };
    ovPan0 = { x: ovTx, y: ovTy };
    ovDidPinch = false;
    ovDidPan = false;
  } else if (ovPointers.size >= 2) {
    ovCapturePinch();
  }
}

function onOvPointerMove(event) {
  if (!ovPointers.has(event.pointerId)) return;
  ovPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (ovPointers.size >= 2) {
    const [a, b] = [...ovPointers.values()];
    const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
    const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const next = Math.min(PINCH_MAX, Math.max(1, ovScale0 * (dist / ovPinch0)));
    const pt = ovPoint(mid.x, mid.y);
    ovScale = next;
    ovTx = pt.x - ovPinchContent.x * ovScale;
    ovTy = pt.y - ovPinchContent.y * ovScale;
    ovClamp();
    ovApply();
    ovDidPinch = true;
    return;
  }
  const canPan =
    ovScale > 1.01 ||
    ovContentW * ovScale > ovFrameW + 1 ||
    ovContentH * ovScale > ovFrameH + 1;
  if (canPan) {
    const ndx = event.clientX - ovPt0.x;
    const ndy = event.clientY - ovPt0.y;
    if (Math.hypot(ndx, ndy) >= TAP) ovDidPan = true;
    ovTx = ovPan0.x + ndx;
    ovTy = ovPan0.y + ndy;
    ovClamp();
    ovApply();
  }
}

function onOvPointerUp(event) {
  if (!ovPointers.has(event.pointerId)) return;
  ovPointers.delete(event.pointerId);
  try {
    els.overFrame.releasePointerCapture(event.pointerId);
  } catch {
    /* ignore */
  }
  if (ovPointers.size === 0) {
    if (ovScale < 1.02) {
      ovScale = 1;
      ovClamp();
      ovApply();
    }
    return;
  }
  const rest = [...ovPointers.values()][0];
  ovPt0 = { x: rest.x, y: rest.y };
  ovPan0 = { x: ovTx, y: ovTy };
  if (ovPointers.size >= 2) ovCapturePinch();
}

function ovZoomAt(clientX, clientY, nextScale) {
  const pt = ovPoint(clientX, clientY);
  const newScale = Math.min(PINCH_MAX, Math.max(1, nextScale));
  const cx = (pt.x - ovTx) / ovScale;
  const cy = (pt.y - ovTy) / ovScale;
  ovScale = newScale;
  ovTx = pt.x - cx * ovScale;
  ovTy = pt.y - cy * ovScale;
  ovClamp();
  ovApply();
}

function onOvWheel(event) {
  if (!live || els.overlay.hidden) return;
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    ovZoomAt(event.clientX, event.clientY, ovScale * (event.deltaY < 0 ? 1.12 : 0.9));
  }
}

function onKey(event) {
  if (!live) return;
  if (event.key === "Escape" && !els.overlay.hidden) {
    event.preventDefault();
    closeOverlay();
  }
}

function onResize() {
  if (!live || els.overlay.hidden) return;
  ovLayout();
}

function paintBike(rec) {
  const label = [rec.make, rec.model].filter(Boolean).join(" ");
  const src = rec.image ? Q.asset(rec.image) : "";

  els.name.textContent = label;

  if (rec.year == null || rec.year === "") {
    els.yearStamp.hidden = true;
    els.yearStamp.textContent = "";
  } else {
    els.yearStamp.hidden = false;
    els.yearStamp.textContent = String(rec.year);
  }

  if (rec.cc == null || rec.cc === "") {
    els.ccStamp.hidden = true;
    els.ccStamp.textContent = "";
  } else {
    els.ccStamp.hidden = false;
    els.ccStamp.textContent = `${rec.cc} cc`;
  }

  if (rec.category) {
    els.catStamp.hidden = false;
    els.catStamp.textContent = String(rec.category);
  } else {
    els.catStamp.hidden = true;
    els.catStamp.textContent = "";
  }

  els.bikeImg.alt = label;
  if (src) {
    preload(src);
    els.bikeImg.src = src;
  } else {
    els.bikeImg.removeAttribute("src");
  }

  const shot = state.photoUrl;
  if (shot) {
    els.shotImg.alt = label;
    els.shotImg.src = Q.asset(shot);
    els.shotImg.hidden = false;
  } else {
    els.shotImg.hidden = true;
    els.shotImg.removeAttribute("src");
    els.shotImg.alt = "";
  }

  return { label, src };
}

function paintManual(id, rec) {
  const has = bikeHasManual(id, rec);
  els.yes.hidden = !has;
  els.none.hidden = has;
  if (els.body) els.body.classList.toggle("has-ref", has);

  if (!has) {
    els.ref.hidden = true;
    els.refImg.removeAttribute("src");
    els.refImg.alt = "";
    els.refCap.textContent = "";
    closeOverlay();
    return;
  }

  const man = Q.manual(manualIdOf(rec));
  const title = man && man.title ? String(man.title) : "";
  const diagramSrc = diagramSrcOf(rec);

  els.refCap.textContent = title;
  els.refImg.alt = title;
  if (diagramSrc) {
    preload(diagramSrc);
    els.refImg.src = diagramSrc;
  } else {
    els.refImg.removeAttribute("src");
  }
  els.ref.hidden = false;
}

registerScreen("confirm", {
  mount(root) {
    const photo = document.createElement("div");
    photo.className = "confirm-photo";

    const bikeImg = document.createElement("img");
    bikeImg.className = "confirm-bike";
    bikeImg.loading = "lazy";
    bikeImg.decoding = "async";
    bikeImg.alt = "";

    const shotImg = document.createElement("img");
    shotImg.className = "confirm-shot card";
    shotImg.loading = "lazy";
    shotImg.decoding = "async";
    shotImg.alt = "";
    shotImg.hidden = true;

    photo.append(bikeImg, shotImg);

    const body = document.createElement("div");
    body.className = "confirm-body";

    const sheet = document.createElement("div");
    sheet.className = "sheet confirm-id";

    const name = document.createElement("h1");
    name.className = "confirm-name";

    const stamps = document.createElement("div");
    stamps.className = "confirm-stamps";

    const yearStamp = document.createElement("span");
    yearStamp.className = "stamp";

    const ccStamp = document.createElement("span");
    ccStamp.className = "stamp";

    const catStamp = document.createElement("span");
    catStamp.className = "stamp";
    catStamp.hidden = true;

    stamps.append(yearStamp, ccStamp, catStamp);
    sheet.append(name, stamps);

    const ref = document.createElement("button");
    ref.type = "button";
    ref.className = "card confirm-ref";
    ref.hidden = true;
    ref.addEventListener("click", openOverlay);

    const refImg = document.createElement("img");
    refImg.className = "confirm-diagram";
    refImg.loading = "lazy";
    refImg.decoding = "async";
    refImg.alt = "";

    const refCap = document.createElement("span");
    refCap.className = "confirm-ref-cap";

    ref.append(refImg, refCap);

    const prompt = document.createElement("p");
    prompt.className = "confirm-prompt";
    prompt.textContent = "IS THIS YOUR BIKE?";

    const actions = document.createElement("div");
    actions.className = "confirm-actions";

    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "btn btn-primary";
    yes.setAttribute("aria-label", "Yes");
    yes.append(glyph("M4 12.5 9.5 18 20 6"));
    yes.addEventListener("click", () => go("pick"));

    const none = document.createElement("button");
    none.type = "button";
    none.className = "btn confirm-none";
    none.setAttribute("aria-label", "No manual");
    none.disabled = true;
    none.hidden = true;
    none.append(bookGlyph());

    const yesSlot = document.createElement("div");
    yesSlot.className = "confirm-yes-slot";
    yesSlot.append(yes, none);

    const no = document.createElement("button");
    no.type = "button";
    no.className = "btn";
    no.setAttribute("aria-label", "No");
    no.append(glyph("M5 5l14 14M19 5L5 19"));
    no.addEventListener("click", () => {
      set({ bikeId: null, photoUrl: null });
      go("identify");
    });

    actions.append(yesSlot, no);
    body.append(sheet, ref, prompt, actions);

    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const overFrame = document.createElement("div");
    overFrame.className = "confirm-over-frame";

    const overZoom = document.createElement("div");
    overZoom.className = "confirm-over-zoom";

    const overImg = document.createElement("img");
    overImg.loading = "lazy";
    overImg.decoding = "async";
    overImg.alt = "";
    overImg.addEventListener("load", ovLayout);

    overZoom.append(overImg);
    overFrame.append(overZoom);

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "btn btn-icon confirm-over-close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.append(glyph("M5 5l14 14M19 5L5 19"));
    closeBtn.addEventListener("click", closeOverlay);

    overlay.append(overFrame, closeBtn);
    root.append(photo, body, overlay);

    Object.assign(els, {
      body,
      bikeImg,
      shotImg,
      name,
      yearStamp,
      ccStamp,
      catStamp,
      ref,
      refImg,
      refCap,
      yes,
      none,
      no,
      overlay,
      overFrame,
      overZoom,
      overImg,
      closeBtn,
    });

    overFrame.addEventListener("pointerdown", onOvPointerDown);
    overFrame.addEventListener("pointermove", onOvPointerMove);
    overFrame.addEventListener("pointerup", onOvPointerUp);
    overFrame.addEventListener("pointercancel", onOvPointerUp);
    overFrame.addEventListener("wheel", onOvWheel, { passive: false });
    window.addEventListener("resize", onResize);

    const rec = bikeOf(state.bikeId);
    if (rec?.image) preload(Q.asset(rec.image));
    const diagramSrc = rec ? diagramSrcOf(rec) : "";
    if (diagramSrc) preload(diagramSrc);
  },

  enter() {
    if (!live) window.addEventListener("keydown", onKey);
    live = true;
    closeOverlay();

    const id = state.bikeId;
    if (id == null || id === "") {
      bounce();
      return;
    }

    const rec = bikeOf(id);
    if (!rec) {
      bounce();
      return;
    }

    paintBike(rec);
    paintManual(id, rec);
  },

  leave() {
    live = false;
    closeOverlay();
    window.removeEventListener("keydown", onKey);
  },
});
