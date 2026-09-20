import { state, set, go, emit, registerScreen } from "../bus.js";
import * as T from "../ttm.js";
import * as speech from "../speech.js";
import * as deepgram from "../deepgram.js";
import { initCost } from "./cost.js";

const MIC_PATH_BODY = "M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z";
const MIC_PATH_ARC = "M5 11a7 7 0 0 0 14 0M12 18v3";
const CAM_PATH =
  "M8 5h2l1-2h2l1 2h4v13H4V5h4zm4 3.25A3.75 3.75 0 1 0 12 15.75 3.75 3.75 0 0 0 12 8.25zm0 2A1.75 1.75 0 1 1 12 13.75 1.75 1.75 0 0 1 12 10.25z";
const MISS_MS = 900;

let root;
let els;
let chapters = [];
let jobsBy = new Map();
let gen = 0;
let askGen = 0;
let busy = false;
let listening = false;
let stt = speech;
let voiceGen = 0;
let missTimer = 0;
let savedY = 0;
let freezeY = false;
let lastBikeId = null;

initCost();

registerScreen("pick", { mount, enter, leave });

function node(tag, attrs) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  return el;
}

function glyph(paths, stroke) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    if (stroke) {
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "2.2");
      path.setAttribute("stroke-linecap", "round");
    } else {
      path.setAttribute("fill", "currentColor");
    }
    svg.append(path);
  }
  return svg;
}

function mount(el) {
  root = el;
  root.replaceChildren();
  window.addEventListener("scroll", snapshotY, { passive: true });

  const strip = node("div", { class: "strip sheet" });
  const who = node("button", { type: "button", class: "who" });
  const whoImg = node("img", { loading: "lazy", decoding: "async", alt: "", width: "44", height: "44" });
  const whoName = node("span", { class: "who-name" });
  who.append(whoImg, whoName);
  who.addEventListener("click", () => {
    snapshotY();
    go("confirm");
  });
  strip.append(who);

  const systems = node("div", { class: "bins systems", role: "list" });
  const jobs = node("div", { class: "jobs", role: "list" });

  const bar = node("div", { class: "askbar sheet" });
  const meter = node("div", { class: "meter", hidden: "" });
  const meterFill = node("i");
  meter.append(meterFill);

  const form = node("form", { class: "ask" });
  const mic = node("button", { type: "button", class: "btn btn-icon mic", "aria-label": "Speak", "aria-pressed": "false" });
  mic.append(glyph([MIC_PATH_BODY, MIC_PATH_ARC], true));
  mic.addEventListener("click", toggleMic);

  const cam = node("button", { type: "button", class: "btn btn-icon cam", "aria-label": "Photo part" });
  cam.append(glyph([CAM_PATH], false));
  cam.addEventListener("click", () => {
    if (busy) return;
    els.file.click();
  });

  const input = node("input", {
    type: "text",
    class: "ask-q",
    enterkeyhint: "go",
    autocomplete: "off",
    autocorrect: "off",
    spellcheck: "false",
    "aria-label": "Ask",
  });
  input.addEventListener("input", syncSend);

  const send = node("button", { type: "submit", class: "btn btn-primary send", "aria-label": "Ask", text: "↑" });
  form.append(mic, cam, input, send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit(input.value);
  });

  const file = node("input", {
    type: "file",
    accept: "image/*",
    capture: "environment",
    hidden: "",
    tabindex: "-1",
    "aria-hidden": "true",
  });
  file.addEventListener("change", onFile);

  bar.append(meter, form, file);
  root.append(strip, systems, jobs, bar);

  els = { who, whoImg, whoName, systems, jobs, bar, meter, meterFill, form, mic, cam, input, send, file };
  els.mic.hidden = !stt.supported;
  syncSend();
}

function bounce() {
  queueMicrotask(() => go("identify", { replace: true }));
}

function enter() {
  if (!state.bikeId) {
    bounce();
    return;
  }
  freezeY = true;
  if (state.bikeId !== lastBikeId) {
    savedY = 0;
    jobsBy = new Map();
    chapters = [];
    lastBikeId = state.bikeId;
    if (els) {
      els.systems.replaceChildren();
      els.jobs.replaceChildren();
      els.input.value = "";
      syncSend();
    }
  }
  load().catch(() => {});
  restoreScroll();
}

function leave() {
  freezeY = false;
  snapshotY();
  stopMic();
  clearMiss();
  askGen += 1;
  busy = false;
  setBusy(false);
}

function snapshotY() {
  if (freezeY || !root) return;
  const section = root.closest("[data-screen]");
  if (section && !section.hidden) savedY = window.scrollY;
}

function restoreScroll() {
  const y = savedY;
  freezeY = true;
  window.scrollTo(0, y);
  requestAnimationFrame(() => {
    window.scrollTo(0, y);
    freezeY = false;
  });
}

async function load() {
  const token = ++gen;
  let rec = T.bike(state.bikeId);
  if (!rec) {
    try {
      await T.loadCatalog();
    } catch {
      /* offline catalog */
    }
    rec = T.bike(state.bikeId);
  }
  if (token !== gen) return;
  if (!rec) {
    bounce();
    return;
  }
  paintBike(rec);

  let list = [];
  try {
    list = (await T.systems(state.bikeId)) || [];
  } catch {
    list = [];
  }
  if (token !== gen) return;
  chapters = list;

  const found = await Promise.all(
    list.map((sys) =>
      Promise.resolve()
        .then(() => T.jobsFor(state.bikeId, sys.id))
        .then((rows) => (Array.isArray(rows) ? rows : []))
        .catch(() => [])
    )
  );
  if (token !== gen) return;
  jobsBy = new Map();
  list.forEach((sys, i) => jobsBy.set(sys.id, found[i]));

  if (!list.some((sys) => sys.id === state.systemId)) {
    set({ systemId: list.length ? list[0].id : null });
  }

  paintChapters();
  paintJobs();
  primeVoice();
}

function paintBike(rec) {
  const label = [rec.make, rec.model, rec.year].filter((x) => x != null && x !== "").join(" ");
  const src = T.asset(rec.thumb || rec.image || "");
  if (src) {
    els.whoImg.src = src;
    els.whoImg.alt = `${rec.make} ${rec.model}`;
    els.whoImg.hidden = false;
  } else {
    els.whoImg.removeAttribute("src");
    els.whoImg.hidden = true;
  }
  els.whoName.textContent = label;
  els.who.setAttribute("aria-label", label);
}

function pageOf(job) {
  if (!job) return null;
  if (Array.isArray(job.pages) && job.pages.length && job.pages[0] != null) return job.pages[0];
  if (job.pageStart != null) return job.pageStart;
  return null;
}

function firstPage(rows) {
  let best = null;
  for (const job of rows || []) {
    const n = pageOf(job);
    if (n == null) continue;
    if (best == null || n < best) best = n;
  }
  return best;
}

function stampPage(n) {
  return n == null ? "" : `p. ${n}`;
}

function paintChapters() {
  els.systems.replaceChildren();
  for (const sys of chapters) {
    const rows = jobsBy.get(sys.id) || [];
    const count = sys.count != null ? sys.count : rows.length;
    const on = sys.id === state.systemId;
    const name = sys.name || sys.id;
    const btn = node("button", {
      type: "button",
      class: on ? "tile chap is-on" : "tile chap",
      "data-id": sys.id,
      role: "listitem",
      "aria-pressed": on ? "true" : "false",
      "aria-label": `${name}, ${count}`,
    });
    const page = firstPage(rows);
    const big = node("span", { class: "chap-n" });
    if (page != null) {
      big.append(node("i", { class: "chap-p", text: "p." }), node("b", { text: String(page) }));
    }
    btn.append(big);
    if (count) btn.append(node("span", { class: "stamp", "aria-hidden": "true", text: String(count) }));
    btn.append(node("span", { class: "cap", text: name }));
    btn.addEventListener("click", () => pickChapter(sys.id));
    els.systems.append(btn);
  }
}

function paintJobs() {
  els.jobs.replaceChildren();
  const rows = jobsBy.get(state.systemId) || [];
  for (const job of rows) {
    const page = pageOf(job);
    const btn = node("button", {
      type: "button",
      class: job.id === state.jobId ? "job is-on" : "job",
      role: "listitem",
      "data-id": job.id,
    });
    btn.append(node("span", { class: "job-t", text: job.title || job.id }));
    if (page != null) btn.append(node("span", { class: "stamp", text: stampPage(page) }));
    btn.addEventListener("click", () => openJob(job, [job]));
    els.jobs.append(btn);
  }
}

function pickChapter(systemId) {
  if (systemId === state.systemId) return;
  set({ systemId });
  paintChapters();
  paintJobs();
  els.jobs.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function chapterIdOf(job) {
  if (job && job.systemId) return job.systemId;
  const name = job && job.chapter;
  if (!name) return state.systemId;
  const hit = chapters.find((sys) => sys.id === name || sys.name === name || sys.chapter === name);
  return hit ? hit.id : state.systemId;
}

function openJob(job, rest) {
  if (!job || !job.id) return;
  snapshotY();
  const ids = (rest || []).map((row) => row && row.id).filter(Boolean);
  const partId = (Array.isArray(job.partIds) && job.partIds[0]) || job.partId || null;
  set({
    jobId: job.id,
    jobIds: ids.length ? ids : [job.id],
    systemId: chapterIdOf(job),
    partId,
  });
  emit("part", { partId });
  go("book");
}

function manualId() {
  const rec = T.bike(state.bikeId);
  return (rec && rec.manualId) || "";
}

function setBusy(on) {
  if (!els) return;
  els.bar.classList.toggle("is-busy", on);
  els.meter.hidden = !on;
  els.meter.classList.toggle("run", on);
  els.cam.disabled = on;
  syncSend();
}

function syncSend() {
  if (!els) return;
  els.send.disabled = busy || !String(els.input.value || "").trim();
}

function clearMiss() {
  if (missTimer) {
    window.clearTimeout(missTimer);
    missTimer = 0;
  }
  if (els) els.bar.classList.remove("miss");
}

function miss() {
  clearMiss();
  if (!els) return;
  els.bar.classList.add("miss");
  missTimer = window.setTimeout(() => {
    missTimer = 0;
    if (els) els.bar.classList.remove("miss");
  }, MISS_MS);
}

async function submit(text) {
  const q = String(text || "").trim();
  if (!q || busy) return;
  const id = manualId();
  if (!id) return;
  stopMic();
  clearMiss();
  els.input.value = q;
  busy = true;
  setBusy(true);
  const token = ++askGen;

  let jobs = [];
  try {
    const res = await T.ask(id, q);
    jobs = Array.isArray(res) ? res : (res && res.jobs) || [];
  } catch {
    jobs = [];
  }
  if (token !== askGen) return;
  busy = false;
  setBusy(false);
  if (!jobs.length) {
    miss();
    return;
  }
  els.input.value = "";
  syncSend();
  openJob(jobs[0], jobs);
}

async function onFile() {
  const file = els.file.files && els.file.files[0];
  els.file.value = "";
  if (!file || busy) return;
  stopMic();
  clearMiss();
  busy = true;
  setBusy(true);
  const token = ++askGen;

  let rows = [];
  try {
    rows = (await T.identifyPart(file)) || [];
  } catch {
    rows = [];
  }
  if (token !== askGen) return;
  busy = false;
  setBusy(false);
  const top = Array.isArray(rows) ? rows[0] : null;
  if (!top) {
    miss();
    return;
  }
  const phrase = String(top.phrase || top.label || "").replace(/_/g, " ").trim();
  if (!phrase) {
    miss();
    return;
  }
  els.input.value = phrase;
  syncSend();
  submit(phrase);
}

function paintMic() {
  if (!els) return;
  els.mic.hidden = !stt.supported;
  els.mic.setAttribute("aria-pressed", listening ? "true" : "false");
  els.mic.classList.toggle("is-on", listening);
}

function stopMic() {
  if (!listening) return;
  listening = false;
  try {
    stt.stop();
  } catch {
    /* already stopped */
  }
  paintMic();
}

function toggleMic() {
  if (listening) {
    stopMic();
    return;
  }
  if (!stt.supported || busy) return;
  listening = true;
  paintMic();
  stt.start(
    (text) => {
      if (!listening) return;
      els.input.value = text;
      syncSend();
    },
    () => {
      listening = false;
      paintMic();
    }
  );
}

function terms() {
  const out = [];
  for (const sys of chapters) {
    if (sys.name) out.push(sys.name);
    for (const job of jobsBy.get(sys.id) || []) {
      if (job && job.title) out.push(job.title);
    }
  }
  return out;
}

async function primeVoice() {
  const token = ++voiceGen;
  let cfg = null;
  try {
    cfg = await T.voiceConfig();
  } catch {
    cfg = null;
  }
  if (token !== voiceGen || !els) return;
  if (cfg && cfg.deepgram && deepgram.supported && T.online()) {
    stt = deepgram;
  }
  stt.prime(terms());
  paintMic();
}
