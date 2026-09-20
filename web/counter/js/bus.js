const listeners = Object.create(null);
const screens = new Map();
let currentId = null;
let booted = false;

export const state = {
  bikeId: null,
  photoUrl: null,
  systemId: null,
  partId: null,
  jobId: null,
  page: null,
  channel: null,
  email: "",
  ticket: "A-17",
};

export const FLOW = ["identify", "confirm", "pick", "book", "follow", "invoice"];

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
    }
  } else {
    screens.set(id, {
      mount: api && api.mount,
      enter: api && api.enter,
      leave: api && api.leave,
      mounted: false,
    });
  }
  bootFromHash();
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
    history.replaceState({ screen: id }, "", "#" + id);
    return;
  }

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

  const hist = { screen: id };
  const url = "#" + id;
  if (next && next.replace) history.replaceState(hist, "", url);
  else history.pushState(hist, "", url);

  emit("screen", { id });
}

const initialHash =
  typeof location !== "undefined" ? location.hash.replace(/^#/, "") : "";

function bootFromHash() {
  if (booted || !initialHash) return;
  if (typeof document !== "undefined" && document.readyState === "loading") return;
  const id = allowed(initialHash) ? initialHash : "identify";
  if (!screens.has(id)) return;
  booted = true;
  go(id, { replace: true });
}

function onPop(event) {
  const hash = location.hash.replace(/^#/, "");
  const fromState = event.state && event.state.screen;
  const id = hash || fromState;
  if (!id) {
    if (currentId) {
      const prev = screens.get(currentId);
      if (prev && typeof prev.leave === "function") prev.leave();
    }
    showSection(null);
    updateRail(null);
    currentId = null;
    return;
  }
  go(FLOW.includes(id) ? id : "identify", { replace: true });
}

if (typeof window !== "undefined") {
  window.HandyBus = { state, go };
  window.addEventListener("popstate", onPop);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFromHash, { once: true });
  }
}
