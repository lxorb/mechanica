/**
 * "Mechanica." — what fires it, what does not, and how long the app takes. Owner: voice agent.
 *
 *   node web/tools/wake-test.mjs
 *
 * WHAT COULD NOT BE MEASURED, AND WHY IT IS SAID FIRST.
 *
 * The plan was ten minutes of shop audio through `--use-file-for-fake-audio-capture` into a live
 * `webkitSpeechRecognition`. It does not work, and the way it fails is worth writing down:
 * **Chrome's SpeechRecognition does not use the WebRTC capture path**, so
 * `--use-fake-device-for-media-stream` does not apply to it. It opened this machine's real
 * microphone instead and transcribed the room — the first run came back with a colleague's
 * conversation, which is both a useless measurement and a thing no harness should ever do. The
 * live-recogniser section was deleted rather than left in with a caveat.
 *
 * So Chrome's own recognition latency is NOT measured here. What Chrome contributes is the delay
 * before an interim result carrying the word arrives, which it does not document and which
 * varies with its speech service; on a real device that interim lands while the sentence is
 * still being spoken, which is the whole reason js/voice-wake.js acts on interims at all.
 *
 * WHAT IS MEASURED — both of them things this code is actually responsible for:
 *
 *   1. THE MATCHER, offline. js/voice-wake.js's own `heard()` against every way a mechanic says
 *      it, and against a workshop's worth of sentences containing "mechanic", "mechanical",
 *      "mechanics" and "mechanic's" — the words a real shop says every ten minutes.
 *
 *   2. THE PIPELINE, in headless Chrome, end to end. A scripted recogniser replays the
 *      interim/final sequence Chrome produces for one spoken sentence, and the clock runs from
 *      the first transcript that carries the word to `InjectUserMessage` leaving for Deepgram
 *      with the rest of his sentence in it. Everything in between is ours.
 */

import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const SHOTS = resolve(WEB, "..", "docs", "voice", "orb");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER =
  process.env.PUPPETEER_DIR ||
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

/** Every way a mechanic summons it, and the sentence he expects to carry with it. */
const WAKES = [
  ["Mechanica, I'm working on a YZF R1.", "I'm working on a YZF R1."],
  ["mechanica what's the torque on the rear axle nut", "what's the torque on the rear axle nut"],
  ["Mechanica. Open the manual.", "Open the manual."],
  ["mechanika it's a 390 duke twenty twenty four", "it's a 390 duke twenty twenty four"],
  ["mecanica chain is loose", "chain is loose"],
  ["Mechanica, show me the brake fluid page.", "show me the brake fluid page."],
  ["mechanic a next page", "next page"],
  ["Mechanica, I've got a BMW R twelve GS on the lift.", "I've got a BMW R twelve GS on the lift."],
  ["hey mechanica what oil does it take", "what oil does it take"],
  ["Mechanica — go back", "go back"],
];

/**
 * A workshop that is NOT talking to the app, written to be as hostile as the real thing: a shop
 * says "mechanic" all day. If any of these fire, the toggle gets switched off within the hour
 * and the feature is dead.
 */
const SHOP = [
  "Can you pass me the fifteen millimetre socket.",
  "The mechanic said he'd look at it after lunch.",
  "It's a mechanical fault, not the electronics.",
  "We've got three mechanics in today and four bikes.",
  "Put it on the lift and drain the oil first.",
  "That's a hundred newton metres, no more.",
  "The chain slack is way out of spec on this one.",
  "Did anyone order the brake pads for the Duke.",
  "It's mechanically sound, it just needs a service.",
  "Tell him it'll be ready Thursday afternoon.",
  "The customer says it's been making a noise since Tuesday.",
  "Torque it down and we'll road test it.",
  "Where did I put the manual for the R twelve.",
  "That's a mechanic's job, not mine.",
  "Coolant's low again, check the hoses.",
  "He's a good mechanic but he's slow.",
  "Ask the mechanic about the mechanical seal.",
  "Mechanically it's fine, cosmetically it's a mess.",
  "Two mechanics, one lift, all afternoon.",
  "The mechanics of it are simple enough.",
];

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".glb": "model/gltf-binary",
};

function serve() {
  return new Promise((done) => {
    const server = createServer((req, res) => {
      const path = decodeURIComponent((req.url || "/").split("?")[0]);
      if (path.startsWith("/fakeapi/")) {
        const tail = path.slice("/fakeapi".length);
        let body = {};
        if (tail === "/health") body = { ok: true };
        else if (tail === "/catalog") body = [];
        else if (tail === "/voice/config") body = { deepgram: true, elevenlabsAgentId: null };
        else if (tail === "/voice/deepgram-token") body = { scheme: "token", key: "stub" };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(body));
        return;
      }
      const file = normalize(join(WEB, path));
      if (!file.startsWith(WEB) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
        "Content-Length": statSync(file).size,
      });
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

async function main() {
  mkdirSync(SHOTS, { recursive: true });

  /* ---- 1. the matcher, offline ---- */
  const url = `file:///${resolve(WEB, "counter/js/voice-wake.js").split("\\").join("/")}`;
  const { heard } = await import(url);

  const clean = (s) => s.toLowerCase().replace(/[^a-z0-9 ]/g, "").replace(/\s+/g, " ").trim();
  const missed = WAKES.filter(([said]) => !heard(said));
  const wrongRest = WAKES.filter(([said, want]) => {
    const hit = heard(said);
    return hit && clean(hit.rest) !== clean(want);
  });
  // Case and punctuation are the recogniser's, not his: every line is tried three ways.
  const corpus = SHOP.flatMap((s) => [s, s.toLowerCase(), s.replace(/[.,']/g, "")]);
  const fired = corpus.filter((s) => heard(s));

  console.log(`matcher: ${WAKES.length - missed.length}/${WAKES.length} summons taken, rest extracted right on ${WAKES.length - wrongRest.length}`);
  console.log(`         ${fired.length}/${corpus.length} shop lines fired (${SHOP.length} sentences x 3 spellings)\n`);
  for (const [said] of missed) console.log(`   missed: ${said}`);
  for (const [said] of wrongRest) console.log(`   rest wrong: ${said} -> "${heard(said).rest}"`);
  for (const bad of fired.slice(0, 6)) console.log(`   FALSE: ${bad}`);

  let bad = 0;
  const say = (ok, line) => {
    if (!ok) bad += 1;
    console.log((ok ? "  ok   " : "  FAIL ") + line);
  };
  say(missed.length === 0, `every summons is taken (${WAKES.length - missed.length}/${WAKES.length})`);
  say(wrongRest.length === 0, `and the sentence after it comes out whole (${WAKES.length - wrongRest.length}/${WAKES.length})`);
  say(fired.length === 0, `no shop line fires it (${fired.length}/${corpus.length}, "the mechanic said" and "mechanical fault" included)`);

  /* ---- 2. the pipeline, in a browser ---- */
  const { server, port } = await serve();
  const puppeteer = (await import(`file:///${PUPPETEER.split("\\").join("/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox",
      "--hide-scrollbars",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
    ],
    protocolTimeout: 120000,
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.evaluateOnNewDocument((base) => {
    window.TTM_API = base;
  }, `http://127.0.0.1:${port}/fakeapi`);
  await page.goto(`http://127.0.0.1:${port}/counter/index.html`, { waitUntil: "domcontentloaded" });

  const run = await page.evaluate(async () => {
    const log = [];
    const mark = (what, extra) => log.push(Object.assign({ what, t: performance.now() }, extra || {}));

    /* The Deepgram socket, stubbed: what is being timed is our side of it. */
    class Stub {
      static OPEN = 1;
      constructor() {
        this.readyState = 0;
        window.__sock = this;
        setTimeout(() => {
          this.readyState = 1;
          if (this.onopen) this.onopen({});
        }, 5);
      }
      json(m) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(m) });
      }
      send(data) {
        if (typeof data !== "string") return;
        let msg = {};
        try {
          msg = JSON.parse(data);
        } catch {
          return;
        }
        if (msg.type === "Settings") {
          this.json({ type: "Welcome", request_id: "wake" });
          this.json({ type: "SettingsApplied" });
          return;
        }
        if (msg.type === "InjectUserMessage") mark("injected", { said: msg.content });
      }
      close() {
        this.readyState = 3;
      }
      addEventListener() {}
      removeEventListener() {}
    }
    window.WebSocket = Stub;

    /**
     * A scripted recogniser. The sequence and the gaps are the shape Chrome produces for one
     * spoken sentence: a handful of growing interims, then one final. Nothing here pretends to
     * measure Chrome's own delay - the clock starts at the interim that first carries the word,
     * which is the first moment our code could possibly know anything.
     */
    const SCRIPT = [
      [0, "mechanica", false],
      [180, "mechanica I'm", false],
      [360, "mechanica I'm working", false],
      [540, "mechanica I'm working on a", false],
      [720, "mechanica I'm working on a YZF", false],
      [900, "mechanica I'm working on a YZF R1", false],
      [1300, "Mechanica, I'm working on a YZF R1.", true],
    ];
    class FakeRec {
      constructor() {
        this.continuous = false;
        this.interimResults = false;
        this.lang = "";
        this.running = false;
        window.__rec = this;
      }
      start() {
        this.running = true;
        for (const [at, said, final] of SCRIPT) {
          setTimeout(() => {
            if (!this.running || !this.onresult) return;
            const alt = { transcript: said };
            const result = [alt];
            result.isFinal = final;
            if (!seen.length) mark("spoken");
            seen.push([Math.round(performance.now()), said, final]);
            this.onresult({ resultIndex: 0, results: [result] });
          }, at);
        }
      }
      stop() {
        this.running = false;
        if (this.onend) this.onend();
      }
      abort() {
        this.stop();
      }
      addEventListener() {}
      removeEventListener() {}
    }
    window.SpeechRecognition = FakeRec;
    window.webkitSpeechRecognition = FakeRec;

    const agent = await import("/counter/js/voice-deepgram.js");
    agent.tuning.settings = {
      url: "wss://stub/agent",
      sampleRate: 24000,
      pages: 0,
      session: "wake-session",
      settings: { type: "Settings" },
    };
    const voice = await import("/counter/js/voice-session.js");
    const wake = await import("/counter/js/voice-wake.js");
    window.__voice = voice;
    window.__wake = wake;

    const seen = [];
    const button = wake.mountToggle((hit) => {
      // The app's own two-stage join, inlined: see js/app.js.
      if (!hit.final) {
        mark("opened", { rest: hit.rest });
        voice.start({});
        return;
      }
      mark("woke", { rest: hit.rest });
      voice.ask(hit.rest);
    });
    const bar = document.querySelector("header.ticket");
    const mounted = Boolean(button) && button.parentElement === bar;
    const beforeTheme =
      mounted && button.nextElementSibling === document.querySelector("[data-theme-button]");

    // Off by default, and the toggle is the gesture the microphone needs.
    const offAtFirst = button.getAttribute("aria-pressed") === "false";
    button.click();
    const onAfterTap = button.getAttribute("aria-pressed") === "true";

    await new Promise((r) => setTimeout(r, 2800));

    const wokeAt = log.find((r) => r.what === "woke");
    const openedAt = log.find((r) => r.what === "opened");
    const injected = log.find((r) => r.what === "injected");
    const spoken = log.find((r) => r.what === "spoken");

    // While the session is live the wake listener must be off: two recognisers on one microphone
    // is a fight nobody wins, and the agent's own voice would trigger it.
    const pausedWhileLive = voice.isLive() && !wake.listening();
    voice.stop();
    await new Promise((r) => setTimeout(r, 300));
    const backAfterEnd = wake.enabled() && wake.listening();

    return {
      mounted,
      beforeTheme,
      offAtFirst,
      onAfterTap,
      rest: wokeAt ? wokeAt.rest : "",
      said: injected ? injected.said : "",
      openMs: openedAt && spoken ? Math.round(openedAt.t - spoken.t) : null,
      wakeMs: wokeAt && spoken ? Math.round(wokeAt.t - spoken.t) : null,
      injectMs: wokeAt && injected ? Math.round(injected.t - wokeAt.t) : null,
      openedRest: openedAt ? openedAt.rest : null,
      totalMs: spoken && injected ? Math.round(injected.t - spoken.t) : null,
      pausedWhileLive,
      backAfterEnd,
      seen,
    };
  });

  say(run.mounted && run.beforeTheme, "the toggle is in the ticket bar, beside the theme disc");
  say(run.offAtFirst && run.onAfterTap, "off by default, on by a tap - which is also the gesture the mic needs");
  say(clean(run.rest) === clean("I'm working on a YZF R1"), `the sentence after the word is what goes in ("${run.rest}")`);
  say(run.said === run.rest, `and it reaches the socket as one user turn ("${run.said}")`);
  say(run.openMs != null && run.openMs <= 120, `first transcript with the word -> socket opening: ${run.openMs} ms`);
  say(run.wakeMs != null, `word heard -> settled sentence in hand: ${run.wakeMs} ms (the recogniser's wait, not ours)`);
  say(run.injectMs != null && run.injectMs <= 1500, `session start -> his sentence on the wire: ${run.injectMs} ms`);
  say(run.totalMs != null, `end to end, our side of it: ${run.totalMs} ms`);
  say(run.pausedWhileLive, "it stops listening while the Deepgram session has the microphone");
  say(run.backAfterEnd, "and picks it up again when the session ends");
  say(errors.length === 0, `no console errors${errors.length ? ": " + errors.slice(0, 2).join(" | ") : ""}`);

  if (process.env.WAKE_DUMP) console.log(JSON.stringify(run.seen));
  await page.screenshot({ path: join(SHOTS, "wake-toggle-phone.png"), clip: { x: 0, y: 0, width: 390, height: 110 } });

  await browser.close();
  server.close();
  console.log(bad ? `\n${bad} failed` : "\nall clear");
  process.exit(bad ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
