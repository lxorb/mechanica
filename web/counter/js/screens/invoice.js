/**
 * Parts — the full-screen view over Book. Owner: parts-UI agent.
 *
 * Two states in one overlay:
 *   grid    every part this bike's manual actually names, as large illustrated tiles,
 *           grouped under the chapter that talks about them, filtered by one
 *           typo-tolerant search field (../parts-search.js).
 *   detail  one part blown up — illustration, name and spec verbatim, the printed page
 *           (tap opens Book there) and the OEM number — plus the live retailer offers
 *           from `T.partOffers`, sortable and filterable. No offers, or no endpoint yet:
 *           the manual's own shop links stand in. Nothing is ever invented here.
 *
 * Detail pushes a history entry of its own, so the hardware Back, the header Back and
 * Escape all step detail -> grid -> closed. The search query survives that step.
 *
 * Illustrations come from web/store/icons-parts-3d/index.json ({id: {webp, png}}, owner:
 * parts-art agent) and fall back to the line-art SVGs behind ../particons.js for every
 * part type that file does not carry yet.
 */

import { state, set, emit, go, closeOverlay, registerOverlay } from "../bus.js";
import * as T from "../ttm.js";
import { iconFor, iconUrl } from "../particons.js";
import { index as buildIndex, search as runSearch } from "../parts-search.js";

const ART_DIR = "../store/icons-parts-3d/";
const OTHER = "Other";
const SORTS = [
  { id: "price-asc", label: "Price ↑" },
  { id: "price-desc", label: "Price ↓" },
  { id: "retailer", label: "Retailer" },
  { id: "condition", label: "Condition" },
];

let root;
let els;
let gen = 0;
let offersGen = 0;

let rows = []; // [{ part, group, ... }] from parts-search.js
let groups = []; // ordered group labels
let query = "";
let view = "grid";
let current = null; // the row the detail is showing
let head = { bike: "", manual: "", manualId: "" };
let sort = "price-asc";
let shopFilter = "";

let art = null; // { id: {webp, png} } once index.json answered, {} when there is none
let artTask = null;

registerOverlay("invoice", { mount, open, close });

/* ------------------------------------------------------------------ elements */

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, val] of Object.entries(attrs)) {
      if (val == null || val === false) continue;
      if (key === "class") node.className = val;
      else if (key === "text") node.textContent = val;
      else if (key === "hidden") node.hidden = true;
      else if (key === "on") for (const [ev, fn] of Object.entries(val)) node.addEventListener(ev, fn);
      else node.setAttribute(key, val === true ? "" : String(val));
    }
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

function stampPage(n) {
  return n == null || n === "" ? "" : `p. ${n}`;
}

/* ------------------------------------------------------------------ illustrations */

/** Values may be a bare file name, a path, or an absolute URL. */
function artSrc(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^(?:https?:)?\/\//.test(raw) || raw.startsWith("/") || raw.startsWith("../")) return raw;
  return ART_DIR + raw.replace(/^\.?\//, "");
}

function loadArt() {
  if (artTask) return artTask;
  artTask = fetch(`${ART_DIR}index.json`, { cache: "force-cache" })
    .then((res) => (res.ok ? res.json() : null))
    .then((body) => {
      const map = body && typeof body === "object" ? body.parts || body.icons || body : null;
      art = map && typeof map === "object" ? map : {};
    })
    .catch(() => {
      art = {};
    });
  return artTask;
}

function artFor(part) {
  const fallback = iconFor(part.name, [part.spec || ""]);
  const rec = art ? art[part.id] || art[fallback] : null;
  if (!rec) return { svg: iconUrl(fallback) };
  if (typeof rec === "string") return { png: artSrc(rec) };
  return { webp: artSrc(rec.webp), png: artSrc(rec.png || rec.jpg || rec.src) };
}

/** <picture> when a rendered illustration exists, a plain <img> on the SVG fallback. */
function artEl(part, size) {
  const rec = artFor(part);
  const img = h("img", { class: `pv-art ${size}`, alt: "", decoding: "async", draggable: "false" });
  img.loading = size === "lg" ? "eager" : "lazy";
  if (rec.svg) {
    img.src = rec.svg;
    img.classList.add("is-line");
    return img;
  }
  img.src = rec.png || rec.webp;
  if (rec.webp && rec.png) {
    const pic = h("picture", { class: "pv-pic" });
    pic.append(h("source", { type: "image/webp", srcset: rec.webp }), img);
    return pic;
  }
  return img;
}

/* ------------------------------------------------------------------ shell */

function mount(node) {
  root = node;
  root.replaceChildren();
  root.setAttribute("data-view", "grid");

  const title = h(
    "div",
    { class: "pv-title" },
    h("b", { text: "Parts" }),
    h("span", { class: "pv-bike" }),
    h("span", { class: "pv-manual" })
  );
  const x = h("button", {
    class: "ov-x pv-x",
    type: "button",
    "aria-label": "Close",
    text: "×",
    on: { click: onX },
  });
  const header = h("header", { class: "ov-head pv-head" }, title, x);

  const input = h("input", {
    class: "pv-q",
    type: "search",
    placeholder: "Search",
    "aria-label": "Search parts",
    autocomplete: "off",
    autocorrect: "off",
    spellcheck: "false",
    enterkeyhint: "search",
    on: { input: onQuery, search: onQuery },
  });
  const count = h("span", { class: "pv-count" });
  const searchBar = h("div", { class: "pv-search" }, input, count);

  const grid = h("div", { class: "pv-grid", on: { click: onGridClick } });
  const detail = h("div", { class: "pv-detail" });
  const panes = h("div", { class: "pv-panes" }, grid, detail);

  root.append(header, searchBar, panes);
  els = {
    bike: title.querySelector(".pv-bike"),
    manual: title.querySelector(".pv-manual"),
    input,
    count,
    grid,
    detail,
  };
}

function setView(next) {
  view = next;
  if (root) root.setAttribute("data-view", next);
}

function onX() {
  if (view === "detail") {
    history.back();
    return;
  }
  closeOverlay();
}

/* ------------------------------------------------------------------ open / load */

function open() {
  if (!state.bikeId) {
    closeOverlay();
    return;
  }
  current = null;
  setView("grid");
  if (els) {
    els.detail.replaceChildren();
    els.input.value = query;
  }
  loadArt();
  load().catch(() => {});
}

function close() {
  gen += 1;
  offersGen += 1;
  current = null;
  query = "";
  shopFilter = "";
  setView("grid");
  if (els) {
    els.input.value = "";
    els.detail.replaceChildren();
  }
}

async function manualOf(rec) {
  const ids = [rec && rec.manualId];
  if (state.jobId) {
    const job = await T.jobById(state.jobId).catch(() => null);
    if (job && job.manualId) ids.unshift(job.manualId);
  }
  for (const id of ids) {
    if (!id) continue;
    const made = await T.manual(id).catch(() => null);
    if (made) return made;
  }
  return null;
}

/** A manual with no parts array still has chapters; walk those for whatever they name. */
async function scrapeParts() {
  const out = [];
  const seen = new Set();
  const systems = (await T.systems(state.bikeId).catch(() => [])) || [];
  for (const sys of systems) {
    const list = (await T.partsFor(state.bikeId, sys.id).catch(() => [])) || [];
    for (const part of list) {
      if (!part || seen.has(part.id)) continue;
      seen.add(part.id);
      out.push(part);
    }
  }
  return out;
}

async function load() {
  const token = ++gen;
  let rec = T.bike(state.bikeId);
  if (!rec) {
    await T.loadCatalog().catch(() => {});
    rec = T.bike(state.bikeId);
  }
  if (token !== gen) return;
  if (!rec) {
    closeOverlay();
    return;
  }

  const made = await manualOf(rec);
  if (token !== gen) return;

  head = {
    bike: [rec.make, rec.model, rec.year].filter((x) => x != null && x !== "").join(" "),
    manual: (made && made.title) || "",
    manualId: (made && made.id) || rec.manualId || "",
  };

  let built = made ? buildIndex(made) : [];
  if (!built.length) {
    const scraped = await scrapeParts();
    if (token !== gen) return;
    built = buildIndex({ parts: scraped, sections: (made && made.sections) || [] });
  }
  rows = built;

  const order = new Map();
  for (const sys of (made && made.systems) || []) order.set(sys.name, order.size);
  const seen = new Set();
  groups = [];
  for (const row of rows) {
    const label = row.group || OTHER;
    row.group = label;
    if (!seen.has(label)) {
      seen.add(label);
      groups.push(label);
    }
  }
  groups.sort((a, z) => {
    const ai = a === OTHER ? Infinity : order.has(a) ? order.get(a) : order.size;
    const zi = z === OTHER ? Infinity : order.has(z) ? order.get(z) : order.size;
    return ai - zi;
  });

  await loadArt();
  if (token !== gen) return;
  paint();
}

/* ------------------------------------------------------------------ grid */

function onQuery(e) {
  query = e.target.value || "";
  paintGrid();
}

function paint() {
  if (!els) return;
  els.bike.textContent = head.bike;
  els.manual.textContent = head.manual;
  els.manual.hidden = !head.manual;
  paintGrid();
}

/** No query: every part, stacked under its chapter. A query: one list, best match first. */
function paintGrid() {
  if (!els) return;
  const hits = runSearch(rows, query);
  els.count.textContent = query ? `${hits.length}/${rows.length}` : String(rows.length);
  els.grid.replaceChildren();
  els.grid.scrollTop = 0;

  if (query) {
    const tiles = h("div", { class: "pv-tiles" });
    for (const row of hits) tiles.append(tile(row));
    els.grid.append(tiles);
    return;
  }

  const byGroup = new Map();
  for (const row of hits) {
    const label = row.group || OTHER;
    if (!byGroup.has(label)) byGroup.set(label, []);
    byGroup.get(label).push(row);
  }
  for (const label of groups) {
    const list = byGroup.get(label);
    if (!list || !list.length) continue;
    const tiles = h("div", { class: "pv-tiles" });
    for (const row of list) tiles.append(tile(row));
    els.grid.append(h("h3", { class: "pv-group", text: label }), tiles);
  }
}

function tile(row) {
  const part = row.part;
  const node = h("button", {
    class: "pv-tile",
    type: "button",
    "data-part": part.id,
    "aria-pressed": current && current.part.id === part.id ? "true" : "false",
  });
  if (!current && state.partId && state.partId === part.id) node.classList.add("is-now");

  node.append(h("span", { class: "pv-frame" }, artEl(part, "md")));
  node.append(h("span", { class: "pv-name", text: part.name || part.id }));
  if (part.spec) node.append(h("span", { class: "pv-spec", text: part.spec }));

  const foot = h("span", { class: "pv-foot" });
  const page = stampPage(part.page);
  if (page) foot.append(h("span", { class: "stamp", text: page }));
  if (part.oem) foot.append(h("span", { class: "pv-oem", text: part.oem }));
  if (foot.childElementCount) node.append(foot);
  return node;
}

function onGridClick(e) {
  const hit = e.target.closest && e.target.closest("[data-part]");
  if (!hit) return;
  const id = hit.getAttribute("data-part");
  const row = rows.find((r) => r.part.id === id);
  if (!row) return;
  openDetail(row);
}

/* ------------------------------------------------------------------ detail */

function openDetail(row) {
  current = row;
  shopFilter = "";
  setView("detail");
  history.pushState({ screen: "book", overlay: "invoice", pvPart: row.part.id }, "", location.hash);
  paintDetail();
  els.grid.querySelectorAll("[data-part]").forEach((node) => {
    node.setAttribute("aria-pressed", node.getAttribute("data-part") === row.part.id ? "true" : "false");
    node.classList.remove("is-now");
  });
  els.detail.scrollTop = 0;
  fetchOffers(row).catch(() => {});
}

function backToGrid() {
  current = null;
  offersGen += 1;
  setView("grid");
  if (!els) return;
  els.detail.replaceChildren();
  els.grid.querySelectorAll("[data-part]").forEach((node) => node.setAttribute("aria-pressed", "false"));
}

function paintDetail() {
  if (!els || !current) return;
  const part = current.part;

  const box = h("div", { class: "pv-det" });
  box.append(h("div", { class: "pv-hero" }, artEl(part, "lg")));
  box.append(h("h2", { class: "pv-det-name", text: part.name || part.id }));
  if (part.spec) box.append(h("p", { class: "pv-det-spec", text: part.spec }));

  const chips = h("div", { class: "pv-det-chips" });
  const page = stampPage(part.page);
  if (page) {
    chips.append(
      h("button", {
        class: "stamp pv-page",
        type: "button",
        text: page,
        "aria-label": `Open page ${part.page}`,
        on: { click: () => openPage(part) },
      })
    );
  }
  if (part.oem) chips.append(h("code", { class: "pv-det-oem", text: part.oem }));
  if (chips.childElementCount) box.append(chips);

  const offers = h("div", { class: "pv-offers" });
  offers.append(skeleton());
  box.append(offers);

  els.detail.replaceChildren(box);
  els.detail.dataset.part = part.id;
}

function skeleton() {
  const wrap = h("div", { class: "pv-skel", "aria-hidden": "true" });
  for (let i = 0; i < 4; i++) wrap.append(h("div", { class: "pv-skel-row" }));
  return wrap;
}

/** The manual's own search links: the answer when the live search has nothing. */
function shopPills(part) {
  const links = Array.isArray(part.links) ? part.links.filter((l) => l && l.url) : [];
  if (!links.length) return null;
  const box = h("div", { class: "pv-shops" });
  for (const link of links) {
    box.append(
      h("a", {
        class: "btn pv-shop",
        href: String(link.url),
        target: "_blank",
        rel: "noopener",
        text: String(link.shop || ""),
      })
    );
  }
  return box;
}

async function fetchOffers(row) {
  const token = ++offersGen;
  const part = row.part;
  const manualId = part.manualId || head.manualId;
  const body = await T.partOffers(manualId, part.id, state.bikeId);
  if (token !== offersGen || !current || current.part.id !== part.id) return;
  paintOffers(body && Array.isArray(body.offers) ? body.offers : []);
}

function paintOffers(list) {
  if (!els || !current) return;
  const box = els.detail.querySelector(".pv-offers");
  if (!box) return;
  box.replaceChildren();

  if (!list.length) {
    const pills = shopPills(current.part);
    if (pills) box.append(pills);
    return;
  }

  const shops = [...new Set(list.map((o) => String(o.retailer || "")).filter(Boolean))].sort();
  if (shopFilter && !shops.includes(shopFilter)) shopFilter = "";

  const sorts = h("div", { class: "pv-sorts", role: "group", "aria-label": "Sort" });
  for (const opt of SORTS) {
    sorts.append(
      h("button", {
        class: "pv-pill",
        type: "button",
        text: opt.label,
        "aria-pressed": sort === opt.id ? "true" : "false",
        on: {
          click: () => {
            sort = opt.id;
            paintOffers(list);
          },
        },
      })
    );
  }
  box.append(sorts);

  if (shops.length > 1) {
    const chips = h("div", { class: "pv-chips", role: "group", "aria-label": "Retailer" });
    const pick = (value) => () => {
      shopFilter = value;
      paintOffers(list);
    };
    chips.append(
      h("button", {
        class: "pv-pill",
        type: "button",
        text: "All",
        "aria-pressed": shopFilter ? "false" : "true",
        on: { click: pick("") },
      })
    );
    for (const shop of shops) {
      chips.append(
        h("button", {
          class: "pv-pill",
          type: "button",
          text: shop,
          "aria-pressed": shopFilter === shop ? "true" : "false",
          on: { click: pick(shop) },
        })
      );
    }
    box.append(chips);
  }

  const shown = sortOffers(list.filter((o) => !shopFilter || String(o.retailer || "") === shopFilter));
  const wrap = h("div", { class: "pv-rows" });
  for (const offer of shown) wrap.append(offerRow(offer));
  box.append(wrap);

  const pills = shopPills(current.part);
  if (pills) box.append(pills);
}

function condRank(value) {
  const text = String(value || "").toLowerCase();
  if (!text) return 2;
  if (text.includes("new")) return 0;
  return 1;
}

function sortOffers(list) {
  const out = list.slice();
  const price = (o) => Number(o.price);
  if (sort === "price-desc") out.sort((a, z) => price(z) - price(a));
  else if (sort === "retailer")
    out.sort((a, z) => String(a.retailer || "").localeCompare(String(z.retailer || "")) || price(a) - price(z));
  else if (sort === "condition") out.sort((a, z) => condRank(a.condition) - condRank(z.condition) || price(a) - price(z));
  else out.sort((a, z) => price(a) - price(z));
  return out;
}

function money(value, currency) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  const code = String(currency || "USD").toUpperCase();
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(n);
  } catch {
    return `${n.toFixed(2)} ${code}`;
  }
}

function offerRow(offer) {
  const a = h("a", {
    class: "pv-offer",
    href: String(offer.url),
    target: "_blank",
    rel: "noopener",
  });
  a.append(h("span", { class: "pv-o-shop", text: String(offer.retailer || "") }));

  const mid = h("span", { class: "pv-o-mid" });
  mid.append(h("span", { class: "pv-o-title", text: String(offer.title || "") }));
  if (offer.variant) mid.append(h("span", { class: "pv-o-var", text: String(offer.variant) }));

  const meta = h("span", { class: "pv-o-meta" });
  if (offer.condition) meta.append(h("span", { class: "pv-tag", text: String(offer.condition) }));
  if (offer.shipping) meta.append(h("span", { class: "pv-tag", text: String(offer.shipping) }));
  if (offer.inStock === true) meta.append(h("span", { class: "pv-tag is-in", text: "In stock" }));
  else if (offer.inStock === false) meta.append(h("span", { class: "pv-tag is-out", text: "Out" }));
  if (meta.childElementCount) mid.append(meta);
  a.append(mid);

  a.append(h("span", { class: "pv-o-price", text: money(offer.price, offer.currency) }));
  return a;
}

/* ------------------------------------------------------------------ page -> Book */

/**
 * A job Book can open for the printed page a part is specified on. Parked on the manual
 * record, which is what T.jobById() reads — the same trick pick.js uses for [p. N] chips.
 */
function bareJob(made, page, title) {
  const sectionId = `part-p${page}`;
  const found = made.jobs.find((j) => j.sectionId === sectionId);
  if (found) return found;
  const job = {
    id: `${state.bikeId}/${sectionId}`,
    bikeId: state.bikeId,
    sectionId,
    manualId: made.id,
    systemId: null,
    chapter: "",
    title,
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

async function openPage(part) {
  const page = Math.max(1, Math.floor(Number(part.page) || 0));
  if (!page) return;
  const made = await T.manual(part.manualId || head.manualId).catch(() => null);
  if (!made || !Array.isArray(made.jobs)) return;
  const job = bareJob(made, page, part.name || `Page ${page}`);
  set({ jobId: job.id, jobIds: [job.id], partId: part.id, page });
  emit("part", { partId: part.id });
  go("book", { replace: true, page });
}

/* ------------------------------------------------------------------ history */

/**
 * bus.js owns the overlay's own entry; the one detail pushes carries `pvPart`, so a Back
 * from detail lands here first and only the second Back leaves Parts altogether.
 */
if (typeof window !== "undefined") {
  window.addEventListener("popstate", (e) => {
    if (!root || root.closest("[hidden]") || !document.querySelector('[data-overlay="invoice"]:not([hidden])')) return;
    const wanted = e.state && e.state.pvPart;
    if (wanted) {
      const row = rows.find((r) => r.part.id === wanted);
      if (row && (!current || current.part.id !== wanted)) {
        current = row;
        setView("detail");
        paintDetail();
        fetchOffers(row).catch(() => {});
      }
      return;
    }
    if (view === "detail") backToGrid();
  });
}
