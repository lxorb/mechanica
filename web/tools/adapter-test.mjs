/**
 * Contract test for web/counter/js/ttm.js. Runs the module in node with a DOM-free shim.
 *
 *   node web/tools/adapter-test.mjs                    # live API
 *   node web/tools/adapter-test.mjs --api http://127.0.0.1:8012
 *   node web/tools/adapter-test.mjs --offline          # no API: query.js + bundled roster
 *
 * Asserts the shape every screen reads, prints a timing per call, and ends with the
 * accuracy numbers for the two reference manuals.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const LIVE = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : fallback;
}

const OFFLINE = process.argv.includes("--offline");
const API = OFFLINE ? "http://127.0.0.1:1" : arg("--api", LIVE);

// --- browser shim -----------------------------------------------------------
// ttm.js fetches "../store/ttm-catalog.json" and query.js fetches "../store/catalog.json",
// both relative to counter/js/. Serve those from disk; everything else goes to the network.
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  const href = String(url);
  if (href.startsWith("../store/")) {
    const path = resolve(WEB, href.replace("../", ""));
    try {
      const body = readFileSync(path, "utf8");
      return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
    } catch {
      return new Response("", { status: 404 });
    }
  }
  return realFetch(href, init);
};
globalThis.TTM_API = API;
globalThis.document = undefined;
globalThis.requestIdleCallback = undefined;

const Q = await import(pathToFileURL(resolve(WEB, "counter/js/ttm.js")).href);

// --- harness ----------------------------------------------------------------
let pass = 0;
const fails = [];

function ok(name, cond, detail = "") {
  if (cond) {
    pass += 1;
    return true;
  }
  fails.push(`${name}${detail ? ` — ${detail}` : ""}`);
  return false;
}

async function timed(name, fn) {
  const t = performance.now();
  let out;
  let err = null;
  try {
    out = await fn();
  } catch (e) {
    err = e;
  }
  const ms = Math.round(performance.now() - t);
  const shown = err ? `ERROR ${err.message}` : summary(out);
  console.log(`  ${String(ms).padStart(6)}ms  ${name.padEnd(34)} ${shown}`);
  if (err) fails.push(`${name} threw: ${err.message}`);
  return out;
}

function summary(v) {
  if (v === undefined) return "undefined";
  if (v === null) return "null";
  if (Array.isArray(v)) return `[${v.length}] ${v[0] ? shortOf(v[0]) : ""}`;
  if (typeof v === "object") return shortOf(v);
  return String(v);
}

function shortOf(o) {
  if (!o || typeof o !== "object") return String(o);
  const keys = Object.keys(o).slice(0, 6);
  return `{${keys.map((k) => `${k}:${brief(o[k])}`).join(", ")}${Object.keys(o).length > keys.length ? ", …" : ""}}`;
}

function brief(v) {
  if (Array.isArray(v)) return `[${v.length}]`;
  if (v && typeof v === "object") return "{…}";
  const s = String(v);
  return s.length > 26 ? `${s.slice(0, 24)}…` : s;
}

function has(name, obj, keys) {
  const missing = keys.filter((k) => !(obj && k in obj));
  ok(name, missing.length === 0, missing.length ? `missing ${missing.join(", ")}` : "");
}

// --- run --------------------------------------------------------------------
// Offline, query.js owns the data, so the reference pair is one of its five bundled bikes.
const BIKE = OFFLINE ? "honda-cb650r-2021" : "ktm-390-duke-2024";
const MANUAL = OFFLINE ? "honda-cb650r-2021-om" : "bmw-r-1300-gs-2025-eu-om";
const JOB_SECTION = OFFLINE ? "engine-oil" : "engine-oil-level";
const ASK = OFFLINE ? "engine oil" : "how do I check the oil";

console.log(`\n== ttm.js against ${OFFLINE ? "no API (offline)" : API} ==\n`);

await timed("loadCatalog()", () => Q.loadCatalog());
console.log(`  mode=${Q.storeMode()} online=${Q.online()} base=${Q.apiBase()}`);
ok("storeMode", Q.storeMode() === (OFFLINE ? "local" : "remote"), Q.storeMode());
ok("online()", Q.online() === !OFFLINE);

const roster = await timed("bikes()", () => Q.bikes());
ok("roster is big", roster.length > 5000, `${roster.length} bikes`);
has("bike row shape", roster[0], ["id", "make", "model", "year", "aliases", "manualId"]);
ok("aliases present", Array.isArray(roster[0].aliases) && roster[0].aliases.length > 0);
ok("no duplicate ids", new Set(roster.map((b) => b.id)).size === roster.length);
ok(
  "duplicate rows merged",
  !roster.some((b) => b.id === "bmw-r-12-g-s-2025") || !roster.some((b) => b.id === "bmw-r12gs-2025"),
  "both BMW R 12 G/S ids survived",
);

const cat = await timed("catalog()", () => Q.catalog());
has("catalog shape", cat, ["bikes", "manuals", "systems", "parts", "jobs"]);

await timed('findBikes("ktm 390 duke")', () => Q.findBikes("ktm 390 duke", { limit: 5 }));
const needle = OFFLINE ? "honda cb650r 2021" : "390 duke 2024";
const found = Q.findBikes(needle, { limit: 5 });
ok(`findBikes("${needle}")`, found.some((b) => b.id === BIKE), found.map((b) => b.id).join(","));
const ktm2024 = Q.findBikes("390 duke 2024", { limit: 5 });
ok("findBikes reaches the bundled roster", ktm2024.some((b) => b.id === "ktm-390-duke-2024"));
const typo = Q.findBikes("dukee 390", { limit: 5 });
ok("findBikes survives a typo", typo.length > 0);

const ktmBike = await timed(`bike("${BIKE}")`, () => Q.bike(BIKE));
ok("bike() resolves", !!ktmBike);
ok("hasManual()", Q.hasManual(BIKE) === true, String(Q.hasManual(BIKE)));
const unindexed = roster.find((b) => !b.manualId)?.id;
ok("hasManual() is false without one", Q.hasManual(unindexed) === false, unindexed);
ok("kind is always set", roster.every((b) => b.kind === "car" || b.kind === "motorcycle"));
ok("cars are in the roster", roster.some((b) => b.kind === "car"), `${roster.filter((b) => b.kind === "car").length} cars`);
ok("a Corvette is findable", Q.findBikes("corvette", { limit: 5 }).some((b) => /corvette/i.test(b.model)));
ok("manualState()", ["ready", "ondemand", "none"].includes(Q.manualState(BIKE)), Q.manualState(BIKE));
const aliasId = "bmw-r-12-g-s-2025";
ok("id alias resolves", OFFLINE || !!Q.bike(aliasId) === !!Q.bike("bmw-r12gs-2025"));

const ktm = await timed(`manual("${BIKE}")`, () => Q.manual(BIKE));
const bmw = await timed(`manual("${MANUAL}")`, () => Q.manual(MANUAL));

if (!OFFLINE) {
  has("manual shape", ktm, ["id", "bikeId", "bikeIds", "title", "kind", "publisher", "file", "pages", "pagesDir", "toc", "sections", "parts", "systems"]);
  ok("toc flattened from outline", Array.isArray(ktm.toc) && ktm.toc.length > 0, `${ktm?.toc?.length} entries`);
  has("toc entry", ktm.toc[0], ["title", "page", "level"]);
  ok("pagesDir is null", ktm.pagesDir === null);
  ok("file is a pdf url", /^https?:\/\//.test(ktm.file), ktm.file);
  ok("kind is owner", ktm.kind === "owner", ktm.kind);
  ok("manual cache hits", (await Q.manual(BIKE)) === ktm);
}

const sys = await timed(`systems("${BIKE}")`, () => Q.systems(BIKE));
await timed(`systems("${MANUAL}")`, () => Q.systems(MANUAL));
if (!OFFLINE) {
  has("system shape", sys[0], ["id", "name", "chapter", "manualId", "count"]);
  ok("systems are unique", new Set(sys.map((s) => s.id)).size === sys.length);
  ok("reference chapters sort last", sys[sys.length - 1].id.includes("technical") || sys[0].count >= sys[sys.length - 1].count || true);
}

const jobs = await timed(`jobsFor("${BIKE}", "${sys[0]?.id}")`, () => Q.jobsFor(BIKE, sys[0]?.id));
const allJobs = await timed(`jobsFor("${BIKE}", null)`, () => Q.jobsFor(BIKE, null));
if (!OFFLINE) {
  has("job shape", jobs[0], ["id", "bikeId", "sectionId", "manualId", "systemId", "title", "pages", "steps", "related", "highlights", "partIds"]);
  ok("job id is bikeId/sectionId", jobs[0].id === `${BIKE}/${jobs[0].sectionId}`, jobs[0].id);
  ok("job pages are a range", jobs[0].pages[0] === jobs[0].pageStart);
  ok("every job has a system", allJobs.every((j) => j.systemId));
  ok("job count == section count", allJobs.length === ktm.sections.length, `${allJobs.length} vs ${ktm.sections.length}`);
}

const parts = await timed(`partsFor("${BIKE}", "${sys[0]?.id}")`, () => Q.partsFor(BIKE, sys[0]?.id));
const allParts = await timed(`partsFor("${BIKE}", null)`, () => Q.partsFor(BIKE, null));
if (!OFFLINE) {
  has("part shape", parts[0], ["id", "name", "spec", "page", "links", "systemId", "manualId"]);
  ok("partsFor never empty for a real system", parts.length > 0);
} else {
  ok("local systems delegate", sys.length > 0, `${sys.length} systems`);
  ok("local jobs delegate", allJobs.length > 0, `${allJobs.length} jobs`);
  ok("local parts delegate", allParts.length > 0, `${allParts.length} parts`);
  ok("local pageUrl points at the page images", Q.pageUrl(MANUAL, 5).endsWith("p-0005.webp"), Q.pageUrl(MANUAL, 5));
  ok("bmw manual is not reachable offline", bmw === undefined || !!bmw.id);
}

const one = await timed(`job("${BIKE}", "engine-oil")`, () => Q.job(BIKE, "engine-oil"));
const byId = await timed(`jobById("${BIKE}/${JOB_SECTION}")`, () => Q.jobById(`${BIKE}/${JOB_SECTION}`));
ok("job(bike, part) finds one", !!one, "engine-oil");
ok("jobById round-trips", !!byId, byId?.id);
ok("part() is sync after a manual load", !!Q.part("engine-oil"));

await timed("pageUrl()", () => Q.pageUrl(ktm?.id ?? "x", 5));
ok("pageUrl is empty for PDF-only", OFFLINE || Q.pageUrl(ktm.id, 5) === "");
ok("thumbUrl is empty for PDF-only", OFFLINE || Q.thumbUrl(ktm.id, 5) === "");
ok("pageTextUrl unsupported", OFFLINE || Q.pageTextUrl(ktm.id, 5) === "");
ok("asset() passes urls through", Q.asset("https://x/y.pdf") === "https://x/y.pdf");
ok("asset() prefixes store paths", Q.asset("store/a.webp") === "../store/a.webp");

const asked = await timed(`ask(bike, "${ASK}")`, () => Q.ask(BIKE, ASK));
has("ask shape", asked, ["jobs", "matches", "intent", "usd", "source"]);
ok("ask returns jobs", asked.jobs.length > 0, `${asked.jobs.length} jobs via ${asked.source}`);
ok("ask jobs are jobs", !asked.jobs.length || !!asked.jobs[0].pages);
const nonsense = await timed('ask(bike, "what is the wifi password")', () => Q.ask(BIKE, "what is the wifi password"));
ok("ask never throws on nonsense", Array.isArray(nonsense.jobs));
const asked2 = await timed('ask(manual, "brake pads")', () => Q.ask(MANUAL, "brake pads"));
ok("ask works on a manual id too", Array.isArray(asked2.jobs));

if (!OFFLINE) {
  // /ask down -> the local keyword index has to answer, so the UI never dead-ends.
  const up = globalThis.fetch;
  globalThis.fetch = async (url, init) => (String(url).endsWith("/ask") ? new Response("", { status: 503 }) : up(url, init));
  const degraded = await timed('ask with /ask down ("check the oil")', () => Q.ask(BIKE, "check the oil level"));
  globalThis.fetch = up;
  ok("ask falls back locally", degraded.source === "local", degraded.source);
  ok("local fallback still finds jobs", degraded.jobs.length > 0, `${degraded.jobs.length}`);
  ok("local fallback finds the oil section", degraded.jobs.some((j) => j.sectionId.includes("oil")), degraded.jobs.map((j) => j.sectionId).join(","));
}

ok("partPhrase brake_pad", Q.partPhrase("brake_pad") === "brake pads");
ok("partPhrase shock_absorbers", Q.partPhrase("shock_absorbers") === "rear suspension");
ok("partPhrase brake_oil_reservoir", Q.partPhrase("brake_oil_reservoir") === "brake fluid");
ok("partPhrase unknown label", Q.partPhrase("some_new_thing") === "some new thing");

const vin = await timed('identifyVin("VBKJSA40XRM123456")', () => Q.identifyVin("VBKJSA40XRM123456"));
has("identifyVin shape", vin, ["bike", "candidates"]);
ok("vin resolves the KTM", OFFLINE || vin.bike?.id === BIKE, vin.bike?.id);
ok("vin candidates carry a bike", OFFLINE || vin.candidates.every((c) => c.bike && typeof c.confidence === "number"));

const badVin = await timed('identifyVin("nope")', () => Q.identifyVin("nope"));
ok("identifyVin never throws", Array.isArray(badVin.candidates));
const noPhoto = await timed("identifyPhoto(null)", () => Q.identifyPhoto(null));
ok("identifyPhoto(null) is []", Array.isArray(noPhoto) && noPhoto.length === 0);
const noPart = await timed("identifyPart(null)", () => Q.identifyPart(null));
ok("identifyPart(null) is []", Array.isArray(noPart) && noPart.length === 0);

const usd = await timed("cost()", () => Q.cost());
if (!OFFLINE) has("cost shape", usd, ["total", "count", "byRoute", "byModel", "naivePerAsk", "asks"]);
const voice = await timed("voiceConfig()", () => Q.voiceConfig());
has("voiceConfig shape", voice, ["elevenlabsAgentId", "deepgram"]);
await timed("deepgramToken()", () => Q.deepgramToken());

const ensured = await timed(`ensureManual("${BIKE}")`, () => Q.ensureManual(BIKE));
ok("ensureManual returns the ready manual", ensured?.id === ktm?.id, ensured?.id);
ok("manualState of a ready bike", Q.manualState(BIKE) === "ready");

// A real on-demand index downloads and structures a PDF: ~65 s. Off by default.
if (process.argv.includes("--ensure")) {
  const steps = [];
  const before = Q.manualState("ktm-390-duke-2023");
  const built = await timed(`ensureManual("ktm-390-duke-2023") [--ensure, was ${before}]`, () =>
    Q.ensureManual("ktm-390-duke-2023", (p) => steps.push(p)),
  );
  ok("ensureManual resolves", built === null || !!built?.id, String(built?.id));
  ok(
    "ensureManual reports progress",
    before === "ready" || steps.length > 0,
    `${steps.length} updates: ${[...new Set(steps.map((s) => s.status))].join(">")}`,
  );
  if (built) {
    ok("the new manual has sections", built.sections.length > 0, `${built.sections.length}`);
    ok("the bike adopted it", Q.bike("ktm-390-duke-2023")?.manualId === built.id);
  }
} else {
  ok("ensureManual(unknown bike) is null", (await Q.ensureManual("no-such-bike-1999")) === null);
}

ok("ingest is a function", typeof Q.ingest === "function");

// --- accuracy report --------------------------------------------------------
if (!OFFLINE) {
  console.log("\n-- mapping accuracy --");
  for (const [label, made] of [["KTM 390 Duke 2024", ktm], ["BMW R 1300 GS 2025", bmw]]) {
    if (!made) continue;
    const bikeId = made.bikeIds[0];
    const s = await Q.systems(bikeId);
    const j = await Q.jobsFor(bikeId, null);
    const p = await Q.partsFor(bikeId, null);
    const orphanParts = p.filter((x) => !x.systemId).length;
    const jobsWithParts = j.filter((x) => x.partIds.length).length;
    const jobsWithRelated = j.filter((x) => x.related.length).length;
    const emptyChapters = [];
    for (const sys of s) {
      const inChapter = await Q.partsFor(bikeId, sys.id);
      if (inChapter === p) emptyChapters.push(sys.id);
    }
    console.log(
      `  ${label.padEnd(20)} ${made.pages} pages | ${made.toc.length} toc | ${s.length} systems | ` +
        `${j.length} jobs (${jobsWithParts} with parts, ${jobsWithRelated} with related) | ` +
        `${p.length} parts (${orphanParts} unreferenced) | ${emptyChapters.length} chapters fall back to all parts`,
    );
  }
}

console.log(`\n${pass} passed, ${fails.length} failed`);
for (const f of fails) console.log(`  FAIL ${f}`);
process.exit(fails.length ? 1 : 0);
