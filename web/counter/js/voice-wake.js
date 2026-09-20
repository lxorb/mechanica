/**
 * "Mechanica." The wake word. Owner: voice agent.
 *
 * WHY IT EXISTS. The mechanic's hands are on the bike and there is a phone on the bench two feet
 * away with brake fluid on his gloves. Tapping a button is the one thing he cannot do. So the
 * whole app has to start with a word, and the word has to carry the sentence with it: "Mechanica,
 * I'm working on a YZF R1" opens the session AND asks the first question, in one breath.
 *
 * WHY THE WEB SPEECH API AND NOT DEEPGRAM. An always-on Deepgram socket is $0.075 a minute and a
 * microphone permanently on the wire; a wake word has to be free and has to stay in the room.
 * `webkitSpeechRecognition` is on-device-or-Google's-service depending on the browser, costs
 * nothing, and is the only continuous recogniser a web page gets. It is worse at transcribing
 * than Deepgram by a distance — which is exactly why it is only ever asked ONE question, "did
 * this contain the word", and the sentence it heard is handed to Deepgram to hear properly.
 *
 * OFF BY DEFAULT, AND BY A TAP. A page cannot open a microphone without a gesture and should not
 * want to: the toggle beside the theme disc is the gesture and the consent, and the choice is
 * remembered (localStorage, not session — "my shop phone listens" is a preference).
 *
 * IT STOPS LISTENING WHEN SOMETHING ELSE IS. While the Deepgram session is live the wake listener
 * is off: two recognisers on one microphone is a fight nobody wins, and the agent's own voice
 * coming back would trigger it. Same when the tab is hidden.
 *
 * WHAT COUNTS AS THE WORD. "mechanica", "mechanika", "mecanica", "mechanica's", and "mechanic a"
 * — which is what Chrome most often returns for it. Deliberately NOT the bare word "mechanic":
 * this is a workshop, somebody says "mechanic" every ten minutes, and a false start that opens a
 * paid socket and talks over the room is worse than a missed one he can repeat.
 */

const KEY = "mechanica.wake";
/** Restart after `end` — Chrome ends a continuous session every ~60 s on its own. */
const RESTART_MS = 250;
/** After a trigger, ignore the same words arriving again as a final result. */
const COOLDOWN_MS = 2500;

const WAKE = /\bme(?:ch|k|c)h?an(?:ic|ik|ica|ika)\s*(?:a|ah|er)?\b/i;
/** The same word, but as a word we will not fire on: bare "mechanic", "mechanical", "mechanics". */
const NOT_WAKE = /\bmechanics?\b|\bmechanical(?:ly)?\b/i;

export const supported =
  typeof window !== "undefined" &&
  Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

/**
 * Did he say it, and what did he say after it?
 *
 * Exported because it is the part worth testing on its own: web/tools/wake-test.mjs runs ten
 * minutes of shop speech through it and counts what it fires on.
 */
export function heard(text) {
  const said = String(text || "").trim();
  if (!said) return null;
  const hit = WAKE.exec(said);
  if (!hit) return null;
  // "the mechanic said" is not a summons. Check the actual matched word, not the sentence:
  // "mechanica, ask the mechanic" must still fire.
  if (NOT_WAKE.test(hit[0])) return null;
  const rest = said
    .slice(hit.index + hit[0].length)
    .replace(/^[\s,.:;!?-]+/, "")
    .trim();
  return { at: hit.index, word: hit[0], rest };
}

let rec = null;
let on = false;
let paused = false;
let restart = 0;
let last = 0;
let onWake = () => {};
let button = null;

function stored() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function remember(value) {
  try {
    localStorage.setItem(KEY, value ? "1" : "0");
  } catch {
    /* private mode: the toggle still works for this visit */
  }
}

function paint() {
  if (!button) return;
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.classList.toggle("is-on", on);
  button.classList.toggle("is-live", on && !paused);
  button.setAttribute(
    "aria-label",
    on ? "Stop listening for Mechanica" : "Listen for Mechanica",
  );
}

function stopRec() {
  const r = rec;
  rec = null;
  if (restart) {
    clearTimeout(restart);
    restart = 0;
  }
  if (!r) return;
  r.onresult = null;
  r.onend = null;
  r.onerror = null;
  try {
    r.stop();
  } catch {
    /* already gone */
  }
}

function startRec() {
  if (rec || !on || paused || !supported) return;
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  const r = new Ctor();
  r.lang = "en-US";
  r.continuous = true;
  // Interim results are the whole point: waiting for a final result costs a second of silence
  // after he has already stopped talking, and the wake word is the one place that second shows.
  r.interimResults = true;
  r.maxAlternatives = 1;
  r.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const said = event.results[i][0] && event.results[i][0].transcript;
      const hit = heard(said);
      if (!hit) continue;
      const now = performance.now();
      // An interim result becomes a final result carrying the same words: fire once.
      if (now - last < COOLDOWN_MS) continue;
      // Only fire on the interim once the sentence looks finished, OR on the final: "mechanica"
      // alone, still being spoken, is not yet "mechanica, I'm working on a YZF R1".
      if (!event.results[i].isFinal && !hit.rest) continue;
      last = now;
      onWake({ rest: hit.rest, text: String(said || "").trim(), final: event.results[i].isFinal });
      return;
    }
  };
  r.onerror = (event) => {
    // "no-speech" and "aborted" are ordinary in a quiet shop; "not-allowed" is the mechanic
    // saying no, and it turns the whole thing off rather than retrying at him for ever.
    if (event && (event.error === "not-allowed" || event.error === "service-not-allowed")) {
      enable(false);
      return;
    }
    schedule();
  };
  r.onend = schedule;
  rec = r;
  try {
    r.start();
  } catch {
    // start() on a recogniser that is already running throws; the end handler will re-arm it.
    schedule();
  }
  paint();
}

function schedule() {
  rec = null;
  if (!on || paused) {
    paint();
    return;
  }
  if (restart) return;
  restart = window.setTimeout(() => {
    restart = 0;
    startRec();
  }, RESTART_MS);
}

/** Something else is using the microphone, or nobody is looking. */
export function pause(value) {
  const want = Boolean(value);
  if (want === paused) return;
  paused = want;
  if (paused) stopRec();
  else startRec();
  paint();
}

export function enable(value) {
  const want = Boolean(value);
  on = want;
  remember(want);
  if (want) startRec();
  else stopRec();
  paint();
  return on;
}

export function enabled() {
  return on;
}

export function listening() {
  return on && !paused && Boolean(rec);
}

/* ------------------------------------------------------------------ the toggle */

const EAR = [
  // An ear, drawn the way every other glyph in this app is: one stroke, no fill.
  "M8.5 9a3.5 3.5 0 1 1 7 0c0 2-1.6 2.6-2.3 3.6-.6.9-.5 1.8-.5 2.6",
  "M12.7 18.2v.2",
  "M5.2 9a6.8 6.8 0 0 1 13.6 0c0 4.2-2.6 5.4-3.4 7.4-.5 1.2-.4 2.6-.4 3.6",
];

function glyph() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of EAR) {
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("fill", "none");
    p.setAttribute("stroke", "currentColor");
    p.setAttribute("stroke-width", "2");
    p.setAttribute("stroke-linecap", "round");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}

const CSS = `
.ticket-wake {
  display: flex; align-items: center; justify-content: center;
  flex: 0 0 auto; width: 44px; height: 44px; padding: 0;
  border: 0; background: none; color: var(--accent-ink, #fff);
  opacity: 0.55; cursor: pointer; appearance: none;
  transition: opacity 0.18s linear, color 0.18s linear;
}
.ticket-wake svg { display: block; width: 21px; height: 21px; }
.ticket-wake.is-on { opacity: 1; color: var(--accent-2, #ffe600); }
/* Live: the ear breathes, very slightly, so "it is listening" is visible from the bench and
   still nothing anyone has to look at. */
.ticket-wake.is-live svg { animation: wake-breathe 2.6s ease-in-out infinite; }
@keyframes wake-breathe { 0%, 100% { opacity: 0.62; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .ticket-wake.is-live svg { animation: none; } }
.ticket-wake:focus-visible { outline: 3px solid var(--accent-ink, #fff); outline-offset: -3px; }
`;

/**
 * The toggle, beside the theme disc, made here rather than in index.html: this is the only module
 * that needs it and the only one that knows what it means. Returns the button, or null when the
 * browser has no continuous recogniser — an affordance that cannot work must not be on screen.
 */
export function mountToggle(onWakeFn) {
  if (typeof document === "undefined") return null;
  onWake = typeof onWakeFn === "function" ? onWakeFn : () => {};
  if (!supported) return null;
  const bar = document.querySelector("header.ticket");
  const theme = bar && bar.querySelector("[data-theme-button]");
  if (!bar) return null;

  if (!document.querySelector("style[data-voice-wake]")) {
    const style = document.createElement("style");
    style.setAttribute("data-voice-wake", "");
    style.textContent = CSS;
    document.head.append(style);
  }

  button = document.createElement("button");
  button.type = "button";
  button.className = "ticket-wake";
  button.setAttribute("data-wake-button", "");
  button.setAttribute("aria-pressed", "false");
  button.append(glyph());
  bar.insertBefore(button, theme || null);
  button.addEventListener("click", () => enable(!on));

  // The gesture requirement is why this is a toggle and not a setting: a remembered "yes" still
  // cannot open the microphone until the page has been touched once, so the first interaction of
  // the visit arms it and nothing pops a permission prompt at a page nobody has touched.
  if (stored()) {
    const arm = () => enable(true);
    document.addEventListener("pointerdown", arm, { once: true, capture: true });
    document.addEventListener("keydown", arm, { once: true, capture: true });
    on = true;
    paint();
    on = false;
  }

  // Nobody is in front of the phone: stop listening rather than burning a recogniser on an empty
  // room, and pick it up again when he comes back.
  document.addEventListener("visibilitychange", () => pause(document.hidden));
  window.addEventListener("mechanica:voice", (e) => {
    const kind = e && e.detail && e.detail.kind;
    // One microphone, one listener. The Deepgram session is the better recogniser and it is the
    // one being paid for; this one gets out of its way and comes back when it ends.
    if (kind === "started") pause(true);
    else if (kind === "ended") pause(false);
  });

  paint();
  return button;
}
