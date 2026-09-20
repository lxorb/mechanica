/**
 * Step 1 - Identify. Owner: landing agent.
 * Files: this, ../../css/screens/identify.css, ./confirm.js, ../../css/screens/confirm.css.
 *
 * The landing page is a search and nothing else: one big centred field, a camera glyph
 * inside it, a VIN link under it. index.html and counter.css belong to another agent, so
 * the landing folds the step rail away through a body class (`id-landing`) instead.
 *
 * First keystroke -> model cards: photo, make and model verbatim, the year span, a mark
 * when a manual exists. Tap a card -> that model's catalog years as chips, unless the
 * query already pinned a year. A query that pins make + model + year to a single bike
 * jumps to Confirm on Enter or once it has been the only candidate for 400 ms.
 * A photo -> /identify/photo -> Confirm with the candidates in state.altIds.
 * A VIN resolves as you type and jumps at 17 characters.
 *
 * Contracts: ../ttm.js (findBikes, bikes, bike, manualState, identifyPhoto, identifyVin,
 * highlight, asset, online), ../bus.js (state/set/go/emit, the back() hook).
 */

import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../ttm.js";
import * as vision from "../vision.js";
import { tokens as splitTokens, fieldTokens } from "../search.js";

const FIND_LIMIT = 2400;
const CARD_LIMIT = 60;
const CHIP_LIMIT = 80;
const MAKE_CHIPS = 12;
const THIN_ROWS = 6;
const SUGGEST_MS = 150;
const VIN_MS = 120;
const VIN_MAX = 17;
/** Shortest run of VIN characters that a known WMI turns into a VIN rather than a model. */
const VIN_PART_MIN = 9;
/** A VIN never uses I, O or Q. */
const VIN_CHARS = /^[A-HJ-NPR-Z0-9]+$/;
/** World manufacturer identifiers; the catalog's own `vins` prefixes are added at runtime. */
const WMI = ["VBK", "WB1", "JH2", "JYA", "JS1", "JKA", "ZDM", "1HD", "SMT", "ME1"];
const JUMP_MS = 400;
const ALT_MAX = 8;
const MATCH_FLOOR = 0.5;
const YEAR_RE = /^(?:19|20)\d{2}$/;
const RANK = { ready: 0, ondemand: 1, none: 2 };
const DASH = "–";
/** Every picture frame on this screen is 3:2. */
const FRAME = 1.5;
/** Past this much off the frame, cover would cut the bike in half: letterbox instead. */
const FIT_OFF = 1.34;

const SVG = "http://www.w3.org/2000/svg";
const CAMERA_PATH =
  "M9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9zm3 13.2a3.7 3.7 0 1 1 0-7.4 3.7 3.7 0 0 1 0 7.4z";
const BOOK_PATH =
  "M12 5.2C10.4 4.2 8.2 3.5 6 3.5 4.4 3.5 2.8 3.9 1.5 4.5v14c1.2-.6 2.8-1 4.5-1 2.2 0 4.4.7 6 1.7 1.6-1 3.8-1.7 6-1.7 1.7 0 3.3.4 4.5 1v-14C21.2 3.9 19.6 3.5 18 3.5c-2.2 0-4.4.7-6 1.7z";
const BIKE_STROKE = [
  "M1 16a4 4 0 1 0 8 0 4 4 0 1 0-8 0",
  "M15 16a4 4 0 1 0 8 0 4 4 0 1 0-8 0",
  "M5 16l3-5h6l3 5M8 11h7M13 11l2-3h3",
];

let root;
let dockEl;
let searchEl;
let queryEl;
let shotEl;
let shotImg;
let vinTag;
let fileEl;
let progressEl;
let chipsEl;
let gridEl;
let chooserEl;
let chooserArt;
let chooserImg;
let chooserMake;
let chooserModel;
let chooserYears;

let live = false;
let modelIndex = null;
let makesCache = null;
let wmiCache = null;
let rosterIds = null;

let rows = [];
let pin = "";
let chooserRow = null;
let landing = false;

let textQ = "";
let vinQ = "";
let vinMode = false;
let vinHit = null;
let vinTimer = 0;
let vinGen = 0;
let subOn = false;

let photoUrl = null;
let photoGen = 0;

let suggestFor = "";
let suggestBikes = [];
let suggestTimer = 0;
let suggestCtl = null;

let jumpTimer = 0;
let jumpedFor = null;
let inputRaf = 0;

const cards = [];
const chips = [];
const remembered = Object.create(null);

/* ------------------------------------------------------------------ roster */

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

function norm(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function keyOf(bike) {
  return `${norm(bike.make)}|${norm(bike.model)}`;
}

/* ------------------------------------------------- make + model -> one card */

function group(list) {
  const map = new Map();
  for (const bike of list) {
    if (!bike || typeof bike.id !== "string") continue;
    const key = keyOf(bike);
    let row = map.get(key);
    if (!row) {
      row = { key, bike, years: [], at: new Map(), rank: RANK.none, span: "" };
      map.set(key, row);
    }
    if (!(row.bike.hero || row.bike.image || row.bike.thumb) && (bike.hero || bike.image || bike.thumb)) row.bike = bike;
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
  }
  const out = [...map.values()];
  for (const row of out) {
    row.years.sort((a, z) => Number(z.year) - Number(a.year));
    if (row.years.length > CHIP_LIMIT) row.years.length = CHIP_LIMIT;
    const last = row.years[row.years.length - 1];
    const first = row.years[0];
    row.span = !first ? "" : row.years.length > 1 ? `${last.year}${DASH}${first.year}` : first.year;
  }
  return out;
}

/** Every model in the roster, so a card always carries the model's full year span. */
function models() {
  if (modelIndex) return modelIndex;
  modelIndex = new Map();
  for (const row of group(roster())) modelIndex.set(row.key, row);
  return modelIndex;
}

function makeList() {
  if (makesCache) return makesCache;
  const count = new Map();
  for (const bike of roster()) {
    if (!bike || !bike.make) continue;
    const hit = count.get(bike.make) || { n: 0, ready: 0 };
    hit.n += 1;
    if (bike.manualId) hit.ready += 1;
    count.set(bike.make, hit);
  }
  makesCache = [...count.entries()]
    .sort((a, z) => z[1].ready - a[1].ready || z[1].n - a[1].n || a[0].localeCompare(z[0]))
    .map(([make]) => make);
  return makesCache;
}

/* -------------------------------------------------------------------- VIN */

/** WMI prefixes: the ten classic shapes plus every `vins` prefix the catalog carries. */
function wmiSet() {
  if (wmiCache) return wmiCache;
  const set = new Set(WMI);
  for (const bike of roster()) {
    if (!bike || !Array.isArray(bike.vins)) continue;
    for (const raw of bike.vins) {
      const p = String(raw ?? "")
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, "");
      if (p.length >= 3) set.add(p.slice(0, 3));
    }
  }
  wmiCache = set;
  return wmiCache;
}

/**
 * The one field tells a VIN from a model on its own. Spaces and dashes are stripped, so
 * "vbk jsa40 xxxxxxxxx" is the same 17 characters as "VBKJSA40XXXXXXXXX". A shorter run
 * counts only when it is one unbroken word behind a known WMI - "wb10n21 2025 gs" is three
 * words about a bike, not a half-typed chassis number. Returns "" for everything else.
 */
function vinOf(text) {
  const raw = String(text ?? "").trim();
  if (!raw) return "";
  const flat = raw.toUpperCase().replace(/[\s-]+/g, "");
  if (flat.length < VIN_PART_MIN || flat.length > VIN_MAX) return "";
  if (!VIN_CHARS.test(flat)) return "";
  if (flat.length === VIN_MAX) return flat;
  if (/\s/.test(raw)) return "";
  return wmiSet().has(flat.slice(0, 3)) ? flat : "";
}

/* ----------------------------------------------------------- query -> rows */

/** "2023 yamaha yzf" -> {year:"2023", rest:"yamaha yzf"}. A bare 19xx/20xx token only. */
function parseQuery(text) {
  const words = String(text ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  let year = "";
  const rest = [];
  for (const word of words) {
    if (!year && YEAR_RE.test(word)) year = word;
    else rest.push(word);
  }
  return { year, rest: rest.join(" ") };
}

function rowsFor(text) {
  const { year, rest } = parseQuery(text);
  const hits = Q.findBikes(rest || text, { limit: FIND_LIMIT }) || [];
  const extra = suggestFor === text ? suggestBikes : [];
  const index = models();
  const seen = new Set();
  const out = [];
  for (const bike of extra.length ? hits.concat(extra) : hits) {
    if (!bike || typeof bike.id !== "string") continue;
    const key = keyOf(bike);
    if (seen.has(key)) continue;
    seen.add(key);
    const row = index.get(key) || group([bike])[0];
    if (!row) continue;
    if (year && !row.at.has(year)) continue;
    out.push(row);
    if (out.length >= CARD_LIMIT) break;
  }
  // Models we can actually hand a manual to come first; relevance orders each group.
  out.sort((a, z) => a.rank - z.rank);
  return { year, out };
}

/** The model's own search tokens, so a whole-word match can be told from a fuzzy one. */
function tokensOf(row) {
  if (!row.tset) row.tset = fieldTokens(row.bike).general;
  return row.tset;
}

/**
 * "390 duke" matches KTM 390 Duke on whole tokens and KTM 1390 Super Duke R only on
 * trigrams; "r1300gs" is the whole folded model of the R 1300 GS and merely a prefix of
 * the GS Adventure. So a query is only pinned when exactly one model matches every one of
 * its words outright - anything looser leaves the cards up.
 */
function pinnedHit() {
  if (vinMode || photoUrl || !pin || !rows.length) return null;
  let cand = rows;
  if (cand.length > 1) {
    const qs = splitTokens(parseQuery(textQ).rest);
    if (!qs.length) return null;
    cand = rows.filter((row) => {
      const set = tokensOf(row);
      return qs.every((t) => set.has(t));
    });
  }
  if (cand.length !== 1) return null;
  const entry = cand[0].at.get(pin);
  return entry ? { row: cand[0], entry } : null;
}

function computeRows() {
  if (vinMode) {
    pin = "";
    return vinHit ? group([vinHit]) : [];
  }
  const text = textQ.trim();
  if (!text) {
    pin = "";
    return [];
  }
  const { year, out } = rowsFor(text);
  pin = year;
  return out;
}

/* -------------------------------------------------------------------- dom */

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

function svgFill(d, size) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute("d", d);
  svg.append(path);
  return svg;
}

function svgStroke(ds) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of ds) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.5");
    path.setAttribute("d", d);
    svg.append(path);
  }
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

function paintPart(node, value, ranges, offset) {
  node.replaceChildren();
  if (!ranges.length) {
    node.textContent = value;
    return;
  }
  let i = 0;
  for (const range of ranges) {
    const a = Math.max(0, range.start - offset);
    const b = Math.min(value.length, range.end - offset);
    if (b <= a) continue;
    if (a > i) node.append(document.createTextNode(value.slice(i, a)));
    const mark = document.createElement("b");
    mark.textContent = value.slice(a, b);
    node.append(mark);
    i = b;
  }
  if (i < value.length) node.append(document.createTextNode(value.slice(i)));
}

/** Q.highlight works over "make model", so the model's ranges sit one space past make. */
function paintName(makeEl, modelEl, row, text) {
  const make = String(row.bike.make ?? "");
  const model = String(row.bike.model ?? "");
  const ranges = text && text.trim() ? Q.highlight(row.bike, text) : [];
  paintPart(makeEl, make, ranges, 0);
  paintPart(modelEl, model, ranges, make ? make.length + 1 : 0);
}

/**
 * The catalog photos run from 0.56 to 2.05 wide: `cover` would crop a portrait shot down
 * to a wheel and a fairing. Anything close to the 3:2 frame fills it, centred; anything
 * further off is letterboxed whole onto the paper tile. Nothing is ever stretched.
 */
function fitArt(img) {
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  if (!w || !h) return;
  const ratio = w / h;
  const off = ratio > FRAME ? ratio / FRAME : FRAME / ratio;
  img.classList.toggle("is-fit", off > FIT_OFF);
}

function watchArt(img) {
  img.addEventListener("load", () => fitArt(img));
}

/**
 * Three sizes ship per bike: hero (1280), image (640), thumb (160). A card takes the hero
 * on a desktop-width grid and the 640 on a phone; the year chooser's tile takes the thumb.
 * Each order falls through to whatever sizes that bike actually has.
 */
const SIZES = {
  card: ["image", "thumb", "hero"],
  wide: ["hero", "image", "thumb"],
  tile: ["thumb", "image", "hero"],
};

const WIDE_Q = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(min-width: 980px)") : null;

function artSrc(bike, want) {
  if (!bike) return "";
  const order = SIZES[want === "card" && WIDE_Q && WIDE_Q.matches ? "wide" : want] || SIZES.card;
  for (const key of order) {
    if (bike[key]) return Q.asset(bike[key]);
  }
  return "";
}

function setArt(img, box, bike, want) {
  const src = artSrc(bike, want || "card");
  box.classList.toggle("is-bare", !src);
  if (!src) {
    img.removeAttribute("src");
    img.classList.remove("is-fit");
    img.hidden = true;
    return;
  }
  img.hidden = false;
  if (img.getAttribute("src") !== src) {
    img.classList.remove("is-fit");
    img.setAttribute("src", src);
  }
  if (img.complete) fitArt(img);
}

/* ------------------------------------------------------------------ cards */

function makeCard() {
  const box = el("button", { type: "button", className: "card id-card" });
  const art = el("span", { className: "id-art" });
  const img = el("img", { loading: "lazy", decoding: "async", alt: "" });
  watchArt(img);
  const ghost = el("span", { className: "id-ghost", "aria-hidden": "true" });
  ghost.append(svgStroke(BIKE_STROKE));
  const flag = el("span", { className: "id-flag", "aria-label": "Manual" });
  flag.append(svgFill(BOOK_PATH, 12));
  art.append(img, ghost, flag);
  const meta = el("span", { className: "id-meta" });
  const make = el("span", { className: "id-make" });
  const model = el("span", { className: "id-model" });
  const span = el("span", { className: "id-span" });
  meta.append(make, model, span);
  box.append(art, meta);
  const rec = { box, art, img, flag, make, model, span, row: null };
  box.addEventListener("click", () => {
    if (rec.row) openRow(rec.row);
  });
  gridEl.append(box);
  cards.push(rec);
  return rec;
}

function bindCard(rec, row, text) {
  rec.row = row;
  rec.box.hidden = false;
  setArt(rec.img, rec.art, row.bike, "card");
  rec.flag.hidden = row.rank === RANK.none;
  rec.flag.className = row.rank === RANK.ready ? "id-flag is-ready" : "id-flag is-ondemand";
  paintName(rec.make, rec.model, row, text);
  const hit = Boolean(pin) && row.at.has(pin);
  rec.span.textContent = hit ? pin : row.span;
  rec.span.className = hit ? "id-span is-pin" : "id-span";
  const label = `${row.bike.make ?? ""} ${row.bike.model ?? ""} ${hit ? pin : row.span}`;
  rec.box.setAttribute("aria-label", label.replace(/\s+/g, " ").trim());
}

function renderGrid() {
  const text = vinMode ? "" : textQ;
  const n = Math.min(rows.length, CARD_LIMIT);
  for (let i = 0; i < n; i++) {
    const rec = cards[i] || makeCard();
    bindCard(rec, rows[i], text);
  }
  for (let i = n; i < cards.length; i++) {
    cards[i].box.hidden = true;
    cards[i].row = null;
  }
  gridEl.hidden = n === 0 || Boolean(chooserRow);
}

/* ---------------------------------------------------------------- chooser */

function chipAt(i) {
  let chip = chips[i];
  if (chip) return chip;
  chip = el("button", { type: "button", className: "id-year" });
  chip.addEventListener("click", () => {
    if (chip.entry) choose(chip.entry);
  });
  chips[i] = chip;
  chooserYears.append(chip);
  return chip;
}

/** A model with a manual somewhere can usually be indexed for its other years too. */
function yearState(row, raw) {
  return raw.state === "none" && row.rank < RANK.none ? "ondemand" : raw.state;
}

function renderChooser() {
  const row = chooserRow;
  chooserEl.hidden = !row;
  if (!row) return;
  setArt(chooserImg, chooserArt, row.bike, "tile");
  chooserMake.textContent = row.bike.make ?? "";
  chooserModel.textContent = row.bike.model ?? "";
  const off = !Q.online();
  const years = row.years;
  for (let i = 0; i < years.length; i++) {
    const raw = years[i];
    const st = yearState(row, raw);
    const entry = st === raw.state ? raw : { ...raw, state: st };
    const chip = chipAt(i);
    chip.hidden = false;
    chip.entry = entry;
    chip.textContent = entry.year;
    chip.className = `id-year is-${entry.state}${entry.year === pin ? " is-pin" : ""}`;
    chip.disabled = entry.state === "none" && off;
  }
  for (let i = years.length; i < chips.length; i++) {
    chips[i].hidden = true;
    chips[i].entry = null;
  }
}

function openRow(row) {
  if (!row) return;
  const hit = pin ? row.at.get(pin) : null;
  if (hit) {
    choose({ ...hit, state: yearState(row, hit) });
    return;
  }
  if (row.years.length === 1) {
    const only = row.years[0];
    choose({ ...only, state: yearState(row, only) });
    return;
  }
  chooserRow = row;
  renderChooser();
  renderGrid();
  paintChips();
  syncLanding();
  signalSub();
  window.scrollTo(0, 0);
  const first = chips.find((chip) => chip && !chip.hidden && !chip.disabled);
  if (first) first.focus({ preventScroll: true });
}

function closeChooser() {
  if (!chooserRow) return false;
  chooserRow = null;
  renderChooser();
  renderGrid();
  paintChips();
  syncLanding();
  signalSub();
  return true;
}

/* -------------------------------------------------------------- make chips */

function matchingMakes(text) {
  const head = norm(text);
  if (!head) return [];
  const out = makeList().filter((make) => norm(make).startsWith(head));
  return out.length > 1 ? out.slice(0, MAKE_CHIPS) : [];
}

function paintChips() {
  const text = textQ.trim();
  const show = !vinMode && !photoUrl && !chooserRow && text.length > 0 && roster().length > 0;
  const list = show ? matchingMakes(text) : [];
  chipsEl.hidden = list.length === 0;
  if (!list.length) {
    chipsEl.replaceChildren();
    return;
  }
  const nodes = [];
  for (const make of list) {
    const chip = el("button", { type: "button", className: "btn id-make-chip", text: make });
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

/* -------------------------------------------------- /catalog/suggest top-up */

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
  if (rows.length >= THIN_ROWS) return;
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
  if (fresh.length && !vinMode && textQ.trim() === text.trim()) refresh(true);
}

/* ------------------------------------------------------------------ paint */

/** Nothing typed, no photo, no chooser: the page is only the field. */
function syncLanding() {
  const bare = !chooserRow && !photoUrl && !textQ.trim();
  if (bare === landing) return;
  landing = bare;
  document.body.classList.toggle("id-landing", bare);
}

/** VIN, a photo, the chooser or a typed query are sub-states the header Back pops. */
function signalSub() {
  const on = Boolean(photoUrl) || Boolean(chooserRow) || textQ.trim().length > 0;
  if (on === subOn) return;
  subOn = on;
  emit("substate", { screen: "identify", on });
}

function refresh(keepScroll) {
  rows = computeRows();
  if (chooserRow && !vinMode) {
    chooserRow = models().get(chooserRow.key) || chooserRow;
    renderChooser();
  }
  renderGrid();
  syncLanding();
  signalSub();
  if (!keepScroll && window.scrollY > 0) window.scrollTo(0, 0);
}

function scheduleSearch() {
  if (inputRaf) return;
  inputRaf = requestAnimationFrame(() => {
    inputRaf = 0;
    refresh();
    scheduleJump();
  });
}

/* ------------------------------------------------------------------ jumps */

function scheduleJump() {
  if (jumpTimer) clearTimeout(jumpTimer);
  jumpTimer = 0;
  const text = textQ.trim();
  if (!text || text === jumpedFor || !pinnedHit()) return;
  const wanted = text;
  jumpTimer = setTimeout(() => {
    jumpTimer = 0;
    if (!live || textQ.trim() !== wanted) return;
    const hit = pinnedHit();
    if (!hit) return;
    jumpedFor = wanted;
    choose({ ...hit.entry, state: yearState(hit.row, hit.entry) }, { confirm: true });
  }, JUMP_MS);
}

function choose(entry, opts) {
  if (!entry || !entry.bike) return;
  const bike = entry.bike;
  if (entry.state === "none" && !Q.online()) return;
  remember(bike);
  const vin = vinMode && vinHit && vinHit.id === bike.id ? vinQ : null;
  set({ bikeId: bike.id, vin, altIds: (opts && opts.alts) || [] });
  emit("bike", { bikeId: bike.id, vin });
  // Nothing left to confirm: the year was tapped by hand and the manual is already indexed.
  const straight = entry.state === "ready" && !photoUrl && !(opts && opts.confirm);
  go(straight ? "pick" : "confirm");
}

/* ----------------------------------------------------------------- actions */

function clearPhoto() {
  photoGen += 1;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null;
  if (state.photoUrl) set({ photoUrl: null });
  showShot(null);
  showProgress(false);
}

function onQuery() {
  textQ = queryEl.value;
  if (textQ.trim() && photoUrl) clearPhoto();
  chooserRow = null;
  renderChooser();
  jumpedFor = null;

  const found = vinOf(textQ);
  const wasVin = vinMode;
  vinMode = Boolean(found);
  if (vinMode !== wasVin) paintVin();
  if (vinMode) {
    if (found !== vinQ) {
      vinQ = found;
      scheduleVin(found);
    }
    paintChips();
    scheduleSearch();
    return;
  }
  if (wasVin) {
    vinQ = "";
    vinHit = null;
    vinGen += 1;
  }
  scheduleSuggest(textQ);
  paintChips();
  scheduleSearch();
}

/** The field itself says what it is reading: monospace, uppercase, a VIN tag inside it. */
function paintVin() {
  searchEl.classList.toggle("is-vin", vinMode);
  vinTag.hidden = !vinMode;
  queryEl.setAttribute("enterkeyhint", vinMode ? "done" : "go");
}

function scheduleVin(clean) {
  if (vinTimer) clearTimeout(vinTimer);
  vinTimer = 0;
  vinGen += 1;
  vinHit = null;
  if (!clean) return;
  const gen = vinGen;
  vinTimer = setTimeout(async () => {
    vinTimer = 0;
    let res;
    try {
      res = await Q.identifyVin(clean);
    } catch {
      return;
    }
    if (gen !== vinGen || !live) return;
    vinHit = bikeFromHit(res);
    if (vinHit) remember(vinHit);
    refresh(true);
    // A whole VIN pins make, model and year: nothing is left to choose, so it goes on.
    if (vinHit && clean.length === VIN_MAX && rows.length === 1) vinGo();
  }, VIN_MS);
}

function vinGo() {
  const row = rows[0];
  if (!row) return;
  const entry = row.at.get(String(vinHit && vinHit.year != null ? vinHit.year : "")) || row.years[0];
  if (entry) choose({ ...entry, state: yearState(row, entry) }, { confirm: true });
}

function bikeFromHit(res) {
  if (!res) return null;
  if (res.bike && typeof res.bike === "object") return res.bike;
  if (Array.isArray(res)) return bikeOfCandidate(res[0]);
  if (Array.isArray(res.candidates)) return bikeOfCandidate(res.candidates[0]);
  return null;
}

/** A photo replaces whatever was typed, so any VIN reading goes with it. */
function clearVin() {
  if (!vinMode && !vinQ) return;
  vinMode = false;
  vinQ = "";
  vinHit = null;
  vinGen += 1;
  paintVin();
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

  clearVin();
  const gen = ++photoGen;
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = URL.createObjectURL(file);
  textQ = "";
  queryEl.value = "";
  chooserRow = null;
  set({ photoUrl });
  showShot(photoUrl);
  showProgress(true);
  paintChips();
  renderChooser();
  refresh();

  let list = [];
  try {
    list = candidates(await Q.identifyPhoto(file));
  } catch {
    list = [];
  }
  if (gen !== photoGen) return;
  if (!list.length) list = await localVision(file, gen);
  if (gen !== photoGen) return;

  const picks = [];
  const seen = new Set();
  for (const entry of list) {
    const bike = bikeOfCandidate(entry);
    if (!bike || seen.has(bike.id)) continue;
    seen.add(bike.id);
    remember(bike);
    const score = Number(entry.confidence);
    picks.push({ bike, confidence: Number.isFinite(score) ? score : 0 });
  }
  showProgress(false);
  if (!picks.length) {
    refresh();
    return;
  }
  const alts = picks.slice(0, ALT_MAX);
  set({ altConf: alts.map((p) => p.confidence) });
  choose(
    { bike: alts[0].bike, year: String(alts[0].bike.year ?? ""), state: Q.manualState(alts[0].bike) },
    { confirm: true, alts: alts.map((p) => p.bike.id) }
  );
}

/* --------------------------------------------------------------- keyboard */

function focusCard(i) {
  const rec = cards[i];
  if (!rec || rec.box.hidden) return;
  rec.box.focus();
}

function gridCols() {
  const n = Math.min(rows.length, CARD_LIMIT);
  if (n < 2) return 1;
  const top = cards[0].box.offsetTop;
  let cols = 1;
  for (let i = 1; i < n; i++) {
    if (cards[i].box.offsetTop !== top) break;
    cols += 1;
  }
  return cols;
}

function onEnter() {
  if (vinMode) {
    if (rows.length) vinGo();
    return;
  }
  const hit = pinnedHit();
  if (hit) {
    jumpedFor = textQ.trim();
    choose({ ...hit.entry, state: yearState(hit.row, hit.entry) }, { confirm: true });
    return;
  }
  if (chooserRow) return;
  if (rows.length) openRow(rows[0]);
}

function onRootKey(event) {
  if (event.target === queryEl) {
    if (event.key === "Enter") {
      event.preventDefault();
      onEnter();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (chooserRow) {
        const first = chips.find((chip) => chip && !chip.hidden);
        if (first) first.focus();
      } else focusCard(0);
    }
    return;
  }
  const hit = event.target.closest && event.target.closest(".id-card, .id-year");
  if (!hit) return;
  if (hit.classList.contains("id-year")) {
    const open = chips.filter((chip) => chip && !chip.hidden);
    let i = open.indexOf(hit);
    if (i < 0) return;
    if (event.key === "ArrowLeft") i -= 1;
    else if (event.key === "ArrowRight") i += 1;
    else if (event.key === "ArrowUp") {
      event.preventDefault();
      queryEl.focus();
      return;
    } else return;
    event.preventDefault();
    const next = open[Math.min(Math.max(0, i), open.length - 1)];
    if (next) next.focus();
    return;
  }
  let i = cards.findIndex((rec) => rec.box === hit);
  if (i < 0) return;
  const cols = gridCols();
  if (event.key === "ArrowLeft") i -= 1;
  else if (event.key === "ArrowRight") i += 1;
  else if (event.key === "ArrowUp") i -= cols;
  else if (event.key === "ArrowDown") i += cols;
  else return;
  event.preventDefault();
  if (i < 0) {
    queryEl.focus();
    return;
  }
  focusCard(Math.min(i, Math.min(rows.length, CARD_LIMIT) - 1));
}

function backOut() {
  if (closeChooser()) return true;
  if (photoUrl) {
    clearPhoto();
    paintChips();
    refresh();
    return true;
  }
  if (textQ.trim()) {
    textQ = "";
    jumpedFor = null;
    queryEl.value = "";
    clearVin();
    paintChips();
    refresh();
    queryEl.focus();
    return true;
  }
  return false;
}

/* ------------------------------------------------------------------ screen */

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
      placeholder: "Search",
      "aria-label": "Search",
    });

    const cam = el("button", { type: "button", className: "id-cam", "aria-label": "Photo" });
    cam.append(svgFill(CAMERA_PATH, 24));

    fileEl = el("input", {
      className: "id-file",
      type: "file",
      accept: "image/*",
      capture: "environment",
      hidden: true,
      tabindex: "-1",
    });

    vinTag = el("span", { className: "id-vin-tag", text: "VIN", hidden: true });

    searchEl.append(shotEl, queryEl, vinTag, cam, fileEl);

    progressEl = el("div", { className: "id-progress", hidden: true });

    dockEl = el("div", { className: "id-dock" });
    dockEl.append(searchEl, progressEl);

    chipsEl = el("div", { className: "id-chips", hidden: true });

    chooserEl = el("div", { className: "id-chooser card", hidden: true });
    chooserArt = el("div", { className: "id-chooser-art" });
    chooserImg = el("img", { loading: "lazy", decoding: "async", alt: "" });
    watchArt(chooserImg);
    const ghost = el("span", { className: "id-ghost", "aria-hidden": "true" });
    ghost.append(svgStroke(BIKE_STROKE));
    chooserArt.append(chooserImg, ghost);
    chooserMake = el("span", { className: "id-chooser-make" });
    chooserModel = el("span", { className: "id-chooser-model" });
    const head = el("div", { className: "id-chooser-head" });
    head.append(chooserMake, chooserModel);
    chooserYears = el("div", { className: "id-chooser-years" });
    const top = el("div", { className: "id-chooser-top" });
    top.append(chooserArt, head);
    chooserEl.append(top, chooserYears);

    gridEl = el("div", { className: "id-grid", hidden: true });

    root.replaceChildren(dockEl, chipsEl, chooserEl, gridEl);

    queryEl.addEventListener("input", onQuery);
    root.addEventListener("keydown", onRootKey);
    cam.addEventListener("click", () => fileEl.click());
    shotEl.addEventListener("click", () => {
      clearPhoto();
      paintChips();
      refresh();
    });
    fileEl.addEventListener("change", onFile);
  },

  enter() {
    live = true;
    set({ partId: null, jobId: null, systemId: null });
    if (!state.photoUrl) clearPhoto();
    else showShot(photoUrl);
    // Coming back from Confirm must not fire the same jump again.
    jumpedFor = textQ.trim() || null;
    paintChips();
    refresh(true);
    // bus emits "screen" after enter() returns and app.js clears the header Back on it,
    // so the sub-state this screen came back to is re-announced one microtask later.
    queueMicrotask(() => {
      if (!live) return;
      subOn = false;
      signalSub();
    });
    Promise.resolve(Q.loadCatalog()).then(() => {
      if (!live) return;
      rosterIds = null;
      modelIndex = null;
      makesCache = null;
      wmiCache = null;
      paintChips();
      refresh(true);
    });
  },

  back() {
    return backOut();
  },

  leave() {
    live = false;
    if (inputRaf) cancelAnimationFrame(inputRaf);
    if (jumpTimer) clearTimeout(jumpTimer);
    inputRaf = 0;
    jumpTimer = 0;
    showProgress(false);
    document.body.classList.remove("id-landing");
    landing = false;
  },
});

if (typeof window !== "undefined") {
  window.addEventListener("ttm:catalog", () => {
    rosterIds = null;
    modelIndex = null;
    makesCache = null;
    wmiCache = null;
    if (!live) return;
    paintChips();
    refresh(true);
  });
  // Crossing into the desktop grid swaps the cards up to the 1280 hero.
  if (WIDE_Q && typeof WIDE_Q.addEventListener === "function") {
    WIDE_Q.addEventListener("change", () => {
      if (live) renderGrid();
    });
  }
}
