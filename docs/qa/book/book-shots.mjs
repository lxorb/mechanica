/**
 * Book-screen harness. Serves web/ locally with /api proxied to the live worker, drives the
 * reader headlessly at three viewports and photographs every state of the top bar.
 *
 *   node book-shots.mjs            # all viewports, all states
 *   node book-shots.mjs phone      # one viewport
 */

import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = "C:/Users/me/trustthemanual/web";
const OUT = process.env.BOOK_OUT || "C:/Users/me/trustthemanual/docs/qa/book";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const LIVE = "https://mechanica.emilvinu.ch";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".pdf": "application/pdf",
  ".glb": "model/gltf-binary",
  ".bin": "application/octet-stream",
};

/** Static web/ + /api -> the live worker (same origin, so no CORS in the page). */
function serve() {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const url = req.url || "/";
      if (url.startsWith("/api/")) {
        try {
          const headers = { Accept: "application/json" };
          if (req.headers.range) headers.Range = req.headers.range;
          const up = await fetch(LIVE + url, { headers });
          const buf = Buffer.from(await up.arrayBuffer());
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
      // pdf.js pulls the manual straight off Azure blob storage; proxy it so Range works
      // and the page never crosses an origin.
      if (url.startsWith("/blob/")) {
        try {
          const headers = {};
          if (req.headers.range) headers.Range = req.headers.range;
          const up = await fetch(decodeURIComponent(url.slice("/blob/".length)), { headers });
          const buf = Buffer.from(await up.arrayBuffer());
          const out = {
            "Content-Type": up.headers.get("content-type") || "application/pdf",
            "Content-Length": buf.length,
            "Accept-Ranges": "bytes",
          };
          if (up.headers.get("content-range")) out["Content-Range"] = up.headers.get("content-range");
          res.writeHead(up.status, out);
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

const BIKE = "ktm-390-duke-2024";
const JOB = "ktm-390-duke-2024/chain-tension-check"; // p.77-78, 4 highlights

const VIEWPORTS = [
  ["phone", 390, 844, 3, true],
  ["tablet", 768, 1024, 2, true],
  ["desktop", 1280, 800, 1, false],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Everything about the bar, measured in the page, so a regression is a number not a picture. */
const PROBE = () => {
  const root = document.querySelector('section[data-screen="book"] [data-root]');
  const bar = document.querySelector(".book-bar");
  const view = document.querySelector(".page-view");
  const strip = document.querySelector(".page-strip");
  const col = document.querySelector(".page-col");
  const title = document.querySelector(".book-title");
  const stamp = document.querySelector(".book-stamp");
  const r = (el) => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { x: +b.x.toFixed(1), y: +b.y.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1) };
  };
  const barBox = r(bar);
  const kids = bar
    ? [...bar.children].filter((n) => !n.hidden).map((n) => {
        const b = n.getBoundingClientRect();
        return {
          cls: n.className,
          x: +b.x.toFixed(1),
          right: +b.right.toFixed(1),
          w: +b.width.toFixed(1),
          h: +b.height.toFixed(1),
          clipped: barBox ? b.right > barBox.x + barBox.w + 0.5 || b.x < barBox.x - 0.5 : false,
        };
      })
    : [];
  const topAt = barBox
    ? document.elementFromPoint(Math.min(innerWidth - 2, barBox.x + barBox.w / 2), barBox.y + barBox.h / 2)
    : null;
  return {
    hasBar: Boolean(bar),
    barVisible: Boolean(bar && bar.offsetParent !== null && barBox.h > 0),
    bar: barBox,
    barOverflow: bar ? bar.scrollWidth - bar.clientWidth : -1,
    kids,
    clipped: kids.filter((k) => k.clipped).map((k) => k.cls),
    topmostOverBar: topAt ? topAt.className || topAt.tagName : null,
    title: title ? title.textContent : null,
    stamp: stamp && !stamp.hidden ? stamp.textContent : null,
    stampHidden: stamp ? stamp.hidden : null,
    view: r(view),
    strip: r(strip),
    stripVisible: Boolean(strip && strip.offsetParent !== null),
    rootH: root ? +root.getBoundingClientRect().height.toFixed(1) : null,
    innerH: innerHeight,
    scrollH: document.scrollingElement.scrollHeight,
    viewScrollW: view ? view.scrollWidth : -1,
    viewClientW: view ? view.clientWidth : -1,
    hOverflow: view ? view.scrollWidth - view.clientWidth : -1,
    sheetW: col ? getComputedStyle(col).getPropertyValue("--sheet-w") : "",
    colTransform: col ? getComputedStyle(col).transform : "",
    sheets: document.querySelectorAll(".page-sheet").length,
    ready: document.querySelectorAll(".page-sheet.is-ready").length,
    marks: document.querySelectorAll(".mark").length,
    zoomed: Boolean(view && view.classList.contains("zoomed")),
    small: [...document.querySelectorAll(".book-bar button, .book-acts button, .strip-chip")]
      .filter((n) => !n.hidden && n.offsetParent !== null)
      .map((n) => { const b = n.getBoundingClientRect(); return { cls: n.className, w: Math.round(b.width), h: Math.round(b.height) }; })
      .filter((t) => t.w < 43.5 || t.h < 43.5),
    ringPct: (document.querySelector(".viewer3d-load-pct") || {}).textContent || "",
    ringOn: Boolean(document.querySelector(".page-load")),
    ringFailed: Boolean(document.querySelector(".page-load.is-failed")),
    skeletons: document.querySelectorAll(".page-sheet:not(.is-ready)").length,
    immersive: Boolean(root && root.classList.contains("immersive")),
  };
};

async function shot(page, name, vp) {
  mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: join(OUT, `${vp}-${name}.png`) });
}

function line(vp, name, p) {
  const bad = [];
  if (!p.barVisible) bad.push("BAR HIDDEN");
  if (p.clipped.length) bad.push("clipped:" + p.clipped.join(","));
  if (p.barOverflow > 0) bad.push("barOverflow:" + p.barOverflow);
  if (!p.zoomed && p.hOverflow > 1) bad.push("hScroll:" + p.hOverflow);
  if (p.small && p.small.length) bad.push("under44:" + p.small.map((t) => t.cls.split(" ").pop() + t.w + "x" + t.h).join(","));
  if (p.bar && p.bar.y < -0.5) bad.push("barY:" + p.bar.y);
  const booting = p.ringOn && p.ready === 0;
  if (!booting && p.sheets > 0 && !p.stamp) bad.push("no stamp");
  if (!booting && !p.title) bad.push("no title");
  return (
    `  ${bad.length ? "!!" : "ok"} ${vp.padEnd(8)} ${name.padEnd(22)} ` +
    `bar=${p.bar ? `${p.bar.y}+${p.bar.h}x${p.bar.w}` : "-"} ` +
    `title="${String(p.title).slice(0, 22)}" stamp="${p.stamp || "-"}" ` +
    `sheets=${p.ready}/${p.sheets} marks=${p.marks} ring=${p.ringOn?(p.ringFailed?"fail":(p.ringPct||"spin")):"-"} ` +
    `${bad.length ? "<< " + bad.join(" | ") : ""}`
  );
}

async function enterBook(page, port) {
  await page.goto(`http://127.0.0.1:${port}/counter/`, { waitUntil: "load", timeout: 45000 });
  await page.waitForFunction(() => document.documentElement.dataset.store, { timeout: 45000 });
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
}

async function run(only) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars", "--allow-insecure-localhost"],
  });
  mkdirSync(OUT, { recursive: true });
  const rows = [];
  let bad = 0;
  const say = (vp, name, p) => {
    const text = line(vp, name, p);
    console.log(text);
    rows.push({ vp, name, p });
    if (text.startsWith("  !!")) bad += 1;
  };

  for (const [vp, w, h, dsf, mobile] of VIEWPORTS) {
    if (only.length && !only.includes(vp)) continue;
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    const errs = [];
    page.on("pageerror", (e) => errs.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error" && !/favicon|fonts\.g|404/.test(m.text())) errs.push(m.text());
    });

    await enterBook(page, port);
    await sleep(600);
    say(vp, "01-entered", await page.evaluate(PROBE));
    await shot(page, "01-entered", vp);

    await page.waitForFunction(() => document.querySelectorAll(".page-sheet.is-ready").length > 0, { timeout: 60000 }).catch(() => {});
    await sleep(900);
    say(vp, "02-rendered", await page.evaluate(PROBE));
    await shot(page, "02-rendered", vp);

    // scroll down a page
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      v.scrollTop = v.scrollHeight * 0.55;
    });
    await sleep(900);
    say(vp, "03-scrolled", await page.evaluate(PROBE));
    await shot(page, "03-scrolled", vp);

    // all-pages toggle
    await page.evaluate(() => document.querySelector(".book-all")?.click());
    await sleep(1400);
    say(vp, "04-allpages", await page.evaluate(PROBE));
    await shot(page, "04-allpages", vp);

    // a page jump from the strip (far page)
    await page.evaluate(() => {
      const chips = [...document.querySelectorAll(".strip-chip")];
      (chips[chips.length - 1] || chips[0])?.click();
    });
    await sleep(1400);
    say(vp, "05-jumped", await page.evaluate(PROBE));
    await shot(page, "05-jumped", vp);

    // zoom in (ctrl+wheel path, works on every viewport)
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      const b = v.getBoundingClientRect();
      v.dispatchEvent(new WheelEvent("wheel", {
        deltaY: -240, ctrlKey: true, bubbles: true, cancelable: true,
        clientX: b.x + b.width / 2, clientY: b.y + b.height / 3,
      }));
    });
    await sleep(900);
    say(vp, "06-zoomed", await page.evaluate(PROBE));
    await shot(page, "06-zoomed", vp);

    // scrolled while zoomed
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      v.scrollTop += 500;
      v.scrollLeft += 120;
    });
    await sleep(700);
    say(vp, "07-zoom-scroll", await page.evaluate(PROBE));
    await shot(page, "07-zoom-scroll", vp);

    // back to fit
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      const b = v.getBoundingClientRect();
      v.dispatchEvent(new MouseEvent("dblclick", {
        bubbles: true, cancelable: true, detail: 2,
        clientX: b.x + b.width / 2, clientY: b.y + b.height / 3,
      }));
    });
    await sleep(700);
    say(vp, "08-unzoomed", await page.evaluate(PROBE));
    await shot(page, "08-unzoomed", vp);

    // a single tap/click on the page (the immersive trap)
    await page.evaluate(() => {
      const v = document.querySelector(".page-view");
      const b = v.getBoundingClientRect();
      const at = { clientX: b.x + b.width / 2, clientY: b.y + b.height / 2, bubbles: true, cancelable: true };
      if ("ontouchstart" in window) {
        const t = (x, y) => new Touch({ identifier: 1, target: v, clientX: x, clientY: y });
        const one = [t(at.clientX, at.clientY)];
        v.dispatchEvent(new TouchEvent("touchstart", { touches: one, targetTouches: one, changedTouches: one, bubbles: true, cancelable: true }));
        v.dispatchEvent(new TouchEvent("touchend", { touches: [], targetTouches: [], changedTouches: one, bubbles: true, cancelable: true }));
      }
      v.dispatchEvent(new MouseEvent("click", { ...at, detail: 1 }));
    });
    await sleep(700);
    say(vp, "09-after-tap", await page.evaluate(PROBE));
    await shot(page, "09-after-tap", vp);

    // rotate (landscape) and back
    await page.setViewport({ width: h, height: w, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await sleep(1200);
    say(vp, "10-rotated", await page.evaluate(PROBE));
    await shot(page, "10-rotated", vp);
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await sleep(900);
    say(vp, "11-unrotated", await page.evaluate(PROBE));
    await shot(page, "11-unrotated", vp);

    // contents / outline, then back to the pages
    await page.evaluate(() => document.querySelector(".book-cover")?.click());
    await sleep(600);
    say(vp, "12-contents", await page.evaluate(PROBE));
    await shot(page, "12-contents", vp);
    await page.evaluate(() => document.querySelector(".toc-row")?.click());
    await sleep(1400);
    say(vp, "13-chapter", await page.evaluate(PROBE));
    await shot(page, "13-chapter", vp);

    // markers: same fractions of the sheet at every width, before and after a rotation
    const markAt = async () =>
      page.evaluate(() => {
        const host = document.querySelector('.page-sheet[data-page="77"]');
        const m = host && host.querySelector(".mark");
        if (!m) return null;
        const a = host.getBoundingClientRect();
        const b = m.getBoundingClientRect();
        return {
          x: +((b.x - a.x) / a.width).toFixed(4),
          y: +((b.y - a.y) / a.height).toFixed(4),
          w: +(b.width / a.width).toFixed(4),
          h: +(b.height / a.height).toFixed(4),
          sheet: Math.round(a.width),
        };
      });
    await page.evaluate(() => document.querySelector('.strip-chip[data-page="77"]')?.click());
    await sleep(1600);
    const mk1 = await markAt();
    say(vp, "14-marks", await page.evaluate(PROBE));
    await shot(page, "14-marks", vp);
    await page.setViewport({ width: h, height: w, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await sleep(1600);
    const mk2 = await markAt();
    await shot(page, "15-marks-rotated", vp);
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, hasTouch: mobile, isMobile: mobile });
    await sleep(900);
    const same = mk1 && mk2 && ["x", "y", "w", "h"].every((k) => Math.abs(mk1[k] - mk2[k]) < 0.004);
    console.log(
      `  ${same ? "ok" : "!!"} ${vp.padEnd(8)} 15-marks-rotated      ` +
        `p77 mark ${JSON.stringify(mk1)} -> ${JSON.stringify(mk2)}`,
    );
    if (!same) bad += 1;

    if (errs.length) console.log(`     errors(${vp}): ${errs.slice(0, 3).join(" | ").slice(0, 300)}`);
    await page.close();
  }

  await browser.close();
  server.close();
  console.log(`\n${rows.length} states · ${bad} flagged · shots in ${OUT}`);
  process.exitCode = bad ? 1 : 0;
}

run(process.argv.slice(2).filter((a) => !a.startsWith("--"))).catch((e) => {
  console.error(e);
  process.exit(1);
});
