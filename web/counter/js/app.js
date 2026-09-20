import { go, state, on, back } from "./bus.js";
import * as Q from "./ttm.js";

/**
 * The store is picked inside ttm.js: loadCatalog() probes ${apiBase()}/health with a
 * 2.5 s timeout and either runs against our FastAPI or delegates to query.js with the
 * bundled roster merged on top. Screens import "../ttm.js" directly; window.Q is here
 * for the console and for the screens that were written against a global.
 */
const SCREENS = ["identify", "confirm", "pick", "book", "follow", "invoice"];

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
    paintBack();
  });
  on("substate", (e) => {
    if (!e || e.screen !== here) return;
    sub = Boolean(e.on);
    paintBack();
  });
  paintBack();
}

function firstGo() {
  const hash = location.hash.slice(1) || "identify";
  if (hash !== "identify" && (state.bikeId == null || state.bikeId === "")) {
    go("identify", { replace: true });
    return;
  }
  go(hash, { replace: true });
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
  navigator.serviceWorker.register("sw.js").catch((err) => {
    console.warn("sw register failed", err);
  });
  if (controlled) return;
  navigator.serviceWorker.addEventListener(
    "controllerchange",
    () => {
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
  });

  window.Q = await pickStore();

  for (const id of SCREENS) {
    try {
      await import(`./screens/${id}.js`);
    } catch (err) {
      console.warn(`screen module missing: ${id}`, err);
    }
  }

  firstGo();
}

boot();
