/**
 * UI bug hunt — the regression list for docs/qa/BUGS-UI.md. Owner: bughunt-UI agent.
 *
 *   node web/tools/bughunt-ui.mjs                 # every check, phone viewport
 *   node web/tools/bughunt-ui.mjs --view desk     # 1280x800
 *   node web/tools/bughunt-ui.mjs --only cost     # one check by name fragment
 *   node web/tools/bughunt-ui.mjs --only themes   # the five-theme walk (opt-in, ~6 min)
 *
 * Every line is one fixed bug: it fails on the code as it was and passes on the code as it
 * is. Serves web/ on a throwaway port with /api/* proxied to the live worker (bodies and
 * all), so the walk runs on real manuals with local files. `--kill` inside a check cuts the
 * API off at the proxy, which is how the error states are exercised.
 *
 * Pairs with docs/qa/book/book-shots.mjs and web/tools/theme-shots.mjs; those two stay the
 * source of truth for the reader and for the themes, this one for everything else.
 */

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const SCRATCH = "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad";
const PUPPETEER = process.env.PUPPETEER_DIR || `${SCRATCH}/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`;
const UPSTREAM = process.env.TTM_API || "https://mechanica.emilvinu.ch";
/** A vehicle whose manual is indexed, and one whose manual is not in English. */
const BIKE = "ktm-390-duke-2024";
const FOREIGN = "triumph tt600";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".bin": "application/octet-stream",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".pdf": "application/pdf",
  ".hdr": "image/vnd.radiance",
  ".wasm": "application/wasm",
  ".ico": "image/x-icon",
};

const nap = (ms) => new Promise((r) => setTimeout(r, ms));

function serve(state) {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const url = req.url || "/";
      if (url.startsWith("/api/") || url.startsWith("/ws/")) {
        if (state.kill) {
          res.writeHead(503, { "Access-Control-Allow-Origin": "*" }).end("{}");
          return;
        }
        try {
          const chunks = [];
          for await (const c of req) chunks.push(c);
          const up = await fetch(`${UPSTREAM}${url}`, {
            method: req.method,
            headers: {
              Accept: req.headers.accept || "*/*",
              ...(req.headers["content-type"] ? { "Content-Type": req.headers["content-type"] } : {}),
            },
            body: chunks.length ? Buffer.concat(chunks) : undefined,
          });
          const body = Buffer.from(await up.arrayBuffer());
          res.writeHead(up.status, {
            "Content-Type": up.headers.get("content-type") || "application/json",
            "Access-Control-Allow-Origin": "*",
          });
          res.end(body);
        } catch {
          res.writeHead(502, { "Access-Control-Allow-Origin": "*" }).end("{}");
        }
        return;
      }
      const path = decodeURIComponent(url.split("?")[0]);
      const file = normalize(join(WEB, path.endsWith("/") ? join(path, "index.html") : path));
      if (!file.startsWith(WEB) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
        "Content-Length": statSync(file).size,
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
      });
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

const VIEWS = {
  phone: { width: 390, height: 844, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  tab: { width: 768, height: 1024, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  desk: { width: 1280, height: 800, deviceScaleFactor: 1 },
};

/**
 * Geometry audit. `offscreen` ignores anything a clipping ancestor already cuts off — an
 * ellipsised title has children wider than the screen by design and that is not a bug.
 */
const AUDIT = () => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const out = { overflowX: Math.max(0, document.documentElement.scrollWidth - vw), offscreen: [], spill: [], small: [] };
  const nm = (el) => el.tagName.toLowerCase() + (typeof el.className === "string" && el.className ? "." + el.className.split(/\s+/)[0] : "");
  const clipped = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.overflow !== "visible" || cs.overflowX !== "visible") return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.top > vh + 600 || r.bottom < -600) continue;
    if ((r.right > vw + 1 || r.left < -1) && !clipped(el)) out.offscreen.push(`${nm(el)} ${Math.round(r.left)}..${Math.round(r.right)}/${vw}`);
    if (!el.children.length && el.textContent.trim() && cs.overflow === "visible"
      && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && !clipped(el)) {
      out.spill.push(`${nm(el)} ${el.scrollWidth}>${el.clientWidth}`);
    }
    const tag = el.tagName.toLowerCase();
    const hit = tag === "button" || tag === "a" || el.getAttribute("role") === "button";
    if (hit && !el.disabled && r.top < vh && r.bottom > 0 && (r.width < 43.5 || r.height < 43.5)) {
      out.small.push(`${nm(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }
  for (const k of ["offscreen", "spill", "small"]) out[k] = [...new Set(out[k])].slice(0, 6);
  return out;
};

async function auditFaults(page) {
  const geo = await page.evaluate(AUDIT);
  const bad = [];
  if (geo.overflowX > 1) bad.push(`h-scroll +${geo.overflowX}px`);
  if (geo.offscreen.length) bad.push(`offscreen ${geo.offscreen.join(", ")}`);
  if (geo.spill.length) bad.push(`spill ${geo.spill.join(", ")}`);
  if (geo.small.length) bad.push(`under 44px: ${geo.small.join(", ")}`);
  return bad;
}

/* ------------------------------------------------------------------ the walk */

async function landing(page, base) {
  await page.goto(`${base}/counter/`, { waitUntil: "load", timeout: 45000 });
  await page.waitForSelector("[data-screen='identify'] .id-q", { timeout: 30000 });
  await nap(1200);
}

/** Straight to Pick on the demo bike, without paying for the Identify walk every time. */
async function toPick(page, base) {
  await landing(page, base);
  await page.evaluate(async (id) => {
    const bus = await import("/counter/js/bus.js");
    bus.set({ bikeId: id });
    bus.go("pick");
  }, BIKE);
  await page.waitForSelector("[data-screen='pick'] .hit", { timeout: 45000 });
  await nap(1500);
}

async function toBook(page, base, { synthetic = true } = {}) {
  await toPick(page, base);
  if (!synthetic) {
    await page.type("[data-screen='pick'] .ask-q", "cleaning the chain", { delay: 20 });
    await nap(1000);
  }
  await page.evaluate(() => document.querySelector("[data-screen='pick'] .hit-go")?.click());
  await nap(500);
  await page.evaluate(() => document.querySelector("[data-screen='pick'] .open")?.click());
  await page.waitForFunction(() => document.body.getAttribute("data-here") === "book", { timeout: 45000 });
  await page.waitForSelector("[data-screen='book'] .page-sheet.is-ready", { timeout: 60000 }).catch(() => {});
  await nap(1500);
}

async function toParts(page, base) {
  await toBook(page, base);
  await page.evaluate(() => document.querySelector(".book-parts")?.click());
  await page.waitForSelector(".pv-sheet .pv-tile", { timeout: 45000 });
  await nap(1200);
}

/* ------------------------------------------------------------------ checks */

const CHECKS = [
  ["bus: an open overlay keeps its history entry", async (page, base) => {
    await toParts(page, base);
    await page.evaluate(() => document.querySelector(".pv-tile")?.click());
    await nap(1200);
    const detail = await page.evaluate(() => ({ hash: location.hash, view: document.querySelector('[data-overlay="invoice"] [data-root]').getAttribute("data-view") }));
    if (detail.view !== "detail") return `detail did not open (${detail.view})`;
    await page.goBack();
    await nap(1000);
    const back1 = await page.evaluate(() => ({
      hash: location.hash,
      open: !document.querySelector('[data-overlay="invoice"]').hidden,
      view: document.querySelector('[data-overlay="invoice"] [data-root]').getAttribute("data-view"),
    }));
    // The bug: replaceState wrote "#book" while Parts was open, throwing the sheet's own
    // entry away, so the next Back did nothing at all.
    if (back1.hash !== "#book+invoice") return `back from detail left ${back1.hash} (want #book+invoice)`;
    if (!back1.open || back1.view !== "grid") return `back from detail did not land on the grid (${back1.view})`;
    await page.goBack();
    await nap(1000);
    const back2 = await page.evaluate(() => ({ hash: location.hash, open: !document.querySelector('[data-overlay="invoice"]').hidden }));
    if (back2.open) return "second back left Parts open";
    if (back2.hash !== "#book") return `second back left ${back2.hash}`;
    return "";
  }],

  ["bus: leaving a screen with an overlay open still walks back", async (page, base) => {
    await toParts(page, base);
    await page.evaluate(async () => { (await import("/counter/js/bus.js")).go("pick"); });
    await nap(800);
    const away = await page.evaluate(() => ({ here: document.body.getAttribute("data-here"), open: !document.querySelector('[data-overlay="invoice"]').hidden }));
    if (away.here !== "pick" || away.open) return `go(pick) left here=${away.here} parts=${away.open}`;
    await page.goBack();
    await nap(1000);
    const one = await page.evaluate(() => ({ hash: location.hash, open: !document.querySelector('[data-overlay="invoice"]').hidden }));
    if (one.hash !== "#book+invoice" || !one.open) return `back landed on ${one.hash}, parts=${one.open}`;
    await page.goBack();
    await nap(1000);
    const two = await page.evaluate(() => ({ hash: location.hash, open: !document.querySelector('[data-overlay="invoice"]').hidden }));
    if (two.open || two.hash !== "#book") return `second back: ${two.hash}, parts=${two.open}`;
    return "";
  }],

  ["cost: a cold load of #cost opens the meter", async (page, base) => {
    await page.goto(`${base}/counter/#cost`, { waitUntil: "load", timeout: 45000 });
    await page.waitForFunction(() => document.querySelector(".cost-veil") && !document.querySelector(".cost-veil").hidden, { timeout: 30000 })
      .catch(() => {});
    const seen = await page.evaluate(() => ({
      hash: location.hash,
      on: Boolean(document.querySelector(".cost-veil")) && !document.querySelector(".cost-veil").hidden,
    }));
    if (!seen.on) return `#cost showed the landing page instead (hash ${seen.hash})`;
    await page.waitForFunction(() => [...document.querySelectorAll(".cost-n")].some((n) => n.textContent !== "—"), { timeout: 40000 })
      .catch(() => {});
    const cells = await page.evaluate(() => [...document.querySelectorAll(".cost-n")].map((n) => n.textContent));
    if (cells.every((c) => c === "—")) return `every cell still "—": ${cells.join(" ")}`;
    return "";
  }],

  ["climate: Conditions is a bottom sheet, not a slab over the reader", async (page, base) => {
    await toBook(page, base);
    await page.evaluate(() => document.querySelector(".book-climate")?.click());
    await page.waitForSelector(".cf-sheet", { timeout: 25000 });
    await nap(1200);
    const box = await page.evaluate(() => {
      const aside = document.querySelector('[data-overlay="conditions"]');
      const r = document.querySelector(".cf-sheet").getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight, cls: aside.className, jc: getComputedStyle(aside).justifyContent };
    });
    if (/\bcv\b/.test(box.cls)) return `the aside still carries chat-ui's cv: "${box.cls}"`;
    if (box.jc !== "flex-end") return `justify-content is ${box.jc}`;
    if (Math.abs(box.bottom - box.vh) > 2) return `sheet sits ${box.top}..${box.bottom} of ${box.vh}`;
    return "";
  }],

  ["pick: the bike chip is a 44 px target", async (page, base) => {
    await toPick(page, base);
    const box = await page.evaluate(() => {
      const r = document.querySelector("[data-screen='pick'] .who").getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    });
    if (box.h < 44) return `.who is ${box.w}x${box.h}`;
    return "";
  }],

  ["pick: leaving mid-load never mounts a second 3D stage", async (page, base) => {
    await landing(page, base);
    await page.evaluate(async (id) => {
      const bus = await import("/counter/js/bus.js");
      bus.set({ bikeId: id });
      bus.go("pick");
    }, BIKE);
    await nap(250);
    await page.evaluate(async () => { (await import("/counter/js/bus.js")).go("confirm"); });
    await nap(6000);
    const n = await page.evaluate(() => document.querySelectorAll("canvas").length);
    if (n > 1) return `${n} canvases alive after leaving Pick mid-load`;
    return "";
  }],

  ["invoice: a dead API ends in shop links, never a stuck skeleton", async (page, base, state) => {
    await toParts(page, base);
    state.kill = true;
    try {
      await page.evaluate(() => document.querySelector(".pv-tile")?.click());
      await nap(9000);
      const seen = await page.evaluate(() => ({
        wait: Boolean(document.querySelector(".pv-wait")),
        rows: document.querySelectorAll(".pv-offer").length,
        pills: document.querySelectorAll(".pv-shop").length,
        name: document.querySelector(".pv-det-name")?.textContent || "",
      }));
      if (!seen.name) return "the detail never painted";
      if (seen.wait) return "the skeleton and its bar are still on screen";
    } finally {
      state.kill = false;
    }
    return "";
  }],

  ["invoice: every page chip is a 44 px target", async (page, base) => {
    await toParts(page, base);
    await page.evaluate(() => document.querySelector(".pv-tile")?.click());
    await nap(2500);
    const small = await page.evaluate(() => [...document.querySelectorAll(".pv-page")]
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width < 43.5 || r.height < 43.5)
      .map((r) => `${Math.round(r.width)}x${Math.round(r.height)}`));
    if (small.length) return `${small.length} chip(s) under 44: ${small.slice(0, 4).join(", ")}`;
    return "";
  }],

  ["book: a reload on an outline heading keeps the reader open", async (page, base) => {
    await toBook(page, base); // the first hit of the contents is a bare heading: a synthetic job
    const before = await page.evaluate(() => ({ here: document.body.getAttribute("data-here"), stamp: document.querySelector(".book-stamp")?.textContent }));
    if (before.here !== "book") return "never reached Book";
    // Twice: app.js::revive() needs the roster to be complete at the instant it runs, so a
    // slow /catalog drops any reload to Identify (UI-H1). That is not this bug — this bug
    // put the reader on Pick with the roster right there. One retry tells the two apart.
    let after = null;
    for (let tries = 0; tries < 2; tries += 1) {
      await page.reload({ waitUntil: "load", timeout: 45000 });
      await nap(6000);
      after = await page.evaluate(() => ({
        here: document.body.getAttribute("data-here"),
        stamp: document.querySelector(".book-stamp")?.textContent || "",
        sheets: document.querySelectorAll(".page-sheet").length,
        roster: window.Q ? window.Q.bikes().length : 0,
      }));
      if (after.here === "book") break;
    }
    if (after.here === "pick") return `the reload dropped to Pick (was ${before.stamp})`;
    if (after.here !== "book") return `the reload dropped to ${after.here}, roster ${after.roster} — see UI-H1`;
    if (!after.sheets) return "Book came back with no page";
    return "";
  }],

  ["index.html: a hanging font CDN cannot blank the app", async (page, base) => {
    await page.setRequestInterception(true);
    const hang = async (r) => {
      if (/fonts\.googleapis|fonts\.gstatic/.test(r.url())) {
        await nap(9000);
        try { await r.abort(); } catch { /* gone */ }
        return;
      }
      try { await r.continue(); } catch { /* gone */ }
    };
    page.on("request", hang);
    try {
      await page.goto(`${base}/counter/`, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
      let fcp = null;
      for (let i = 0; i < 40 && fcp == null; i++) {
        fcp = await page.evaluate(() => {
          const e = performance.getEntriesByType("paint").find((x) => x.name === "first-contentful-paint");
          return e ? Math.round(e.startTime) : null;
        }).catch(() => null);
        if (fcp == null) await nap(150);
      }
      if (fcp == null) return "nothing painted at all";
      if (fcp > 4000) return `first paint waited ${fcp} ms on fonts.googleapis.com`;
    } finally {
      page.off("request", hang);
      await page.setRequestInterception(false);
    }
    return "";
  }],

  ["identify: a non-English manual is tagged, an English one is not", async (page, base) => {
    await landing(page, base);
    await page.type("[data-screen='identify'] .id-q", FOREIGN, { delay: 20 });
    await page.waitForSelector("[data-screen='identify'] .id-card", { timeout: 25000 });
    await nap(1200);
    await page.click("[data-screen='identify'] .id-card");
    await page.waitForSelector("[data-screen='identify'] .id-chooser", { timeout: 20000 });
    await nap(800);
    const chip = await page.evaluate(() => {
      const c = [...document.querySelectorAll(".id-year:not([hidden])")][0];
      return c ? { text: c.textContent, tag: c.querySelector(".id-lang")?.textContent || "", h: Math.round(c.getBoundingClientRect().height) } : null;
    });
    if (!chip) return "no year chips";
    if (!/^[A-Z]{2}$/.test(chip.tag)) return `the year chip carries no language tag (${chip.text})`;
    if (chip.h < 44) return `chip is ${chip.h} px tall`;
    await page.evaluate(() => [...document.querySelectorAll(".id-year:not([hidden])")][0].click());
    await page.waitForFunction(() => document.body.getAttribute("data-here") === "confirm", { timeout: 30000 });
    await nap(1500);
    const stamp = await page.evaluate(() => {
      const el = document.querySelector(".confirm-lang");
      return el && !el.hidden ? el.textContent : "";
    });
    if (!/^[A-Z]{2}$/.test(stamp)) return `Confirm shows no language stamp (got "${stamp}")`;
    // and the English demo bike shows nothing
    await page.evaluate(async (id) => {
      const bus = await import("/counter/js/bus.js");
      bus.set({ bikeId: id });
      bus.go("identify");
      bus.go("confirm");
    }, BIKE);
    await nap(2000);
    const english = await page.evaluate(() => {
      const el = document.querySelector(".confirm-lang");
      return el && !el.hidden ? el.textContent : "";
    });
    if (english) return `an English manual was tagged "${english}"`;
    return "";
  }],

  ["theme: reduced motion skips the crossfade, tokens still swap", async (page, base) => {
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    try {
      await landing(page, base);
      const out = await page.evaluate(async () => {
        const t = await import("/counter/js/theme.js");
        const was = t.current();
        t.cycle();
        return { was, now: t.current(), armed: document.documentElement.hasAttribute("data-swapping") };
      });
      if (out.armed) return "[data-swapping] was armed under prefers-reduced-motion";
      if (out.now === out.was) return "the theme did not change";
    } finally {
      await page.emulateMediaFeatures([]);
    }
    return "";
  }],

  // Opt-in (`--only themes`): ten walks is six minutes. It is theme-shots' two assertions —
  // the theme applies at every stop and the console stays silent — without the twenty
  // full-page WebGL captures that make that tool slow and flaky, plus the two things this
  // pass fixed that a contact sheet cannot see: the Conditions sheet's edge and a cold #cost.
  ["themes: all five survive the walk", async (page, base, state, browser, view) => {
    const faults = [];
    for (const theme of ["workshop", "night", "blueprint", "track", "paper"]) {
      const tab = await browser.newPage();
      await tab.setViewport(view);
      const errs = [];
      tab.on("pageerror", (e) => errs.push(`pageerror: ${e.message.slice(0, 80)}`));
      tab.on("console", (m) => {
        if (m.type() !== "error") return;
        const t = m.text();
        if (/404|favicon|fonts\.g|Failed to load resource|net::ERR/.test(t)) return;
        errs.push(t.slice(0, 80));
      });
      await tab.evaluateOnNewDocument((id) => {
        try { localStorage.setItem("mechanica.theme", id); } catch { /* private */ }
        if (navigator.serviceWorker) navigator.serviceWorker.register = () => Promise.reject(new Error("off"));
      }, theme);
      const seen = [];
      const at = async (label) => {
        seen.push(`${label}:${await tab.evaluate(() => document.documentElement.getAttribute("data-theme"))}`);
      };
      try {
        await tab.goto(`${base}/counter/`, { waitUntil: "load", timeout: 60000 });
        await tab.waitForSelector(".id-q", { timeout: 40000 });
        await at("landing");
        await tab.type(".id-q", "390 duke", { delay: 20 });
        await tab.waitForSelector(".id-card", { timeout: 30000 });
        await nap(500);
        await at("cards");
        await tab.click(".id-card");
        await tab.waitForSelector(".id-chooser", { timeout: 25000 });
        await at("chooser");
        await tab.evaluate(async (id) => {
          const bus = await import("/counter/js/bus.js");
          bus.set({ bikeId: id });
          bus.go("confirm");
        }, BIKE);
        await nap(1500);
        await at("confirm");
        await tab.evaluate(async () => { (await import("/counter/js/bus.js")).go("pick"); });
        await tab.waitForSelector("[data-screen='pick'] .hit", { timeout: 90000 });
        await at("pick");
        await tab.evaluate(() => document.querySelector(".hit-go")?.click());
        await nap(400);
        await tab.evaluate(() => document.querySelector("[data-screen='pick'] .open")?.click());
        await tab.waitForFunction(() => document.body.getAttribute("data-here") === "book", { timeout: 60000 });
        await nap(2500);
        await at("book");
        await tab.evaluate(() => document.querySelector(".book-parts")?.click());
        await tab.waitForSelector(".pv-sheet .pv-tile", { timeout: 60000 });
        await at("parts");
        await tab.evaluate(() => history.back());
        await nap(800);
        await tab.evaluate(() => document.querySelector(".book-climate")?.click());
        await tab.waitForSelector(".cf-sheet", { timeout: 30000 });
        await nap(600);
        const cf = await tab.evaluate(() => {
          const r = document.querySelector(".cf-sheet").getBoundingClientRect();
          return { bottom: Math.round(r.bottom), vh: window.innerHeight };
        });
        if (Math.abs(cf.bottom - cf.vh) > 2) errs.push(`conditions sits ${cf.bottom}/${cf.vh}`);
        await at("conditions");
        await tab.goto(`${base}/counter/#cost`, { waitUntil: "load", timeout: 45000 });
        await tab.waitForFunction(() => document.querySelector(".cost-veil") && !document.querySelector(".cost-veil").hidden, { timeout: 30000 });
        await at("cost");
      } catch (error) {
        errs.push(`stop failed: ${String(error.message).slice(0, 70)}`);
      }
      const wrong = seen.filter((s) => !s.endsWith(`:${theme}`));
      if (errs.length || wrong.length || seen.length !== 9) {
        faults.push(`${theme}: ${seen.length}/9${wrong.length ? ` wrong ${wrong.join(",")}` : ""}${errs.length ? ` ${errs.slice(0, 2).join(" | ")}` : ""}`);
      }
      await tab.close();
    }
    return faults.join(" ;; ");
  }, { optIn: true }],

  ["geometry: nothing escapes, nothing under 44 px, on every stop", async (page, base) => {
    const faults = [];
    const at = async (name) => {
      const bad = await auditFaults(page);
      if (bad.length) faults.push(`${name}: ${bad.join(" / ")}`);
    };
    await landing(page, base);
    await at("landing");
    await page.type("[data-screen='identify'] .id-q", "390 duke", { delay: 20 });
    await page.waitForSelector(".id-card", { timeout: 25000 });
    await nap(1000);
    await at("cards");
    await page.click(".id-card");
    await page.waitForSelector(".id-chooser", { timeout: 20000 });
    await nap(800);
    await at("chooser");
    await toPick(page, base);
    await at("pick");
    await page.type("[data-screen='pick'] .ask-q", "brake fluid", { delay: 20 });
    await nap(900);
    await at("pick-search");
    await toBook(page, base);
    await at("book");
    await page.evaluate(() => document.querySelector(".book-cover")?.click());
    await nap(1200);
    await at("contents");
    await page.evaluate(() => document.querySelector(".book-cover")?.click());
    await nap(1200);
    await toParts(page, base);
    await at("parts");
    await page.evaluate(() => document.querySelector(".pv-tile")?.click());
    await nap(2500);
    await at("part-detail");
    if (faults.length) return faults.join(" ;; ");
    return "";
  }],
];

/* ------------------------------------------------------------------ runner */

async function run() {
  const args = process.argv.slice(2);
  const pick = (flag, fallback) => {
    const i = args.indexOf(flag);
    return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
  };
  const view = VIEWS[pick("--view", "phone")] || VIEWS.phone;
  const only = pick("--only", "");

  const state = { kill: false };
  const { server, port } = await serve(state);
  const base = `http://127.0.0.1:${port}`;
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    // Software-rasterised WebGL blocks the renderer for seconds at a time while the 3D
    // stage warms up; the default 30 s protocol timeout fires on that, not on a bug.
    protocolTimeout: 180000,
    args: [
      "--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars",
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    ],
  });

  let passed = 0;
  let failed = 0;
  for (const [name, fn, opts] of CHECKS) {
    if (only && !name.includes(only)) continue;
    if (!only && opts && opts.optIn) continue;
    const page = await browser.newPage();
    await page.setViewport(view);
    const noise = [];
    page.on("pageerror", (e) => noise.push(`pageerror: ${e.message.slice(0, 120)}`));
    page.on("console", (m) => {
      if (m.type() !== "error") return;
      const t = m.text();
      if (/favicon|fonts\.g|Failed to load resource|net::ERR/.test(t)) return;
      noise.push(`console: ${t.slice(0, 120)}`);
    });
    await page.evaluateOnNewDocument(() => {
      if (navigator.serviceWorker) navigator.serviceWorker.register = () => Promise.reject(new Error("off"));
    });
    let why = "";
    try {
      why = (await fn(page, base, state, browser, view)) || "";
    } catch (error) {
      why = `threw: ${String(error.message).slice(0, 120)}`;
    }
    if (!why && noise.length) why = noise[0];
    if (why) {
      failed += 1;
      console.log(`!! ${name}\n     ${why}`);
    } else {
      passed += 1;
      console.log(`ok ${name}`);
    }
    await page.close();
  }

  await browser.close();
  server.close();
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
}

run();
