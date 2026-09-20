/**
 * Hidden meter. Reachable at #cost only; the flow rail never links it.
 * It is an overlay, not a flow screen, so bus.js keeps owning the six steps.
 */

import { state, go, on } from "../bus.js";
import { cost } from "../ttm.js";

const CELLS = ["total", "per ask", "naive per ask", "calls"];

let veil = null;
let cells = null;
let armed = false;
let lastScreen = null;
let prevScreen = null;
let costBack = null;
let gen = 0;

const wanted = readHash() === "cost";

function readHash() {
  if (typeof location === "undefined") return "";
  return location.hash.replace(/^#/, "");
}

function usd(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return v >= 100 ? v.toFixed(2) : v.toFixed(4);
}

function styles() {
  const href = new URL("../../css/screens/cost.css", import.meta.url).href;
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.append(link);
}

function h(tag, attrs) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, val] of Object.entries(attrs)) {
      if (val == null || val === false) continue;
      if (key === "class") node.className = val;
      else if (key === "text") node.textContent = val;
      else node.setAttribute(key, val === true ? "" : String(val));
    }
  }
  return node;
}

function build() {
  styles();
  veil = h("div", { class: "cost-veil", hidden: "" });
  const bar = h("div", { class: "cost-bar" });
  const back = h("button", { type: "button", class: "btn btn-icon cost-back", "aria-label": "Back", text: "←" });
  back.addEventListener("click", leave);
  bar.append(back);
  const grid = h("div", { class: "cost-grid" });
  cells = CELLS.map((label) => {
    const box = h("div", { class: "card cost-cell" });
    const value = h("b", { class: "cost-n", text: "—" });
    box.append(value, h("span", { class: "cost-lab", text: label }));
    grid.append(box);
    return value;
  });
  veil.append(bar, grid);
  document.body.append(veil);
}

function load() {
  const token = ++gen;
  Promise.resolve()
    .then(() => cost())
    .then((sum) => {
      if (token !== gen || !sum || !cells) return;
      const asks = Number(sum.asks) || 0;
      const total = Number(sum.total) || 0;
      const values = [
        usd(total),
        usd(asks > 0 ? total / asks : 0),
        usd(sum.naivePerAsk),
        String(sum.count == null ? "—" : sum.count),
      ];
      values.forEach((v, i) => {
        cells[i].textContent = v;
      });
    })
    .catch(() => {});
}

function open() {
  if (!veil) build();
  if (!veil.hidden) {
    load();
    return;
  }
  veil.hidden = false;
  const back = costBack || lastScreen;
  if (back && back !== lastScreen && state.bikeId) {
    try {
      go(back, { replace: true });
    } catch {
      /* the flow keeps itself */
    }
  }
  try {
    history.replaceState({ screen: lastScreen || "identify" }, "", "#cost");
  } catch {
    /* no history */
  }
  load();
}

function close() {
  gen += 1;
  if (veil) veil.hidden = true;
}

function leave() {
  if (!veil || veil.hidden) return;
  const id = lastScreen || "identify";
  history.back();
  window.setTimeout(() => {
    if (!veil || veil.hidden) return;
    close();
    try {
      history.replaceState({ screen: id }, "", "#" + id);
    } catch {
      /* no history */
    }
  }, 160);
}

function route(id) {
  if (id === "cost") open();
  else close();
}

function onHash(e) {
  let hash = "";
  try {
    hash = e && e.newURL ? new URL(e.newURL).hash : location.hash;
  } catch {
    hash = location.hash;
  }
  route(hash.replace(/^#/, ""));
}

function onPop() {
  costBack = readHash() === "cost" ? lastScreen : prevScreen;
  if (readHash() === "cost") route("cost");
}

export function initCost() {
  if (armed || typeof window === "undefined") return;
  armed = true;
  on("screen", (e) => {
    const id = e && e.id;
    if (!id || id === lastScreen) return;
    prevScreen = lastScreen;
    lastScreen = id;
    if (wanted && !veil) {
      costBack = id;
      open();
    }
  });
  window.addEventListener("hashchange", onHash);
  window.addEventListener("popstate", onPop);
}
