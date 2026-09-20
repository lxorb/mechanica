/**
 * Drives the chat view and voice mode in headless Chrome and saves web/docs-shots/voice-*.png.
 * Owner: voice-mode agent. Pairs with counter/js/chat-ui.js and counter/js/voice-deepgram.js.
 *
 *   node web/tools/voice-shots.mjs                 # needs web on :5201 and the API on :8017
 *
 * Headless Chrome has no microphone, so --use-fake-device-for-media-stream hands the page a
 * synthetic input and the turn is typed into the LIVE session instead, through the same
 * InjectUserMessage the Deepgram docs describe: the socket, the Settings message, the mic
 * pipeline, the function calls and the playback buffer are all the real ones.
 *
 * /voice/deepgram-token is fulfilled locally with the account key, because that key cannot mint
 * a browser credential (no keys:write on the project) and the endpoint honestly 502s. The key
 * never leaves this machine and never reaches a deployed page.
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

const browser = await puppeteer.launch({
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

const page = await browser.newPage();
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text().slice(0, 200));
});
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));

await page.setRequestInterception(true);
page.on("request", async (req) => {
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
  // the query-string manual id, so for this run only it goes back into the parameters where the
  // old handlers expect it. Everything else in the Settings message is untouched.
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

await page.evaluateOnNewDocument((api) => {
  window.TTM_API = api;
}, API);

async function openChat() {
  await page.goto(`${WEB}/counter/`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => window.HandyBus && window.Q, { timeout: 30000 });
  await page.evaluate((id) => {
    window.HandyBus.state.bikeId = id;
    window.HandyBus.go("pick");
  }, BIKE);
  await page.waitForFunction(() => {
    const pill = document.querySelector('[data-screen="pick"] .chat-pill');
    return pill && !pill.hidden;
  }, { timeout: 30000 });
  await page.evaluate(() => document.querySelector(String.raw`[data-screen="pick"] .chat-pill`).click());
  await page.waitForSelector('[data-overlay="chat"].open .cv-body deep-chat', { timeout: 20000 });
  await wait(700);
}

async function shoot(name) {
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
  console.log("shot  ", `${name}.png`);
}

async function runVoice() {
  await page.waitForFunction(() => {
    const b = document.querySelector(".cv-voice");
    return b && !b.hidden;
  }, { timeout: 20000 });
  await page.evaluate(() => document.querySelector(".cv-voice").click());
  await page.waitForFunction(() => {
    const s = document.querySelector(".cv-said");
    return s && /Listening|Speaking|Thinking/.test(s.textContent || "");
  }, { timeout: 30000 });
  console.log("voice  listening");
  await wait(1200);
}

async function injectTurn() {
  const sent = await page.evaluate(async (text) => {
    const mod = await import("/counter/js/voice-deepgram.js");
    return mod.inject(text);
  }, ASK);
  console.log("inject", sent);
  await page.waitForFunction(
    () => {
      const host = document.querySelector(".cv-body deep-chat");
      const root = host && host.shadowRoot;
      if (!root) return false;
      return root.querySelectorAll(".ai-message .message-bubble").length > 0;
    },
    { timeout: 45000 }
  );
  await wait(1500);
  return page.evaluate(() => {
    const root = document.querySelector(".cv-body deep-chat").shadowRoot;
    return [...root.querySelectorAll(".message-bubble")].map((n) => n.textContent.trim()).filter(Boolean);
  });
}

// ---------------------------------------------------------------- phone

await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await openChat();
await shoot("voice-chat-390");
await runVoice();
await shoot("voice-listening-390");
const phoneTurns = await injectTurn();
await shoot("voice-answer-390");
console.log("turns  ", JSON.stringify(phoneTurns, null, 1));
await page.evaluate(() => document.querySelector(".cv-voice").click());
await wait(400);

// ---------------------------------------------------------------- desktop

await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
await openChat();
await shoot("voice-chat-1280");
await runVoice();
const deskTurns = await injectTurn();
await shoot("voice-answer-1280");
console.log("turns  ", JSON.stringify(deskTurns, null, 1));

console.log("errors ", errors.length ? errors : "none");
await browser.close();
