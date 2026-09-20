#!/usr/bin/env node
/**
 * Renders the mermaid block that lives inside each pitch .md and saves it as an SVG next to that
 * pitch, so every flow diagram exists as a file the index page can inline.
 *
 *   node docs/pitches/deck/mermaid.mjs
 *
 * Mermaid itself is loaded from jsDelivr into headless Chrome (there is no mermaid-cli on this
 * machine); Chrome comes from CHROME_PATH, puppeteer-core from the scratchpad. Diagrams that
 * already have a rendered .svg beside the pitch are left alone — this never overwrites a file it
 * did not create, and it never touches a .md.
 */

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PITCHES = resolve(HERE, "..");
const PUP = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

/** The block in each pitch .md, and where it goes. Only these six lack a rendered SVG. */
export const RENDER = [
  { pitch: "general", name: "user-path" },
  { pitch: "token-company", name: "token-path" },
  { pitch: "ramp", name: "cost-path" },
  { pitch: "dropbox", name: "folder-sync" },
  { pitch: "elevenlabs", name: "agent" },
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
  startOnLoad: false, securityLevel: "loose", theme: "base", flowchart: { htmlLabels: false, padding: 14 },
  themeVariables: {
    fontFamily: "Barlow, system-ui, sans-serif", fontSize: "16px",
    background: "#ffffff", primaryColor: "#ece7dc", primaryTextColor: "#141414",
    primaryBorderColor: "#b3a996", lineColor: "#141414", secondaryColor: "#ffffff",
    tertiaryColor: "#f6f3ec", clusterBkg: "#f6f3ec", clusterBorder: "#b3a996",
    edgeLabelBackground: "#ffffff", nodeBorder: "#b3a996",
  },
});
window.__render = async (code) => {
  await document.fonts.ready;
  const { svg } = await mermaid.render("m" + Math.random().toString(36).slice(2), code);
  return svg;
};
window.__ready = true;
</script></body>`;

async function main() {
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

  for (const job of RENDER) {
    const code = mermaidOf(job.pitch);
    if (!code) { console.error("no mermaid block in " + job.pitch + ".md"); continue; }
    const out = join(PITCHES, job.pitch, job.name + ".svg");
    let svg;
    try {
      svg = await page.evaluate((c) => window.__render(c), code);
    } catch (e) { console.error(`${job.pitch}/${job.name}: ${e.message}`); continue; }
    writeFileSync(out, svg, "utf8");
    console.log(`${(job.pitch + "/" + job.name + ".svg").padEnd(34)} ${(Buffer.byteLength(svg) / 1024).toFixed(0)} KB`);
  }
  if (errs.length) console.error("page errors:", errs.slice(0, 5));
  await browser.close();
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) await main();
