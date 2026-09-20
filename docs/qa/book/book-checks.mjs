/** Three things a screenshot cannot show: zoom sharpness, scroll keeping, layout shift. */
import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const WEB = "C:/Users/me/trustthemanual/web";
const OUT = process.env.BOOK_OUT || "C:/Users/me/trustthemanual/docs/qa/book";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PUPPETEER =
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const LIVE = "https://mechanica.emilvinu.ch";
const BIKE = "ktm-390-duke-2024";
const JOB = "ktm-390-duke-2024/chain-tension-check";
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
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
      if (url.startsWith("/api/")) {
        const up = await fetch(LIVE + url, { headers: { Accept: "application/json" } });
        const buf = Buffer.from(await up.arrayBuffer());
        res.writeHead(up.status, {
          "Content-Type": up.headers.get("content-type") || "application/json",
          "Content-Length": buf.length,
        });
        res.end(buf);
        return;
      }
      const path = decodeURIComponent(url.split("?")[0]);
      let file = normalize(join(WEB, path));
      if (path.endsWith("/")) file = normalize(join(WEB, path, "index.html"));
      if (!file.startsWith(normalize(WEB)) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("nf");
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
let bad = 0;
const check = (ok, text) => {
  if (!ok) bad += 1;
  console.log(`  ${ok ? "ok" : "!!"} ${text}`);
};

async function main() {
  const { server, port } = await serve();
  const pup = await import(`file:///${PUPPETEER}`);
  const browser = await pup.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars"],
  });
  for (const [name, w, h, dsf, mobile] of [
    ["phone", 390, 844, 3, true],
    ["desktop", 1280, 800, 1, false],
  ]) {
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await page.evaluateOnNewDocument(() => {
      try {
        localStorage.clear();
      } catch {}
    });
    await page.goto(`http://127.0.0.1:${port}/counter/`, { waitUntil: "load", timeout: 60000 });
    await page.waitForFunction(() => document.documentElement.dataset.store, { timeout: 60000 });
    // layout shift: watch the column's height while the sheets rasterise
    await page.evaluate(
      async (bike, job) => {
        window.__shift = 0;
        const bus = await import("/counter/js/bus.js");
        await import("/counter/js/screens/book.js");
        bus.set({ bikeId: bike, jobId: job });
        bus.go("book");
        const tick = () => {
          const col = document.querySelector(".page-col");
          if (col) {
            const now = col.offsetHeight;
            if (window.__lastH != null && window.__lastH !== now) window.__shift += 1;
            window.__lastH = now;
          }
          if (!window.__stop) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      },
      BIKE,
      JOB,
    );
    await page.waitForFunction(() => document.querySelectorAll(".page-sheet.is-ready").length > 1, { timeout: 90000 });
    await sleep(2500);
    const shift = await page.evaluate(() => {
      window.__stop = true;
      return window.__shift;
    });
    check(shift <= 2, `${name} layout shift while rasterising: ${shift} column-height changes`);

    // zoom sharpness: the canvas bitmap must grow with the zoom
    const before = await page.evaluate(() => {
      const c = document.querySelector(".page-sheet.is-ready canvas");
      return { w: c.width, css: Math.round(c.getBoundingClientRect().width) };
    });
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      const b = v.getBoundingClientRect();
      for (let i = 0; i < 3; i++) {
        v.dispatchEvent(
          new WheelEvent("wheel", {
            deltaY: -120,
            ctrlKey: true,
            bubbles: true,
            cancelable: true,
            clientX: b.x + b.width / 2,
            clientY: b.y + b.height / 3,
          }),
        );
      }
    });
    await sleep(2500);
    const after = await page.evaluate(() => {
      const c = document.querySelector(".page-sheet.is-ready canvas");
      return {
        w: c.width,
        css: Math.round(c.getBoundingClientRect().width),
        zoom: getComputedStyle(document.querySelector(".page-col")).transform,
      };
    });
    const ratioBefore = before.w / before.css;
    const ratioAfter = after.w / after.css;
    check(
      ratioAfter > ratioBefore * 0.9,
      `${name} zoom raster: ${before.w}px bitmap over ${before.css}css (${ratioBefore.toFixed(2)}x) -> ` +
        `${after.w}px over ${after.css}css (${ratioAfter.toFixed(2)}x)`,
    );

    // scroll keeping across the all-pages toggle
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      const b = v.getBoundingClientRect();
      v.dispatchEvent(
        new MouseEvent("dblclick", { bubbles: true, cancelable: true, detail: 2, clientX: b.x + 10, clientY: b.y + 10 }),
      );
    });
    await sleep(600);
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      v.scrollTop += 260;
    });
    await sleep(900);
    const was = await page.evaluate(() => {
      const host = document.querySelector(`.page-sheet[data-page="${window.HandyBus.state.page}"]`);
      const v = document.querySelector(".page-view");
      const top = host.getBoundingClientRect().top - v.getBoundingClientRect().top + v.scrollTop;
      return { page: window.HandyBus.state.page, f: +((v.scrollTop - top) / host.offsetHeight).toFixed(3) };
    });
    await page.evaluate(() => document.querySelector(".book-all")?.click());
    await sleep(1600);
    const now = await page.evaluate(() => {
      const host = document.querySelector(`.page-sheet[data-page="${window.HandyBus.state.page}"]`);
      const v = document.querySelector(".page-view");
      if (!host) return null;
      const top = host.getBoundingClientRect().top - v.getBoundingClientRect().top + v.scrollTop;
      return { page: window.HandyBus.state.page, f: +((v.scrollTop - top) / host.offsetHeight).toFixed(3) };
    });
    check(
      now && now.page === was.page && Math.abs(now.f - was.f) < 0.06,
      `${name} all-pages toggle keeps the place: p.${was.page}+${was.f} -> p.${now && now.page}+${now && now.f}`,
    );

    mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: join(OUT, `${name}-16-checks.png`) });
    await page.close();
  }
  await browser.close();
  server.close();
  console.log(`\n${bad ? bad + " FAILED" : "all checks passed"}`);
  process.exitCode = bad ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
