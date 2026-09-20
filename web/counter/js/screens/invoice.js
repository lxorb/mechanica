/**
 * Parts — the full-screen view over Book. Owner: parts-UI agent.
 *
 * Two states in one overlay:
 *   grid    every part that fits THIS vehicle, as large illustrated tiles under sticky
 *           chapter headings, filtered by one typo-tolerant search field
 *           (../parts-search.js). The rows come from `T.partCatalog` — the per-vehicle
 *           catalogue, where a taxonomy entry (`standard`) carries the group, the
 *           illustration and the pages that mention it, and a printed entry carries the
 *           spec, the page and the OEM number on top. While that route is still a 404 the
 *           view falls back to the manual's own `parts[]`, grouped by chapter.
 *   detail  one part blown up — illustration, name and spec verbatim, every page that
 *           mentions it as a tappable `p. N` chip (-> Book), the OEM number — then the
 *           live retailer offers from `T.partOffers`, one row per offer, priced in USD,
 *           sortable and filterable. A cold search takes 10-20 s, so the rows sit under a
 *           skeleton and a thin bar for up to 25 s and are looked at once more 10 s later;
 *           only then do the manual's own shop links stand in. Nothing is invented here.
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
import { PART_ICONS, iconFor, iconUrl } from "../particons.js";
import { strip as climateStrip } from "../climate.js";
import {
  GROUPS,
  index as buildIndex,
  indexCatalog,
  search as runSearch,
} from "../parts-search.js";

const ART_DIR = "../store/icons-parts-3d/";
const OTHER = "Other";
const BAR_MS = 35000; // how long the progress bar takes to crawl to its cap
const RECHECK_MS = 10000; // the backend keeps fetching in the background; look again
const DEAD_MS = 2000; // an answer this fast and this empty is a missing route, not a search
const MENTION_CAP = 12;

const SORTS = [
  { id: "price-asc", label: "Price ↑" },
  { id: "price-desc", label: "Price ↓" },
  { id: "retailer", label: "Retailer" },
  { id: "condition", label: "Condition" },
];

const KNOWN_ICON = new Set(PART_ICONS);

let root;
let els;
let gen = 0;
let offersGen = 0;
let barTimer = null;

let rows = []; // [{ part, group, ... }] from parts-search.js
let groups = []; // ordered group labels
let query = "";
let view = "grid";
let current = null; // the row the detail is showing
let head = { bike: "", manual: "", manualId: "" };
let sort = "price-asc";
let shopFilter = "";
let allMentions = false;

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

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

function stampPage(n) {
  return n == null || n === "" ? "" : `p. ${n}`;
}

function mentionsOf(part) {
  return Array.isArray(part.mentions) ? part.mentions.filter((m) => m && m.page) : [];
}

/** The page to stamp: the one the spec is printed on, else the first that mentions it. */
function pageOf(part) {
  if (part.page != null && part.page !== "") return part.page;
  const first = mentionsOf(part)[0];
  return first ? first.page : null;
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

/** The catalogue names its illustration; everything else is read off the part's own name. */
function artFor(part) {
  const guess = iconFor(part.name, [part.spec || "", part.id || ""]);
  const line = part.icon && KNOWN_ICON.has(part.icon) ? part.icon : guess;
  const rec = art ? art[part.icon] || art[part.id] || art[line] : null;
  if (!rec) return { svg: iconUrl(line) };
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

  // Climate Fit: the verdicts that need an action, each still carrying its manual page.
  root.append(header, searchBar, climateStrip(), panes);
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
  stopOffers();
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

/** Catalogue order when the route answers, the manual's own chapter order when it does not. */
function orderGroups(made, catalogue) {
  const seen = new Set();
  const present = [];
  for (const row of rows) {
    const label = row.group || OTHER;
    row.group = label;
    if (!seen.has(label)) {
      seen.add(label);
      present.push(label);
    }
  }
  const order = new Map();
  if (catalogue) GROUPS.forEach(([, label], i) => order.set(label, i));
  else for (const sys of (made && made.systems) || []) order.set(sys.name, order.size);
  return present.sort((a, z) => {
    const ai = a === OTHER ? Infinity : order.has(a) ? order.get(a) : order.size;
    const zi = z === OTHER ? Infinity : order.has(z) ? order.get(z) : order.size;
    return ai - zi;
  });
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

  // The backend starts fetching this vehicle's common parts now, so the first tap is warm.
  T.warmOffers(head.manualId, state.bikeId).catch(() => {});

  const catalogue = await T.partCatalog(head.manualId, state.bikeId).catch(() => null);
  if (token !== gen) return;

  if (catalogue && catalogue.length) {
    rows = indexCatalog(catalogue);
  } else {
    let built = made ? buildIndex(made) : [];
    if (!built.length) {
      const scraped = await scrapeParts();
      if (token !== gen) return;
      built = buildIndex({ parts: scraped, sections: (made && made.sections) || [] });
    }
    rows = built;
  }
  groups = orderGroups(made, Boolean(catalogue && catalogue.length));

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

/** No query: every part, stacked under its group. A query: one list, best match first. */
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
    // One section per shelf, so its heading sticks over its own tiles and is pushed off by
    // the next one instead of every heading piling up at the top.
    els.grid.append(h("section", { class: "pv-shelf" }, h("h3", { class: "pv-group", text: label }), tiles));
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
  // always present, so every tile reserves the same spec line and the rows line up
  node.append(h("span", { class: "pv-spec", text: part.spec || "" }));

  const foot = h("span", { class: "pv-foot" });
  const page = stampPage(pageOf(part));
  // Printed in the manual: the solid stamp. Catalogue entry the manual only mentions: hollow.
  if (page) foot.append(h("span", { class: part.page != null ? "stamp" : "stamp pv-ref", text: page }));
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
  allMentions = false;
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
  stopOffers();
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
  if (part.page != null && part.page !== "") chips.append(pageChip(part, part.page, "stamp pv-page", part.spec || ""));
  if (part.oem) chips.append(h("code", { class: "pv-det-oem", text: part.oem }));
  if (chips.childElementCount) box.append(chips);

  const mentions = mentionsOf(part).filter((m) => m.page !== part.page);
  if (mentions.length) {
    const wrap = h("div", { class: "pv-mentions" });
    const shown = allMentions ? mentions : mentions.slice(0, MENTION_CAP);
    for (const m of shown) wrap.append(pageChip(part, m.page, "stamp pv-page pv-ref", m.quote || ""));
    if (!allMentions && mentions.length > shown.length) {
      wrap.append(
        h("button", {
          class: "stamp pv-page pv-more",
          type: "button",
          text: `+${mentions.length - shown.length}`,
          on: {
            click: () => {
              allMentions = true;
              paintDetail();
              fetchOffers(current).catch(() => {});
            },
          },
        })
      );
    }
    box.append(wrap);
  }

  const offers = h("div", { class: "pv-offers" });
  offers.append(waiting());
  box.append(offers);

  els.detail.replaceChildren(box);
  els.detail.dataset.part = part.id;
}

/** `p. N`, tappable: Book opens on that printed page. The quote is its accessible name. */
function pageChip(part, page, cls, quote) {
  return h("button", {
    class: cls,
    type: "button",
    text: stampPage(page),
    title: quote || undefined,
    "aria-label": quote ? `Page ${page}: ${quote}` : `Open page ${page}`,
    on: { click: () => openPage(part, page) },
  });
}

/* ------------------------------------------------------------------ offers */

function stopOffers() {
  offersGen += 1;
  if (barTimer) {
    clearInterval(barTimer);
    barTimer = null;
  }
}

/** Skeleton rows under a thin bar: a cold retailer search really does take 10-20 s. */
function waiting() {
  const wrap = h("div", { class: "pv-wait", "aria-busy": "true" });
  const bar = h("div", { class: "pv-bar" });
  const fill = h("i");
  bar.append(fill);
  wrap.append(bar);
  const skel = h("div", { class: "pv-skel", "aria-hidden": "true" });
  for (let i = 0; i < 4; i++) skel.append(h("div", { class: "pv-skel-row" }));
  wrap.append(skel);

  if (barTimer) clearInterval(barTimer);
  const started = Date.now();
  barTimer = setInterval(() => {
    if (!fill.isConnected) {
      clearInterval(barTimer);
      barTimer = null;
      return;
    }
    const done = Math.min(0.97, (Date.now() - started) / BAR_MS);
    fill.style.width = `${(done * 100).toFixed(1)}%`;
  }, 200);
  return wrap;
}

/** The manual's own search links: the answer when the live search comes back with nothing. */
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

function stale(token, part) {
  return token !== offersGen || !current || current.part.id !== part.id;
}

/**
 * One look worth up to 25 s, then — because the backend keeps searching in the background
 * and fills its own cache — one more 10 s later. A route that is simply not there answers
 * instantly and empty, and gets the pills straight away instead of a 35 s wait.
 */
async function fetchOffers(row) {
  const token = ++offersGen;
  const part = row.part;
  const manualId = part.manualId || head.manualId;

  const started = Date.now();
  let body = await T.partOffers(manualId, part.id, state.bikeId);
  if (stale(token, part)) return;
  if (body && body.offers.length) {
    paintOffers(body.offers);
    return;
  }
  if (!body && Date.now() - started < DEAD_MS) {
    paintOffers([]);
    return;
  }

  await sleep(RECHECK_MS);
  if (stale(token, part)) return;
  body = await T.partOffers(manualId, part.id, state.bikeId, { fresh: true });
  if (stale(token, part)) return;
  paintOffers(body && Array.isArray(body.offers) ? body.offers : []);
}

function paintOffers(list) {
  if (!els || !current) return;
  const box = els.detail.querySelector(".pv-offers");
  if (!box) return;
  if (barTimer) {
    clearInterval(barTimer);
    barTimer = null;
  }
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

/** Dollars, always: what the rows are ranked and compared on. */
function usd(offer) {
  const n = Number(offer.priceUsd == null ? offer.price : offer.priceUsd);
  return Number.isFinite(n) ? n : Infinity;
}

function condRank(value) {
  const text = String(value || "").toLowerCase();
  if (!text) return 2;
  if (text.includes("new")) return 0;
  return 1;
}

function sortOffers(list) {
  const out = list.slice();
  if (sort === "price-desc") out.sort((a, z) => usd(z) - usd(a));
  else if (sort === "retailer")
    out.sort((a, z) => String(a.retailer || "").localeCompare(String(z.retailer || "")) || usd(a) - usd(z));
  else if (sort === "condition") out.sort((a, z) => condRank(a.condition) - condRank(z.condition) || usd(a) - usd(z));
  else out.sort((a, z) => usd(a) - usd(z));
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

/** One row per offer — several from the same seller is normal, they are different products. */
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

  const cost = h("span", { class: "pv-o-cost" });
  cost.append(h("b", { class: "pv-o-price", text: money(usd(offer), "USD") }));
  const code = String(offer.currency || "USD").toUpperCase();
  if (offer.price != null && code !== "USD") {
    cost.append(h("span", { class: "pv-o-orig", text: money(offer.price, code) }));
  }
  a.append(cost);
  return a;
}

/* ------------------------------------------------------------------ page -> Book */

/**
 * A job Book can open for a printed page. Parked on the manual record, which is what
 * T.jobById() reads — the same trick pick.js uses for its [p. N] chips.
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

async function openPage(part, wanted) {
  const page = Math.max(1, Math.floor(Number(wanted == null ? pageOf(part) : wanted) || 0));
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
    if (!root || !document.querySelector('[data-overlay="invoice"]:not([hidden])')) return;
    const wanted = e.state && e.state.pvPart;
    if (wanted) {
      const row = rows.find((r) => r.part.id === wanted);
      if (row && (!current || current.part.id !== wanted)) {
        current = row;
        allMentions = false;
        setView("detail");
        paintDetail();
        fetchOffers(row).catch(() => {});
      }
      return;
    }
    if (view === "detail") backToGrid();
  });
}
