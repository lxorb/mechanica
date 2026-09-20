import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../ttm.js";
import * as vision from "../vision.js";

const GAP = 8;
const ROW_H = 96;
const OVERSCAN = 3;
const FIND_LIMIT = 2400;
const ROW_LIMIT = 400;
const CHIP_LIMIT = 60;
const MAKE_CHIPS = 24;
const THIN_ROWS = 8;
const SUGGEST_MS = 150;
const VIN_MS = 120;
const VIN_MIN = 6;
const VIN_MAX = 17;
const CONF_PIPS = 5;
const MATCH_FLOOR = 0.5;
const CAMERA_PATH =
  "M9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9zm3 13.2a3.7 3.7 0 1 1 0-7.4 3.7 3.7 0 0 1 0 7.4z";
const BOOK_PATH =
  "M12 5.2C10.4 4.2 8.2 3.5 6 3.5 4.4 3.5 2.8 3.9 1.5 4.5v14c1.2-.6 2.8-1 4.5-1 2.2 0 4.4.7 6 1.7 1.6-1 3.8-1.7 6-1.7 1.7 0 3.3.4 4.5 1v-14C21.2 3.9 19.6 3.5 18 3.5c-2.2 0-4.4.7-6 1.7z";
const RANK = { ready: 0, ondemand: 1, none: 2 };

let root;
let searchEl;
let shotEl;
let shotImg;
let queryEl;
let vinBtn;
let fileEl;
let progressEl;
let chipsEl;
let boardEl;
let windowEl;

let live = false;
let shownRows = [];
let rosterRowsCache = null;
let rosterIds = null;

let textQ = "";
let vinQ = "";
let vinMode = false;
let vinHit = null;
let vinTimer = 0;
let vinGen = 0;
let subOn = false;

let photoUrl = null;
let photoRows = [];
let photoGen = 0;

let suggestFor = "";
let suggestBikes = [];
let suggestTimer = 0;
let suggestCtl = null;

let inputRaf = 0;
let scrollRaf = 0;
let focusRow = -1;
let focusChip = -1;
let lastStart = 0;

const pool = [];
const remembered = Object.create(null);

/* roster */

function roster() {
  const list = Q.bikes();
  return Array.isArray(list) ? list : [];
}

function knownId(id) {
  if (!rosterIds) {
    rosterIds = new Set();
    for (const bike of roster()) if (bike && bike.id) rosterIds.add(bike.id);
  }
  return rosterIds.has(id);
}

function remember(bike) {
  if (!bike || typeof bike.id !== "string") return;
  remembered[bike.id] = bike;
  const bag = globalThis.HandyInjectBikes;
  if (bag && typeof bag === "object") bag[bike.id] = bike;
  else globalThis.HandyInjectBikes = Object.assign(Object.create(null), remembered);
}

function bikeOfCandidate(entry) {
  if (!entry || typeof entry !== "object") return null;
  if (entry.bike && typeof entry.bike === "object") return entry.bike;
  const id = entry.bikeId || entry.id;
  if (typeof id !== "string") return null;
  return Q.bike(id) || remembered[id] || null;
}

/* rows */

function norm(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function group(list, conf) {
  const map = new Map();
  for (const bike of list) {
    if (!bike || typeof bike.id !== "string") continue;
    const key = `${norm(bike.make)}|${norm(bike.model)}`;
    let row = map.get(key);
    if (!row) {
      row = {
        key,
        bike,
        label: `${bike.make ?? ""} ${bike.model ?? ""}`.trim(),
        years: [],
        at: new Map(),
        rank: RANK.none,
        conf: 0,
      };
      map.set(key, row);
    }
    const mState = Q.manualState(bike);
    const year = bike.year == null ? "" : String(bike.year);
    const seen = row.at.get(year);
    if (seen) {
      if (RANK[mState] < RANK[seen.state]) {
        seen.state = mState;
        seen.bike = bike;
      }
    } else {
      const entry = { year, bike, state: mState };
      row.at.set(year, entry);
      row.years.push(entry);
    }
    if (RANK[mState] < row.rank) row.rank = RANK[mState];
    if (conf) {
      const score = conf.get(bike.id) ?? 0;
      if (score > row.conf) row.conf = score;
    }
  }
  const rows = [...map.values()];
  for (const row of rows) {
    row.years.sort((a, z) => Number(z.year) - Number(a.year));
    if (row.years.length > CHIP_LIMIT) row.years.length = CHIP_LIMIT;
  }
  return rows;
}

function rosterRows() {
  if (rosterRowsCache) return rosterRowsCache;
  const rows = group(roster());
  rows.sort((a, z) => a.rank - z.rank);
  rosterRowsCache = rows;
  return rows;
}

function computeRows() {
  if (vinMode) return vinHit ? group([vinHit]) : [];
  const text = textQ.trim();
  if (!text) {
    if (photoRows.length) return photoRows;
    const rows = rosterRows();
    const id = state.bikeId;
    if (!id) return rows;
    const i = rows.findIndex((row) => [...row.at.values()].some((entry) => entry.bike.id === id));
    if (i <= 0) return rows;
    const out = rows.slice();
    out.unshift(out.splice(i, 1)[0]);
    return out;
  }
  const hits = Q.findBikes(text, { limit: FIND_LIMIT }) || [];
  const extra = suggestFor === text ? suggestBikes : [];
  return group(extra.length ? hits.concat(extra) : hits).slice(0, ROW_LIMIT);
}

function bestYear(row) {
  for (const entry of row.years) if (entry.state === "ready") return entry;
  for (const entry of row.years) if (entry.state === "ondemand") return entry;
  return row.years[0] || null;
}

/* /catalog/suggest: bikes the API knows and this session has not loaded */

function scheduleSuggest(text) {
  if (suggestTimer) clearTimeout(suggestTimer);
  suggestTimer = 0;
  if (!text.trim() || !Q.online()) return;
  suggestTimer = setTimeout(() => {
    suggestTimer = 0;
    runSuggest(text);
  }, SUGGEST_MS);
}

async function runSuggest(text) {
  if (shownRows.length >= THIN_ROWS) return;
  if (suggestCtl) suggestCtl.abort();
  const ctl = new AbortController();
  suggestCtl = ctl;
  let list;
  try {
    const res = await fetch(`${Q.apiBase()}/catalog/suggest?q=${encodeURIComponent(text)}`, { signal: ctl.signal });
    if (!res.ok) return;
    list = await res.json();
  } catch {
    return;
  }
  if (ctl !== suggestCtl || !Array.isArray(list)) return;
  const fresh = [];
  for (const bike of list) {
    if (!bike || typeof bike.id !== "string" || knownId(bike.id)) continue;
    remember(bike);
    fresh.push(bike);
  }
  suggestFor = text;
  suggestBikes = fresh;
  if (fresh.length && !vinMode && textQ.trim() === text.trim()) refreshList(true);
}

/* dom */

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

function showProgress(on) {
  progressEl.hidden = !on;
}

function showShot(url) {
  if (url) {
    shotImg.src = url;
    shotEl.hidden = false;
  } else {
    shotImg.removeAttribute("src");
    shotEl.hidden = true;
  }
}

function paintLabel(node, row, text) {
  const label = row.label;
  const ranges = text && text.trim() ? Q.highlight(row.bike, text) : [];
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

function makeRow() {
  const box = el("div", { className: "card id-row" });
  const top = el("div", { className: "id-row-top" });
  const mark = el("span", { className: "stamp id-mark", "aria-label": "Manual" });
  mark.append(svgPath(BOOK_PATH, 13));
  const name = el("span", { className: "id-name" });
  const conf = el("span", { className: "id-conf", "aria-hidden": "true" });
  for (let i = 0; i < CONF_PIPS; i++) conf.append(el("i"));
  top.append(mark, name, conf);
  const years = el("div", { className: "id-years" });
  box.append(top, years);
  windowEl.append(box);
  return { box, mark, name, conf, years, chips: [] };
}

function chipOf(rec, i) {
  let chip = rec.chips[i];
  if (chip) return chip;
  chip = el("button", { type: "button", className: "id-year" });
  chip.addEventListener("click", () => {
    if (chip.entry) pick(chip.entry.bike, chip.entry.state);
  });
  chip.addEventListener("focus", () => {
    focusRow = Number(rec.box.dataset.index);
    focusChip = i;
  });
  rec.chips[i] = chip;
  rec.years.append(chip);
  return chip;
}

function bindRow(rec, row, index, text) {
  rec.box.hidden = false;
  rec.box.dataset.index = String(index);
  rec.mark.hidden = row.rank !== RANK.ready;
  paintLabel(rec.name, row, text);

  const pips = Math.round(row.conf * CONF_PIPS);
  rec.conf.hidden = !row.conf;
  const lamps = rec.conf.children;
  for (let i = 0; i < lamps.length; i++) lamps[i].className = i < pips ? "on" : "";

  const years = row.years;
  const off = !Q.online();
  for (let i = 0; i < years.length; i++) {
    const raw = years[i];
    const state = raw.state === "none" && row.rank < RANK.none ? "ondemand" : raw.state;
    const entry = state === raw.state ? raw : { ...raw, state };
    const chip = chipOf(rec, i);
    chip.hidden = false;
    chip.entry = entry;
    chip.textContent = entry.year;
    chip.className = `id-year is-${entry.state}`;
    chip.disabled = entry.state === "none" && off;
  }
  for (let i = years.length; i < rec.chips.length; i++) rec.chips[i].hidden = true;
  rec.years.scrollLeft = 0;
}

function ensurePool(n) {
  while (pool.length < n) pool.push(makeRow());
}

function paintWindow() {
  if (!boardEl || !live) return;
  const list = shownRows;
  const total = list.length;
  const rowH = ROW_H + GAP;
  boardEl.style.height = total ? `${total * ROW_H + (total - 1) * GAP}px` : "0px";

  if (!total) {
    lastStart = 0;
    windowEl.style.transform = "translate3d(0,0,0)";
    for (const rec of pool) rec.box.hidden = true;
    return;
  }

  const boardTop = boardEl.getBoundingClientRect().top + window.scrollY;
  const relTop = window.scrollY - boardTop;
  const relBot = relTop + window.innerHeight;
  let start = Math.floor(relTop / rowH) - OVERSCAN;
  let end = Math.ceil(relBot / rowH) + OVERSCAN;
  if (start < 0) start = 0;
  if (end > total) end = total;
  if (start > end) start = end;

  windowEl.style.transform = `translate3d(0, ${start * rowH}px, 0)`;
  const n = end - start;
  ensurePool(n);
  lastStart = start;

  const text = vinMode ? "" : textQ;
  const active = document.activeElement;
  const keepFocus = active && windowEl.contains(active);

  for (let i = 0; i < pool.length; i++) {
    if (i >= n) {
      pool[i].box.hidden = true;
      continue;
    }
    bindRow(pool[i], list[start + i], start + i, text);
  }

  if (keepFocus && focusRow >= start && focusRow < end) {
    const rec = pool[focusRow - start];
    const chip = rec && rec.chips[focusChip];
    if (chip && !chip.hidden && document.activeElement !== chip) chip.focus({ preventScroll: true });
  }
}

function refreshList(keepScroll) {
  shownRows = computeRows();
  if (!keepScroll && window.scrollY > 0) window.scrollTo(0, 0);
  paintWindow();
  signalSub();
}

/** VIN, a photo or a typed query are sub-states: the header back button pops them. */
function signalSub() {
  const on = vinMode || Boolean(photoUrl) || textQ.trim().length > 0;
  if (on === subOn) return;
  subOn = on;
  emit("substate", { screen: "identify", on });
}

function backOut() {
  if (vinMode) {
    setVinMode(false);
    return true;
  }
  if (photoUrl) {
    clearPhoto();
    paintChips();
    refreshList();
    return true;
  }
  if (textQ.trim()) {
    textQ = "";
    queryEl.value = "";
    paintChips();
    refreshList();
    return true;
  }
  return false;
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

/* make chips */

function makeList() {
  const count = new Map();
  for (const row of rosterRows()) {
    const make = row.bike.make;
    if (!make) continue;
    const hit = count.get(make) || { n: 0, ready: 0 };
    hit.n += row.years.length;
    if (row.rank === RANK.ready) hit.ready += 1;
    count.set(make, hit);
  }
  return [...count.entries()]
    .sort((a, z) => z[1].ready - a[1].ready || z[1].n - a[1].n || a[0].localeCompare(z[0]))
    .map(([make]) => make);
}

function matchingMakes(text) {
  const head = norm(text);
  const all = makeList();
  if (!head) return all.slice(0, MAKE_CHIPS);
  const out = all.filter((make) => norm(make).startsWith(head));
  return out.length > 1 ? out.slice(0, MAKE_CHIPS) : [];
}

function paintChips() {
  const text = textQ.trim();
  // Only while the user is typing: an empty box must not preview makes it did not ask for.
  const show = !vinMode && !photoUrl && text.length > 0 && roster().length > 0;
  const list = show ? matchingMakes(text) : [];
  chipsEl.hidden = list.length === 0;
  if (!list.length) {
    chipsEl.replaceChildren();
    return;
  }
  const nodes = [];
  for (const make of list) {
    const chip = el("button", { type: "button", className: "btn id-make", text: make });
    chip.addEventListener("click", () => {
      textQ = `${make} `;
      queryEl.value = textQ;
      queryEl.focus();
      onQuery();
    });
    nodes.push(chip);
  }
  chipsEl.replaceChildren(...nodes);
}

/* actions */

function pick(bike, mState) {
  if (!bike) return;
  if (mState === "none" && !Q.online()) return;
  remember(bike);
  const vin = vinMode && vinHit && vinHit.id === bike.id && vinQ.length >= VIN_MIN ? vinQ : null;
  set({ bikeId: bike.id, vin });
  emit("bike", { bikeId: bike.id, vin });
  go("confirm");
}

function clearPhoto() {
  photoGen += 1;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
  photoRows = [];
  if (state.photoUrl) set({ photoUrl: null });
  showShot(null);
  showProgress(false);
}

function cleanVin(value) {
  return String(value ?? "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, VIN_MAX);
}

function onQuery() {
  if (vinMode) {
    const clean = cleanVin(queryEl.value);
    if (clean !== queryEl.value) queryEl.value = clean;
    vinQ = clean;
    scheduleVin(clean);
    scheduleSearch();
    return;
  }
  textQ = queryEl.value;
  if (textQ.trim() && photoUrl) clearPhoto();
  scheduleSuggest(textQ);
  paintChips();
  scheduleSearch();
}

function scheduleVin(clean) {
  if (vinTimer) clearTimeout(vinTimer);
  vinTimer = 0;
  vinGen += 1;
  if (clean.length < VIN_MIN) {
    vinHit = null;
    return;
  }
  const gen = vinGen;
  vinTimer = setTimeout(async () => {
    vinTimer = 0;
    let res;
    try {
      res = await Q.identifyVin(clean);
    } catch {
      return;
    }
    if (gen !== vinGen) return;
    vinHit = bikeFromHit(res);
    if (vinHit) remember(vinHit);
    refreshList(true);
  }, VIN_MS);
}

function bikeFromHit(res) {
  if (!res) return null;
  if (res.bike && typeof res.bike === "object") return res.bike;
  if (Array.isArray(res)) return bikeOfCandidate(res[0]);
  if (Array.isArray(res.candidates)) return bikeOfCandidate(res.candidates[0]);
  return null;
}

function setVinMode(on) {
  if (vinMode === on) return;
  vinMode = on;
  searchEl.classList.toggle("is-vin", on);
  vinBtn.setAttribute("aria-pressed", String(on));
  queryEl.setAttribute("placeholder", on ? "VIN" : "Search here");
  queryEl.setAttribute("enterkeyhint", on ? "done" : "go");
  queryEl.setAttribute("autocapitalize", on ? "characters" : "off");
  queryEl.setAttribute("maxlength", on ? String(VIN_MAX) : "120");
  if (on) {
    clearPhoto();
    queryEl.value = vinQ;
    scheduleVin(vinQ);
  } else {
    queryEl.value = textQ;
  }
  paintChips();
  queryEl.focus();
  refreshList();
}

function candidates(res) {
  if (Array.isArray(res)) return res;
  if (res && Array.isArray(res.candidates)) return res.candidates;
  return [];
}

async function localVision(file, gen) {
  if (typeof vision.isVisionAvailable !== "function" || !vision.isVisionAvailable()) return [];
  let url = "";
  try {
    url = URL.createObjectURL(file);
    const img = new Image();
    img.src = url;
    await img.decode();
    if (gen !== photoGen) return [];
    const match = await vision.identifyBike(img, roster());
    const score = Number(match && match.score);
    if (!(score >= MATCH_FLOOR)) return [];
    const id = match.bikeId || match.id || (match.bike && match.bike.id);
    return id ? [{ bikeId: id, confidence: score }] : [];
  } catch {
    return [];
  } finally {
    if (url) URL.revokeObjectURL(url);
  }
}

async function onFile() {
  const file = fileEl.files && fileEl.files[0];
  fileEl.value = "";
  if (!file) return;

  setVinMode(false);
  const gen = ++photoGen;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = URL.createObjectURL(file);
  photoRows = [];
  textQ = "";
  queryEl.value = "";
  set({ photoUrl });
  showShot(photoUrl);
  showProgress(true);
  paintChips();
  refreshList();

  let list = [];
  try {
    list = candidates(await Q.identifyPhoto(file));
  } catch {
    list = [];
  }
  if (gen !== photoGen) return;

  if (!list.length) list = await localVision(file, gen);
  if (gen !== photoGen) return;

  const conf = new Map();
  const bikes = [];
  for (const entry of list) {
    const bike = bikeOfCandidate(entry);
    if (!bike) continue;
    remember(bike);
    bikes.push(bike);
    const score = Number(entry.confidence);
    conf.set(bike.id, Number.isFinite(score) ? score : 0);
  }
  const rows = group(bikes, conf);
  rows.sort((a, z) => z.conf - a.conf || a.rank - z.rank);
  photoRows = rows;
  showProgress(false);
  refreshList();
}

function focusAt(row, col) {
  if (row < 0 || row >= shownRows.length) return;
  const years = shownRows[row].years;
  if (!years.length) return;
  const i = Math.min(Math.max(0, col), years.length - 1);
  focusRow = row;
  focusChip = i;
  const rowH = ROW_H + GAP;
  const boardTop = boardEl.getBoundingClientRect().top + window.scrollY;
  const top = boardTop + row * rowH;
  if (top < window.scrollY) window.scrollTo(0, Math.max(0, top - GAP));
  else if (top + ROW_H > window.scrollY + window.innerHeight) {
    window.scrollTo(0, top + ROW_H - window.innerHeight);
  }
  paintWindow();
  const rec = pool[row - lastStart];
  const chip = rec && rec.chips[i];
  if (chip && !chip.hidden) chip.focus({ preventScroll: true });
}

function onRootKey(event) {
  if (event.target === queryEl) {
    if (event.key === "Enter") {
      event.preventDefault();
      const row = shownRows[0];
      const entry = row && bestYear(row);
      if (entry) pick(entry.bike, entry.state);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      focusAt(0, 0);
    }
    return;
  }
  if (!event.target.closest || !event.target.closest(".id-year")) return;
  let row = focusRow;
  let col = focusChip;
  if (event.key === "ArrowLeft") col -= 1;
  else if (event.key === "ArrowRight") col += 1;
  else if (event.key === "ArrowUp") row -= 1;
  else if (event.key === "ArrowDown") row += 1;
  else return;
  event.preventDefault();
  focusAt(row, col);
}

function attachLive() {
  if (live) return;
  live = true;
  window.addEventListener("scroll", scheduleScroll, { passive: true });
  window.addEventListener("resize", scheduleScroll);
}

function detachLive() {
  live = false;
  window.removeEventListener("scroll", scheduleScroll);
  window.removeEventListener("resize", scheduleScroll);
}

registerScreen("identify", {
  mount(mountRoot) {
    root = mountRoot;

    searchEl = el("div", { className: "id-search" });
    shotEl = el("button", { type: "button", className: "id-shot", "aria-label": "Photo", hidden: true });
    shotImg = el("img", { loading: "lazy", decoding: "async", alt: "" });
    shotEl.append(shotImg);

    queryEl = el("input", {
      className: "id-q",
      type: "text",
      autocomplete: "off",
      autocorrect: "off",
      autocapitalize: "off",
      spellcheck: "false",
      enterkeyhint: "go",
      maxlength: "120",
      placeholder: "Search here",
    });

    vinBtn = el("button", {
      type: "button",
      className: "btn btn-icon id-vin",
      "aria-label": "VIN",
      "aria-pressed": "false",
      text: "VIN",
    });

    const cam = el("button", { type: "button", className: "btn btn-icon", "aria-label": "Photo" });
    cam.append(svgPath(CAMERA_PATH, 22));

    fileEl = el("input", {
      className: "id-file",
      type: "file",
      accept: "image/*",
      capture: "environment",
      hidden: true,
      tabindex: "-1",
    });

    searchEl.append(shotEl, queryEl, vinBtn, cam, fileEl);

    progressEl = el("div", { className: "id-progress", hidden: true });
    const dock = el("div", { className: "id-dock" });
    dock.append(searchEl, progressEl);

    chipsEl = el("div", { className: "id-chips", hidden: true });
    boardEl = el("div", { className: "id-board" });
    windowEl = el("div", { className: "id-window" });
    boardEl.append(windowEl);
    root.replaceChildren(dock, chipsEl, boardEl);

    queryEl.addEventListener("input", onQuery);
    root.addEventListener("keydown", onRootKey);
    vinBtn.addEventListener("click", () => setVinMode(!vinMode));
    cam.addEventListener("click", () => fileEl.click());
    shotEl.addEventListener("click", () => {
      clearPhoto();
      paintChips();
      refreshList();
    });
    fileEl.addEventListener("change", onFile);

    if (typeof ResizeObserver === "function") new ResizeObserver(scheduleScroll).observe(boardEl);
  },

  enter() {
    set({ partId: null, jobId: null, systemId: null });
    if (!state.photoUrl) clearPhoto();
    else showShot(photoUrl);
    attachLive();
    paintChips();
    refreshList(true);
    Promise.resolve(Q.loadCatalog()).then(() => {
      if (!live) return;
      rosterIds = null;
      rosterRowsCache = null;
      paintChips();
      refreshList(true);
    });
  },

  back() {
    return backOut();
  },

  leave() {
    if (inputRaf) cancelAnimationFrame(inputRaf);
    if (scrollRaf) cancelAnimationFrame(scrollRaf);
    inputRaf = 0;
    scrollRaf = 0;
    showProgress(false);
    detachLive();
  },
});
