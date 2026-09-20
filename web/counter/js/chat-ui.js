/**
 * Chat over the selected motorcycle's manual. Owner: chat-ui agent.
 * Files: this, ../css/chat-ui.css, ../../vendor/deep-chat/ (the forked component),
 * ttm.chat() + ttm.voiceSettings() (the only backend calls), ./voice-deepgram.js (voice mode),
 * web/docs/CHAT-UI.md (why deep-chat), web/docs/VOICE.md (how voice mode works).
 *
 * A FULL-SCREEN VIEW, NOT A DRAWER. Chat is a bus overlay on Pick — the same mechanics Parts
 * uses over Book: `registerOverlay("chat")`, `openOverlay("chat")` and the `#pick+chat` history
 * entry, so the header Back, Escape and the hardware Back button all close the chat and hand
 * Pick back with its 3D stage still standing. The overlay element is created here rather than
 * in index.html (another agent's file) and lives at body level, because a fixed sheet inside a
 * hidden <section> is a hidden sheet.
 *
 * THE FORK. deep-chat 2.5.1 (OvidijusParsiunas/deep-chat, MIT, 3.7k stars) is vendored under
 * web/vendor/deep-chat/ and imported lazily — 387 KB that must not sit in front of Identify.
 * Nothing in its source is patched; everything below is configuration:
 *   connect = {stream:true, handler}  our handler is the ONLY transport, so no key and no
 *                                     provider ever reaches the browser
 *   requestBodyLimits.maxMessages = 1 we keep the conversation ourselves (see `sessions`)
 *                                     and hand the API the whole thing, so its own six-turn
 *                                     memory window is the one that decides
 *   htmlClassUtilities                click handlers + styling for elements inside an `html`
 *                                     message — how a [p. N] chip becomes tappable
 *   messageStyles / textInput / submitButtonStyles / inputAreaStyle / auxiliaryStyle
 *                                     the Mechanica repaint. The component renders into an
 *                                     OPEN shadow root, so css/chat-ui.css cannot reach
 *                                     inside it; AUX below is injected through it instead.
 *   introMessage                      deliberately never set: the first bubble is empty.
 *
 * VOICE. The header's VOICE toggle opens a Deepgram Voice Agent session (./voice-deepgram.js),
 * and ./voice-orb.js puts the orb over the conversation for as long as it lasts — the orb owns
 * everything the rider sees in voice mode (state, level, the live line, interrupt, leave), so the
 * only thing this file does with it is mount it, feed it the session's meters and forward events.
 * Every finished turn it reports lands in the same `sessions` history as a typed one, so the
 * conversation is one conversation whichever way the question was asked, and `show_page` from
 * the agent takes the same jump() a citation chip takes. Hidden unless /voice/config says the
 * backend has a Deepgram key.
 *
 * mountChat(host, {manualId, bike, bikeId, onPage}) -> {open, close, toggle, isOpen, setContext, destroy}
 * `onPage(N)` is called with a printed page number when a citation chip is tapped or the agent
 * calls show_page; the screen that mounted us decides what that means (pick.js: a synthetic job,
 * then go("book")). It is always called AFTER the overlay has closed itself, so the screen's own
 * navigation starts from a settled history.
 *
 * History lives in `sessions`, keyed by manual, in memory for the session only: closing the
 * view keeps the conversation, changing bike starts a new one, a reload forgets it.
 */

import * as T from "./ttm.js";
import { registerOverlay, openOverlay, closeOverlay, overlayOpen } from "./bus.js";
import * as agent from "./voice-deepgram.js";
import { mountOrb } from "./voice-orb.js";

const BUNDLE = "../../vendor/deep-chat/deepChat.bundle.js";
const OVERLAY = "chat";

const INK = "#141414";
const PAPER = "#ece7dc";
const ORANGE = "#e85d04";
const YELLOW = "#ffe600";
const CARD = "#ffffff";
const SANS = "Barlow, system-ui, sans-serif";
const DISPLAY = '"Big Shoulders Display", sans-serif';

const NO_ANSWER = "No answer.";
const BARS = 5;

const SAY = {
  connecting: "Connecting…",
  listening: "Listening",
  thinking: "Thinking…",
  speaking: "Speaking",
  closed: "",
};

/**
 * Raw CSS handed to the component's shadow root — the only way in, and therefore also where the
 * VOICE button injected into #input is styled (see placeVoice).
 *
 * THE INPUT ROW. The component ships #text-input-container at width:80% with 0.8em margins and
 * floats the submit button over the field (`inside-end`, absolutely positioned). That reads as a
 * misaligned icon, and it leaves nowhere for a second button to stand. So: the submit button moves
 * out of the field (`outside-end`), #input becomes a real flex row, and the row is
 *     [ field flex-1 ] 8px [ VOICE 44x44 ] 8px [ SEND 44x44 ]
 * with every box 44 tall and every 3px border on the same two lines.
 */
const AUX = `
  #chat-view { background: ${PAPER}; }
  #messages { background: ${PAPER}; padding-top: 10px; scrollbar-width: thin; }
  #messages::-webkit-scrollbar { width: 8px; }
  #messages::-webkit-scrollbar-thumb { background: ${INK}; }
  .message-bubble { font-family: ${SANS}; font-weight: 400; font-size: 0.95rem; line-height: 1.35;
    border-radius: 0 !important; border: 3px solid ${INK}; max-width: 86%; }
  .message-bubble p { margin: 0 0 6px; }
  .message-bubble p:last-child { margin-bottom: 0; }
  .message-bubble ol, .message-bubble ul { margin: 2px 0 0 18px; }
  .message-bubble strong { font-weight: 800; }
  .html-message .message-bubble { border: 0 !important; background: transparent !important;
    padding: 0 !important; max-width: 100%; }
  .error-message-text { font-family: ${SANS}; font-weight: 800; font-size: 0.8rem;
    letter-spacing: 0.06em; text-transform: uppercase; background: ${INK} !important;
    color: ${YELLOW} !important; border-radius: 0 !important; border: 0 !important; }

  #input { box-sizing: border-box; display: flex; align-items: center; gap: 8px; }
  /* the component leaves four button slots around the field; the empty ones must not eat a gap */
  .input-button-container { flex: 0 0 auto; margin: 0 !important; padding: 0 !important;
    display: flex; align-items: center; }
  .input-button-container:empty { display: none; }
  #text-input-container { box-sizing: border-box; flex: 1 1 auto; min-width: 0; width: auto;
    min-height: 44px !important; height: 44px; margin: 0 !important; display: flex;
    align-items: center; }
  #text-input { flex: 1 1 auto; min-width: 0; font-family: ${SANS}; font-weight: 600;
    font-size: 1rem; line-height: 20px; padding: 9px 10px !important; max-height: 20px; }
  #text-input[textarea] { border-radius: 0; }
  /* border-box !important because the component sizes these boxes content-box, so a 44px box
     with a 3px border came out 50 wide and sat 3px proud of the field */
  .input-button { position: static !important; box-sizing: border-box !important;
    width: 44px !important; height: 44px !important; min-width: 44px; margin: 0 !important;
    padding: 0 !important; border-radius: 0 !important; display: flex !important;
    align-items: center; justify-content: center; }
  .input-button svg { display: block; margin: 0; }
  /* the component blows the lone submit button up by 10% and adds .3em either side, which is
     exactly the 48x48-in-a-44-row misalignment this row is here to fix */
  .input-button.submit-button-enlarged { scale: 1 !important; margin-inline: 0 !important; }

  /* the VOICE toggle, injected into the row next to SEND */
  .ttm-voice { flex: 0 0 auto; width: 44px; height: 44px; padding: 0; box-sizing: border-box;
    display: flex; align-items: center; justify-content: center; border: 3px solid ${INK};
    border-radius: 0; background: ${YELLOW}; color: ${INK}; cursor: pointer; appearance: none; }
  .ttm-voice svg { display: block; width: 20px; height: 20px; }
  /* the flex display above outranks the UA rule behind the hidden attribute */
  .ttm-voice[hidden] { display: none !important; }
  .ttm-voice.is-on { background: ${INK}; color: ${YELLOW}; }
  .ttm-voice.is-on svg { animation: ttm-pulse 1.1s ease-in-out infinite; }
  .ttm-voice:active { background: ${ORANGE}; color: #fff; }
  @media (hover: hover) { .ttm-voice:hover { background: ${ORANGE}; color: #fff; } }
  @keyframes ttm-pulse { 50% { opacity: 0.3; } }

  #scroll-button { border-radius: 0; border: 3px solid ${INK}; background: ${YELLOW}; }
`;

const MIC_BODY = "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z";
const MIC_ARC = "M5 11a7 7 0 0 0 14 0M12 18v3";

/** manualId -> [{role, content, citations?, saved?}] for this session. */
const sessions = new Map();

let bundle = null;

function load() {
  if (!bundle) bundle = import(BUNDLE);
  return bundle;
}

/* ------------------------------------------------------------------ helpers */

function node(tag, attrs) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  return el;
}

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

function glyph(paths) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2.2");
    path.setAttribute("stroke-linecap", "round");
    svg.append(path);
  }
  return svg;
}

/** The done frame's citations as one row of tappable chips, or "" when nothing was cited. */
function chipsHtml(citations) {
  const seen = new Set();
  const chips = [];
  for (const row of citations ?? []) {
    const page = Number(row && row.page);
    if (!page || seen.has(page)) continue;
    seen.add(page);
    chips.push(
      `<button type="button" class="cite-chip" data-page="${page}" title="${esc(row.quote)}">p. ${page}</button>`
    );
  }
  return chips.length ? `<div class="cite-row">${chips.join("")}</div>` : "";
}

/** deep-chat hands us {messages:[{role, text}]}; with maxMessages 1 that is the new question. */
function latest(body) {
  const rows = (body && body.messages) || [];
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (row && row.role && row.role !== "user") continue;
    const text = String((row && row.text) ?? "").trim();
    if (text) return text;
  }
  return "";
}

function turnsOf(id) {
  return (sessions.get(id) ?? []).map((t) => ({
    role: t.role === "assistant" ? "assistant" : "user",
    content: t.content,
  }));
}

function remember(id, turn) {
  if (!id) return;
  const rows = sessions.get(id) ?? [];
  rows.push(turn);
  sessions.set(id, rows);
}

/** The session replayed as deep-chat history: answer bubble, then its chips. */
function historyOf(id) {
  const out = [];
  for (const turn of sessions.get(id) ?? []) {
    if (turn.role === "user") {
      out.push({ role: "user", text: turn.content });
      continue;
    }
    out.push({ role: "ai", text: turn.content });
    const html = chipsHtml(turn.citations);
    if (html) out.push({ role: "ai", html });
  }
  return out;
}

function lastSaved(id) {
  const rows = sessions.get(id) ?? [];
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].role === "assistant") return Number(rows[i].saved) || 0;
  }
  return 0;
}

/* ------------------------------------------------------------------ mount */

export function mountChat(host, opts = {}) {
  if (!host) return null;

  let manualId = String(opts.manualId || "");
  let bikeId = String(opts.bikeId || "");
  let label = String(opts.bike || "");
  const onPage = typeof opts.onPage === "function" ? opts.onPage : () => {};

  let chat = null;
  let building = null;
  let shown = false;

  /* ---------------------------------------------------------- the shell */

  // Body level, not inside `host`: an overlay under a hidden <section> is a hidden overlay.
  // `host` stays the screen's marker that this view belongs to it.
  host.replaceChildren();
  host.hidden = true;

  const wrap = node("aside", { class: "ov cv", "data-overlay": OVERLAY, hidden: "" });
  const sheet = node("div", {
    class: "ov-sheet cv-sheet",
    role: "dialog",
    "aria-modal": "true",
    "aria-label": "Chat",
    "data-root": "",
  });

  const head = node("div", { class: "ov-head cv-head" });
  const title = node("div", { class: "cv-title" });
  const who = node("span", { class: "cv-bike", text: label });
  title.append(node("b", { text: "Chat" }), who);

  // The VOICE toggle lives in the input row, beside SEND — see placeVoice(). `cv-voice` stays on
  // it so the screenshot tool and any outside CSS can still find it.
  const voiceBtn = node("button", {
    type: "button",
    class: "cv-voice ttm-voice",
    "aria-label": "Voice",
    "aria-pressed": "false",
    hidden: "",
  });
  voiceBtn.append(glyph([MIC_BODY, MIC_ARC]));
  const shut = node("button", {
    type: "button",
    class: "ov-x cv-x",
    "data-ov-close": "",
    "aria-label": "Close",
    text: "✕",
  });
  head.append(title, shut);

  // The live voice strip: level meter + what the session is doing + the last thing said.
  const strip = node("div", { class: "cv-mic", hidden: "", role: "status", "aria-live": "polite" });
  const meter = node("div", { class: "cv-meter", "aria-hidden": "true" });
  const bars = [];
  for (let i = 0; i < BARS; i++) {
    const bar = node("i");
    bars.push(bar);
    meter.append(bar);
  }
  const said = node("span", { class: "cv-said" });
  strip.append(meter, said);

  const body = node("div", { class: "cv-body" });
  const foot = node("div", { class: "cv-foot", hidden: "" });

  sheet.append(head, strip, body, foot);
  wrap.append(sheet);
  document.body.append(wrap);

  // The orb lives over the conversation, not over the header: Back and ✕ stay reachable, and
  // nothing enters or leaves the flow when voice mode starts, so there is no layout shift.
  const orb = mountOrb(body, {
    levels: () => (voice ? { mic: voice.level(), out: voice.out() } : { mic: 0, out: 0 }),
    onInterrupt: () => {
      if (voice) voice.interrupt();
    },
    onLeave: stopVoice,
  });

  voiceBtn.addEventListener("click", toggleVoice);

  registerOverlay(OVERLAY, { mount: () => {}, open: opened, close: closed });

  /* ---------------------------------------------------------- the stat */

  function paintSaved(saved) {
    const n = Number(saved) || 0;
    foot.hidden = n <= 0;
    foot.textContent = n > 0 ? `${n.toLocaleString("en-US")} tokens saved` : "";
  }

  /* ---------------------------------------------------------- pages */

  /**
   * A citation chip or the agent's show_page. The overlay closes ITSELF first and the screen is
   * told on the far side of that history step, so Pick -> Book is one clean push either way.
   */
  function jump(page) {
    const n = Math.floor(Number(page) || 0);
    if (n <= 0) return;
    if (overlayOpen() === OVERLAY) {
      closeOverlay();
      window.setTimeout(() => onPage(n), 0);
      return;
    }
    onPage(n);
  }

  /* ---------------------------------------------------------- the transport */

  /**
   * deep-chat's custom request handler. `signals.onOpen()` drops the loading bubble, every
   * `onResponse({text})` appends into the live one (connect.stream), `onClose()` gives the
   * submit button back. The stop button aborts the fetch through the same AbortController.
   */
  function handler(build, signals) {
    const question = latest(build);
    const id = manualId;
    if (!question || !id) {
      signals.onResponse({ error: NO_ANSWER });
      return;
    }
    const turns = turnsOf(id);
    turns.push({ role: "user", content: question });

    let stopped = false;
    const ctl = new AbortController();
    if (signals.stopClicked) {
      signals.stopClicked.listener = () => {
        stopped = true;
        ctl.abort();
      };
    }
    signals.onOpen();

    T.chat(
      id,
      turns,
      (frame) => {
        if (frame && frame.type === "token" && frame.text) signals.onResponse({ text: String(frame.text) });
      },
      { signal: ctl.signal }
    )
      .then((done) => {
        signals.onClose();
        if (stopped) return;
        const answer = String(done.answer ?? "").trim();
        const citations = Array.isArray(done.citations) ? done.citations : [];
        const saved = Number(done.tokensSaved) || 0;
        remember(id, { role: "user", content: question });
        remember(id, { role: "assistant", content: answer, citations, saved });
        const html = chipsHtml(citations);
        if (html && chat) {
          try {
            chat.addMessage({ html, role: "ai" });
          } catch {
            /* the answer is already on screen; chips are a bonus */
          }
        }
        if (id === manualId) paintSaved(saved);
      })
      .catch(() => {
        if (stopped) {
          signals.onClose();
          return;
        }
        signals.onResponse({ error: NO_ANSWER });
      });
  }

  /* ---------------------------------------------------------- the component */

  function configure(el) {
    el.style.cssText = "width:100%;height:100%;border:none;border-radius:0;background:transparent;";
    el.connect = { stream: true, handler };
    el.requestBodyLimits = { maxMessages: 1 };
    el.errorMessages = { overrides: { default: NO_ANSWER } };
    el.auxiliaryStyle = AUX;
    el.messageStyles = {
      default: {
        shared: { bubble: { fontFamily: SANS } },
        user: { bubble: { background: INK, color: "#fff", borderColor: INK } },
        ai: { bubble: { background: CARD, color: INK, borderColor: INK } },
      },
      html: {
        shared: { outerContainer: { marginTop: "-4px" } },
      },
      loading: {
        message: { styles: { bubble: { background: CARD, borderColor: INK } } },
      },
    };
    el.textInput = {
      placeholder: { text: "Ask the manual", style: { color: "#8d8778", fontWeight: "600" } },
      styles: {
        container: {
          background: CARD,
          border: `3px solid ${INK}`,
          borderRadius: "0",
          boxShadow: "none",
          minHeight: "48px",
        },
        text: { color: INK, padding: "13px 12px" },
        focus: { outline: `3px solid ${ORANGE}`, outlineOffset: "-3px" },
      },
    };
    el.inputAreaStyle = {
      background: PAPER,
      borderTop: `3px solid ${INK}`,
      padding: "8px",
      boxSizing: "border-box",
    };
    // backgroundColor, not the `background` shorthand: the component merges its own defaults
    // into this object and the shorthand comes back out as `background-color: unset`.
    const square = (backgroundColor, border = INK) => ({
      backgroundColor,
      border: `3px solid ${border}`,
      borderRadius: "0",
      width: "44px",
      height: "44px",
      margin: "0",
    });
    // outside-end, not inside-end: inside-end absolutely positions the icon over the field, which
    // is what made it look misaligned. Out here it is one 44x44 box in the row.
    el.submitButtonStyles = {
      position: "outside-end",
      submit: {
        container: { default: square(INK), hover: square(ORANGE), click: square(ORANGE) },
        svg: { styles: { default: { filter: "brightness(0) invert(1)", width: "20px" } } },
      },
      loading: {
        container: { default: square(ORANGE) },
        svg: { styles: { default: { filter: "brightness(0) invert(1)" } } },
      },
      stop: {
        container: { default: square(ORANGE) },
        svg: { styles: { default: { filter: "brightness(0) invert(1)" } } },
      },
      disabled: {
        container: { default: square("#b9b2a3") },
        svg: { styles: { default: { filter: "brightness(0) invert(1)", width: "20px" } } },
      },
    };
    el.htmlClassUtilities = {
      "cite-row": { styles: { default: { display: "flex", flexWrap: "wrap", gap: "6px", padding: "2px 0" } } },
      "cite-chip": {
        events: {
          click: (event) => {
            const hit = event.target && event.target.closest ? event.target.closest(".cite-chip") : event.target;
            const page = Number(hit && hit.dataset && hit.dataset.page);
            if (page) jump(page);
          },
        },
        styles: {
          default: {
            display: "inline-flex",
            alignItems: "center",
            minHeight: "34px",
            padding: "0 10px",
            border: `3px solid ${INK}`,
            borderRadius: "0",
            background: YELLOW,
            color: INK,
            fontFamily: DISPLAY,
            fontWeight: "800",
            fontSize: "1rem",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontVariantNumeric: "tabular-nums",
            cursor: "pointer",
          },
          hover: { background: ORANGE, color: "#fff" },
          click: { background: INK, color: YELLOW },
        },
      },
    };
    el.history = historyOf(manualId);
  }

  /**
   * Put the VOICE toggle in the input row, immediately before SEND.
   *
   * The component renders into an OPEN shadow root and owns only the nodes it created, so a
   * button appended into #input survives its re-renders. This is the one place chat-ui reaches
   * inside the fork — the alternative is a second row under the field, which is exactly the
   * "chopped" shape the full-screen view was built to get rid of. Retried across a few frames
   * because #input appears one tick after the element is attached.
   */
  function placeVoice(el, tries = 20) {
    const root = el && el.shadowRoot;
    const row = root && root.querySelector("#input");
    if (!row) {
      if (tries > 0) requestAnimationFrame(() => placeVoice(el, tries - 1));
      return;
    }
    if (voiceBtn.parentNode === row) return;
    const send = [...row.querySelectorAll(".input-button-container")].find((c) => c.children.length);
    row.insertBefore(voiceBtn, send || null);
  }

  async function ensure() {
    if (chat) return chat;
    if (building) return building;
    building = load()
      .then(() => {
        const el = document.createElement("deep-chat");
        configure(el);
        body.append(el);
        chat = el;
        placeVoice(el);
        paintSaved(lastSaved(manualId));
        return el;
      })
      .catch(() => {
        body.replaceChildren(node("p", { class: "chat-dead", text: "Offline." }));
        return null;
      })
      .finally(() => {
        building = null;
      });
    return building;
  }

  /* ---------------------------------------------------------- voice mode */

  let voice = null; // the live session handle
  let voiceBusy = false;
  let raf = 0;
  let offered = null; // the /voice/config probe, once

  function paintVoice(status) {
    const on = Boolean(voice) || voiceBusy;
    voiceBtn.setAttribute("aria-pressed", on ? "true" : "false");
    voiceBtn.classList.toggle("is-on", on);
    const text = status == null ? "" : SAY[status] ?? "";
    // The orb says what the session is doing; the strip stays for the one thing the orb has no
    // word for, which is a session that failed to start.
    strip.hidden = true;
    sheet.classList.toggle("is-voice", on);
    if (orb) orb.setState(on ? status || "connecting" : "closed");
    if (text) said.textContent = text;
    if (!on) {
      said.textContent = "";
      for (const bar of bars) bar.style.transform = "scaleY(0.12)";
    }
  }

  function tick() {
    raf = 0;
    if (!voice) return;
    const level = Math.min(1, voice.level() * 2.2);
    for (let i = 0; i < bars.length; i++) {
      // Middle bars lead, outer bars trail: a voice, not an equaliser demo.
      const weight = 1 - Math.abs(i - (bars.length - 1) / 2) / bars.length;
      bars[i].style.transform = `scaleY(${(0.12 + level * weight).toFixed(3)})`;
    }
    raf = requestAnimationFrame(tick);
  }

  function startMeter() {
    if (!raf) raf = requestAnimationFrame(tick);
  }

  function stopMeter() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  /**
   * Every finished turn joins the typed conversation, so the history is one history.
   *
   * The agent answers one SENTENCE per ConversationText, so a two-sentence answer would land as
   * two bubbles from the same breath. `part` marks every sentence after the first of a turn and
   * it is appended to the message already there instead.
   */
  function transcribe(role, text, part) {
    const clean = String(text || "").trim();
    if (!clean) return;
    const rows = sessions.get(manualId) ?? [];
    const last = rows[rows.length - 1];
    if (part && last && last.role === "assistant") {
      last.content = `${last.content} ${clean}`.trim();
    } else {
      remember(manualId, role === "user" ? { role: "user", content: clean } : { role: "assistant", content: clean, citations: [], saved: 0 });
    }
    if (orb) orb.setLine(clean);
    said.textContent = clean;
    if (!chat) return;
    try {
      if (part) chat.addMessage({ text: clean, role: "ai" });
      else chat.addMessage({ text: clean, role: role === "user" ? "user" : "ai" });
    } catch {
      /* the orb already showed it */
    }
  }

  function stopVoice() {
    const live = voice;
    voice = null;
    voiceBusy = false;
    stopMeter();
    if (live) {
      try {
        live.stop();
      } catch {
        /* already gone */
      }
    }
    paintVoice(null);
  }

  async function startVoice() {
    if (voice || voiceBusy || !manualId) return;
    voiceBusy = true;
    paintVoice("connecting");
    await ensure();
    try {
      voice = await agent.start({
        manualId,
        bikeId,
        on: (event) => {
          if (event.type === "status") {
            if (event.value === "closed") {
              stopVoice();
              return;
            }
            paintVoice(event.value);
            return;
          }
          if (event.type === "text") {
            transcribe(event.role, event.text, event.part);
            return;
          }
          if (event.type === "interrupted") {
            // The rider talked over the answer. Say so where he is already looking.
            if (orb) orb.setLine("…");
            return;
          }
          if (event.type === "page") {
            jump(event.page);
            return;
          }
          if (event.type === "error") {
            strip.hidden = false;
            said.textContent = event.message || "Voice failed.";
            stopMeter();
          }
        },
      });
      voiceBusy = false;
      paintVoice("listening");
      startMeter();
    } catch {
      voiceBusy = false;
      voice = null;
      paintVoice(null);
      strip.hidden = false;
      said.textContent = "Voice unavailable.";
      window.setTimeout(() => {
        if (!voice) strip.hidden = true;
      }, 2600);
    }
  }

  function toggleVoice() {
    if (voice || voiceBusy) stopVoice();
    else startVoice();
  }

  /** The toggle only exists when the backend has a Deepgram key and this browser can capture. */
  function offerVoice() {
    if (offered) return offered;
    offered = (agent.supported ? T.voiceConfig() : Promise.resolve(null))
      .then((cfg) => {
        const ok = Boolean(cfg && cfg.deepgram);
        voiceBtn.hidden = !ok;
        return ok;
      })
      .catch(() => {
        voiceBtn.hidden = true;
        return false;
      });
    return offered;
  }

  /* ---------------------------------------------------------- the view */

  /** bus opened the overlay. */
  function opened() {
    shown = true;
    offerVoice();
    ensure().then((el) => {
      if (!el || !shown) return;
      try {
        el.focusInput();
      } catch {
        /* a closed keyboard is not a failure */
      }
    });
  }

  /** bus closed the overlay — by ✕, Escape, Back, or a screen change. */
  function closed() {
    shown = false;
    stopVoice();
  }

  function open() {
    if (shown) return;
    openOverlay(OVERLAY);
  }

  function close() {
    if (!shown) return false;
    if (overlayOpen() === OVERLAY) closeOverlay();
    else closed();
    return true;
  }

  /**
   * A different manual is a different conversation: drop the component so it rebuilds with
   * that manual's own history (deep-chat reads `history` once, at first render).
   */
  function setContext(next = {}) {
    if (next.bike !== undefined) {
      label = String(next.bike || "");
      who.textContent = label;
    }
    if (next.bikeId !== undefined) bikeId = String(next.bikeId || "");
    if (next.manualId === undefined) return;
    const id = String(next.manualId || "");
    if (id === manualId) return;
    manualId = id;
    stopVoice();
    if (chat) {
      chat.remove();
      chat = null;
    }
    body.replaceChildren();
    paintSaved(lastSaved(manualId));
    if (shown) ensure();
  }

  function destroy() {
    close();
    stopVoice();
    if (orb) orb.destroy();
    if (chat) chat.remove();
    chat = null;
    wrap.remove();
    host.replaceChildren();
    host.hidden = true;
  }

  return {
    open,
    close,
    toggle: () => (shown ? close() : open()),
    isOpen: () => shown,
    setContext,
    destroy,
  };
}
