/**
 * Deepgram Voice Agent in the browser. Owner: voice-mode agent.
 * Pairs with api/app/voice.py (GET /voice/agent-settings, POST /voice/deepgram-token) and is
 * driven by chat-ui.js, which owns the toggle, the meter and the transcript.
 *
 * ONE socket does everything: wss://agent.deepgram.com/v1/agent/converse carries the mic up as
 * raw linear16 and the agent's voice back down as raw linear16, with JSON events interleaved as
 * text frames. No SDK — 60 lines of AudioWorklet beat a 200 KB bundle in front of a chat drawer.
 *
 * AUTH. Deployed, the socket is `wss://<origin>/ws/deepgram/agent`: the Cloudflare Worker holds
 * the account key and opens Deepgram's socket with a real `Authorization: Token` header, so this
 * tab carries no credential at all. Only a page served from localhost — no Worker in front of it
 * — falls back to /voice/deepgram-token, which mints a short-lived key that travels in the
 * Sec-WebSocket-Protocol pair `[scheme, key]` because a browser WebSocket has no headers.
 *
 * GROUNDING. The Settings message is built on the server, never here: the prompt, the model and
 * the four tool endpoints are all in it, and Deepgram calls those endpoints itself, so the
 * manual's text never round-trips through this tab. The only function this file runs is the
 * client-side show_page(page), which jumps the reader.
 *
 * SAYING A PAGE IS SHOWING IT. The prompt makes the agent name the page every figure came off
 * ("page 115 says ..."), and show_page is there to open it — but a language model calls a function
 * it does not need for its own answer only when it feels like it, and measured against the live
 * socket it mostly did not: four spoken turns on the 390 Duke, four pages named out loud, zero
 * show_page calls. So the page a turn names is not left to the model. The assistant's own
 * transcript arrives on the same millisecond as the first byte of its audio, and the page number
 * in it moves the reader — the mechanic hears "page 115" and page 115 is already there. show_page
 * still works and still wins when the agent does call it; this only covers the turns it doesn't.
 *
 * start({manualId, bikeId, on}) -> handle {stop(), speaking(), level()}
 * `on` is called with:
 *   {type:"status", value:"connecting|listening|thinking|speaking|closed"}
 *   {type:"text", role:"user"|"assistant", text}   one finished turn, for the transcript
 *   {type:"page", page}                            show_page, or the page the answer named
 *   {type:"error", message}
 */

import * as T from "./ttm.js";

const FALLBACK_RATE = 24000;
const FRAME = 1024; // samples per upstream chunk: ~43 ms at 24 kHz
const LEVEL_DECAY = 0.82;
// Enough to ride out a stalled frame, small enough that it is not felt in front of the answer.
const JITTER_S = 0.08;
const KEEPALIVE_MS = 8000;
// How long after a barge-in to keep dropping the abandoned answer's chunks. Long enough to cover
// what was already in flight, short enough that a missing AgentStartedSpeaking costs nothing.
const BARGE_MUTE_MS = 500;

// "page 115 says ...", "on page 115", "pages 85 and 86" — the first printed page an answer names.
// Only ever "page N": a bare number in an answer is a torque or a capacity, never somewhere to go.
const SPOKEN_PAGE = /\bpages?\s+(\d{1,4})\b/i;

const WORKLET = `class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel && channel.length) {
      const copy = new Float32Array(channel)
      this.port.postMessage(copy, [copy.buffer])
    }
    return true
  }
}
registerProcessor('ttm-agent-tap', Tap)`;

export const supported =
  typeof window !== "undefined" &&
  typeof WebSocket !== "undefined" &&
  typeof AudioContext !== "undefined" &&
  Boolean(navigator && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

const LOCAL = new Set(["localhost", "127.0.0.1", "[::1]", "::1", ""]);

/**
 * The same-origin socket the Worker proxies, or null when this page is served from localhost and
 * there is no Worker to proxy it. Same four lines in deepgram.js: importing a 400-line agent
 * module into the dictation path to share them would cost more than it saves.
 */
function proxy(path) {
  if (typeof location === "undefined" || LOCAL.has(location.hostname)) return null;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

/* ------------------------------------------------------------------ pcm */

/** Float32 [-1,1] at `from` Hz -> Int16 little-endian at `to` Hz. Nearest-sample: the mic is
 *  already 24 kHz in every browser that honours the AudioContext hint, so this rarely resamples. */
function pcm16(input, from, to) {
  const ratio = from / to;
  const count = ratio === 1 ? input.length : Math.floor(input.length / ratio);
  const out = new Int16Array(count);
  for (let i = 0; i < count; i++) {
    const s = Math.max(-1, Math.min(1, input[ratio === 1 ? i : Math.floor(i * ratio)]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

function toFloat(buffer) {
  const pcm = new Int16Array(buffer);
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] / 0x8000;
  return out;
}

/* ------------------------------------------------------------------ playback */

/**
 * The agent's voice arrives as a stream of raw PCM chunks with no timing of their own, so each
 * one is scheduled to start where the last one ended — a cursor, not a queue of timers. A chunk
 * that arrives late (cursor already in the past) restarts the cursor JITTER_S ahead of now, which
 * is the whole jitter buffer: one number.
 */
function player(ctx, rate, onDone) {
  let cursor = 0;
  let live = [];
  let gain = null;
  let muteUntil = 0;

  function sink() {
    if (!gain) {
      gain = ctx.createGain();
      gain.connect(ctx.destination);
    }
    return gain;
  }

  return {
    push(buffer) {
      // After a barge-in the rest of the abandoned answer keeps arriving for a moment; dropping
      // it is the difference between interrupting the agent and talking over it. A window, not a
      // flag: Deepgram does not always send AgentStartedSpeaking, and a mute nothing lifts would
      // silence the session for good.
      if (performance.now() < muteUntil) return;
      const samples = toFloat(buffer);
      if (!samples.length) return;
      const frame = ctx.createBuffer(1, samples.length, rate);
      frame.getChannelData(0).set(samples);
      const src = ctx.createBufferSource();
      src.buffer = frame;
      src.connect(sink());
      const now = ctx.currentTime;
      if (cursor < now + 0.005) cursor = now + JITTER_S;
      src.start(cursor);
      cursor += frame.duration;
      live.push(src);
      src.onended = () => {
        live = live.filter((s) => s !== src);
        if (!live.length && typeof onDone === "function") onDone();
      };
    },
    /**
     * Barge-in: the rider started talking, so the agent stops mid-word. `stop()` on a scheduled
     * AudioBufferSourceNode takes effect on the next render quantum - under 3 ms - so what the
     * rider actually waits for is Deepgram's UserStartedSpeaking crossing the network.
     */
    flush() {
      muteUntil = performance.now() + BARGE_MUTE_MS;
      for (const src of live) {
        try {
          src.onended = null;
          src.stop();
        } catch {
          /* already finished */
        }
      }
      live = [];
      cursor = 0;
    },
    /** The agent is starting a new answer: take the mute off early. */
    resume() {
      muteUntil = 0;
    },
    busy() {
      return live.length > 0;
    },
  };
}

/* ------------------------------------------------------------------ session */

let current = null;

export function stop() {
  const s = current;
  current = null;
  if (s) tear(s);
}

function tear(s) {
  if (s.dead) return;
  s.dead = true;
  if (s.beat) {
    clearInterval(s.beat);
    s.beat = 0;
  }
  const ws = s.ws;
  s.ws = null;
  if (ws) {
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  }
  if (s.play) s.play.flush();
  try {
    if (s.src) s.src.disconnect();
    if (s.node) s.node.disconnect();
  } catch {
    /* detached */
  }
  for (const track of (s.stream && s.stream.getTracks()) || []) track.stop();
  if (s.ctx) s.ctx.close().catch(() => {});
  if (s.worklet) URL.revokeObjectURL(s.worklet);
  s.worklet = null;
}

/**
 * Opens a session. Resolves to a handle once the mic and the socket are up; rejects only when
 * the session cannot start at all (no config, no key, mic refused).
 */
export async function start(opts = {}) {
  stop();
  const on = typeof opts.on === "function" ? opts.on : () => {};
  const session = {
    ws: null,
    ctx: null,
    stream: null,
    node: null,
    src: null,
    play: null,
    worklet: null,
    beat: 0,
    level: 0,
    dead: false,
    pages: 0, // printed pages in this manual; 0 until the settings arrive
    page: 0, // the page already on the rider's screen
  };
  current = session;

  const say = (event) => {
    if (!session.dead) on(event);
  };

  try {
    await run(session, opts, say);
  } catch (err) {
    if (current === session) current = null;
    tear(session);
    say({ type: "error", message: (err && err.message) || "voice failed" });
    throw err;
  }

  return {
    stop() {
      if (current === session) current = null;
      const was = session.dead;
      tear(session);
      if (!was) say({ type: "status", value: "closed" });
    },
    speaking: () => Boolean(session.play && session.play.busy()),
    level: () => session.level,
  };
}

async function run(session, opts, say) {
  say({ type: "status", value: "connecting" });

  const relay = proxy("/ws/deepgram/agent");
  const [config, token] = await Promise.all([
    T.voiceSettings(opts.manualId, opts.bikeId),
    relay ? null : T.deepgramToken(),
  ]);
  if (session.dead) return;
  if (!config || !config.settings) throw new Error("no agent settings");
  session.pages = Number(config.pages) || 0;
  let url = relay;
  let protocols;
  if (!relay) {
    const key = typeof token === "string" ? token : token && (token.key || token.token);
    if (!key) throw new Error("no deepgram key");
    url = config.url;
    protocols = [(token && token.scheme) || "token", key];
  }
  const rate = Number(config.sampleRate) || FALLBACK_RATE;

  session.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  if (session.dead) return;

  const ctx = new AudioContext({ sampleRate: rate });
  session.ctx = ctx;
  session.play = player(ctx, rate, () => say({ type: "status", value: "listening" }));
  if (ctx.state === "suspended") await ctx.resume();
  if (session.dead) return;

  const ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url);
  ws.binaryType = "arraybuffer";
  session.ws = ws;

  ws.onopen = () => {
    ws.send(JSON.stringify(config.settings));
    session.beat = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "KeepAlive" }));
    }, KEEPALIVE_MS);
  };

  ws.onmessage = (event) => {
    if (typeof event.data !== "string") {
      session.play.push(event.data);
      return;
    }
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    handle(session, ws, msg, say);
  };

  ws.onerror = () => say({ type: "error", message: "voice connection failed" });
  ws.onclose = () => {
    if (session.dead) return;
    if (current === session) current = null;
    tear(session);
    say({ type: "status", value: "closed" });
  };

  await capture(session, ws, rate, say);
}

/** One server event. Everything the drawer shows comes through here. */
function handle(session, ws, msg, say) {
  switch (msg.type) {
    case "Welcome":
      break;
    case "SettingsApplied":
      say({ type: "status", value: "listening" });
      break;
    // Barge-in. Flux (listen v2) announces a turn with StartOfTurn; nova-3 sends
    // UserStartedSpeaking. Whichever arrives, the buffered answer dies on the spot.
    case "UserStartedSpeaking":
    case "StartOfTurn":
      session.play.flush();
      say({ type: "status", value: "listening" });
      break;
    case "AgentThinking":
      say({ type: "status", value: "thinking" });
      break;
    case "AgentStartedSpeaking":
      session.play.resume();
      say({ type: "status", value: "speaking" });
      break;
    case "ConversationText": {
      const text = String(msg.content || "").trim();
      if (!text) break;
      const assistant = msg.role !== "user";
      say({ type: "text", role: assistant ? "assistant" : "user", text });
      // The page the agent just said out loud, for the turns where it does not call show_page.
      if (assistant) {
        const named = SPOKEN_PAGE.exec(text);
        if (named) turnTo(session, Number(named[1]), say);
      }
      break;
    }
    case "FunctionCallRequest":
      for (const call of msg.functions || []) run_function(session, ws, call, say);
      break;
    case "AgentAudioDone":
      // The last chunk is scheduled, not played: the player says "listening" when it drains.
      if (!session.play.busy()) say({ type: "status", value: "listening" });
      break;
    case "Error":
      say({ type: "error", message: String(msg.description || msg.message || "voice error") });
      break;
    default:
      break;
  }
}

/**
 * Move the reader to a printed page, once. Out-of-range pages are dropped rather than jumping the
 * reader somewhere the manual does not have, and the page already on screen is not re-sent.
 */
function turnTo(session, page, say) {
  const n = Math.floor(Number(page));
  if (!Number.isFinite(n) || n < 1) return false;
  if (session.pages && n > session.pages) return false;
  if (session.page === n) return true;
  session.page = n;
  say({ type: "page", page: n });
  return true;
}

/**
 * The only function this browser runs. Everything grounded is server-side — Deepgram calls the
 * API's own /voice/tools/* endpoints — so `client_side` should only ever be show_page.
 */
function run_function(session, ws, call, say) {
  if (!call || call.client_side === false) return;
  let args = {};
  try {
    args = typeof call.arguments === "string" ? JSON.parse(call.arguments || "{}") : call.arguments || {};
  } catch {
    args = {};
  }
  let content = "unknown function";
  if (call.name === "show_page") {
    const page = Math.floor(Number(args.page));
    content = turnTo(session, page, say) ? `Page ${page} is on the rider's screen.` : "No such page.";
  }
  if (ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "FunctionCallResponse", id: call.id, name: call.name, content }));
}

/** Mic -> fixed-size linear16 frames -> socket, with a decaying level for the meter. */
async function capture(session, ws, rate, say) {
  const ctx = session.ctx;
  let queue = new Float32Array(0);

  const push = (chunk) => {
    let peak = 0;
    for (let i = 0; i < chunk.length; i++) {
      const v = chunk[i] < 0 ? -chunk[i] : chunk[i];
      if (v > peak) peak = v;
    }
    session.level = Math.max(peak, session.level * LEVEL_DECAY);

    const merged = new Float32Array(queue.length + chunk.length);
    merged.set(queue);
    merged.set(chunk, queue.length);
    queue = merged;
    while (queue.length >= FRAME) {
      if (ws.readyState === WebSocket.OPEN) ws.send(pcm16(queue.subarray(0, FRAME), ctx.sampleRate, rate));
      queue = queue.slice(FRAME);
    }
  };

  let node;
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    session.worklet = url;
    await ctx.audioWorklet.addModule(url);
    if (session.dead) return;
    const tap = new AudioWorkletNode(ctx, "ttm-agent-tap");
    tap.port.onmessage = (e) => push(e.data);
    node = tap;
  } catch {
    // Safari < 14.1 and any browser that refuses the blob module.
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => push(new Float32Array(e.inputBuffer.getChannelData(0)));
    node = proc;
  }
  if (session.dead) return;

  // A ScriptProcessor only fires while it is connected to the graph; muted so the rider
  // never hears their own voice come back.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  node.connect(mute);
  mute.connect(ctx.destination);

  const src = ctx.createMediaStreamSource(session.stream);
  src.connect(node);
  session.src = src;
  session.node = node;
  say({ type: "status", value: "connecting" });
}

/** Type a turn into a live session — the same path a spoken turn takes. Used by the tests. */
export function inject(text) {
  const s = current;
  const said = String(text || "").trim();
  if (!s || !s.ws || s.ws.readyState !== WebSocket.OPEN || !said) return false;
  s.ws.send(JSON.stringify({ type: "InjectUserMessage", content: said }));
  return true;
}
