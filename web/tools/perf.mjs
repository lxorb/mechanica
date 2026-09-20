/**
 * First-load stopwatch for the counter app. Owner: performance agent.
 *
 *   node web/tools/perf.mjs                      # local server, the default matrix
 *   node web/tools/perf.mjs --live               # https://mechanica.emilvinu.ch/counter/
 *   node web/tools/perf.mjs --only fast4g-cold   # one row of the matrix
 *   node web/tools/perf.mjs --offline            # warm visit, then pull the plug
 *   node web/tools/perf.mjs --out docs/qa/perf/before.json
 *
 * Every row is a fresh browser profile (cold) or a second visit in the same profile (warm,
 * service worker installed and controlling). The page is opened at 390x844 with the network
 * and the CPU throttled through CDP, and three numbers are taken from inside the page so no
 * driver round-trip is counted:
 *
 *   fcp      first-contentful-paint
 *   field    the moment `.id-q` (the search box) is in the DOM
 *   card     the moment the first `.id-card` is on screen after "390" was typed
 *
 * "390" is typed by the page itself, in the same task that first sees the field, so `card`
 * is the honest "a mechanic could have used this by now" number: it includes every byte and
 * every long task that still stood between the field and an answer.
 *
 * Bytes and requests come from Network.loadingFinished (encoded, i.e. what crossed the wire)
 * and are split by initiator type, with cache and service-worker hits counted separately.
 * Long tasks come from PerformanceObserver with attribution.
 */

import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const ROOT = resolve(WEB, "..");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER = process.env.PUPPETEER_DIR || resolve(ROOT, "node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js");
const LIVE = "https://mechanica.emilvinu.ch/counter/";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
  ".pdf": "application/pdf",
  ".glb": "model/gltf-binary",
  ".bin": "application/octet-stream",
  ".wasm": "application/wasm",
  ".onnx": "application/octet-stream",
  ".txt": "text/plain; charset=utf-8",
};

const GZIP = /^(text\/|application\/(javascript|json|manifest\+json)|image\/svg)/;

const PUBLIC_API = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";

/**
 * docs/qa/perf/index-head.patch, applied to the served bytes instead of to the file — the head
 * of index.html belongs to another agent this week, and a hint that is only worth having if it
 * measures well has to be measurable before it is handed over. `--patch` turns it on.
 *
 * Hunk 1 (hints): the roster and the module graph start with the HTML instead of two round
 * trips after it, and the two CDNs the reader and the 3D viewer load from are connected early.
 * Hunk 2 (css): the five screens nobody can reach from the landing stop blocking the first
 * paint. Both are exactly what the patch file writes.
 */
const HEAD_HINTS = `  <link rel="preload" href="../store/ttm-catalog.json" as="fetch">
  <link rel="modulepreload" href="js/bus.js">
  <link rel="modulepreload" href="js/ttm.js">
  <link rel="modulepreload" href="js/search.js">
  <link rel="modulepreload" href="js/index-data.js">
  <link rel="modulepreload" href="js/vision.js">
  <link rel="modulepreload" href="js/screens/identify.js">
  <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
  <link rel="preconnect" href="https://cdnjs.cloudflare.com" crossorigin>
`;

const LATE_CSS = ["confirm", "pick", "book", "invoice", "cost"];

function patchHead(html, { css = true } = {}) {
  let out = html.replace(
    '  <link rel="stylesheet" href="css/counter.css">',
    `${HEAD_HINTS}  <link rel="stylesheet" href="css/counter.css">`
  );
  if (!css) return out;
  const late = (href) => {
    out = out.replace(
      `<link rel="stylesheet" href="${href}">`,
      `<link rel="stylesheet" media="print" onload="this.media='all'" href="${href}">`
    );
  };
  for (const id of LATE_CSS) late(`css/screens/${id}.css`);
  late("css/climate.css");
  late("css/viewer3d.css");
  return out;
}

/**
 * web/ over http, gzipped and ETagged like the edge serves it, and /api proxied to the same
 * container the Worker puts behind /api, so a local run boots down the same REMOTE path the
 * phone on the conference wifi will. `--noapi` answers /api with 503 instead: that is the
 * offline / LOCAL store path.
 */
function serve({ api = PUBLIC_API, patch = false } = {}) {
  const etags = new Map();
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      if ((req.url || "").startsWith("/api")) {
        if (!api) {
          res.writeHead(503, { "Content-Type": "text/plain" }).end("no api");
          return;
        }
        const target = `${api}${req.url === "/api" ? "/" : req.url.slice(4)}`;
        try {
          const upstream = await fetch(target, { headers: { Accept: "application/json" } });
          res.writeHead(upstream.status, {
            "Content-Type": upstream.headers.get("content-type") || "application/json",
            "Access-Control-Allow-Origin": "*",
          });
          if (upstream.body) await pipeline(Readable.fromWeb(upstream.body), res);
          else res.end();
        } catch (err) {
          // A page that navigated away mid-proxy aborts the socket: that is not a failure.
          if (!res.headersSent) res.writeHead(502, { "Content-Type": "text/plain" });
          res.end();
        }
        return;
      }
      let path = decodeURIComponent((req.url || "/").split("?")[0]);
      if (path.endsWith("/")) path += "index.html";
      const file = normalize(join(WEB, path));
      if (!file.startsWith(WEB) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404, { "Content-Type": "text/plain" }).end("not found");
        return;
      }
      const type = TYPES[extname(file).toLowerCase()] || "application/octet-stream";
      if (patch && file.endsWith("index.html")) {
        const body = gzipSync(Buffer.from(patchHead(readFileSync(file, "utf8")), "utf8"), { level: 6 });
        res.writeHead(200, {
          "Content-Type": type,
          "Cache-Control": "max-age=0, must-revalidate",
          "Content-Encoding": "gzip",
          "Content-Length": body.length,
        }).end(body);
        return;
      }
      const stat = statSync(file);
      let tag = etags.get(file);
      if (!tag || tag.mtime !== stat.mtimeMs) {
        tag = { mtime: stat.mtimeMs, etag: `"${createHash("sha1").update(`${file}${stat.mtimeMs}${stat.size}`).digest("hex").slice(0, 16)}"` };
        etags.set(file, tag);
      }
      const head = { "Content-Type": type, "Cache-Control": "max-age=0, must-revalidate", ETag: tag.etag, "Access-Control-Allow-Origin": "*" };
      if (req.headers["if-none-match"] === tag.etag) {
        res.writeHead(304, head).end();
        return;
      }
      const wantsGzip = String(req.headers["accept-encoding"] || "").includes("gzip");
      if (wantsGzip && GZIP.test(type) && stat.size < 12_000_000) {
        const body = gzipSync(readFileSync(file), { level: 6 });
        res.writeHead(200, { ...head, "Content-Encoding": "gzip", "Content-Length": body.length }).end(body);
        return;
      }
      res.writeHead(200, { ...head, "Content-Length": stat.size });
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

/* ------------------------------------------------------------ throttling */

const NETS = {
  // Chrome DevTools presets, spelled out so the report can be reproduced.
  none: null,
  fast4g: { downloadThroughput: (4 * 1024 * 1024) / 8, uploadThroughput: (3 * 1024 * 1024) / 8, latency: 20 },
  slow4g: { downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8, latency: 150 },
  slow3g: { downloadThroughput: (400 * 1024) / 8, uploadThroughput: (400 * 1024) / 8, latency: 2000 },
};

/* --------------------------------------------------------- in-page probes */

const PROBE = `
window.__perf = { marks: {}, long: [], typed: null };
(function () {
  const P = window.__perf;
  const mark = (k) => { if (P.marks[k] == null) P.marks[k] = performance.now(); };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === "first-contentful-paint") mark("fcp"); })
      .observe({ type: "paint", buffered: true });
  } catch (e) {}
  try {
    new PerformanceObserver((l) => { const e = l.getEntries(); if (e.length) P.marks.lcp = e[e.length - 1].startTime; })
      .observe({ type: "largest-contentful-paint", buffered: true });
  } catch (e) {}
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        if (e.duration < 50) continue;
        P.long.push({
          start: Math.round(e.startTime),
          dur: Math.round(e.duration),
          name: e.name,
          attr: (e.attribution || []).map((a) => a.containerSrc || a.containerName || a.name || a.containerType).filter(Boolean),
        });
      }
    }).observe({ type: "longtask", buffered: true });
  } catch (e) {}

  const type = () => {
    const q = document.querySelector(".id-q");
    if (!q || P.typed) return;
    P.typed = true;
    try { q.focus(); } catch (e) {}
    q.value = "390";
    q.dispatchEvent(new Event("input", { bubbles: true }));
    mark("typed");
  };
  const tick = () => {
    if (P.marks.field == null && document.querySelector(".id-q")) { mark("field"); if (window.__AUTOTYPE) type(); }
    if (P.marks.card == null && document.querySelector(".id-card")) mark("card");
    if (P.marks.card == null) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  setInterval(() => { if (P.marks.card == null) tick(); }, 60);
})();
`;

/* ------------------------------------------------------------- one measure */

function kind(type, url) {
  const t = String(type || "").toLowerCase();
  if (t === "document") return "html";
  if (t === "stylesheet") return "css";
  if (t === "script") return "js";
  if (t === "font") return "font";
  if (t === "image") return "img";
  if (/\.json(\?|$)/.test(url)) return "json";
  if (t === "fetch" || t === "xhr") return "api";
  return t || "other";
}

async function measure(browser, { url, net, cpu, autotype = true, offline = false, label, settle = 1500, timeout = 90000 }) {
  const page = await browser.newPage();
  const client = await page.createCDPSession();
  const wire = new Map();
  const out = { label, requests: 0, bytes: 0, byType: {}, cached: 0, sw: 0, failed: [], errors: [] };

  await client.send("Network.enable");
  client.on("Network.responseReceived", (e) => {
    const row = wire.get(e.requestId) || {};
    Object.assign(row, { url: e.response.url, kind: kind(e.type, e.response.url), cache: e.response.fromDiskCache, sw: e.response.fromServiceWorker, status: e.response.status });
    wire.set(e.requestId, row);
  });
  client.on("Network.requestServedFromCache", (e) => {
    const row = wire.get(e.requestId) || {};
    row.cache = true;
    wire.set(e.requestId, row);
  });
  client.on("Network.requestWillBeSent", (e) => {
    const row = wire.get(e.requestId) || {};
    row.start = e.timestamp;
    row.url = row.url || e.request.url;
    wire.set(e.requestId, row);
  });
  client.on("Network.loadingFinished", (e) => {
    const row = wire.get(e.requestId);
    if (!row) return;
    row.bytes = e.encodedDataLength || 0;
    row.end = e.timestamp;
  });
  client.on("Network.loadingFailed", (e) => {
    const row = wire.get(e.requestId);
    if (row && !e.canceled) out.failed.push(`${row.url} ${e.errorText}`);
  });

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await page.evaluateOnNewDocument(`window.__AUTOTYPE = ${autotype ? "true" : "false"};\n${PROBE}`);
  page.on("pageerror", (e) => out.errors.push(e.message.slice(0, 120)));
  page.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text().slice(0, 120)); });

  if (offline) await page.setOfflineMode(true);
  if (net && NETS[net]) await client.send("Network.emulateNetworkConditions", { offline: false, ...NETS[net] });
  if (cpu > 1) await client.send("Emulation.setCPUThrottlingRate", { rate: cpu });

  /**
   * A service worker re-issues the page's requests from its own target, which the page's
   * session does not throttle: without this, every warm load quietly measures a 4 MB/s phone
   * on unlimited wifi. Attached as the workers appear, for as long as this page lives.
   */
  const workers = new Set();
  const throttleWorkers = async () => {
    for (const target of browser.targets()) {
      if (target.type() !== "service_worker" || workers.has(target)) continue;
      workers.add(target);
      try {
        const sess = await target.createCDPSession();
        if (net && NETS[net]) await sess.send("Network.emulateNetworkConditions", { offline: Boolean(offline), ...NETS[net] });
        else if (offline) await sess.send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
        if (cpu > 1) await sess.send("Emulation.setCPUThrottlingRate", { rate: cpu });
      } catch {
        /* the worker was gone before we got to it: nothing to throttle */
      }
    }
  };
  await throttleWorkers();
  const watching = setInterval(() => { throttleWorkers().catch(() => {}); }, 500);

  const started = Date.now();
  // Not awaited before the probe: on slow 3G `load` is minutes behind the first usable card,
  // and the numbers that matter are taken from inside the page anyway.
  const nav = page.goto(url, { waitUntil: "domcontentloaded", timeout }).catch((err) => {
    out.errors.push(`goto: ${err.message.slice(0, 100)}`);
  });
  await page.waitForFunction("window.__perf && window.__perf.marks.card != null", { timeout, polling: 200 }).catch(() => {});
  await nav;
  await new Promise((r) => setTimeout(r, settle));

  const perf = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0] || {};
    return {
      marks: window.__perf.marks,
      long: window.__perf.long,
      ttfb: Math.round(nav.responseStart || 0),
      dcl: Math.round(nav.domContentLoadedEventEnd || 0),
      load: Math.round(nav.loadEventEnd || 0),
      // What the page itself asked for, the way DevTools counts it: a service worker re-issues
      // the page's requests from its own context, where the page's CDP session cannot see them,
      // so Network.loadingFinished alone undercounts every warm load.
      res: performance.getEntriesByType("resource").map((e) => ({
        url: e.name,
        kind: e.initiatorType,
        bytes: e.transferSize || 0,
        body: e.encodedBodySize || 0,
        end: Math.round(e.responseEnd),
      })),
      docBytes: (performance.getEntriesByType("navigation")[0] || {}).transferSize || 0,
      cards: document.querySelectorAll(".id-card").length,
      store: document.documentElement.dataset.store || "",
      sw: Boolean(navigator.serviceWorker && navigator.serviceWorker.controller),
      // User Timing the app writes itself: boot phases, named "ttm:<phase>".
      phases: performance.getEntriesByType("measure")
        .filter((m) => m.name.startsWith("ttm:"))
        .map((m) => ({ name: m.name.slice(4), start: Math.round(m.startTime), dur: Math.round(m.duration) })),
    };
  }).catch(() => ({ marks: {}, long: [] }));

  const cardAt = Math.round(perf.marks.card ?? 0);
  out.landing = { requests: 1, bytes: perf.docBytes || 0 };
  out.requests = 1;
  out.bytes = perf.docBytes || 0;
  out.byType.html = perf.docBytes || 0;
  for (const row of perf.res || []) {
    out.requests += 1;
    out.bytes += row.bytes;
    const k = row.bytes === 0 && row.body > 0 ? "cache/sw" : kind(row.kind, row.url);
    out.byType[k] = (out.byType[k] || 0) + row.bytes;
    if (row.bytes === 0 && row.body > 0) out.cached += 1;
    // What the landing actually cost: everything that had finished by the time the first card
    // was on screen. The rest (photo index, manuals, the worker filling its cache) is after.
    if (cardAt && row.end <= cardAt) {
      out.landing.requests += 1;
      out.landing.bytes += row.bytes;
    }
  }
  // The worker's own fetches, which the page's timeline never sees, kept separately.
  for (const row of wire.values()) if (row.sw) out.sw += 1;
  const first = Math.min(...[...wire.values()].map((r) => r.start ?? Infinity));
  out.slow = [...wire.values()]
    .filter((r) => r.start && r.end)
    .map((r) => ({ url: String(r.url).replace(/^https?:\/\/[^/]+/, "").slice(-58), at: Math.round((r.start - first) * 1000), ms: Math.round((r.end - r.start) * 1000), kb: Math.round((r.bytes || 0) / 1024) }))
    .sort((a, z) => z.ms - a.ms)
    .slice(0, 10);
  out.wall = Date.now() - started;
  out.fcp = Math.round(perf.marks.fcp ?? 0);
  out.lcp = Math.round(perf.marks.lcp ?? 0);
  out.field = Math.round(perf.marks.field ?? 0);
  out.card = Math.round(perf.marks.card ?? 0);
  out.ttfb = perf.ttfb;
  out.dcl = perf.dcl;
  out.load = perf.load;
  out.cards = perf.cards;
  out.store = perf.store;
  out.controlled = perf.sw;
  out.long = (perf.long || []).sort((a, z) => z.dur - a.dur).slice(0, 12);
  out.longTotal = (perf.long || []).reduce((sum, e) => sum + e.dur, 0);
  out.longCount = (perf.long || []).length;
  out.phases = perf.phases || [];
  clearInterval(watching);
  await page.close();
  return out;
}

/* ------------------------------------------------------------------ rows */

function kb(n) {
  return `${(n / 1024).toFixed(0)} KB`;
}

function line(row) {
  const types = Object.entries(row.byType).sort((a, z) => z[1] - a[1]).map(([k, v]) => `${k} ${kb(v)}`).join(" · ");
  return [
    `  ${row.label.padEnd(26)} fcp ${String(row.fcp).padStart(5)} lcp ${String(row.lcp).padStart(5)} ` +
    `field ${String(row.field).padStart(6)} card ${String(row.card).padStart(6)} ` +
    `| landing ${String(row.landing ? row.landing.requests : 0).padStart(3)} req ${kb(row.landing ? row.landing.bytes : 0).padStart(8)} of ${String(row.requests).padStart(3)}/${kb(row.bytes)} | long ${row.longCount}/${row.longTotal}ms | cards ${row.cards} store ${row.store}${row.controlled ? " sw" : ""}`,
    `      ${types}`,
    row.long.length ? `      long: ${row.long.slice(0, 4).map((t) => `${t.dur}ms@${t.start}`).join(" ")}` : "",
    row.phases && row.phases.length ? `      phases: ${row.phases.map((p) => `${p.name} ${p.start}+${p.dur}`).join(" · ")}` : "",
    row.slow && row.slow.length ? `      slowest: ${row.slow.slice(0, 4).map((r) => `${r.url.split("/").pop()} ${r.ms}ms/${r.kb}KB@${r.at}`).join(" · ")}` : "",
    row.errors.length ? `      !! ${row.errors.slice(0, 2).join(" | ")}` : "",
    row.failed.length ? `      !! failed ${row.failed.slice(0, 2).join(" | ")}` : "",
  ].filter(Boolean).join("\n");
}

/* ------------------------------------------------------------------ main */

async function main() {
  const argv = process.argv.slice(2);
  const flag = (name) => argv.includes(`--${name}`);
  const value = (name, fallback) => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
  };

  const live = flag("live");
  const only = value("only", "");
  const outPath = value("out", "");
  const cpu = Number(value("cpu", 4));
  const timeout = Number(value("timeout", 120000));
  const noapi = flag("noapi");

  let server = null;
  let origin;
  if (live) {
    origin = LIVE;
  } else {
    const started = await serve({ api: noapi ? null : PUBLIC_API, patch: flag("patch") });
    server = started.server;
    origin = `http://127.0.0.1:${started.port}/counter/`;
  }

  const puppeteer = await import(`file:///${String(PUPPETEER).replace(/\\/g, "/")}`);
  const rows = [];
  // Every row three times if you ask for it: the API behind /api is a container in another
  // hemisphere and one run of anything is a coin toss.
  const runs = Math.max(1, Number(value("runs", 1)));
  const plan = [];
  for (let n = 0; n < runs; n++) {
    for (const row of [
      { id: "fast4g-cold", net: "fast4g", cpu, warm: false },
      { id: "fast4g-warm", net: "fast4g", cpu, warm: true },
      { id: "slow3g-cold", net: "slow3g", cpu, warm: false },
      { id: "nothrottle-cold", net: "none", cpu: 1, warm: false },
    ]) {
      if (!only || row.id === only) plan.push(runs > 1 ? { ...row, tag: `.${n + 1}` } : row);
    }
  }

  for (const row of plan) {
    const browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required"],
    });
    try {
      if (row.warm) {
        // First visit: install the worker and let it precache, then measure the second.
        const first = await browser.newPage();
        await first.goto(origin, { waitUntil: "load", timeout: 120000 }).catch(() => {});
        await first.waitForFunction("navigator.serviceWorker && navigator.serviceWorker.controller", { timeout: 60000 }).catch(() => {});
        await new Promise((r) => setTimeout(r, 6000));
        await first.close();
      }
      const res = await measure(browser, { url: origin, net: row.net, cpu: row.cpu, timeout, label: `${live ? "live" : "local"} ${row.id}${row.tag || ""}` });
      rows.push(res);
      console.log(line(res));

      if (flag("offline") && row.warm) {
        const off = await measure(browser, { url: origin, net: "none", cpu: row.cpu, offline: true, label: `${live ? "live" : "local"} offline`, timeout: 40000 });
        rows.push(off);
        console.log(line(off));
      }
    } finally {
      await browser.close();
    }
  }

  if (server) server.close();
  if (outPath) {
    const file = resolve(ROOT, outPath);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, `${JSON.stringify({ origin, when: new Date().toISOString(), rows }, null, 2)}\n`);
    console.log(`\n  wrote ${outPath}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
