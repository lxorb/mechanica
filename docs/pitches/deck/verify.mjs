#!/usr/bin/env node
/**
 * Opens every built deck in headless Chrome, fails on a console error, and writes
 * docs/pitches/deck/shots/<pitch>-01.png (slide 1) and <pitch>-big.png (the biggest number slide).
 *
 *   node docs/pitches/deck/verify.mjs            # all
 *   node docs/pitches/deck/verify.mjs openai 3   # one deck, plus slide 3 as an extra shot
 */
import { readdirSync, existsSync, mkdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = join(HERE, "shots");
const PUP = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const args = process.argv.slice(2);
const only = args.filter((a) => !/^\d+$/.test(a));
const extra = args.filter((a) => /^\d+$/.test(a)).map(Number);

mkdirSync(SHOTS, { recursive: true });
const decks = readdirSync(HERE).filter((f) => f.endsWith(".html") && f !== "index.html").sort();
const puppeteer = await import(pathToFileURL(PUP).href);
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new", protocolTimeout: 180000,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars", "--force-color-profile=srgb"],
  defaultViewport: { width: 1600, height: 900, deviceScaleFactor: 1 },
});

let bad = 0;
for (const file of ["index.html", ...decks]) {
  const pitch = file.replace(/\.html$/, "");
  if (only.length && pitch !== "index" && !only.includes(pitch)) continue;
  const page = await browser.newPage();
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("requestfailed", (r) => errs.push("requestfailed " + r.url().slice(0, 80)));
  await page.goto(pathToFileURL(join(HERE, file)).href, { waitUntil: "networkidle0", timeout: 120000 });
  await new Promise((r) => setTimeout(r, 900));

  const mb = (statSync(join(HERE, file)).size / 1048576).toFixed(2);
  if (pitch === "index") {
    await page.screenshot({ path: join(SHOTS, "index.png"), fullPage: false });
  } else {
    const info = await page.evaluate(() => {
      const s = [...document.querySelectorAll("#stage .slide")];
      // the biggest number slide = the one whose largest glyph run is tallest
      let best = 0, bestSize = -1;
      s.forEach((el, i) => {
        const n = el.querySelector(".huge, .s-numbers .big, .panel-value");
        if (!n) return;
        const size = parseFloat(getComputedStyle(n).fontSize) || 0;
        if (size > bestSize) { bestSize = size; best = i; }
      });
      return { n: s.length, big: best, bigSize: bestSize };
    });
    for (const [name, idx] of [["01", 0], ["big", info.big], ...extra.map((e) => [String(e).padStart(2, "0"), e - 1])]) {
      await page.evaluate((i) => { location.hash = "#" + (i + 1); }, idx);
      await new Promise((r) => setTimeout(r, 450));
      await page.screenshot({ path: join(SHOTS, `${pitch}-${name}.png`) });
    }
    console.log(`${pitch.padEnd(15)} ${String(info.n).padStart(2)} slides  ${mb.padStart(5)} MB  biggest-number slide ${info.big + 1} @${info.bigSize}px  errors ${errs.length}`);
  }
  if (errs.length) { bad++; console.error("  ! " + errs.slice(0, 4).join("\n  ! ")); }
  await page.close();
}
await browser.close();
if (bad) process.exitCode = 1;
