/**
 * ElevenLabs Agents Platform in the browser. Owner: elevenlabs-pitch agent.
 *
 * A DROP-IN for ./voice-deepgram.js: same exports, same option bag, same event shapes, so
 * chat-ui.js switches engines by changing one import specifier. See
 * docs/pitches/elevenlabs/chat-ui.patch.
 *
 *   supported                                        boolean, at module load
 *   start({manualId, bikeId, on}) -> handle          {stop(), speaking(), level(), say(), photo()}
 *   stop()                                           kill whatever is live
 *   inject(text)                                     type a turn into a live session
 *
 * `on` is called with exactly what voice-deepgram.js calls it with:
 *   {type:"status", value:"connecting|listening|thinking|speaking|closed"}
 *   {type:"text", role:"user"|"assistant", text}
 *   {type:"page", page}
 *   {type:"error", message}
 *
 * GROUNDING. Identical to the Deepgram path and for the same reason: the four manual tools are
 * SERVER tools. ElevenLabs' own servers POST them at /voice/elevenlabs/tools/*, so the manual's
 * text never passes through this tab and cannot be edited on its way to the model. The only tool
 * that runs here is show_page, which moves the reader — the same jump a [p. N] citation chip takes.
 *
 * CREDENTIAL. GET /voice/elevenlabs/session returns a WebRTC conversation token (or a signed
 * WebSocket URL) minted on the server with the account key, plus the dynamic variables that bind
 * this session to one bike and one book. The xi-api-key never reaches the browser.
 *
 * SDK. @elevenlabs/client, imported from a CDN on the first start() and never at boot — voice is
 * one button in a drawer and should cost nothing until it is pressed.
 */

import * as T from "./ttm.js";

const CLIENT_SRC = "https://cdn.jsdelivr.net/npm/@elevenlabs/client/+esm";
// The SDK reports input volume on demand; the meter in chat-ui.js reads level() every frame, so
// smooth it the way the Deepgram path smooths its own RMS instead of letting it flicker.
const LEVEL_DECAY = 0.82;

export const supported =
  typeof window !== "undefined" &&
  typeof AudioContext !== "undefined" &&
  Boolean(navigator && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

let sdk;

function loadSdk() {
  if (!sdk) {
    sdk = import(/* @vite-ignore */ CLIENT_SRC).catch((err) => {
      sdk = undefined;
      throw err;
    });
  }
  return sdk;
}

/** The server's description of one session: credential + dynamic variables. Throws with a readable
 *  message, because every failure here is a configuration fact somebody has to act on. */
async function describe(manualId, bikeId) {
  const id = String(manualId || "").trim();
  if (!id) throw new Error("no manual");
  const params = new URLSearchParams({ manualId: id });
  if (bikeId) params.set("bikeId", String(bikeId));
  const res = await fetch(`${T.apiBase()}/voice/elevenlabs/session?${params.toString()}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(res.status === 501 ? "ElevenLabs voice is not configured" : detail || `session ${res.status}`);
  }
  return res.json();
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
  const conv = s.conv;
  s.conv = null;
  if (conv) {
    try {
      conv.endSession();
    } catch {
      /* already gone */
    }
  }
  for (const track of (s.stream && s.stream.getTracks()) || []) track.stop();
  s.stream = null;
}

/**
 * Opens a session. Resolves once the conversation is up; rejects when it cannot start at all
 * (no manual, not configured, mic refused, CDN blocked).
 */
export async function start(opts = {}) {
  stop();
  const on = typeof opts.on === "function" ? opts.on : () => {};
  const session = { conv: null, stream: null, dead: false, level: 0, mode: "", spoke: "" };
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
    speaking: () => session.mode === "speaking",
    level: () => session.level,
    /** Type a turn into the live voice session — text and speech share one conversation. */
    say: (text) => inject(text),
    /** Hold a part up to the camera mid-conversation. See photo() below. */
    photo: (file) => photo(file),
  };
}

async function run(session, opts, say) {
  say({ type: "status", value: "connecting" });

  // The server call and the SDK download are independent; the mic prompt is not, and asking for it
  // first means a refusal costs no credential and no 400 KB.
  session.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const [cfg, mod] = await Promise.all([describe(opts.manualId, opts.bikeId), loadSdk()]);
  if (session.dead) return;

  const Conversation = mod.Conversation || (mod.default && mod.default.Conversation);
  if (!Conversation) throw new Error("ElevenLabs client did not load");

  const options = {
    agentId: cfg.agentId,
    connectionType: cfg.connectionType === "websocket" ? "websocket" : "webrtc",
    dynamicVariables: cfg.dynamicVariables || {},
    clientTools: {
      // The only tool that runs in this tab. Everything the agent SAYS came from a server tool.
      show_page: (params) => {
        const page = Number(params && params.page);
        if (Number.isFinite(page) && page > 0) say({ type: "page", page });
      },
    },
    onStatusChange: (info) => {
      const value = (info && info.status) || "";
      if (value === "connected") say({ type: "status", value: "listening" });
      else if (value === "disconnected") say({ type: "status", value: "closed" });
    },
    onModeChange: (info) => {
      session.mode = (info && info.mode) || "";
      say({ type: "status", value: session.mode === "speaking" ? "speaking" : "listening" });
    },
    onMessage: (msg) => {
      const text = String((msg && (msg.message ?? msg.text)) || "").trim();
      if (!text) return;
      const role = (msg && msg.source) === "user" ? "user" : "assistant";
      say({ type: "text", role, text });
    },
    onError: (err) => {
      say({ type: "error", message: (err && (err.message || err.reason)) || "voice failed" });
    },
  };
  // A private agent is reached with a credential, never with the bare id. Both shapes are handed
  // over by the server; whichever one arrived is the one we use.
  if (cfg.conversationToken) options.conversationToken = cfg.conversationToken;
  if (cfg.signedUrl) options.signedUrl = cfg.signedUrl;

  session.conv = await Conversation.startSession(options);
  if (session.dead) {
    tear(session);
    return;
  }
  meter(session);
  say({ type: "status", value: "listening" });
}

/** The input level chat-ui.js draws its bars from. The SDK exposes it as a poll, so poll it. */
function meter(session) {
  const tick = () => {
    if (session.dead || !session.conv) return;
    let raw = 0;
    try {
      raw = Number(session.conv.getInputVolume()) || 0;
    } catch {
      raw = 0;
    }
    session.level = Math.max(raw, session.level * LEVEL_DECAY);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ------------------------------------------------------------------ multimodal */

/** Type a turn into a live session — the same path a spoken turn takes. Used by the tests. */
export function inject(text) {
  const s = current;
  const said = String(text || "").trim();
  if (!s || !s.conv || !said) return false;
  try {
    s.conv.sendUserMessage(said);
    return true;
  } catch {
    return false;
  }
}

/**
 * A photo, mid-conversation, without leaving the conversation.
 *
 * The mechanic points the phone at the part in their hand. POST /identify/part classifies it, and
 * the labels go in as a CONTEXTUAL UPDATE — context the agent may use but must not answer on its
 * own — followed by the question. So the agent still has to call find_procedure and read_page for
 * anything it says: seeing the part changes what it looks up, never what it is allowed to claim.
 *
 * Resolves to the list of {label, confidence, phrase}, or [] when nothing was recognised.
 */
export async function photo(file) {
  const s = current;
  if (!s || !s.conv || !file) return [];
  const rows = await T.identifyPart(file);
  const named = (rows || []).filter((r) => r && r.phrase).slice(0, 3);
  if (!named.length) return [];
  const list = named.map((r) => r.phrase).join(", ");
  try {
    s.conv.sendContextualUpdate(
      `The mechanic is holding a part up to the camera. The classifier says it is one of: ${list}. ` +
        `Treat this as what they are pointing at, not as anything the manual says.`,
    );
    s.conv.sendUserMessage(`What does the manual say about the ${named[0].phrase}?`);
  } catch {
    return [];
  }
  return named;
}
