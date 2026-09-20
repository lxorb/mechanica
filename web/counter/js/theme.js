/**
 * Themes. Owner: theme agent. Pairs with css/themes.css and the token floor in css/counter.css.
 *
 * A theme is a list of colours and nothing else: this module only ever writes `data-theme` on
 * <html>, so every rule in the app keeps working and no screen has to know a theme exists.
 *
 *   window.mechanicaTheme.list        [{ id, label, swatch: [ground, accent] }, ...] in cycle order
 *   window.mechanicaTheme.current()   the id on <html> right now
 *   window.mechanicaTheme.set(id)     apply and remember it
 *   window.mechanicaTheme.next()      the id one step along the cycle
 *
 * Every change dispatches `mechanica:theme` on window with { id, previous, tokens }, so a module
 * that cannot read CSS — js/viewer3d.js, which paints the exploded-view grid in WebGL — can pick
 * its colours up from `tokens` (or from getComputedStyle) instead of hard-coding them.
 *
 * The saved id is applied before first paint by the inline script in index.html, not by this
 * module: a module is deferred, so waiting for it would show one frame of Workshop to a user who
 * chose Night. This file re-applies the same id (cheap, idempotent) and owns everything after.
 */

const KEY = "mechanica.theme";
const ATTR = "data-theme";
const SWAP = "data-swapping";

/**
 * Cycle order, and the two colours each theme shows on the switch. The swatch is the theme's
 * ground and its accent, which is the smallest honest preview of what a tap will do.
 */
export const THEMES = [
  { id: "workshop", label: "Workshop", swatch: ["#ece7dc", "#e85d04"], color: "#e85d04" },
  { id: "night", label: "Night", swatch: ["#15181a", "#ff7a1f"], color: "#ff7a1f" },
  { id: "blueprint", label: "Blueprint", swatch: ["#0e2742", "#3fd0f7"], color: "#3fd0f7" },
  { id: "track", label: "Track", swatch: ["#111111", "#ffd100"], color: "#ffd100" },
  { id: "paper", label: "Paper", swatch: ["#ffffff", "#cc0000"], color: "#cc0000" },
];

const DEFAULT = THEMES[0].id;
const ids = THEMES.map((t) => t.id);
const has = (id) => ids.includes(id);

/** Storage throws in private mode and in some embedded webviews; a theme is never worth a crash. */
function remember(id) {
  try { localStorage.setItem(KEY, id); } catch { /* nothing to do about it */ }
}

function remembered() {
  try {
    const id = localStorage.getItem(KEY);
    return has(id) ? id : null;
  } catch {
    return null;
  }
}

/**
 * First visit only. A dark system means a dark room, so Night is the better guess than the
 * default — but the moment the user taps the switch their choice is stored and this never runs
 * again, in either direction. The switch is the preference; the OS is only the opening bid.
 */
function firstGuess() {
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return dark ? "night" : DEFAULT;
}

export function current() {
  const id = document.documentElement.getAttribute(ATTR);
  return has(id) ? id : DEFAULT;
}

export function next(from) {
  const i = ids.indexOf(has(from) ? from : current());
  return ids[(i + 1) % ids.length];
}

/** The tokens a non-CSS consumer needs. Read live, so it is whatever themes.css actually says. */
export function tokens() {
  const css = getComputedStyle(document.documentElement);
  const read = (name) => css.getPropertyValue(name).trim();
  return {
    bg: read("--bg"),
    fg: read("--fg"),
    accent: read("--accent"),
    card: read("--card"),
    line: read("--line"),
    grid: read("--grid"),
    gridBg: read("--grid-bg"),
  };
}

/** The <meta> the OS paints the status bar and the task switcher with. */
function paintMeta(id) {
  const meta = document.querySelector('meta[name="theme-color"]');
  const theme = THEMES.find((t) => t.id === id);
  if (meta && theme) meta.setAttribute("content", theme.color);
}

/** The disc is a preview of what one more tap does, so it always wears the NEXT theme. */
function paintButton(id) {
  const button = document.querySelector("[data-theme-button]");
  if (!button) return;
  const after = THEMES.find((t) => t.id === next(id));
  if (!after) return;
  const disc = button.querySelector("i") || button;
  disc.style.setProperty("--swatch-a", after.swatch[0]);
  disc.style.setProperty("--swatch-b", after.swatch[1]);
  button.setAttribute("aria-label", after.label);
  button.title = after.label;
}

let swapTimer = 0;

/**
 * [data-swapping] exists only while the crossfade runs — see the note in css/counter.css. It is
 * skipped entirely on the first application (nothing to fade from) and under reduced motion.
 */
function crossfade() {
  const root = document.documentElement;
  const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (still) return;
  const ms = parseInt(getComputedStyle(root).getPropertyValue("--theme-swap"), 10) || 180;
  root.setAttribute(SWAP, "");
  clearTimeout(swapTimer);
  swapTimer = setTimeout(() => root.removeAttribute(SWAP), ms + 40);
}

/**
 * Re-applying the theme that is already on is not a no-op: the pre-paint script in index.html
 * sets the attribute but knows nothing about the disc or the event, so arm() calls set() with
 * the id already in place to finish the job. Only the crossfade is skipped when nothing moves.
 */
export function set(id, { fade = true, store = true } = {}) {
  const wanted = has(id) ? id : DEFAULT;
  const previous = current();
  if (fade && wanted !== previous) crossfade();
  document.documentElement.setAttribute(ATTR, wanted);
  if (store) remember(wanted);
  paintMeta(wanted);
  paintButton(wanted);
  window.dispatchEvent(new CustomEvent("mechanica:theme", {
    detail: { id: wanted, previous, tokens: tokens() },
  }));
  return wanted;
}

export function cycle() {
  return set(next());
}

function arm() {
  const button = document.querySelector("[data-theme-button]");
  if (button && !button.dataset.armed) {
    button.dataset.armed = "1";
    button.addEventListener("click", () => cycle());
  }
  // The pre-paint script in index.html already chose; this only fills in the parts it cannot
  // reach (the meta tag, the disc) and publishes the first event.
  set(document.documentElement.getAttribute(ATTR) || remembered() || firstGuess(), { fade: false });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arm, { once: true });
else arm();

window.mechanicaTheme = { list: THEMES, current, set, next, cycle, tokens };

export default window.mechanicaTheme;
