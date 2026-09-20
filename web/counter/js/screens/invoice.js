import { state, go, registerScreen } from "../bus.js";
import * as T from "../ttm.js";

const SVG = "http://www.w3.org/2000/svg";
const EXT_PATH = "M9 5H5v14h14v-4M14 5h6v6M20 5 11 14";

let root;
let els;
let gen = 0;
let parts = [];
let head = { bike: "", job: "", page: null };

registerScreen("invoice", { mount, enter, leave() {} });

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

function bounce() {
  queueMicrotask(() => go(state.bikeId ? "pick" : "identify", { replace: true }));
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

  const headBox = h("div", { class: "sheet inv-head" });
  const meta = h("div", { class: "inv-meta" });
  const name = h("div", { class: "inv-name" });
  const bike = h("div", { class: "inv-bike" });
  meta.append(name, bike);
  const stamp = h("span", { class: "stamp" });
  headBox.append(meta, stamp);

  const list = h("div", { class: "inv-list" });

  const wrapTix = h("div", { class: "inv-tix-wrap" });
  const ticket = h("div", { class: "card inv-ticket" });
  const tixTop = h("div", { class: "inv-tix-top" });
  const tixBike = h("div", { class: "inv-tix-bike" });
  const tixNo = h("b", { class: "inv-tix-no" });
  tixTop.append(tixBike, tixNo);
  const tixRows = h("div", { class: "inv-tix-rows" });
  ticket.append(tixTop, tixRows);
  wrapTix.append(ticket);

  const foot = h("div", { class: "inv-foot" });
  const send = h("a", { class: "btn btn-primary", text: "Quote", hidden: true });
  const save = h("button", { type: "button", class: "btn", text: "Save" });
  save.addEventListener("click", () => {
    savePng().catch(() => {});
  });
  foot.append(send, save);

  wrap.append(headBox, list, wrapTix, foot);
  root.append(wrap);

  els = { name, bike, stamp, list, tixBike, tixNo, tixRows, send, save };
}

function enter() {
  if (!state.bikeId) {
    bounce();
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
    bounce();
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
  for (const part of parts) {
    els.list.append(partCard(part));
  }

  els.tixBike.textContent = head.bike;
  els.tixNo.textContent = state.ticket || "";
  els.tixRows.replaceChildren();
  for (const part of parts) {
    const row = h("div", { class: "inv-tix-row" });
    const detail = h("div", { class: "inv-tix-detail" });
    detail.append(h("div", { class: "inv-tix-part", text: part.name || "" }));
    if (part.spec) detail.append(h("div", { class: "inv-tix-spec", text: part.spec }));
    if (part.oem) detail.append(h("div", { class: "inv-oem", text: part.oem }));
    row.append(h("span", { class: "inv-tix-lab", text: "Part" }), detail, h("span", { class: "inv-amt", text: stampPage(part.page) }));
    els.tixRows.append(row);
  }

  const target = quoteTarget(parts[0]);
  if (target) {
    els.send.hidden = false;
    els.send.setAttribute("href", target);
    els.send.setAttribute("target", "_blank");
    els.send.setAttribute("rel", "noopener");
  } else {
    els.send.hidden = true;
    els.send.removeAttribute("href");
  }
}

function partCard(part) {
  const card = h("div", { class: "card inv-part" });
  const listing = h("div", { class: "inv-listing" });
  listing.append(h("span", { class: "inv-pname", text: part.name || "" }));
  const page = stampPage(part.page);
  if (page) listing.append(h("span", { class: "stamp", text: page }));
  card.append(listing);
  if (part.spec) card.append(h("div", { class: "inv-prov", text: part.spec }));
  if (part.oem) card.append(h("div", { class: "inv-oem", text: part.oem }));
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

/** Their quote request, kept alive only when a part carries a merchant contact. */
function quoteTarget(part) {
  if (!part) return "";
  const email = part.email || (part.merchant && part.merchant.email) || "";
  const contact = part.contactUrl || (part.merchant && part.merchant.contactUrl) || "";
  if (!email && !contact) return "";
  if (contact) return String(contact);
  const subject = `Quote request — ${head.bike} — ${part.name || ""} ${part.oem || ""}`.trim();
  const body = [
    `Part:      ${part.name || ""}`,
    `OEM no.:   ${part.oem || ""}`,
    `Spec:      ${part.spec || ""}`,
    `Manual:    ${stampPage(part.page)}`,
  ].join("\r\n");
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function wrapText(ctx, text, maxWidth) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const out = [];
  let cur = "";
  for (const word of words) {
    const next = cur ? `${cur} ${word}` : word;
    if (cur && ctx.measureText(next).width > maxWidth) {
      out.push(cur);
      cur = word;
    } else {
      cur = next;
    }
  }
  if (cur) out.push(cur);
  return out;
}

function drawTicket(ctx, w, hgt) {
  ctx.fillStyle = "#ece7dc";
  ctx.fillRect(0, 0, w, hgt);
  const x = 24;
  const y = 24;
  const tw = w - 48;
  const th = hgt - 48;
  ctx.fillStyle = "#fff";
  ctx.fillRect(x, y, tw, th);
  ctx.strokeStyle = "#141414";
  ctx.lineWidth = 3;
  ctx.setLineDash([10, 8]);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + tw, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeRect(x, y + 1.5, tw, th - 1.5);

  ctx.fillStyle = "#e85d04";
  ctx.fillRect(x, y + 3, tw, 52);
  ctx.fillStyle = "#fff";
  ctx.font = "800 32px 'Big Shoulders Display', sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillText(String(state.ticket || ""), x + tw - 16, y + 29);
  ctx.textAlign = "left";
  ctx.font = "800 22px Barlow, sans-serif";
  ctx.fillText(head.bike, x + 16, y + 29);

  ctx.textBaseline = "top";
  ctx.fillStyle = "#141414";
  let ry = y + 74;
  const px = x + 16;
  const room = tw - 32;
  for (const part of parts) {
    ctx.font = "800 20px Barlow, sans-serif";
    ctx.fillText(String(part.name || ""), px, ry);
    ctx.textAlign = "right";
    ctx.font = "16px ui-monospace, monospace";
    ctx.fillText(stampPage(part.page), x + tw - 16, ry + 3);
    ctx.textAlign = "left";
    ry += 26;
    ctx.font = "14px ui-monospace, monospace";
    for (const line of wrapText(ctx, part.spec, room - 90)) {
      ctx.fillText(line, px, ry);
      ry += 18;
    }
    if (part.oem) {
      ctx.fillText(String(part.oem), px, ry);
      ry += 18;
    }
    ry += 10;
    ctx.strokeStyle = "#e4dfd2";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(px, ry - 5);
    ctx.lineTo(x + tw - 16, ry - 5);
    ctx.stroke();
    ctx.strokeStyle = "#141414";
  }
}

function ticketHeight() {
  let n = 120;
  for (const part of parts) {
    n += 26 + 28 + (part.oem ? 18 : 0) + Math.max(1, Math.ceil(String(part.spec || "").length / 52)) * 18;
  }
  return Math.max(320, n);
}

async function savePng() {
  if (!parts.length) return;
  if (document.fonts && document.fonts.ready) {
    try {
      await document.fonts.ready;
    } catch {
      /* keep going */
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = 780;
  canvas.height = ticketHeight();
  drawTicket(canvas.getContext("2d"), canvas.width, canvas.height);
  await new Promise((resolve) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        resolve();
        return;
      }
      const a = h("a");
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = `handy-book-${state.ticket}.png`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      resolve();
    }, "image/png");
  });
}
