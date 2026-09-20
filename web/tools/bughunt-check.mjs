/**
 * Regressions for the JS half of the 2026-09-20 bug hunt (docs/qa/BUGS.md).
 * No DOM, no network: every module under test is pure.
 *
 *   node web/tools/bughunt-check.mjs
 */

import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const mod = (p) => import(pathToFileURL(resolve(ROOT, p)).href);

let pass = 0;
const fails = [];
function ok(name, cond, detail = "") {
  if (cond) pass++;
  else fails.push(`${name}${detail ? ` — ${detail}` : ""}`);
}
function eq(name, got, want) {
  ok(name, JSON.stringify(got) === JSON.stringify(want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

const search = await mod("web/counter/js/search.js");
const pickSearch = await mod("web/counter/js/pick-search.js");
const bus = await mod("web/counter/js/bus.js");
const worker = await mod("worker/index.js");

/* --------------------------------------------------- BUG-08  highlight offsets on folded text */

// "Tenere" with decomposed accents (e + U+0301), which is how plenty of PDF text layers hand a
// French or German heading over. The old map counted characters in the NORMALISED copy and then
// indexed the ORIGINAL, so every offset after the first accent was off by one per accent.
const DECOMPOSED = "Ténéré 700".normalize("NFD");
{
  const { folded, map, ends } = search.foldWithMap(DECOMPOSED);
  eq("foldWithMap folds the accents away", folded, "tenere700");
  ok("foldWithMap starts at the first letter", map[0] === 0, `map[0]=${map[0]}`);
  // the "7" of 700 is the 7th folded char; slicing the original there must give "7"
  const at = folded.indexOf("700");
  ok(
    "foldWithMap offsets index the ORIGINAL string",
    DECOMPOSED.slice(map[at], ends[at + 2]) === "700",
    `sliced ${JSON.stringify(DECOMPOSED.slice(map[at], ends[at + 2]))}`,
  );
  // a span over an accented letter keeps its combining mark
  eq("a span swallows its combining mark", DECOMPOSED.slice(map[0], ends[5]).normalize("NFC"), "Ténéré");
}

{
  const spans = pickSearch.marks(`Checking the ${DECOMPOSED} chain`, "chain");
  ok("marks() finds the word", spans.length === 1, JSON.stringify(spans));
  const cut = `Checking the ${DECOMPOSED} chain`.slice(spans[0]?.start, spans[0]?.end);
  eq("marks() offsets index the ORIGINAL title", cut, "chain");
}

{
  const plain = "Checking the engine oil level";
  const spans = pickSearch.marks(plain, "oil");
  eq("marks() still works on plain ASCII", plain.slice(spans[0].start, spans[0].end), "oil");
}

/* ------------------------------------------------------------ BUG-09  a pasted paragraph query */

{
  const bikes = [];
  for (let i = 0; i < 400; i++) {
    bikes.push({ id: `b${i}`, make: "KTM", model: `${390 + i} Duke`, year: 2024, manualId: null });
  }
  search.buildIndex(bikes);
  const nasty = new Array(4000).fill("a").join(" "); // every token matches something
  const t0 = performance.now();
  const hits = search.search(nasty, { limit: 10 });
  const ms = performance.now() - t0;
  ok("bike search survives a pasted paragraph", ms < 1500, `${Math.round(ms)} ms`);
  ok("bike search still answers", Array.isArray(hits));
  ok("MAX_QUERY_TOKENS is published", search.MAX_QUERY_TOKENS > 0 && search.MAX_QUERY_TOKENS <= 32);
}

{
  const entries = pickSearch.build({
    manual: {
      pages: 200,
      outline: Array.from({ length: 300 }, (_, i) => ({ title: `${i} Checking the oil level`, page: i + 1 })),
    },
    jobs: [],
  });
  const nasty = new Array(4000).fill("oil").join(" ");
  const t0 = performance.now();
  const hits = pickSearch.search(entries, nasty, 20);
  const ms = performance.now() - t0;
  ok("pick search survives a pasted paragraph", ms < 1500, `${Math.round(ms)} ms`);
  ok("pick search still answers", hits.length > 0);
}

/* ----------------------------------------------------------- search corner cases (no regression,
   just the ones the hunt was asked to cover, pinned so they stay true) */

{
  eq("empty query returns nothing on Pick", pickSearch.search([], ""), []);
  eq("splitHeading keeps a slashed model code", pickSearch.splitHeading("85/105 SX").label, "85/105 SX");
  const entries = pickSearch.build({
    manual: {
      pages: 20,
      outline: [
        { title: "1 Chain", page: 3 },
        { title: "2 Pneus / Ténéré".normalize("NFD"), page: 8 },
      ],
    },
    jobs: [],
  });
  ok("diacritics are searchable unaccented", pickSearch.search(entries, "tenere").length === 1);
  ok("a model code with a slash narrows", pickSearch.search(entries, "pneus tenere").length === 1);
  ok("an unmatched token narrows to nothing", pickSearch.search(entries, "chain tenere").length === 0);
}

/* --------------------------------------------------------- BUG-05  the proxy's own 307s */

{
  const here = new URL("https://mechanica.emilvinu.ch/api/health/");
  const API = "https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io";
  eq(
    "an http:// redirect back to the API is rewritten under /api",
    worker.backToApi(`${API.replace("https://", "http://")}/health`, here),
    "https://mechanica.emilvinu.ch/api/health",
  );
  eq(
    "the query survives the rewrite",
    worker.backToApi(`${API}/catalog/suggest?q=duke`, here),
    "https://mechanica.emilvinu.ch/api/catalog/suggest?q=duke",
  );
  eq(
    "a blob redirect is left alone",
    worker.backToApi("https://ttm48317e81bf0f44248f69c.blob.core.windows.net/pdf/x.pdf", here),
    "",
  );
  // a relative Location is legal HTTP and means "this origin", which through the proxy is /api
  eq("a relative redirect lands under /api", worker.backToApi("/health", here), "https://mechanica.emilvinu.ch/api/health");
  eq("another host is left alone", worker.backToApi("https://example.com/x", here), "");
}

/* ------------------------------------------- BUG-21  one bad bundle row must not kill the roster */

{
  const indexData = await mod("web/counter/js/index-data.js");
  const good = indexData.expandBundle({ rows: [["KTM", "390 Duke", { r: [2023, 2025] }, {}, "EU"]] });
  eq("a normal year range expands", good.map((b) => b.year), [2023, 2024, 2025]);
  let survived = true;
  let rows = [];
  try {
    rows = indexData.expandBundle({
      rows: [
        ["KTM", "390 Duke", { r: [2026, 2020] }, {}, "EU"],
        ["BMW", "R 1300 GS", { r: [2024, 2024] }, {}, "EU"],
      ],
    });
  } catch {
    survived = false;
  }
  ok("a reversed year range does not throw", survived);
  eq("the good row beside it still expands", rows.map((b) => b.id), ["bmw-r-1300-gs-2024"]);
}

/* ------------------------------------------------------------------- bus.js hash routing edges */

{
  eq("splitHash of a bare screen", bus.splitHash("#book"), { screen: "book", overlay: "" });
  eq("splitHash of an overlay", bus.splitHash("#book+invoice"), { screen: "book", overlay: "invoice" });
  eq("splitHash of an empty hash", bus.splitHash(""), { screen: "", overlay: "" });
  eq("splitHash of a bare +", bus.splitHash("#+invoice"), { screen: "", overlay: "invoice" });
  eq("splitHash of a double +", bus.splitHash("#book+a+b"), { screen: "book", overlay: "a+b" });
  eq("splitHash of a non-string", bus.splitHash(null), { screen: "", overlay: "" });
  eq("FLOW is the four steps", bus.FLOW, ["identify", "confirm", "pick", "book"]);
}

console.log(`\n${pass} passed, ${fails.length} failed`);
for (const f of fails) console.log(`  FAIL ${f}`);
process.exit(fails.length ? 1 : 0);
