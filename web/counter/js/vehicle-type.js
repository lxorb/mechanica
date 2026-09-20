/**
 * Which vehicle a bike *is*, and which 3D model to show for it. Owner: vehicle-models agent.
 * No imports, no DOM, no fetch except the two lookup tables it loads on demand — so it is safe
 * to import from a worker, a node script or the viewer.
 *
 * ---------------------------------------------------------------------------------------------
 * INTEGRATION CONTRACT (js/viewer3d.js consumes exactly this)
 *
 *   await ready()                  // loads ../store/bike-types.json + bike-colors.json once;
 *                                  // resolves even when both 404 — heuristics still answer
 *   typeOf(bike)      -> type      // one of TYPES, never null; "naked" is the fallback
 *   exactModelFor(b)  -> key|null  // "yzf-2021" | "honda-cbr650r" | "corvette-c8"
 *   genericModelFor(type, bike)    // generic model key, make-aware (a KTM motocross gets the KTM)
 *   tintFor(bike)     -> "#rrggbb" | null
 *
 *   modelFor(bike) -> {
 *     key:    "yzf-2021" | "generic/motocross-ktm" | …   // stable id, also the cache key
 *     url:    "../../store/models/<key>/model.glb"       // absolute, resolved off this module
 *     exact:  boolean,        // true = this is the bike itself, not a stand-in for its type
 *     type:   "sportbike",    // typeOf(bike)
 *     tint:   "#e0341f"|null, // paint colour; null = leave the model's own paint alone
 *     parts:  "bike"|"car",   // which part table the viewer should match node names against
 *     label:  "KTM 450 SX-F", // what is actually on screen, for the credit line
 *   }
 *
 * `tint` is a base-colour swap on the paint groups only (fuel-tank / fairing / frame bodywork):
 * set `material.color`, leave roughness, metalness, normal and AO alone, and never touch a mesh
 * whose part key is wheel, engine, exhaust, seat or a light. modelFor() is synchronous; call
 * ready() once at boot if you want the tables, and it degrades to heuristics + brand colours if
 * they never arrive.
 * ---------------------------------------------------------------------------------------------
 *
 * Why a type at all: we have three exact models and 22.3k bikes. The brief is "if we have the
 * exact model take it, otherwise one general model for that type", so every bike has to land in
 * a bucket that a generic model can honestly stand for. A KTM 450 SX-F must not be a sportbike.
 *
 * Where the type comes from, in order:
 *   1. the make/model name heuristics in RULES below.
 *   2. ../store/bike-types.json — folded make|model -> type code, distilled from the bikez
 *      Category column (38k rows, api/data/seeds/all_bikez_curated.csv) by web/tools/bike-types.mjs.
 *   3. "naked", the most forgiving silhouette to stand in for an unknown motorcycle.
 *
 * The brief asked for the bikez Category first, and the data said no. Its categories are a decade
 * of crowd edits: a Honda Grom is filed under "Sport", a Super Ténéré under "Super motard", every
 * R 1250 GS and Africa Twin under "Enduro / offroad" — and it has no adventure category at all,
 * which is one of the shapes the app must show. The model name, by contrast, is a manufacturer's
 * own naming scheme and says exactly what the bike is: SX-F, EXC, SMC, YZF, GS, Ténéré. So the
 * names lead and bikez fills the gaps, which is also why bike-types.json ships as only the keys
 * no rule below has an opinion on — see web/tools/bike-types.mjs.
 */

/* ------------------------------------------------------------------ vocabulary */

/** Every type the app can show. Order is the report/debug order, not a priority. */
export const TYPES = [
  "motocross", "enduro", "supermoto", "sportbike", "naked", "adventure", "touring",
  "cruiser", "scooter", "classic", "trial", "minibike", "car",
];

export const TYPE_LABELS = {
  motocross: "Motocross", enduro: "Enduro", supermoto: "Supermoto", sportbike: "Sportbike",
  naked: "Naked", adventure: "Adventure", touring: "Touring", cruiser: "Cruiser",
  scooter: "Scooter", classic: "Classic", trial: "Trials", minibike: "Minibike", car: "Car",
};

export const FALLBACK_TYPE = "naked";

/** Single-letter codes, so bike-types.json stays a fraction of the size of the type names. */
export const TYPE_CODES = {
  x: "motocross", e: "enduro", u: "supermoto", s: "sportbike", n: "naked", a: "adventure",
  t: "touring", c: "cruiser", k: "scooter", l: "classic", r: "trial", m: "minibike", g: "car",
};
export const CODE_OF = Object.fromEntries(Object.entries(TYPE_CODES).map(([code, type]) => [type, code]));

/* ------------------------------------------------------------------ key folding
 * Identical to ttm.js imageKey(), on purpose: bike-types.json, bike-images.json and
 * bike-colors.json are all keyed "make|model" the same way, so one fold serves all three.
 */

export const foldPart = (value) =>
  String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "");

export const bikeKey = (make, model) => `${foldPart(make)}|${foldPart(model)}`;

/** Trailing variant words the tables rarely distinguish: "F 900 R ABS" -> "F 900 R". */
const VARIANT = /[\s-]+(abs|se|le|sp|gt|eu|us|dct|i|ie|fi)$/i;

/** Walk a table shortening the model name, the way ttm.js lookupImage does. */
function lookup(table, make, model) {
  if (!table) return null;
  let name = String(model ?? "");
  for (let i = 0; i < 4; i++) {
    const hit = table[bikeKey(make, name)];
    if (hit) return hit;
    const shorter = name.replace(VARIANT, "");
    if (shorter === name || !shorter) return null;
    name = shorter;
  }
  return null;
}

/* ------------------------------------------------------------------ name heuristics
 * Tested against "<make> <model>" lowercased with punctuation flattened to spaces, so "YZF-R7"
 * is "yzf r7" and "CRF450R" is "crf450r". Ordered: the first rule that matches wins, so the
 * specific ones (a CRF450**R** is a motocrosser, a CRF450**X** is an enduro) come before the
 * families they live in. Every regex was checked against the 22.3k rows in api/data/bikes.json
 * with `node web/tools/bike-types.mjs --check`.
 */

/**
 * Makes that only ever build motorcycles. A car word inside one of their model names is a
 * special edition, not a car — "Ducati Streetfighter V4 Lamborghini" is a motorcycle — so the
 * car rules are skipped entirely for these.
 */
const BIKE_MAKES = new Set([
  "yamaha", "honda", "kawasaki", "suzuki", "ktm", "harley-davidson", "harley", "triumph", "bmw",
  "ducati", "aprilia", "husqvarna", "gasgas", "gas-gas", "indian", "moto-guzzi", "royal-enfield",
  "hero", "mv-agusta", "victory", "can-am", "zero", "sherco", "kove", "tvs", "bajaj", "cake",
  "kymco", "vmoto", "qj-motor", "voge", "niu", "vespa", "piaggio", "benelli", "beta", "cfmoto",
  "sym", "lambretta", "norton", "buell", "bimota", "ural", "jawa", "rieju", "fantic", "swm",
]);

const RULES = [
  // --- cars first: a car must never fall through into a motorcycle bucket
  ["car", /\b(corvette|stingray|camaro|mustang|porsche|ferrari|lamborghini|tesla|model [sy3x]\b)/],
  // no bare "seat" here even though SEAT makes cars: "Thruxton 1200 (Dual Seat)" is a motorcycle
  ["car", /\b(chevrolet|chevy|ford|toyota|volkswagen|audi|mercedes|nissan|mazda|volvo|skoda|renault|opel|fiat|jeep|dodge|chrysler|subaru|hyundai|kia|lexus|jaguar|land rover|mini cooper|cupra)\b/],

  // --- minibike: before motocross, because a "z125 pro" is a minibike not a KX
  ["minibike", /\b(grom|monkey|dax|msx ?125|z125|pw ?50|pw ?80|tt ?r ?50|crf ?50|crf ?110|kx ?65|mini ?moto|pocket ?bike|pit ?bike|ruckus|navi|trail ?125|ct ?125|super ?cub|sur ?ron|talaria)\b/],

  // --- trials: tiny, distinct, and its name words appear nowhere else
  ["trial", /\b(trial|txt ?racing|txt ?gp|cota|evo ?\d{3}$|raga|4rt|scorpa|beta evo)\b/],

  // --- supermoto before motocross/enduro: an SMC is an EXC with road wheels
  ["supermoto", /\b(smc|supermoto|super ?motard|motard|hypermotard|husqvarna 701 supermoto|sm ?[rct]?\b|701 sm|dr ?z ?400 ?sm|fs ?450|sxv|rxv)\b/],

  // --- motocross: closed-course race bikes
  ["motocross", /\b(sx ?f?|yz ?\d{2,3}f?|kx ?\d{2,3}f?|rm ?z|cr ?f? ?\d{3} ?r|crf ?\d{3} ?r|mc ?\d{2,3}|fc ?\d{3}|tc ?\d{2,3}|mx ?\d|motocross|cross)\b(?! ?country)/],

  // --- enduro / offroad
  ["enduro", /\b(exc|xc ?w|xcw|xc ?f?\b|wr ?\d{2,3}f?|wrf|crf ?\d{3} ?[xl]|fe ?\d{3}|te ?\d{3}|tx ?\d{3}|ec ?\d{3}|enduro|dr ?z|klx|ttr|xr ?\d{3}|tw ?200|serow|xt ?\d{3}|ec ?f|se ?\d ?f|beta rr|rr ?\d{3} ?racing|romeo|sef|sm ?r)\b/],

  // --- scooters, before sportbike (an "sh 125" must not read as an S 1000)
  ["scooter", /\b(vespa|x ?max|xmax|n ?max|nmax|burgman|pcx|forza|sh ?\d{2,3}|tricity|tmax|t ?max|scooter|scoot|dio|activa|jupiter|beat|vario|lead|zoomer|metropolis|liberty|primavera|sprint|gts ?\d{3}|gtv|medley|beverly|typhoon|fly ?\d|agility|like ?\d|people|downtown|ak ?550|xciting|silver ?wing|majesty|kymco|piaggio|sym|lambretta|peugeot ?(kisbee|django|tweet)|c ?\d00 ?(gt|x)|ce ?0[24]|nqi|mqi|ujet|seat mo|moped|scarabeo|sr ?\d{2,3}|habana|mojito|rs ?\d ?scoot)\b/],

  // --- adventure / big trail
  ["adventure", /\b(adventure|advent|\bgs\b|gsa|tenere|ténéré|africa twin|crf ?\d{4} ?l|versys|v ?strom|vstrom|dl ?\d{3,4}|tiger|multistrada|desert ?x|tuareg|klr|himalayan|scram|super ?adventure|norden|rally|transalp|varadero|caponord|stelvio|dominar|rx ?\d ?adv|nc ?\d{3} ?x|cb ?\d{3} ?x|tracer|f ?\d{3} ?gs|r ?\d{4} ?gs)\b/],

  // --- touring / baggers
  ["touring", /\b(gold ?wing|goldwing|k ?1600|fjr|\brt\b|glide|road ?king|roadmaster|pursuit|chieftain|challenger|voyager|vaquero|concours|trophy|st ?1300|nt ?\d{3,4}|tour|ltd|c ?650 ?gt|spyder|ryker|can ?am rt)\b/],

  // --- cruisers
  ["cruiser", /\b(rebel|vulcan|bolt|sportster|softail|dyna|fat ?boy|fatboy|breakout|low ?rider|street ?bob|nightster|forty ?eight|iron ?\d{3}|chief|scout|shadow|intruder|boulevard|marauder|vstar|v ?star|dragstar|bobber|speedmaster|rocket ?3|thunderbird|meteor|super ?meteor|shotgun|eliminator|vn ?\d{3,4}|c ?\d{2}b?|vt ?\d{3,4}|vtx|valkyrie|cruiser|chopper|diavel|xdiavel|x ?diavel|m ?109|volusia|savage|stryker|raider|roadstar|road ?star|phantom|aero|spirit|sabre|interstate|stateline|fury)\b/],

  // --- classic / retro / cafe
  ["classic", /\b(bonneville|thruxton|scrambler|street ?twin|speed ?twin|t ?100|t ?120|classic|continental gt|interceptor|bullet|hunter ?350|cafe|caf[eé] ?racer|retro|vintage|w ?\d{3}|z ?\d{3} ?rs|xsr|sr ?400|sr ?500|gb ?\d{3}|cl ?\d{3}|v7|v9|nevada|envy|guzzi california|commando|le ?mans|bobber ?black)\b/],

  // --- sportbikes
  ["sportbike", /\b(r ?[1367]\b|r ?1m|yzf|cbr|zx ?\d{1,2} ?r?|ninja|gsx ?r|gsxr|panigale|superleggera|supersport|rsv ?4|rsv|rs ?\d{3}|s ?1000 ?rr|f3 ?\d{3}|f4|rr\b|daytona|fireblade|hayabusa|gsx ?\d{4} ?r|zzr|sport|rc ?\d{3}|rc ?\d{2}|cbr ?\d{3,4}|ninja ?h2|h2 ?r|v4 ?s|superbike)\b/],

  // --- naked / roadster (the fallback family; last so anything above beats it)
  ["naked", /\b(mt ?\d{2}|mt ?\d{1,2}|\bz ?\d{3,4}\b|cb ?\d{3,4}|duke|street ?triple|speed ?triple|trident|monster|svartpilen|vitpilen|fz ?\d{1,2}|fz ?\d{3}|hornet|brutale|dragster|rivale|tuono|shiver|dorsoduro|naked|street ?fighter|streetfighter|gsx ?s|gs ?\d{3} ?s|\bs ?\d{3}\b|nk\b|cf ?\d{3}|vitesse|er ?\d n?|z ?h2|vmax|v ?max|ns ?\d{3}|pulsar|apache|raider ?125|gixxer|fz ?s)\b/],
];

/* ------------------------------------------------------------------ typeOf */

let TABLE = null;     // make|model -> type code, the corrections list
let COLORS = null;    // make|model -> {hex, name}
let BRANDS = null;    // make -> hex

const flat = (value) =>
  String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/** The text the rules are tested against: "<make> <model>", flattened. */
function textOf(bike) {
  if (bike && typeof bike === "object") {
    return flat([bike.make || bike.brand, bike.model || bike.name].filter(Boolean).join(" ")) || flat(bike.id);
  }
  return flat(bike);
}

function heuristic(text, make) {
  const bikeMake = BIKE_MAKES.has(foldPart(make));
  for (const [type, re] of RULES) {
    if (type === "car" && bikeMake) continue;
    if (re.test(text)) return type;
  }
  return "";
}

/**
 * The shape a make builds when nothing in the name says otherwise — better than one global
 * fallback, because "a Harley we have no rule for" is a cruiser and "a Vespa we have no rule
 * for" is a scooter, and neither is ever a naked bike.
 */
const MAKE_DEFAULT = {
  "harley-davidson": "cruiser", harley: "cruiser", indian: "cruiser", victory: "cruiser",
  vespa: "scooter", piaggio: "scooter", kymco: "scooter", sym: "scooter", lambretta: "scooter",
  niu: "scooter", vmoto: "scooter", "can-am": "touring",
  gasgas: "enduro", "gas-gas": "enduro", sherco: "trial", beta: "enduro", rieju: "enduro",
  "royal-enfield": "classic", "moto-guzzi": "classic", norton: "classic", jawa: "classic",
  ural: "classic", husqvarna: "enduro", ktm: "naked", "mv-agusta": "sportbike",
  hero: "naked", tvs: "naked", bajaj: "naked", chevrolet: "car",
};

/**
 * typeOf(bike, table?, opts?) -> one of TYPES.
 * `table` defaults to whatever ready() loaded; pass one explicitly from node scripts.
 * opts.explain: true returns {type, via} where via is "table" | "heuristic" | "fallback".
 */
export function typeOf(bike, table = TABLE, opts = {}) {
  const make = bike && typeof bike === "object" ? bike.make || bike.brand : "";
  const model = bike && typeof bike === "object" ? bike.model || bike.name : bike;
  const fromName = heuristic(textOf(bike), make);
  if (fromName) return opts.explain ? { type: fromName, via: "heuristic" } : fromName;
  const code = lookup(table, make, model);
  const fromTable = code && (TYPE_CODES[code] || (TYPES.includes(code) ? code : ""));
  if (fromTable) return opts.explain ? { type: fromTable, via: "table" } : fromTable;
  const fromMake = MAKE_DEFAULT[foldPart(make)];
  if (fromMake) return opts.explain ? { type: fromMake, via: "make" } : fromMake;
  return opts.explain ? { type: FALLBACK_TYPE, via: "fallback" } : FALLBACK_TYPE;
}

/* ------------------------------------------------------------------ model choice */

/**
 * The three models that ARE the bike rather than a stand-in for its type. Keep this list tiny:
 * every entry is a model we actually ship under store/models/<key>/model.glb.
 */
const EXACT = [
  ["corvette-c8", /\bcorvette\b|\bstingray\b|\bc8\b/],
  ["honda-cbr650r", /\bhonda\b.*\bcbr ?650\b|\bcbr ?650 ?r?\b/],
  ["yzf-2021", /\byamaha\b.*\byzf\b|\byzf ?r ?[1367]\b|\byzf\b/],
];

export function exactModelFor(bike) {
  const text = textOf(bike);
  if (!text) return null;
  for (const [key, re] of EXACT) if (re.test(text)) return key;
  return null;
}

/**
 * Generic models, per type. The value is the ordered list of keys that stand for that type;
 * `make` picks among them when a brand-matched one exists (a KTM motocrosser for a KTM), because
 * "an orange KTM-shaped bike" reads as the right bike far more than a colour swap does.
 * Filled in by web/tools/models-fetch.mjs — it rewrites GENERIC and parts.json together, so the
 * table here and the files on disk can never drift apart.
 */
export const GENERIC = {
  motocross: ["motocross"],
  enduro: ["enduro"],
  supermoto: ["supermoto"],
  sportbike: ["sportbike"],
  naked: ["naked"],
  adventure: ["adventure"],
  touring: ["touring"],
  cruiser: ["cruiser"],
  scooter: ["scooter"],
  classic: ["classic"],
  trial: ["trial"],
  minibike: ["minibike"],
  car: ["car"],
};

/** Which shipped generic belongs to which make, when one of them clearly does. */
export const GENERIC_MAKES = {};

/**
 * genericModelFor(type, bike?) -> "generic/<name>"
 * When several generics cover a type, a make match wins; otherwise the first (the best-rated
 * one, which is the order models-fetch.mjs writes them in).
 */
export function genericModelFor(type, bike) {
  const list = GENERIC[type] || GENERIC[FALLBACK_TYPE] || [];
  if (!list.length) return null;
  const make = foldPart(bike && typeof bike === "object" ? bike.make || bike.brand : "");
  if (make) {
    const preferred = list.find((name) => (GENERIC_MAKES[name] || []).includes(make));
    if (preferred) return `generic/${preferred}`;
  }
  return `generic/${list[0]}`;
}

/** Which part table a model key wants: cars and bikes name their nodes nothing alike. */
export function partsKindFor(type) {
  return type === "car" ? "car" : "bike";
}

/* ------------------------------------------------------------------ colour */

/**
 * Brand colours, the fallback when no photo of that exact bike has been measured. These are the
 * racing/livery colours a rider would name, not the logo colours: a KTM is orange, a Kawasaki is
 * lime, a BMW is the white of a GS rather than the blue of the roundel.
 */
export const BRAND_COLORS = {
  ktm: "#ff6600", kawasaki: "#4caf19", ducati: "#cc1122", yamaha: "#1b4fa8", bmw: "#e8eaec",
  honda: "#e01020", suzuki: "#1657b8", triumph: "#1c1c20", "harley-davidson": "#141416",
  "royal-enfield": "#4d5237", aprilia: "#1a1a1e", husqvarna: "#2b3138", gasgas: "#d81f26",
  "moto-guzzi": "#8a1c22", indian: "#8b1a1a", "mv-agusta": "#b81420", vespa: "#c9d4c5",
  piaggio: "#c9d4c5", benelli: "#1f6f4a", "can-am": "#f0c000", zero: "#2b2f33",
  victory: "#1a1a1c", sherco: "#1d69b4", beta: "#c2172a", hero: "#d3202a", bajaj: "#1a4fa0",
  tvs: "#1a56a8", kymco: "#0b5ea8", cfmoto: "#2a2e33", kove: "#2f3237", "qj-motor": "#25282c",
  voge: "#2a2d31", niu: "#2b2f33", cake: "#1f2226", vmoto: "#2c3035", chevrolet: "#c8102e",
};

/**
 * tintFor(bike) -> "#rrggbb" | null
 * The photo-measured colour of that exact bike if web/tools/bike-colors.py has seen one, else
 * the brand colour, else null (leave the model alone). Null matters: a tint that is a guess on
 * top of a guess is worse than the model's own paint.
 */
export function tintFor(bike) {
  const make = bike && typeof bike === "object" ? bike.make || bike.brand : "";
  const model = bike && typeof bike === "object" ? bike.model || bike.name : "";
  const hit = lookup(COLORS, make, model);
  if (hit && hit.hex) return hit.hex;
  const brand = (BRANDS || BRAND_COLORS)[foldPart(make)];
  return brand || null;
}

/** The human name of the tint, when there is one ("racing red"), for the caption. */
export function tintNameFor(bike) {
  const make = bike && typeof bike === "object" ? bike.make || bike.brand : "";
  const model = bike && typeof bike === "object" ? bike.model || bike.name : "";
  const hit = lookup(COLORS, make, model);
  return (hit && hit.name) || null;
}

/* ------------------------------------------------------------------ modelFor */

const MODEL_BASE = new URL("../../store/models/", import.meta.url);

export const urlForKey = (key) => new URL(`${key}/model.glb`, MODEL_BASE).href;

/**
 * modelFor(bike) -> the descriptor at the top of this file. Synchronous and total: it answers
 * for a string id, a half-filled record or undefined, and never throws.
 */
export function modelFor(bike) {
  const type = typeOf(bike);
  const exact = exactModelFor(bike);
  const key = exact || genericModelFor(type, bike) || "yzf-2021";
  const make = bike && typeof bike === "object" ? bike.make || bike.brand : "";
  const model = bike && typeof bike === "object" ? bike.model || bike.name : bike;
  return {
    key,
    url: urlForKey(key),
    exact: !!exact,
    type,
    // the exact models already wear the right paint; tinting one would only make it wrong
    tint: exact ? null : tintFor(bike),
    parts: partsKindFor(type),
    label: [make, model].filter(Boolean).join(" ") || String(bike ?? ""),
  };
}

/* ------------------------------------------------------------------ tables */

const TABLE_URL = new URL("../../store/bike-types.json", import.meta.url);
const COLORS_URL = new URL("../../store/bike-colors.json", import.meta.url);

let readyPromise = null;

async function grab(url) {
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/**
 * Load the lookup tables once. Resolves with {types, colors} whether or not either file exists —
 * every export above answers without them, just less precisely, so nothing awaits this to paint.
 */
export function ready() {
  if (!readyPromise) {
    readyPromise = Promise.all([grab(TABLE_URL), grab(COLORS_URL)]).then(([types, colors]) => {
      if (types && typeof types === "object") TABLE = types;
      if (colors && typeof colors === "object") {
        COLORS = colors.bikes || colors;
        BRANDS = colors.brands ? { ...BRAND_COLORS, ...colors.brands } : null;
      }
      return { types: TABLE, colors: COLORS };
    });
  }
  return readyPromise;
}

/** For node scripts and tests: hand the tables over directly instead of fetching them. */
export function useTables({ types, colors, brands } = {}) {
  if (types) TABLE = types;
  if (colors) COLORS = colors;
  if (brands) BRANDS = { ...BRAND_COLORS, ...brands };
}
