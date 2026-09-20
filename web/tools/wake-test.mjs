/**
 * "Mechanica." — how fast, and how often when nobody said it. Owner: voice agent.
 *
 *   node web/tools/wake-test.mjs            ten minutes of shop speech, live recogniser
 *   node web/tools/wake-test.mjs --minutes 2
 *
 * WHAT IS BEING MEASURED. Two numbers, and they pull against each other:
 *
 *   latency       from the last sample of "Mechanica, <something>" leaving the speaker to the
 *                 wake callback firing in the page. This is what he feels.
 *   false fires   how many times the matcher fired on ten minutes of shop talk that does NOT
 *                 summon it — including "the mechanic said", "mechanical fault", "mechanics",
 *                 which are the words a workshop actually contains.
 *
 * HOW. A ten-minute wav is built from aura-2 lines mixed with synthetic shop noise, twelve of
 * which begin with "Mechanica," at known offsets. Headless Chrome plays it into
 * `webkitSpeechRecognition` through `--use-file-for-fake-audio-capture`, which is the real
 * recogniser on the real audio path — Chrome's Web Speech works headlessly, verified before this
 * harness was written. The page runs js/voice-wake.js's own `heard()` over every result.
 *
 * THE HONEST PART. Chrome's recogniser is a network service with its own latency and its own
 * accuracy, and both vary by the hour. So the run reports the DISTRIBUTION, not one number, and
 * the false-fire count is reported against the transcript the recogniser actually produced —
 * which is the only thing `heard()` ever sees. A second, offline pass runs `heard()` over a fixed
 * corpus of shop sentences, so the matcher itself has a number that does not move.
 */

import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const CACHE = resolve(HERE, ".voice-echo");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER =
  process.env.PUPPETEER_DIR ||
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const KEYFILE = process.env.DEEPGRAM_KEY_FILE || "C:/Users/me/agent-secrets/deepgram.txt";

const RATE = 24000;
const MINUTES = Number((process.argv.find((a) => a.startsWith("--minutes")) || "").split("=")[1] || 0) ||
  Number(process.argv[process.argv.indexOf("--minutes") + 1]) || 10;

/** The twelve summons. Each is one breath: the word, then the thing he wants. */
const WAKES = [
  "Mechanica, I'm working on a YZF R1.",
  "Mechanica, what's the torque on the rear axle nut.",
  "Mechanica, open the manual.",
  "Mechanica, it's a 390 Duke, twenty twenty-four.",
  "Mechanica, chain is loose.",
  "Mechanica, show me the brake fluid page.",
  "Mechanica, next page.",
  "Mechanica, I've got a BMW R twelve GS on the lift.",
  "Mechanica, what oil does it take.",
  "Mechanica, open the parts list.",
  "Mechanica, go back.",
  "Mechanica, which page was that.",
];

/**
 * Ten minutes of a workshop that is NOT talking to the app — and deliberately full of the word
 * this thing is named after. If any of these fire, the toggle gets switched off within the hour.
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
];

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

/* ------------------------------------------------------------------ wav */

function wavHeader(samples) {
  const bytes = samples * 2;
  const head = Buffer.alloc(44);
  head.write("RIFF", 0);
  head.writeUInt32LE(36 + bytes, 4);
  head.write("WAVE", 8);
  head.write("fmt ", 12);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20);
  head.writeUInt16LE(1, 22);
  head.writeUInt32LE(RATE, 24);
  head.writeUInt32LE(RATE * 2, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write("data", 36);
  head.writeUInt32LE(bytes, 40);
  return head;
}

function writeWav(file, pcm) {
  const body = Buffer.alloc(pcm.length * 2);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    body.writeInt16LE(Math.round(s < 0 ? s * 0x8000 : s * 0x7fff), i * 2);
  }
  writeFileSync(file, Buffer.concat([wavHeader(pcm.length), body]));
}

function readWav(file) {
  const raw = readFileSync(file);
  let at = 12;
  while (at + 8 <= raw.length) {
    const id = raw.toString("ascii", at, at + 4);
    const size = raw.readUInt32LE(at + 4);
    if (id === "data") {
      const count = Math.floor(Math.min(size, raw.length - at - 8) / 2);
      const out = new Float32Array(count);
      for (let i = 0; i < count; i++) out[i] = raw.readInt16LE(at + 8 + i * 2) / 0x8000;
      return out;
    }
    at += 8 + size + (size % 2);
  }
  throw new Error(`no data chunk in ${file}`);
}

/** Broadband shop noise: a compressor two benches away, not a hiss generator. */
function shopNoise(samples, level) {
  const out = new Float32Array(samples);
  let lp = 0;
  for (let i = 0; i < samples; i++) {
    const white = Math.random() * 2 - 1;
    lp = lp * 0.96 + white * 0.04;
    // A slow throb on top: an air line cycling.
    const throb = 0.7 + 0.3 * Math.sin((i / RATE) * 2 * Math.PI * 0.35);
    out[i] = lp * 8 * level * throb;
  }
  return out;
}

async function speak(text, voice, file) {
  if (existsSync(file)) return file;
  const key = readFileSync(KEYFILE, "utf8").trim();
  const url = `https://api.deepgram.com/v1/speak?model=${voice}&encoding=linear16&sample_rate=${RATE}&container=wav`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Token ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`deepgram speak ${res.status}: ${(await res.text()).slice(0, 200)}`);
  writeFileSync(file, Buffer.from(await res.arrayBuffer()));
  return file;
}

function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

/* ------------------------------------------------------------------ server */

function serve() {
  return new Promise((done) => {
    const server = createServer((req, res) => {
      const path = decodeURIComponent((req.url || "/").split("?")[0]);
      if (path === "/" || path === "/wake.html") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end("<!doctype html><title>wake</title><body>");
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

/* ------------------------------------------------------------------ run */

async function main() {
  mkdirSync(CACHE, { recursive: true });

  // Every line, once, cached: a re-run costs nothing and the audio is identical, which is what
  // makes two runs comparable.
  const clips = new Map();
  for (const line of [...WAKES, ...SHOP]) {
    const file = join(CACHE, `say-${hash(line)}.wav`);
    await speak(line, "aura-2-orpheus-en", file);
    clips.set(line, readWav(file));
  }

  // Build the track: shop talk with a summons every ~50 s, 1.2 s of room between lines.
  const total = Math.round(RATE * 60 * MINUTES);
  const track = shopNoise(total, 0.045);
  const marks = [];
  let at = Math.round(RATE * 1.5);
  let wake = 0;
  let chat = 0;
  const every = Math.max(2, Math.round(WAKES.length ? (SHOP.length * MINUTES) / WAKES.length / 2 : 4));
  let sinceWake = 0;
  while (at < total - RATE * 6) {
    const summon = sinceWake >= every && wake < WAKES.length * Math.max(1, Math.round(MINUTES / 10));
    const line = summon ? WAKES[wake % WAKES.length] : SHOP[chat % SHOP.length];
    const pcm = clips.get(line);
    for (let i = 0; i < pcm.length && at + i < total; i++) {
      track[at + i] = Math.max(-1, Math.min(1, track[at + i] + pcm[i] * 0.75));
    }
    const endAt = at + pcm.length;
    if (summon) {
      // The clock starts at the LAST sample of the line: that is when he has finished saying it.
      marks.push({ line, endMs: (endAt / RATE) * 1000 });
      wake += 1;
      sinceWake = 0;
    } else {
      chat += 1;
      sinceWake += 1;
    }
    at = endAt + Math.round(RATE * 1.2);
  }
  const wav = join(CACHE, `wake-${MINUTES}m.wav`);
  writeWav(wav, track);
  console.log(`${MINUTES} min of shop audio: ${marks.length} summons, ${chat} other lines, ${wav}\n`);

  // The matcher on its own, against the transcripts it would ever be handed. No browser, no
  // network, no variance: this number is the matcher's and nothing else's.
  const { heard } = await import(`file:///${resolve(WEB, "counter/js/voice-wake.js").split("\\").join("/")}`);
  const falseCorpus = SHOP.flatMap((s) => [s, s.toLowerCase(), s.replace(/[.,]/g, "")]);
  const offlineFalse = falseCorpus.filter((s) => heard(s));
  const offlineHits = WAKES.filter((s) => heard(s));
  console.log(`matcher, offline: ${offlineHits.length}/${WAKES.length} summons matched, ${offlineFalse.length}/${falseCorpus.length} shop lines fired`);
  for (const bad of offlineFalse.slice(0, 5)) console.log(`   false: ${bad}`);

  const { server, port } = await serve();
  const puppeteer = (await import(`file:///${PUPPETEER.split("\\").join("/")}`)).default;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-audio-capture=${wav}`,
      "--autoplay-policy=no-user-gesture-required",
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
    ],
    protocolTimeout: (MINUTES + 3) * 60000,
  });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${port}/wake.html`, { waitUntil: "domcontentloaded" });

  const out = await page.evaluate(
    async (ms) => {
      const wake = await import("/counter/js/voice-wake.js");
      const fires = [];
      const results = [];
      const t0 = performance.now();
      // mountToggle wants the app's header; this page has none, so drive the listener the way
      // the toggle would. Same module, same recogniser, same heard().
      const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Ctor) return { fires, results, why: "no recogniser" };
      let rec = null;
      let last = 0;
      const start = () => {
        rec = new Ctor();
        rec.lang = "en-US";
        rec.continuous = true;
        rec.interimResults = true;
        rec.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const said = e.results[i][0].transcript;
            results.push({ t: Math.round(performance.now() - t0), said, final: e.results[i].isFinal });
            const hit = wake.heard(said);
            if (!hit) continue;
            const now = performance.now();
            if (now - last < 2500) continue;
            if (!e.results[i].isFinal && !hit.rest) continue;
            last = now;
            fires.push({ t: Math.round(now - t0), said, rest: hit.rest });
          }
        };
        rec.onend = () => {
          if (performance.now() - t0 < ms) setTimeout(start, 200);
        };
        rec.onerror = () => {};
        try {
          rec.start();
        } catch {
          setTimeout(start, 400);
        }
      };
      start();
      await new Promise((r) => setTimeout(r, ms));
      try {
        rec.stop();
      } catch {
        /* done */
      }
      return { fires, results, why: "" };
    },
    Math.round(MINUTES * 60000) + 4000,
  );

  await browser.close();
  server.close();

  // Match each fire to the summons it followed. A fire more than 6 s after any summons, or with
  // no summons before it, is a false start.
  const lat = [];
  const used = new Set();
  let falsePositive = 0;
  for (const fire of out.fires) {
    const mark = marks.find((m, i) => !used.has(i) && fire.t >= m.endMs - 1500 && fire.t <= m.endMs + 6000 && (used.add(i), true));
    if (mark) lat.push(Math.round(fire.t - mark.endMs));
    else falsePositive += 1;
  }
  lat.sort((a, z) => a - z);
  const pick = (p) => (lat.length ? lat[Math.min(lat.length - 1, Math.floor(lat.length * p))] : null);

  console.log(`\nlive: ${out.results.length} recogniser results, ${out.fires.length} fires against ${marks.length} summons`);
  console.log(`woke on ${lat.length}/${marks.length}, missed ${marks.length - lat.length}, false starts ${falsePositive}`);
  if (lat.length) {
    console.log(`latency ms  min ${lat[0]}  median ${pick(0.5)}  p90 ${pick(0.9)}  max ${lat[lat.length - 1]}`);
  }
  console.log(`false starts per 10 min: ${(falsePositive / MINUTES) * 10}`);
  for (const fire of out.fires.slice(0, 4)) console.log(`   fired at ${fire.t} ms on "${fire.said.trim()}" -> "${fire.rest}"`);
  if (process.env.WAKE_DUMP) {
    for (const r of out.results.filter((r) => /me[ck]/i.test(r.said)).slice(0, 25)) console.log(`   heard ${r.t} ${r.final ? "F" : "i"} "${r.said.trim()}"`);
  }

  let bad = 0;
  const say = (ok, line) => {
    if (!ok) bad += 1;
    console.log((ok ? "\n  ok   " : "\n  FAIL ") + line);
  };
  say(offlineHits.length === WAKES.length, `the matcher takes every summons (${offlineHits.length}/${WAKES.length})`);
  say(offlineFalse.length === 0, `and no shop line at all (${offlineFalse.length}/${falseCorpus.length})`);
  say(falsePositive === 0, `no false start in ${MINUTES} minutes of shop talk (${falsePositive})`);
  say(lat.length >= Math.ceil(marks.length * 0.5), `it wakes on most of them (${lat.length}/${marks.length})`);
  console.log(bad ? `\n${bad} failed` : "\nall clear");
  process.exit(bad ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
