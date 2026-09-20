/**
 * The switch, end to end. Owner: theme agent.
 *
 *   node web/tools/theme-switch-test.mjs
 *
 * Asserts the behaviour a screenshot cannot: the cycle order, that the disc previews the NEXT
 * theme, that <meta name="theme-color"> follows, that the choice survives a reload, that a first
 * visit under a dark system lands on Night, that the crossfade is armed for ~180 ms and is
 * skipped entirely under prefers-reduced-motion, and that the event other modules listen for
 * actually fires with usable tokens.
 */

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const SCRATCH = "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad";
const PUPPETEER = process.env.PUPPETEER_DIR || `${SCRATCH}/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`;
const CHROME = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const UPSTREAM = process.env.TTM_API || "https://mechanica.emilvinu.ch";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json", ".png": "image/png", ".webp": "image/webp",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".pdf": "application/pdf",
};

const server = createServer(async (req, res) => {
  const url = req.url || "/";
  if (url.startsWith("/api/")) {
    try {
      const up = await fetch(`${UPSTREAM}${url}`);
      const body = Buffer.from(await up.arrayBuffer());
      res.writeHead(up.status, { "Content-Type": up.headers.get("content-type") || "application/json" });
      res.end(body);
    } catch { res.writeHead(502).end("{}"); }
    return;
  }
  const p = decodeURIComponent(url.split("?")[0]);
  const f = normalize(join(WEB, p.endsWith("/") ? join(p, "index.html") : p));
  if (!f.startsWith(WEB) || !existsSync(f) || !statSync(f).isFile()) { res.writeHead(404).end("nf"); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(f).toLowerCase()] || "application/octet-stream", "Cache-Control": "no-store" });
  createReadStream(f).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/counter/`;

const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
});

let failed = 0;
const ok = (name, pass, detail = "") => {
  if (!pass) failed += 1;
  console.log(`  ${pass ? "ok " : "!! "} ${name}${detail ? ` — ${detail}` : ""}`);
};

async function open({ dark = false, still = false, seed = null } = {}) {
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/404|favicon|fonts\.g|Failed to load resource|net::ERR/.test(m.text())) return;
    errors.push(m.text());
  });
  // Always stated, never inherited: this box runs Windows in dark mode, so a test that
  // does not say "light" would be testing the machine rather than the code.
  const features = [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }];
  if (still) features.push({ name: "prefers-reduced-motion", value: "reduce" });
  await page.emulateMediaFeatures(features);
  // The profile is shared across pages in one browser, so a test that means "first visit" has
  // to say so: no seed clears the key rather than inheriting the previous block's choice.
  await page.evaluateOnNewDocument((id) => {
    if (navigator.serviceWorker) navigator.serviceWorker.register = () => Promise.reject(new Error("off"));
    try {
      if (id) localStorage.setItem("mechanica.theme", id);
      else localStorage.removeItem("mechanica.theme");
    } catch { /* private mode */ }
  }, seed);
  await page.goto(BASE, { waitUntil: "load", timeout: 45000 });
  await page.waitForSelector("[data-theme-button]", { timeout: 20000 });
  return { page, errors };
}

const read = (page) => page.evaluate(() => {
  const disc = document.querySelector("[data-theme-button] i");
  return {
    theme: document.documentElement.getAttribute("data-theme"),
    meta: document.querySelector('meta[name="theme-color"]').getAttribute("content"),
    label: document.querySelector("[data-theme-button]").getAttribute("aria-label"),
    a: disc.style.getPropertyValue("--swatch-a"),
    b: disc.style.getPropertyValue("--swatch-b"),
    stored: localStorage.getItem("mechanica.theme"),
    api: typeof window.mechanicaTheme === "object" && window.mechanicaTheme.list.length,
    bg: getComputedStyle(document.body).backgroundColor,
    size: (() => {
      const r = document.querySelector("[data-theme-button]").getBoundingClientRect();
      return [Math.round(r.width), Math.round(r.height)];
    })(),
  };
});

console.log("\ncycle + persistence");
{
  const { page, errors } = await open();
  const first = await read(page);
  ok("first visit is Workshop", first.theme === "workshop", first.theme);
  ok("switch is a 44 px target", first.size[0] >= 44 && first.size[1] >= 44, first.size.join("x"));
  ok("disc previews the next theme", first.a === "#15181a" && first.b === "#ff7a1f", `${first.a} / ${first.b}`);
  ok("window.mechanicaTheme exposes five", first.api === 5, String(first.api));

  const order = [];
  const grounds = new Set();
  for (let i = 0; i < 6; i += 1) {
    await page.click("[data-theme-button]");
    await new Promise((r) => setTimeout(r, 320));
    const now = await read(page);
    order.push(now.theme);
    grounds.add(now.bg);
  }
  ok("cycles Workshop -> Night -> Blueprint -> Track -> Paper -> Workshop",
    order.join(",") === "night,blueprint,track,paper,workshop,night", order.join(","));
  ok("each theme repaints the ground", grounds.size === 5, `${grounds.size} distinct`);

  const last = await read(page);
  ok("theme-color meta follows", last.meta === "#ff7a1f", last.meta);
  ok("aria-label names the next theme", last.label === "Blueprint", last.label);
  ok("choice is stored", last.stored === "night", String(last.stored));
  ok("no console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
  await page.close();
}

console.log("\nreload keeps the choice, before first paint");
{
  const { page, errors } = await open({ seed: "track" });
  const now = await read(page);
  ok("stored theme is on <html>", now.theme === "track", now.theme);
  ok("no Workshop frame: the inline script ran in <head>", await page.evaluate(
    () => document.querySelector('script:not([src])').textContent.includes("mechanica.theme"),
  ));
  ok("meta was set before the module loaded", now.meta === "#ffd100", now.meta);
  ok("no console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
  await page.close();
}

console.log("\nfirst visit under a dark system");
{
  const { page } = await open({ dark: true });
  ok("lands on Night", (await read(page)).theme === "night");
  await page.click("[data-theme-button]");
  await new Promise((r) => setTimeout(r, 300));
  const after = await read(page);
  ok("a tap still wins over the system", after.theme === "blueprint" && after.stored === "blueprint", after.theme);
  await page.close();
}
{
  const { page } = await open({ dark: true, seed: "paper" });
  ok("a stored light theme survives a dark system", (await read(page)).theme === "paper");
  await page.close();
}

console.log("\nthe crossfade");
{
  const { page } = await open();
  await page.evaluate(() => {
    window.__swaps = [];
    new MutationObserver(() => window.__swaps.push(document.documentElement.hasAttribute("data-swapping")))
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-swapping"] });
  });
  await page.click("[data-theme-button]");
  await new Promise((r) => setTimeout(r, 60));
  ok("armed during the swap", await page.evaluate(() => document.documentElement.hasAttribute("data-swapping")));
  const fade = await page.evaluate(() => getComputedStyle(document.body).transitionDuration);
  ok("180 ms on colour only", fade.startsWith("0.18s"), fade);
  await new Promise((r) => setTimeout(r, 300));
  ok("disarmed after", await page.evaluate(() => !document.documentElement.hasAttribute("data-swapping")));
  await page.close();
}
{
  const { page } = await open({ still: true });
  await page.click("[data-theme-button]");
  await new Promise((r) => setTimeout(r, 50));
  const armed = await page.evaluate(() => document.documentElement.hasAttribute("data-swapping"));
  ok("reduced motion: never armed", armed === false);
  ok("reduced motion: still switches", (await read(page)).theme === "night");
  await page.close();
}

console.log("\nthe event other modules listen for");
{
  const { page } = await open();
  await page.evaluate(() => {
    window.__seen = [];
    window.addEventListener("mechanica:theme", (e) => window.__seen.push(e.detail));
  });
  await page.click("[data-theme-button]");
  await new Promise((r) => setTimeout(r, 300));
  const seen = await page.evaluate(() => window.__seen);
  ok("mechanica:theme fires", seen.length === 1, JSON.stringify(seen[0]?.id));
  ok("carries the previous id", seen[0]?.previous === "workshop", String(seen[0]?.previous));
  ok("carries live grid tokens for viewer3d.js",
    seen[0]?.tokens?.grid === "#828c93" && seen[0]?.tokens?.gridBg === "#0e1214",
    `${seen[0]?.tokens?.grid} / ${seen[0]?.tokens?.gridBg}`);
  await page.close();
}

console.log("\nthe page stays paper in every theme");
{
  const { page } = await open();
  const values = [];
  for (let i = 0; i < 5; i += 1) {
    values.push(await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      return [css.getPropertyValue("--page").trim(), css.getPropertyValue("--highlight").trim()].join(" ");
    }));
    await page.click("[data-theme-button]");
    await new Promise((r) => setTimeout(r, 260));
  }
  ok("--page and --highlight never move", new Set(values).size === 1, values[0]);
  await page.close();
}

await browser.close();
server.close();
console.log(failed ? `\n${failed} failure(s)` : "\nall green");
process.exitCode = failed ? 1 : 0;
