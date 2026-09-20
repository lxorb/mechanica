import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../query.js";

const SCORE_FLOOR = 0.35;
const AUTO_MS = 600;

let root;
let bikeBtn;
let bikeImg;
let bikeName;
let camBtn;
let fileInput;
let meter;
let meterFill;
let systemsEl;
let partsEl;
let savedY = 0;
let restoreGen = 0;
let freezeY = false;
let prevScrollRestoration = null;
let lastBikeId = null;
let hitIds = new Set();
let autoTimer = 0;
let busy = false;

registerScreen("pick", {
  mount,
  enter,
  leave,
});

function mount(el) {
  root = el;
  root.replaceChildren();
  window.addEventListener("scroll", snapshotY, { passive: true });

  const strip = node("div", { class: "strip sheet" });

  bikeBtn = node("button", {
    type: "button",
    class: "who",
  });
  bikeBtn.addEventListener("click", () => {
    snapshotY();
    go("confirm");
  });
  bikeImg = node("img", {
    loading: "lazy",
    decoding: "async",
    alt: "",
    width: "44",
    height: "44",
  });
  bikeName = node("span", { class: "who-name" });
  bikeBtn.append(bikeImg, bikeName);

  camBtn = node("button", {
    type: "button",
    class: "btn btn-icon cam",
    "aria-label": "Photo part",
  });
  camBtn.append(cameraGlyph());
  camBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (busy) return;
    fileInput.click();
  });

  fileInput = node("input", {
    type: "file",
    accept: "image/*",
    capture: "environment",
    hidden: "",
    tabindex: "-1",
    "aria-hidden": "true",
  });
  fileInput.addEventListener("change", onFile);

  strip.append(bikeBtn, camBtn, fileInput);

  meter = node("div", { class: "meter", hidden: "" });
  meterFill = node("i");
  meter.append(meterFill);

  systemsEl = node("div", { class: "bins systems", role: "list" });
  partsEl = node("div", { class: "bins parts", role: "list" });

  root.append(strip, meter, systemsEl, partsEl);
}

function bounceIdentify() {
  queueMicrotask(() => go("identify", { replace: true }));
}

function enter() {
  if (!state.bikeId) {
    bounceIdentify();
    return;
  }
  const rec = Q.bike(state.bikeId);
  if (rec) {
    enterReady(rec);
    return;
  }
  Q.loadCatalog()
    .then(() => {
      if (!state.bikeId) {
        bounceIdentify();
        return;
      }
      const row = Q.bike(state.bikeId);
      if (!row) bounceIdentify();
      else enterReady(row);
    })
    .catch(() => bounceIdentify());
}

function enterReady(rec) {
  freezeY = true;
  lockHistoryScroll();
  if (state.bikeId !== lastBikeId) {
    savedY = 0;
    hitIds = new Set();
    lastBikeId = state.bikeId;
  }

  const sysList = Q.systems(state.bikeId);
  if (state.systemId && !sysList.some((s) => s.id === state.systemId)) {
    set({ systemId: null });
  }

  paint(rec, sysList);
  restoreScroll();
}

function leave() {
  restoreGen += 1;
  freezeY = false;
  snapshotY();
  clearAuto();
  if (!state.bikeId) unlockHistoryScroll();
}

function snapshotY() {
  if (freezeY) return;
  const section = root && root.closest("[data-screen]");
  if (section && !section.hidden) savedY = window.scrollY;
}

function lockHistoryScroll() {
  if (prevScrollRestoration == null) {
    prevScrollRestoration = history.scrollRestoration || "auto";
  }
  try {
    history.scrollRestoration = "manual";
  } catch {
    /* ignore */
  }
}

function unlockHistoryScroll() {
  if (prevScrollRestoration == null) return;
  try {
    history.scrollRestoration = prevScrollRestoration;
  } catch {
    /* ignore */
  }
  prevScrollRestoration = null;
}

function restoreScroll() {
  const y = savedY;
  const gen = ++restoreGen;
  freezeY = true;
  window.scrollTo(0, y);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (gen !== restoreGen) return;
      window.scrollTo(0, y);
      freezeY = false;
    });
  });
}

function paint(rec, sysList) {
  rec = rec || Q.bike(state.bikeId);
  sysList = sysList || (state.bikeId ? Q.systems(state.bikeId) : []);
  if (!rec) return;

  const label = `${rec.make} ${rec.model} · ${rec.year}`;
  bikeImg.src = Q.asset(rec.thumb || rec.image);
  bikeImg.alt = `${rec.make} ${rec.model}`;
  bikeName.textContent = label;
  bikeBtn.setAttribute("aria-label", label);

  fillGrid(systemsEl, sysList, (sys) => {
    const n = Q.partsFor(state.bikeId, sys.id).length;
    const on = sys.id === state.systemId;
    return tile({
      id: sys.id,
      name: sys.name,
      src: Q.asset(sys.thumb || sys.image),
      stamp: String(n),
      on,
      pressed: on,
      onClick: () => pickSystem(sys.id),
    });
  });

  const parts = state.systemId ? Q.partsFor(state.bikeId, state.systemId) : [];
  fillGrid(partsEl, parts, (part) => {
    const job = Q.job(state.bikeId, part.id);
    const stamp = printedStamp(job);
    return tile({
      id: part.id,
      name: part.name,
      src: Q.asset(part.thumb || part.image),
      stamp,
      on: hitIds.has(part.id) || part.id === state.partId,
      pressed: false,
      onClick: () => pickPart(part.id),
    });
  });
}

function pickSystem(systemId) {
  clearAuto();
  hitIds = new Set();
  set({ systemId });
  paint();
  partsEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function pickPart(partId) {
  clearAuto();
  const job = Q.job(state.bikeId, partId);
  if (!job) return;
  snapshotY();
  set({ partId, jobId: job.id });
  emit("part", { partId });
  go("book");
}

async function onFile() {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (!file || busy) return;

  busy = true;
  camBtn.disabled = true;
  setMeter(0);

  const url = URL.createObjectURL(file);
  try {
    const { loadPartModel, classifyPart } = await import("../vision.js");
    await loadPartModel((v) => setMeter(v));
    const img = new Image();
    img.decoding = "async";
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = url;
    });
    try {
      if (img.decode) await img.decode();
    } catch {
      /* decode is best-effort */
    }
    setMeter(1);
    const rows = await classifyPart(img);
    applyVision(rows);
  } catch {
    /* vision failure never breaks the screen */
  } finally {
    URL.revokeObjectURL(url);
    busy = false;
    camBtn.disabled = false;
    hideMeter();
  }
}

function applyVision(rows) {
  if (!Array.isArray(rows) || !state.bikeId) return;
  const top = rows.find((row) => row && row.score >= SCORE_FLOOR);
  if (!top) return;

  const ids = (Array.isArray(top.partIds) ? top.partIds : []).filter((id) =>
    Boolean(Q.job(state.bikeId, id))
  );
  if (!ids.length) return;

  const first = Q.part(ids[0]);
  const systemId = first && first.systemId;
  if (!systemId) return;

  clearAuto();
  hitIds = new Set(ids);
  set({ systemId });

  if (ids.length === 1) {
    const job = Q.job(state.bikeId, ids[0]);
    if (job) set({ partId: ids[0], jobId: job.id });
    emit("part", { partId: ids[0] });
    paint();
    scrollHits();
    autoTimer = window.setTimeout(() => {
      autoTimer = 0;
      snapshotY();
      go("book");
    }, AUTO_MS);
    return;
  }

  paint();
  scrollHits();
}

function scrollHits() {
  const hit = partsEl.querySelector(".tile.is-on");
  if (hit) hit.scrollIntoView({ block: "center", behavior: "smooth" });
  else partsEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function printedStamp(job) {
  if (!job) return "";
  const raw = job.printedPage;
  if (raw == null || String(raw).trim() === "") return "";
  const printed = String(raw).trim();
  if (/^\d+$/.test(printed)) return `p.${printed}`;
  return printed;
}

function fillGrid(box, items, make) {
  box.replaceChildren();
  for (const item of items) {
    const child = make(item);
    child.setAttribute("role", "listitem");
    box.append(child);
  }
}

function tile({ id, name, src, stamp, on, pressed, onClick }) {
  const btn = node("button", {
    type: "button",
    class: on ? "tile is-on" : "tile",
    "data-id": id,
    "aria-pressed": pressed ? "true" : "false",
  });
  const img = node("img", {
    loading: "lazy",
    decoding: "async",
    src,
    alt: name,
  });
  btn.append(img);
  btn.setAttribute("aria-label", stamp ? `${name}, ${stamp}` : name);
  if (stamp) {
    const mark = node("span", { class: "stamp", "aria-hidden": "true" });
    mark.textContent = stamp;
    btn.append(mark);
  }
  const cap = node("span", { class: "cap" });
  cap.textContent = name;
  btn.append(cap);
  btn.addEventListener("click", onClick);
  return btn;
}

function cameraGlyph() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute(
    "d",
    "M8 5h2l1-2h2l1 2h4v13H4V5h4zm4 3.25A3.75 3.75 0 1 0 12 15.75 3.75 3.75 0 0 0 12 8.25zm0 2A1.75 1.75 0 1 1 12 13.75 1.75 1.75 0 0 1 12 10.25z"
  );
  svg.append(path);
  return svg;
}

function setMeter(value) {
  meter.hidden = false;
  const pct = Math.max(0, Math.min(1, Number(value) || 0)) * 100;
  meterFill.style.width = `${pct}%`;
}

function hideMeter() {
  meter.hidden = true;
  meterFill.style.width = "0%";
}

function clearAuto() {
  if (autoTimer) {
    window.clearTimeout(autoTimer);
    autoTimer = 0;
  }
}

function node(tag, attrs) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  return el;
}
