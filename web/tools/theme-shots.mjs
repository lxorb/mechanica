/**
 * Theme verification. Owner: theme agent. Pairs with ../counter/js/theme.js + css/themes.css.
 *
 *   node web/tools/theme-shots.mjs                     # every theme, both viewports, contact sheets
 *   node web/tools/theme-shots.mjs --themes workshop   # one theme only
 *   node web/tools/theme-shots.mjs --out <dir>         # raw per-stop PNGs go here too (baseline diffs)
 *   node web/tools/theme-shots.mjs --base <dir>        # pixel-diff every stop against that dir
 *
 * Serves web/ on a throwaway port and proxies /api/* to the live worker, so the walk runs against
 * real manuals with the local CSS. Each theme is forced before first paint by seeding
 * localStorage["mechanica.theme"], which is exactly the path a returning user takes.
 *
 * Stops: landing · cards · chooser · confirm · pick · book · parts · chat · conditions · cost.
 * Every stop is best-effort: a stop whose selector never lands is reported, not fatal, so one
 * flaky manual fetch cannot cost the whole run.
 */

import { createReadStream, existsSync, mkdirSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const REPO = resolve(WEB, "..");
const SHEETS = join(REPO, "docs", "ui-themes");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const SCRATCH = "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad";
const SHARP = process.env.SHARP_DIR || `${SCRATCH}/node_modules/sharp/dist/index.cjs`;
const PUPPETEER = process.env.PUPPETEER_DIR || `${SCRATCH}/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`;
const UPSTREAM = process.env.TTM_API || "https://mechanica.emilvinu.ch";

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

function serve() {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const url = req.url || "/";
      if (url.startsWith("/api/") || url.startsWith("/ws/")) {
        try {
          const up = await fetch(`${UPSTREAM}${url}`, {
            method: req.method,
            headers: { Accept: req.headers.accept || "*/*" },
          });
          const body = Buffer.from(await up.arrayBuffer());
          res.writeHead(up.status, {
            "Content-Type": up.headers.get("content-type") || "application/json",
            "Access-Control-Allow-Origin": "*",
          });
          res.end(body);
        } catch {
          res.writeHead(502).end("{}");
        }
        return;
      }
      const path = decodeURIComponent(url.split("?")[0]);
      const file = normalize(join(WEB, path));
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

const VIEWS = [
  { id: "phone", width: 390, height: 844 },
  { id: "desk", width: 1280, height: 800 },
];

const nap = (ms) => new Promise((r) => setTimeout(r, ms));

/** Each stop: a name and a driver that leaves the app where the shot should be taken. */
const STOPS = [
  ["landing", async (p, base) => {
    await p.goto(`${base}/counter/`, { waitUntil: "load", timeout: 45000 });
    await p.waitForSelector("[data-screen='identify'] .id-q", { timeout: 30000 });
    await nap(1200);
  }],
  ["cards", async (p) => {
    await p.type("[data-screen='identify'] .id-q", "390", { delay: 40 });
    await p.waitForSelector("[data-screen='identify'] .id-card", { timeout: 25000 });
    await nap(1500);
  }],
  ["chooser", async (p) => {
    await p.click("[data-screen='identify'] .id-card");
    await p.waitForSelector("[data-screen='identify'] .id-chooser", { timeout: 20000 });
    await nap(1200);
  }],
  ["confirm", async (p, base) => {
    await p.goto(`${base}/counter/`, { waitUntil: "load", timeout: 45000 });
    await p.waitForSelector("[data-screen='identify'] .id-q", { timeout: 30000 });
    await p.type("[data-screen='identify'] .id-q", "2024 390 duke", { delay: 40 });
    await p.waitForFunction(
      () => document.body.getAttribute("data-here") === "confirm",
      { timeout: 30000 },
    );
    await nap(2000);
  }],
  ["pick", async (p) => {
    await p.evaluate(() => {
      const yes = document.querySelector("[data-screen='confirm'] .confirm-yes-slot .btn");
      if (yes) yes.click();
    });
    await p.waitForFunction(
      () => document.body.getAttribute("data-here") === "pick",
      { timeout: 60000 },
    );
    await p.waitForSelector("[data-screen='pick'] .hit", { timeout: 40000 }).catch(() => {});
    await p.waitForFunction(
      () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
      { timeout: 45000 },
    ).catch(() => {});
    await nap(2500);
  }],
  ["chat", async (p) => {
    await p.evaluate(() => document.querySelector("[data-screen='pick'] .chat-pill")?.click());
    await p.waitForSelector(".cv-sheet", { timeout: 20000 });
    await nap(2000);
  }],
  ["book", async (p) => {
    await p.evaluate(() => {
      const x = document.querySelector(".cv-head .ov-x");
      if (x) x.click();
    });
    await nap(600);
    await p.evaluate(() => {
      const rows = [...document.querySelectorAll("[data-screen='pick'] .hit-go")];
      (rows[1] || rows[0])?.click();
    });
    await nap(700);
    await p.evaluate(() => document.querySelector("[data-screen='pick'] .open")?.click());
    await p.waitForFunction(
      () => document.body.getAttribute("data-here") === "book",
      { timeout: 45000 },
    );
    await p.waitForSelector("[data-screen='book'] .page-sheet.is-ready", { timeout: 60000 }).catch(() => {});
    await nap(2500);
  }],
  ["parts", async (p) => {
    await p.evaluate(() => {
      const hit = [...document.querySelectorAll("[data-screen='book'] .bar-word")]
        .find((b) => /part/i.test(b.textContent || ""));
      if (hit) hit.click();
      else location.hash = "book+invoice";
    });
    await p.waitForSelector(".pv-sheet .pv-tile", { timeout: 40000 }).catch(() => {});
    await nap(2500);
  }],
  ["conditions", async (p) => {
    await p.evaluate(() => { location.hash = "book+conditions"; });
    await p.waitForSelector(".cf-sheet", { timeout: 20000 }).catch(() => {});
    await nap(1800);
  }],
  ["cost", async (p, base) => {
    await p.goto(`${base}/counter/#cost`, { waitUntil: "load", timeout: 45000 });
    await p.waitForSelector(".cost-veil", { timeout: 25000 }).catch(() => {});
    await nap(2200);
  }],
];

async function run() {
  const args = process.argv.slice(2);
  const pick = (flag, fallback) => {
    const i = args.indexOf(flag);
    return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
  };
  const themes = pick("--themes", "workshop,night,blueprint,track,paper").split(",").filter(Boolean);
  const outDir = pick("--out", "");
  const baseDir = pick("--base", "");

  const { server, port } = await serve();
  const base = `http://127.0.0.1:${port}`;
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars",
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    ],
  });

  mkdirSync(SHEETS, { recursive: true });
  if (outDir) mkdirSync(outDir, { recursive: true });

  let problems = 0;
  for (const theme of themes) {
    const tiles = [];
    for (const view of VIEWS) {
      const page = await browser.newPage();
      await page.setViewport({ width: view.width, height: view.height, deviceScaleFactor: 1 });
      const errors = [];
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      page.on("console", (m) => {
        if (m.type() !== "error") return;
        const t = m.text();
        if (/404|favicon|fonts\.g|Failed to load resource|net::ERR/.test(t)) return;
        errors.push(t);
      });
      await page.evaluateOnNewDocument((id) => {
        try { localStorage.setItem("mechanica.theme", id); } catch { /* private mode */ }
        if (navigator.serviceWorker) navigator.serviceWorker.register = () => Promise.reject(new Error("off"));
      }, theme);

      for (const [name, drive] of STOPS) {
        let ok = true;
        try {
          await drive(page, base);
        } catch (error) {
          ok = false;
          problems += 1;
          console.log(`  !! ${theme}/${view.id}/${name}: ${String(error.message).slice(0, 90)}`);
        }
        const shot = Buffer.from(await page.screenshot({ encoding: "binary" }));
        const applied = await page.evaluate(() => ({
          attr: document.documentElement.getAttribute("data-theme"),
          meta: document.querySelector('meta[name="theme-color"]')?.getAttribute("content"),
        }));
        if (applied.attr !== theme && !args.includes("--baseline")) {
          console.log(`  !! ${theme}/${view.id}/${name}: data-theme=${applied.attr}`);
          problems += 1;
        }
        const file = `${theme}-${view.id}-${name}.png`;
        if (outDir) writeFileSync(join(outDir, file), shot);
        tiles.push({ name: `${view.id} · ${name}${ok ? "" : " !!"}`, buffer: shot, file });
        if (baseDir && existsSync(join(baseDir, file))) {
          const diff = await pixelDiff(sharp, join(baseDir, file), shot);
          if (diff > 0.0005) {
            console.log(`  ~~ ${file} differs from baseline: ${(diff * 100).toFixed(3)} % of pixels`);
            problems += 1;
          }
        }
      }
      if (errors.length) {
        console.log(`  !! ${theme}/${view.id} console: ${errors.slice(0, 3).join(" | ").slice(0, 200)}`);
        problems += 1;
      } else {
        console.log(`  ok ${theme}/${view.id} — ${STOPS.length} stops, 0 console errors`);
      }
      await page.close();
    }
    await contactSheet(sharp, theme, tiles);
  }

  await browser.close();
  server.close();
  console.log(problems ? `\n${problems} problem(s)` : "\nall clean");
  process.exitCode = problems ? 1 : 0;
}

/** Fraction of pixels that differ by more than 2/255 on any channel. */
async function pixelDiff(sharp, aPath, bBuffer) {
  const a = await sharp(aPath).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const b = await sharp(bBuffer).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  if (a.info.width !== b.info.width || a.info.height !== b.info.height) return 1;
  let bad = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    if (Math.abs(a.data[i] - b.data[i]) > 2
      || Math.abs(a.data[i + 1] - b.data[i + 1]) > 2
      || Math.abs(a.data[i + 2] - b.data[i + 2]) > 2) bad += 1;
  }
  return bad / (a.data.length / 4);
}

/** One PNG per theme: every stop scaled to a common cell, labelled, tiled five across. */
async function contactSheet(sharp, theme, tiles) {
  if (!tiles.length) return;
  const CELL_W = 260;
  const CELL_H = 560;
  const LABEL = 22;
  const cols = 5;
  const rows = Math.ceil(tiles.length / cols);
  const cells = await Promise.all(tiles.map(async (tile) => {
    const body = await sharp(tile.buffer)
      .resize({ width: CELL_W, height: CELL_H, fit: "contain", position: "top", background: "#20242a" })
      .toBuffer();
    return sharp({ create: { width: CELL_W, height: CELL_H + LABEL, channels: 4, background: "#20242a" } })
      .composite([
        { input: body, top: LABEL, left: 0 },
        {
          input: Buffer.from(
            `<svg width="${CELL_W}" height="${LABEL}">`
            + `<rect width="${CELL_W}" height="${LABEL}" fill="#101317"/>`
            + `<text x="6" y="15" font-family="monospace" font-size="12" fill="#e9e4d7">${tile.name}</text></svg>`,
          ),
          top: 0, left: 0,
        },
      ])
      .png()
      .toBuffer();
  }));
  const sheet = sharp({
    create: { width: cols * CELL_W, height: rows * (CELL_H + LABEL), channels: 4, background: "#101317" },
  }).composite(cells.map((input, i) => ({
    input,
    left: (i % cols) * CELL_W,
    top: Math.floor(i / cols) * (CELL_H + LABEL),
  })));
  await sheet.png().toFile(join(SHEETS, `${theme}.png`));
  console.log(`  -> docs/ui-themes/${theme}.png`);
}

run();
