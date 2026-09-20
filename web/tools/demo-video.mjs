/**
 * demo-video.mjs — records the two demo takes on the LIVE site. Owner: demo-video agent.
 * Writes docs/pitches/video/*.webm, *.mp4, the contact sheets and SHOTLIST.md.
 *
 *   node web/tools/demo-video.mjs            # both takes
 *   node web/tools/demo-video.mjs 1          # take 1 only (the product path)
 *   node web/tools/demo-video.mjs 2          # take 2 only (the cold manual)
 *   node web/tools/demo-video.mjs --dry      # drive the path, write no video
 *   node web/tools/demo-video.mjs --keep-raw # keep the CRF-12 capture next to the finals
 *
 * Everything is driven through the real UI — a click on the search field, keystrokes with a
 * human delay, a wheel to zoom, a drag to orbit the bike — so the recording is a mechanic's
 * session and not a scripted state machine. The two places that cheat are named in SHOTLIST.md:
 * the smooth scrolls are animated in the page (a synthetic wheel scrolls in jerky notches), and
 * the book's pinch-zoom arrives as the ctrl+wheel event the same handler listens for.
 *
 * Why the live site and not a local server: the point of the video is that these numbers came
 * off the deployed thing. A judge who pauses on a frame should see the same URL they can open.
 *
 * Bitrate. puppeteer's screencast hard-codes `-b:v 0`, so its VP9 is quality-targeted and a
 * mostly-static UI lands around 1 Mbps — below what the submission asks for. The capture is
 * therefore taken at CRF 12 (visually lossless for screen content) and re-encoded once to a
 * fixed 8 Mbps, which is also what produces the .mp4.
 *
 * Cold bike. Take 2 needs a vehicle with a free manual URL and no index yet; the first run
 * warms it forever. The list is re-read from the live catalog at record time and the first
 * still-cold year is used, so a re-run picks the next one instead of filming a cached bar.
 */

import { mkdirSync, existsSync, readFileSync, writeFileSync, rmSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const OUT = join(REPO, "docs", "pitches", "video");
const SCRATCH = process.env.TTM_SCRATCH
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER = process.env.PUPPETEER_DIR || `${SCRATCH}/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js`;
const SHARP = process.env.SHARP_DIR || `${SCRATCH}/node_modules/sharp/dist/index.cjs`;
const LIVE = process.env.TTM_LIVE || "https://mechanica.emilvinu.ch";
const APP = `${LIVE}/counter/`;

const W = 1280;
const H = 720;
const FPS = 24;
const CAPTURE_CRF = 12;
const TARGET_BPS = "8M";

const DRY = process.argv.includes("--dry");
const KEEP_RAW = process.argv.includes("--keep-raw");
const ONLY = process.argv.slice(2).filter((a) => /^[12]$/.test(a)).map(Number);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ff = (args) => spawnSync("ffmpeg", args, { encoding: "utf8" });
const secs = (n) => `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(Math.floor(n % 60)).padStart(2, "0")}`;

/* ------------------------------------------------------------------ the take recorder */

/**
 * A take is a list of beats and the clock they happened on. `mark()` is called at the moment the
 * thing is on screen and settled, not when the click was issued, so a presenter who seeks to the
 * printed timestamp lands on the state, not on the transition into it.
 */
function makeTake(name) {
  const beats = [];
  let t0 = 0;
  return {
    name,
    beats,
    start() { t0 = Date.now(); },
    mark(title, note) {
      const t = t0 ? (Date.now() - t0) / 1000 : 0;
      beats.push({ t, title, note: note || "" });
      console.log(`    ${secs(t)}  ${title}${note ? ` — ${note}` : ""}`);
    },
    get seconds() { return t0 ? (Date.now() - t0) / 1000 : 0; },
  };
}

/* ------------------------------------------------------------------ page helpers */

/** A human pause. Every state gets one so the presenter has somewhere to talk. */
const dwell = (ms) => sleep(ms);

/**
 * `TTM_TRACE=1` prints how long each wait actually took. The takes have a hard 2:30 ceiling and
 * the only thing that ever threatens it is a wait that quietly runs to its timeout, which looks
 * identical to a slow network in the finished video.
 */
const TRACE = Boolean(process.env.TTM_TRACE);
async function waited(label, promise) {
  const t = Date.now();
  const out = await promise.catch((e) => {
    if (TRACE) console.log(`      ~ ${label}: FAILED ${String(e.message || e).slice(0, 60)}`);
    return null;
  });
  if (TRACE) console.log(`      ~ ${label}: ${((Date.now() - t) / 1000).toFixed(1)} s`);
  return out;
}

async function type(page, text, delay = 115) {
  await page.keyboard.type(text, { delay });
}

/** Click a real element at its centre, through the mouse, so the recording shows a real click. */
async function tap(page, selector, { deep = false } = {}) {
  const box = await page.evaluate((sel, pierce) => {
    const find = () => {
      if (!pierce) return document.querySelector(sel);
      const stack = [document.documentElement];
      while (stack.length) {
        const n = stack.pop();
        if (!n) continue;
        if (n.matches && n.matches(sel)) return n;
        if (n.shadowRoot) stack.push(...n.shadowRoot.children);
        if (n.children) stack.push(...n.children);
      }
      return null;
    };
    const el = find();
    if (!el) return null;
    el.scrollIntoView({ block: "nearest" });
    const b = el.getBoundingClientRect();
    if (b.width < 2 || b.height < 2) return null;
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }, selector, deep);
  if (!box) throw new Error(`no clickable ${selector}`);
  await page.mouse.move(box.x, box.y, { steps: 12 });
  await sleep(140);
  await page.mouse.click(box.x, box.y);
  return box;
}

/** Scroll a container the way a thumb does: eased, ~700 ms, not a jump. */
async function glide(page, selector, delta, ms = 900) {
  await page.evaluate(
    (sel, d, duration) =>
      new Promise((done) => {
        const el = sel === "window" ? document.scrollingElement : document.querySelector(sel);
        if (!el) return done();
        const from = el.scrollTop;
        const t0 = performance.now();
        const step = (now) => {
          const p = Math.min(1, (now - t0) / duration);
          const eased = p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2;
          el.scrollTop = from + d * eased;
          if (p < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    selector,
    delta,
    ms,
  );
}

/**
 * Tap a heading row. The top hit is already selected when the results land, and pick.js reads a
 * click on the selected row as "open it" — so tapping it blind would skip the beat it was meant
 * to show. This only clicks rows that are not lit.
 */
async function tapHit(page, index) {
  const box = await page.evaluate((i) => {
    const rows = [...document.querySelectorAll(".hit")];
    const row = rows[i];
    if (!row || row.classList.contains("is-on")) return null;
    row.scrollIntoView({ block: "nearest" });
    const b = row.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }, index);
  if (!box) return false;
  await page.mouse.move(box.x, box.y, { steps: 10 });
  await sleep(150);
  await page.mouse.click(box.x, box.y);
  return true;
}

/**
 * One step of the book's pinch zoom, centred on the last marker. It arrives as the ctrl+wheel
 * event the reader already listens for — a trackpad pinch and a phone pinch both reach the same
 * handler. Zooming back out this way rather than with a double-click is deliberate: a click on
 * the sheet also toggles the immersive bar, which would hide ALL and PARTS for the next beat.
 */
async function pinch(page, deltaY) {
  await page.evaluate((d) => {
    const v = document.querySelector(".page-view");
    const ms = [...document.querySelectorAll('.page-sheet[data-page="77"] .mark')];
    const m = ms[ms.length - 1];
    if (!v) return;
    const b = m ? m.getBoundingClientRect() : v.getBoundingClientRect();
    v.dispatchEvent(
      new WheelEvent("wheel", {
        deltaY: d,
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
        clientX: b.x + b.width / 2,
        clientY: b.y + b.height / 2,
      }),
    );
  }, deltaY);
}

/** Whichever Back is on screen — the book runs fullscreen and folds the ticket bar away. */
async function backTo(page, hash, tries = 5) {
  for (let i = 0; i < tries; i++) {
    const at = await page.evaluate(() => location.hash);
    if (at === hash) return true;
    await page.evaluate(() => {
      const bar = document.querySelector(".bar-back");
      const ticket = document.querySelector("[data-back]");
      const visible = (el) => el && el.offsetParent !== null && el.getBoundingClientRect().width > 2;
      (visible(bar) ? bar : visible(ticket) ? ticket : bar || ticket)?.click();
    });
    await sleep(1200);
  }
  return (await page.evaluate(() => location.hash)) === hash;
}

/** Orbit the 3D stage with a slow pointer drag. */
async function orbit(page, dx = 210, ms = 1700) {
  const box = await page.evaluate(() => {
    const v = document.querySelector(".viewer3d canvas") || document.querySelector(".viewer3d");
    if (!v) return null;
    const b = v.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  });
  if (!box) return;
  const steps = 34;
  await page.mouse.move(box.x - dx / 2, box.y);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(box.x - dx / 2 + (dx * i) / steps, box.y + Math.sin((i / steps) * Math.PI) * 10);
    await sleep(ms / steps);
  }
  await page.mouse.up();
}

/* ------------------------------------------------------------------ take 1: the product */

async function takeOne(page, take) {
  take.start();
  take.mark("Landing", "one search field, 29,890 vehicles behind it");
  await dwell(2000);

  await tap(page, ".id-q");
  await type(page, "2024 390");
  await dwell(2200);
  take.mark("Model cards", "photo cards while the query is still ambiguous");
  await dwell(900);

  await type(page, " duke");
  // The landing jumps by itself once one bike has been the only candidate for 400 ms; Enter is
  // the other way in, and the one a mechanic uses. Whichever fires first, we end up on Confirm.
  await dwell(900);
  if ((await page.evaluate(() => location.hash)) !== "#confirm") await page.keyboard.press("Enter");
  await page.waitForFunction(() => location.hash === "#confirm", { timeout: 30000 });
  await page.waitForFunction(
    () => !!document.querySelector('section[data-screen="confirm"] button[aria-label="Yes"]'),
    { timeout: 30000 },
  );
  await dwell(1800);
  take.mark("Confirm", "KTM 390 DUKE 2024 — the hero photo and the manual it carries");
  await dwell(2000);

  await tap(page, 'section[data-screen="confirm"] button[aria-label="Yes"]');
  await page.waitForFunction(() => location.hash === "#pick", { timeout: 60000 });
  // Capped, not patient: past this the ring is more honest than a video that misses its ceiling.
  await waited(
    "3D stage",
    page.waitForFunction(() => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready", {
      timeout: 40000,
    }),
  );
  await dwell(3600);
  take.mark("Pick · the 3D stage", "the model idles into a slow spin after three seconds, then a drag");
  await dwell(900);
  await orbit(page);
  await dwell(2400);

  await tap(page, ".ask-q");
  await type(page, "chain is loose", 118);
  await dwell(450);
  await page.keyboard.press("Enter");
  await waited("headings", page.waitForFunction(() => document.querySelectorAll(".hit").length > 0, { timeout: 60000 }));
  await dwell(1700);
  take.mark("The manual's own headings", "12.12 p.77–78 and 12.13 p.78 — KTM's section numbers, not ours");
  await dwell(1500);

  take.mark("Exploded view, chain lit", "the bike explodes and the drive chain lights under the top heading");
  await dwell(2100);
  await tapHit(page, 1);
  await dwell(1900);
  take.mark("The second heading", "12.13 Adjusting the chain tension — the 3D focus follows the heading");
  await dwell(1300);
  await tapHit(page, 0);
  await dwell(1900);

  await tap(page, ".open");
  await page.waitForFunction(() => location.hash.startsWith("#book"), { timeout: 60000 });
  await waited(
    "page 77 + marks",
    page.waitForFunction(() => document.querySelectorAll('.page-sheet[data-page="77"] .mark').length >= 2, {
      timeout: 45000,
    }),
  );
  await dwell(1300);
  take.mark("Page 77 of KTM's manual", "the printed page, orange markers on the two answering lines");
  await dwell(2400);

  // one pinch step onto the two lines that answer, then centre them
  await pinch(page, -260);
  await dwell(900);
  await page.evaluate(() => {
    const v = document.querySelector(".page-view");
    const ms = [...document.querySelectorAll('.page-sheet[data-page="77"] .mark')];
    if (!v || ms.length < 2) return;
    const a = ms[ms.length - 2].getBoundingClientRect();
    const b = ms[ms.length - 1].getBoundingClientRect();
    const box = v.getBoundingClientRect();
    v.scrollTop += (a.y + b.y + b.height) / 2 - (box.y + box.height / 2);
    v.scrollLeft += (a.x + a.width / 2 + b.x + b.width / 2) / 2 - (box.x + box.width / 2);
  });
  await dwell(1100);
  take.mark("The marked lines", "measure the chain tension · Chain tension 7 … 10 mm (0.28 … 0.39 in)");
  await dwell(3000);

  await pinch(page, 260);
  await dwell(1200);

  await tap(page, ".book-all");
  await waited(
    "all pages",
    page.waitForFunction(() => document.querySelectorAll(".page-sheet").length > 20, { timeout: 20000 }),
  );
  await dwell(1300);
  take.mark("All pages", "143 sheets — the whole book, when he wants it");
  await glide(page, ".page-view", 1100, 1400);
  await dwell(1400);

  await tap(page, ".book-parts");
  await waited("parts", page.waitForFunction(() => document.querySelectorAll(".pv-tile").length > 10, { timeout: 60000 }));
  await dwell(1600);
  take.mark("Parts", "135 parts, each one on the list because the manual prints a spec for it");
  await glide(page, ".pv-tiles", 420, 1000);
  await dwell(1000);
  await glide(page, ".pv-tiles", -420, 800);

  await tap(page, ".pv-q");
  await type(page, "chain", 130);
  await dwell(1200);
  const tile = await page.evaluate(() => {
    const tiles = [...document.querySelectorAll(".pv-tile")];
    const exact = tiles.find((n) => (n.querySelector(".pv-name")?.textContent || "").trim().toLowerCase() === "chain");
    const t = exact || tiles[0];
    if (!t) return null;
    t.scrollIntoView({ block: "center" });
    const b = t.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2, name: (t.querySelector(".pv-name")?.textContent || "").trim() };
  });
  if (tile) {
    await page.mouse.move(tile.x, tile.y, { steps: 10 });
    await sleep(160);
    await page.mouse.click(tile.x, tile.y);
  }
  await waited("offers", page.waitForFunction(() => document.querySelectorAll(".pv-offer").length > 0, { timeout: 60000 }));
  await dwell(1800);
  take.mark("Drive chain", `${tile ? tile.name : "Chain"} · 5/8 x 1/4" (520) X-ring · p.126 · live USD offers`);
  await glide(page, ".pv-detail", 190, 900);
  await dwell(2600);

  // out of Parts, out of the book, back to the bike
  await page.evaluate(() => document.querySelector(".pv-x")?.click());
  await dwell(1000);
  await backTo(page, "#pick");
  await dwell(1200);

  await tap(page, ".chat-pill");
  await page.waitForFunction(
    () => {
      const stack = [document.documentElement];
      while (stack.length) {
        const n = stack.pop();
        if (!n) continue;
        if (n.id === "text-input") return true;
        if (n.shadowRoot) stack.push(...n.shadowRoot.children);
        if (n.children) stack.push(...n.children);
      }
      return false;
    },
    { timeout: 40000 },
  );
  await dwell(1200);
  take.mark("Chat", "the one place it may write a sentence — and only with page numbers in it");
  await tap(page, "#text-input", { deep: true });
  await type(page, "what's the torque on the rear axle nut", 80);
  await dwell(600);
  await page.keyboard.press("Enter");
  await page
    .waitForFunction(
      () => {
        const stack = [document.documentElement];
        while (stack.length) {
          const n = stack.pop();
          if (!n) continue;
          if (n.classList && n.classList.contains("cite-chip")) return true;
          if (n.shadowRoot) stack.push(...n.shadowRoot.children);
          if (n.children) stack.push(...n.children);
        }
        return false;
      },
      { timeout: 90000 },
    )
    .catch(() => {});
  await dwell(1500);
  take.mark("The answer, with its page", "Rear wheel spindle nut: 100 Nm (73.8 lbf ft) [p. 130] + the p.130 chip");
  await dwell(3000);

  await page.evaluate(() => document.querySelector(".cv-x")?.click());
  await dwell(1300);

  for (let i = 0; i < 2; i++) {
    await tap(page, "[data-theme-button]");
    await dwell(1700);
    const id = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    take.mark(`Theme · ${id}`, "a theme is colours and nothing else; every screen keeps working");
    await dwell(900);
  }

  await backTo(page, "#identify");
  await page.evaluate(() => {
    const q = document.querySelector(".id-q");
    if (q && q.value) {
      q.focus();
      q.value = "";
      q.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  await dwell(1200);
  take.mark("Back to the search field", "one field, and the next bike");
  await dwell(1800);
}

/* ------------------------------------------------------------------ take 2: the cold manual */

/** The first MT-07 year the live catalog still has no index for. */
async function coldBike() {
  const rows = await fetch(`${LIVE}/api/catalog`, { headers: { Accept: "application/json" } }).then((r) => r.json());
  const family = rows.filter((r) => /^yamaha-mt07-(19|20)\d\d$/.test(r.id) && r.manualUrl && !r.manualId);
  const preferred = family.find((r) => r.id === "yamaha-mt07-2018");
  const pick = preferred || family.sort((a, b) => b.year - a.year)[0];
  if (!pick) throw new Error("no cold MT-07 left in the catalog");
  return pick;
}

async function takeTwo(page, take, bike) {
  take.start();
  take.mark("Landing", "a bike the app has never fetched a manual for");
  await dwell(2200);

  await tap(page, ".id-q");
  await type(page, "mt-07");
  await page.waitForFunction(() => document.querySelectorAll(".id-card").length > 0, { timeout: 30000 });
  await dwell(2400);
  take.mark("Cards, cold and warm", "the flag on each card says whether a manual is already indexed");
  await dwell(1600);

  const card = await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".id-card")];
    const t = cards.find((n) => (n.querySelector(".id-model")?.textContent || "").trim().toUpperCase() === "MT07") || cards[0];
    if (!t) return null;
    const b = t.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  });
  await page.mouse.move(card.x, card.y, { steps: 12 });
  await sleep(140);
  await page.mouse.click(card.x, card.y);
  await page.waitForFunction(() => document.querySelectorAll(".id-year").length > 0, { timeout: 30000 });
  await dwell(2200);
  take.mark("Every year Yamaha built it", "orange chips are indexed, outlined chips are not");
  await dwell(1800);

  const chip = await page.evaluate((year) => {
    const y = [...document.querySelectorAll(".id-year")].find((n) => n.textContent.trim() === String(year));
    if (!y) return null;
    y.scrollIntoView({ block: "center" });
    const b = y.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }, bike.year);
  if (!chip) throw new Error(`no year chip ${bike.year}`);
  await page.mouse.move(chip.x, chip.y, { steps: 10 });
  await sleep(140);
  await page.mouse.click(chip.x, chip.y);
  await page.waitForFunction(() => location.hash === "#confirm", { timeout: 30000 });
  await dwell(2400);
  take.mark(`Confirm · ${bike.make} ${bike.model} ${bike.year}`, "no manual on our servers, four minutes ago or ever");
  await dwell(2000);

  const t0 = Date.now();
  await tap(page, 'section[data-screen="confirm"] button[aria-label="Yes"]');
  take.mark("The fetch starts", "Yamaha's own PDF, pulled and read for the first time");
  const seen = new Set();
  for (let i = 0; i < 160; i++) {
    await sleep(900);
    const p = await page.evaluate(() => ({
      hash: location.hash,
      title: document.querySelector(".confirm-work-title")?.textContent || "",
      width: document.querySelector(".confirm-bar i")?.style.width || "",
    }));
    const pct = Number.parseFloat(p.width) || 0;
    for (const step of [25, 50, 75, 95]) {
      if (pct >= step && !seen.has(step)) {
        seen.add(step);
        take.mark(`Progress ${step}%`, `${p.title || "reading the manual"} — ${((Date.now() - t0) / 1000).toFixed(0)} s in`);
      }
    }
    if (p.hash === "#pick") break;
  }
  const ingest = (Date.now() - t0) / 1000;
  await page
    .waitForFunction(() => document.querySelector(".viewer3d")?.getAttribute("data-viewer3d") === "ready", {
      timeout: 90000,
    })
    .catch(() => {});
  await dwell(2200);
  take.mark("Searchable", `${ingest.toFixed(1)} s from tap to a manual with an index`);
  await dwell(2600);

  await tap(page, ".ask-q");
  await type(page, "oil", 140);
  await dwell(500);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll(".hit").length > 0, { timeout: 60000 }).catch(() => {});
  await dwell(2200);
  take.mark("A question against a manual that was cold", "Yamaha's own headings, on a book nobody had indexed");
  await dwell(2400);

  await tap(page, ".hit");
  await dwell(2200);
  await tap(page, ".open");
  await page.waitForFunction(() => location.hash.startsWith("#book"), { timeout: 60000 });
  await page
    .waitForFunction(() => document.querySelectorAll(".page-sheet.is-ready").length > 0, { timeout: 120000 })
    .catch(() => {});
  await dwell(2400);
  take.mark("The page", "the same printed page, out of a PDF that was not on our servers a minute ago");
  await dwell(3400);
  return { ingest, bike };
}

/* ------------------------------------------------------------------ encoding + sheets */

function probe(file) {
  const r = spawnSync(
    "ffprobe",
    ["-v", "error", "-show_entries", "format=duration,size,bit_rate", "-show_entries", "stream=codec_name,width,height,avg_frame_rate", "-of", "json", file],
    { encoding: "utf8" },
  );
  if (r.status !== 0) return null;
  try {
    const j = JSON.parse(r.stdout);
    const s = (j.streams || []).find((x) => x.width) || {};
    return {
      duration: Number(j.format?.duration) || 0,
      size: Number(j.format?.size) || 0,
      bitrate: Number(j.format?.bit_rate) || 0,
      codec: s.codec_name,
      w: s.width,
      h: s.height,
      fps: s.avg_frame_rate,
    };
  } catch {
    return null;
  }
}

function encode(raw, webm, mp4) {
  console.log("  encoding webm @ 8 Mbps…");
  const a = ff([
    "-y", "-loglevel", "error", "-i", raw,
    "-c:v", "libvpx-vp9", "-b:v", TARGET_BPS, "-minrate", "6M", "-maxrate", "12M",
    "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-threads", "8",
    "-pix_fmt", "yuv420p", "-r", String(FPS), "-an", webm,
  ]);
  if (a.status !== 0) console.log("  !! webm encode:", (a.stderr || "").slice(0, 300));
  console.log("  encoding mp4 @ 8 Mbps…");
  const b = ff([
    "-y", "-loglevel", "error", "-i", raw,
    "-c:v", "libx264", "-b:v", TARGET_BPS, "-maxrate", "10M", "-bufsize", "16M",
    "-preset", "medium", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", String(FPS),
    "-movflags", "+faststart", "-an", mp4,
  ]);
  if (b.status !== 0) console.log("  !! mp4 encode:", (b.stderr || "").slice(0, 300));
}

/** Twelve labelled frames, 4x3, so a judge can see the whole take without playing it. */
async function contactSheet(video, beats, duration, out) {
  const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
  const picks = [];
  if (beats.length >= 12) {
    for (let i = 0; i < 12; i++) picks.push(beats[Math.round((i * (beats.length - 1)) / 11)]);
  } else {
    for (let i = 0; i < 12; i++) {
      const t = (duration * (i + 0.5)) / 12;
      const near = [...beats].reverse().find((b) => b.t <= t) || beats[0] || { title: "", t };
      picks.push({ t, title: near.title });
    }
  }
  const CW = 426;
  const CH = 240;
  const tiles = [];
  for (let i = 0; i < picks.length; i++) {
    const at = Math.max(0.2, Math.min(duration - 0.3, picks[i].t + 0.9));
    const png = join(SCRATCH, `sheet-${i}.png`);
    const r = ff(["-y", "-loglevel", "error", "-ss", at.toFixed(2), "-i", video, "-frames:v", "1", png]);
    if (r.status !== 0 || !existsSync(png)) continue;
    const label = `${secs(picks[i].t)}  ${picks[i].title}`.replace(/[<>&]/g, "").slice(0, 46);
    tiles.push(
      await sharp(readFileSync(png))
        .resize(CW, CH, { fit: "fill" })
        .composite([
          {
            input: Buffer.from(
              `<svg width="${CW}" height="24"><rect width="${CW}" height="24" fill="#111"/>` +
                `<text x="7" y="17" font-family="monospace" font-size="13" fill="#e85d04">${label}</text></svg>`,
            ),
            top: CH - 24,
            left: 0,
          },
        ])
        .png()
        .toBuffer(),
    );
    rmSync(png, { force: true });
  }
  if (!tiles.length) return 0;
  await sharp({ create: { width: CW * 4, height: CH * 3, channels: 3, background: "#1a1a1a" } })
    .composite(tiles.map((input, i) => ({ input, left: (i % 4) * CW, top: Math.floor(i / 4) * CH })))
    .png()
    .toFile(out);
  return tiles.length;
}

/* ------------------------------------------------------------------ run */

/**
 * A throwaway tab that opens the manual and the parts list once, so the recorded tab gets the
 * PDF and the parts catalogue out of the HTTP cache instead of making the video sit on a
 * progress ring. It deliberately never touches Pick: a second WebGL context on this box makes
 * the recorded one take three times longer to come up, or hang the tab outright — which is
 * worse than the ring it was meant to save. Take 2 is never warmed; the cold fetch is its point.
 */
async function warm(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  try {
    await page.goto(APP, { waitUntil: "load", timeout: 90000 });
    await page.waitForSelector(".id-q", { timeout: 90000 });
    await page.evaluate(async () => {
      await import("/counter/js/screens/book.js");
      await import("/counter/js/screens/invoice.js");
      const bus = await import("/counter/js/bus.js");
      bus.set({ bikeId: "ktm-390-duke-2024", jobId: "ktm-390-duke-2024/chain-tension-check" });
      bus.go("book");
    });
    await page
      .waitForFunction(() => document.querySelectorAll('.page-sheet[data-page="77"] .mark').length >= 2, {
        timeout: 120000,
      })
      .catch(() => {});
    await page.evaluate(() => document.querySelector(".book-parts")?.click());
    await page.waitForFunction(() => document.querySelectorAll(".pv-tile").length > 10, { timeout: 60000 }).catch(() => {});
    await sleep(1200);
  } catch {
    /* a cold cache only costs the video a few seconds of ring */
  }
  await page.close();
  await sleep(1500);
}

async function record(which, fn) {
  const puppeteer = await import(`file:///${PUPPETEER.replace(/\\/g, "/")}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    protocolTimeout: 240000,
    args: [
      "--no-sandbox",
      "--hide-scrollbars",
      "--enable-unsafe-swiftshader",
      "--use-gl=angle",
      "--force-device-scale-factor=1",
      `--window-size=${W},${H}`,
    ],
  });
  if (which.warm) await warm(browser);
  const page = await browser.newPage();
  // Workshop, not Night: headless reports a dark system and the video would open on the one
  // theme that is not the product's own.
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("mechanica.theme", "workshop");
    } catch {
      /* private mode */
    }
  });
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.slice(0, 120)));

  const take = makeTake(which.name);
  let recorder = null;
  const raw = join(SCRATCH, `${which.file}.raw.webm`);
  let extra = null;
  try {
    // The load is outside the take: nobody wants to watch a service worker boot.
    await page.goto(APP, { waitUntil: "load", timeout: 90000 });
    await page.waitForSelector(".id-q", { timeout: 90000 });
    await sleep(900);
    if (!DRY) {
      recorder = await page.screencast({ path: raw, fps: FPS, quality: CAPTURE_CRF });
      await sleep(500);
    }
    extra = await fn(page, take);
  } finally {
    if (recorder) await recorder.stop();
    await browser.close();
  }
  if (errors.length) console.log(`  page errors: ${[...new Set(errors)].slice(0, 3).join(" | ")}`);
  return { take, raw, extra };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  mkdirSync(SCRATCH, { recursive: true });
  const report = [];

  const plan = [
    {
      n: 1,
      name: "Take 1 — the product path",
      file: "take-1-product",
      warm: true,
      run: (page, take) => takeOne(page, take),
    },
    {
      n: 2,
      name: "Take 2 — a manual nobody had indexed",
      file: "take-2-ondemand",
      run: async (page, take) => takeTwo(page, take, await coldBike()),
    },
  ].filter((p) => !ONLY.length || ONLY.includes(p.n));

  for (const which of plan) {
    console.log(`\n${which.name}`);
    if (which.n === 2 && !DRY) {
      const bike = await coldBike();
      console.log(`  cold bike: ${bike.id} (${bike.manualUrl.slice(0, 70)}…)`);
      which.run = (page, take) => takeTwo(page, take, bike);
    }
    const { take, raw, extra } = await record(which, which.run);
    if (DRY) {
      report.push({ take, extra });
      continue;
    }
    const webm = join(OUT, `${which.file}.webm`);
    const mp4 = join(OUT, `${which.file}.mp4`);
    const rawInfo = probe(raw);
    console.log(`  capture: ${(statSync(raw).size / 1e6).toFixed(1)} MB, ${rawInfo ? rawInfo.duration.toFixed(1) : "?"} s`);
    encode(raw, webm, mp4);
    const info = probe(webm);
    const infoMp4 = probe(mp4);
    const sheet = join(OUT, `${which.file}-sheet.png`);
    const n = await contactSheet(webm, take.beats, info ? info.duration : take.seconds, sheet);
    if (!KEEP_RAW) rmSync(raw, { force: true });
    console.log(
      `  -> ${webm}  ${info ? `${info.duration.toFixed(1)} s · ${(info.bitrate / 1e6).toFixed(1)} Mbps · ${(info.size / 1e6).toFixed(1)} MB` : "probe failed"}`,
    );
    console.log(`  -> ${mp4}   ${infoMp4 ? `${infoMp4.duration.toFixed(1)} s · ${(infoMp4.bitrate / 1e6).toFixed(1)} Mbps` : ""}`);
    console.log(`  -> ${sheet}  (${n} frames)`);
    report.push({ file: which.file, name: which.name, take, info, infoMp4, sheet: n, extra });
  }

  if (!DRY && report.length) writeShotlist(report);
}

function writeShotlist(report) {
  const path = join(OUT, "SHOTLIST.md");
  const old = existsSync(path) ? readFileSync(path, "utf8") : "";
  const kept = old.includes("<!-- takes -->") ? old.split("<!-- takes -->")[0] : "";
  const out = [];
  out.push(kept || header());
  out.push("<!-- takes -->");
  for (const r of report) {
    const dur = r.info ? r.info.duration : r.take.seconds;
    out.push(`\n## ${r.name}\n`);
    out.push(
      `\`${r.file}.webm\` — **${secs(dur)}**, ${r.info ? `${(r.info.bitrate / 1e6).toFixed(1)} Mbps, ${(r.info.size / 1e6).toFixed(1)} MB, ${r.info.w}×${r.info.h}` : ""}. ` +
        `\`${r.file}.mp4\` is the same take, H.264${r.infoMp4 ? `, ${(r.infoMp4.bitrate / 1e6).toFixed(1)} Mbps` : ""}. ` +
        `Contact sheet: \`${r.file}-sheet.png\`.\n`,
    );
    out.push("| time | beat | what is on screen |");
    out.push("|---|---|---|");
    for (const b of r.take.beats) out.push(`| **${secs(b.t)}** | ${b.title} | ${b.note} |`);
  }
  out.push("");
  writeFileSync(path, out.join("\n"), "utf8");
  console.log(`\n-> ${path}`);
}

function header() {
  return `# Demo video — shot list

Recorded on the live site, https://mechanica.emilvinu.ch/counter/, in headless Chrome at
1280×720. No narration and no captions: the presenter talks over it. Re-record with
\`node web/tools/demo-video.mjs\`.

`;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
