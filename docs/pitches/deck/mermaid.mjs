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
 * Mermaid writes its own default font stack into the SVG and ignores a `fontFamily` theme
 * variable set from a diagram's init directive, so the family is swapped afterwards — Barlow
 * where it is installed, a sane sans everywhere else — and the node labels are given the weight
 * the rest of the deck uses.
 */
const MERMAID_FONT = '"trebuchet ms",verdana,arial,sans-serif';
const OUR_FONT = 'Barlow,"Segoe UI",system-ui,sans-serif';

function dress(svg, id) {
  let out = svg.split(MERMAID_FONT).join(OUR_FONT);
  out = out.replace("</style>", `#${id} .nodeLabel,#${id} .nodeLabel *{font-weight:600}</style>`);
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
  await browser.close();
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) await main();
