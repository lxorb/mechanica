/**
 * The voice orb. Owner: voice agent. Pairs with ../css/voice-orb.css; mounted by voice-session.js.
 *
 * WHAT IT IS. One round thing that is listening to you, and it lives above the whole app rather
 * than inside one view: the mechanic's hands are on the bike, he is a metre from the phone, and
 * the only affordance that survives that is a target the size of his fist in the place his eye
 * already is.
 *
 * TWO SIZES, ONE ELEMENT. Opened from the chat it is FULL: the screen is the orb, because there
 * is nothing else to look at yet. The moment the manual is up it DOCKS — the same element, a
 * transform away, sitting above the reader's thumb row with one line of transcript beside it —
 * because now the page is the thing to look at and the assistant is a companion to it, not a
 * replacement for it. Nothing unmounts, nothing reconnects, nothing stops listening.
 *
 * WHAT IT SAYS, WITHOUT WORDS.
 *   listening  the disc breathes, and rides the mic's own RMS on top of the breath, so he can see
 *              that it heard him before he has finished the sentence
 *   thinking   the breath stops and three rings leave the edge — a lookup is running, and the
 *              stillness in the middle is the difference between "working" and "hung"
 *   speaking   the breath stops again and the disc pulses on the agent's OUTPUT level, so the
 *              shape on screen is the shape of the voice in the room
 *
 * THE THREE GESTURES. Tap while it is talking: stop the answer. Tap while it is not: dock or
 * undock. Long press: leave. A tap has to mean "be quiet" while it is talking, because that is
 * the only thing anyone ever wants from a talking machine, and it cannot mean two things at once.
 *
 * SIXTY FRAMES, NO LAYOUT. One requestAnimationFrame loop writes two custom properties, `--s`
 * (scale) and `--g` (glow), and the stylesheet turns those into a transform and an opacity. No
 * width, height, margin or top is ever touched — by the loop or by the dock, which is one more
 * transform on the same element. The loop does not run when the orb is not mounted.
 *
 * REDUCED MOTION. No breath, no ripple, no pulse, and the dock is instant: `--lvl` drives a ring
 * that fills instead, which moves nothing. The state word still changes, which is the part that
 * actually carries the meaning.
 *
 * mountOrb(host, {levels, onInterrupt, onLeave, onToggle})
 *   -> {setState, setLine, setDock, chip, isCompact, el, destroy}
 *   levels()      -> {mic, out} in 0..1, pulled once a frame; the session owns the meters
 *   onInterrupt() tapped while the agent was talking - stop it
 *   onToggle()    tapped while it was not - the other size
 *   onLeave()     the x, or a long press on the orb - leave voice mode
 */

const WORDS = {
  connecting: "Connecting",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  closed: "",
};

// A long press is how you leave without aiming at a 44px x with a glove on.
const HOLD_MS = 600;
// Breath: one slow cycle, ±3.5% of the disc. Any faster and it reads as a heartbeat monitor.
const BREATH_MS = 3400;
const BREATH = 0.035;
// How hard the mic and the agent's own level push the disc. The mic is scaled harder because a
// question asked a metre away is quiet and still has to look like it landed.
const MIC_GAIN = 0.42;
const OUT_GAIN = 0.3;
// Levels are pulled once a frame and smoothed here rather than in the session, so the meter can
// rise fast (you see the word land) and fall slowly (it does not flicker between syllables).
const RISE = 0.5;
const FALL = 0.12;
// A figure with a page on it, shown beside the orb and then gone. Long enough to read twice.
const CHIP_MS = 5200;

const reduced = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function el(tag, attrs = {}) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

const CHEVRON = "M6 9l6 6 6-6";

/**
 * The stylesheet comes with the module rather than with a <link> in index.html or an @import in
 * another agent's screen CSS: this is the only file that needs it and it is the only file that
 * knows where it lives. Once per document, idempotent.
 */
function styled() {
  if (typeof document === "undefined") return;
  const href = new URL("../css/voice-orb.css", import.meta.url).href;
  if (document.querySelector(`link[data-voice-orb]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.setAttribute("data-voice-orb", "");
  document.head.append(link);
}

export function mountOrb(host, opts = {}) {
  if (!host) return null;
  styled();
  const levels = typeof opts.levels === "function" ? opts.levels : () => ({ mic: 0, out: 0 });
  const onInterrupt = typeof opts.onInterrupt === "function" ? opts.onInterrupt : () => {};
  const onLeave = typeof opts.onLeave === "function" ? opts.onLeave : () => {};
  const onToggle = typeof opts.onToggle === "function" ? opts.onToggle : () => {};

  const wrap = el("div", { class: "vo is-full", hidden: "" });
  // The whole overlay is one live region: the state word is what a screen reader needs, and it is
  // the only thing that changes often enough to be worth announcing.
  const line = el("div", { class: "vo-line", "aria-hidden": "true" });
  const orb = el("button", {
    type: "button",
    class: "vo-orb",
    "aria-label": "Stop the answer",
  });
  for (let i = 0; i < 3; i++) orb.append(el("i", { class: "vo-ring", "aria-hidden": "true" }));
  const state = el("div", { class: "vo-state", role: "status", "aria-live": "polite" });
  const shut = el("button", { type: "button", class: "vo-x", "aria-label": "Leave voice mode", text: "✕" });

  // The one thing an answer leaves behind on the page: the figure and the page it is printed on,
  // beside the orb, gone before it is clutter. He heard it; this is so he can check he did.
  const chipEl = el("div", { class: "vo-chip", "aria-hidden": "true" });

  const back = el("button", { type: "button", class: "vo-back", "aria-label": "Dock the orb" });
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2.4");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", CHEVRON);
  svg.append(path);
  back.append(svg, document.createTextNode("Manual"));

  wrap.append(line, orb, state, chipEl, shut, back);
  host.append(wrap);

  let raf = 0;
  let value = "closed";
  let mic = 0;
  let out = 0;
  let compact = false;
  let hold = 0;
  let held = false;
  let t0 = 0;
  let chipTimer = 0;

  /* ---------------------------------------------------------- the loop */

  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (!t0) t0 = now;
    const live = levels() || {};
    const wantMic = Math.min(1, Math.max(0, Number(live.mic) || 0));
    const wantOut = Math.min(1, Math.max(0, Number(live.out) || 0));
    mic += (wantMic - mic) * (wantMic > mic ? RISE : FALL);
    out += (wantOut - out) * (wantOut > out ? RISE : FALL);

    if (reduced()) {
      // No motion at all: the level is a ring that fills, which changes nothing about the layout.
      const lvl = value === "speaking" ? out : mic;
      orb.style.setProperty("--lvl", lvl.toFixed(3));
      orb.style.setProperty("--g", (0.25 + lvl * 0.5).toFixed(3));
      return;
    }

    let scale = 1;
    let glow = 0.22;
    if (value === "speaking") {
      scale = 1 + out * OUT_GAIN;
      glow = 0.3 + out * 0.6;
    } else if (value === "thinking") {
      // Still in the middle; the rings do the talking. A thinking orb that also breathed would
      // read as listening, which is the one thing it is not doing.
      scale = 1;
      glow = 0.34;
    } else {
      const breath = Math.sin(((now - t0) / BREATH_MS) * Math.PI * 2);
      scale = 1 + breath * BREATH + mic * MIC_GAIN;
      glow = 0.2 + mic * 0.7;
    }
    orb.style.setProperty("--s", scale.toFixed(4));
    orb.style.setProperty("--g", glow.toFixed(3));
  }

  function run() {
    if (!raf) raf = requestAnimationFrame(frame);
  }

  function halt() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    t0 = 0;
  }

  /* ---------------------------------------------------------- the taps */

  function press() {
    held = false;
    hold = window.setTimeout(() => {
      held = true;
      hold = 0;
      onLeave();
    }, HOLD_MS);
  }

  function release() {
    if (hold) {
      clearTimeout(hold);
      hold = 0;
    }
  }

  orb.addEventListener("pointerdown", press);
  orb.addEventListener("pointerup", release);
  orb.addEventListener("pointercancel", release);
  orb.addEventListener("pointerleave", release);
  orb.addEventListener("click", (event) => {
    event.preventDefault();
    // The long press already left; the click that follows it is not a second command.
    if (held) {
      held = false;
      return;
    }
    // While it is talking a tap means one thing and it is not "resize".
    if (value === "speaking") {
      onInterrupt();
      return;
    }
    onToggle();
  });

  shut.addEventListener("click", (event) => {
    event.preventDefault();
    onLeave();
  });

  back.addEventListener("click", (event) => {
    event.preventDefault();
    onToggle();
  });

  /* ---------------------------------------------------------- the face */

  /** Full screen, or a companion in the corner. One transform apart; nothing remounts. */
  function setDock(mode) {
    const next = mode === "compact";
    if (next === compact) return;
    compact = next;
    wrap.classList.toggle("is-compact", compact);
    wrap.classList.toggle("is-full", !compact);
    orb.setAttribute("aria-label", compact ? "Open voice full screen" : "Stop the answer");
  }

  function setState(next) {
    const name = WORDS[next] === undefined ? "listening" : next;
    if (name === value) return;
    value = name;
    orb.classList.toggle("is-thinking", name === "thinking");
    orb.classList.toggle("is-speaking", name === "speaking");
    state.textContent = WORDS[name] || "";
    const on = name !== "closed";
    wrap.hidden = !on;
    if (on) run();
    else {
      halt();
      setDock("full");
      chip("");
      line.classList.remove("is-on");
      line.textContent = "";
      orb.style.setProperty("--s", "1");
      orb.style.setProperty("--g", "0");
      mic = 0;
      out = 0;
    }
  }

  /** One line, one line only: the last thing either of them said. */
  function setLine(text) {
    const clean = String(text || "").trim();
    line.textContent = clean;
    line.classList.toggle("is-on", Boolean(clean));
  }

  /** "p. 85 · DOT four" — the figure, where it is printed, and then gone. */
  function chip(text) {
    const clean = String(text || "").trim();
    if (chipTimer) {
      clearTimeout(chipTimer);
      chipTimer = 0;
    }
    chipEl.textContent = clean;
    chipEl.classList.toggle("is-on", Boolean(clean));
    if (!clean) return;
    chipTimer = window.setTimeout(() => {
      chipTimer = 0;
      chipEl.classList.remove("is-on");
    }, CHIP_MS);
  }

  function destroy() {
    halt();
    release();
    if (chipTimer) clearTimeout(chipTimer);
    wrap.remove();
  }

  return {
    setState,
    setLine,
    setDock,
    chip,
    isCompact: () => compact,
    el: wrap,
    destroy,
  };
}
