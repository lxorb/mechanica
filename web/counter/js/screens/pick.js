/**
 * Step 3 — Pick. Owner: step-3 agent. Files: this, ../pick-search.js, ../../css/screens/pick.css.
 *
 * The 3D bike sits in a sticky panel at the top and never leaves the screen. Under it, one
 * search field over EVERY heading in the manual — chapters and subchapters — plus every
 * indexed section. Before you type it is the assembled bike and the list is the manual's
 * own contents. First keystroke explodes it. Narrow to one hit (or tap a hit) and that part
 * lights up and the camera eases onto it. Then one button: MANUAL.
 *
 * Contracts used (all owned elsewhere):
 *   ../viewer3d.js  mount(host, modelFor(bike), {onSelect}) -> {explode,highlight,focus,reset,dispose}
 *                   partFor(title, keywords) -> part key | null
 *   ../particons.js iconFor(name, keywords), iconEl(id, size)
 *   ../ttm.js       manual(), jobsFor(), systems(), ask(), identifyPart(), partPhrase()
 *   ../bus.js       state / set / go — "Manual" only sets state.jobId + state.jobIds and go("book").
 *
 * The one liberty taken: most outline headings have no indexed section behind them (KTM:
 * 20 sections for 270 headings), and Book resolves state.jobId through T.jobById(), which
 * only knows real sections. So openManual() synthesises a job for a bare heading — its page
 * range comes straight from the outline — and parks it on the manual record T.manual()
 * returns, where jobById() finds it. Marked `synthetic: true` so the index skips it.
 */

import { state, set, go, emit, registerScreen } from "../bus.js";
import * as T from "../ttm.js";
import * as speech from "../speech.js";
import * as deepgram from "../deepgram.js";
import { initCost } from "./cost.js";
import { build, roots, search, marks, spanOf, byId, normTitle } from "../pick-search.js";
import { mount as mountViewer, modelFor, partFor, PART_LABELS } from "../viewer3d.js";
import { iconFor, iconEl } from "../particons.js";
import { mountChat } from "../chat-ui.js";
import { ensureDock, setChat, showChat } from "../dock.js";

const MIC_PATH_BODY = "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z";
const MIC_PATH_ARC = "M5 11a7 7 0 0 0 14 0M12 18v3";
const CAM_PATH =
  "M8 5h2l1-2h2l1 2h4v13H4V5h4zm4 3.25A3.75 3.75 0 1 0 12 15.75 3.75 3.75 0 0 0 12 8.25zm0 2A1.75 1.75 0 1 1 12 13.75 1.75 1.75 0 0 1 12 10.25z";
const CHAT_PATH = "M3 4h18v12H9l-6 5V4z";

ensureDock();
// Book's dock asks for the same conversation this screen owns - one chat per manual, opened
// from either screen. The guard inside toggleChat() makes this a no-op before a manual exists.
window.addEventListener("mechanica:chat", () => toggleChat());
/** Submit. A stroked path, not the "up arrow" character: a glyph cannot be clipped by its box. */
const SEND_PATH = "M12 19V5M5 12l7-7 7 7";
/** The expand twist, rotated 90 degrees by CSS when the group is open. */
const TWIST_PATH = "M9 5l7 7-7 7";

const MISS_MS = 900;
const VIEW_MS = 120;
const MAX_ROWS = 60;

let root;
let els;
let viewer = null;
let viewerBike = null;
let chat = null; // the chat drawer controller (../chat-ui.js), built once a manual is known

let entries = [];
let index = new Map();
let systemsList = [];
let expanded = new Set();
let results = [];
let selected = null;
let rowCap = MAX_ROWS;

let gen = 0;
let askGen = 0;
let voiceGen = 0;
let busy = false;
let listening = false;
let stt = speech;
let missTimer = 0;
let viewTimer = 0;
let savedY = 0;
let freezeY = false;
let lastBikeId = null;

initCost();

registerScreen("pick", { mount, enter, leave, back });

/* ------------------------------------------------------------------ dom helpers */

function node(tag, attrs) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  return el;
}

function glyph(paths, stroke) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    if (stroke) {
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "2.2");
      path.setAttribute("stroke-linecap", "round");
    } else {
      path.setAttribute("fill", "currentColor");
    }
    svg.append(path);
  }
  return svg;
}

/* ------------------------------------------------------------------ mount */

function mount(el) {
  root = el;
  root.replaceChildren();
  window.addEventListener("scroll", snapshotY, { passive: true });

  const stage = node("div", { class: "stage" });
  const stageViewer = node("div", { class: "vx" });

  const who = node("button", { type: "button", class: "who" });
  const whoImg = node("img", { loading: "lazy", decoding: "async", alt: "", width: "28", height: "28" });
  const whoName = node("span", { class: "who-name" });
  who.append(whoImg, whoName);
  who.addEventListener("click", () => {
    snapshotY();
    go("confirm");
  });

  const bar = node("div", { class: "askbar" });
  const meter = node("div", { class: "meter", hidden: "" });
  meter.append(node("i"));

  const form = node("form", { class: "ask" });
  const mic = node("button", {
    type: "button",
    class: "btn btn-icon mic",
    "aria-label": "Speak",
    "aria-pressed": "false",
  });
  mic.append(glyph([MIC_PATH_BODY, MIC_PATH_ARC], true));
  mic.addEventListener("click", toggleMic);

  const cam = node("button", { type: "button", class: "btn btn-icon cam", "aria-label": "Photo part" });
  cam.append(glyph([CAM_PATH], false));
  cam.addEventListener("click", () => {
    if (busy) return;
    els.file.click();
  });

  const input = node("input", {
    type: "search",
    class: "ask-q",
    enterkeyhint: "search",
    autocomplete: "off",
    autocorrect: "off",
    spellcheck: "false",
    placeholder: "Search the manual",
    "aria-label": "Search the manual",
  });
  input.addEventListener("input", onType);
  input.addEventListener("search", onType);

  const send = node("button", { type: "submit", class: "btn btn-icon send", "aria-label": "Ask" });
  send.append(glyph([SEND_PATH], true));

  form.append(mic, cam, input, send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    onSubmit();
  });

  const file = node("input", {
    type: "file",
    accept: "image/*",
    capture: "environment",
    hidden: "",
    tabindex: "-1",
    "aria-hidden": "true",
  });
  file.addEventListener("change", onFile);

  bar.append(meter, form);
  stage.append(stageViewer, bar);

  const hits = node("div", { class: "hits", role: "list" });
  const foot = node("div", { class: "foot", hidden: "" });
  const open = node("button", { type: "button", class: "btn btn-primary open", hidden: "" });
  const openT = node("b", { text: "Manual" });
  const openP = node("span", { class: "open-p" });
  open.append(openT, openP);
  open.addEventListener("click", openManual);

  foot.append(open);

  const chatHost = node("div", { hidden: "" });

  root.append(stage, hits, foot, file, chatHost);
  stageViewer.append(who);

  els = { stage, stageViewer, who, whoImg, whoName, bar, meter, form, mic, cam, input, send, file, hits, foot, open, openP, chatHost };
  els.mic.hidden = !stt.supported;
  syncSend();
}

/* ------------------------------------------------------------------ screen life */

function bounce() {
  queueMicrotask(() => go("identify", { replace: true }));
}

function enter() {
  if (!state.bikeId) {
    bounce();
    return;
  }
  freezeY = true;
  setChat(toggleChat);
  showChat(Boolean(chat));
  if (state.bikeId !== lastBikeId) {
    savedY = 0;
    entries = [];
    index = new Map();
    systemsList = [];
    expanded = new Set();
    results = [];
    selected = null;
    rowCap = MAX_ROWS;
    lastBikeId = state.bikeId;
    if (chat) chat.close();
    if (els) {
      els.input.value = "";
      els.hits.replaceChildren();
      syncFoot();
      syncSend();
    }
  }
  startViewer();
  load().catch(() => {});
  restoreScroll();
}

function leave() {
  freezeY = false;
  snapshotY();
  if (chat) chat.close();
  stopMic();
  clearMiss();
  clearView();
  askGen += 1;
  // load() checks this token before it paints and before it mounts the viewer. Without the
  // bump, a catalog fetch that lands after the screen is gone re-mounts the 3D stage behind
  // whatever the user is now looking at — a live WebGL context nothing will ever dispose.
  gen += 1;
  busy = false;
  setBusy(false);
  stopViewer();
}

/** Back closes the chat, then pops the selection and the query, before it walks a step back. */
function back() {
  if (chat && chat.close()) return true;
  if (selected) {
    clearSelection();
    return true;
  }
  if (els && els.input.value) {
    els.input.value = "";
    onType();
    return true;
  }
  return false;
}

function snapshotY() {
  if (freezeY || !root) return;
  const section = root.closest("[data-screen]");
  if (section && !section.hidden) savedY = window.scrollY;
}

function restoreScroll() {
  const y = savedY;
  freezeY = true;
  window.scrollTo(0, y);
  requestAnimationFrame(() => {
    window.scrollTo(0, y);
    freezeY = false;
  });
}

/* ------------------------------------------------------------------ the viewer */

function startViewer() {
  if (!els) return;
  const rec = T.bike(state.bikeId);
  const key = modelFor(rec || state.bikeId);
  if (viewer && viewerBike === key) return;
  stopViewer();
  viewerBike = key;
  try {
    viewer = mountViewer(els.stageViewer, key, {
      onSelect: onPartTap,
      // the browser took the WebGL context away: a fresh mount is the only way back
      onContextLost: () => { stopViewer(); startViewer(); },
    });
  } catch {
    viewer = null;
  }
}

function stopViewer() {
  if (!viewer) return;
  try {
    viewer.dispose();
  } catch {
    /* already gone */
  }
  viewer = null;
  viewerBike = null;
}

/**
 * Tapping the model. The background clears the pick. A part picks the first heading on
 * screen that is about it; if nothing on screen is, the part's own name goes into the
 * search field — tapping the rear wheel IS a search for the rear wheel — unless the user
 * has typed something of their own, which is theirs to keep.
 */
function onPartTap(partKey) {
  if (!partKey) {
    if (selected) clearSelection();
    return;
  }
  const hit = onScreen().find((e) => partOf(e) === partKey);
  if (hit) {
    select(hit, { scroll: true });
    return;
  }
  const label = PART_LABELS[partKey];
  // …but only when the manual has something to say about it; an empty list is a dead end.
  if (label && !query() && search(entries, label, 1).length) {
    els.input.value = label;
    selected = null;
    onType();
    if (results.length) select(results[0], { scroll: true });
    return;
  }
  if (viewer) {
    try {
      viewer.highlight(partKey);
    } catch {
      /* the viewer answers for itself */
    }
  }
}

/** The entries the list is actually showing, in order. */
function onScreen() {
  if (!els) return [];
  const out = [];
  for (const row of els.hits.querySelectorAll(".hit")) {
    const hit = index.get(row.getAttribute("data-id"));
    if (hit) out.push(hit);
  }
  return out;
}

function partOf(entry) {
  if (!entry) return null;
  if (entry.partKey === undefined) {
    try {
      entry.partKey = partFor(entry.label || entry.title, entry.keywords) || null;
    } catch {
      entry.partKey = null;
    }
  }
  return entry.partKey;
}

function clearView() {
  if (viewTimer) {
    window.clearTimeout(viewTimer);
    viewTimer = 0;
  }
}

/**
 * One place decides what the model is doing: nothing typed -> assembled; typing -> exploded;
 * a heading picked -> exploded, its part lit and the camera eased in. Debounced so a fast
 * typist does not queue up a dozen camera tweens.
 */
function applyView(now) {
  clearView();
  const run = () => {
    viewTimer = 0;
    if (!viewer) return;
    try {
      if (selected) {
        const part = partOf(selected);
        viewer.explode(true);
        if (part) viewer.focus(part);
        else viewer.highlight(null);
        return;
      }
      if (els && els.input.value.trim()) {
        viewer.highlight(null);
        viewer.explode(true);
        return;
      }
      viewer.reset();
    } catch {
      /* the viewer answers for itself; the list keeps working */
    }
  };
  if (now) run();
  else viewTimer = window.setTimeout(run, VIEW_MS);
}

/* ------------------------------------------------------------------ data */

async function load() {
  const token = ++gen;
  let rec = T.bike(state.bikeId);
  if (!rec) {
    try {
      await T.loadCatalog();
    } catch {
      /* offline catalog */
    }
    rec = T.bike(state.bikeId);
  }
  if (token !== gen) return;
  if (!rec) {
    bounce();
    return;
  }
  paintBike(rec);
  startViewer();
  syncChat();

  const [made, jobs, sys] = await Promise.all([
    Promise.resolve().then(() => T.manual(rec.manualId || state.bikeId)).catch(() => null),
    Promise.resolve().then(() => T.jobsFor(state.bikeId)).then((r) => (Array.isArray(r) ? r : [])).catch(() => []),
    Promise.resolve().then(() => T.systems(state.bikeId)).then((r) => (Array.isArray(r) ? r : [])).catch(() => []),
  ]);
  if (token !== gen) return;

  systemsList = sys;
  const was = selected;
  entries = build({ manual: made || {}, jobs, pages: made && made.pages });
  index = byId(entries);
  // Coming back from Book rebuilds the index; keep the pick so the row, the button and the
  // lit part still agree with each other. Entry objects are new, so match on the dedupe key.
  selected = was ? entries.find((e) => e.key === was.key) || null : null;
  render();
  primeVoice();
}

function paintBike(rec) {
  const label = [rec.make, rec.model, rec.year].filter((x) => x != null && x !== "").join(" ");
  const src = T.asset(rec.thumb || rec.image || "");
  if (src) {
    els.whoImg.src = src;
    els.whoImg.alt = "";
    els.whoImg.hidden = false;
  } else {
    els.whoImg.removeAttribute("src");
    els.whoImg.hidden = true;
  }
  els.whoName.textContent = label;
  els.who.setAttribute("aria-label", `${label} — change bike`);
}

function manualId() {
  const rec = T.bike(state.bikeId);
  return (rec && rec.manualId) || "";
}

/* ------------------------------------------------------------------ list */

function query() {
  return els ? els.input.value.trim() : "";
}

/** Browse mode: the contents as the manual prints them, chapters collapsed. */
function browseRows() {
  const out = [];
  const walk = (list) => {
    for (const entry of list) {
      out.push(entry);
      if (expanded.has(entry.id)) {
        walk(entry.childIds.map((id) => index.get(id)).filter(Boolean));
      }
    }
  };
  walk(roots(entries));
  return out;
}

function render() {
  if (!els) return;
  const q = query();
  const browsing = !q;
  results = browsing ? [] : search(entries, q, MAX_ROWS);

  if (!browsing && selected && !results.includes(selected)) selected = null;
  // The founder's rule: one hit left is the same as tapping it.
  if (!browsing && !selected && results.length === 1) selected = results[0];

  const rows = browsing ? browseRows() : results;
  const shown = rows.slice(0, rowCap);

  const frag = document.createDocumentFragment();
  for (const entry of shown) frag.append(rowFor(entry, q, browsing));
  if (rows.length > shown.length) {
    const more = node("button", {
      type: "button",
      class: "more",
      text: `+${rows.length - shown.length} more`,
    });
    more.addEventListener("click", () => {
      rowCap += MAX_ROWS;
      render();
    });
    frag.append(more);
  }
  if (!rows.length) {
    frag.append(node("p", { class: "none", text: busy ? "Looking…" : "Nothing in this manual" }));
  }
  els.hits.replaceChildren(frag);
  els.hits.classList.toggle("is-flat", !browsing);
  syncFoot();
  syncSend();
  applyView();
}

function stamp(entry) {
  const a = entry.page;
  const b = entry.pageEnd;
  return b > a ? `p. ${a}–${b}` : `p. ${a}`;
}

function titleNode(entry, q) {
  const span = node("span", { class: "hit-t" });
  const text = entry.label || entry.title;
  const spans = q ? marks(text, q) : [];
  if (!spans.length) {
    span.textContent = text;
    return span;
  }
  let at = 0;
  for (const range of spans) {
    if (range.start > at) span.append(document.createTextNode(text.slice(at, range.start)));
    span.append(node("mark", { text: text.slice(range.start, range.end) }));
    at = range.end;
  }
  if (at < text.length) span.append(document.createTextNode(text.slice(at)));
  return span;
}

function rowFor(entry, q, browsing) {
  const row = node("div", {
    class: selected === entry ? "hit is-on" : "hit",
    "data-id": entry.id,
    "data-depth": String(Math.min(entry.depth, 2)),
    role: "listitem",
  });

  const go2 = node("button", { type: "button", class: "hit-go" });
  // Only when the icon set really recognises the part — a wrench on every chapter is noise.
  let icon = null;
  try {
    const id = iconFor(entry.label || entry.title, entry.keywords);
    if (id && id !== "generic-part") icon = iconEl(id, "sm");
  } catch {
    icon = null;
  }
  go2.append(icon || node("span", { class: "hit-pad", "aria-hidden": "true" }));

  const body = node("span", { class: "hit-b" });
  if (entry.number) body.append(node("i", { class: "hit-n", text: entry.number }));
  body.append(titleNode(entry, q));
  go2.append(body);
  go2.append(node("span", { class: "stamp", text: stamp(entry) }));
  go2.addEventListener("click", () => select(entry));
  row.append(go2);

  if (browsing && entry.childIds.length) {
    const on = expanded.has(entry.id);
    const twist = node("button", {
      type: "button",
      class: on ? "hit-x is-on" : "hit-x",
      "aria-expanded": on ? "true" : "false",
      "aria-label": on ? "Collapse" : "Expand",
    });
    twist.append(glyph([TWIST_PATH], true));
    twist.addEventListener("click", () => {
      if (expanded.has(entry.id)) expanded.delete(entry.id);
      else expanded.add(entry.id);
      render();
    });
    row.append(twist);
  }
  return row;
}

function syncFoot() {
  if (!els) return;
  // The foot is the MANUAL button and nothing else now - Chat moved into the search bar.
  els.foot.hidden = !selected;
  els.open.hidden = !selected;
  if (!selected) return;
  const part = partOf(selected);
  els.openP.textContent = part && PART_LABELS[part] ? `${stamp(selected)} · ${PART_LABELS[part]}` : stamp(selected);
}

/* ------------------------------------------------------------------ selection */

function select(entry, opts) {
  if (!entry) return;
  if (selected === entry) {
    openManual();
    return;
  }
  selected = entry;
  for (const row of els.hits.querySelectorAll(".hit")) {
    row.classList.toggle("is-on", row.getAttribute("data-id") === entry.id);
  }
  syncFoot();
  applyView(true);
  if (opts && opts.scroll) {
    const row = els.hits.querySelector(`.hit[data-id="${entry.id}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function clearSelection() {
  if (!selected) return;
  selected = null;
  for (const row of els.hits.querySelectorAll(".hit.is-on")) row.classList.remove("is-on");
  syncFoot();
  applyView(true);
}

function onType() {
  rowCap = MAX_ROWS;
  clearMiss();
  render();
}

/* ------------------------------------------------------------------ opening the manual */

function slug(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

/** The chapter (system) a bare heading belongs to, so Book and Follow keep their context. */
function systemIdFor(entry) {
  let top = entry;
  const seen = new Set();
  while (top && top.parentId && !seen.has(top.id)) {
    seen.add(top.id);
    top = index.get(top.parentId) || top;
  }
  const wanted = normTitle(top ? top.title : entry.title);
  const hit = systemsList.find(
    (sys) => normTitle(sys.chapter || "") === wanted || normTitle(sys.name || "") === wanted
  );
  return hit ? hit.id : null;
}

/**
 * A job Book can open for something the index never named — a bare outline heading, or a page
 * a chat citation points at. Parked on the manual record, which is what T.jobById() reads;
 * without that Book would bounce straight back here. Marked `synthetic` so the index skips it.
 */
function bareJob(made, { sectionId, pages, title, chapter, systemId }) {
  const found = made.jobs.find((j) => j.sectionId === sectionId);
  if (found) return found;
  const job = {
    id: `${state.bikeId}/${sectionId}`,
    bikeId: state.bikeId,
    sectionId,
    manualId: made.id,
    systemId: systemId || null,
    chapter: chapter || title,
    title,
    partId: null,
    partIds: [],
    pages,
    page: pages[0],
    pageStart: pages[0],
    pageEnd: pages[pages.length - 1],
    printedPage: null,
    steps: pages.map((page) => ({ page })),
    related: [],
    highlights: [],
    keywords: [],
    oem: null,
    links: [],
    price: null,
    ship: null,
    days: null,
    from: null,
    used: [],
    alts: [],
    new: null,
    synthetic: true,
  };
  made.jobs.push(job);
  if (made.jobsById && typeof made.jobsById.set === "function") made.jobsById.set(job.id, job);
  return job;
}

/** A heading with an indexed section behind it already has a job; a bare one gets bareJob(). */
async function jobFor(entry) {
  if (!entry) return null;
  if (entry.job) return entry.job;
  const made = await T.manual(manualId() || state.bikeId).catch(() => null);
  if (!made || !Array.isArray(made.jobs)) return null;

  entry.job = bareJob(made, {
    sectionId: `toc-${entry.page}-${slug(entry.label || entry.title)}`,
    pages: spanOf(entry),
    title: entry.label || entry.title,
    chapter: entry.chapter || entry.title,
    systemId: systemIdFor(entry),
  });
  return entry.job;
}

async function openManual() {
  const entry = selected;
  if (!entry || busy) return;
  busy = true;
  setBusy(true);
  const token = ++askGen;
  const job = await jobFor(entry);
  if (token !== askGen) return;
  busy = false;
  setBusy(false);
  if (!job) {
    miss();
    return;
  }
  const ids = [job.id];
  for (const other of results) {
    if (other !== entry && other.job && other.job.id && !ids.includes(other.job.id)) ids.push(other.job.id);
  }
  snapshotY();
  const partId = (Array.isArray(job.partIds) && job.partIds[0]) || job.partId || null;
  set({
    jobId: job.id,
    jobIds: ids,
    systemId: job.systemId || state.systemId || null,
    partId,
    page: job.pages[0],
  });
  emit("part", { partId });
  go("book");
}

/** The job Ask hands back is real; open it the same way a tapped result opens. */
function openAskJob(job, rest) {
  if (!job || !job.id) return;
  snapshotY();
  const ids = (rest || []).map((row) => row && row.id).filter(Boolean);
  const partId = (Array.isArray(job.partIds) && job.partIds[0]) || job.partId || null;
  set({
    jobId: job.id,
    jobIds: ids.length ? ids : [job.id],
    systemId: job.systemId || null,
    partId,
    page: (Array.isArray(job.pages) && job.pages[0]) || null,
  });
  emit("part", { partId });
  go("book");
}

/* ------------------------------------------------------------------ chat */

function bikeLabel() {
  const rec = T.bike(state.bikeId);
  if (!rec) return "";
  return [rec.make, rec.model, rec.year].filter((x) => x != null && x !== "").join(" ");
}

/**
 * The pill appears the moment this bike has an indexed manual to talk about, and the drawer
 * is built on the first tap (the component is 387 KB — it must not sit in front of the list).
 */
function syncChat() {
  if (!els) return;
  const id = manualId();
  showChat(Boolean(id));
  if (!id) {
    if (chat) chat.close();
  } else if (!chat) {
    chat = mountChat(els.chatHost, { manualId: id, bike: bikeLabel(), onPage: openPage });
  } else {
    chat.setContext({ manualId: id, bike: bikeLabel() });
  }
  syncFoot();
}

function toggleChat() {
  if (!chat) return;
  stopMic();
  chat.toggle();
}

/** The outline heading the cited page falls under, so the reader opens with its bearings. */
function headingAt(page) {
  let best = null;
  for (const entry of entries) {
    if (entry.page > page) continue;
    if (!best || entry.page > best.page || (entry.page === best.page && entry.depth > best.depth)) best = entry;
  }
  return best;
}

/** A [p. N] chip: one synthetic job for that single printed page, then Book opens on it. */
async function openPage(n) {
  const page = Math.max(1, Math.floor(Number(n) || 0));
  if (!page) return;
  const made = await T.manual(manualId() || state.bikeId).catch(() => null);
  if (!made || !Array.isArray(made.jobs)) {
    miss();
    return;
  }
  const under = headingAt(page);
  const job = bareJob(made, {
    sectionId: `chat-p${page}`,
    pages: [page],
    title: under ? under.label || under.title : `Page ${page}`,
    chapter: under ? under.chapter || under.title : "",
    systemId: under ? systemIdFor(under) : null,
  });
  if (chat) chat.close();
  snapshotY();
  set({ jobId: job.id, jobIds: [job.id], systemId: job.systemId || state.systemId || null, partId: null, page });
  emit("part", { partId: null });
  go("book");
}

/* ------------------------------------------------------------------ ask / mic / camera */

function setBusy(on) {
  if (!els) return;
  els.bar.classList.toggle("is-busy", on);
  els.meter.hidden = !on;
  els.meter.classList.toggle("run", on);
  els.cam.disabled = on;
  syncSend();
}

function syncSend() {
  if (!els) return;
  els.send.disabled = busy || !query();
}

function clearMiss() {
  if (missTimer) {
    window.clearTimeout(missTimer);
    missTimer = 0;
  }
  if (els) els.bar.classList.remove("miss");
}

function miss() {
  clearMiss();
  if (!els) return;
  els.bar.classList.add("miss");
  missTimer = window.setTimeout(() => {
    missTimer = 0;
    if (els) els.bar.classList.remove("miss");
  }, MISS_MS);
}

/**
 * Enter / send, in tiers: open what is picked, else pick the best local hit (the model moves
 * so you can see it is the right part), else — free text this manual never prints — ask.
 */
function onSubmit() {
  if (busy) return;
  if (selected) {
    openManual();
    return;
  }
  if (results.length) {
    select(results[0], { scroll: true });
    return;
  }
  ask(query());
}

async function ask(text) {
  const q = String(text || "").trim();
  if (!q || busy) return;
  const id = manualId();
  if (!id) {
    miss();
    return;
  }
  stopMic();
  clearMiss();
  busy = true;
  setBusy(true);
  const token = ++askGen;

  let jobs = [];
  try {
    const res = await T.ask(id, q);
    jobs = Array.isArray(res) ? res : (res && res.jobs) || [];
  } catch {
    jobs = [];
  }
  if (token !== askGen) return;
  busy = false;
  setBusy(false);
  if (!jobs.length) {
    miss();
    return;
  }
  openAskJob(jobs[0], jobs);
}

async function onFile() {
  const file = els.file.files && els.file.files[0];
  els.file.value = "";
  if (!file || busy) return;
  stopMic();
  clearMiss();
  busy = true;
  setBusy(true);
  const token = ++askGen;

  let rows = [];
  try {
    rows = (await T.identifyPart(file)) || [];
  } catch {
    rows = [];
  }
  if (token !== askGen) return;
  busy = false;
  setBusy(false);
  const top = Array.isArray(rows) ? rows[0] : null;
  if (!top) {
    miss();
    return;
  }
  const phrase = String(top.phrase || T.partPhrase(top.label) || "").trim();
  if (!phrase) {
    miss();
    return;
  }
  // The photo types for you: the field fills, the model explodes, the list narrows.
  els.input.value = phrase;
  selected = null;
  onType();
  if (results.length) select(results[0], { scroll: true });
  else ask(phrase);
}

function paintMic() {
  if (!els) return;
  els.mic.hidden = !stt.supported;
  els.mic.setAttribute("aria-pressed", listening ? "true" : "false");
  els.mic.classList.toggle("is-on", listening);
}

function stopMic() {
  if (!listening) return;
  listening = false;
  try {
    stt.stop();
  } catch {
    /* already stopped */
  }
  paintMic();
}

function toggleMic() {
  if (listening) {
    stopMic();
    return;
  }
  if (!stt.supported || busy) return;
  listening = true;
  paintMic();
  stt.start(
    (text) => {
      if (!listening) return;
      els.input.value = text;
      selected = null;
      onType();
    },
    () => {
      listening = false;
      paintMic();
    }
  );
}

function terms() {
  const out = [];
  for (const entry of entries) {
    if (entry.label) out.push(entry.label);
    if (out.length > 400) break;
  }
  return out;
}

async function primeVoice() {
  const token = ++voiceGen;
  let cfg = null;
  try {
    cfg = await T.voiceConfig();
  } catch {
    cfg = null;
  }
  if (token !== voiceGen || !els) return;
  if (cfg && cfg.deepgram && deepgram.supported && T.online()) {
    stt = deepgram;
  }
  stt.prime(terms());
  paintMic();
}
