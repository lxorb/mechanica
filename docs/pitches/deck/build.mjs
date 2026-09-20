#!/usr/bin/env node
/**
 * Mechanica pitch decks — one self-contained HTML file per pitch, plus an index.
 *
 *   node docs/pitches/deck/build.mjs            # build all nine + index.html
 *   node docs/pitches/deck/build.mjs openai     # build one
 *
 * Input   docs/pitches/deck/slides/<pitch>.json   (authored; see the schema below)
 * Output  docs/pitches/deck/<pitch>.html          (inline CSS, inline SVG, data: images)
 *         docs/pitches/deck/index.html            (the nine, in rehearsal order)
 *
 * No dependencies. `sharp` is used to downscale screenshots when it happens to be present in
 * the scratchpad node_modules; without it the PNGs are embedded as they are.
 *
 * ---------------------------------------------------------------------------------------
 * Slide JSON
 * ---------------------------------------------------------------------------------------
 * {
 *   "pitch": "openai", "order": 3, "title": "…", "target": "…", "length": "5:00",
 *   "angle": "one line for the index page",
 *   "marks": [ { "t": "1:00", "do": "what you should be doing at 1:00" } ],
 *   "slides": [ { "kind": …, "at": "0:30", "notes": ["…"], "defs": [ {"n":"27,751","d":"…"} ], … } ]
 * }
 *
 * kind           fields
 * title          title, line, meta?, mark? (show the piston mark)
 * statement      kicker?, text, sub?
 * number         label, value, unit?, sub?, tone? ("orange" | "ink")
 * numbers        kicker?, items: [{ value, label, sub? }]   (2–4)
 * image          title?, line?, image, caption?, points? (≤3 short lines)
 * two-up         title?, left: panel, right: panel          (panel = {image|value, label, caption?})
 * diagram        title?, caption?, flow: {…}  |  svgFile: "dropbox/rows-per-portal.svg"
 * demo           title, line?, rows: [{ do, see }]
 * qa             title, groups: [{ label, items: [ "…" ] }]   — set "presenterOnly": true
 *
 * Inline markup in any string: *bold*  ~orange~
 * Every number on a slide is listed in `defs` with the definition from numbers.md; the build
 * fails if the figure is not found in numbers.md, and the definitions are shown in presenter view.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PITCHES = resolve(HERE, "..");
const REPO = resolve(PITCHES, "../..");
const SLIDES = join(HERE, "slides");
const FONTS = join(HERE, "fonts");

const SHARP_DIR = process.env.SHARP_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/sharp/dist/index.cjs";

let sharp = null;
try {
  if (existsSync(SHARP_DIR)) sharp = (await import(pathToFileURL(SHARP_DIR).href)).default;
} catch { sharp = null; }

const NUMBERS_RAW = readFileSync(join(PITCHES, "numbers.md"), "utf8");
const problems = [];

/* ------------------------------------------------------------------ text */

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** *bold*  ~orange~ */
function rich(s) {
  return esc(s)
    .replace(/\*([^*]+)\*/g, "<b>$1</b>")
    .replace(/~([^~]+)~/g, '<em class="hl">$1</em>');
}

/* ---------------------------------------------------------------- assets */

const assetCache = new Map();
let assetBytes = 0;

async function dataUri(rel) {
  if (assetCache.has(rel)) return assetCache.get(rel);
  const file = resolve(PITCHES, rel);
  if (!existsSync(file)) { problems.push(`missing image ${rel}`); return ""; }
  let buf = readFileSync(file);
  let mime = rel.endsWith(".png") ? "image/png" : rel.endsWith(".webp") ? "image/webp" : "image/jpeg";
  if (sharp) {
    try {
      const meta = await sharp(file).metadata();
      let pipe = sharp(file);
      if (meta.width > 1600) pipe = pipe.resize({ width: 1600 });
      buf = await pipe.webp({ quality: 82, effort: 5 }).toBuffer();
      mime = "image/webp";
    } catch (e) { problems.push(`sharp failed on ${rel}: ${e.message}`); }
  }
  assetBytes += buf.length;
  const uri = `data:${mime};base64,${buf.toString("base64")}`;
  assetCache.set(rel, uri);
  return uri;
}

function fontFaces() {
  if (!existsSync(FONTS)) return "";
  const files = readdirSync(FONTS).filter((f) => f.endsWith(".woff2"));
  const out = [];
  const seen = new Set();
  for (const f of files) {
    const m = /^(.+?)-(\d+)\.woff2$/.exec(f);
    if (!m) continue;
    const family = m[1] === "BigShouldersDisplay" ? "Big Shoulders Display" : m[1];
    const b64 = readFileSync(join(FONTS, f)).toString("base64");
    // The Big Shoulders subsets are one variable file; register it once over 700–800.
    const key = family + ":" + b64.slice(0, 40);
    if (seen.has(key)) continue;
    seen.add(key);
    const weight = family === "Big Shoulders Display" ? "700 800" : m[2];
    out.push(`@font-face{font-family:'${family}';font-style:normal;font-weight:${weight};font-display:swap;`
      + `src:url(data:font/woff2;base64,${b64}) format('woff2')}`);
  }
  return out.join("\n");
}

/* --------------------------------------------------------------- diagram */

const TONES = {
  paper: { fill: "#ece7dc", stroke: "#b3a996", text: "#141414", sub: "#4a453d" },
  white: { fill: "#ffffff", stroke: "#b3a996", text: "#141414", sub: "#4a453d" },
  grey: { fill: "#ffffff", stroke: "#b3a996", text: "#141414", sub: "#4a453d" },
  orange: { fill: "#e85d04", stroke: "#8f3a02", text: "#ffffff", sub: "#ffe0cb" },
  green: { fill: "#d8f1e3", stroke: "#1b7a55", text: "#0d3b2a", sub: "#215f47" },
  ink: { fill: "#141414", stroke: "#e85d04", text: "#ece7dc", sub: "#b5ad9e" },
  yellow: { fill: "#ffe600", stroke: "#a89400", text: "#141414", sub: "#4a453d" },
  ghost: { fill: "none", stroke: "#b3a996", text: "#4a453d", sub: "#6b6357" },
};

const TITLE_SIZE = 23, TITLE_LH = 29, SUB_SIZE = 17.5, SUB_LH = 23;

function wrap(text, width, size, ratio) {
  const max = Math.max(6, Math.floor((width - 30) / (size * ratio)));
  const lines = [];
  for (const chunk of String(text).split("|")) {
    let line = "";
    for (const word of chunk.trim().split(/\s+/)) {
      if (!line) { line = word; continue; }
      if ((line + " " + word).length <= max) line += " " + word;
      else { lines.push(line); line = word; }
    }
    if (line) lines.push(line);
  }
  return lines;
}

function itemLayout(item, width) {
  const t = wrap(item.t || "", width, TITLE_SIZE, 0.53);
  const s = item.sub ? wrap(item.sub, width, SUB_SIZE, 0.50) : [];
  const h = 17 + t.length * TITLE_LH + (s.length ? 8 + s.length * SUB_LH : 0) + 17;
  return { t, s, h: Math.max(64, h) };
}

function drawItem(item, x, y, w, h, lay) {
  const tone = TONES[item.tone || "white"] || TONES.white;
  const cx = x + w / 2;
  let ty = y + 17 + TITLE_SIZE * 0.82;
  const body = lay.t.map((l) => {
    const line = `<text x="${cx}" y="${ty.toFixed(1)}" text-anchor="middle" font-size="${TITLE_SIZE}" font-weight="700" fill="${tone.text}">${esc(l)}</text>`;
    ty += TITLE_LH;
    return line;
  });
  if (lay.s.length) {
    ty += 8 - TITLE_LH + SUB_LH * 0.05;
    ty = y + 17 + lay.t.length * TITLE_LH + 8 + SUB_SIZE * 0.82;
    for (const l of lay.s) {
      body.push(`<text x="${cx}" y="${ty.toFixed(1)}" text-anchor="middle" font-size="${SUB_SIZE}" fill="${tone.sub}">${esc(l)}</text>`);
      ty += SUB_LH;
    }
  }
  const dash = item.tone === "ghost" ? ' stroke-dasharray="7 6"' : "";
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="11" fill="${tone.fill}" stroke="${tone.stroke}" stroke-width="2"${dash}/>` + body.join("");
}

function arrow(x, y, len) {
  const x2 = x + len;
  return `<path d="M${x} ${y} H${x2 - 9}" stroke="#141414" stroke-width="2.5" opacity=".55"/>`
    + `<path d="M${x2} ${y} l-11 -6 v12 z" fill="#141414" opacity=".55"/>`;
}

function down(x, y, h) {
  return `<path d="M${x} ${y} V${y + h - 12}" stroke="#141414" stroke-width="2.5" opacity=".55"/>`
    + `<path d="M${x} ${y + h} l-7 -13 h14 z" fill="#141414" opacity=".55"/>`;
}

function flowSvg(flow) {
  const W = flow.w || 1440;
  const bands = flow.bands || [{ rows: flow.rows }];
  const parts = [];
  let y = 0;

  if (flow.legend && flow.legend.length) {
    const gap = 26;
    let lx = 0;
    const chips = [];
    for (const l of flow.legend) {
      const tone = TONES[l.tone] || TONES.white;
      const w = 20 + String(l.label).length * 9.2;
      chips.push({ tone, label: l.label, w });
      lx += w + gap;
    }
    let x = Math.max(0, (W - (lx - gap)) / 2);
    for (const c of chips) {
      parts.push(`<rect x="${x}" y="${y}" width="16" height="16" rx="4" fill="${c.tone.fill}" stroke="${c.tone.stroke}" stroke-width="2"/>`
        + `<text x="${x + 24}" y="${y + 13.5}" font-size="17" font-weight="600" fill="#141414">${esc(c.label)}</text>`);
      x += c.w + 26;
    }
    y += 34;
  }

  bands.forEach((band, bi) => {
    const hasLabel = !!band.label;
    const padX = band.label || band.tone ? 18 : 0;
    const top = y;
    let iy = y + (hasLabel ? 40 : 0) + (band.label || band.tone ? 14 : 0);

    (band.rows || []).forEach((row, ri) => {
      const items = row.items || [];
      const n = items.length;
      const gap = row.gap ?? 42;
      const inner = W - padX * 2 - 24;
      const iw = (inner - gap * (n - 1)) / n;
      const lays = items.map((it) => itemLayout(it, iw));
      const rh = Math.max(...lays.map((l) => l.h));
      let x = padX + 12;
      items.forEach((it, i) => {
        parts.push(drawItem(it, x, iy, iw, rh, lays[i]));
        if (i < n - 1 && row.link !== "none") parts.push(arrow(x + iw + 8, iy + rh / 2, gap - 16));
        x += iw + gap;
      });
      if (row.caption) {
        parts.push(`<text x="${W / 2}" y="${iy + rh + 22}" text-anchor="middle" font-size="17" font-style="italic" fill="#4a453d">${esc(row.caption)}</text>`);
        iy += 26;
      }
      var nextRow = band.rows[ri + 1];
      if (nextRow && nextRow.down) { parts.push(down(W / 2, iy + rh + 6, 30)); iy += 30; }
      iy += rh + (ri < band.rows.length - 1 ? 16 : 0);
    });

    const bh = iy - top + (band.label || band.tone ? 16 : 0);
    if (band.label || band.tone) {
      const tone = TONES[band.tone || "ghost"] || TONES.ghost;
      parts.unshift(`<rect x="0" y="${top}" width="${W}" height="${bh}" rx="14" fill="none" stroke="${tone.stroke}" stroke-width="2" stroke-dasharray="8 7" opacity=".85"/>`);
      if (hasLabel) {
        parts.unshift(`<text x="20" y="${top + 28}" font-family="Big Shoulders Display, Barlow, sans-serif" font-size="27" font-weight="800" letter-spacing="1.4" fill="${band.labelColor || "#141414"}">${esc(band.label.toUpperCase())}</text>`);
      }
    }
    y = top + bh;
    if (bi < bands.length - 1) {
      const midY = y + 16;
      parts.push(`<path d="M${W / 2} ${y + 4} V${midY + 12}" stroke="#141414" stroke-width="2.5" opacity=".55"/>`
        + `<path d="M${W / 2} ${midY + 24} l-7 -12 h14 z" fill="#141414" opacity=".55"/>`);
      y = midY + 30;
    }
  });

  return `<svg viewBox="0 0 ${W} ${Math.ceil(y)}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" font-family="Barlow, system-ui, sans-serif" role="img">${parts.join("")}</svg>`;
}

function inlineSvgFile(rel) {
  const file = resolve(PITCHES, rel);
  if (!existsSync(file)) { problems.push(`missing svg ${rel}`); return ""; }
  let svg = readFileSync(file, "utf8").trim();
  const uid = "d" + Math.abs([...rel].reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)).toString(36);
  svg = svg.replace(/my-svg/g, uid);                                   // mermaid's fixed id
  svg = svg.replace(/(\sid=")([^"]+)"/g, `$1${uid}-$2"`).replace(/url\(#([^)]+)\)/g, `url(#${uid}-$1)`);
  svg = svg.replace(/<svg([^>]*)>/, (m, attrs) => {
    let a = attrs.replace(/\swidth="[^"]*"/, "").replace(/\sheight="[^"]*"/, "").replace(/\sstyle="[^"]*"/, "");
    return `<svg${a} width="100%" height="100%" preserveAspectRatio="xMidYMid meet">`;
  });
  return svg;
}

/* ---------------------------------------------------------------- slides */

/** Markdown emphasis and code ticks are not part of a figure: **100%** of 48 == 100% of 48. */
const norm = (s) => String(s).replace(/[*`_]/g, "").replace(/ /g, " ").replace(/[ \t]+/g, " ");

const NUMBERS = norm(NUMBERS_RAW);

const srcCache = new Map();
function srcText(rel) {
  if (!srcCache.has(rel)) {
    const file = resolve(PITCHES, rel);
    srcCache.set(rel, existsSync(file) ? norm(readFileSync(file, "utf8")) : null);
  }
  return srcCache.get(rel);
}

/**
 * Every figure on a slide carries its definition. Without `src` it must be in numbers.md,
 * which is the source of truth; `src` is the escape hatch for the per-pitch working files
 * numbers.md itself points at (ramp/numbers.md, token-company/cost-report.md, …), and the
 * figure still has to be findable there.
 */
function defsBlock(slide) {
  if (!slide.defs || !slide.defs.length) return "";
  const rows = slide.defs.map((d) => {
    const where = d.src || "numbers.md";
    const text = d.src ? srcText(d.src) : NUMBERS;
    const fig = norm(d.n);
    if (text == null) problems.push(`source file ${where} not found (figure "${d.n}")`);
    else if (!text.includes(fig)) problems.push(`figure "${d.n}" is not in ${where}`);
    return `<li><b>${esc(d.n)}</b> — ${esc(d.d)}<i>${esc(where)}</i></li>`;
  });
  return `<div class="pv-defs"><h4>the figures on this slide</h4><ul>${rows.join("")}</ul></div>`;
}

function notesHtml(slide) {
  const notes = (slide.notes || []).map((n) => `<p>${rich(n)}</p>`).join("");
  return `<div class="pv-note">${notes || "<p class=\"muted\">no notes</p>"}</div>` + defsBlock(slide);
}

async function panelHtml(p) {
  if (p.image) {
    const uri = await dataUri(p.image);
    return `<figure class="panel"><img src="${uri}" alt=""/>`
      + (p.label ? `<figcaption><b>${rich(p.label)}</b>${p.caption ? `<span>${rich(p.caption)}</span>` : ""}</figcaption>` : "")
      + `</figure>`;
  }
  return `<div class="panel panel-text"><div class="panel-value">${rich(p.value || "")}</div>`
    + (p.label ? `<div class="panel-label">${rich(p.label)}</div>` : "")
    + (p.caption ? `<div class="panel-caption">${rich(p.caption)}</div>` : "") + `</div>`;
}

async function body(slide) {
  switch (slide.kind) {
    case "title":
      return `<div class="s-title">`
        + (slide.mark === false ? "" : `<img class="mark" src="${await dataUri("deck/assets/mark.png")}" alt=""/>`)
        + `<h1>${rich(slide.title)}</h1>`
        + (slide.line ? `<p class="lede">${rich(slide.line)}</p>` : "")
        + (slide.meta ? `<p class="meta">${rich(slide.meta)}</p>` : "")
        + `</div>`;

    case "statement":
      return `<div class="s-statement">`
        + (slide.kicker ? `<p class="kicker">${rich(slide.kicker)}</p>` : "")
        + `<h2>${rich(slide.text)}</h2>`
        + (slide.sub ? `<p class="sub">${rich(slide.sub)}</p>` : "") + `</div>`;

    case "number":
      return `<div class="s-number ${slide.tone === "ink" ? "tone-ink" : ""}">`
        + (slide.label ? `<p class="kicker">${rich(slide.label)}</p>` : "")
        + `<div class="huge">${rich(slide.value)}${slide.unit ? `<span class="unit">${rich(slide.unit)}</span>` : ""}</div>`
        + (slide.sub ? `<p class="sub">${rich(slide.sub)}</p>` : "") + `</div>`;

    case "numbers": {
      const n = slide.items.length;
      const cells = slide.items.map((it) => `<div class="cell">`
        + `<div class="big">${rich(it.value)}</div>`
        + `<div class="cell-label">${rich(it.label)}</div>`
        + (it.sub ? `<div class="cell-sub">${rich(it.sub)}</div>` : "") + `</div>`).join("");
      return `<div class="s-numbers">`
        + (slide.kicker ? `<p class="kicker">${rich(slide.kicker)}</p>` : "")
        + `<div class="grid g${n}">${cells}</div>`
        + (slide.sub ? `<p class="sub">${rich(slide.sub)}</p>` : "") + `</div>`;
    }

    case "image": {
      const uri = await dataUri(slide.image);
      const pts = (slide.points || []).map((p) => `<li>${rich(p)}</li>`).join("");
      return `<div class="s-image${slide.wide ? " wide" : ""}">`
        + `<div class="col">`
        + (slide.title ? `<h3>${rich(slide.title)}</h3>` : "")
        + (slide.line ? `<p class="line">${rich(slide.line)}</p>` : "")
        + (pts ? `<ul class="points">${pts}</ul>` : "")
        + (slide.caption ? `<p class="src">${rich(slide.caption)}</p>` : "")
        + `</div><figure class="shot"><img src="${uri}" alt=""/></figure></div>`;
    }

    case "two-up":
      return `<div class="s-twoup">`
        + (slide.title ? `<h3>${rich(slide.title)}</h3>` : "")
        + `<div class="pair">${await panelHtml(slide.left)}${await panelHtml(slide.right)}</div>`
        + (slide.caption ? `<p class="src">${rich(slide.caption)}</p>` : "") + `</div>`;

    case "diagram": {
      const svg = slide.svgFile ? inlineSvgFile(slide.svgFile) : flowSvg(slide.flow);
      return `<div class="s-diagram">`
        + (slide.title ? `<h3>${rich(slide.title)}</h3>` : "")
        + `<div class="fig${slide.svgFile ? " card" : ""}">${svg}</div>`
        + (slide.caption ? `<p class="src">${rich(slide.caption)}</p>` : "") + `</div>`;
    }

    case "quote":
      return `<div class="s-quote"><blockquote>${rich(slide.text)}</blockquote>`
        + (slide.cite ? `<p class="cite">${rich(slide.cite)}</p>` : "") + `</div>`;

    case "table": {
      const al = slide.align || [];
      const cell = (v, j, tag) => `<${tag}${al[j] === "r" ? ' class="r"' : ""}>${rich(v)}</${tag}>`;
      const head = slide.head ? `<thead><tr>${slide.head.map((h, j) => cell(h, j, "th")).join("")}</tr></thead>` : "";
      const rows = slide.rows.map((r) => {
        const emph = Array.isArray(r) ? false : r.emph;
        const cells = (Array.isArray(r) ? r : r.cells).map((c, j) => cell(c, j, "td")).join("");
        return `<tr${emph ? ' class="emph"' : ""}>${cells}</tr>`;
      }).join("");
      return `<div class="s-table${slide.dense ? " dense" : ""}">`
        + (slide.title ? `<h3>${rich(slide.title)}</h3>` : "")
        + (slide.line ? `<p class="line">${rich(slide.line)}</p>` : "")
        + `<table>${head}<tbody>${rows}</tbody></table>`
        + (slide.note ? `<p class="src">${rich(slide.note)}</p>` : "") + `</div>`;
    }

    case "demo": {
      const rows = slide.rows.map((r) => `<tr><td class="do">${rich(r.do)}</td><td class="see">${rich(r.see)}</td></tr>`).join("");
      return `<div class="s-demo"><div class="live">LIVE</div>`
        + `<h3>${rich(slide.title)}</h3>`
        + (slide.line ? `<p class="line">${rich(slide.line)}</p>` : "")
        + `<table>${rows}</table></div>`;
    }

    case "qa": {
      const groups = (slide.groups || []).map((g) =>
        `<div class="group"><h4>${rich(g.label)}</h4><ul>${g.items.map((i) => `<li>${rich(i)}</li>`).join("")}</ul></div>`).join("");
      return `<div class="s-qa"><div class="stamp">DO NOT SAY</div><h3>${rich(slide.title)}</h3><div class="groups">${groups}</div></div>`;
    }

    default:
      problems.push(`unknown kind ${slide.kind}`);
      return `<div class="s-statement"><h2>${esc(slide.kind)}?</h2></div>`;
  }
}

async function slideHtml(slide, i, deck, total) {
  const chrome = slide.kind === "title" ? "" :
    `<div class="chrome"><span class="left">${esc(deck.title)} · ${esc(deck.target)}</span>`
    + `<span class="right">${slide.at ? esc(slide.at) + " · " : ""}${i + 1}/${total}</span></div>`;
  const cls = ["slide", "k-" + slide.kind, slide.presenterOnly ? "presenter-only" : ""].filter(Boolean).join(" ");
  const hidden = slide.presenterOnly
    ? `<div class="s-endcard"><img class="mark" src="${await dataUri("deck/assets/mark.png")}" alt=""/>`
      + `<p>${rich(deck.endline || "Don't trust the AI. Trust the manual.")}</p>`
      + `<p class="url">mechanica.emilvinu.ch</p></div>`
    : "";
  const content = slide.presenterOnly ? hidden : await body(slide);
  return `<section class="${cls}" data-i="${i}">${chrome}<div class="hold">${content}</div>`
    + `<div class="bar"><i style="width:${((i + 1) / total * 100).toFixed(2)}%"></i></div>`
    + (slide.presenterOnly ? `<div class="print-only">${await body(slide)}</div>` : "")
    + `</section>`;
}

/* ------------------------------------------------------------------- CSS */

const CSS = `
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--orange:#e85d04;--yellow:#ffe600;--ink:#141414;--paper:#ece7dc;--rule:#e4dfd2;--card:#fff;--dim:#6b6357}
html,body{height:100%}
body{background:#0a0a0a;color:var(--ink);font-family:Barlow,system-ui,sans-serif;overflow:hidden;-webkit-font-smoothing:antialiased}
b,strong{font-weight:700}
em.hl{font-style:normal;color:var(--orange);font-weight:700}
#deck{position:fixed;inset:0}
#stage{position:absolute;left:0;top:0;width:1600px;height:900px;transform-origin:0 0}
.slide{position:absolute;inset:0;display:none;flex-direction:column;
  background:repeating-linear-gradient(0deg,var(--paper) 0 31px,var(--rule) 31px 32px),var(--paper);
  padding:46px 78px 30px;overflow:hidden}
.slide.on{display:flex}
.chrome{display:flex;justify-content:space-between;font-family:"Big Shoulders Display",Barlow,sans-serif;
  font-weight:700;font-size:21px;letter-spacing:.11em;text-transform:uppercase;color:var(--dim);flex:0 0 auto}
.chrome .right{color:var(--orange)}
.hold{flex:1 1 auto;display:flex;align-items:center;justify-content:center;min-height:0;padding:14px 0 6px}
.bar{position:absolute;left:0;right:0;bottom:0;height:7px;background:rgba(20,20,20,.1)}
.bar i{display:block;height:100%;background:var(--orange)}
.print-only{display:none}

h1,h2,h3,h4{font-weight:700;line-height:1.04}
.kicker{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:31px;
  letter-spacing:.13em;text-transform:uppercase;color:var(--orange)}
.sub{font-size:31px;line-height:1.3;color:#3b362e;max-width:1180px}
.src{font-size:20px;color:var(--dim);margin-top:10px}

/* title */
.s-title{text-align:center}
.s-title .mark{height:156px;width:auto;margin-bottom:14px}
.s-title h1{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:184px;
  letter-spacing:.02em;text-transform:uppercase;line-height:.9}
.s-title .lede{font-size:46px;font-weight:600;margin-top:16px}
.s-title .meta{margin-top:30px;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:700;
  font-size:27px;letter-spacing:.15em;text-transform:uppercase;color:#fff;background:var(--orange);
  display:inline-block;padding:9px 22px}

/* statement */
.s-statement{max-width:1300px;text-align:center}
.s-statement .kicker{margin-bottom:22px}
.s-statement h2{font-size:80px;font-weight:600;line-height:1.08;letter-spacing:-.015em}
.s-statement .sub{margin:28px auto 0}

/* one number */
.s-number{text-align:center}
.s-number .kicker{margin-bottom:6px}
.s-number .huge{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:330px;
  line-height:.84;color:var(--orange);letter-spacing:-.01em}
.s-number.tone-ink .huge{color:var(--ink)}
.s-number .unit{font-size:.36em;margin-left:.1em;letter-spacing:.04em}
.s-number .sub{margin:26px auto 0;font-size:35px}

/* many numbers */
.s-numbers{width:100%;text-align:center}
.s-numbers .kicker{margin-bottom:26px}
.s-numbers .grid{display:grid;gap:34px 30px}
.s-numbers .g2{grid-template-columns:repeat(2,1fr)}
.s-numbers .g3{grid-template-columns:repeat(3,1fr)}
.s-numbers .g4{grid-template-columns:repeat(2,1fr)}
.s-numbers .g5,.s-numbers .g6{grid-template-columns:repeat(3,1fr)}
.s-numbers .cell{background:var(--card);border:2px solid #ddd5c4;padding:30px 20px 26px;display:flex;flex-direction:column;justify-content:center}
.s-numbers .big{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:106px;
  line-height:.88;color:var(--orange)}
.s-numbers .g2 .big{font-size:150px}
.s-numbers .g4 .big{font-size:120px}
.s-numbers .cell-label{font-size:27px;font-weight:600;margin-top:13px;line-height:1.16}
.s-numbers .cell-sub{font-size:20px;color:var(--dim);margin-top:8px;line-height:1.25}
.s-numbers .sub{margin:26px auto 0;font-size:26px}

/* screenshot */
.s-image{display:flex;gap:56px;align-items:center;width:100%;height:100%}
.s-image .col{flex:1 1 auto;min-width:0}
.s-image h3{font-size:70px;line-height:1.02;letter-spacing:-.015em}
.s-image .line{font-size:33px;line-height:1.28;margin-top:20px;color:#2d2924;max-width:760px}
.s-image .points{list-style:none;margin-top:24px;max-width:760px}
.s-image .points li{font-size:25px;line-height:1.3;padding-left:26px;position:relative;margin-top:11px;color:#3b362e}
.s-image .points li::before{content:"";position:absolute;left:0;top:.52em;width:13px;height:3px;background:var(--orange)}
.s-image .shot{flex:0 0 auto;height:100%;display:flex;align-items:center}
.s-image .shot img{max-height:660px;width:auto;border:3px solid var(--ink);background:#fff;display:block}
.s-image.wide .shot img{max-height:700px}

/* two panels */
.s-twoup{width:100%;text-align:center}
.s-twoup h3{font-size:58px;margin-bottom:22px;letter-spacing:-.01em}
.pair{display:flex;gap:48px;justify-content:center;align-items:stretch}
.panel{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.panel img{max-height:520px;max-width:100%;width:auto;border:3px solid var(--ink);background:#fff}
.panel figcaption{font-size:24px;line-height:1.24}
.panel figcaption span{display:block;color:var(--dim);font-size:20px;margin-top:5px}
.panel-text{background:var(--card);border:2px solid #ddd5c4;padding:38px 26px}
.panel-value{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:128px;
  line-height:.88;color:var(--orange)}
.panel-label{font-size:29px;font-weight:600;line-height:1.16}
.panel-caption{font-size:20px;color:var(--dim);line-height:1.26}

/* diagram — always full width of the stage */
.slide.k-diagram{padding:40px 40px 26px}
.slide.k-diagram .hold{padding:10px 0 4px}
.s-diagram{width:100%;height:100%;display:flex;flex-direction:column;align-items:center}
.s-diagram h3{font-size:44px;flex:0 0 auto;margin-bottom:10px;letter-spacing:-.01em;text-align:center}
.s-diagram .fig{flex:1 1 auto;min-height:0;width:100%;display:flex;align-items:center;justify-content:center}
.s-diagram .fig.card{background:#fff;border:2px solid #ddd5c4;padding:14px}
.s-diagram .fig svg{max-width:100%;max-height:100%}
.s-diagram .src{flex:0 0 auto;font-size:23px;color:#3b362e;text-align:center;max-width:1300px}

/* table */
.s-table{width:100%;max-width:1400px}
.s-table h3{font-size:56px;letter-spacing:-.015em;text-align:center}
.s-table .line{font-size:25px;color:var(--dim);margin-top:8px;text-align:center}
.s-table table{width:100%;border-collapse:collapse;margin-top:24px}
.s-table th{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:22px;
  letter-spacing:.12em;text-transform:uppercase;color:var(--orange);text-align:left;padding:0 14px 10px;
  border-bottom:3px solid var(--ink)}
.s-table td{padding:14px;border-bottom:2px solid #ddd5c4;font-size:28px;line-height:1.2;vertical-align:top}
.s-table .r{text-align:right;font-variant-numeric:tabular-nums}
.s-table tr.emph td{background:#fff;font-weight:600}
.s-table tr.emph td b{color:var(--orange)}
.s-table.dense td{font-size:23px;padding:10px 14px}
.s-table.dense th{font-size:19px}
.s-table .src{text-align:center;margin-top:16px}

/* quote */
.s-quote{max-width:1260px;text-align:center}
.s-quote blockquote{font-size:60px;font-weight:600;line-height:1.14;letter-spacing:-.015em}
.s-quote blockquote::before{content:"\\201C"}
.s-quote blockquote::after{content:"\\201D"}
.s-quote .cite{margin-top:26px;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:700;
  font-size:26px;letter-spacing:.14em;text-transform:uppercase;color:var(--orange)}

/* demo */
.s-demo{width:100%;max-width:1360px}
.s-demo .live{display:inline-block;background:var(--orange);color:#fff;font-family:"Big Shoulders Display",Barlow,sans-serif;
  font-weight:800;font-size:28px;letter-spacing:.2em;padding:6px 18px}
.s-demo h3{font-size:62px;margin-top:14px;letter-spacing:-.015em}
.s-demo .line{font-size:26px;color:var(--dim);margin-top:10px}
.s-demo table{width:100%;border-collapse:collapse;margin-top:24px}
.s-demo td{padding:15px 16px;border-top:2px solid #ddd5c4;vertical-align:top;font-size:26px;line-height:1.24}
.s-demo td.do{width:46%;font-weight:600}
.s-demo td.see{color:#3b362e}

/* the do-not-say card */
.s-endcard{text-align:center}
.s-endcard .mark{height:132px;width:auto}
.s-endcard p{font-size:56px;font-weight:600;margin-top:18px}
.s-endcard .url{font-size:27px;color:var(--dim);font-weight:400;margin-top:16px;letter-spacing:.04em}
.s-qa{width:100%}
.s-qa .stamp{display:inline-block;background:var(--ink);color:var(--yellow);font-family:"Big Shoulders Display",Barlow,sans-serif;
  font-weight:800;font-size:26px;letter-spacing:.2em;padding:5px 16px}
.s-qa h3{font-size:44px;margin-top:12px}
.s-qa .groups{display:grid;grid-template-columns:1fr 1fr;gap:20px 40px;margin-top:20px}
.s-qa h4{font-size:22px;text-transform:uppercase;letter-spacing:.1em;color:var(--orange)}
.s-qa ul{margin-top:8px;padding-left:20px}
.s-qa li{font-size:21px;line-height:1.32;margin-top:6px}

/* ------------------------------------------------------------ presenter */
#pv{position:fixed;right:0;top:0;bottom:0;width:0;background:#141414;color:#ece7dc;display:none;
  flex-direction:column;padding:20px;gap:14px;overflow:hidden;font-size:16px}
body.presenter #pv{display:flex;width:var(--pw)}
#pv h4{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:19px;
  letter-spacing:.16em;text-transform:uppercase;color:var(--orange)}
#clock{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:82px;line-height:.9;letter-spacing:.02em}
#clock.warn{color:var(--yellow)}
#clock.over{color:var(--orange)}
#clock small{display:block;font-family:Barlow,sans-serif;font-weight:400;font-size:14px;letter-spacing:.1em;
  text-transform:uppercase;color:#8e867a;margin-top:6px}
#marks{list-style:none;font-size:15px;line-height:1.3;max-height:150px;overflow:auto}
#marks li{display:flex;gap:10px;padding:3px 0;color:#8e867a}
#marks li b{color:#ece7dc;font-variant-numeric:tabular-nums;flex:0 0 46px}
#marks li.now{color:#ece7dc}
#marks li.now b{color:var(--orange)}
#notes{flex:1 1 auto;overflow:auto;line-height:1.42;font-size:17px}
#notes p{margin-bottom:10px}
#notes .muted{color:#6f675c}
.pv-defs{margin-top:12px;border-top:1px solid #2e2e2e;padding-top:10px}
.pv-defs h4{font-size:15px;letter-spacing:.14em;margin-bottom:6px}
.pv-defs ul{list-style:none;font-size:14.5px;line-height:1.34;color:#b5ad9e}
.pv-defs li{margin-bottom:5px}
.pv-defs b{color:var(--yellow);font-weight:700}
.pv-defs i{display:block;font-style:normal;font-size:12px;color:#6f675c;letter-spacing:.04em}
#nextwrap{flex:0 0 auto}
#nextbox{position:relative;width:100%;overflow:hidden;border:1px solid #2e2e2e;background:#000}
#nextbox .slide{position:absolute;display:flex!important;transform-origin:0 0}
#nextbox .bar,#nextbox .chrome{opacity:.6}
#pvfoot{font-size:13px;color:#6f675c;line-height:1.5}
#jump{position:fixed;left:50%;bottom:34px;transform:translateX(-50%);background:var(--ink);color:var(--yellow);
  font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:40px;letter-spacing:.14em;
  padding:8px 22px;display:none}
#jump.on{display:block}

@media print{
  @page{size:1600px 900px;margin:0}
  html,body{overflow:visible;background:#fff;height:auto}
  #deck{position:static}
  #stage{position:static;transform:none!important;width:auto;height:auto}
  #pv,#jump{display:none!important}
  .slide{position:relative;inset:auto;display:flex!important;width:1600px;height:900px;
    break-after:page;page-break-after:always;break-inside:avoid;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .slide:last-child{break-after:auto;page-break-after:auto}
  .presenter-only .s-endcard{display:none}
  .presenter-only .print-only{display:block;width:100%}
}
`;

/* -------------------------------------------------------------------- JS */

const JS = `
(function(){
  var slides=[].slice.call(document.querySelectorAll('#stage .slide'));
  var meta=window.__DECK__, N=slides.length, i=0, started=0, buf='', bufT=0;
  var stage=document.getElementById('stage'), pv=document.getElementById('pv');
  var PW=430;
  document.documentElement.style.setProperty('--pw',PW+'px');

  function layout(){
    var pres=document.body.classList.contains('presenter');
    var w=innerWidth-(pres?PW:0), h=innerHeight;
    var k=Math.min(w/1600,h/900);
    stage.style.transform='translate('+((w-1600*k)/2)+'px,'+((h-900*k)/2)+'px) scale('+k+')';
    var box=document.getElementById('nextbox');
    if(box){var bw=box.clientWidth||1; box.style.height=(bw*900/1600)+'px';
      var kid=box.firstElementChild; if(kid) kid.style.transform='scale('+(bw/1600)+')';}
  }

  function fmt(ms){
    var neg=ms<0, s=Math.round(Math.abs(ms)/1000);
    return (neg?'+':'')+Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
  }

  function tick(){
    var c=document.getElementById('clock'); if(!c) return;
    var left=started?(meta.seconds*1000-(Date.now()-started)):meta.seconds*1000;
    c.firstChild.nodeValue=fmt(left);
    c.className=left<0?'over':(left<60000?'warn':'');
    var el=started?(Date.now()-started)/1000:0, marks=meta.marks||[], at=-1;
    for(var m=0;m<marks.length;m++) if(marks[m].s<=el) at=m;
    var lis=document.querySelectorAll('#marks li');
    for(var j=0;j<lis.length;j++) lis[j].classList.toggle('now',j===at);
  }

  function show(n){
    n=Math.max(0,Math.min(N-1,n));
    if(n!==i&&!started) started=Date.now();
    i=n;
    for(var j=0;j<N;j++) slides[j].classList.toggle('on',j===i);
    location.hash='#'+(i+1);
    var s=meta.slides[i]||{};
    document.getElementById('notes').innerHTML=s.notes||'';
    var box=document.getElementById('nextbox');
    box.innerHTML='';
    if(i+1<N){var c=slides[i+1].cloneNode(true); c.classList.add('on'); box.appendChild(c);}
    document.getElementById('nextlabel').textContent=i+1<N?('next · '+(i+2)+'/'+N):'last slide';
    layout(); tick();
  }

  function jumpBuf(){ if(buf){ show(parseInt(buf,10)-1); buf=''; document.getElementById('jump').classList.remove('on'); } }

  addEventListener('keydown',function(e){
    if(e.metaKey||e.ctrlKey||e.altKey) return;
    var k=e.key;
    if(k>='0'&&k<='9'){ buf+=k; var j=document.getElementById('jump'); j.textContent=buf; j.classList.add('on');
      clearTimeout(bufT); bufT=setTimeout(jumpBuf,900); e.preventDefault(); return; }
    if(k==='Enter'){ jumpBuf(); e.preventDefault(); return; }
    if(k==='ArrowRight'||k==='ArrowDown'||k===' '||k==='PageDown'||k==='n'){ show(i+1); e.preventDefault(); }
    else if(k==='ArrowLeft'||k==='ArrowUp'||k==='PageUp'||k==='p'){ show(i-1); e.preventDefault(); }
    else if(k==='Home'){ show(0); e.preventDefault(); }
    else if(k==='End'){ show(N-1); e.preventDefault(); }
    else if(k==='s'||k==='S'){ document.body.classList.toggle('presenter'); layout(); e.preventDefault(); }
    else if(k==='Escape'){ document.body.classList.remove('presenter'); layout(); }
    else if(k==='f'||k==='F'){ if(document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen(); }
    else if(k==='r'||k==='R'){ started=Date.now(); tick(); }
    else if(k==='t'||k==='T'){ started=0; tick(); }
  });

  addEventListener('resize',layout);
  addEventListener('hashchange',function(){var n=parseInt(location.hash.slice(1),10); if(n&&n-1!==i) show(n-1);});
  stage.addEventListener('click',function(e){ show(i+(e.clientX<innerWidth*0.22?-1:1)); });
  setInterval(tick,250);

  var start=parseInt(location.hash.slice(1),10);
  show(start?start-1:0);
  if(!start) started=0;
  layout();
})();
`;

/* ----------------------------------------------------------------- shell */

function clock(t) {
  const [m, s] = String(t).split(":").map(Number);
  return (m || 0) * 60 + (s || 0);
}

async function buildDeck(deck) {
  const total = deck.slides.length;
  const sections = [];
  for (let i = 0; i < total; i++) sections.push(await slideHtml(deck.slides[i], i, deck, total));

  const marks = (deck.marks || []).map((m) => ({ ...m, s: clock(m.t) }));
  const runtime = {
    seconds: clock(deck.length || "5:00"),
    marks: marks.map((m) => ({ t: m.t, s: m.s })),
    slides: deck.slides.map((s) => ({ notes: notesHtml(s) })),
  };

  const markList = marks.map((m) => `<li><b>${esc(m.t)}</b><span>${esc(m.do)}</span></li>`).join("");

  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(deck.title)} — ${esc(deck.target)} — Mechanica</title>
<style>${fontFaces()}
${CSS}</style>
</head><body>
<div id="deck"><div id="stage">${sections.join("\n")}</div></div>
<aside id="pv">
  <div><h4>time left</h4><div id="clock">5:00<small>starts on the first advance · R restart · T reset</small></div></div>
  <div><h4>the clock</h4><ul id="marks">${markList}</ul></div>
  <div style="flex:1 1 auto;min-height:0;display:flex;flex-direction:column"><h4>notes</h4><div id="notes"></div></div>
  <div id="nextwrap"><h4 id="nextlabel">next</h4><div id="nextbox"></div></div>
  <div id="pvfoot">→ ← space · Home/End · digits+Enter jump · S presenter · F fullscreen · Ctrl+P prints one slide per page</div>
</aside>
<div id="jump"></div>
<script>window.__DECK__=${JSON.stringify(runtime)};</script>
<script>${JS}</script>
</body></html>`;
}

/* ----------------------------------------------------------------- index */

/**
 * Every flow diagram this project owns, per pitch, with the one line to say over it.
 * `docs/pitches/deck/mermaid.mjs` renders the ones that only existed inside a .md.
 */
const DIAGRAMS = {
  general: [["general/user-path.svg",
    "The whole product in one line: name the bike, say what is wrong in your own words, get the printed page — parts, chat and voice all lead back to it."]],
  "long-lake": [["long-lake/second-deployment.svg",
    "Built once, deployed N times. Grey took the whole hackathon and is never paid for again; orange is what one new vehicle costs; black is what a new shop costs, which is nothing."]],
  openai: [
    ["openai/architecture.svg",
      "Every lane has the same shape: orange is an OpenAI call, green is the code that can throw its answer away, black is what the mechanic actually gets."],
    ["openai/not-a-wrapper.svg",
      "What is deterministic, the three things the model is allowed to decide, and what is verified in code before anything renders."]],
  "token-company": [["token-company/token-path.svg",
    "Where the tokens go: the router, the spec path that costs nothing past it, the picker gate — and compression sitting between the PDF text and every model call, as a cost lever only."]],
  ramp: [["ramp/cost-path.svg",
    "Why the bill is small: retrieval is free, most asks never pay for a picker, and the manual is never in the prompt."]],
  deepgram: [["deepgram/architecture.svg",
    "One socket. The Cloudflare Worker holds the key, Deepgram calls our API server-to-server, and the browser tab only ever learns a sentence and a page number."]],
  elevenlabs: [["elevenlabs/agent.svg",
    "Everything black is ElevenLabs, everything cream is ours, and every arrow into the model comes out of a PDF."]],
  dropbox: [
    ["dropbox/rows-per-portal.svg", "One registry, 84 publisher portals, every one of them a different shape."],
    ["dropbox/chaos-to-order.svg", "53,557 rows down to 14,770 fetchable PDFs and 13,537 vehicles that open on the right page."],
    ["dropbox/folder-sync.svg",
      "One poller, one webhook, one ingest. A path that does not parse to make, model and year comes back unmatched instead of being guessed at."]],
  voloridge: [["voloridge/pipeline.svg",
    "The noisy half on the left, 600 GB of NOAA reduced in-stream to a 4 MB table on the right, and a verdict that costs zero tokens."]],
};

function diagramStrip(pitch) {
  const list = DIAGRAMS[pitch] || [];
  if (!list.length) return "";
  const figs = list.map(([file, caption]) => `<figure class="dg">
      <div class="dg-svg">${inlineSvgFile(file)}</div>
      <figcaption><b>${esc(file)}</b>${esc(caption)}</figcaption></figure>`).join("");
  return `<details class="dgs"><summary>${list.length} diagram${list.length > 1 ? "s" : ""} — ${list.map((l) => l[0].split("/")[1]).join(" · ")}</summary>${figs}</details>`;
}

function indexHtml(decks) {
  const rows = decks.map((d, n) => `<div class="item"><a class="row" href="${d.pitch}.html">
    <span class="n">${n + 1}</span>
    <span class="body"><b>${esc(d.title)}</b><span class="target">${esc(d.target)}</span>
    <span class="angle">${rich(d.angle || "")}</span></span>
    <span class="len">${esc(d.length)}<small>${d.slides.length} slides</small></span></a>
    ${diagramStrip(d.pitch)}</div>`).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mechanica — the nine decks</title><style>${fontFaces()}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--orange:#e85d04;--ink:#141414;--paper:#ece7dc;--rule:#e4dfd2;--dim:#6b6357}
body{font-family:Barlow,system-ui,sans-serif;color:var(--ink);
  background:repeating-linear-gradient(0deg,var(--paper) 0 31px,var(--rule) 31px 32px),var(--paper);min-height:100vh}
.wrap{max-width:1000px;margin:0 auto;padding:56px 26px 80px}
h1{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:92px;letter-spacing:.02em;
  text-transform:uppercase;line-height:.9}
.lede{font-size:26px;font-weight:600;margin-top:10px}
.note{font-size:17px;color:var(--dim);margin-top:10px;max-width:760px;line-height:1.45}
.rows{margin-top:38px;border-top:2px solid #ddd5c4}
.item{border-bottom:2px solid #ddd5c4}
.row{display:flex;gap:22px;align-items:center;padding:20px 8px;text-decoration:none;color:inherit}
.row:hover{background:#fff}
.dgs{padding:0 8px 18px}
.dgs summary{cursor:pointer;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:700;font-size:17px;
  letter-spacing:.11em;text-transform:uppercase;color:var(--dim);padding:6px 0}
.dgs summary:hover{color:var(--orange)}
.dgs[open] summary{color:var(--orange)}
.dg{margin:14px 0 22px;background:#fff;border:2px solid #ddd5c4}
.dg-svg{padding:14px;overflow-x:auto}
.dg-svg svg{display:block;width:100%;height:auto;max-height:640px}
.dg figcaption{border-top:2px solid #ddd5c4;padding:11px 14px;font-size:16px;line-height:1.4;color:#3b362e}
.dg figcaption b{display:block;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:700;font-size:16px;
  letter-spacing:.11em;text-transform:uppercase;color:var(--orange);margin-bottom:3px}
.n{font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;font-size:56px;color:var(--orange);
  flex:0 0 52px;line-height:.9;text-align:right}
.body{flex:1 1 auto;min-width:0}
.body b{font-size:29px;font-weight:700;display:block;line-height:1.1}
.target{display:block;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:700;font-size:19px;
  letter-spacing:.13em;text-transform:uppercase;color:var(--orange);margin-top:3px}
.angle{display:block;font-size:18px;color:#3b362e;margin-top:6px;line-height:1.35}
.len{flex:0 0 96px;text-align:right;font-family:"Big Shoulders Display",Barlow,sans-serif;font-weight:800;
  font-size:34px;line-height:1}
.len small{display:block;font-family:Barlow,sans-serif;font-weight:400;font-size:14px;color:var(--dim);
  letter-spacing:.06em;margin-top:4px}
.keys{margin-top:34px;font-size:17px;color:var(--dim);line-height:1.6}
.keys b{color:var(--ink)}
em.hl{font-style:normal;color:var(--orange);font-weight:700}
</style></head><body><div class="wrap">
<h1>The nine decks</h1>
<p class="lede">One product, nine rooms. Same story, same numbers, five minutes each.</p>
<p class="note">In rehearsal order. <b>general</b> first, always — it is the spine, and eight of the nine are
80% rehearsed once it is muscle memory. Every figure comes from <b>numbers.md</b>; re-run
<b>pitch_numbers.py</b> and read §11 before you present. The last slide of every deck is that pitch's
<b>do not say</b> card — the audience sees the end card, the presenter view sees the list.</p>
<p class="note">Open a row's <b>diagrams</b> line to see every flow diagram that pitch owns, rendered
inline. The decks themselves carry a redrawn, full-width version of each one: a mermaid render is the
right shape for this page and the wrong shape for a 16:9 projector. Rebuild everything with
<b>node docs/pitches/deck/build.mjs</b>, and re-render the .md-only diagrams with
<b>node docs/pitches/deck/mermaid.mjs</b>.</p>
<div class="rows">${rows}</div>
<p class="keys"><b>→ ← space</b> next / previous · <b>Home / End</b> · <b>digits then Enter</b> jump to a slide ·
<b>S</b> presenter view (notes, next slide, the 5-minute countdown) · <b>F</b> fullscreen ·
<b>R</b> restart the clock · <b>Ctrl+P</b> prints one slide per page.</p>
</div></body></html>`;
}

/* ------------------------------------------------------------------ main */

const want = process.argv.slice(2).filter((a) => !a.startsWith("-"));
const files = readdirSync(SLIDES).filter((f) => f.endsWith(".json")).sort();
const decks = files.map((f) => JSON.parse(readFileSync(join(SLIDES, f), "utf8")));
decks.sort((a, b) => (a.order || 99) - (b.order || 99));

mkdirSync(join(HERE, "shots"), { recursive: true });
let totalBytes = 0;
for (const deck of decks) {
  if (want.length && !want.includes(deck.pitch)) continue;
  assetBytes = 0;
  const html = await buildDeck(deck);
  const out = join(HERE, deck.pitch + ".html");
  writeFileSync(out, html, "utf8");
  totalBytes += Buffer.byteLength(html);
  console.log(`${deck.pitch.padEnd(15)} ${String(deck.slides.length).padStart(2)} slides  ${(Buffer.byteLength(html) / 1048576).toFixed(2)} MB`);
}
writeFileSync(join(HERE, "index.html"), indexHtml(decks), "utf8");
console.log(`index.html      ${decks.length} decks`);
if (problems.length) {
  console.error("\nPROBLEMS:");
  for (const p of [...new Set(problems)]) console.error("  - " + p);
  process.exitCode = 1;
}
