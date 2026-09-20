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
const SHARP = process.env.SHARP_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/sharp/dist/index.cjs";
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
    // a model URL that 404s: the backdrop and the ring stay, the ring goes quiet and becomes a
    // tap target. Nothing stands in for the vehicle — there is no schematic any more.
    ["viewer-error-retry", "model=generic/does-not-exist",
      () => document.querySelector(".viewer3d-load.is-failed")
        && document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "error"],
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
/**
 * `--sheet`: every generic model on one contact sheet. Eleven separate screenshots are eleven
 * things to look at one at a time; one sheet shows at a glance which models are lying on their
 * side, facing backwards, black, or missing — which is the only way to check the things that
 * cannot be asserted (orientation, shading, framing).
 */
async function sheet(names) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  mkdirSync(SHOTS, { recursive: true });
  const CELL = 300;
  const tiles = [];
  for (const [name, query] of names) {
    const page = await browser.newPage();
    await page.setViewport({ width: CELL, height: CELL, deviceScaleFactor: 1 });
    try {
      await page.goto(`http://127.0.0.1:${port}/counter/solo.html?${query}`, { waitUntil: "load", timeout: 40000 });
      await page.waitForFunction(
        () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
        { timeout: 70000 },
      ).catch(() => {});
      await new Promise((r) => setTimeout(r, 2200));
      const shot = await page.screenshot({ encoding: "binary" });
      tiles.push({ name, buffer: Buffer.from(shot) });
      console.log(`  ${name}`);
    } catch (error) {
      console.log(`  !! ${name}: ${error.message.slice(0, 80)}`);
    }
    await page.close();
  }
  await browser.close();
  server.close();
  if (!tiles.length) return;
  const cols = 4;
  const rows = Math.ceil(tiles.length / cols);
  const labelled = await Promise.all(tiles.map(async (tile, i) => ({
    input: await sharp(tile.buffer)
      .composite([{
        input: Buffer.from(
          `<svg width="${CELL}" height="26"><rect width="${CELL}" height="26" fill="#141414"/>` +
          `<text x="8" y="18" font-family="monospace" font-size="15" fill="#fff">${tile.name}</text></svg>`,
        ),
        top: 0, left: 0,
      }])
      .png()
      .toBuffer(),
    left: (i % cols) * CELL,
    top: Math.floor(i / cols) * CELL,
  })));
  const out = join(SHOTS, "generic-sheet.png");
  await sharp({ create: { width: cols * CELL, height: rows * CELL, channels: 3, background: "#222" } })
    .composite(labelled).png().toFile(out);
  console.log(`\n${tiles.length} tiles -> ${out}`);
}

/**
 * Frame times across a focus, per model. Records every rAF gap for a second before and two
 * seconds after viewer.focus(), and reports the worst frame — which is where the stall was.
 */
async function frames(models) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  let worstOverall = 0;
  for (const [name, query] of models) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
    try {
      await page.goto(`http://127.0.0.1:${port}/counter/solo.html?${query}`, { waitUntil: "load", timeout: 40000 });
      await page.waitForFunction(
        () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
        { timeout: 70000 },
      ).catch(() => {});
      await new Promise((r) => setTimeout(r, 2500));
      const result = await page.evaluate(async () => {
        const gaps = [];
        let last = performance.now();
        let running = true;
        const tick = (now) => { gaps.push(now - last); last = now; if (running) requestAnimationFrame(tick); };
        requestAnimationFrame(tick);
        await new Promise((r) => setTimeout(r, 700));
        const before = gaps.length;
        const parts = window.viewer.state().parts;
        const target = parts.find((p) => p !== "frame") || parts[0];
        const t0 = performance.now();
        window.viewer.focus(target);
        const call = performance.now() - t0;
        await new Promise((r) => setTimeout(r, 1800));
        running = false;
        const during = gaps.slice(before);
        return {
          target,
          call: +call.toFixed(2),
          worst: +Math.max(0, ...during).toFixed(1),
          median: +during.sort((a, b) => a - b)[Math.floor(during.length / 2)].toFixed(1),
          over32: during.filter((g) => g > 32).length,
        };
      });
      worstOverall = Math.max(worstOverall, result.worst);
      console.log(
        `  ${result.over32 ? "!! " : "ok "} ${name.padEnd(12)} focus(${String(result.target).padEnd(12)}) ` +
        `call ${String(result.call).padStart(6)} ms · worst frame ${String(result.worst).padStart(6)} ms · ` +
        `median ${String(result.median).padStart(5)} ms · frames over 32 ms: ${result.over32}`,
      );
    } catch (error) {
      console.log(`  !! ${name}: ${error.message.slice(0, 80)}`);
    }
    await page.close();
  }
  await browser.close();
  server.close();
  console.log(`
worst frame across every model: ${worstOverall.toFixed(1)} ms`);
}

/** one sheet per viewport of every environment, so the four can be compared side by side. */
async function envs(list) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  mkdirSync(SHOTS, { recursive: true });
  for (const [vpName, vw, vh] of [["phone", 390, 844], ["desktop", 1280, 800]]) {
    const tiles = [];
    for (const [name, query] of list) {
      const page = await browser.newPage();
      await page.setViewport({ width: vw, height: vh, deviceScaleFactor: 1 });
      try {
        await page.goto(`http://127.0.0.1:${port}/counter/solo.html?${query}`, { waitUntil: "load", timeout: 40000 });
        await page.waitForFunction(
          () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
          { timeout: 70000 },
        ).catch(() => {});
        await new Promise((r) => setTimeout(r, 3800));
        const shot = Buffer.from(await page.screenshot({ encoding: "binary" }));
        const stats = await sharp(shot).resize(64, 64, { fit: "fill" }).raw().toBuffer({ resolveWithObject: true });
        let sum = 0;
        let n = 0;
        for (let i = 0; i < stats.data.length; i += stats.info.channels) {
          sum += (stats.data[i] * 0.2126 + stats.data[i + 1] * 0.7152 + stats.data[i + 2] * 0.0722) / 255;
          n += 1;
        }
        const swatches = await page.evaluate(() => document.querySelectorAll(".viewer3d-env").length);
        tiles.push({ name, buffer: shot });
        console.log(`  ${vpName.padEnd(8)} ${name.padEnd(26)} mean ${(sum / n).toFixed(3)}  swatches ${swatches}`);
      } catch (error) {
        console.log(`  !! ${vpName} ${name}: ${error.message.slice(0, 70)}`);
      }
      await page.close();
    }
    if (!tiles.length) continue;
    const CW = Math.round(vw / 2);
    const CH = Math.round(vh / 2);
    const cols = 4;
    const rows = Math.ceil(tiles.length / cols);
    const composed = await Promise.all(tiles.map(async (tile, i) => ({
      input: await sharp(tile.buffer).resize(CW, CH, { fit: "fill" }).composite([{
        input: Buffer.from(
          `<svg width="${CW}" height="22"><rect width="${CW}" height="22" fill="#141414"/>` +
          `<text x="6" y="16" font-family="monospace" font-size="12" fill="#fff">${tile.name}</text></svg>`),
        top: 0, left: 0,
      }]).png().toBuffer(),
      left: (i % cols) * CW,
      top: Math.floor(i / cols) * CH,
    })));
    const out = join(SHOTS, `env-${vpName}.png`);
    await sharp({ create: { width: cols * CW, height: rows * CH, channels: 3, background: "#222" } })
      .composite(composed).png().toFile(out);
    console.log(`  -> ${out}`);
  }
  await browser.close();
  server.close();
}

/** default / exploded / focused, both viewports, with a luminance reading per tile. */
async function states3(models) {
  const { server, port } = await serve();
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-gl=angle", "--hide-scrollbars"],
  });
  mkdirSync(SHOTS, { recursive: true });
  const VIEWPORTS = [["phone", 390, 844], ["desktop", 1280, 800]];
  const STATES = [["default", ""], ["exploded", "&explode=1"], ["focused", "&explode=1&focus=front-wheel"]];
  const report = [];
  for (const [vpName, vw, vh] of VIEWPORTS) {
    const tiles = [];
    for (const [name, query] of models) {
      for (const [stateName, extra] of STATES) {
        const page = await browser.newPage();
        await page.setViewport({ width: vw, height: vh, deviceScaleFactor: 1 });
        const logs = [];
        page.on("console", (m) => { if (/viewer3d:/.test(m.text())) logs.push(m.text()); });
        try {
          await page.goto(`http://127.0.0.1:${port}/counter/solo.html?${query}${extra}`, { waitUntil: "load", timeout: 40000 });
          await page.waitForFunction(
            () => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready",
            { timeout: 70000 },
          ).catch(() => {});
          await new Promise((r) => setTimeout(r, 3200));
          const shot = Buffer.from(await page.screenshot({ encoding: "binary" }));
          // mean luminance of the frame, and of its darkest quarter, straight off the pixels
          const stats = await sharp(shot).resize(64, 64, { fit: "fill" }).raw().toBuffer({ resolveWithObject: true });
          let sum = 0;
          const lums = [];
          for (let i = 0; i < stats.data.length; i += stats.info.channels) {
            const l = (stats.data[i] * 0.2126 + stats.data[i + 1] * 0.7152 + stats.data[i + 2] * 0.0722) / 255;
            lums.push(l);
            sum += l;
          }
          lums.sort((a, b) => a - b);
          const mean = sum / lums.length;
          const dark = lums.slice(0, Math.floor(lums.length * 0.25)).reduce((a, b) => a + b, 0) / Math.max(1, Math.floor(lums.length * 0.25));
          const fps = await page.evaluate(() => (window.__viewer3d ? 1 : 1));
          tiles.push({ name: `${name} ${stateName}`, buffer: shot });
          report.push({ viewport: vpName, model: name, state: stateName, mean: +mean.toFixed(3), dark: +dark.toFixed(3), logs });
          console.log(`  ${vpName.padEnd(8)} ${name.padEnd(12)} ${stateName.padEnd(9)} mean ${mean.toFixed(3)} darkest-quarter ${dark.toFixed(3)}${logs.length ? "  " + logs[0].slice(0, 90) : ""}`);
        } catch (error) {
          console.log(`  !! ${vpName} ${name} ${stateName}: ${error.message.slice(0, 70)}`);
        }
        await page.close();
      }
    }
    if (tiles.length) {
      const CW = Math.round(vw / 2);
      const CH = Math.round(vh / 2);
      const cols = 3;
      const rows = Math.ceil(tiles.length / cols);
      const composed = await Promise.all(tiles.map(async (tile, i) => ({
        input: await sharp(tile.buffer).resize(CW, CH, { fit: "fill" }).composite([{
          input: Buffer.from(
            `<svg width="${CW}" height="22"><rect width="${CW}" height="22" fill="#141414"/>` +
            `<text x="6" y="16" font-family="monospace" font-size="13" fill="#fff">${tile.name}</text></svg>`),
          top: 0, left: 0,
        }]).png().toBuffer(),
        left: (i % cols) * CW,
        top: Math.floor(i / cols) * CH,
      })));
      const out = join(SHOTS, `explode-light-${vpName}.png`);
      await sharp({ create: { width: cols * CW, height: rows * CH, channels: 3, background: "#222" } })
        .composite(composed).png().toFile(out);
      console.log(`  -> ${out}`);
    }
  }
  await browser.close();
  server.close();
  const worst = report.filter((r) => r.mean < 0.12).map((r) => `${r.viewport}/${r.model}/${r.state}`);
  console.log(`
${report.length} renders · ${worst.length ? `TOO DARK: ${worst.join(", ")}` : "none below mean luminance 0.12"}`);
}

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
  // --rotations <model>: the same model at every plausible upright rotation, on one sheet.
  // Which way is up cannot be read reliably out of a bounding box (a scooter is nearly as wide
  // as it is tall), so the answer is chosen by looking, once, per model.
  if (process.argv.includes("--rotations")) {
    const name = only[0];
    const candidates = [
      "none", "-90,0,0", "90,0,0", "0,0,90", "0,0,-90",
      "0,90,90", "90,90,0", "-90,0,180", "0,90,0",
    ];
    return sheet(candidates.map((r) => [`${name} ${r}`, `model=generic/${name}&rotate=${encodeURIComponent(r)}`]));
  }
  /**
   * --states3 <model...>: default / exploded / focused, at phone and desktop, for every model.
   * This is the grid the founder's three reports live in — the exploded view being unreadable,
   * parts leaving the frame, the focus jumping — and none of them show up in a default render.
   * Each tile also carries the measured mean luminance of the model against its backdrop, so
   * "too dark" is a number in the log rather than an argument about a screenshot.
   */
  // --envs: every environment, with one exact and one generic model, at both viewports
  // --frames: frame-time trace around a focus. The founder's report was "it lags a bit and then
  // just teleports there", which is one long frame (shader compilation for the highlight
  // materials) with the camera tween running underneath it. This measures the long frame.
  if (process.argv.includes("--frames")) {
    const dir = join(WEB, "store", "models", "generic");
    const generics = readdirSync(dir)
      .filter((n) => existsSync(join(dir, n, "model.glb")))
      .map((n) => [n, `model=generic/${n}`]);
    const exact = [["yzf-2021", "model=yzf-2021"], ["cbr650r", "model=honda-cbr650r"], ["corvette", "model=corvette-c8"]];
    return frames(only.length ? generics.filter(([n]) => only.includes(n)) : [...generics, ...exact]);
  }
  if (process.argv.includes("--envs")) {
    const ENVS = ["auto_service", "autoshop_01", "studio_small_09", "empty_warehouse_01"];
    const MODELS = [["yzf", "model=yzf-2021"], ["naked", "model=generic/naked"]];
    const list = [];
    for (const env of ENVS) for (const [m, q] of MODELS) list.push([`${env} ${m}`, `${q}&env=${env}`]);
    return envs(list);
  }
  if (process.argv.includes("--states3")) {
    const dir = join(WEB, "store", "models", "generic");
    const generics = readdirSync(dir)
      .filter((n) => existsSync(join(dir, n, "model.glb")))
      .map((n) => [n, `model=generic/${n}`]);
    const exact = [["yzf-2021", "model=yzf-2021"], ["cbr650r", "model=honda-cbr650r"], ["corvette", "model=corvette-c8"]];
    const models = (only.length ? generics.filter(([n]) => only.includes(n)) : [...generics, ...exact]);
    return states3(models);
  }
  if (process.argv.includes("--sheet")) {
    const dir = join(WEB, "store", "models", "generic");
    const generics = readdirSync(dir)
      .filter((n) => existsSync(join(dir, n, "model.glb")))
      .map((n) => [n, `model=generic/${n}`]);
    const exact = [["yzf-2021", "model=yzf-2021"], ["cbr650r", "model=honda-cbr650r"], ["corvette", "model=corvette-c8"]];
    return sheet(only.length ? generics.filter(([n]) => only.includes(n)) : [...generics, ...exact]);
  }
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
