/**
 * The one renderer behind every Mechanica flow chart — the nine standalone .svg/.png beside the
 * pitches and the `diagram` slides inside the decks. Both call `laneSvg()` with the same flow, so
 * a chart cannot look like one thing in the deck and another in the repo.
 *
 * Geometry is explicit, never a layout engine's guess:
 *   · one row of boxes per lane, all boxes the same width, gaps equal by construction;
 *   · a horizontal arrow leaves the right edge of a box at its vertical midpoint and lands on the
 *     left edge of the next at the same y — perfectly straight, never a diagonal, never a corner;
 *   · a row-to-row connector is an orthogonal elbow: verticals down out of the source boxes'
 *     bottom midpoints, one horizontal bus, verticals into the target boxes' top midpoints;
 *   · every arrow carries one verb, sitting *above* its line on an opaque paper pill, inside the
 *     gap it belongs to, so it can never cross a line or touch a box.
 *
 * flow = { w?, bands: [ { rows: [ {
 *   items: [{ tone, t, sub? }],      // one noun per box
 *   labels?: [verb…],                // one per horizontal arrow (items.length - 1)
 *   link?: "none",                   // the row is a set of alternatives, no arrows between them
 *   down?: true, downLabel?: verb,   // the connector coming from the row above
 *   into?: index,                    // which box in this row that connector lands on (default 0)
 *   from?: index,                    // which box it left the row above by (default: the last)
 * } ] } ] }
 *
 * `opts.measure(text, size, weight)` returns a real pixel width; without one a character estimate
 * is used, which is what the deck build does (it has no browser).
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const TONES = {
  paper: { fill: "#ece7dc", stroke: "#141414", text: "#141414", sub: "#4a453d" },
  white: { fill: "#ffffff", stroke: "#141414", text: "#141414", sub: "#4a453d" },
  orange: { fill: "#e85d04", stroke: "#8f3a02", text: "#ffffff", sub: "#ffe0cb" },
  ink: { fill: "#141414", stroke: "#e85d04", text: "#ece7dc", sub: "#b5ad9e" },
};

export const GROUND = "#ece7dc";  // the pill behind an edge verb, and the page the chart sits on
const LINE = "#141414";
const EDGE_INK = "#3b362e";

const TITLE = 30, TITLE_LH = 37, SUB = 17.5, SUB_LH = 23;
const EDGE = 19;                 // the verb on an arrow
const PILL_X = 9, PILL_Y = 5;    // padding inside the pill
const PILL_LIFT = 17;            // how far the pill's centre sits above its line
const BOX_PAD_X = 30, BOX_PAD_Y = 20, BOX_MIN_H = 84;
const GAP_MIN = 70, ROW_GAP = 104, PAD = 28;
const STROKE = 3, HEAD = 11;

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/**
 * Real Barlow widths, measured in Chrome by mermaid.mjs and written to metrics.json, so the deck
 * build — which has no browser — lays a chart out to the same pixel as the standalone render.
 * Anything not in the table falls back to the sum of its words, then to a character estimate.
 */
export function makeMeasure(table) {
  const guess = (t, size, weight) => String(t).length * size * (weight >= 600 ? 0.545 : 0.515);
  return (t, size, weight) => {
    const key = JSON.stringify([String(t), size, weight]);
    if (table && table.has(key)) return table.get(key);
    const words = String(t).split(" ");
    if (words.length > 1) {
      return words.reduce((a, w) => {
        const k = JSON.stringify([w, size, weight]);
        return a + (table && table.has(k) ? table.get(k) : guess(w, size, weight));
      }, 0) + size * 0.26 * (words.length - 1);
    }
    return guess(t, size, weight);
  };
}

export const METRICS = join(dirname(fileURLToPath(import.meta.url)), "metrics.json");

let loaded = null;
function defaultMeasure() {
  if (!loaded) {
    let table = null;
    try { table = new Map(Object.entries(JSON.parse(readFileSync(METRICS, "utf8")))); } catch { table = null; }
    loaded = makeMeasure(table);
  }
  return loaded;
}

/* ------------------------------------------------------------------ boxes */

function wrapTo(text, width, size, weight, measure) {
  const lines = [];
  for (const chunk of String(text).split("|")) {
    let line = "";
    for (const word of chunk.trim().split(/\s+/)) {
      if (!line) { line = word; continue; }
      if (measure(line + " " + word, size, weight) <= width) line += " " + word;
      else { lines.push(line); line = word; }
    }
    if (line) lines.push(line);
  }
  return lines;
}

/** Narrow columns take smaller type rather than a five-line box. */
function itemLayout(item, width, measure) {
  const k = width < 175 ? 0.80 : width < 215 ? 0.87 : width < 265 ? 0.94 : 1;
  const ts = TITLE * k, ss = SUB * k, tlh = TITLE_LH * k, slh = SUB_LH * k;
  const inner = width - BOX_PAD_X * 2;
  const t = wrapTo(item.t || "", inner, ts, 700, measure);
  const s = item.sub ? wrapTo(item.sub, inner, ss, 400, measure) : [];
  const h = BOX_PAD_Y * 2 + t.length * tlh + (s.length ? 8 + s.length * slh : 0);
  return { t, s, ts, ss, tlh, slh, h: Math.max(BOX_MIN_H, h) };
}

function drawBox(item, x, y, w, h, lay) {
  const tone = TONES[item.tone] || TONES.paper;
  const cx = x + w / 2;
  const block = lay.t.length * lay.tlh + (lay.s.length ? 8 + lay.s.length * lay.slh : 0);
  let ty = y + (h - block) / 2 + lay.ts * 0.78;
  const body = lay.t.map((l) => {
    const line = `<text x="${cx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="middle" font-size="${lay.ts.toFixed(1)}" font-weight="700" fill="${tone.text}">${esc(l)}</text>`;
    ty += lay.tlh;
    return line;
  });
  if (lay.s.length) {
    ty = y + (h - block) / 2 + lay.t.length * lay.tlh + 8 + lay.ss * 0.78;
    for (const l of lay.s) {
      body.push(`<text x="${cx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="middle" font-size="${lay.ss.toFixed(1)}" fill="${tone.sub}">${esc(l)}</text>`);
      ty += lay.slh;
    }
  }
  return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="14"`
    + ` fill="${tone.fill}" stroke="${tone.stroke}" stroke-width="${STROKE}"/>` + body.join("");
}

/* ------------------------------------------------------------------ lines */

const hLine = (x1, x2, y) =>
  `<path d="M${x1.toFixed(1)} ${y.toFixed(1)} H${(x2 - HEAD + 1).toFixed(1)}" stroke="${LINE}" stroke-width="2.5" fill="none"/>`
  + `<path d="M${x2.toFixed(1)} ${y.toFixed(1)} l-${HEAD} -6.5 v13 z" fill="${LINE}"/>`;

const vLine = (x, y1, y2, head) =>
  `<path d="M${x.toFixed(1)} ${y1.toFixed(1)} V${(head ? y2 - HEAD + 1 : y2).toFixed(1)}" stroke="${LINE}" stroke-width="2.5" fill="none"/>`
  + (head ? `<path d="M${x.toFixed(1)} ${y2.toFixed(1)} l-6.5 -${HEAD} h13 z" fill="${LINE}"/>` : "");

const plain = (x1, y1, x2, y2) =>
  `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${LINE}" stroke-width="2.5" fill="none"/>`;

/** A verb on an opaque pill, centred at (cx, cy). Returns the markup and the box it occupies. */
function pill(text, cx, cy, measure) {
  const w = measure(text, EDGE, 600) + PILL_X * 2;
  const h = EDGE + PILL_Y * 2;
  const x = cx - w / 2, y = cy - h / 2;
  return {
    box: { x, y, w, h },
    svg: `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${(h / 2).toFixed(1)}" fill="${GROUND}"/>`
      + `<text x="${cx.toFixed(1)}" y="${(cy + EDGE * 0.35).toFixed(1)}" text-anchor="middle" font-size="${EDGE}" font-weight="600" fill="${EDGE_INK}">${esc(text)}</text>`,
  };
}

/* ------------------------------------------------------------------ chart */

export function laneSvg(flow, opts = {}) {
  const measure = opts.measure || defaultMeasure();
  const W = flow.w || 1440;
  const rows = (flow.bands || [{ rows: flow.rows }]).flatMap((b) => b.rows || []);
  const inner = W - PAD * 2;

  const cols = Math.max(...rows.map((r) => (r.items || []).length), 1);
  const verbW = (v) => measure(v, EDGE, 600) + PILL_X * 2 + 16;
  const gap = Math.max(GAP_MIN, ...rows.flatMap((r) => (r.labels || []).map(verbW)));
  const iw = (inner - gap * (cols - 1)) / cols;

  // 1. place every box
  let y = PAD;
  const placed = rows.map((row) => {
    const items = row.items || [];
    const lays = items.map((it) => itemLayout(it, iw, measure));
    const rh = Math.max(...lays.map((l) => l.h));
    const x0 = PAD + (inner - (items.length * iw + gap * (items.length - 1))) / 2;
    const boxes = items.map((it, i) => ({ it, lay: lays[i], x: x0 + i * (iw + gap), y, w: iw, h: rh }));
    const out = { row, boxes, top: y, bottom: y + rh };
    y += rh + ROW_GAP;
    return out;
  });
  const height = placed[placed.length - 1].bottom + PAD;

  // 2. draw: lines first, then pills, then boxes — a box is never crossed by a line it does not own
  const lines = [], pills = [], boxes = [];
  const labelBoxes = [], segments = [];
  const seg = (x1, y1, x2, y2) => segments.push({ x1, y1, x2, y2 });

  for (const { row, boxes: bs } of placed) {
    for (const b of bs) boxes.push(drawBox(b.it, b.x, b.y, b.w, b.h, b.lay));
    if (row.link === "none") continue;
    for (let i = 0; i < bs.length - 1; i++) {
      const a = bs[i], z = bs[i + 1];
      const cy = a.y + a.h / 2;                       // the vertical midpoint of both node edges
      lines.push(hLine(a.x + a.w, z.x, cy)); seg(a.x + a.w, cy, z.x, cy);
      const verb = (row.labels || [])[i];
      if (verb) {
        const p = pill(verb, (a.x + a.w + z.x) / 2, cy - PILL_LIFT, measure);
        pills.push(p.svg); labelBoxes.push(p.box);
      }
    }
  }

  // 3. row-to-row connectors, orthogonal, into and out of edge midpoints
  for (let r = 1; r < placed.length; r++) {
    const prev = placed[r - 1], cur = placed[r];
    if (!cur.row.down) continue;
    const src = prev.row.link === "none" ? prev.boxes
      : [prev.boxes[prev.row.from ?? prev.boxes.length - 1]];
    const dst = cur.row.link === "none" ? cur.boxes
      : [cur.boxes[cur.row.into ?? 0]];
    const busY = (prev.bottom + cur.top) / 2;
    const sxs = src.map((b) => b.x + b.w / 2);
    const txs = dst.map((b) => b.x + b.w / 2);

    if (sxs.length === 1 && txs.length === 1 && Math.abs(sxs[0] - txs[0]) < 0.5) {
      lines.push(vLine(txs[0], prev.bottom, cur.top, true)); seg(txs[0], prev.bottom, txs[0], cur.top);
    } else {
      for (const sx of sxs) { lines.push(vLine(sx, prev.bottom, busY, false)); seg(sx, prev.bottom, sx, busY); }
      const lo = Math.min(...sxs, ...txs), hi = Math.max(...sxs, ...txs);
      if (hi - lo > 0.5) { lines.push(plain(lo, busY, hi, busY)); seg(lo, busY, hi, busY); }
      for (const tx of txs) { lines.push(vLine(tx, busY, cur.top, true)); seg(tx, busY, tx, cur.top); }
    }
    if (cur.row.downLabel) {
      // Above the bus, in the widest stretch no vertical crosses — so the verb never sits on a
      // line even when a connector fans out of three boxes into two.
      const need = measure(cur.row.downLabel, EDGE, 600) + PILL_X * 2 + 10;
      const lo = Math.min(...sxs, ...txs), hi = Math.max(...sxs, ...txs);
      const best = (xs) => {
        const cuts = [lo, ...xs.filter((x) => x > lo && x < hi).sort((p, q) => p - q), hi];
        let win = null;
        for (let i = 0; i < cuts.length - 1; i++) {
          const w = cuts[i + 1] - cuts[i];
          if (!win || w > win.w) win = { w, c: (cuts[i] + cuts[i + 1]) / 2 };
        }
        return win;
      };
      const up = best(sxs), downSide = best(txs);
      let cx = (lo + hi) / 2, cy = busY - PILL_LIFT;
      if (up && up.w >= need) cx = up.c;
      else if (downSide && downSide.w >= need) { cx = downSide.c; cy = busY + PILL_LIFT; }
      else if (sxs.length === 1 && txs.length === 1 && Math.abs(sxs[0] - txs[0]) < 0.5) {
        cx = sxs[0] + need / 2 + 14; cy = (prev.bottom + cur.top) / 2;
      }
      const p = pill(cur.row.downLabel, cx, cy, measure);
      pills.push(p.svg); labelBoxes.push(p.box);
    }
  }

  const svg = `<svg viewBox="0 0 ${W} ${Math.ceil(height)}" width="${W}" height="${Math.ceil(height)}"`
    + ` preserveAspectRatio="xMidYMid meet" font-family="Barlow,&quot;Segoe UI&quot;,system-ui,sans-serif"`
    + ` xmlns="http://www.w3.org/2000/svg" role="img">`
    + `<rect width="${W}" height="${Math.ceil(height)}" fill="${GROUND}"/>`
    + lines.join("") + pills.join("") + boxes.join("") + `</svg>`;

  return { svg, width: W, height: Math.ceil(height), placed, labelBoxes, segments, gap, iw };
}

/** What the deck wants: the markup, scaled to its stage. */
export function laneMarkup(flow, opts) {
  const { svg } = laneSvg(flow, opts);
  return svg.replace(/^<svg([^>]*)>/, (m, a) =>
    `<svg${a.replace(/\swidth="[^"]*"/, "").replace(/\sheight="[^"]*"/, "")} width="100%" height="100%">`)
    .replace(/<rect width="\d+" height="\d+" fill="#ece7dc"\/>/, "");
}
