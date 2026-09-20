import { go, state, on } from "./bus.js";
import { loadCatalog } from "./query.js";

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

async function boot() {
  paintTicket();
  on("state", (patch) => {
    if (patch && Object.prototype.hasOwnProperty.call(patch, "ticket")) paintTicket();
  });

  try {
    await loadCatalog();
  } catch (err) {
    console.warn("catalog load failed", err);
  }

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
