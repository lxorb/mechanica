/**
 * Parts — the optional sheet over Book. Only what our manuals actually carry: an icon,
 * the part name, the spec verbatim, the page it is written on, the OEM number and the
 * shops. No quote flow, no prices: the manual is the answer.
 */

import { state, closeOverlay, registerOverlay } from "../bus.js";
import * as T from "../ttm.js";
import { iconElFor } from "../particons.js";

const SVG = "http://www.w3.org/2000/svg";
const EXT_PATH = "M9 5H5v14h14v-4M14 5h6v6M20 5 11 14";

let root;
let els;
let gen = 0;
let parts = [];
let head = { bike: "", job: "", page: null };

registerOverlay("invoice", { mount, open });

function h(tag, attrs) {
  const node = document.createElement(tag);
  if (!attrs) return node;
  for (const [key, val] of Object.entries(attrs)) {
    if (val == null || val === false) continue;
    if (key === "class") node.className = val;
    else if (key === "text") node.textContent = val;
    else if (key === "hidden") node.hidden = true;
    else node.setAttribute(key, val === true ? "" : String(val));
  }
  return node;
}

function extGlyph() {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.4");
  path.setAttribute("stroke-linecap", "square");
  path.setAttribute("d", EXT_PATH);
  svg.append(path);
  return svg;
}

function stampPage(n) {
  return n == null || n === "" ? "" : `p. ${n}`;
}

function jobIds() {
  const list = Array.isArray(state.jobIds) ? state.jobIds.filter(Boolean) : [];
  if (state.jobId && !list.includes(state.jobId)) list.unshift(state.jobId);
  return list;
}

async function jobRows() {
  const rows = [];
  for (const id of jobIds()) {
    try {
      const job = await T.jobById(id);
      if (job) rows.push(job);
    } catch {
      /* a stale job id is not an error */
    }
  }
  return rows;
}

/** Manual-scoped first: bare part ids repeat across manuals. */
function partOf(manualId, id) {
  return (manualId ? T.part(`${manualId}/${id}`) : undefined) || T.part(id);
}

function partsOfJobs(jobs) {
  const seen = new Set();
  const out = [];
  for (const job of jobs) {
    const ids = Array.isArray(job.partIds) ? job.partIds.slice() : [];
    if (job.partId && !ids.includes(job.partId)) ids.unshift(job.partId);
    for (const id of ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      const part = partOf(job.manualId, id);
      if (part) out.push(part);
    }
  }
  return out;
}

async function allParts(manualId) {
  if (manualId) {
    try {
      const man = await T.manual(manualId);
      if (man && Array.isArray(man.parts) && man.parts.length) return man.parts;
    } catch {
      /* fall through to the chapters */
    }
  }
  const out = [];
  const seen = new Set();
  let systems = [];
  try {
    systems = (await T.systems(state.bikeId)) || [];
  } catch {
    systems = [];
  }
  for (const sys of systems) {
    let rows = [];
    try {
      rows = (await T.partsFor(state.bikeId, sys.id)) || [];
    } catch {
      rows = [];
    }
    for (const part of rows) {
      if (!part || seen.has(part.id)) continue;
      seen.add(part.id);
      out.push(part);
    }
  }
  return out;
}

function order(rows) {
  if (!state.partId) return rows;
  const first = rows.filter((row) => row.id === state.partId);
  if (!first.length) return rows;
  return first.concat(rows.filter((row) => row.id !== state.partId));
}

function mount(node) {
  root = node;
  root.replaceChildren();

  const wrap = h("div", { class: "inv" });

  const headBox = h("div", { class: "inv-head" });
  const meta = h("div", { class: "inv-meta" });
  const name = h("div", { class: "inv-name" });
  const bike = h("div", { class: "inv-bike" });
  meta.append(name, bike);
  const stamp = h("span", { class: "stamp" });
  headBox.append(meta, stamp);

  const list = h("div", { class: "inv-list" });
  const empty = h("p", { class: "inv-empty", text: "No parts named on these pages.", hidden: true });

  wrap.append(headBox, list, empty);
  root.append(wrap);

  els = { name, bike, stamp, list, empty };
}

function open() {
  if (!state.bikeId) {
    closeOverlay();
    return;
  }
  load().catch(() => {});
}

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
    closeOverlay();
    return;
  }

  const jobs = await jobRows();
  if (token !== gen) return;
  const job = jobs[0];
  head = {
    bike: [rec.make, rec.model, rec.year].filter((x) => x != null && x !== "").join(" "),
    job: (job && job.title) || "",
    page: job ? (Array.isArray(job.pages) && job.pages[0] != null ? job.pages[0] : job.pageStart) : null,
  };

  let rows = partsOfJobs(jobs);
  if (!rows.length) {
    rows = await allParts(rec.manualId || (job && job.manualId));
    if (token !== gen) return;
  }
  parts = order(rows.filter(Boolean));
  paint();
}

function paint() {
  if (!els) return;
  els.name.textContent = head.job;
  els.bike.textContent = head.bike;
  els.stamp.textContent = stampPage(head.page);
  els.stamp.hidden = !head.page;

  els.list.replaceChildren();
  for (const part of parts) els.list.append(partCard(part));
  els.empty.hidden = parts.length > 0;
}

function partCard(part) {
  const card = h("div", { class: "card inv-part" });

  const top = h("div", { class: "inv-top" });
  top.append(iconElFor(part.name, part.keywords || [], "sm"));
  const listing = h("div", { class: "inv-listing" });
  listing.append(h("span", { class: "inv-pname", text: part.name || "" }));
  if (part.oem) listing.append(h("span", { class: "inv-oem", text: part.oem }));
  top.append(listing);
  const page = stampPage(part.page);
  if (page) top.append(h("span", { class: "stamp", text: page }));
  card.append(top);

  if (part.spec) card.append(h("div", { class: "inv-prov", text: part.spec }));

  const links = Array.isArray(part.links) ? part.links.filter((l) => l && l.url) : [];
  if (links.length) {
    const shops = h("div", { class: "inv-shops" });
    for (const link of links) {
      const a = h("a", {
        class: "btn inv-shop",
        href: String(link.url),
        target: "_blank",
        rel: "noopener",
        text: String(link.shop || ""),
      });
      a.append(extGlyph());
      shops.append(a);
    }
    card.append(shops);
  }
  return card;
}
