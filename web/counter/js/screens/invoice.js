import { state, set, go, emit, registerScreen } from "../bus.js";
import * as Q from "../query.js";

const TAX = 0.0825;
const QTY_MIN = 1;
const QTY_MAX = 99;
const CHANNELS = [
  ["quote", "Quote"],
  ["new", "New"],
  ["used", "Used"],
  ["other", "Other"],
];
const CHANNEL_IDS = CHANNELS.map(([id]) => id);
const SVG = "http://www.w3.org/2000/svg";
const EXT_PATH = "M9 5H5v14h14v-4M14 5h6v6M20 5 11 14";

let root;
let els;
let seenJob = null;
let pickUsed = -1;
let pickAlt = -1;

function bounce() {
  queueMicrotask(() => go(state.bikeId ? "pick" : "identify", { replace: true }));
}

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
  path.setAttribute("stroke-linejoin", "miter");
  path.setAttribute("d", EXT_PATH);
  svg.append(path);
  return svg;
}

function money(n, dash) {
  if (dash) return "—";
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  if (v === 0) return "Free";
  return "$" + v.toFixed(2);
}

function finite(n) {
  return Number.isFinite(Number(n));
}

function qtyOf() {
  const n = Number(state.qty);
  if (Number.isInteger(n) && n >= QTY_MIN) return Math.min(QTY_MAX, n);
  return QTY_MIN;
}

function totals(price, ship, qty) {
  const q = Number.isInteger(qty) && qty >= QTY_MIN ? qty : QTY_MIN;
  const pc = finite(price) ? Math.round(Number(price) * 100) * q : 0;
  const sc = finite(ship) ? Math.round(Number(ship) * 100) : 0;
  const tc = Math.round((pc + sc) * TAX);
  return { price: pc / 100, ship: sc / 100, tax: tc / 100, total: (pc + sc + tc) / 100 };
}

function jobOf() {
  return state.jobId ? Q.jobById(state.jobId) : undefined;
}

function newRecord(job) {
  if (!job || job.new == null || typeof job.new !== "object") return null;
  return job.new;
}

function listingNew(job) {
  if (!job) return null;
  if (job.new === null) return null;
  if (job.new && typeof job.new === "object") return job.new;
  return {
    from: job.from,
    url: job.url,
    price: job.price,
    currency: job.currency,
    ship: job.ship,
    days: job.days,
    retrieved: job.retrieved,
    oem: job.oem,
    oemVerified: job.oemVerified,
  };
}

function strField(row, key) {
  if (!row || typeof row !== "object") return "";
  const val = row[key];
  if (val == null || val === "") return "";
  return String(val);
}

function oemOf(job) {
  const neu = listingNew(job);
  if (neu && neu.oem != null && neu.oem !== "") return String(neu.oem);
  return job && job.oem != null ? String(job.oem) : "";
}

function oemVerifiedOf(job) {
  const neu = listingNew(job);
  if (neu && Object.prototype.hasOwnProperty.call(neu, "oemVerified")) return neu.oemVerified;
  return job ? job.oemVerified : undefined;
}

function hrefOf(row) {
  if (!row || typeof row !== "object") return "";
  const url = row.url;
  if (url == null || url === "") return "";
  return String(url);
}

function provText(from, retrieved) {
  const a = from != null && from !== "" ? String(from) : "";
  const b = retrieved != null && retrieved !== "" ? String(retrieved) : "";
  if (a && b) return a + " · " + b;
  return a || b;
}

function daysText(days) {
  if (days == null || days === "") return "";
  const n = Number(days);
  if (!Number.isFinite(n)) return "";
  return n + " d";
}

function shipDetail(line) {
  const from = line && line.from != null && line.from !== "" ? String(line.from) : "";
  const days = daysText(line && line.days);
  if (from && days) return from + "  " + days;
  return from || days;
}

function lineOf(job) {
  const ch = state.channel;
  if (ch === "used" && pickUsed >= 0) {
    const row = Array.isArray(job.used) ? job.used[pickUsed] : null;
    if (row && typeof row === "object") {
      return {
        price: row.price,
        ship: 0,
        dash: !finite(row.price),
        from: row.from,
        retrieved: row.retrieved,
        url: hrefOf(row),
        days: row.days,
        shipKnown: true,
      };
    }
  }
  if (ch === "other" && pickAlt >= 0 && Array.isArray(job.alts) && job.alts[pickAlt] != null) {
    const row = job.alts[pickAlt];
    if (typeof row === "string") {
      return { price: 0, ship: 0, dash: true, from: "", retrieved: "", url: "", days: "", shipKnown: true };
    }
    return {
      price: 0,
      ship: 0,
      dash: true,
      from: row.from,
      retrieved: row.retrieved,
      url: hrefOf(row),
      days: row.days,
      shipKnown: true,
    };
  }
  const neu = listingNew(job);
  if (neu == null) {
    return { price: 0, ship: 0, dash: true, from: "", retrieved: "", url: "", days: "", shipKnown: false };
  }
  return {
    price: neu.price,
    ship: neu.ship,
    dash: !finite(neu.price),
    from: neu.from,
    retrieved: neu.retrieved,
    url: hrefOf(neu),
    days: neu.days,
    shipKnown: neu.ship != null && neu.ship !== "",
  };
}

function shipText(line, t, dash) {
  if (dash) return "—";
  if (!line.shipKnown && (line.ship == null || line.ship === "")) return "";
  return money(t.ship, false);
}

function qtyUnitText(line, qty, dash) {
  return String(qty) + " × " + money(line.price, dash || !finite(line.price));
}

function priceRef(neu) {
  if (!neu || !finite(neu.price)) return "";
  return String(Number(neu.price));
}

function quoteMailto(job, part, bike) {
  const neu = newRecord(job);
  const email = strField(neu, "email").trim();
  const merchant = strField(neu, "from");
  const oem = oemOf(job);
  const qty = qtyOf();
  const year = bike.year != null && bike.year !== "" ? String(bike.year) : "";
  const make = bike.make != null && bike.make !== "" ? String(bike.make) : "";
  const model = bike.model != null && bike.model !== "" ? String(bike.model) : "";
  const name = part.name != null && part.name !== "" ? String(part.name) : "";
  const url = hrefOf(neu);
  const retrieved = strField(neu, "retrieved");
  const currency = strField(neu, "currency");
  const price = priceRef(neu);
  const bikePhrase = [year, make, model].filter(Boolean).join(" ");
  const subject = "Quote request — " + bikePhrase + " — " + name + " " + oem;
  const body = [
    "Hello " + merchant + " parts desk,",
    "",
    "Please quote the following for a " + bikePhrase + ":",
    "",
    "Part:      " + name,
    "OEM no.:   " + oem,
    "Quantity:  " + qty,
    "Ship to:   (please advise shipping options and ETA)",
    "",
    "Reference listing: " + url + " (seen " + retrieved + ", " + price + " " + currency + ")",
    "",
    "Kindly reply with unit price, availability and lead time.",
    "",
    "Thank you",
  ].join("\r\n");
  return "mailto:" + email + "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
}

function quoteTarget(job) {
  const neu = newRecord(job);
  if (!neu) return { hidden: true, href: "", external: false };
  const email = strField(neu, "email").trim();
  const contactUrl = strField(neu, "contactUrl").trim();
  if (email) return { hidden: false, href: "", external: false, email: true };
  if (contactUrl) return { hidden: false, href: contactUrl, external: true };
  return { hidden: true, href: "", external: false };
}

function setChannel(ch) {
  if (state.channel === ch) return;
  set({ channel: ch });
  emit("channel", { ch });
  paint();
}

function setQty(next) {
  const n = Math.max(QTY_MIN, Math.min(QTY_MAX, Math.floor(Number(next) || QTY_MIN)));
  if (n !== qtyOf() || state.qty !== n) set({ qty: n });
  paintQty();
  paintTicket();
}

function listKey(rows) {
  return rows
    .map((row) =>
      typeof row === "string"
        ? row
        : [row.label, row.from, row.where, row.price, row.url, row.retrieved].join("\0")
    )
    .join("\n");
}

function syncRowState(box, selected) {
  const kids = box.children;
  for (let i = 0; i < kids.length; i++) {
    const on = i === selected;
    kids[i].classList.toggle("selected", on);
    kids[i].classList.toggle("btn-primary", on);
    kids[i].setAttribute("aria-pressed", on ? "true" : "false");
  }
}

function bindHref(node, url, label) {
  if (url) {
    node.setAttribute("href", url);
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener");
    if (label && node.classList.contains("inv-ext")) node.setAttribute("aria-label", label);
    node.hidden = false;
  } else {
    node.removeAttribute("href");
    node.removeAttribute("target");
    node.removeAttribute("rel");
    node.removeAttribute("aria-label");
    if (node.classList.contains("inv-ext")) node.hidden = true;
  }
}

function fillList(box, rows, selected, onPick) {
  const key = listKey(rows);
  if (box.dataset.rows === key && box.childElementCount === rows.length) {
    syncRowState(box, selected);
    return;
  }
  box.replaceChildren();
  box.dataset.rows = key;
  rows.forEach((row, i) => {
    const btn = h("div", { class: "card inv-row", role: "button", tabindex: "0", "aria-pressed": "false" });
    if (typeof row === "string") {
      btn.append(h("span", { text: row }));
    } else {
      const url = hrefOf(row);
      const listing = h(url ? "a" : "div", { class: "inv-listing" });
      if (url) bindHref(listing, url, row.from || row.label || "");
      const label = row.label != null && row.label !== "" ? row.label : row.from || "";
      listing.append(h("span", { text: label }));
      if (row.where) listing.append(h("span", { text: row.where }));
      if (finite(row.price)) listing.append(h("span", { class: "inv-amt", text: money(row.price, false) }));
      btn.append(listing);
      if (url) {
        const ext = h("a", { class: "btn btn-icon inv-ext" });
        bindHref(ext, url, row.from || row.label || "");
        ext.append(extGlyph());
        btn.append(ext);
      }
      const prov = provText(row.from, row.retrieved);
      if (prov) btn.append(h("div", { class: "inv-prov", text: prov }));
    }
    btn.addEventListener("click", () => onPick(i, btn));
    btn.addEventListener("keydown", (ev) => {
      if (ev.target !== btn) return;
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      onPick(i, btn);
    });
    box.append(btn);
  });
  syncRowState(box, selected);
}

function clearList(box) {
  box.replaceChildren();
  delete box.dataset.rows;
}

function pickRow(kind, i, node) {
  if (kind === "used") pickUsed = i;
  else pickAlt = i;
  const box = kind === "used" ? els.used : els.alts;
  syncRowState(box, i);
  paintTicket();
  if (node && document.activeElement !== node) node.focus();
}

function markOem(node, oem, verified) {
  node.textContent = oem;
  node.classList.toggle("is-dash", verified === false);
}

function fillSources(line) {
  const text = provText(line.from, line.retrieved);
  if (!text) {
    els.tixSrc.replaceChildren();
    els.tixSrc.hidden = true;
    return;
  }
  els.tixSrc.hidden = false;
  const url = line.url;
  const node = url ? h("a", { class: "inv-prov inv-src" }) : h("div", { class: "inv-prov inv-src" });
  node.textContent = text;
  if (url) bindHref(node, url, text);
  els.tixSrc.replaceChildren(node);
}

function paintQty() {
  const qty = qtyOf();
  els.qtyN.textContent = String(qty);
  els.qtyDec.disabled = qty <= QTY_MIN;
  els.qtyInc.disabled = qty >= QTY_MAX;
}

function paintTicket() {
  if (!els) return;
  const job = jobOf();
  if (!job) return;
  const part = Q.part(job.partId) || {};
  const bike = Q.bike(job.bikeId) || Q.bike(state.bikeId) || {};
  const line = lineOf(job);
  const qty = qtyOf();
  const t = line.dash ? { price: 0, ship: 0, tax: 0, total: 0 } : totals(line.price, line.ship, qty);
  const dash = line.dash;
  const oem = oemOf(job);
  els.tixNo.textContent = state.ticket || "";
  els.tixBike.textContent = [bike.make, bike.model, bike.year].filter((x) => x != null && x !== "").join(" ");
  els.tixPart.textContent = part.name || "";
  markOem(els.tixOem, oem, oemVerifiedOf(job));
  els.tixQty.textContent = qtyUnitText(line, qty, dash);
  els.amtPart.textContent = money(t.price, dash);
  els.tixShip.textContent = shipDetail(line);
  els.amtShip.textContent = shipText(line, t, dash);
  els.amtTax.textContent = money(t.tax, dash);
  els.amtTotal.textContent = money(t.total, dash);
  fillSources(line);
  syncQuote(job, part, bike);
}

function syncQuote(job, part, bike) {
  const target = quoteTarget(job);
  if (target.hidden) {
    els.send.hidden = true;
    els.send.removeAttribute("href");
    els.send.removeAttribute("target");
    els.send.removeAttribute("rel");
    els.send.removeAttribute("aria-label");
    return;
  }
  els.send.hidden = false;
  els.send.removeAttribute("aria-label");
  if (target.email) {
    els.send.setAttribute("href", quoteMailto(job, part, bike));
    els.send.removeAttribute("target");
    els.send.removeAttribute("rel");
  } else {
    els.send.setAttribute("href", target.href);
    els.send.setAttribute("target", "_blank");
    els.send.setAttribute("rel", "noopener");
  }
}

function paintNew(job) {
  const neu = listingNew(job);
  const oem = oemOf(job);
  const verified = oemVerifiedOf(job);
  if (neu == null) {
    els.fresh.classList.add("is-oem");
    els.freshOem.hidden = false;
    markOem(els.freshOem, oem, verified);
    els.listing.hidden = true;
    bindHref(els.listing, "", "");
    els.from.textContent = "";
    els.days.textContent = "";
    els.days.hidden = true;
    els.price.textContent = "";
    els.ext.hidden = true;
    els.ext.removeAttribute("href");
    els.prov.hidden = true;
    els.prov.textContent = "";
    return;
  }
  els.fresh.classList.remove("is-oem");
  els.freshOem.hidden = true;
  els.freshOem.textContent = "";
  els.freshOem.classList.remove("is-dash");
  els.listing.hidden = false;
  els.from.textContent = neu.from || "";
  const days = daysText(neu.days);
  els.days.textContent = days;
  els.days.hidden = !days;
  els.price.textContent = money(neu.price, !finite(neu.price));
  const url = hrefOf(neu);
  bindHref(els.listing, url, neu.from || oem);
  bindHref(els.ext, url, neu.from || oem);
  const prov = provText(neu.from, neu.retrieved);
  els.prov.textContent = prov;
  els.prov.hidden = !prov;
}

function paint() {
  if (!els) return;
  const job = jobOf();
  if (!job) return;
  const part = Q.part(job.partId) || {};
  const bike = Q.bike(job.bikeId) || Q.bike(state.bikeId) || {};
  const ch = state.channel;
  const src = Q.asset(part.thumb || part.image);

  els.photo.alt = part.name || "";
  if (src) {
    els.photo.src = src;
    els.photo.hidden = false;
  } else {
    els.photo.removeAttribute("src");
    els.photo.hidden = true;
  }

  els.name.textContent = part.name || "";
  markOem(els.oem, oemOf(job), oemVerifiedOf(job));
  els.stamp.textContent = [bike.model, bike.year].filter((x) => x != null && x !== "").join(" · ");

  for (const btn of els.chBtns) {
    const on = btn.dataset.ch === ch;
    btn.classList.toggle("btn-primary", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }

  els.fresh.hidden = ch !== "new";
  els.used.hidden = ch !== "used";
  els.alts.hidden = ch !== "other";

  paintQty();
  paintNew(job);

  const used = Array.isArray(job.used) ? job.used : [];
  const alts = Array.isArray(job.alts) ? job.alts : [];
  if (ch === "used") {
    fillList(els.used, used, pickUsed, (i, btn) => pickRow("used", i, btn));
  } else {
    clearList(els.used);
  }
  if (ch === "other") {
    fillList(els.alts, alts, pickAlt, (i, btn) => pickRow("other", i, btn));
  } else {
    clearList(els.alts);
  }

  paintTicket();
}

function wrapUrl(ctx, text, maxWidth) {
  if (!text) return [];
  const out = [];
  let cur = "";
  for (const ch of String(text)) {
    const next = cur + ch;
    if (cur && ctx.measureText(next).width > maxWidth) {
      out.push(cur);
      cur = ch;
    } else {
      cur = next;
    }
  }
  if (cur) out.push(cur);
  return out;
}

function contactLines(job) {
  const neu = newRecord(job);
  const lines = [];
  const merchant = strField(neu, "from");
  const email = strField(neu, "email").trim();
  const contactUrl = strField(neu, "contactUrl").trim();
  if (merchant) lines.push(merchant);
  if (email) lines.push(email);
  if (contactUrl) lines.push(contactUrl);
  return lines;
}

function drawTicket(ctx, w, h, job, part, bike, dash, t, img, line, qty) {
  ctx.fillStyle = "#ece7dc";
  ctx.fillRect(0, 0, w, h);
  const x = 24;
  const y = 24;
  const tw = w - 48;
  const th = h - 48;
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

  const px = x + 16;
  const py = y + 70;
  ctx.fillStyle = "#141414";
  ctx.strokeRect(px, py, 88, 88);
  if (img && img.naturalWidth) {
    const dw = 82;
    const dh = 82;
    const ir = img.naturalWidth / img.naturalHeight;
    const r = dw / dh;
    let sx = 0;
    let sy = 0;
    let sw = img.naturalWidth;
    let sh = img.naturalHeight;
    if (ir > r) {
      sw = img.naturalHeight * r;
      sx = (img.naturalWidth - sw) / 2;
    } else {
      sh = img.naturalWidth / r;
      sy = (img.naturalHeight - sh) / 2;
    }
    ctx.drawImage(img, sx, sy, sw, sh, px + 3, py + 3, dw, dh);
  }

  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.font = "800 22px Barlow, sans-serif";
  ctx.fillText([bike.make, bike.model, bike.year].filter(Boolean).join(" "), px + 104, py);
  ctx.font = "800 20px Barlow, sans-serif";
  ctx.fillText(part.name || "", px + 104, py + 28);
  ctx.font = "16px ui-monospace, monospace";
  ctx.fillText(oemOf(job), px + 104, py + 54);
  if (oemVerifiedOf(job) === false) {
    const oem = oemOf(job);
    const ow = Math.ceil(ctx.measureText(oem).width) + 10;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(px + 99, py + 50, ow, 22);
    ctx.setLineDash([]);
  }

  const rows = [
    ["Part", qtyUnitText(line, qty, dash), money(t.price, dash)],
    ["Ship", shipDetail(line), shipText(line, t, dash)],
    ["Tax 8.25%", "", money(t.tax, dash)],
    ["Total", "", money(t.total, dash)],
  ];
  let ry = py + 112;
  rows.forEach((row, i) => {
    if (i === 3) {
      ctx.fillStyle = "#ffe600";
      ctx.fillRect(x + 8, ry - 8, tw - 16, 40);
      ctx.fillStyle = "#141414";
    }
    ctx.font = i === 3 ? "800 18px ui-monospace, monospace" : "16px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText(row[0], px, ry);
    if (row[1]) ctx.fillText(row[1], px + 88, ry);
    ctx.textAlign = "right";
    ctx.fillText(row[2], x + tw - 16, ry);
    ry += 36;
  });

  ctx.textAlign = "left";
  ctx.font = "12px ui-monospace, monospace";
  ctx.fillStyle = "#141414";
  const extra = [];
  const prov = provText(line.from, line.retrieved);
  if (prov) extra.push(prov);
  if (line.url) extra.push(line.url);
  extra.push.apply(extra, contactLines(job));
  extra.forEach((u) => {
    wrapUrl(ctx, u, tw - 32).forEach((bit) => {
      ctx.fillText(bit, px, ry);
      ry += 16;
    });
  });
}

async function savePng() {
  const job = jobOf();
  if (!job) return;
  const part = Q.part(job.partId) || {};
  const bike = Q.bike(job.bikeId) || {};
  const line = lineOf(job);
  const qty = qtyOf();
  const t = line.dash ? { price: 0, ship: 0, tax: 0, total: 0 } : totals(line.price, line.ship, qty);
  if (document.fonts && document.fonts.ready) {
    try {
      await document.fonts.ready;
    } catch {
      /* keep going */
    }
  }
  if (els.photo.src && typeof els.photo.decode === "function") {
    try {
      await els.photo.decode();
    } catch {
      /* draw without photo */
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = 780;
  canvas.height = 760;
  drawTicket(canvas.getContext("2d"), canvas.width, canvas.height, job, part, bike, line.dash, t, els.photo, line, qty);
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

function mount(node) {
  root = node;
  root.replaceChildren();

  const head = h("div", { class: "sheet inv-head" });
  const frame = h("div", { class: "inv-photo" });
  const photo = h("img", { loading: "lazy", decoding: "async", alt: "" });
  frame.append(photo);
  const meta = h("div", { class: "inv-meta" });
  const name = h("div", { class: "inv-name" });
  const oem = h("div", { class: "inv-oem" });
  const qtyBox = h("div", { class: "inv-qty", role: "group" });
  const qtyDec = h("button", { type: "button", "aria-label": "Decrease", text: "−" });
  const qtyN = h("button", { type: "button", "aria-label": "Quantity", text: "1" });
  const qtyInc = h("button", { type: "button", "aria-label": "Increase", text: "+" });
  qtyDec.addEventListener("click", () => setQty(qtyOf() - 1));
  qtyInc.addEventListener("click", () => setQty(qtyOf() + 1));
  qtyBox.append(qtyDec, qtyN, qtyInc);
  meta.append(name, oem, qtyBox);
  const stamp = h("span", { class: "stamp" });
  head.append(frame, meta, stamp);

  const ch = h("div", { class: "inv-ch" });
  const chBtns = CHANNELS.map(([id, label]) => {
    const btn = h("button", { type: "button", class: "btn", text: label, "data-ch": id, "aria-pressed": "false" });
    btn.addEventListener("click", () => setChannel(id));
    ch.append(btn);
    return btn;
  });

  const fresh = h("div", { class: "card inv-new" });
  const freshOem = h("div", { class: "inv-oem", hidden: true });
  const listing = h("a", { class: "inv-listing" });
  const from = h("span");
  const days = h("span", { class: "inv-amt" });
  const price = h("span", { class: "inv-amt" });
  listing.append(from, days, price);
  const ext = h("a", { class: "btn btn-icon inv-ext", hidden: true });
  ext.append(extGlyph());
  const prov = h("div", { class: "inv-prov", hidden: true });
  fresh.append(freshOem, listing, ext, prov);

  const used = h("div", { class: "inv-list", "data-kind": "used" });
  const alts = h("div", { class: "inv-list", "data-kind": "alts" });

  const wrapTix = h("div", { class: "inv-tix-wrap" });
  const ticket = h("div", { class: "card inv-ticket" });
  const tixTop = h("div", { class: "inv-tix-top" });
  const tixBike = h("div", { class: "inv-tix-bike" });
  const tixNo = h("b", { class: "inv-tix-no" });
  tixTop.append(tixBike, tixNo);
  function row(label, detail, amtRef) {
    const r = h("div", { class: "inv-tix-row" });
    r.append(h("span", { class: "inv-tix-lab", text: label }), detail, amtRef);
    return r;
  }
  const tixPart = h("div", { class: "inv-tix-part" });
  const tixOem = h("div", { class: "inv-oem" });
  const tixQty = h("div", { class: "inv-tix-unit" });
  const partDetail = h("div", { class: "inv-tix-detail" });
  partDetail.append(tixPart, tixOem, tixQty);
  const amtPart = h("span", { class: "inv-amt" });
  const tixShip = h("div", { class: "inv-tix-detail" });
  const amtShip = h("span", { class: "inv-amt" });
  const amtTax = h("span", { class: "inv-amt" });
  const amtTotal = h("span", { class: "inv-amt" });
  const taxDetail = h("div", { class: "inv-tix-detail" });
  const totalDetail = h("div", { class: "inv-tix-detail" });
  const totalRow = row("Total", totalDetail, amtTotal);
  totalRow.classList.add("inv-due");
  ticket.append(
    tixTop,
    row("Part", partDetail, amtPart),
    row("Ship", tixShip, amtShip),
    row("Tax 8.25%", taxDetail, amtTax),
    totalRow
  );
  const tixSrc = h("div", { class: "inv-tix-src", hidden: true });
  wrapTix.append(ticket, tixSrc);

  const foot = h("div", { class: "inv-foot" });
  const send = h("a", { class: "btn btn-primary", text: "Quote", href: "mailto:", hidden: true });
  const save = h("button", { type: "button", class: "btn", text: "Save" });
  save.addEventListener("click", () => {
    savePng().catch(() => {});
  });
  foot.append(send, save);

  const wrap = h("div", { class: "inv" });
  wrap.append(head, ch, fresh, used, alts, wrapTix, foot);
  root.append(wrap);

  els = {
    photo,
    name,
    oem,
    stamp,
    qtyDec,
    qtyN,
    qtyInc,
    chBtns,
    fresh,
    freshOem,
    listing,
    from,
    days,
    price,
    ext,
    prov,
    used,
    alts,
    tixNo,
    tixBike,
    tixPart,
    tixOem,
    tixQty,
    tixShip,
    amtPart,
    amtShip,
    amtTax,
    amtTotal,
    tixSrc,
    send,
    save,
  };
}

function enter() {
  const job = jobOf();
  if (!job) {
    bounce();
    return;
  }
  if (seenJob !== job.id) {
    seenJob = job.id;
    pickUsed = -1;
    pickAlt = -1;
    set({ qty: QTY_MIN });
  } else if (!Number.isInteger(Number(state.qty)) || Number(state.qty) < QTY_MIN) {
    set({ qty: QTY_MIN });
  }
  if (!CHANNEL_IDS.includes(state.channel)) {
    set({ channel: "new" });
    emit("channel", { ch: "new" });
  }
  paint();
}

registerScreen("invoice", {
  mount,
  enter,
  leave() {},
});
