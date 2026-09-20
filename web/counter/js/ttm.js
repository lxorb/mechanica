/**
 * Trust-the-manual backend adapter for the Handy Book counter app.
 * Owner: adapter agent. Screens import ONLY these names (plus query.js names re-exported from here).
 * Base URL: window.TTM_API (set in index.html) or the same-origin "/api" proxy.
 *
 * Mapping of our backend (api/app/models.py) onto the Handy Book model used by the screens:
 *   Bike    -> bike     {id, make, model, year, aliases[], manualId|null, thumb?, image?}
 *   Manual  -> manual   {id, bikeId, bikeIds[], title, kind:"owner", publisher, file (PDF url), pages, toc[{title,page}]}
 *   chapter -> system   {id, name}                        (distinct Section.chapter of a manual, rider tasks first)
 *   Part    -> part     {id, systemId, name, spec, page, oem?, links[{shop,url}]}
 *   Section -> job      {id: bikeId+"/"+sectionId, bikeId, sectionId, manualId, partId?, title, chapter,
 *                        pages[pageStart..pageEnd], steps[{page}], related[{page,title}], highlights[{page,x,y,w,h}], partIds[]}
 */

// --- query.js-compatible surface (sync after loadCatalog) ---
export async function loadCatalog() {}              // GET /catalog (+ bundled fallback); builds bikes/manuals caches
export function catalog() {}                        // {bikes, systems:[], parts:[], manuals}
export function bikes() {}
export function findBikes(text, opts) {}            // local index over the full catalog + /catalog/suggest merge
export function bike(id) {}
export function hasManual(id) {}
export async function manual(id) {}                 // GET /manuals/{id} -> manual (cached)
export async function systems(bikeId) {}            // chapters of the bike's manual
export async function partsFor(bikeId, systemId) {} // parts referenced by sections in that chapter
export async function jobsFor(bikeId, systemId) {}  // jobs (sections) in that chapter, rider tasks first
export async function job(bikeId, partId) {}        // first job that lists that part
export async function jobById(id) {}
export function part(id) {}
export function pageUrl(manualId, n) {}             // "" for PDF-only manuals (render with pdf.js instead)
export function thumbUrl(manualId, n) {}
export function pageTextUrl(manualId, n) {}
export function asset(path) {}

// --- ours ---
export async function ask(manualId, query) {}       // POST /ask -> {jobs:[job], intent, usd}; [] when out of scope
export async function identifyPhoto(file) {}        // POST /identify/photo -> [{bike, confidence}]
export async function identifyVin(vin) {}           // POST /identify/vin -> {bike|null, candidates:[{bike,confidence}]}
export async function identifyPart(file) {}         // POST /identify/part -> [{label, confidence, phrase}]
export async function ingest(fileOrUrl, meta, onProgress) {} // POST /ingest(/upload) + poll -> manual
export async function cost() {}                     // GET /cost
export async function voiceConfig() {}              // GET /voice/config -> {elevenlabsAgentId, deepgram}
export async function deepgramToken() {}            // POST /voice/deepgram-token
export function apiBase() {}
export function online() {}                         // true when the API answered /health once this session
