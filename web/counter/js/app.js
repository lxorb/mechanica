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

async function boot() {
  paintTicket();
  armBack();
  registerSw();
  on("state", (patch) => {
    if (patch && Object.prototype.hasOwnProperty.call(patch, "ticket")) paintTicket();
    stash();
  });

  window.Q = await pickStore();
  revive();

  for (const id of [...SCREENS, ...OVERLAYS]) {
    try {
      await import(`./screens/${id}.js`);
    } catch (err) {
      console.warn(`screen module missing: ${id}`, err);
    }
  }

  firstGo();
}

boot();
