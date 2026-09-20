/**
 * Renders each vehicle model in headless Chrome and saves a screenshot. Owner: vehicle-models.
 *
 *   node web/tools/viewer-shots.mjs                  # every bike in the harness + the 3 exact
 *   node web/tools/viewer-shots.mjs scooter corvette # only these (matched against the bike list)
 *   node web/tools/viewer-shots.mjs --states         # the loading ring and the 404 fallback
 *
 * Serves web/ on a throwaway port, opens counter/viewer-test.html?bike=<name>, waits for the GLB
 * to be adopted (data-viewer3d="ready"), then writes web/docs-shots/generic-<type>.png and prints
 * what the viewer reported — model key, tint, part groups, console errors. That last column is
 * the point: a model that renders but lands every mesh in the catch-all group is a model whose
 * part regexes still need work, and a screenshot alone would not show it.
 *
 * `--states` covers the two paths a plain screenshot run never reaches, because both are over in
 * a few hundred milliseconds on localhost: the progress ring (the GLB is trickled at ~2 MB/s so
 * it shows a real percentage) and the schematic fallback for a model URL that 404s.
 */

import { createReadStream, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const SHOTS = join(WEB, "docs-shots");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
// puppeteer-core is a dev-only dependency and web/ has no node_modules, so it is imported by
// absolute path out of wherever it was installed. $PUPPETEER_DIR overrides.
const PUPPETEER = process.env.PUPPETEER_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const TYPES = {
  "image/html": "text/html",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".bin": "application/octet-stream",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".hdr": "image/vnd.radiance",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm",
};

function serve({ slow = false } = {}) {
  return new Promise((done) => {
    const server = createServer(async (req, res) => {
      const path = decodeURIComponent((req.url || "/").split("?")[0]);
      const file = normalize(join(WEB, path));
      if (!file.startsWith(WEB) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
        "Content-Length": statSync(file).size,       // the loading ring needs a real total
        "Access-Control-Allow-Origin": "*",
      });
      if (slow && file.endsWith("model.glb")) {
        // trickle it so the ring is on screen long enough to photograph with a real percentage
        for await (const chunk of createReadStream(file, { highWaterMark: 120_000 })) {
          res.write(chunk);
          await new Promise((r) => setTimeout(r, 60));
        }
        res.end();
        return;
      }
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

const SHOT_LIST = [
  ["duke", "naked"], ["yzf", "sportbike-exact"], ["cbr650r", "sportbike-exact-cbr"],
  ["sx-f", "motocross"], ["exc", "enduro"], ["smc", "supermoto"], ["vespa", "scooter"],
  ["gold wing", "touring"], ["gs", "adventure"], ["softail", "cruiser"],
  ["classic 350", "classic"], ["grom", "minibike"], ["txt", "trial"], ["corvette", "car"],
];

/**
 * The two transient states. Both are invisible in a normal run — the ring because localhost
 * serves 4 MB instantly, the fallback because nothing 404s — so each gets its own page with the
 * condition it needs, and the assertion is the printed row, not the picture.
 */
async function states() {
  const { server, port } = await serve({ slow: true });
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  mkdirSync(SHOTS, { recursive: true });
  const cases = [
    ["viewer-loading-ring", "model=yzf-2021",
      () => document.querySelector(".viewer3d-load.is-known")
        && /[1-9]/.test(document.querySelector(".viewer3d-load-pct")?.textContent || "")],
    ["viewer-fallback-404", "model=generic/does-not-exist",
      () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "placeholder"],
  ];
  let bad = 0;
  for (const [name, query, condition] of cases) {
    const page = await browser.newPage();
    await page.setViewport({ width: 900, height: 620 });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      // a 404 is the point of the second case, so only real script errors count
      if (m.type() === "error" && !/404|favicon|fonts\.g|Failed to load resource/.test(m.text())) errors.push(m.text());
    });
    await page.goto(`http://127.0.0.1:${port}/counter/viewer-test.html?${query}`, { waitUntil: "load", timeout: 40000 });
    const met = await page.waitForFunction(condition, { timeout: 45000 }).then(() => true).catch(() => false);
    await new Promise((r) => setTimeout(r, 500));
    const info = await page.evaluate(() => ({
      attr: document.querySelector(".viewer3d")?.getAttribute("data-viewer3d"),
      ring: !!document.querySelector(".viewer3d-load"),
      known: !!document.querySelector(".viewer3d-load.is-known"),
      pct: document.querySelector(".viewer3d-load-pct")?.textContent || "",
      groups: window.viewer ? window.viewer.state().parts.length : 0,
    }));
    await page.screenshot({ path: join(SHOTS, `${name}.png`) });
    if (!met) bad += 1;
    console.log(
      `  ${met ? "ok " : "!! "} ${name.padEnd(22)} state=${String(info.attr).padEnd(12)} ` +
      `ring=${String(info.ring).padEnd(5)} known=${String(info.known).padEnd(5)} ` +
      `pct=${(info.pct || "-").padEnd(5)} groups=${info.groups} errors=${errors.length ? errors[0].slice(0, 80) : "none"}`,
    );
    await page.close();
  }
  await browser.close();
  server.close();
  process.exitCode = bad ? 1 : 0;
}

/**
 * `--orient`: one contact sheet per generic model, at 0 / 90 / 180 / 270 degrees of Y rotation.
 * Which way a model faces cannot be read out of its bounding box — the front and the back of a
 * motorcycle have the same silhouette from above — so this renders all four and a human picks,
 * then the number goes into web/tools/model-shortlist.json as `orient`.
 */
async function orient(names) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  mkdirSync(SHOTS, { recursive: true });
  for (const name of names) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1120, height: 300, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${port}/counter/orient-test.html?model=generic/${name}`, { waitUntil: "load", timeout: 40000 });
    await page.waitForFunction(() => window.orientReady === 4, { timeout: 90000 }).catch(() => {});
    await new Promise((r) => setTimeout(r, 1200));
    await page.screenshot({ path: join(SHOTS, `orient-${name}.png`) });
    console.log(`  ${name} -> docs-shots/orient-${name}.png`);
    await page.close();
  }
  await browser.close();
  server.close();
}

async function main() {
  const only = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  if (process.argv.includes("--states")) return states();
  if (process.argv.includes("--orient")) {
    const dir = join(WEB, "store", "models", "generic");
    const names = only.length ? only : readdirSync(dir).filter((n) => existsSync(join(dir, n, "model.glb")));
    return orient(names);
  }
  const list = only.length
    ? SHOT_LIST.filter(([q, name]) => only.some((o) => q.includes(o) || name.includes(o)))
    : SHOT_LIST;
  mkdirSync(SHOTS, { recursive: true });
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  const rows = [];
  for (const [query, name] of list) {
    const page = await browser.newPage();
    await page.setViewport({ width: 900, height: 620, deviceScaleFactor: 1 });
    const console_ = [];
    page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") console_.push(m.text()); });
    page.on("pageerror", (e) => console_.push(`pageerror: ${e.message}`));
    const url = `http://127.0.0.1:${port}/counter/viewer-test.html?bike=${encodeURIComponent(query)}`;
    try {
      await page.goto(url, { waitUntil: "load", timeout: 40000 });
      await page.waitForFunction(
        () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
        { timeout: 60000 },
      ).catch(() => {});
      // a couple of seconds of frames so the camera fit and the HDRI have settled
      await new Promise((r) => setTimeout(r, 2500));
      const state = await page.evaluate(() => ({
        attr: document.querySelector(".viewer3d")?.getAttribute("data-viewer3d"),
        text: document.getElementById("out")?.textContent || "",
        state: window.viewer ? window.viewer.state() : null,
        descriptor: window.lastDescriptor || null,
        fps: (window.fpsSamples || []).slice(-3),
      }));
      const file = join(SHOTS, `generic-${name}.png`);
      await page.screenshot({ path: file });
      const d = state.descriptor || {};
      rows.push({
        name, query, status: state.attr, key: d.key, tint: d.tint, type: d.type,
        groups: state.state ? state.state.parts.length : 0,
        meshes: state.state ? state.state.meshes : 0,
        fps: state.fps[state.fps.length - 1] || 0,
        errors: console_.filter((t) => !/favicon|fonts\.g/.test(t)).slice(0, 2),
      });
      console.log(
        `  ${state.attr === "ready" ? "ok " : "!! "} ${name.padEnd(20)} ${String(d.key).padEnd(22)} ` +
        `${String(d.tint || "-").padEnd(8)} ${String(rows.at(-1).groups).padStart(2)} groups · ` +
        `${String(rows.at(-1).meshes).padStart(4)} meshes · ${rows.at(-1).fps} fps` +
        (rows.at(-1).errors.length ? `\n      ${rows.at(-1).errors.join(" | ").slice(0, 200)}` : ""),
      );
    } catch (error) {
      console.log(`  !! ${name}: ${error.message}`);
      rows.push({ name, query, status: "failed", errors: [error.message] });
    }
    await page.close();
  }
  await browser.close();
  server.close();
  const ok = rows.filter((r) => r.status === "ready").length;
  console.log(`\n${ok}/${rows.length} rendered · screenshots in ${SHOTS}`);
  process.exitCode = ok === rows.length ? 0 : 1;
}

main().catch((error) => { console.error(error); process.exit(1); });
