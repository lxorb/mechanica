/**
 * Does the agent hear itself? Owner: voice agent.
 *
 *   node web/tools/voice-echo.mjs            both runs, both verdicts
 *   node web/tools/voice-echo.mjs --keep     leave the generated wavs in place
 *
 * THE BUG. "It is like detecting itself making sound in a loop." The phone's speaker is 20 cm
 * from its microphone, so while the agent talks the mic hears the agent, and every one of those
 * frames used to be forwarded to Deepgram. Deepgram's VAD cannot tell our voice from his: it
 * answered its own greeting with UserStartedSpeaking, the client flushed the answer it had just
 * scheduled, and the first syllable of the replacement answer started the same loop again.
 *
 * HOW THIS REPRODUCES IT. Headless Chrome with `--use-fake-device-for-media-stream` and
 * `--use-file-for-fake-audio-capture=<wav>`, where the wav is aura-2 speaking the agent's own
 * lines - so the microphone of this browser hears nothing but the agent, which is the worst case
 * of the real room. The Deepgram socket is stubbed IN THE PAGE rather than dialled: the stub
 * streams the same aura-2 audio down as the agent's voice, runs the same kind of VAD Deepgram
 * runs over whatever the client sends up, and emits UserStartedSpeaking when it hears a voice.
 * That is the whole loop, deterministic, at no cost, with every event timestamped.
 *
 * WHAT IS MEASURED, PER RUN
 *   mic frames forwarded while the agent was audible   (the loop's fuel)
 *   UserStartedSpeaking the stub raised from our own output   (the loop itself)
 *   answers cut by one of those                              (what the rider hears)
 *   the applied getUserMedia constraints, from track.getSettings()
 *   the playback route the client chose
 *
 * TWO RUNS, ONE BINARY. `--legacy` sets `tuning.guard = false` inside voice-deepgram.js, which is
 * the code path as it shipped: forward every mic frame, duck on a fixed RMS. Same wav, same stub,
 * same VAD - the only difference is the guard, so the difference in the numbers is the guard's.
 *
 * AND A REAL BARGE-IN. The second wav is quiet agent echo for three seconds and then a DIFFERENT
 * aura-2 voice at speaking level over the top. The guard has to let that through, and the number
 * that matters is how long after the loud onset the first mic frame reaches the socket.
 *
 * HONEST LIMIT. A fake capture device is not an acoustic loop: Chrome's echo canceller has
 * nothing to subtract here, because the file it is fed was never in the room. So this harness
 * measures the guard and the thresholds, which is what the fix is; it cannot measure AEC. The
 * constraints are read back from getSettings() and reported, not credited.
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
/** What the microphone hears of our own speaker, past the device's canceller. RMS, 0..1. */
const ECHO_RMS = 0.022;
/** A man a foot from the phone, shouting over it. */
const RIDER_RMS = 0.095;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webp": "image/webp",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".glb": "model/gltf-binary",
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

/** Every wav here is one we wrote or Deepgram wrote: 16-bit mono, header then data. */
function readWav(file) {
  const raw = readFileSync(file);
  let at = 12;
  while (at + 8 <= raw.length) {
    const id = raw.toString("ascii", at, at + 4);
    const size = raw.readUInt32LE(at + 4);
    if (id === "data") {
      // Deepgram streams its wav, so the header is written before the length is known and the
      // data chunk claims more bytes than the file holds. Trust the file.
      const count = Math.floor(Math.min(size, raw.length - at - 8) / 2);
      const out = new Float32Array(count);
      for (let i = 0; i < count; i++) out[i] = raw.readInt16LE(at + 8 + i * 2) / 0x8000;
      return out;
    }
    at += 8 + size + (size % 2);
  }
  throw new Error(`no data chunk in ${file}`);
}

function rmsOf(pcm) {
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i];
  return Math.sqrt(sum / (pcm.length || 1));
}

/** Scale a clip so its RMS over the parts that are not silence is `want`. */
function normalise(pcm, want) {
  let sum = 0;
  let n = 0;
  for (let i = 0; i < pcm.length; i++) {
    if (Math.abs(pcm[i]) < 0.004) continue;
    sum += pcm[i] * pcm[i];
    n += 1;
  }
  const have = Math.sqrt(sum / (n || 1)) || 1;
  const k = want / have;
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = Math.max(-1, Math.min(1, pcm[i] * k));
  return out;
}

function loop(pcm, samples) {
  const out = new Float32Array(samples);
  for (let i = 0; i < samples; i++) out[i] = pcm[i % pcm.length];
  return out;
}

/* ------------------------------------------------------------------ tts */

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

/* ------------------------------------------------------------------ server */

function serve(settings) {
  return new Promise((done) => {
    const server = createServer((req, res) => {
      const [path] = (req.url || "/").split("?");
      // The app's own backend, reduced to the three answers voice mode needs. There is no API in
      // front of this harness and there does not need to be one: the Settings message is the
      // server's business and the loop is not.
      if (path.startsWith("/fakeapi/")) {
        const tail = path.slice("/fakeapi".length);
        let body = {};
        if (tail === "/health") body = { ok: true };
        else if (tail === "/catalog") body = [];
        else if (tail === "/voice/config") body = { deepgram: true, elevenlabsAgentId: null };
        // 127.0.0.1 is "localhost" to the client, so it takes the no-Worker path and asks for a
        // short-lived key. The socket is stubbed; the key is never used and never leaves here.
        else if (tail === "/voice/deepgram-token") body = { scheme: "token", key: "stub" };
        else if (tail === "/voice/agent-settings") body = settings;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(body));
        return;
      }
      const file = normalize(join(WEB, decodeURIComponent(path)));
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

/* ------------------------------------------------------------------ the page */

/**
 * Everything below runs inside the tab. It stubs the Deepgram socket, starts a real session from
 * the real module, and hands back a log.
 *
 * The stub is written to be Deepgram, not to be kind: it runs a VAD over whatever the client
 * sends it and raises UserStartedSpeaking when that VAD says a person is talking, exactly as the
 * real socket does. If the client forwards its own echo, the stub interrupts the client's own
 * answer - which is the bug, reproduced from first principles rather than asserted.
 */
async function drive(page, opts) {
  return page.evaluate(async (o) => {
    const log = [];
    const mark = (type, extra) => log.push(Object.assign({ type, t: Math.round(performance.now()) }, extra || {}));

    /* ---- the agent's voice, as Int16 frames ---- */
    const speech = Int16Array.from(o.agent);
    const FRAME = 1024;

    /* ---- the stub socket ---- */
    class Stub {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      constructor() {
        this.readyState = 0;
        this.binaryType = "blob";
        this.onopen = null;
        this.onmessage = null;
        this.onerror = null;
        this.onclose = null;
        this.at = 0; // where in `speech` the current turn is
        this.timer = 0;
        this.turn = 0;
        this.loudMs = 0;
        this.vadArmed = false;
        window.__stub = this;
        setTimeout(() => {
          this.readyState = 1;
          if (this.onopen) this.onopen({});
        }, 5);
      }
      json(msg) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(msg) });
      }
      bin(buf) {
        if (this.onmessage) this.onmessage({ data: buf });
      }
      /** One spoken turn, paced in real time, 1024 samples at a go - the real chunk size. */
      speak() {
        this.turn += 1;
        this.at = 0;
        this.vadArmed = true;
        this.loudMs = 0;
        mark("agent-turn", { turn: this.turn });
        const tick = () => {
          if (this.readyState !== 1) return;
          if (this.at >= speech.length) {
            this.timer = 0;
            this.json({ type: "AgentAudioDone" });
            return;
          }
          const slice = speech.slice(this.at, this.at + FRAME);
          this.at += FRAME;
          this.bin(slice.buffer.slice(slice.byteOffset, slice.byteOffset + slice.byteLength));
          this.timer = setTimeout(tick, (FRAME / o.rate) * 1000);
        };
        this.json({ type: "ConversationText", role: "assistant", content: "Page 78, one hundred newton metres." });
        tick();
      }
      cut() {
        if (this.timer) clearTimeout(this.timer);
        this.timer = 0;
      }
      /** Deepgram's side of the loop: a VAD over what the client sends up. */
      heard(buffer) {
        const pcm = new Int16Array(buffer);
        let sum = 0;
        for (let i = 0; i < pcm.length; i++) sum += (pcm[i] / 32768) * (pcm[i] / 32768);
        const rms = Math.sqrt(sum / (pcm.length || 1));
        const ms = (pcm.length / o.rate) * 1000;
        const talking = this.timer !== 0 || this.at < speech.length;
        mark("up", { rms: Number(rms.toFixed(4)), ms: Math.round(ms), talking });
        if (rms < o.vad) {
          this.loudMs = 0;
          return;
        }
        this.loudMs += ms;
        if (this.loudMs < o.vadMs || !this.vadArmed) return;
        this.loudMs = 0;
        this.vadArmed = false;
        const cutMid = this.timer !== 0;
        mark("UserStartedSpeaking", { cutMid, turn: this.turn });
        this.cut();
        this.json({ type: "UserStartedSpeaking" });
        // A real agent answers the thing it just heard. That answer is what loops.
        setTimeout(() => {
          if (this.readyState === 1) this.speak();
        }, 700);
      }
      send(data) {
        if (typeof data === "string") {
          let msg = {};
          try {
            msg = JSON.parse(data);
          } catch {
            return;
          }
          if (msg.type === "Settings") {
            this.json({ type: "Welcome", request_id: "stub" });
            this.json({ type: "SettingsApplied" });
            setTimeout(() => this.speak(), 250);
          }
          return;
        }
        this.heard(data);
      }
      close() {
        this.readyState = 3;
        this.cut();
      }
      addEventListener() {}
      removeEventListener() {}
    }
    window.WebSocket = Stub;

    /* ---- the real client ---- */
    const agent = await import("/counter/js/voice-deepgram.js");
    if (o.legacy) agent.tuning.guard = false;

    const handle = await agent.start({
      manualId: "stub",
      bikeId: "stub",
      on: (e) => mark(e.type === "status" ? `status:${e.value}` : e.type, e.type === "text" ? {} : e),
    });

    await new Promise((done) => setTimeout(done, o.ms));

    const audio = handle.audio();
    handle.stop();
    return { log, audio };
  }, opts);
}

/* ------------------------------------------------------------------ verdicts */

function summarise(out) {
  const log = out.log;
  const up = log.filter((r) => r.type === "up");
  const overTalk = up.filter((r) => r.talking);
  const starts = log.filter((r) => r.type === "UserStartedSpeaking");
  return {
    frames: up.length,
    overTalk: overTalk.length,
    bytesOverTalk: overTalk.length * 2048,
    selfStarts: starts.length,
    cutMid: starts.filter((r) => r.cutMid).length,
    turns: log.filter((r) => r.type === "agent-turn").length,
    interrupted: log.filter((r) => r.type === "interrupted").length,
    audio: out.audio,
  };
}

/** When did the loud stretch of the barge-in wav reach the mic, and when did a frame go up? */
function bargeLatency(out) {
  const up = out.log.filter((r) => r.type === "up");
  if (!up.length) return null;
  const loud = out.log.find((r) => r.type === "UserStartedSpeaking");
  return loud ? loud.t : null;
}

/* ------------------------------------------------------------------ run */

async function main() {
  mkdirSync(CACHE, { recursive: true });
  const agentWav = join(CACHE, "agent.wav");
  const riderWav = join(CACHE, "rider.wav");
  await speak("Page 78, one hundred newton metres. Page 130, forty five newton metres.", "aura-2-asteria-en", agentWav);
  await speak("Wait. Stop. The brake fluid, which page.", "aura-2-orpheus-en", riderWav);

  const agentPcm = readWav(agentWav);
  const riderPcm = readWav(riderWav);

  // The echo wav: nothing but our own voice, at echo level, for as long as the run lasts.
  const echoOnly = join(CACHE, "mic-echo.wav");
  const echo = normalise(agentPcm, ECHO_RMS);
  writeWav(echoOnly, loop(echo, RATE * 20));

  // The barge-in wav: the same echo, and at 3.2 s a different voice at speaking level over it.
  const bargeFile = join(CACHE, "mic-barge.wav");
  const barge = loop(echo, RATE * 20);
  const rider = normalise(riderPcm, RIDER_RMS);
  for (let i = 0; i < rider.length && i + RATE * 3.2 < barge.length; i++) {
    barge[Math.round(RATE * 3.2) + i] = Math.max(-1, Math.min(1, barge[Math.round(RATE * 3.2) + i] + rider[i]));
  }
  writeWav(bargeFile, barge);

  console.log(`agent clip ${(agentPcm.length / RATE).toFixed(1)} s, echo RMS ${rmsOf(echo).toFixed(4)}`);
  console.log(`rider clip ${(riderPcm.length / RATE).toFixed(1)} s, rider RMS ${rmsOf(rider).toFixed(4)}\n`);

  const settings = {
    url: "wss://stub/agent",
    sampleRate: RATE,
    pages: 320,
    manualId: "stub",
    bike: "Stub",
    settings: { type: "Settings", audio: { input: { encoding: "linear16", sample_rate: RATE } } },
  };
  const { server, port } = await serve(settings);
  const puppeteer = (await import(`file:///${PUPPETEER.split("\\").join("/")}`)).default;

  const cases = [
    { name: "legacy, echo only", wav: echoOnly, legacy: true, ms: 9000 },
    { name: "fixed,  echo only", wav: echoOnly, legacy: false, ms: 9000 },
    { name: "fixed,  real barge-in", wav: bargeFile, legacy: false, ms: 8000 },
  ];

  const results = [];
  for (const c of cases) {
    const browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: [
        "--no-sandbox",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        `--use-file-for-fake-audio-capture=${c.wav}`,
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
      ],
      protocolTimeout: 120000,
    });
    const page = await browser.newPage();
    await page.evaluateOnNewDocument((base) => {
      window.TTM_API = base;
    }, `http://127.0.0.1:${port}/fakeapi`);
    await page.goto(`http://127.0.0.1:${port}/counter/index.html`, { waitUntil: "domcontentloaded" });

    const out = await drive(page, {
      agent: Array.from(pcm16(readWav(agentWav))),
      rate: RATE,
      legacy: c.legacy,
      ms: c.ms,
      // Deepgram's VAD is not published; this is a plain RMS gate at a level a person clears and
      // a quiet echo does not, held for 200 ms. Both runs face the same one.
      vad: 0.02,
      vadMs: 200,
    });
    await browser.close();
    results.push({ c, sum: summarise(out), out });
  }

  server.close();

  console.log("run                    frames up   over the agent      self-interrupts   turns");
  for (const { c, sum } of results) {
    console.log(
      `${c.name.padEnd(22)} ${String(sum.frames).padStart(9)}   ${String(sum.overTalk).padStart(6)} (${String(sum.bytesOverTalk).padStart(6)} B)   ${String(sum.selfStarts).padStart(15)}   ${String(sum.turns).padStart(5)}`,
    );
  }

  const legacy = results[0].sum;
  const fixed = results[1].sum;
  const bargeRun = results[2];

  console.log(`\nconstraints applied: ${JSON.stringify(fixed.audio.constraints)}`);
  console.log(`playback route:      ${fixed.audio.route}`);
  console.log(`measured echo RMS:   ${Number(fixed.audio.echo).toFixed(4)}  threshold ${Number(fixed.audio.threshold).toFixed(4)}`);
  console.log(`frames withheld:     ${fixed.audio.withheld}   sent ${fixed.audio.sent}`);

  let bad = 0;
  const say = (ok, line) => {
    if (!ok) bad += 1;
    console.log((ok ? "\n  ok   " : "\n  FAIL ") + line);
  };
  say(legacy.selfStarts > 0, `legacy hears itself: ${legacy.selfStarts} UserStartedSpeaking off our own output, ${legacy.turns} turns in ${results[0].c.ms} ms`);
  say(fixed.overTalk === 0, `fixed forwards nothing over the agent: ${fixed.overTalk} frames (legacy ${legacy.overTalk})`);
  say(fixed.selfStarts === 0, `fixed never interrupts itself: ${fixed.selfStarts} self-raised UserStartedSpeaking`);
  say(fixed.turns <= 2, `fixed does not loop: ${fixed.turns} agent turns (legacy ${legacy.turns})`);

  const lat = bargeLatency(bargeRun.out);
  const loudAt = bargeRun.out.log.find((r) => r.type === "up" && r.rms > 0.05);
  const delta = lat != null && loudAt ? lat - loudAt.t : null;
  say(
    delta != null && delta <= 400,
    `a real voice still cuts in: first loud frame at ${loudAt ? loudAt.t : "?"} ms, socket believed it at ${lat} ms (+${delta} ms)`,
  );
  say(bargeRun.sum.interrupted > 0, `and the answer stopped: ${bargeRun.sum.interrupted} interruptions reported to the UI`);

  console.log(bad ? `\n${bad} failed` : "\nall clear");
  process.exit(bad ? 1 : 0);
}

/** Float32 -> Int16, for handing the agent's voice into the page as a plain array. */
function pcm16(pcm) {
  const out = new Int16Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    out[i] = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
  }
  return out;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
