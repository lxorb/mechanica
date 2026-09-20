/**
 * Deepgram Flux dictation over WebSocket, keyed by a short-lived token from the API.
 * Same shape as speech.js: supported, prime(terms), start(onText, onEnd), stop().
 */

import { deepgramToken } from "./ttm.js";

const RATE = 16000;
const FRAME = 1280;
const MAX_KEYTERMS = 40;

const STOP = new Set([
  "the", "and", "for", "with", "from", "your", "that", "this", "into", "onto", "over", "when", "work",
  "works", "after", "before", "using", "each", "both", "only", "more", "than", "also", "must", "have",
]);

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
registerProcessor('ttm-tap', Tap)`;

export const supported =
  typeof window !== "undefined" &&
  typeof WebSocket !== "undefined" &&
  typeof AudioContext !== "undefined" &&
  Boolean(navigator && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

let keyterms = [];

export function prime(terms) {
  const out = [];
  const seen = new Set();
  for (const source of terms || []) {
    for (const raw of String(source || "").split(/[^A-Za-z0-9-]+/)) {
      const word = raw.replace(/^-+|-+$/g, "");
      const low = word.toLowerCase();
      if (word.length < 4 || STOP.has(low) || seen.has(low)) continue;
      seen.add(low);
      out.push(word);
      if (out.length >= MAX_KEYTERMS) {
        keyterms = out;
        return;
      }
    }
  }
  keyterms = out;
}

let live = null;

function tear(s) {
  s.dead = true;
  const ws = s.ws;
  s.ws = null;
  if (ws) {
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "CloseStream" }));
    } catch {
      /* closed */
    }
    try {
      ws.close();
    } catch {
      /* closed */
    }
  }
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

export function stop() {
  const s = live;
  live = null;
  if (s) tear(s);
}

function pcm16(input, from) {
  const ratio = from / RATE;
  const count = Math.floor(input.length / ratio);
  const out = new Int16Array(count);
  for (let i = 0; i < count; i++) {
    const sample = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return out.buffer;
}

export function start(onText, onEnd) {
  stop();
  const session = { ws: null, ctx: null, stream: null, node: null, src: null, worklet: null, dead: false };
  live = session;

  const finish = () => {
    if (session.dead) return;
    if (live === session) live = null;
    tear(session);
    onEnd();
  };

  run(session, onText, finish).catch(finish);
}

async function run(session, onText, finish) {
  const token = await deepgramToken();
  const key = typeof token === "string" ? token : token && (token.key || token.token);
  if (!key) throw new Error("deepgram token");
  if (session.dead) return;

  session.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  if (session.dead) {
    tear(session);
    return;
  }

  const ctx = new AudioContext({ sampleRate: RATE });
  session.ctx = ctx;

  const params = new URLSearchParams({
    model: "flux-general-en",
    encoding: "linear16",
    sample_rate: String(RATE),
  });
  for (const term of keyterms) params.append("keyterm", term);

  const ws = new WebSocket(`wss://api.deepgram.com/v2/listen?${params.toString()}`, ["token", key]);
  ws.binaryType = "arraybuffer";
  session.ws = ws;

  ws.onmessage = (event) => {
    if (typeof event.data !== "string") return;
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    if (msg.type === "Error" || msg.type === "ConfigureFailure") {
      finish();
      return;
    }
    if (msg.type !== "TurnInfo") return;
    const text = String(msg.transcript || "").trim();
    const done = msg.event === "EndOfTurn";
    if (text) onText(text, done);
    if (done) finish();
  };
  ws.onerror = () => finish();
  ws.onclose = () => finish();

  const need = Math.max(1, Math.round(FRAME * (ctx.sampleRate / RATE)));
  let queue = new Float32Array(0);
  const push = (chunk) => {
    const merged = new Float32Array(queue.length + chunk.length);
    merged.set(queue);
    merged.set(chunk, queue.length);
    queue = merged;
    while (queue.length >= need) {
      if (ws.readyState === WebSocket.OPEN) ws.send(pcm16(queue.subarray(0, need), ctx.sampleRate));
      queue = queue.slice(need);
    }
  };

  let node;
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    session.worklet = url;
    await ctx.audioWorklet.addModule(url);
    if (session.dead) {
      tear(session);
      return;
    }
    const tap = new AudioWorkletNode(ctx, "ttm-tap");
    tap.port.onmessage = (e) => push(e.data);
    node = tap;
  } catch {
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => push(new Float32Array(e.inputBuffer.getChannelData(0)));
    node = proc;
  }

  const sink = ctx.createGain();
  sink.gain.value = 0;
  node.connect(sink);
  sink.connect(ctx.destination);

  const src = ctx.createMediaStreamSource(session.stream);
  src.connect(node);
  session.src = src;
  session.node = node;
  if (ctx.state === "suspended") await ctx.resume();
}
