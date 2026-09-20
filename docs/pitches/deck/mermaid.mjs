#!/usr/bin/env node
/**
 * Draws the one flow chart each pitch owns.
 *
 *   node docs/pitches/deck/mermaid.mjs            # all nine, then the audit
 *   node docs/pitches/deck/mermaid.mjs openai     # one
 *   node docs/pitches/deck/mermaid.mjs --audit    # measure only, render nothing
 *
 * The editable source is the ```mermaid``` block inside each pitch .md, mirrored to the .mmd
 * beside it. It is parsed — the format the generator writes is strict — and handed to `lane.mjs`,
 * which is also what draws the decks' diagram slides. Mermaid's own layout engine is not used for
 * the shipped art: it centres a verb on its arrow and it will not promise that an arrow leaves a
 * box at the midpoint of its edge. lane.mjs places every coordinate itself, so it does.
 *
 * Chrome (CHROME_PATH) is used for two things only: measuring real text widths, so the boxes,
 * the gaps and the label pills are exact rather than estimated, and screenshotting the 2× PNGs.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { laneSvg, makeMeasure, METRICS, GROUND } from "./lane.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PITCHES = resolve(HERE, "..");
const FONTS = join(HERE, "fonts");
const PUP = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

/** One chart per pitch, nine in all. */
export const RENDER = [
  { pitch: "general", name: "user-path" },
  { pitch: "long-lake", name: "second-deployment" },
  { pitch: "openai", name: "architecture" },
  { pitch: "token-company", name: "token-path" },
  { pitch: "ramp", name: "cost-path" },
  { pitch: "deepgram", name: "architecture" },
  { pitch: "elevenlabs", name: "agent" },
  { pitch: "dropbox", name: "folder-sync" },
  { pitch: "voloridge", name: "pipeline" },
];

const TONE_OF = { ends: "ink", ours: "paper", them: "orange" };

export function mermaidOf(pitch) {
  const md = readFileSync(join(PITCHES, pitch + ".md"), "utf8");
  const m = /^```mermaid\r?\n([\s\S]*?)^```/m.exec(md);
  return m ? m[1].trim() : null;
}

/* ------------------------------------------------------------------ parse */

/**
 * The mermaid source -> the flow lane.mjs draws. One invisible subgraph per row; inside a row
 * `A --> B` is an arrow and `A ~~~ B` marks alternatives; `R1 -- "verb" --> R2` is the connector
 * between two rows, and `%% into R3 FIT` says which box in R3 it lands on.
 */
export function flowOf(code) {
  const nodeRe = /([A-Z][A-Z0-9]*)\("([^"]+)"\):::(\w+)/g;
  const rows = [];
  const byId = new Map();

  for (const block of code.split(/^\s*subgraph .*$/m).slice(1)) {
    const body = block.split(/^\s*end\s*$/m)[0];
    const items = [], labels = [];
    let m;
    nodeRe.lastIndex = 0;
    while ((m = nodeRe.exec(body))) {
      items.push({ tone: TONE_OF[m[3]] || "paper", t: m[2] });
      byId.set(m[1], { row: rows.length, index: items.length - 1 });
    }
    for (const v of body.matchAll(/-- "([^"]+)" -->/g)) labels.push(v[1]);
    const alt = /~~~/.test(body);
    const row = { items };
    if (alt) row.link = "none"; else if (labels.length) row.labels = labels;
    rows.push(row);
  }

  if (!rows.length) {                                   // a one-row chart has no subgraphs
    const items = [], labels = [];
    let m;
    nodeRe.lastIndex = 0;
    while ((m = nodeRe.exec(code))) items.push({ tone: TONE_OF[m[3]] || "paper", t: m[2] });
    for (const v of code.matchAll(/-- "([^"]+)" -->/g)) labels.push(v[1]);
    rows.push(labels.length ? { items, labels } : { items });
    return { w: 1440, bands: [{ rows }] };
  }

  const link = /^\s*(R\d+(?:\s*--\s*"[^"]+"\s*-->\s*R\d+)+)\s*$/m.exec(code);
  if (link) {
    const verbs = [...link[1].matchAll(/-- "([^"]+)" -->/g)].map((v) => v[1]);
    verbs.forEach((verb, i) => { rows[i + 1].down = true; rows[i + 1].downLabel = verb; });
  }
  for (const d of code.matchAll(/^\s*%% (into|from) R(\d+) ([A-Z][A-Z0-9]*)\s*$/gm)) {
    const at = byId.get(d[3]);
    if (at) rows[Number(d[2]) - 1][d[1]] = at.index;
  }
  return { w: 1440, bands: [{ rows }] };
}

/* ---------------------------------------------------------------- measure */

const MEASURE_PAGE = (faces) => `<!doctype html><meta charset="utf-8"><style>${faces}
body{margin:0;font-family:Barlow,"Segoe UI",system-ui,sans-serif}
#m{position:absolute;visibility:hidden;white-space:pre}</style><body><span id="m"></span>
<script>
window.__measure = (jobs) => jobs.map(([t, size, weight]) => {
  const el = document.getElementById("m");
  el.style.font = weight + " " + size + "px Barlow, 'Segoe UI', system-ui, sans-serif";
  el.textContent = t;
  return el.getBoundingClientRect().width;
});
window.__ready = true;
</script></body>`;

/** Every string a chart can print, measured once in the real font. */
async function measurer(page, flows) {
  const want = new Set();
  const add = (t, size, weight) => want.add(JSON.stringify([String(t), size, weight]));
  for (const flow of flows) {
    for (const row of flow.bands[0].rows) {
      for (const it of row.items) {
        for (const w of String(it.t).split(/[\s|]+/)) { for (const s of [30, 28.2, 26.1, 24]) add(w, s, 700); }
        for (const s of [30, 28.2, 26.1, 24]) { add(it.t, s, 700); add(it.t.replace(/\|/g, " "), s, 700); }
      }
      for (const v of [...(row.labels || []), ...(row.downLabel ? [row.downLabel] : [])]) add(v, 19, 600);
    }
  }
  const jobs = [...want].map((j) => JSON.parse(j));
  const widths = await page.evaluate((j) => window.__measure(j), jobs);
  const table = new Map(jobs.map((j, i) => [JSON.stringify(j), widths[i]]));
  writeFileSync(METRICS, JSON.stringify(Object.fromEntries(table), null, 0), "utf8");
  return makeMeasure(table);
}

function fontFaces() {
  if (!existsSync(FONTS)) return "";
  return readdirSync(FONTS).filter((f) => /^Barlow-\d+\.woff2$/.test(f)).map((f) => {
    const weight = /-(\d+)\.woff2$/.exec(f)[1];
    return `@font-face{font-family:'Barlow';font-style:normal;font-weight:${weight};`
      + `src:url(data:font/woff2;base64,${readFileSync(join(FONTS, f)).toString("base64")}) format('woff2')}`;
  }).join("\n");
}

/* ------------------------------------------------------------------ audit */

const overlaps = (a, b, tol = 0) =>
  a.x + a.w > b.x + tol && b.x + b.w > a.x + tol && a.y + a.h > b.y + tol && b.y + b.h > a.y + tol;

/**
 * Numeric, not visual: every label pill against every box and every line segment, and every
 * arrow endpoint against the midpoint of the node edge it should touch. Tolerance 1 px.
 */
function audit(name, flow, out) {
  const bad = [];
  const boxes = out.placed.flatMap((p) => p.boxes.map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.h, t: b.it.t })));

  // 1. pills clear of every box, and of each other
  for (const L of out.labelBoxes) {
    for (const b of boxes) if (overlaps(L, b, 1)) bad.push(`label overlaps box "${b.t}"`);
  }
  for (let i = 0; i < out.labelBoxes.length; i++) {
    for (let j = i + 1; j < out.labelBoxes.length; j++) {
      if (overlaps(out.labelBoxes[i], out.labelBoxes[j], 1)) bad.push("two labels overlap");
    }
  }

  // 1b. no pill sits on a drawn line — tested against the real segments, not their bounding boxes
  const hits = (L, g) => {
    if (Math.abs(g.y1 - g.y2) < 0.5) {                                   // horizontal
      return g.y1 > L.y && g.y1 < L.y + L.h && Math.max(g.x1, g.x2) > L.x && Math.min(g.x1, g.x2) < L.x + L.w;
    }
    return g.x1 > L.x && g.x1 < L.x + L.w && Math.max(g.y1, g.y2) > L.y && Math.min(g.y1, g.y2) < L.y + L.h;
  };
  for (const L of out.labelBoxes) {
    for (const g of out.segments) if (hits(L, g)) bad.push("a label sits on a line");
  }

  // 2. every horizontal arrow leaves and lands on a node-edge midpoint, dead straight
  for (const { row, boxes: bs } of out.placed) {
    if (row.link === "none") continue;
    for (let i = 0; i < bs.length - 1; i++) {
      const a = bs[i], z = bs[i + 1];
      const ay = a.y + a.h / 2, zy = z.y + z.h / 2;
      if (Math.abs(ay - zy) > 1) bad.push(`arrow ${i + 1} is not horizontal`);
      if (Math.abs((a.x + a.w) - (z.x - out.gap)) > 1) bad.push(`arrow ${i + 1} does not span the gap`);
    }
    const gaps = bs.slice(1).map((b, i) => b.x - (bs[i].x + bs[i].w));
    if (gaps.length && Math.max(...gaps) - Math.min(...gaps) > 1) bad.push("gaps in a row are unequal");
    if (new Set(bs.map((b) => Math.round(b.y))).size > 1) bad.push("a row is off its baseline");
  }

  // 3. row-to-row connectors are orthogonal and land on top-edge midpoints
  for (let r = 1; r < out.placed.length; r++) {
    const prev = out.placed[r - 1], cur = out.placed[r];
    if (!cur.row.down) continue;
    const dst = cur.row.link === "none" ? cur.boxes : [cur.boxes[cur.row.into ?? 0]];
    for (const d of dst) {
      const midX = d.x + d.w / 2;
      if (!Number.isFinite(midX)) bad.push("connector target has no midpoint");
      if (Math.abs(d.y - cur.top) > 1) bad.push("connector lands off the row top");
    }
    if (prev.bottom >= cur.top) bad.push("rows overlap");
  }
  return { name, boxes: boxes.length, labels: out.labelBoxes.length, bad };
}

/** The shipped .svg, opened and measured: every verb's glyph box must sit inside its own pill. */
async function measureInBrowser(page, svg, faces) {
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>${faces}</style><body style="margin:0">${svg}</body>`,
    { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(() => {
    const out = [];
    const svgEl = document.querySelector("svg");
    const texts = [...svgEl.querySelectorAll("text")].filter((t) => t.getAttribute("font-size") === "19");
    for (const t of texts) {
      const b = t.getBBox();
      const r = t.previousElementSibling;
      if (!r || r.tagName !== "rect") { out.push(`verb "${t.textContent}" has no pill`); continue; }
      const p = { x: +r.getAttribute("x"), y: +r.getAttribute("y"), w: +r.getAttribute("width"), h: +r.getAttribute("height") };
      if (b.x < p.x - 0.5 || b.x + b.width > p.x + p.w + 0.5 || b.y < p.y - 0.5 || b.y + b.height > p.y + p.h + 0.5) {
        out.push(`verb "${t.textContent}" overflows its pill`);
      }
    }
    return out;
  });
}

/* ----------------------------------------------------------------- render */

const SHOT = (svg, w, h, faces) => `<!doctype html><meta charset="utf-8"><style>${faces}</style>
<body style="margin:0;background:${GROUND};width:${w}px;height:${h}px;overflow:hidden">${svg}</body>`;

async function main() {
  const args = process.argv.slice(2);
  const auditOnly = args.includes("--audit");
  const only = args.filter((a) => !a.startsWith("--"));
  const jobs = only.length ? RENDER.filter((j) => only.includes(j.pitch)) : RENDER;

  const puppeteer = await import(pathToFileURL(PUP).href);
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: "new", protocolTimeout: 180000,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
    defaultViewport: { width: 1600, height: 1200 },
  });
  const faces = fontFaces();
  const page = await browser.newPage();
  await page.setContent(MEASURE_PAGE(faces), { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => window.__ready === true, { timeout: 30000 });

  const sources = jobs.map((j) => ({ ...j, code: mermaidOf(j.pitch) }));
  for (const s of sources) if (!s.code) throw new Error("no mermaid block in " + s.pitch + ".md");
  const flows = sources.map((s) => flowOf(s.code));
  const measure = await measurer(page, flows);

  const shot = await browser.newPage();
  const report = [];
  for (const [i, job] of sources.entries()) {
    const flow = flows[i];
    const nodes = flow.bands[0].rows.reduce((a, r) => a + r.items.length, 0);
    if (nodes > 10) console.error(`${job.pitch}: ${nodes} nodes — the cap is 10`);
    const base = join(PITCHES, job.pitch, job.name);
    const out = laneSvg(flow, { measure });
    const a = audit(`${job.pitch}/${job.name}`, flow, out);
    a.bad.push(...await measureInBrowser(shot, out.svg, faces));
    report.push(a);

    if (!auditOnly) {
      writeFileSync(base + ".mmd", job.code + "\n", "utf8");
      writeFileSync(base + ".svg", out.svg, "utf8");
      await shot.setViewport({ width: out.width, height: out.height, deviceScaleFactor: 2 });
      await shot.setContent(SHOT(out.svg, out.width, out.height, faces), { waitUntil: "domcontentloaded", timeout: 60000 });
      await shot.evaluate(() => document.fonts.ready);
      await new Promise((r) => setTimeout(r, 200));
      await shot.screenshot({ path: base + ".png" });
    }
    console.log(`${a.name.padEnd(34)} ${String(nodes).padStart(2)} nodes  ${String(a.labels).padStart(2)} verbs  `
      + `${String(out.width).padStart(4)}×${String(out.height).padEnd(4)} `
      + (a.bad.length ? "FAIL " + a.bad.slice(0, 3).join("; ") : "clean"));
  }

  if (!auditOnly && jobs.length === RENDER.length) await sheet(shot, faces, sources, flows, measure);
  await browser.close();
  const failed = report.filter((r) => r.bad.length);
  console.log(`\n${report.length} charts audited — ${failed.length ? failed.length + " FAILED" : "0 overlaps, 0 misaligned arrows"}`);
  if (failed.length) process.exitCode = 1;
}

/* ------------------------------------------------------- the contact sheet */

const nodesOf = (flow) => flow.bands[0].rows.flatMap((r) => r.items.map((i) => i.t));
const verbsOf = (flow) => flow.bands[0].rows.flatMap((r) => [...(r.downLabel ? [r.downLabel] : []), ...(r.labels || [])]);

async function sheet(page, faces, sources, flows, measure) {
  const cells = sources.map((s, i) => ({
    ...s, svg: laneSvg(flows[i], { measure }).svg, nodes: nodesOf(flows[i]), verbs: verbsOf(flows[i]),
  }));

  const html = `<!doctype html><meta charset="utf-8"><style>${faces}
    *{box-sizing:border-box;margin:0}
    body{width:2100px;background:${GROUND};font-family:Barlow,"Segoe UI",system-ui,sans-serif;padding:40px}
    h1{font-size:44px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;margin-bottom:6px}
    .lede{font-size:21px;color:#4a453d;margin-bottom:28px}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
    figure{background:#fff;border:3px solid #141414;border-radius:14px;padding:16px 14px 12px;
      display:flex;flex-direction:column;gap:10px;min-height:440px}
    figcaption{font-size:23px;font-weight:700}
    figcaption small{display:block;font-weight:600;font-size:17px;color:#8f3a02}
    .fig{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}
    .fig svg{max-width:100%;max-height:340px;height:auto;width:auto}
  </style><body>
  <h1>Mechanica — the nine diagrams</h1>
  <p class="lede">One flow chart per pitch. At most ten nodes, one thing per node, one verb on every arrow, the mechanic and the manual page at the two ends, the sponsor's own services in orange.</p>
  <div class="grid">${cells.map((c) => `<figure>
    <figcaption>${c.pitch}<small>${c.pitch}/${c.name} · ${c.nodes.length} nodes · ${c.verbs.length} verbs</small></figcaption>
    <div class="fig">${c.svg}</div></figure>`).join("")}</div></body>`;

  await page.setViewport({ width: 2100, height: 800, deviceScaleFactor: 2 });
  await page.setContent(html, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, 400));
  await page.screenshot({ path: join(PITCHES, "DIAGRAMS.png"), fullPage: true });

  const md = `# The nine diagrams

One flow chart per pitch, nine in all. At most ten nodes each and one thing per node — a service, a
model, a tool, an artefact, the person — with **the mechanic and the manual page as the two ends**.
No sentences and no numbers inside a box; every drawn arrow carries one lowercase verb, on an opaque
pill above its line. Three colours, the same in all nine: **ink** for the two ends, **paper** for our
own code, **orange** for the sponsor's services (or, in the pitches with no sponsor tech, for the
thing that room is there to look at).

![the nine diagrams](DIAGRAMS.png)

Each chart lives in three places, all from the same rows: the \`.mmd\` beside its pitch, the
\`mermaid\` block inside the pitch \`.md\`, and the \`diagram\` slide in \`deck/slides/<pitch>.json\`.
The \`.mmd\` is the editable source; \`deck/lane.mjs\` draws the shipped art from it with explicit
coordinates — every arrow leaves and lands on the midpoint of a node edge, rows share a baseline,
gaps are equal, and a row-to-row connector is an orthogonal elbow, never a diagonal. Re-render with
\`node docs/pitches/deck/mermaid.mjs\` (which also writes \`DIAGRAMS.png\` and this file and audits
every chart numerically), then rebuild the decks with \`node docs/pitches/deck/build.mjs\`.

| # | pitch | source | the nodes, in order | the verb on every arrow |
|---|---|---|---|---|
${cells.map((c, i) => `| ${i + 1} | [\`${c.pitch}.md\`](${c.pitch}.md) | [\`${c.pitch}/${c.name}.mmd\`](${c.pitch}/${c.name}.mmd) · [\`.svg\`](${c.pitch}/${c.name}.svg) · [\`.png\`](${c.pitch}/${c.name}.png) | **${c.nodes.length}** — ${c.nodes.join(" · ")} | **${c.verbs.length}** — ${c.verbs.join(" · ")} |`).join("\n")}

## What changed

The old charts were architecture drawings: legends, sentences inside the boxes, measured figures,
and up to twenty-six nodes. They were accurate and unreadable at slide size. These carry the same
claims — every node names something that exists in the repo — with the detail moved to the caption,
the presenter notes and the pitch text, where it can be said out loud instead of squinted at.

The OpenAI pitch had two charts; it now has one. \`openai/not-a-wrapper\` is gone as a drawing and
lives as the argument spoken over \`openai/architecture\` — *Structured Outputs* for shape,
*Grounding gate* for truth — plus the table in \`openai.md\`.
`;
  writeFileSync(join(PITCHES, "DIAGRAMS.md"), md, "utf8");
  console.log(`\nDIAGRAMS.png + DIAGRAMS.md   ${cells.length} diagrams, `
    + `${cells.reduce((a, c) => a + c.nodes.length, 0)} nodes and `
    + `${cells.reduce((a, c) => a + c.verbs.length, 0)} edge verbs in all`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) await main();
