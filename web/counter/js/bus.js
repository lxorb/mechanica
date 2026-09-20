const listeners = Object.create(null);
const screens = new Map();
const overlays = new Map();
let currentId = null;
let overlayId = null;
let booted = false;

export const state = {
  bikeId: null,
  vin: null,
  photoUrl: null,
  systemId: null,
  partId: null,
  jobId: null,
  page: null,
  channel: null,
  email: "",
  ticket: "",
};

/** Four steps. Parts (invoice) is an overlay on Book, not a step of its own. */
export const FLOW = ["identify", "confirm", "pick", "book"];

export function on(event, handler) {
  if (!listeners[event]) listeners[event] = [];
  listeners[event].push(handler);
}

export function emit(event, payload) {
  const list = listeners[event];
  if (!list) return;
  for (const handler of list.slice()) handler(payload);
}

export function set(patch) {
  if (!patch || typeof patch !== "object") return;
  Object.assign(state, patch);
  emit("state", patch);
}

export function registerScreen(id, api) {
  const existing = screens.get(id);
  if (existing) {
    if (!existing.mounted) {
      existing.mount = api && api.mount;
      existing.enter = api && api.enter;
      existing.leave = api && api.leave;
      existing.back = api && api.back;
    }
  } else {
    screens.set(id, {
      mount: api && api.mount,
      enter: api && api.enter,
      leave: api && api.leave,
      back: api && api.back,
      mounted: false,
    });
  }
  bootFromHash();
}

/* ---------------------------------------------------------------- overlays */

/**
 * An overlay is a sheet over the screen that opened it: its own history entry
 * (#book+invoice), so the header Back, back() and the browser's own Back all close it
 * before they leave the screen underneath. The screen never leaves or re-enters.
 */
export function registerOverlay(id, api) {
  overlays.set(id, {
    mount: api && api.mount,
    open: api && api.open,
    close: api && api.close,
    mounted: false,
  });
}

function overlayNode(id) {
  return document.querySelector(`[data-overlay="${id}"]`);
}

function overlayRoot(id) {
  const node = overlayNode(id);
  if (!node) return null;
  return node.querySelector("[data-root]") || node;
}

function paintOverlay(id, on) {
  const node = overlayNode(id);
  if (!node) return;
  if (on) {
    node.hidden = false;
    requestAnimationFrame(() => node.classList.add("open"));
  } else {
    node.classList.remove("open");
    node.hidden = true;
  }
}

/** Open / close with no history of its own; onPop and openOverlay own the entries. */
function syncOverlay(id) {
  if (id === overlayId) return;
  if (overlayId) {
    const prev = overlays.get(overlayId);
    paintOverlay(overlayId, false);
    if (prev && typeof prev.close === "function") prev.close();
    emit("overlay", { id: overlayId, on: false });
    overlayId = null;
  }
  if (!id) return;
  const rec = overlays.get(id);
  if (!rec) return;
  overlayId = id;
  if (!rec.mounted) {
    if (typeof rec.mount === "function") rec.mount(overlayRoot(id));
    rec.mounted = true;
  }
  paintOverlay(id, true);
  if (typeof rec.open === "function") rec.open();
  emit("overlay", { id, on: true });
}

export function openOverlay(id) {
  if (!overlays.has(id) || overlayId === id) return;
  syncOverlay(id);
  history.pushState({ screen: currentId, overlay: id }, "", `#${currentId || "identify"}+${id}`);
}

export function closeOverlay() {
  if (!overlayId) return false;
  history.back();
  return true;
}

export function overlayOpen() {
  return overlayId;
}

/**
 * One step back. An open overlay goes first, then a screen with an open sub-state
 * (Identify's VIN / photo / query, Book's immersive mode) pops that by returning true from
 * its own back(); everything else is the browser's own history step, so the header button
 * and the hardware Back button agree.
 */
export function back() {
  if (overlayId) {
    history.back();
    return;
  }
  const rec = currentId && screens.get(currentId);
  if (rec && typeof rec.back === "function" && rec.back() === true) return;
  history.back();
}

function allowed(id) {
  if (!FLOW.includes(id)) return false;
  if (id === "identify") return true;
  return state.bikeId != null && state.bikeId !== "";
}

function onlyReplace(params) {
  if (!params || typeof params !== "object") return false;
  const keys = Object.keys(params);
  return keys.length === 1 && keys[0] === "replace" && params.replace === true;
}

/**
 * The URL of a screen, carrying the overlay that is open over it. Writing a bare "#book"
 * while the Parts sheet is up threw that sheet's own history entry away: the browser's Back
 * then landed on an entry that no longer said "+invoice", so one press closed nothing and
 * the next did nothing at all.
 */
function hashFor(id) {
  return overlayId ? `#${id}+${overlayId}` : `#${id}`;
}

function histFor(id) {
  return overlayId ? { screen: id, overlay: overlayId } : { screen: id };
}

function showSection(id) {
  document.querySelectorAll("section[data-screen]").forEach((section) => {
    section.hidden = section.getAttribute("data-screen") !== id;
  });
}

function updateRail(id) {
  const here = FLOW.indexOf(id);
  document.querySelectorAll("li[data-step]").forEach((li) => {
    const i = FLOW.indexOf(li.getAttribute("data-step"));
    if (i < 0) return;
    const now = i === here;
    li.classList.toggle("now", now);
    li.classList.toggle("done", i < here);
    if (now) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  });
}

function rootFor(id) {
  const section = document.querySelector(`section[data-screen="${id}"]`);
  if (!section) return null;
  return section.querySelector("[data-root], .root") || section;
}

export function go(id, params) {
  if (!FLOW.includes(id)) return;

  let next = params;
  if (currentId == null && !allowed(id)) {
    id = "identify";
    next = Object.assign({}, params, { replace: true });
  }

  if (id === currentId && !(next && next.replace)) return;

  if (id === currentId && onlyReplace(next)) {
    history.replaceState(histFor(id), "", hashFor(id));
    return;
  }

  if (overlayId) syncOverlay(null);

  showSection(id);
  updateRail(id);

  if (currentId && currentId !== id) {
    const prev = screens.get(currentId);
    if (prev && typeof prev.leave === "function") prev.leave();
  }

  const rec = screens.get(id);
  if (rec) {
    if (!rec.mounted) {
      if (typeof rec.mount === "function") rec.mount(rootFor(id));
      rec.mounted = true;
    }
    if (typeof rec.enter === "function") rec.enter(next);
  }

  currentId = id;

  const hist = histFor(id);
  const url = hashFor(id);
  if (next && next.replace) history.replaceState(hist, "", url);
  else history.pushState(hist, "", url);

  emit("screen", { id });
}

/** "#book+invoice" -> screen "book", overlay "invoice". */
export function splitHash(raw) {
  const value = String(raw || "").replace(/^#/, "");
  const cut = value.indexOf("+");
  if (cut < 0) return { screen: value, overlay: "" };
  return { screen: value.slice(0, cut), overlay: value.slice(cut + 1) };
}

/**
 * The hash the page was opened with, captured before anything rewrites it. bus.js is the
 * first module in the graph, so this is the URL the user actually typed or shared — a
 * non-step hash (#cost) is rewritten to #identify by the time the module that owns it runs,
 * which is why that module needs this instead of reading location.hash for itself.
 */
export const bootHash =
  typeof location !== "undefined" ? splitHash(location.hash).screen : "";

const initialHash = bootHash;

function bootFromHash() {
  if (booted || !initialHash) return;
  if (typeof document !== "undefined" && document.readyState === "loading") return;
  const id = allowed(initialHash) ? initialHash : "identify";
  if (!screens.has(id)) return;
  booted = true;
  go(id, { replace: true });
}

function onPop(event) {
  const { screen: hash, overlay } = splitHash(location.hash);
  const fromState = event.state && event.state.screen;
  const id = hash || fromState;
  if (!id) {
    // An entry with neither a hash nor a screen: land on Identify rather than hiding every
    // section, which used to leave a ground-coloured blank page with nothing to tap.
    syncOverlay(null);
    go("identify", { replace: true });
    return;
  }
  syncOverlay(overlays.has(overlay) ? overlay : null);
  // A hash that is not a step (#cost) belongs to something else: the screen underneath
  // keeps its place instead of being thrown back to Identify.
  if (!FLOW.includes(id)) {
    if (!currentId) go("identify", { replace: true });
    return;
  }
  go(id, { replace: true });
}

function onKey(e) {
  if (e.key !== "Escape" || !overlayId) return;
  e.preventDefault();
  closeOverlay();
}

if (typeof window !== "undefined") {
  window.HandyBus = { state, go, back, openOverlay, closeOverlay };
  window.addEventListener("popstate", onPop);
  window.addEventListener("keydown", onKey);
  document.addEventListener("click", (e) => {
    const hit = e.target.closest && e.target.closest("[data-ov-close]");
    if (hit) closeOverlay();
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFromHash, { once: true });
  }
}
