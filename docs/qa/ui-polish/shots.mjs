/**
 * UI-polish before/after contact shots. Owner: ui-polish agent.
 *
 *   node docs/qa/ui-polish/shots.mjs --tag before
 *   node docs/qa/ui-polish/shots.mjs --tag after --stops landing,confirm-none
 *   node docs/qa/ui-polish/shots.mjs --probe            # print the "no manual" candidates
 *
 * Serves web/ on a throwaway port with /api/* proxied to the live worker, exactly like
 * web/tools/theme-shots.mjs. Two viewports (390x844, 1280x800) x two themes (workshop,
 * night). Files land in docs/qa/ui-polish/<tag>/<theme>-<view>-<stop>.png.
 */

import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..", "..");
const WEB = join(REPO, "web");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const SCRATCH = "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad";
const PUPPETEER = process.env.PUPPETEER_DIR || `${SCRATCH}/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`;
const UPSTREAM = process.env.TTM_API || "https://mechanica.emilvinu.ch";

/** A vehicle the registry has no manual for at all (manualState "none"). */
const NO_MANUAL = "1199 panigale";
/** ...and which card among that query hits is the model with no manual in any year. */
const NO_MANUAL_CARD = "Ducati 1199 Panigale 20";

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

function serve() {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const url = req.url || "/";
      if (url.startsWith("/api/") || url.startsWith("/ws/")) {
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
          res.writeHead(502).end("{}");
        }
        return;
      }
      let path = normalize(join(WEB, decodeURIComponent(url.split("?")[0])));
      if (!path.startsWith(WEB)) {
        res.writeHead(403).end();
        return;
      }
      if (existsSync(path) && statSync(path).isDirectory()) path = join(path, "index.html");
      if (!existsSync(path)) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream" });
      createReadStream(path).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

const VIEWS = [
  { id: "390", width: 390, height: 844 },
  { id: "1280", width: 1280, height: 800 },
];

async function landing(p, base) {
  await p.goto(`${base}/counter/`, { waitUntil: "load", timeout: 45000 });
  await p.waitForSelector("[data-screen='identify'] .id-q", { timeout: 30000 });
  await nap(1400);
}

/** Types a query and opens the year chooser for the card `match` names (else the first). */
async function chooser(p, base, query, match) {
  await landing(p, base);
  await p.type("[data-screen='identify'] .id-q", query, { delay: 35 });
  await p.waitForSelector("[data-screen='identify'] .id-card", { timeout: 25000 });
  await nap(1600);
  const hit = await p.evaluate((want) => {
    const cards = [...document.querySelectorAll("[data-screen='identify'] .id-card")];
    const card = want
      ? cards.find((c) => (c.getAttribute("aria-label") || "").startsWith(want))
      : cards[0];
    if (!card) return false;
    card.click();
    return true;
  }, match || "");
  if (!hit) throw new Error("no card for " + (match || query));
  await p.waitForSelector("[data-screen='identify'] .id-chooser", { timeout: 20000 });
  await nap(700);
}

/** Clicks the first year chip that the catalog has no manual for. */
async function pickNoManualYear(p) {
  const ok = await p.evaluate(() => {
    const chips = [...document.querySelectorAll("[data-screen='identify'] .id-year")];
    const dead = chips.find((c) => c.classList.contains("is-none") && !c.disabled);
    if (!dead) return false;
    dead.click();
    return true;
  });
  if (!ok) throw new Error("no year chip without a manual");
  await p.waitForFunction(() => document.body.getAttribute("data-here") === "confirm", { timeout: 30000 });
  await nap(1600);
}

const STOPS = [
  ["pickdirect", async (p, base) => {
    await landing(p, base);
    await p.evaluate(async (id) => {
      const bus = await import("/counter/js/bus.js");
      bus.set({ bikeId: id });
      bus.go("pick");
    }, "ktm-390-duke-2024");
    await p.waitForSelector("[data-screen='pick'] .hit", { timeout: 60000 });
    await nap(1000);
  }],
  ["landing", landing],
  ["cards", async (p, base) => {
    await landing(p, base);
    await p.type("[data-screen='identify'] .id-q", "390 duke", { delay: 35 });
    await p.waitForSelector("[data-screen='identify'] .id-card", { timeout: 25000 });
    await nap(1500);
  }],
  ["chooser", async (p, base) => { await chooser(p, base, "390 duke"); }],
  ["confirm-ready", async (p, base) => {
    await landing(p, base);
    await p.type("[data-screen='identify'] .id-q", "2024 390 duke", { delay: 35 });
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "confirm", { timeout: 30000 });
    await nap(2200);
  }],
  ["confirm-none", async (p, base) => {
    await chooser(p, base, NO_MANUAL, NO_MANUAL_CARD);
    await pickNoManualYear(p);
  }],
  ["confirm-none-2", async (p, base) => {
    await chooser(p, base, NO_MANUAL, NO_MANUAL_CARD);
    await pickNoManualYear(p);
    // the manual button: whatever the "yes" slot is showing for a bike with no manual
    await p.evaluate(() => {
      const slot = document.querySelector("[data-screen='confirm'] .confirm-yes-slot");
      const btn = slot && [...slot.querySelectorAll(".btn")].find((b) => !b.hidden && !b.disabled);
      if (btn) btn.click();
    });
    await nap(9000);
  }],
  ["pick", async (p, base) => {
    await landing(p, base);
    await p.type("[data-screen='identify'] .id-q", "2024 390 duke", { delay: 35 });
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "confirm", { timeout: 30000 });
    await nap(1500);
    await p.evaluate(() => {
      const yes = document.querySelector("[data-screen='confirm'] .confirm-yes-slot .btn");
      if (yes) yes.click();
    });
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "pick", { timeout: 60000 });
    await p.waitForSelector("[data-screen='pick'] .hit", { timeout: 40000 }).catch(() => {});
    await p.waitForFunction(
      () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
      { timeout: 45000 },
    ).catch(() => {});
    await nap(2500);
  }],
  ["book", async (p, base) => {
    await landing(p, base);
    await p.type("[data-screen='identify'] .id-q", "2024 390 duke", { delay: 35 });
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "confirm", { timeout: 30000 });
    await nap(1500);
    await p.evaluate(() => document.querySelector("[data-screen='confirm'] .confirm-yes-slot .btn")?.click());
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "pick", { timeout: 60000 });
    await p.waitForSelector("[data-screen='pick'] .hit", { timeout: 40000 }).catch(() => {});
    await nap(1200);
    await p.evaluate(() => {
      const rows = [...document.querySelectorAll("[data-screen='pick'] .hit-go")];
      (rows[1] || rows[0])?.click();
    });
    await nap(700);
    await p.evaluate(() => document.querySelector("[data-screen='pick'] .open")?.click());
    await p.waitForFunction(() => document.body.getAttribute("data-here") === "book", { timeout: 45000 });
    await p.waitForSelector("[data-screen='book'] .page-sheet.is-ready", { timeout: 60000 }).catch(() => {});
    await nap(2500);
  }],
];

async function probe(page, base) {
  await landing(page, base);
  await page.type("[data-screen='identify'] .id-q", NO_MANUAL, { delay: 35 });
  await page.waitForSelector("[data-screen='identify'] .id-card", { timeout: 25000 });
  await nap(1800);
  const cards = await page.evaluate(() =>
    [...document.querySelectorAll("[data-screen='identify'] .id-card")]
      .slice(0, 8)
      .map((c) => c.getAttribute("aria-label")));
  await page.evaluate((want) => {
    const cards = [...document.querySelectorAll("[data-screen='identify'] .id-card")];
    (cards.find((c) => (c.getAttribute("aria-label") || "").startsWith(want)) || cards[0]).click();
  }, NO_MANUAL_CARD);
  await page.waitForSelector("[data-screen='identify'] .id-chooser", { timeout: 20000 });
  await nap(800);
  const years = await page.evaluate(() =>
    [...document.querySelectorAll("[data-screen='identify'] .id-year")]
      .map((c) => `${c.textContent.trim()} [${c.className}]${c.disabled ? " disabled" : ""}`));
  console.log("cards:", cards);
  console.log("years:", years);
}

async function run() {
  const args = process.argv.slice(2);
  const pick = (flag, fallback) => {
    const i = args.indexOf(flag);
    return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
  };
  const tag = pick("--tag", "before");
  const themes = pick("--themes", "workshop,night").split(",").filter(Boolean);
  const want = pick("--stops", "").split(",").filter(Boolean);
  const views = pick("--views", "390,1280").split(",").filter(Boolean);
  const stops = want.length ? STOPS.filter(([n]) => want.includes(n)) : STOPS;

  const { server, port } = await serve();
  const base = `http://127.0.0.1:${port}`;
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const launch = () => puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars",
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    ],
  });

  const out = join(HERE, tag);
  mkdirSync(out, { recursive: true });

  if (args.includes("--probe")) {
    const browser = await launch();
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
    await probe(page, base);
    await browser.close();
    server.close();
    return;
  }

  const allErrors = [];
  for (const theme of themes) {
    for (const view of VIEWS.filter((v) => views.includes(v.id))) {
      const browser = await launch();
      for (const [name, drive] of stops) {
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
        let note = "";
        try {
          await drive(page, base);
        } catch (error) {
          note = ` !! ${String(error.message).slice(0, 80)}`;
        }
        let raw = null;
        for (let tries = 0; tries < 4 && !raw; tries += 1) {
          try {
            raw = await page.screenshot({ encoding: "binary", captureBeyondViewport: false });
          } catch {
            await nap(1000);
          }
        }
        if (raw) writeFileSync(join(out, `${theme}-${view.id}-${name}.png`), raw);
        for (const e of errors) allErrors.push(`${theme}/${view.id}/${name}: ${e}`);
        console.log(`  ${theme}/${view.id}/${name}${raw ? "" : " (no capture)"}${note}${errors.length ? ` [${errors.length} console errors]` : ""}`);
        await page.close();
      }
      await browser.close();
    }
  }
  server.close();
  console.log(allErrors.length ? `\nconsole errors:\n${allErrors.join("\n")}` : "\n0 console errors");
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
