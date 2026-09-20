import { go, state, on } from "./bus.js";
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

function firstGo() {
  const hash = location.hash.slice(1) || "identify";
  if (hash !== "identify" && (state.bikeId == null || state.bikeId === "")) {
    go("identify", { replace: true });
    return;
  }
  go(hash, { replace: true });
}

function registerSw() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("sw.js").catch((err) => {
    console.warn("sw register failed", err);
  });
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
  registerSw();
}

boot();
