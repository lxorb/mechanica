/**
 * Conditions — Climate Fit. Owner: climate agent.
 *
 * The manual already prints rules that depend on where the vehicle lives: an antifreeze floor, a
 * temperature-banded oil grade, "service more often in dusty conditions". This screen resolves
 * those rules against the measured climate at the nearest NOAA ISD station and shows the
 * manufacturer's own line. It never writes a sentence of its own: every row is
 *
 *     CLAIM (the manual's label) · status · the manual's printed line · one measured number · p. N
 *
 * and tapping the row does what every other row in this app does - opens the PDF on that page.
 * Nothing here is generated; the verdict endpoint costs 0 tokens and answers from two precomputed
 * tables, so opening this screen adds $0 to a question that already costs $0.0003.
 *
 * The overlay node is created here and registered with bus.js, so it gets its own history entry
 * (#book+conditions) and the header Back, the hardware Back and Escape all close it first.
 *
 * Location, in this order, with no dialog on first paint:
 *   1. a place the counter already typed (localStorage)
 *   2. navigator.geolocation, only when permission is ALREADY granted
 *   3. a typed city, resolved against the station table itself - no external geocoder
 */

import { state, set, go, openOverlay, closeOverlay, registerOverlay } from "./bus.js";
import * as T from "./ttm.js";

const PLACE_KEY = "hb.climate.place";
const STATUS = {
  breached: "action needed",
  borderline: "watch",
  ok: "ok",
  unknown: "no data",
};
const ORDER = { breached: 0, borderline: 1, ok: 2, unknown: 3 };

let root = null;
let els = null;
let gen = 0;
let place = "";
let coords = null;
let lastFit = null;
let strips = new Set();

/* ---------------------------------------------------------------- helpers */

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "on") for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
      else node.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

function stored(key) {
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function store(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode: the field still works, it just does not survive a reload */
  }
}

/** Geolocation only when the browser already granted it: this screen never raises a prompt. */
async function granted() {
  if (!navigator.geolocation || !navigator.permissions) return null;
  try {
    const status = await navigator.permissions.query({ name: "geolocation" });
    if (status.state !== "granted") return null;
  } catch {
    return null;
  }
  return new Promise((done) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => done({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => done(null),
      { maximumAge: 600000, timeout: 4000 }
    );
  });
}

async function manualId() {
  if (state.jobId) {
    const job = await T.jobById(state.jobId).catch(() => null);
    if (job && job.manualId) return job.manualId;
  }
  const made = state.bikeId ? await T.manual(state.bikeId).catch(() => null) : null;
  return made ? made.id : "";
}

async function load(id) {
  if (!id) return null;
  if (coords) return T.climateFit(id, { ...coords, bikeId: state.bikeId });
  if (place) return T.climateFit(id, { place, bikeId: state.bikeId });
  return null;
}

/* ---------------------------------------------------------------- rows */

/** One verdict: a claim, a number, a page. Never a paragraph. */
function row(verdict, onPage) {
  const rule = verdict.rule || {};
  const page = Number(rule.page) || 0;
  const node = h("button", {
    class: "cv-row",
    type: "button",
    "data-status": verdict.status,
    "data-page": String(page),
    on: { click: () => onPage && page && onPage(page) },
  });
  node.append(
    h(
      "div",
      { class: "cv-head" },
      h("b", { class: "cv-name", text: rule.name || rule.ruleType || "" }),
      h("span", { class: "cv-flag", text: STATUS[verdict.status] || verdict.status })
    ),
    h("p", { class: "cv-claim", text: verdict.claim || rule.quote || "" }),
    h(
      "div",
      { class: "cv-foot" },
      h("span", { class: "cv-fact", text: verdict.evidence || "" }),
      page ? h("span", { class: "stamp cv-page", text: `p. ${page}` }) : null
    )
  );
  return node;
}

/** Open the PDF on the page the rule is printed on. Same step Parts takes from a mention chip. */
async function openPage(page, id) {
  const made = await T.manual(id).catch(() => null);
  if (!made || !Array.isArray(made.jobs)) return;
  const sectionId = `climate-p${page}`;
  let job = made.jobs.find((j) => j.sectionId === sectionId);
  if (!job) {
    job = {
      id: `${state.bikeId}/${sectionId}`,
      bikeId: state.bikeId,
      sectionId,
      manualId: made.id,
      systemId: null,
      chapter: "",
      title: `Page ${page}`,
      partId: null,
      partIds: [],
      pages: [page],
      page,
      pageStart: page,
      pageEnd: page,
      printedPage: null,
      steps: [{ page }],
      related: [],
      highlights: [],
      keywords: [],
      oem: null,
      links: [],
      synthetic: true,
    };
    made.jobs.push(job);
    if (made.jobsById && typeof made.jobsById.set === "function") made.jobsById.set(job.id, job);
  }
  closeOverlay();
  set({ jobId: job.id, jobIds: [job.id], page });
  go("book", { replace: true, page });
}

/* ---------------------------------------------------------------- overlay */

function node() {
  const found = document.querySelector('[data-overlay="conditions"]');
  if (found) return found;
  const sheet = h("div", {
    class: "ov-sheet cv-sheet",
    role: "dialog",
    "aria-modal": "true",
    "aria-label": "Conditions",
    "data-root": true,
  });
  const aside = h("aside", { class: "ov cv", "data-overlay": "conditions", hidden: true });
  aside.append(h("div", { class: "ov-veil", "data-ov-close": true }), sheet);
  document.body.append(aside);
  return aside;
}

function mount(host) {
  root = host;
  root.replaceChildren();

  const title = h(
    "div",
    { class: "cv-title" },
    h("b", { text: "Conditions" }),
    h("span", { class: "cv-station" })
  );
  const x = h("button", {
    class: "ov-x",
    type: "button",
    "aria-label": "Close",
    text: "×",
    on: { click: () => closeOverlay() },
  });
  const input = h("input", {
    class: "cv-q",
    type: "search",
    placeholder: "City",
    "aria-label": "City",
    autocomplete: "off",
    spellcheck: "false",
    enterkeyhint: "search",
    on: {
      change: onPlace,
      search: onPlace,
      keydown: (e) => {
        if (e.key === "Enter") onPlace();
      },
    },
  });
  const body = h("div", { class: "ov-body cv-body" });
  root.append(h("header", { class: "ov-head cv-head" }, title, x), h("div", { class: "cv-bar" }, input), body);
  els = { station: title.querySelector(".cv-station"), input, body };
}

function onPlace() {
  const value = String(els.input.value || "").trim();
  if (!value) return;
  place = value;
  coords = null;
  store(PLACE_KEY, value);
  refresh();
}

function paint(fit, id) {
  els.body.replaceChildren();
  if (!fit) {
    els.station.textContent = "";
    els.body.append(h("p", { class: "cv-empty", text: place ? "No station" : "Type a city" }));
    return;
  }
  const st = fit.station || {};
  const km = st.km == null ? "" : `${Number(st.km).toFixed(1)} km`;
  els.station.textContent = [st.name, km, `${Number(st.obs || 0).toLocaleString()} obs`]
    .filter(Boolean)
    .join(" · ");
  const list = (fit.verdicts || []).slice().sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  if (!list.length) {
    els.body.append(h("p", { class: "cv-empty", text: "No rules in this manual" }));
    return;
  }
  els.body.append(
    h(
      "div",
      { class: "cv-tally" },
      h("span", { class: "stamp cv-count", text: `${fit.breached}/${fit.checked}` }),
      h("span", { class: "cv-tallyword", text: "breached" })
    )
  );
  for (const v of list) els.body.append(row(v, (page) => openPage(page, id)));
}

async function refresh() {
  if (!els) return;
  const my = ++gen;
  const id = await manualId();
  const fit = await load(id).catch(() => null);
  if (my !== gen) return;
  lastFit = fit;
  paint(fit, id);
  for (const fn of strips) fn(fit, id);
}

async function open() {
  if (!els) return;
  place = place || stored(PLACE_KEY);
  els.input.value = place;
  if (!place && !coords) coords = await granted();
  await refresh();
}

function close() {
  gen += 1;
}

registerOverlay("conditions", { mount, open, close });
node();

/* ---------------------------------------------------------------- public */

export function openConditions() {
  openOverlay("conditions");
}

/**
 * The compact strip the Parts sheet shows above its rows: only the verdicts that need an action,
 * each still carrying its page. Returns the element; it fills itself as soon as a fit lands and
 * stays empty - not "loading" - while there is nothing to say.
 */
export function strip() {
  const host = h("div", { class: "cv-strip", hidden: true });
  const fill = (fit, id) => {
    host.replaceChildren();
    const list = (fit && fit.verdicts ? fit.verdicts : []).filter((v) => v.status === "breached");
    host.hidden = !list.length;
    if (!list.length) return;
    for (const v of list.slice(0, 3)) {
      const page = Number(v.rule && v.rule.page) || 0;
      host.append(
        h(
          "button",
          {
            class: "cv-chip",
            type: "button",
            "data-status": v.status,
            on: { click: () => page && openPage(page, id) },
          },
          h("b", { text: (v.rule && v.rule.name) || "" }),
          h("span", { class: "cv-chipfact", text: v.evidence || "" }),
          page ? h("span", { class: "stamp cv-page", text: `p. ${page}` }) : null
        )
      );
    }
  };
  strips.add(fill);
  if (lastFit) manualId().then((id) => fill(lastFit, id));
  else {
    place = place || stored(PLACE_KEY);
    if (place || coords) refresh();
  }
  return host;
}

export function lastVerdicts() {
  return lastFit;
}
