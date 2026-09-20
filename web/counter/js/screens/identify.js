import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../query.js";
import { buildIndex } from "../search.js";
import * as vision from "../vision.js";

const MATCH_FLOOR = 0.5;
const GAP = 8;
const OVERSCAN = 4;
const COL_BREAK = "(min-width: 900px)";
const FIXTURE_URL = "../tools/fixtures/collection.sample.json";
const CAMERA_PATH =
  "M9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9zm3 13.2a3.7 3.7 0 1 1 0-7.4 3.7 3.7 0 0 1 0 7.4z";
const BOOK_PATH =
  "M12 5.2C10.4 4.2 8.2 3.5 6 3.5 4.4 3.5 2.8 3.9 1.5 4.5v14c1.2-.6 2.8-1 4.5-1 2.2 0 4.4.7 6 1.7 1.6-1 3.8-1.7 6-1.7 1.7 0 3.3.4 4.5 1v-14C21.2 3.9 19.6 3.5 18 3.5c-2.2 0-4.4.7-6 1.7z";

let root;
let searchEl;
let shotEl;
let queryEl;
let fileEl;
let progressEl;
let boardEl;
let windowEl;
let visionGen = 0;
let lastBlob = null;
let inputRaf = 0;
let scrollRaf = 0;
let shown = [];
let focusIndex = -1;
let lastStart = 0;
let live = false;
let colMq;
let fixtureRoster = null;
let fixturePromise = null;
let cachedM = null;

const pool = [];

const io =
  typeof IntersectionObserver === "function"
    ? new IntersectionObserver(onIntersect, { root: null, rootMargin: "400px 0px", threshold: 0.01 })
    : null;

function el(tag, attrs) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  return node;
}

function svgPath(d, size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute("d", d);
  svg.append(path);
  return svg;
}

function cameraGlyph() {
  return svgPath(CAMERA_PATH, 22);
}

function bookGlyph() {
  return svgPath(BOOK_PATH, 14);
}

function wantsFixture() {
  try {
    return new URLSearchParams(location.search).get("fixture") === "1";
  } catch {
    return false;
  }
}

function roster() {
  if (fixtureRoster) return fixtureRoster;
  const all = Q.bikes();
  return Array.isArray(all) ? all : [];
}

function loadFixtureIfNeeded() {
  if (!wantsFixture()) return Promise.resolve();
  if (fixtureRoster) return Promise.resolve();
  if (fixturePromise) return fixturePromise;
  fixturePromise = fetch(FIXTURE_URL)
    .then((res) => (res.ok ? res.json() : null))
    .then((json) => {
      const bikes = json && Array.isArray(json.bikes) ? json.bikes : null;
      if (!bikes || !bikes.length) return;
      fixtureRoster = bikes;
      buildIndex(bikes);
    })
    .catch(() => {})
    .then(() => {});
  return fixturePromise;
}

function bikeHasManual(bike) {
  return Q.hasManual(bike.id) || !!bike.manualId;
}

function bikesFor(text) {
  const empty = !String(text ?? "").trim();
  const list = empty ? roster().slice() : Q.findBikes(text, { limit: 60 }).slice();
  const id = state.bikeId;
  if (!id || !empty) return list;
  const i = list.findIndex((bike) => bike.id === id);
  if (i > 0) {
    const [hit] = list.splice(i, 1);
    list.unshift(hit);
  }
  return list;
}

function choose(bikeId) {
  set({ bikeId });
  emit("bike", { bikeId });
  go("confirm");
}

function matchId(match) {
  if (!match || typeof match !== "object") return null;
  const score = Number(match.score);
  if (!(score >= MATCH_FLOOR)) return null;
  const bikeId = match.bikeId || match.id || match.bike?.id;
  return bikeId || null;
}

function showProgress(on) {
  progressEl.hidden = !on;
}

function showShot(url) {
  if (url) {
    shotEl.src = url;
    shotEl.hidden = false;
  } else {
    shotEl.removeAttribute("src");
    shotEl.hidden = true;
  }
}

function paintLabel(node, bike, text) {
  const label = `${bike.make ?? ""} ${bike.model ?? ""}`.trim();
  const ranges = text && String(text).trim() ? Q.highlight(bike, text) : [];
  node.classList.toggle("id-hit", ranges.length > 0);
  node.replaceChildren();
  if (!ranges.length) {
    node.textContent = label;
    return;
  }
  let i = 0;
  for (const range of ranges) {
    const a = Math.max(0, range.start);
    const b = Math.min(label.length, range.end);
    if (b <= a) continue;
    if (a > i) node.append(document.createTextNode(label.slice(i, a)));
    const mark = document.createElement("b");
    mark.textContent = label.slice(a, b);
    node.append(mark);
    i = b;
  }
  if (i < label.length) node.append(document.createTextNode(label.slice(i)));
}

function onIntersect(entries) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const img = entry.target;
    const src = img.dataset.src;
    if (src && img.getAttribute("src") !== src) img.src = src;
    if (io) io.unobserve(img);
  }
}

function makeTile() {
  const btn = el("button", { type: "button", className: "tile" });
  const img = el("img", {
    loading: "lazy",
    decoding: "async",
    fetchpriority: "low",
    alt: "",
  });
  img.fetchPriority = "low";
  const manual = el("span", { className: "stamp id-manual", "aria-label": "Manual" });
  manual.append(bookGlyph());
  const year = el("span", { className: "stamp id-year" });
  const name = el("span", { className: "id-name" });
  btn.append(img, manual, year, name);
  const rec = { btn, img, manual, year, name, bikeId: "" };
  btn.addEventListener("click", () => {
    const id = btn.dataset.id;
    if (id) choose(id);
  });
  btn.addEventListener("focus", () => {
    const i = Number(btn.dataset.index);
    if (Number.isFinite(i)) focusIndex = i;
  });
  return rec;
}

function ensurePool(n) {
  while (pool.length < n) {
    const rec = makeTile();
    pool.push(rec);
    windowEl.append(rec.btn);
  }
}

function colsNow() {
  if (colMq) return colMq.matches ? 4 : 2;
  return window.innerWidth >= 900 ? 4 : 2;
}

function measure() {
  const width = boardEl.clientWidth;
  const cols = colsNow();
  const tileW = Math.max(0, (width - GAP * (cols - 1)) / cols);
  const tileH = tileW * (2 / 3);
  const rowH = tileH + GAP;
  cachedM = { width, cols, tileW, tileH, rowH };
  boardEl.style.setProperty("--id-tile-h", `${tileH}px`);
  boardEl.style.setProperty("--id-cols", String(cols));
  return cachedM;
}

function scrollIndexIntoView(i) {
  const m = cachedM || measure();
  const row = Math.floor(i / m.cols);
  const boardTop = boardEl.getBoundingClientRect().top + window.scrollY;
  const tileTop = boardTop + row * m.rowH;
  const tileBot = tileTop + m.tileH;
  const y = window.scrollY;
  const vh = window.innerHeight;
  if (tileTop < y) window.scrollTo(0, tileTop);
  else if (tileBot > y + vh) window.scrollTo(0, tileBot - vh);
}

function bindTile(rec, bike, index, text) {
  rec.btn.hidden = false;
  rec.btn.dataset.id = bike.id;
  rec.btn.dataset.index = String(index);
  rec.year.textContent = String(bike.year ?? "");
  rec.manual.hidden = !bikeHasManual(bike);
  paintLabel(rec.name, bike, text);

  const next = Q.asset(bike.thumb || bike.image) || "";
  if (rec.bikeId !== bike.id) {
    rec.bikeId = bike.id;
    rec.img.removeAttribute("src");
    rec.img.dataset.src = next;
    if (io) {
      io.unobserve(rec.img);
      if (next) io.observe(rec.img);
    } else if (next) {
      rec.img.src = next;
    }
  } else {
    rec.img.dataset.src = next;
    if (!io && next && rec.img.getAttribute("src") !== next) rec.img.src = next;
  }
}

function paintWindow() {
  if (!boardEl || !live) return;
  const list = shown;
  const m = measure();
  const rows = Math.ceil(list.length / m.cols) || 0;
  const height = rows ? rows * m.tileH + Math.max(0, rows - 1) * GAP : 0;
  boardEl.style.height = `${height}px`;

  if (!list.length || !m.tileH || !m.width) {
    lastStart = 0;
    windowEl.style.transform = "translate3d(0,0,0)";
    for (const rec of pool) rec.btn.hidden = true;
    return;
  }

  const boardTop = boardEl.getBoundingClientRect().top + window.scrollY;
  const viewTop = window.scrollY;
  const viewBot = viewTop + window.innerHeight;
  const relTop = viewTop - boardTop;
  const relBot = viewBot - boardTop;
  let startRow = Math.floor(relTop / m.rowH) - OVERSCAN;
  let endRow = Math.ceil(relBot / m.rowH) + OVERSCAN;
  if (startRow < 0) startRow = 0;
  if (endRow > rows) endRow = rows;
  if (startRow > endRow) startRow = endRow;

  windowEl.style.transform = `translate3d(0, ${startRow * m.rowH}px, 0)`;

  const start = startRow * m.cols;
  const end = Math.min(list.length, endRow * m.cols);
  const n = Math.max(0, end - start);
  lastStart = start;
  ensurePool(n);

  const text = queryEl.value;
  const active = document.activeElement;
  const keepFocus = active && windowEl.contains(active);

  for (let i = 0; i < pool.length; i++) {
    const rec = pool[i];
    if (i >= n) {
      rec.btn.hidden = true;
      continue;
    }
    bindTile(rec, list[start + i], start + i, text);
  }

  if (keepFocus && focusIndex >= start && focusIndex < end) {
    const rec = pool[focusIndex - start];
    if (rec && document.activeElement !== rec.btn) rec.btn.focus({ preventScroll: true });
  }
}

function refreshList() {
  shown = bikesFor(queryEl.value);
  paintWindow();
}

function scheduleSearch() {
  if (inputRaf) return;
  inputRaf = requestAnimationFrame(() => {
    inputRaf = 0;
    refreshList();
  });
}

function scheduleScroll() {
  if (scrollRaf) return;
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0;
    paintWindow();
  });
}

function focusAt(i) {
  if (i < 0 || i >= shown.length) return;
  focusIndex = i;
  scrollIndexIntoView(i);
  paintWindow();
  const rec = pool[focusIndex - lastStart];
  if (rec && !rec.btn.hidden) rec.btn.focus({ preventScroll: true });
}

function onEnter(event) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  const first = bikesFor(queryEl.value)[0];
  if (first) choose(first.id);
}

function onRootKey(event) {
  if (event.target === queryEl) {
    if (event.key === "Enter") onEnter(event);
    else if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAt(0);
    }
    return;
  }
  if (!event.target.closest || !event.target.closest(".tile")) return;
  const cols = cachedM?.cols || colsNow();
  let delta = 0;
  if (event.key === "ArrowLeft") delta = -1;
  else if (event.key === "ArrowRight") delta = 1;
  else if (event.key === "ArrowUp") delta = -cols;
  else if (event.key === "ArrowDown") delta = cols;
  else return;
  event.preventDefault();
  if (focusIndex < 0) focusAt(0);
  else focusAt(focusIndex + delta);
}

async function onFile() {
  const file = fileEl.files && fileEl.files[0];
  fileEl.value = "";
  if (!file) return;

  const gen = ++visionGen;
  if (lastBlob) URL.revokeObjectURL(lastBlob);
  const url = URL.createObjectURL(file);
  lastBlob = url;
  set({ photoUrl: url });
  showProgress(true);

  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    if (gen !== visionGen) return;

    let match = null;
    if (typeof vision.identifyBike === "function") {
      const bag = Q.catalog()?.bikes ?? [];
      match = await vision.identifyBike(img, bag);
    }
    if (gen !== visionGen) return;

    const bikeId = matchId(match);
    if (bikeId) {
      showShot(null);
      choose(bikeId);
      return;
    }

    showShot(url);
    queryEl.focus();
  } catch {
    if (gen !== visionGen) return;
    showShot(url);
    queryEl.focus();
  } finally {
    if (gen === visionGen) showProgress(false);
  }
}

function attachLive() {
  if (live) return;
  live = true;
  window.addEventListener("scroll", scheduleScroll, { passive: true });
  window.addEventListener("resize", scheduleScroll);
  if (colMq && colMq.addEventListener) colMq.addEventListener("change", scheduleScroll);
}

function detachLive() {
  live = false;
  window.removeEventListener("scroll", scheduleScroll);
  window.removeEventListener("resize", scheduleScroll);
  if (colMq && colMq.removeEventListener) colMq.removeEventListener("change", scheduleScroll);
  if (io) io.disconnect();
}

registerScreen("identify", {
  mount(mountRoot) {
    root = mountRoot;
    colMq = window.matchMedia(COL_BREAK);

    searchEl = el("div", { className: "id-search" });
    shotEl = el("img", {
      className: "id-shot",
      loading: "lazy",
      decoding: "async",
      alt: "",
      hidden: true,
    });
    queryEl = el("input", {
      className: "id-q",
      type: "search",
      autocomplete: "off",
      enterkeyhint: "go",
      placeholder: "Honda CB650R",
    });
    const cam = el("button", {
      type: "button",
      className: "btn btn-icon",
      "aria-label": "Photo",
    });
    cam.append(cameraGlyph());
    fileEl = el("input", {
      className: "id-file",
      type: "file",
      accept: "image/*",
      capture: "environment",
      hidden: true,
      tabindex: "-1",
    });
    searchEl.append(shotEl, queryEl, cam, fileEl);

    progressEl = el("div", { className: "id-progress", hidden: true });
    const dock = el("div", { className: "id-dock" });
    dock.append(searchEl, progressEl);

    boardEl = el("div", { className: "id-board" });
    windowEl = el("div", { className: "id-window" });
    boardEl.append(windowEl);
    root.replaceChildren(dock, boardEl);

    queryEl.addEventListener("input", scheduleSearch);
    root.addEventListener("keydown", onRootKey);
    cam.addEventListener("click", () => fileEl.click());
    fileEl.addEventListener("change", onFile);

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(scheduleScroll).observe(boardEl);
    }
  },
  enter() {
    set({ partId: null, jobId: null, systemId: null });
    showShot(state.photoUrl);
    for (const rec of pool) rec.bikeId = "";
    attachLive();
    loadFixtureIfNeeded().then(() => {
      if (!live) return;
      refreshList();
    });
  },
  leave() {
    if (inputRaf) cancelAnimationFrame(inputRaf);
    if (scrollRaf) cancelAnimationFrame(scrollRaf);
    inputRaf = 0;
    scrollRaf = 0;
    visionGen += 1;
    showProgress(false);
    detachLive();
  },
});
