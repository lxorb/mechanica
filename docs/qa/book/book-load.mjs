/**
 * The reader's loading states, on a cold cache and a throttled link.
 *   node book-load.mjs            # slow 3G, phone + desktop
 *   node book-load.mjs --fail     # the PDF 502s: the quiet failure + tap-to-retry
 */

import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const WEB = "C:/Users/me/trustthemanual/web";
const OUT = process.env.BOOK_OUT || "C:/Users/me/trustthemanual/docs/qa/book";
const CHROME = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PUPPETEER =
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const LIVE = "https://mechanica.emilvinu.ch";
const WHOLE = process.argv.includes("--whole");
const FAIL = process.argv.includes("--fail");
const BIKE = "ktm-390-duke-2024";
const JOB = "ktm-390-duke-2024/chain-tension-check";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
};

function serve() {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const url = req.url || "/";
      // One whole-file, Content-Length-known, trickled copy of the PDF, so the ring has a real
      // percentage to show. Azure serves Range requests, and pdf.js then pulls a few chunks and
      // never reports a whole-file total - correct, but it exercises only the spin.
      if (url.startsWith("/blob-slow/")) {
        try {
          const up = await fetch(decodeURIComponent(url.slice("/blob-slow/".length)));
          const buf = Buffer.from(await up.arrayBuffer());
          res.writeHead(200, { "Content-Type": "application/pdf", "Content-Length": buf.length });
          const step = 220_000;
          for (let i = 0; i < buf.length; i += step) {
            res.write(buf.subarray(i, i + step));
            await new Promise((r) => setTimeout(r, 90));
          }
          res.end();
        } catch (e) {
          res.writeHead(502).end(String(e));
        }
        return;
      }
      if (url.startsWith("/api/")) {
        try {
          const up = await fetch(LIVE + url, { headers: { Accept: "application/json" } });
          let buf = Buffer.from(await up.arrayBuffer());
          if ((WHOLE || FAIL) && url.indexOf("/api/manuals/") === 0) {
            try {
              const j = JSON.parse(buf.toString("utf8"));
              if (FAIL && j && j.file) j.file = "/no-such-manual.pdf";
              if (j && j.file) j.file = "/blob-slow/" + encodeURIComponent(j.file);
              buf = Buffer.from(JSON.stringify(j));
            } catch {}
          }
          res.writeHead(up.status, {
            "Content-Type": up.headers.get("content-type") || "application/json",
            "Content-Length": buf.length,
          });
          res.end(buf);
        } catch (e) {
          res.writeHead(502).end(String(e));
        }
        return;
      }
      const path = decodeURIComponent(url.split("?")[0]);
      let file = normalize(join(WEB, path));
      if (path.endsWith("/")) file = normalize(join(WEB, path, "index.html"));
      if (!file.startsWith(normalize(WEB)) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
        "Content-Length": statSync(file).size,
        "Cache-Control": "no-store",
      });
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PROBE = () => {
  const load = document.querySelector(".page-load");
  const sheet = document.querySelector(".page-sheet");
  const bar = document.querySelector(".book-bar");
  const b = bar ? bar.getBoundingClientRect() : null;
  return {
    bar: b ? `${b.height}x${Math.round(b.width)}` : "-",
    title: document.querySelector(".book-title")?.textContent || "",
    stamp: document.querySelector(".book-stamp")?.hidden === false
      ? document.querySelector(".book-stamp").textContent
      : "-",
    ring: load ? (load.classList.contains("is-failed") ? "FAILED" : load.classList.contains("is-known") ? "known" : "spin") : "-",
    pct: document.querySelector(".viewer3d-load-pct")?.textContent || "",
    sheets: document.querySelectorAll(".page-sheet").length,
    ready: document.querySelectorAll(".page-sheet.is-ready").length,
    skeletonPaper: sheet ? getComputedStyle(sheet).backgroundColor : "",
    anim: sheet ? getComputedStyle(sheet).animationName : "",
  };
};

async function main() {
  const fail = process.argv.includes("--fail");
  const { server, port } = await serve();
  const pup = await import(`file:///${PUPPETEER}`);
  const browser = await pup.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars"],
  });
  mkdirSync(OUT, { recursive: true });
  for (const [name, w, h, dsf, mobile] of [
    ["phone", 390, 844, 3, true],
    ["desktop", 1280, 800, 1, false],
  ]) {
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await page.setCacheEnabled(false);
    let pdfHits = 0;
    page.on("request", (r) => { if (/no-such-manual|.pdf/i.test(r.url())) pdfHits += 1; });
    const client = await page.createCDPSession();
    await client.send("Network.clearBrowserCache");
    if (fail) {
      await page.setRequestInterception(true);
      page.on("request", (r) => {
        if (/\.pdf(\?|$)/i.test(r.url())) r.respond({ status: 502, body: "no" });
        else r.continue();
      });
    }
    // boot on a normal link, then throttle before the PDF is asked for
    await page.goto(`http://127.0.0.1:${port}/counter/`, { waitUntil: "load", timeout: 60000 });
    await page.waitForFunction(() => document.documentElement.dataset.store, { timeout: 60000 });
    await page.emulateNetworkConditions({
      offline: false,
      download: 400 * 1024 / 8, // ~400 kbit/s, slow 3G
      upload: 400 * 1024 / 8,
      latency: 400,
    });
    await page.evaluate(
      async (bike, job) => {
        await import("/counter/js/screens/book.js");
        const bus = await import("/counter/js/bus.js");
        bus.set({ bikeId: bike, jobId: job });
        bus.go("book");
      },
      BIKE,
      JOB,
    );
    const tag = fail ? "fail" : WHOLE ? "whole" : "slow";
    for (const [label, wait] of [["a", 700], ["b", 1800], ["c", 2500], ["d", 30000]]) {
      await sleep(wait);
      const p = await page.evaluate(PROBE);
      await page.screenshot({ path: join(OUT, `${name}-load-${tag}-${label}.png`) });
      console.log(
        `  ${name.padEnd(8)} ${tag}-${label} bar=${p.bar} ring=${String(p.ring).padEnd(6)} pct=${(p.pct || "-").padEnd(5)} ` +
        `sheets=${p.ready}/${p.sheets} anim=${p.anim} title="${p.title.slice(0, 26)}" stamp=${p.stamp}`,
      );
    }
    if (FAIL) {
      // the retry is the whole error affordance: a tap must put the ring back to work
      const before = await page.evaluate(() => document.querySelector(".page-load.is-failed") ? "failed" : "-");
      const hitsBefore = pdfHits;
      await page.evaluate(async () => {
        const pdf = await import("/counter/js/pdf.js");
        const url = document.querySelector(".book-title") ? window.__pdfUrl : null;
        window.__seq = [];
        window.__pdf = pdf;
      });
      await page.evaluate(async () => {
        const pdf = window.__pdf;
        // the reader's own file url, read back off the manual the adapter cached
        const Q = window.Q;
        const m = await Q.manual("ktm-390-duke-2024-om-en");
        window.__off = pdf.onDoc(Q.asset(m.file), (s) => window.__seq.push(s.status));
      });
      await page.evaluate(() => document.querySelector(".page-load")?.click());
      await sleep(400);
      const after = await page.evaluate(() => ({
        failed: Boolean(document.querySelector(".page-load.is-failed")),
        stalled: Boolean(document.querySelector(".page-sheet.is-stalled")),
        ring: Boolean(document.querySelector(".page-load")),
      }));
      console.log("  " + name.padEnd(8) + " retry     was=" + before + " -> ring=" + after.ring + " failed=" + after.failed + " stalled=" + after.stalled + " requests " + hitsBefore + "->" + pdfHits + " seq=" + (await page.evaluate(() => (window.__seq || []).join(">"))));
    }
    await page.emulateNetworkConditions(null);
    await page.close();
  }
  await browser.close();
  server.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
