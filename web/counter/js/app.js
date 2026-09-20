import { go, state, set, on, back, splitHash } from "./bus.js";
import * as Q from "./ttm.js";

/**
 * The store is picked inside ttm.js: loadCatalog() probes ${apiBase()}/health with a
 * 2.5 s timeout and either runs against our FastAPI or delegates to query.js with the
 * bundled roster merged on top. Screens import "../ttm.js" directly; window.Q is here
 * for the console and for the screens that were written against a global.
 */
const SCREENS = ["identify", "confirm", "pick", "book"];

/** Not steps: Parts is an overlay on Book, the meter is reachable at #cost only. */
const OVERLAYS = ["invoice"];

function paintTicket() {
  const el = document.querySelector("[data-ticket]");
  if (el) el.textContent = state.ticket;
}

/* Header back: every screen past Identify, plus Identify once a sub-state is open. */
let here = "identify";
let sub = false;

function paintBack() {
  const el = document.querySelector("[data-back]");
  if (el) el.classList.toggle("is-off", here === "identify" && !sub);
}

function armBack() {
  const el = document.querySelector("[data-back]");
  if (el) el.addEventListener("click", back);
  on("screen", (e) => {
    if (!e || !e.id) return;
    here = e.id;
    sub = false;
    // Book runs fullscreen: counter.css folds the ticket bar and the rail away for it.
    document.body.setAttribute("data-here", here);
    paintBack();
    stash();
  });
  on("substate", (e) => {
    if (!e || e.screen !== here) return;
    sub = Boolean(e.on);
    paintBack();
  });
  document.body.setAttribute("data-here", here);
  paintBack();
}

/**
 * Where the mechanic was, across a reload.
 *
 * The store survives one: the worker has the shell, the roster, /health, every manual that was
 * opened and the PDF behind it. The bus does not — `state` is in memory only — so a reload on
 * #pick or #book found state.bikeId empty, firstGo() bounced to Identify, and offline (where
 * there is no way to search the bike again) that was the end of the job. These few ids are
 * therefore written on every state change and read back before the first route.
 *
 * sessionStorage, not localStorage: this is "where was I a second ago", not a preference. A
 * counter phone handed to the next mechanic opens on Identify, as it should.
 *
 * photoUrl is deliberately not kept — it is an object URL, and it is dead the moment the page is.
 */
const KEEP = ["bikeId", "vin", "manualId", "systemId", "partId", "jobId", "jobIds", "page", "ticket", "email"];
const SPOT = "ttm.spot";

function stash() {
  try {
    const spot = { screen: here };
    for (const key of KEEP) {
      const value = state[key];
      if (value != null && value !== "") spot[key] = value;
    }
    sessionStorage.setItem(SPOT, JSON.stringify(spot));
  } catch {
    /* private mode, or a browser with site data off: the app just forgets, as it did before */
  }
}

function stashed() {
  try {
    const spot = JSON.parse(sessionStorage.getItem(SPOT) || "null");
    return spot && typeof spot === "object" ? spot : null;
  } catch {
    return null;
  }
}

/**
 * Only a bike the roster can still resolve is restored — offline the roster is the bundled one, and
 * a bikeId it does not carry would put a screen in front of a vehicle it cannot name.
 *
 * This has to run before the screen modules are imported, not in firstGo(): bus.js routes from the
 * hash the moment the first screen registers itself, and with state.bikeId still empty that route
 * rewrites #book to #identify — after which firstGo() has nothing left to read.
 */
function revive() {
  const hash = splitHash(location.hash).screen || "identify";
  if (hash === "identify" || !SCREENS.includes(hash)) return false;
  if (state.bikeId != null && state.bikeId !== "") return false;
  const spot = stashed();
  if (!spot || !spot.bikeId || !Q.bike(spot.bikeId)) return false;
  const patch = {};
  for (const key of KEEP) if (spot[key] != null) patch[key] = spot[key];
  set(patch);
  return true;
}

function firstGo() {
  const hash = splitHash(location.hash).screen || "identify";
  const id = SCREENS.includes(hash) ? hash : "identify";
  if (id !== "identify" && (state.bikeId == null || state.bikeId === "")) {
    go("identify", { replace: true });
    return;
  }
  go(id, { replace: true });
  stash();
}

/**
 * First visit: the worker only starts controlling this page part-way through boot, so the
 * /health answer that keeps ttm.js in REMOTE mode never reaches its cache and a later
 * offline reload would fall back to the bundled-only store. One 31-byte re-probe once the
 * worker has claimed the page fixes that, and costs nothing on every later visit.
 *
 * Registration waits for the page to finish loading. Installing a worker means it precaches,
 * and on a cold first load those fetches raced the ones the search field was waiting for —
 * the roster went down the same wire twice. The worker is for the *second* visit, so it is
 * started once the first one is standing.
 */
function registerSw() {
  if (!("serviceWorker" in navigator)) return;
  const controlled = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.register("sw.js", { updateViaCache: "none" }).catch((err) => {
    console.warn("sw register failed", err);
  });
  navigator.serviceWorker.addEventListener(
    "controllerchange",
    () => {
      // A page that was already controlled has just been claimed by a newly deployed worker:
      // its old caches are gone, so load the new shell once. A first visit only re-probes.
      if (controlled) {
        location.reload();
        return;
      }
      fetch(`${Q.apiBase()}/health`, { headers: { Accept: "application/json" } }).catch(() => {});
    },
    { once: true }
  );
}

/**
 * Everything the second visit needs and the first one does not: the other screens, the
 * deep-chat bundle, the worker's own copy of the roster. The worker only takes them when the
 * page says it is done loading, so an offline reload still finds them and a cold load never
 * waits behind them. Sent once; the worker ignores a repeat.
 */
function fillCaches() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.ready
    .then((reg) => {
      const worker = reg.active || navigator.serviceWorker.controller;
      if (worker) worker.postMessage({ type: "precache-rest" });
    })
    .catch(() => {});
}

/** requestIdleCallback with a deadline, so a busy main thread cannot postpone this forever. */
function idle(fn, timeout = 2000) {
  if (typeof requestIdleCallback === "function") requestIdleCallback(fn, { timeout });
  else setTimeout(fn, Math.min(timeout, 250));
}

function measure(name, from) {
  try {
    performance.measure?.(`ttm:${name}`, from);
  } catch {
    /* the mark buffer was cleared: a missing timing is not worth a throw on the boot path */
  }
}

async function pickStore() {
  const started = performance.now();
  try {
    await Q.loadCatalog();
  } catch (err) {
    console.warn("catalog load failed", err);
  }
  const ms = Math.round(performance.now() - started);
  console.info(`store: ${Q.storeMode()} (${Q.apiBase()}), ${Q.bikes().length} bikes in ${ms}ms`);
  document.documentElement.dataset.store = Q.storeMode() ?? "local";
  return Q;
}

/* --------------------------------------------------------- screen modules */

const loading = new Map();

function loadScreen(id) {
  let hit = loading.get(id);
  if (!hit) {
    hit = import(`./screens/${id}.js`).catch((err) => {
      loading.delete(id); // a dropped connection must not make the screen permanently missing
      console.warn(`screen module missing: ${id}`, err);
    });
    loading.set(id, hit);
  }
  return hit;
}

let restStarted = false;

/**
 * Identify is the only screen the landing needs, and the other four bring the 3D viewer, the
 * chat bundle, the PDF reader and the parts sheet with them — 90 KB gzipped of JavaScript that
 * used to be fetched, parsed and compiled one module at a time *before* the search field
 * existed. They come in as soon as the roster is there (the earliest a mechanic can tap a
 * card), or on the first touch, whichever happens first.
 */
function loadRest() {
  if (restStarted) return Promise.resolve();
  restStarted = true;
  performance.mark?.("ttm:rest:a");
  const rest = [...SCREENS.filter((id) => id !== "identify"), ...OVERLAYS].map(loadScreen);
  return Promise.all(rest).then(() => {
    measure("rest", "ttm:rest:a");
    heal();
  });
}

/**
 * A screen whose module arrived after the route had already asked for it: go() showed the
 * section, found nothing registered and left it empty. If that is where we are standing once
 * the modules are in, route to it again and let bus.js mount it. In the normal case — the
 * screen is painted, or we never left Identify — this is one DOM query.
 */
function heal() {
  const section = document.querySelector(`section[data-screen="${here}"]`);
  const root = section && (section.querySelector("[data-root]") || section);
  if (!root || root.childNodes.length) return;
  go(here, { replace: true });
}

async function boot() {
  paintTicket();
  armBack();
  on("state", (patch) => {
    if (patch && Object.prototype.hasOwnProperty.call(patch, "ticket")) paintTicket();
    stash();
  });

  // window.Q is the same module namespace object `import * as Q` hands every screen, so it can
  // be published before the store has picked its backing.
  window.Q = Q;

  const hash = splitHash(location.hash).screen || "identify";
  const deep = SCREENS.includes(hash) && hash !== "identify";

  // A touch or a keystroke is a promise to navigate: bring the other screens in now.
  addEventListener("pointerdown", () => loadRest(), { once: true, passive: true, capture: true });
  addEventListener("keydown", () => loadRest(), { once: true, capture: true });

  const store = pickStore().then(() => {
    revive();
    idle(() => loadRest(), 1200);
    idle(fillCaches, 4000);
  });

  if (deep) {
    // A reload on #pick or #book: revive() has to run before any screen registers itself, or
    // bus.js routes off the hash with an empty state and rewrites it to #identify. That path
    // therefore keeps the old order — store first, then screens.
    await store;
    await Promise.all([loadScreen("identify"), loadScreen(hash)]);
    firstGo();
    Q.uiUp();
    loadRest();
    return;
  }

  performance.mark?.("ttm:identify:a");
  await loadScreen("identify");
  measure("identify", "ttm:identify:a");
  // The field is on screen from here. The roster fills it in when it lands: ttm.js fires
  // "ttm:catalog", which Identify already listens for.
  //
  // uiUp() releases the two heavy passes the store holds back until there is a screen to hold
  // them back for. On a warm load the roster is in hand before this module has even finished
  // evaluating, and the search index was being built in front of it: 12 s of blocked thread
  // between the first paint and the search field.
  firstGo();
  Q.uiUp();
  await store;
}

// The worker is not part of the first paint: register it once the page has finished loading.
if (document.readyState === "complete") idle(registerSw, 3000);
else addEventListener("load", () => idle(registerSw, 3000), { once: true });

boot();
