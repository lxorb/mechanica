#!/usr/bin/env node
/**
 * Renders the one flow diagram each pitch owns — the mermaid block that lives inside the pitch
 * .md, mirrored as the .mmd beside it — to an .svg and a 2× .png next to that pitch.
 *
 *   node docs/pitches/deck/mermaid.mjs            # all nine
 *   node docs/pitches/deck/mermaid.mjs openai     # one
 *
 * One diagram per pitch, at most ten nodes, one noun phrase per node. The .md block is the
 * source of truth; the .mmd is written from it so the file beside the pitch never drifts.
 *
 * Mermaid itself is loaded from jsDelivr into headless Chrome (there is no mermaid-cli on this
 * machine); Chrome comes from CHROME_PATH, puppeteer-core from the scratchpad.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PITCHES = resolve(HERE, "..");
const FONTS = join(HERE, "fonts");
const PUP = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

/** The block in each pitch .md, and where its render goes. One per pitch, nine in all. */
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

export function mermaidOf(pitch) {
  const md = readFileSync(join(PITCHES, pitch + ".md"), "utf8");
  const m = /^```mermaid\r?\n([\s\S]*?)^```/m.exec(md);
  return m ? m[1].trim() : null;
}

const PAGE = `<!doctype html><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>.nodeLabel,.nodeLabel text,.nodeLabel tspan,svg text,svg tspan{font-weight:600}</style>
<body style="margin:0;background:#fff"><div id="out"></div>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({
  startOnLoad: false, securityLevel: "loose", theme: "base",
  flowchart: { htmlLabels: false, padding: 16, curve: "linear", useMaxWidth: false },
  themeVariables: {
    fontFamily: "Barlow, system-ui, sans-serif", fontSize: "21px",
    background: "#ffffff", primaryColor: "#ece7dc", primaryTextColor: "#141414",
    primaryBorderColor: "#141414", lineColor: "#141414", secondaryColor: "#ffffff",
    tertiaryColor: "#f6f3ec", clusterBkg: "#f6f3ec", clusterBorder: "#b3a996",
    edgeLabelBackground: "#ffffff", nodeBorder: "#141414",
  },
});
window.__render = async (code, id) => {
  await document.fonts.ready;
  const { svg } = await mermaid.render(id, code);
  document.getElementById("out").innerHTML = svg;
  const el = document.querySelector("#out svg");
  const box = el.getBBox();
  return { svg, w: Math.ceil(box.width + 40), h: Math.ceil(box.height + 40) };
};
window.__ready = true;
</script></body>`;

/**
 * Mermaid only honours a `fontFamily` theme variable that names one family, so each diagram asks
 * for bare `Barlow` — which is what it is then laid out in. The fallbacks are added afterwards,
 * for whoever renders the .mmd without Barlow installed, and the node labels are given the weight
 * the rest of the deck uses (the extra `flowchart.padding` in each diagram covers it).
 */
const OUR_FONT = 'Barlow,"Segoe UI",system-ui,sans-serif';

function dress(svg, id) {
  let out = svg.split("font-family:Barlow").join("font-family:" + OUR_FONT);
  out = out.replace("</style>", `#${id} .nodeLabel,#${id} .nodeLabel *,#${id} text,#${id} tspan{font-weight:600}</style>`);
  return out;
}

/** The deck's own Barlow, inlined, so a render never depends on the network or on what is installed. */
function fontFaces() {
  if (!existsSync(FONTS)) return "";
  return readdirSync(FONTS).filter((f) => /^Barlow-\d+\.woff2$/.test(f)).map((f) => {
    const weight = /-(\d+)\.woff2$/.exec(f)[1];
    const b64 = readFileSync(join(FONTS, f)).toString("base64");
    return `@font-face{font-family:'Barlow';font-style:normal;font-weight:${weight};`
      + `src:url(data:font/woff2;base64,${b64}) format('woff2')}`;
  }).join("\n");
}

/** The rendered SVG, sized to its own content and on a white ground, ready to screenshot. */
const SHOT = (svg, w, h, faces) => `<!doctype html><meta charset="utf-8"><style>${faces}</style>
<body style="margin:0;background:#fff;width:${w}px;height:${h}px;overflow:hidden">
<div id="fig" style="width:${w}px;height:${h}px;display:flex;align-items:center;justify-content:center">${svg}</div>
</body>`;

async function main() {
  const only = process.argv.slice(2);
  const jobs = only.length ? RENDER.filter((j) => only.includes(j.pitch)) : RENDER;
  const puppeteer = await import(pathToFileURL(PUP).href);
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: "new", protocolTimeout: 180000,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files"],
    defaultViewport: { width: 1600, height: 1200 },
  });
  const page = await browser.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await page.setContent(PAGE, { waitUntil: "networkidle2", timeout: 90000 });
  await page.waitForFunction(() => window.__ready === true, { timeout: 60000 });

  const shot = await browser.newPage();
  const faces = fontFaces();
  for (const job of jobs) {
    const code = mermaidOf(job.pitch);
    if (!code) { console.error("no mermaid block in " + job.pitch + ".md"); continue; }
    const nodes = new Set(code.match(/\b[A-Z][A-Z0-9]*(?=\(")/g) || []).size;
    if (nodes > 10) console.error(`${job.pitch}: ${nodes} nodes — the cap is 10`);
    const base = join(PITCHES, job.pitch, job.name);
    const id = "mm-" + job.pitch + "-" + job.name;
    writeFileSync(base + ".mmd", code + "\n", "utf8");

    let out;
    try {
      out = await page.evaluate((c, i) => window.__render(c, i), code, id);
    } catch (e) { console.error(`${job.pitch}/${job.name}: ${e.message}`); continue; }
    const svg = dress(out.svg, id);
    writeFileSync(base + ".svg", svg, "utf8");

    // 2× PNG: the same SVG, screenshotted at deviceScaleFactor 2.
    await shot.setViewport({ width: out.w, height: out.h, deviceScaleFactor: 2 });
    await shot.setContent(SHOT(svg, out.w, out.h, faces), { waitUntil: "domcontentloaded", timeout: 60000 });
    await shot.evaluate(() => document.fonts.ready);
    await new Promise((r) => setTimeout(r, 250));
    await shot.screenshot({ path: base + ".png" });

    console.log(`${(job.pitch + "/" + job.name).padEnd(34)} ${String(nodes).padStart(2)} nodes  `
      + `${String(out.w).padStart(4)}×${String(out.h).padEnd(4)} → .svg + .png@2x`);
  }
  if (errs.length) console.error("page errors:", errs.slice(0, 5));
  if (jobs.length === RENDER.length) await sheet(shot, faces);
  await browser.close();
}

/** Every node label, in the order the source declares them. */
function nodesOf(code) {
  return [...code.matchAll(/\b[A-Z][A-Z0-9]*\("([^"]+)"\)/g)].map((m) => m[1]);
}

/**
 * docs/pitches/DIAGRAMS.png — the nine on one sheet, so a change to any of them is one look
 * away — and DIAGRAMS.md, which lists each one's nodes.
 */
async function sheet(page, faces) {
  const cells = RENDER.map((job) => {
    const file = join(PITCHES, job.pitch, job.name);
    const code = readFileSync(file + ".mmd", "utf8");
    return { ...job, svg: readFileSync(file + ".svg", "utf8"), nodes: nodesOf(code) };
  });

  const html = `<!doctype html><meta charset="utf-8"><style>${faces}
    *{box-sizing:border-box;margin:0}
    body{width:2100px;background:#ece7dc;font-family:Barlow,"Segoe UI",system-ui,sans-serif;padding:40px}
    h1{font-size:44px;font-weight:800;letter-spacing:.02em;text-transform:uppercase;margin-bottom:6px}
    .lede{font-size:21px;color:#4a453d;margin-bottom:28px}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
    figure{background:#fff;border:3px solid #141414;border-radius:14px;padding:16px 14px 12px;
      display:flex;flex-direction:column;gap:10px;min-height:430px}
    figcaption{font-size:23px;font-weight:700}
    figcaption small{display:block;font-weight:600;font-size:17px;color:#8f3a02}
    .fig{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}
    .fig svg{max-width:100%;max-height:330px;height:auto;width:auto}
  </style><body>
  <h1>Mechanica — the nine diagrams</h1>
  <p class="lede">One flow chart per pitch. At most ten nodes, one thing per node, the mechanic and the manual page at the two ends, the sponsor's own services in orange.</p>
  <div class="grid">${cells.map((c) => `<figure>
    <figcaption>${c.pitch}<small>${c.pitch}/${c.name} · ${c.nodes.length} nodes</small></figcaption>
    <div class="fig">${c.svg}</div></figure>`).join("")}</div></body>`;

  await page.setViewport({ width: 2100, height: 800, deviceScaleFactor: 2 });
  await page.setContent(html, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, 400));
  await page.screenshot({ path: join(PITCHES, "DIAGRAMS.png"), fullPage: true });

  const md = `# The nine diagrams

One flow chart per pitch, nine in all. At most ten nodes each and one thing per node — a service, a
model, a tool, an artefact, the person — with **the mechanic and the manual page as the two ends**.
No sentences, no numbers, no edge labels. Three colours, the same in all nine:
**ink** for the two ends, **paper** for our own code, **orange** for the sponsor's services (or, in
the pitches with no sponsor tech, for the thing that room is there to look at).

![the nine diagrams](DIAGRAMS.png)

Each diagram lives in three places, all generated from the same node list: the \`.mmd\` beside its
pitch, the \`\`\`mermaid\`\`\` block inside the pitch \`.md\`, and the \`diagram\` slide in
\`deck/slides/<pitch>.json\`. Re-render with \`node docs/pitches/deck/mermaid.mjs\`, then rebuild the
decks with \`node docs/pitches/deck/build.mjs\`.

| # | pitch | source | nodes | the nodes, in order |
|---|---|---|---|---|
${cells.map((c, i) => `| ${i + 1} | [\`${c.pitch}.md\`](${c.pitch}.md) | [\`${c.pitch}/${c.name}.mmd\`](${c.pitch}/${c.name}.mmd) · [\`.svg\`](${c.pitch}/${c.name}.svg) · [\`.png\`](${c.pitch}/${c.name}.png) | ${c.nodes.length} | ${c.nodes.join(" · ")} |`).join("\n")}

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
    + `${cells.reduce((a, c) => a + c.nodes.length, 0)} nodes in all`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) await main();
