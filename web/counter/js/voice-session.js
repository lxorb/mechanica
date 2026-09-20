/**
 * The assistant that outlives the screen. Owner: voice agent.
 *
 * WHY THIS FILE EXISTS. Voice used to be a mode of the chat drawer: the session was a local
 * variable inside chat-ui.js, the orb was mounted into the conversation, and closing the chat —
 * which is what happens the instant you open the manual — called `stop()`. So the assistant you
 * had just asked for page 85 hung up on the way to page 85. A mechanic does not want a voice
 * inside a chat window; he wants a voice in the room for the whole job. This module is that: ONE
 * session, owned by nobody's screen, that is started once and answers from Pick, from the reader,
 * from the Parts sheet and from the chat, until he ends it or leaves the page.
 *
 * WHAT IT OWNS. The socket, the microphone, the playback, the transcript, the state, and the orb.
 * The orb's host is a single `position: fixed` div on <body>, created here and never moved, so a
 * screen change is invisible to it — no unmount, no remount, no reconnect, no gap in listening.
 *
 * HOW SCREENS TALK TO IT, AND IT TO THEM. They do not import it and it does not import them.
 *   in   `window.dispatchEvent(new CustomEvent("mechanica:voice-toggle"))` starts or ends it
 *   out  `window.addEventListener("mechanica:voice", e => e.detail)` carries everything else
 * The one exception is chat-ui.js, which mounts the toggle and registers where a page lives when
 * the reader is not on screen (`onPage`), because getting from Pick to a page is the chat's own
 * jump and there is no reason to write it twice.
 *
 * WHAT THE ANSWERS DO TO THE PAGE.
 *   a page named, or show_page      the reader turns and the page's marker pulses
 *   "next" / "previous" / "back"    the reader steps, with no round trip at all
 *   a figure with a page on it      a chip beside the orb, five seconds, then gone
 * The page half is not new — it is why this product exists — but it now happens from wherever he
 * is standing instead of only from inside the chat.
 *
 * WHERE THE ORB SITS. Full screen when he opened it from the chat, because there is nothing else
 * to look at yet; docked into the corner the moment the manual is up, because now there is. That
 * is the `on("screen")` subscription below and nothing more: Book docks it, anything else does
 * not, and his own tap overrides both until the next screen change.
 *
 * ENDING CLEANLY. `pagehide` and `offline` end the session. A zombie socket costs $0.075 a minute
 * and a phone that is listening after the app is gone is worse than that.
 */

import { on as busOn, state as busState } from "./bus.js";
import * as agent from "./voice-deepgram.js";
import { mountOrb } from "./voice-orb.js";

/** How far off the bottom the docked orb sits when the reader's thumb row is not measurable. */
const DOCK_GAP = 24;
/** Clear of the thumb row by this much when it is. */
const DOCK_CLEARANCE = 16;
/** One line of transcript is worth keeping; a scrollback is the chat's job, not the orb's. */
const KEEP = 60;

/* "page 85", "pages 85 and 86" - the printed page an answer names. Only ever "page N": a bare
   number in an answer is a torque or a capacity, never somewhere to go. */
const NAMED_PAGE = /\bpages?\s+(\d{1,4})\b/i;
/* The next thing he says after a page is the figure, and the two together are the whole answer. */
const FIGURE = /\bpages?\s+\d{1,4}\s*[,.:-]?\s*(.{3,60}?)\s*$/i;
/* Said to the reader, not to the model: these never wait for a round trip. */
const NEXT = /^(?:ok(?:ay)?[, ]+)?(?:next|next page|forward|scroll down|go on|keep going)\b[.!]?$/i;
const PREV = /^(?:ok(?:ay)?[, ]+)?(?:previous|previous page|back|go back|last page|scroll up)\b[.!]?$/i;

let live = null; // the voice-deepgram handle
let orb = null;
let host = null;
let starting = false;
let ctx = { manualId: "", bikeId: "", bike: "" };
let screen = "";
let userDock = null; // his own tap wins until the next screen change
let pageSink = null; // how to get to a page when the reader is not the screen on show
let transcript = [];
let wired = false;

/* ------------------------------------------------------------------ out */

/** Everything a screen can know about the session, and the only way it learns any of it. */
function shout(detail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("mechanica:voice", { detail }));
}

export const supported = agent.supported;

export function isLive() {
  return Boolean(live || starting);
}

export function status() {
  return live ? live.status() : "closed";
}

export function lines() {
  return transcript.slice();
}

/** chat-ui.js registers the one thing it knows and this module does not: where a page lives. */
export function onPage(fn) {
  pageSink = typeof fn === "function" ? fn : null;
}

export function setContext(next = {}) {
  const before = ctx.manualId;
  if (next.manualId !== undefined) ctx.manualId = String(next.manualId || "");
  if (next.bikeId !== undefined) ctx.bikeId = String(next.bikeId || "");
  if (next.bike !== undefined) ctx.bike = String(next.bike || "");
  // A different manual is a different book, and an agent grounded in the old one must not answer
  // about the new one. That is the one context change worth hanging up for.
  if (before && ctx.manualId && before !== ctx.manualId && isLive()) stop();
}

/* ------------------------------------------------------------------ the orb's home */

/**
 * One fixed layer on <body>, made once. Not inside a screen and not inside the chat overlay:
 * both of those are removed, hidden or re-rendered by their owners, and an orb that lives in one
 * of them is an orb that stops existing when its landlord changes screens.
 */
function home() {
  if (host && host.isConnected) return host;
  host = document.createElement("div");
  host.className = "vo-host";
  document.body.append(host);
  return host;
}

/** The reader's thumb row is the one thing the docked orb must never cover. Measure it. */
function dockGap() {
  const acts = document.querySelector(".book-acts");
  if (!acts) return DOCK_GAP;
  const box = acts.getBoundingClientRect();
  if (!box.height) return DOCK_GAP;
  // Distance from the bottom of the viewport to the top of the row, plus a thumb's worth.
  return Math.round(window.innerHeight - box.top + DOCK_CLEARANCE);
}

function applyDock(mode) {
  if (!orb) return;
  orb.el.style.setProperty("--dock-gap", `${dockGap()}px`);
  orb.setDock(mode);
  shout({ kind: "dock", dock: mode });
}

/** Where the orb belongs right now: his own choice first, then the screen's. */
function want() {
  if (userDock) return userDock;
  return screen === "book" ? "compact" : "full";
}

function ensureOrb() {
  if (orb) return orb;
  orb = mountOrb(home(), {
    levels: () => (live ? { mic: live.level(), out: live.out() } : { mic: 0, out: 0 }),
    onInterrupt: () => {
      if (live) live.interrupt();
    },
    onToggle: () => {
      userDock = orb.isCompact() ? "full" : "compact";
      applyDock(userDock);
    },
    onMute: (on) => mute(on),
    onLeave: stop,
  });
  return orb;
}

/**
 * The microphone off, and nothing else off.
 *
 * A workshop is not a quiet room: an impact wrench, a radio, a colleague on the phone. "Mute"
 * here means the shop stops being heard — the track is disabled at the source, so Deepgram
 * receives silence and there is no path left by which a frame could reach it. It deliberately
 * does NOT stop the answer in flight and does not close anything: muting yourself is not
 * hanging up, and a mute that cut the sentence you were listening to would be the opposite of
 * what it is for. Nothing is persisted; the next session starts listening.
 */
export function mute(on) {
  if (!live) return false;
  const now = live.mute(on === undefined ? !live.muted() : on);
  if (orb) orb.setMuted(now);
  shout({ kind: "mute", muted: now });
  return now;
}

export function muted() {
  return Boolean(live && live.muted());
}

/* ------------------------------------------------------------------ the page */

function turn(page) {
  const n = Math.floor(Number(page) || 0);
  if (n <= 0) return;
  // On the reader, the page turn is the reader's own jump and it pulses the marker. Anywhere
  // else, getting there is a navigation, and chat-ui already owns that path.
  if (screen === "book") {
    shout({ kind: "page", page: n });
    return;
  }
  if (pageSink) pageSink(n);
  else shout({ kind: "page", page: n });
}

function step(dir) {
  if (screen !== "book") return false;
  shout({ kind: "step", dir });
  return true;
}

/**
 * The figure and the page it is printed on, for the chip. Only ever off a line that names a page:
 * this exists to let him check what he heard, and a sentence with no page in it is not a figure.
 */
function chipFor(text) {
  const named = NAMED_PAGE.exec(text);
  if (!named) return "";
  const rest = FIGURE.exec(text);
  const tail = rest ? rest[1].replace(/[.,;:]+$/, "").trim() : "";
  return tail ? `p. ${named[1]} · ${tail}` : `p. ${named[1]}`;
}

/* ------------------------------------------------------------------ the session */

function remember(role, text, part) {
  const last = transcript[transcript.length - 1];
  if (part && last && last.role === "assistant") last.text = `${last.text} ${text}`.trim();
  else transcript.push({ role, text });
  if (transcript.length > KEEP) transcript.splice(0, transcript.length - KEEP);
}

function heard(event) {
  if (event.type === "status") {
    if (event.value === "closed") {
      shut();
      return;
    }
    if (orb) orb.setState(event.value);
    shout({ kind: "status", status: event.value });
    return;
  }

  if (event.type === "text") {
    const text = String(event.text || "").trim();
    if (!text) return;
    remember(event.role, text, event.part);
    if (orb) orb.setLine(text);
    shout({ kind: "text", role: event.role, text, part: Boolean(event.part) });
    if (event.role === "user") {
      // Said to the reader, answered by the reader. No model, no socket, no wait.
      if (NEXT.test(text)) step("next");
      else if (PREV.test(text)) step("prev");
      return;
    }
    const chip = chipFor(text);
    if (chip && orb) orb.chip(chip);
    if (chip) shout({ kind: "spec", chip });
    return;
  }

  if (event.type === "page") {
    turn(event.page);
    return;
  }

  if (event.type === "interrupted") {
    if (orb) orb.setLine("…");
    shout({ kind: "interrupted" });
    return;
  }

  if (event.type === "error") {
    shout({ kind: "error", message: event.message || "Voice failed." });
  }
}

/** Everything the session leaves behind, put back. Safe to call twice. */
function shut() {
  const was = live;
  live = null;
  starting = false;
  userDock = null;
  if (was) {
    try {
      was.stop();
    } catch {
      /* already gone */
    }
  }
  if (orb) {
    orb.setState("closed");
    orb.setLine("");
  }
  shout({ kind: "ended" });
  shout({ kind: "status", status: "closed" });
}

export function stop() {
  if (!live && !starting) return;
  shut();
}

export async function start(next = {}) {
  setContext(next);
  if (!ctx.manualId || isLive()) return isLive();
  wire();
  starting = true;
  ensureOrb();
  orb.setState("connecting");
  applyDock(want());
  shout({ kind: "started" });
  shout({ kind: "status", status: "connecting" });
  try {
    live = await agent.start({ manualId: ctx.manualId, bikeId: ctx.bikeId, on: heard });
    starting = false;
    orb.setState(live.status() || "listening");
    shout({ kind: "status", status: live.status() || "listening" });
    return true;
  } catch (err) {
    starting = false;
    live = null;
    if (orb) orb.setState("closed");
    shout({ kind: "error", message: (err && err.message) || "Voice unavailable." });
    shout({ kind: "ended" });
    return false;
  }
}

export function toggle(next = {}) {
  if (isLive()) {
    stop();
    return false;
  }
  start(next);
  return true;
}

/** Full screen or docked, from outside — the reader's own mic button uses this. */
export function dock(mode) {
  userDock = mode === "compact" ? "compact" : "full";
  applyDock(userDock);
}

/* ------------------------------------------------------------------ the wiring */

function wire() {
  if (wired || typeof window === "undefined") return;
  wired = true;

  // The screen changed under a running session. The session does not care; the orb does.
  busOn("screen", (e) => {
    screen = (e && e.id) || "";
    userDock = null;
    if (isLive()) applyDock(want());
  });

  // The Parts sheet opens over the reader. The orb stays where it is - it is above the sheet and
  // it is still listening - but the thumb row it was clearing may have gone, so re-measure.
  busOn("overlay", () => {
    if (isLive() && orb) orb.el.style.setProperty("--dock-gap", `${dockGap()}px`);
  });

  window.addEventListener("resize", () => {
    if (isLive() && orb) orb.el.style.setProperty("--dock-gap", `${dockGap()}px`);
  });

  // A screen asking for the assistant without importing it.
  window.addEventListener("mechanica:voice-toggle", (e) => {
    const detail = (e && e.detail) || {};
    toggle({
      manualId: detail.manualId ?? ctx.manualId,
      bikeId: detail.bikeId ?? ctx.bikeId ?? busState.bikeId,
      bike: detail.bike ?? ctx.bike,
    });
  });

  // M for mute, while voice is open and he is not typing into something. One key, because the
  // phone is on the bench and the laptop in the corner of the shop is where the second pair of
  // hands is. Never a shortcut when there is no session: M is a letter first.
  window.addEventListener("keydown", (e) => {
    if (!live || e.key !== "m" || e.metaKey || e.ctrlKey || e.altKey) return;
    const at = document.activeElement;
    const tag = at && at.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || (at && at.isContentEditable)) return;
    e.preventDefault();
    mute();
  });

  // A socket nobody is listening to still bills by the minute, and a phone that keeps its
  // microphone open after the page is gone is worse than the money.
  window.addEventListener("pagehide", stop);
  window.addEventListener("offline", stop);
}

if (typeof window !== "undefined") wire();
