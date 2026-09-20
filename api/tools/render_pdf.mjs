/**
 * Print one assembled HTML file to one A4 PDF with headless Chrome.
 *
 *   node api/tools/render_pdf.mjs <input.html> <output.pdf> "<footer line>"
 *
 * Called by api/tools/render_html_manual.py — see that file for what the input looks like and why
 * this exists at all: several manufacturers publish the owner's manual only as an online reader,
 * and /ingest takes PDFs. Chrome is the only thing that turns their own HTML into a page-faithful
 * PDF **with a real text layer**, which is what the ingest pipeline needs; an image of the page
 * would be useless to it.
 *
 * The input is loaded as a file:// URL rather than set with page.setContent so that the images
 * inside it — which are absolute URLs on the publisher's CDN — load exactly as they do in the
 * publisher's own reader. `networkidle0` then waits for them.
 *
 * The footer line is the provenance and it is printed on every page: the official source URL and
 * the date it was fetched. It is passed in rather than built here so that the Python side owns
 * what a row claims about itself.
 *
 * puppeteer-core resolves from the repo's own node_modules; Chrome is CHROME_PATH or the usual
 * Windows install. Neither is bundled, and both are checked with a clear error rather than a stack.
 */

import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

const [input, output, footer = ""] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: render_pdf.mjs <input.html> <output.pdf> [footer]");
  process.exit(2);
}

const chrome = CHROME_CANDIDATES.find((p) => existsSync(p));
if (!chrome) {
  console.error(`no Chrome found. Set CHROME_PATH. Tried:\n  ${CHROME_CANDIDATES.join("\n  ")}`);
  process.exit(3);
}

let puppeteer;
try {
  puppeteer = (await import("puppeteer-core")).default;
} catch {
  console.error("puppeteer-core is not installed. From the repo root: npm i -D puppeteer-core");
  process.exit(4);
}

const escape = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const FOOT = `
  <div style="width:100%;font-size:7px;font-family:Arial,sans-serif;color:#555;
              padding:0 12mm;display:flex;justify-content:space-between;gap:8px;">
    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%">${escape(footer)}</span>
    <span><span class="pageNumber"></span>/<span class="totalPages"></span></span>
  </div>`;

// A 200-section manual with hundreds of figures takes minutes to lay out and print, and
// puppeteer's default protocolTimeout is 180 s - which is what "Page.printToPDF timed out" means.
const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: "new",
  protocolTimeout: 1_800_000,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
});
try {
  const page = await browser.newPage();
  page.setDefaultNavigationTimeout(180000);
  // A missing image must not fail the print: the manual's text is the part /ingest needs.
  page.on("requestfailed", (r) => console.error(`  asset failed: ${r.url().slice(0, 120)}`));
  // `load` plus a settle window, not networkidle0: a manual pulls hundreds of CDN images and the
  // network never goes fully idle for the two seconds networkidle0 insists on.
  await page.goto(pathToFileURL(resolve(input)).href, { waitUntil: "load", timeout: 300000 });
  await page.evaluate(async () => {
    await Promise.all([...document.images].filter((i) => !i.complete).map((i) =>
      new Promise((done) => { i.addEventListener("load", done, { once: true }); i.addEventListener("error", done, { once: true }); })));
  });
  await page.emulateMediaType("print");
  await page.pdf({
    path: resolve(output),
    format: "A4",
    printBackground: true,
    preferCSSPageSize: false,
    margin: { top: "14mm", bottom: "16mm", left: "14mm", right: "14mm" },
    displayHeaderFooter: true,
    headerTemplate: "<span></span>",
    footerTemplate: FOOT,
    timeout: 1_500_000,
  });
} finally {
  await browser.close();
}
console.log(`wrote ${output}`);
