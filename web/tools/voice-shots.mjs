/**
 * Drives the chat view and voice mode in headless Chrome and saves web/docs-shots/voice-*.png.
 * Owner: voice-mode agent. Pairs with counter/js/chat-ui.js and counter/js/voice-deepgram.js.
 *
 *   node web/tools/voice-shots.mjs                 # both viewports
 *   ONLY=390 node web/tools/voice-shots.mjs        # just the phone
 *
 * Needs web on :5201 and the API on :8017, and the API must advertise an https PUBLIC_BASE —
 * Deepgram calls the tool endpoints from its own servers and refuses http:
 *   PUBLIC_BASE=https://mechanica.emilvinu.ch/api uvicorn app.main:app --port 8017
 *
 * Headless Chrome has no microphone, so --use-fake-device-for-media-stream hands the page a
 * synthetic input and the turn is typed into the LIVE session instead, through the same
 * InjectUserMessage the Deepgram docs describe: the socket, the Settings message, the mic
 * pipeline, the function calls and the playback buffer are all the real ones.
 *
 * /voice/deepgram-token is fulfilled locally with the account key, because that key cannot mint
 * a browser credential (no keys:write on the project) and the endpoint honestly 502s. The key
 * never leaves this machine and never reaches a deployed page.
 *
 * It also measures the input row and photographs it on its own (voice-input-row-*.png): field
 * flex-1, VOICE 44x44, SEND 44x44, 8 px gaps, one baseline.
 */

import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = join(resolve(HERE, ".."), "docs-shots");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER =
  process.env.PUPPETEER_DIR ||
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const WEB = process.env.WEB_ORIGIN || "http://127.0.0.1:5201";
const API = process.env.API_ORIGIN || "http://127.0.0.1:8017";
const BIKE = "ktm-390-duke-2024";
const ASK = "what is the front tyre pressure?";
const KEY = readFileSync("C:/Users/me/agent-secrets/deepgram.txt", "utf8").trim();

const { default: puppeteer } = await import(pathToFileURL(PUPPETEER).href);
if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const launch = () =>
  puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    protocolTimeout: 180000,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      "--no-sandbox",
    ],
  });

const errors = [];
let browser = null;
let page = null;

async function newPage() {
  const tab = await browser.newPage();
  tab.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text().slice(0, 200));
  });
  tab.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));

  await tab.setRequestInterception(true);
  tab.on("request", async (req) => {
    if (req.method() === "POST" && req.url().endsWith("/voice/deepgram-token")) {
      await req.respond({
        status: 200,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify({ key: KEY, expiresIn: 600, scheme: "token" }),
      });
      return;
    }
    // Deepgram calls the tool endpoints from its own servers, so they have to be the DEPLOYED
    // ones (run this API with PUBLIC_BASE=https://mechanica.emilvinu.ch/api). That build predates
    // the query-string manual id, so for this run only it goes back into the parameters where
    // the old handlers expect it. Everything else in the Settings message is untouched.
    if (req.url().includes("/voice/agent-settings")) {
      const res = await fetch(req.url());
      const body = await res.json();
      for (const fn of body?.settings?.agent?.think?.functions || []) {
        if (!fn.endpoint) continue;
        const id = new URL(fn.endpoint.url).searchParams.get("manualId");
        fn.parameters.properties.manualId = { type: "string", description: `Always exactly "${id}".` };
        fn.parameters.required = [...new Set([...(fn.parameters.required || []), "manualId"])];
      }
      await req.respond({
        status: res.status,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify(body),
      });
      return;
    }
    req.continue();
  });

  await tab.evaluateOnNewDocument((api) => {
    window.TTM_API = api;
  }, API);
  return tab;
}

async function openChat() {
  await page.goto(`${WEB}/counter/`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => window.HandyBus && window.Q, { timeout: 60000 });
  await page.evaluate((id) => {
    window.HandyBus.state.bikeId = id;
    window.HandyBus.go("pick");
  }, BIKE);
  await page.waitForFunction(() => {
    const pill = document.querySelector('[data-screen="pick"] .chat-pill');
    return pill && !pill.hidden;
  }, { timeout: 60000 });
  await page.evaluate(() => document.querySelector(String.raw`[data-screen="pick"] .chat-pill`).click());
  await page.waitForSelector('[data-overlay="chat"].open .cv-body deep-chat', { timeout: 20000 });
  await wait(700);
}

async function shoot(name) {
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
  console.log("shot  ", `${name}.png`);
}

/** The input row, measured and photographed on its own: the founder's alignment check. */
async function inputRow(tag) {
  const box = await page.evaluate(() => {
    const root = document.querySelector(".cv-body deep-chat").shadowRoot;
    const row = root.querySelector("#input");
    const r = row.getBoundingClientRect();
    const items = [...row.children]
      .filter((c) => c.getBoundingClientRect().width > 0)
      .map((c) => {
        const b = c.getBoundingClientRect();
        const el = c.classList.contains("input-button-container") ? c.firstElementChild || c : c;
        const eb = el.getBoundingClientRect();
        return {
          what: c.id || (c.classList.contains("ttm-voice") ? "voice" : "send"),
          x: Math.round(eb.x),
          y: Math.round(eb.y),
          w: Math.round(eb.width),
          h: Math.round(eb.height),
        };
      });
    return { row: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }, items };
  });
  console.log("row   ", JSON.stringify(box));
  const gaps = [];
  for (let i = 1; i < box.items.length; i++) gaps.push(box.items[i].x - (box.items[i - 1].x + box.items[i - 1].w));
  console.log("gaps  ", gaps, "| tops", box.items.map((i) => i.y), "| heights", box.items.map((i) => i.h));
  await page.screenshot({
    path: join(SHOTS, `voice-input-row-${tag}.png`),
    clip: { x: box.row.x, y: box.row.y - 6, width: box.row.w, height: box.row.h + 12 },
  });
  console.log("shot  ", `voice-input-row-${tag}.png`);
  return box;
}

const bubbles = () =>
  page.evaluate(() => {
    const host = document.querySelector(".cv-body deep-chat");
    const root = host && host.shadowRoot;
    if (!root) return [];
    return [...root.querySelectorAll(".message-bubble")].map((n) => n.textContent.trim()).filter(Boolean);
  });

async function runVoice() {
  await page.waitForFunction(() => {
    const b = document.querySelector(".cv-body deep-chat").shadowRoot.querySelector(".cv-voice");
    return b && !b.hidden;
  }, { timeout: 30000 });
  await page.evaluate(() => document.querySelector(".cv-body deep-chat").shadowRoot.querySelector(".cv-voice").click());
  await page.waitForFunction(() => {
    const s = document.querySelector(".cv-said");
    return s && (s.textContent || "").trim() && !/Connecting/.test(s.textContent);
  }, { timeout: 40000 }).catch(async () => {
    console.log("voice  STUCK:", await page.evaluate(() => document.querySelector(".cv-said").textContent), errors.slice(-6));
    throw new Error("voice never started");
  });
  console.log("voice ", await page.evaluate(() => document.querySelector(".cv-said").textContent));
  await wait(1200);
}

/** The session is live; type the turn into it and wait for a spoken answer to land as a bubble. */
async function injectTurn() {
  const before = (await bubbles()).length;
  const sent = await page.evaluate(async (text) => {
    const mod = await import("/counter/js/voice-deepgram.js");
    return mod.inject(text);
  }, ASK);
  console.log("inject", sent);
  // greeting + the question + at least one answer sentence
  await page.waitForFunction((n) => {
    const host = document.querySelector(".cv-body deep-chat");
    const root = host && host.shadowRoot;
    return Boolean(root) && root.querySelectorAll(".message-bubble").length >= n;
  }, { timeout: 90000 }, before + 2);
  await wait(2500);
  return bubbles();
}

// ---------------------------------------------------------------- the two passes

/**
 * Each viewport gets a browser of its own. Reusing one leaves a live AudioContext, a WebGL
 * stage and an open agent socket behind, and headless Chrome then either refuses the next
 * screenshot or takes the renderer down with it. The pause after is for Deepgram, which does
 * not like the next session opening on the heels of the last one.
 */
async function pass(tag, viewport) {
  browser = await launch();
  page = await newPage();
  await page.setViewport(viewport);
  await openChat();
  await shoot(`voice-chat-${tag}`);
  await inputRow(tag);
  await runVoice();
  await shoot(`voice-listening-${tag}`);
  const turns = await injectTurn();
  await shoot(`voice-answer-${tag}`);
  console.log("turns  ", JSON.stringify(turns, null, 1));
  await browser.close();
  await wait(4000);
}

const ONLY = process.env.ONLY || "";
if (!ONLY || ONLY === "390") await pass("390", { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
if (!ONLY || ONLY === "1280") await pass("1280", { width: 1280, height: 800, deviceScaleFactor: 1 });

console.log("errors ", errors.length ? errors : "none");
