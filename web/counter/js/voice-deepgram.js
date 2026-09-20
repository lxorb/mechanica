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
 * THE EVENTS DEEPGRAM DOES NOT SEND. Measured over five live sessions on this configuration
 * (flux listen v2 + open_ai think + aura-2 speak), the socket sends Welcome, SettingsApplied,
 * ConversationText, History, LatencyReport, UserStartedSpeaking, EndOfTurn, FunctionCallRequest,
 * FunctionCallResponse and AgentAudioDone — and **never once AgentThinking or
 * AgentStartedSpeaking**. Those two were the entire basis of the "Thinking" and "Speaking"
 * statuses, so the drawer sat on "Listening" through every lookup and every answer. The status is
 * therefore derived from what does arrive: EndOfTurn or a FunctionCallRequest means thinking, the
 * first audio frame of a turn means speaking, a drained player with nothing in flight means
 * listening. AgentThinking/AgentStartedSpeaking are still honoured if they ever show up.
 *
 * ONE SEC, CHECKING THE MANUAL. A spec question answers in 1.4-2.1 s; a question that walks
 * find_procedure then reads four printed pages takes five to ten, and the mechanic hears nothing
 * at all in between. Measured, no single round trip is slow - every one is 250-650 ms - so there
 * is nothing to hang a per-call spinner on: it is the CHAIN that is slow. So the ack is a
 * turn-level timer. If a lookup is running and this turn has made no sound ACK_MS after the
 * rider stopped talking, the client sends InjectAgentMessage with behavior "queue", which is
 * Deepgram's documented filler-during-a-long-function-call path. Live: sent at 2,503 ms, heard at
 * 2,636 ms, against a real answer at 5,191 ms - four seconds of silence turned into one sentence
 * and a wait. ACK_MS is above the slowest measured spec turn so a two-second answer never gets one.
 *
 * BARGE-IN, BEFORE DEEPGRAM SAYS SO. UserStartedSpeaking is the truth, but it is 0.4-2.2 s of
 * network and model away (measured range over five sessions; median ~0.7 s, worst 2.2 s), and
 * being talked over for two seconds is the single least human thing this agent does. So the mic's
 * own RMS ducks playback locally after ~130 ms of speech while the agent is talking, and the
 * server event - if it comes - turns the duck into a real stop. If it does not come within
 * UNDUCK_MS the agent was not being interrupted at all (a dropped spanner, a compressor) and the
 * answer comes back up where it left off. A duck is reversible; a flush is not.
 *
 * start({manualId, bikeId, on}) -> handle {stop(), interrupt(), speaking(), level(), out()}
 * `on` is called with:
 *   {type:"status", value:"connecting|listening|thinking|speaking|closed"}
 *   {type:"text", role:"user"|"assistant", text}   one finished turn, for the transcript
 *   {type:"page", page}                            show_page, or the page the answer named
 *   {type:"interrupted"}                           the agent was cut off, for the UI to show
 *   {type:"error", message}
 */

import * as T from "./ttm.js";

const FALLBACK_RATE = 24000;
const FRAME = 1024; // samples per upstream chunk: ~43 ms at 24 kHz
const LEVEL_DECAY = 0.82;
// Enough to ride out a stalled frame, small enough that it is not felt in front of the answer.
const JITTER_S = 0.08;
const KEEPALIVE_MS = 8000;
// How long after a barge-in to keep dropping the abandoned answer's chunks. Measured, 8-103 KB of
// the abandoned answer still arrives after the rider starts talking - up to two seconds of audio -
// so the window has to outlive the flush. Short enough that a lost UserStartedSpeaking costs
// nothing, because a mute nothing lifts would silence the session for good.
const BARGE_MUTE_MS = 500;
const DUCKED_GAIN = 0.08;

/* ---- half duplex: the mic must not hear the agent ----------------------------------------
 *
 * THE LOOP, MEASURED. The phone's speaker is 20 cm from its microphone, so while the agent
 * talks the mic hears the agent. Every one of those frames used to go straight up the socket,
 * and Deepgram's VAD cannot tell our voice from his: it answered its own greeting with
 * UserStartedSpeaking, this client flushed the playback it had just scheduled, the orb flashed
 * "interrupted", the agent started a new turn - and the first syllable of THAT turn started the
 * same loop again. Reproduced in headless Chrome with the agent's own greeting on the fake
 * capture device (web/tools/voice-echo.mjs) and fixed on four layers:
 *
 *   1. constraints          echoCancellation + noiseSuppression on, autoGainControl OFF. AGC is
 *                           what lifts a quiet room's echo up to a speaking level.
 *   2. playback route       through a MediaStreamAudioDestinationNode into an <audio> element,
 *                           which is the render path Chrome's AEC has a reference for and the
 *                           ONLY one iOS Safari cancels at all.
 *   3. this guard           while the agent is audible (first frame -> drained + TAIL_MS) the
 *                           mic is not forwarded, unless it is loud enough to be a person.
 *   4. one threshold        "loud enough" is measured, not guessed: the echo's own level during
 *                           the first ECHO_MS of the turn, times BARGE_RATIO, held for BARGE_MS.
 *                           The local duck obeys the same number, so the agent can no longer
 *                           duck itself.
 */

// How long after the last scheduled sample the mic stays shut. Room reverb and the speaker's own
// decay outlive the samples; 250 ms is past both and still inside a human turn gap.
const TAIL_MS = 250;
// The window at the start of a spoken turn where the mic is only measuring, never judging: what
// it hears here IS the echo, by definition, because the rider has not started talking yet.
const ECHO_MS = 300;
// A real voice has to beat the measured echo by this much, for this long, to be believed.
const BARGE_RATIO = 2.5;
const BARGE_MS = 120;
// Floors, so a silent room (echo ~0) does not make every cough a barge-in, and so a session that
// never measured an echo still needs a real voice. RMS of speech a metre from a phone is ~0.05.
const BARGE_FLOOR = 0.035;
const ECHO_FLOOR = 0.006;
// The mic frames withheld during the guard are kept this long: on a true barge-in they are sent
// first, so Deepgram hears the word he started with and not the second half of it.
const PRIME_MS = 320;
// Frames are AudioWorklet render quanta - 128 samples, ~5 ms at 24 kHz - so every "how long has
// this been loud" is counted in milliseconds. The old code counted three FRAMES and called it
// 130 ms; three quanta is 16 ms, which is why the agent ducked itself on its own first syllable.
// If Deepgram never agrees that the rider spoke, it was not speech: put the answer back.
const UNDUCK_MS = 900;
// A turn with a lookup running and no sound yet gets one spoken acknowledgement at this mark.
// Above the slowest measured spec turn (2,107 ms) so a two-second answer never earns one.
const ACK_MS = 2500;
const ACK_TEXT = "One sec, checking the manual.";

// "page 115 says ...", "on page 115", "pages 85 and 86" — the first printed page an answer names.
// Only ever "page N": a bare number in an answer is a torque or a capacity, never somewhere to go.
const SPOKEN_PAGE = /\bpages?\s+(\d{1,4})\b/i;

/**
 * The one knob, and it exists for the measurement rather than for the product: with `guard`
 * false this file behaves exactly as it shipped before the half-duplex guard, so
 * web/tools/voice-echo.mjs can run the loop and the fix against the same stub, the same audio
 * and the same VAD and attribute the difference to one thing. Nothing in the app writes it.
 */
export const tuning = { guard: true };

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
  let meter = null;
  let window = null;
  let muteUntil = 0;
  let audible = 0; // performance.now() of the last sample scheduled, so the guard knows the tail
  let route = "element";
  let tag = null;

  function sink() {
    if (!gain) {
      gain = ctx.createGain();
      // The orb pulses on the voice the rider is actually hearing, so the meter has to be on the
      // node the voice goes through, not on the chunks going into it: a chunk is scheduled up to
      // JITTER_S before it is audible, and an orb 80 ms ahead of the sound looks broken.
      meter = ctx.createAnalyser();
      meter.fftSize = 256;
      meter.smoothingTimeConstant = 0;
      window = new Float32Array(meter.fftSize);
      gain.connect(meter);
      // THE ROUTE MATTERS. ctx.destination is a WebAudio render stream of this context's own
      // sample rate (24 kHz here, never the device's), and the platform echo canceller's
      // reference is the DEVICE render stream. A MediaStreamAudioDestinationNode played through
      // an <audio> element goes out the media pipeline instead, which is the one Chrome
      // references and the only one iOS Safari cancels at all. If the element will not play -
      // an autoplay policy, an ancient browser - fall back rather than lose the voice.
      try {
        const dest = ctx.createMediaStreamDestination();
        gain.connect(dest);
        tag = new Audio();
        tag.srcObject = dest.stream;
        tag.autoplay = true;
        tag.muted = false;
        tag.volume = 1;
        const played = tag.play();
        if (played && typeof played.catch === "function") {
          played.catch(() => {
            if (route !== "element") return;
            route = "destination";
            gain.connect(ctx.destination);
          });
        }
      } catch {
        route = "destination";
        gain.connect(ctx.destination);
      }
    }
    return gain;
  }

  return {
    /** Which render path the voice is leaving by, for VOICE.md and the harness. */
    route: () => route,
    /**
     * Is the agent audible right now, or was it within `tail` ms? `busy()` goes false the moment
     * the last buffer's onended fires, and the room is still ringing for a moment after that.
     */
    audible(tail) {
      if (live.length) return true;
      return performance.now() < audible + (tail || 0);
    },
    /** RMS of what is coming out of the speaker right now, 0..1. */
    level() {
      if (!meter || !live.length) return 0;
      meter.getFloatTimeDomainData(window);
      let sum = 0;
      for (let i = 0; i < window.length; i++) sum += window[i] * window[i];
      return Math.sqrt(sum / window.length);
    },
    /**
     * Quieten the answer without throwing it away. The rider may only have coughed; a duck is a
     * guess that can be taken back, and `flush` - which cannot - waits for Deepgram to confirm.
     */
    duck(on) {
      if (!gain) return;
      const now = ctx.currentTime;
      gain.gain.cancelScheduledValues(now);
      gain.gain.setTargetAtTime(on ? DUCKED_GAIN : 1, now, 0.02);
    },
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
      // Wall-clock moment the last scheduled sample stops being in the room. The guard reads it,
      // so the mic stays shut through the whole jitter buffer and not just through what has
      // already been handed to the speaker.
      audible = performance.now() + Math.max(0, (cursor - ctx.currentTime) * 1000);
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
      // Nothing is in the room any more, so the half-duplex guard must not keep the mic shut for
      // a tail that no longer exists - the rider is mid-sentence and every frame counts.
      audible = 0;
      if (gain) {
        // A flush ends the duck: the next answer must not arrive at eight percent.
        gain.gain.cancelScheduledValues(ctx.currentTime);
        gain.gain.value = 1;
      }
    },
    /** The element keeps a live MediaStream; a session that ends without this leaves it playing. */
    close() {
      if (!tag) return;
      try {
        tag.pause();
        tag.srcObject = null;
      } catch {
        /* already gone */
      }
      tag = null;
    },
    /** The agent is starting a new answer: take the mute off early. */
    resume() {
      muteUntil = 0;
      if (gain) {
        gain.gain.cancelScheduledValues(ctx.currentTime);
        gain.gain.value = 1;
      }
    },
    busy() {
      return live.length > 0;
    },
    /** Still inside the window where the abandoned answer's chunks are being dropped. */
    muted() {
      return performance.now() < muteUntil;
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
  if (s.ack) {
    clearTimeout(s.ack);
    s.ack = 0;
  }
  if (s.unduck) {
    clearTimeout(s.unduck);
    s.unduck = 0;
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
  if (s.play) {
    s.play.flush();
    s.play.close();
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
    status: "",
    lookups: 0, // server-side function calls still out
    ack: 0, // the "one sec" timer for this turn
    acked: false, // this turn has already had its one acknowledgement
    said: false, // this turn has made a sound
    spoke: false, // this turn already has an assistant line in the transcript
    loudMs: 0, // how long the mic has been over the barge threshold, in ms
    ducked: false,
    unduck: 0,
    /* half duplex */
    echo: 0, // measured RMS of our own voice coming back into the mic
    echoPeak: 0, // the peak of the turn being measured
    echoMs: 0, // how much of ECHO_MS this turn has collected
    echoTurn: false, // this spoken turn has been measured
    gated: false, // the mic is currently not being forwarded
    barged: false, // a real voice beat the threshold; forward everything until the turn ends
    held: [], // the withheld frames, newest last, ~PRIME_MS of them
    heldMs: 0,
    withheld: 0, // frames the guard kept out of the socket, for the harness
    sent: 0, // frames that did go up
    settings: null, // what getUserMedia actually applied
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
    /** The rider tapped the orb while the agent was talking. Same path as a spoken barge-in. */
    interrupt() {
      if (session.dead || !session.play || !session.play.busy()) return false;
      session.play.flush();
      session.ducked = false;
      say({ type: "interrupted" });
      status(session, "listening", say);
      return true;
    },
    speaking: () => Boolean(session.play && session.play.busy()),
    level: () => session.level,
    out: () => (session.play ? session.play.level() : 0),
    status: () => session.status,
    /** Everything the echo harness and VOICE.md quote. Not used by the UI. */
    audio: () => ({
      constraints: session.settings,
      route: session.play ? session.play.route() : "",
      echo: session.echo,
      threshold: barge(session),
      gated: session.gated,
      withheld: session.withheld,
      sent: session.sent,
    }),
  };
}

/** What a voice has to beat to be a voice and not our own speaker. Measured, with a floor. */
function barge(session) {
  return Math.max(BARGE_FLOOR, (session.echo || ECHO_FLOOR) * BARGE_RATIO);
}

/** One status, said once. Everything that drives the orb goes through here. */
function status(session, value, say) {
  if (session.dead || session.status === value) return;
  session.status = value;
  say({ type: "status", value });
}

/**
 * The rider stopped talking and a lookup is running. If this turn is still silent ACK_MS later,
 * have the agent say one short thing rather than leave him in front of a dead phone. `queue` is
 * Deepgram's documented behaviour for exactly this - filler during a long-running function call -
 * and it is refused rather than obeyed if the rider is speaking, which is the right answer too.
 */
function arm(session, ws, say) {
  if (session.ack || session.acked || session.said || session.dead) return;
  session.ack = window.setTimeout(() => {
    session.ack = 0;
    if (session.dead || session.said || !session.lookups) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    session.acked = true;
    // Deepgram echoes the injected line back as an ordinary assistant ConversationText, so the
    // transcript gets it from there; saying it twice here would put it in the history twice.
    ws.send(JSON.stringify({ type: "InjectAgentMessage", message: ACK_TEXT, behavior: "queue" }));
  }, ACK_MS);
}

/** A turn is starting: nothing has been said yet and the last turn's acknowledgement is spent. */
function fresh(session) {
  if (session.ack) {
    clearTimeout(session.ack);
    session.ack = 0;
  }
  session.said = false;
  session.acked = false;
  session.spoke = false;
  session.lookups = 0;
  // A new turn is a new room: the guard shuts again, and the next answer re-measures its own
  // echo rather than trusting a number taken while the rider was holding an impact wrench.
  session.barged = false;
  session.echoTurn = false;
  session.echoMs = 0;
  session.echoPeak = 0;
  session.loudMs = 0;
}

async function run(session, opts, say) {
  status(session, "connecting", say);

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

  // autoGainControl OFF. The other two are obvious; this one is the subtle half of the loop. AGC
  // normalises the mic towards a target level, so in a quiet workshop it winds the gain UP until
  // the only thing in the room - the phone's own speaker - is at speaking level, and every
  // threshold downstream of it is measuring an amplified echo. Off, the echo stays quiet and the
  // rider's voice stays louder than it, which is the entire premise of the barge-in threshold.
  session.stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: false,
    },
  });
  if (session.dead) return;
  // What the browser actually applied, not what we asked for: a device that refuses echo
  // cancellation is a device where the guard below is the only thing standing between the agent
  // and its own voice, and it is worth being able to read that back.
  const track = session.stream.getAudioTracks()[0];
  session.settings = track && typeof track.getSettings === "function" ? track.getSettings() : null;

  const ctx = new AudioContext({ sampleRate: rate });
  session.ctx = ctx;
  session.play = player(ctx, rate, () => status(session, session.lookups ? "thinking" : "listening", say));
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
      // The first frame of a turn is the only "AgentStartedSpeaking" this socket ever sends.
      if (!session.said && !session.play.muted()) {
        session.said = true;
        if (session.ack) {
          clearTimeout(session.ack);
          session.ack = 0;
        }
        status(session, "speaking", say);
      }
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
      status(session, "listening", say);
      break;
    // Barge-in. Flux (listen v2) announces a turn with StartOfTurn; nova-3 sends
    // UserStartedSpeaking. Whichever arrives, the buffered answer dies on the spot - and so does
    // the local duck that has probably been holding it down for the last half second.
    case "UserStartedSpeaking":
    case "StartOfTurn": {
      const cut = session.play.busy();
      session.play.flush();
      session.ducked = false;
      session.loudMs = 0;
      if (session.unduck) {
        clearTimeout(session.unduck);
        session.unduck = 0;
      }
      fresh(session);
      // Deepgram agrees there is a person talking, so the guard opens for the rest of this turn
      // whatever the levels say - the flush above just took our own voice out of the room.
      session.barged = true;
      if (cut) say({ type: "interrupted" });
      status(session, "listening", say);
      break;
    }
    // The rider's turn is over and the model has it. Nothing will be audible for a second or two.
    case "EndOfTurn":
      fresh(session);
      status(session, "thinking", say);
      // The clock starts when HE stopped talking, not when a lookup happens to be reported: the
      // first FunctionCallRequest is itself 0.7-1.0 s away, and 2,500 ms measured from there
      // would land the acknowledgement after the answer on half the turns it is meant to cover.
      arm(session, ws, say);
      break;
    case "AgentThinking":
      status(session, "thinking", say);
      break;
    case "AgentStartedSpeaking":
      session.play.resume();
      session.said = true;
      status(session, "speaking", say);
      break;
    case "ConversationText": {
      const text = String(msg.content || "").trim();
      if (!text) break;
      const assistant = msg.role !== "user";
      // The acknowledgement is not part of the answer: it stands alone and the answer that lands
      // four seconds later is a fresh line, not a sentence appended to "one sec".
      if (assistant && text === ACK_TEXT) {
        say({ type: "text", role: "assistant", text });
        session.spoke = false;
        break;
      }
      // The model answers one sentence per message. A mechanic asked one question and got one
      // answer, so the transcript gets one line: `part` is true for every sentence after the
      // first of the same turn, and chat-ui appends it to the bubble already there.
      say({ type: "text", role: assistant ? "assistant" : "user", text, part: assistant && session.spoke });
      if (assistant) {
        session.spoke = true;
        // The page the agent just said out loud, for the turns where it does not call show_page.
        const named = SPOKEN_PAGE.exec(text);
        if (named) turnTo(session, Number(named[1]), say);
      } else {
        session.spoke = false;
      }
      break;
    }
    case "FunctionCallRequest":
      // Deepgram reports its OWN server-side calls here too, so this is where the browser learns
      // that a lookup is running at all - the one thing it needs to know to cover the silence.
      for (const call of msg.functions || []) {
        if (call && call.client_side === false) session.lookups += 1;
        run_function(session, ws, call, say);
      }
      status(session, "thinking", say);
      // Only if the turn began before this client was listening (a reconnect mid-turn).
      arm(session, ws, say);
      break;
    case "FunctionCallResponse":
      session.lookups = Math.max(0, session.lookups - 1);
      break;
    case "AgentAudioDone":
      // The last chunk is scheduled, not played: the player says "listening" when it drains. And
      // the acknowledgement finishes with an AgentAudioDone of its own while the real answer is
      // still being looked up, which is thinking, not listening.
      if (session.lookups) status(session, "thinking", say);
      else if (!session.play.busy()) status(session, "listening", say);
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

/**
 * One frame of the mic while the agent is audible, judged for two things at once: is this our own
 * echo (measure it), and is this a person (let him through).
 *
 * Returns true when the frame may go up the socket. Everything else here is the local duck, which
 * is the same decision taken 0.4-2.2 s before Deepgram's UserStartedSpeaking can agree with it:
 * a duck is reversible and a flush is not, so this ducks and the server event flushes.
 */
function listen(session, rms, ms, say) {
  if (session.dead || !session.play) return true;
  // The harness turns the guard off to reproduce the loop against the same stub and the same
  // audio (web/tools/voice-echo.mjs). Nothing in the app ever writes this.
  if (!tuning.guard) return true;

  const speaking = session.play.audible(TAIL_MS);
  if (!speaking) {
    // The room is ours again. Everything about the last turn's echo is spent except the number.
    session.loudMs = 0;
    session.echoTurn = false;
    session.echoMs = 0;
    session.echoPeak = 0;
    if (session.gated) {
      session.gated = false;
      session.barged = false;
      session.held = [];
      session.heldMs = 0;
    }
    return true;
  }

  session.gated = true;
  // Already through the gate this turn: he is talking, keep sending.
  if (session.barged) return true;

  // CALIBRATION. The first ECHO_MS of a spoken turn is our own voice by definition - he has not
  // started talking yet, because the turn only just started - so whatever the mic hears here IS
  // the echo, at this room's volume, with this phone's speaker, past this device's canceller.
  if (!session.echoTurn) {
    session.echoMs += ms;
    if (rms > session.echoPeak) session.echoPeak = rms;
    if (session.echoMs >= ECHO_MS) {
      session.echoTurn = true;
      // Follow a rising echo at once and a falling one slowly: the threshold must never sit
      // under the echo, and the loudest thing this turn is the safest number to stand on.
      session.echo =
        session.echoPeak > session.echo ? session.echoPeak : session.echo * 0.7 + session.echoPeak * 0.3;
    }
    // Nothing goes up during calibration. This IS the loop, in one line: these are the frames
    // that used to make Deepgram answer its own greeting.
    return false;
  }

  if (rms < barge(session)) {
    session.loudMs = 0;
    return false;
  }
  session.loudMs += ms;
  if (session.loudMs < BARGE_MS) return false;

  // A real voice, over our own speaker, for long enough to be a sentence. Stop talking, send him
  // the words he has already said, and let the rest through until the turn is over.
  session.loudMs = 0;
  session.barged = true;
  session.play.flush();
  if (!session.ducked) say({ type: "interrupted" });
  session.ducked = false;
  if (session.unduck) {
    clearTimeout(session.unduck);
    session.unduck = 0;
  }
  status(session, "listening", say);
  return true;
}

/**
 * The softer half of the same decision: he is over the threshold but not yet for BARGE_MS, so the
 * answer drops to a whisper rather than stopping. If nothing confirms it inside UNDUCK_MS it was
 * a dropped spanner and the answer comes back up where it left off.
 */
function duck(session, rms, say) {
  if (session.ducked || session.barged || !session.play || !session.play.busy()) return;
  if (tuning.guard) {
    if (!session.echoTurn || rms < barge(session)) return;
  } else {
    // The rule as it shipped: a fixed RMS, held for three FRAMES. A worklet render quantum is 128
    // samples, so "three frames" was 16 ms, not the 130 ms the comment claimed - which is why the
    // agent ducked itself on its own first syllable.
    if (rms < 0.05) {
      session.loudMs = 0;
      return;
    }
    session.loudMs += 1;
    if (session.loudMs < 3) return;
    session.loudMs = 0;
  }
  session.ducked = true;
  session.play.duck(true);
  say({ type: "interrupted" });
  session.unduck = window.setTimeout(() => {
    session.unduck = 0;
    if (session.dead || !session.ducked) return;
    session.ducked = false;
    session.play.duck(false);
  }, UNDUCK_MS);
}

/** Mic -> fixed-size linear16 frames -> socket, with a decaying level for the meter. */
async function capture(session, ws, rate, say) {
  const ctx = session.ctx;
  let queue = new Float32Array(0);

  const send = (buffer) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    ws.send(buffer);
    session.sent += 1;
  };

  const push = (chunk) => {
    // RMS, not peak: the orb has to grow with how loud the sentence is, and a peak meter is
    // pinned at the top by the first consonant and says nothing after that.
    let sum = 0;
    for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
    const rms = Math.sqrt(sum / (chunk.length || 1));
    const ms = (chunk.length / (ctx.sampleRate || 1)) * 1000;
    // The orb rides the mic even while the guard is shut: he has to see that it hears him, and
    // the two are different questions. What he sees is never what we forward.
    session.level = Math.max(rms, session.level * LEVEL_DECAY);

    const open = listen(session, rms, ms, say);
    if (!open) duck(session, rms, say);

    const merged = new Float32Array(queue.length + chunk.length);
    merged.set(queue);
    merged.set(chunk, queue.length);
    queue = merged;
    while (queue.length >= FRAME) {
      const frame = pcm16(queue.subarray(0, FRAME), ctx.sampleRate, rate);
      queue = queue.slice(FRAME);
      if (open) {
        // A barge-in sends what he already said before it sends what he is saying: the guard was
        // holding the first syllables of the word that broke it.
        if (session.held.length) {
          for (const old of session.held) send(old);
          session.held = [];
          session.heldMs = 0;
        }
        send(frame);
        continue;
      }
      // Held, not dropped. PRIME_MS of the most recent frames, and the rest go.
      session.withheld += 1;
      session.held.push(frame);
      session.heldMs += (FRAME / rate) * 1000;
      while (session.heldMs > PRIME_MS && session.held.length > 1) {
        session.held.shift();
        session.heldMs -= (FRAME / rate) * 1000;
      }
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
}

/** Type a turn into a live session — the same path a spoken turn takes. Used by the tests. */
export function inject(text) {
  const s = current;
  const said = String(text || "").trim();
  if (!s || !s.ws || s.ws.readyState !== WebSocket.OPEN || !said) return false;
  s.ws.send(JSON.stringify({ type: "InjectUserMessage", content: said }));
  return true;
}
