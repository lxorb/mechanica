/**
 * 3D vehicle viewer for the Pick screen. Owner: 3d agent. Ported from rexheng/hackmit@threejs
 * (web/src/bikes/assembly-scene.js + yzf-model.js): exploded view, per-part highlight, focus fit.
 *
 * Models live in ../store/models/<modelKey>/model.glb (Sketchfab, see ../store/models/CREDITS.md):
 *   yzf-2021 (Yamaha YZF, generic motorcycle fallback), honda-cbr650r, corvette-c8.
 * modelFor(bike) picks the key: Honda CBR650R -> honda-cbr650r, Chevrolet Corvette -> corvette-c8,
 * everything else -> yzf-2021. Until the real GLBs are dropped in, a procedural placeholder assembly
 * (grouped primitives with the same part keys) renders so the screen can be built and tested.
 *
 * Part keys (stable, used by the Pick screen to map manual sections -> 3D parts):
 *   front-wheel, rear-wheel, front-brake, rear-brake, front-fork, rear-shock, swingarm, chain,
 *   sprocket, engine, exhaust, radiator, fuel-tank, seat, handlebar, mirrors, headlight, taillight,
 *   battery, air-filter, frame, fairing, footpeg, clutch, oil, spark-plug, fuse, tire (alias of wheel)
 *
 * partFor(sectionTitle, keywords[]) -> part key | null   (keyword table lives here so the mapping is
 * one place; "Checking the front brake fluid level" -> front-brake, "chain tension" -> chain, ...)
 *
 * ---------------------------------------------------------------------------------------------
 * three.js loading. The module wants these bare specifiers, so index.html should carry:
 *
 *   <script type="importmap">
 *   {"imports":{
 *     "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
 *     "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
 *   }}
 *   </script>
 *
 * ...placed BEFORE <script type="module" src="js/app.js">. Until it is there this module injects
 * exactly that map itself on first mount(), and if injection is refused it falls back to the full
 * CDN URL for the three core plus a built-in orbit controller, so the viewer always runs.
 * three is loaded lazily (dynamic import on first mount), so importing this module costs nothing.
 * ---------------------------------------------------------------------------------------------
 */

const THREE_VERSION = "0.170.0";
const CDN = `https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/`;
const IMPORTS = { three: `${CDN}build/three.module.js`, "three/addons/": `${CDN}examples/jsm/` };

const ORANGE = 0xe85d04;
const DIM_OPACITY = 0.35;
const EXPLODE_MS = 400;
const FOCUS_MS = 500;
const IDLE_MS = 3000;

/* ------------------------------------------------------------------ part vocabulary */

export const PART_KEYS = [
  "front-wheel", "rear-wheel", "front-brake", "rear-brake", "front-fork", "rear-shock",
  "swingarm", "chain", "sprocket", "engine", "exhaust", "radiator", "fuel-tank", "seat",
  "handlebar", "mirrors", "headlight", "taillight", "battery", "air-filter", "frame",
  "fairing", "footpeg", "clutch", "oil", "spark-plug", "fuse", "tire",
];

export const PART_LABELS = {
  "front-wheel": "Front wheel", "rear-wheel": "Rear wheel", "front-brake": "Front brake",
  "rear-brake": "Rear brake", "front-fork": "Front forks", "rear-shock": "Rear shock",
  swingarm: "Swingarm", chain: "Drive chain", sprocket: "Sprocket", engine: "Engine",
  exhaust: "Exhaust", radiator: "Radiator", "fuel-tank": "Fuel tank", seat: "Seat",
  handlebar: "Handlebar", mirrors: "Mirrors", headlight: "Headlight", taillight: "Tail light",
  battery: "Battery", "air-filter": "Air filter", frame: "Frame", fairing: "Bodywork",
  footpeg: "Footpeg", clutch: "Clutch", oil: "Oil / filter", "spark-plug": "Spark plug",
  fuse: "Fuse", tire: "Tyre",
};

/** Keys callers may pass that are really another group. */
export const PART_ALIASES = {
  tire: "front-wheel", tyre: "front-wheel", wheel: "front-wheel", brake: "front-brake",
  fork: "front-fork", suspension: "front-fork", shock: "rear-shock", bodywork: "fairing",
  chassis: "frame", motor: "engine", tank: "fuel-tank", light: "headlight", bulb: "headlight",
};

/** When a model has no group for a key, highlight the next best thing instead of nothing. */
const FALLBACK = {
  tire: "front-wheel", oil: "engine", "spark-plug": "engine", clutch: "engine",
  "air-filter": "engine", radiator: "engine", fuse: "battery", battery: "frame",
  sprocket: "rear-wheel", chain: "rear-wheel", "rear-shock": "swingarm", swingarm: "frame",
  footpeg: "frame", mirrors: "handlebar", handlebar: "frame", taillight: "fairing",
  headlight: "fairing", "front-brake": "front-wheel", "rear-brake": "rear-wheel",
  "front-fork": "frame", seat: "fairing", "fuel-tank": "fairing", fairing: "frame",
  exhaust: "engine", frame: "engine",
};

export const MODEL_KEYS = ["yzf-2021", "honda-cbr650r", "corvette-c8"];

/* ------------------------------------------------------------------ parts tables
 * meshes: regexes tested against a GLB node's own name, its parent/group name and — for skinned
 * meshes — its joint name. The names are tried in that priority order and the first table entry
 * that matches a name wins, so a specific node name always beats a generic parent group.
 * explode: offset in normalised model units (the model is scaled so its bounding sphere radius
 * is 1), multiplied by the current spacing.
 *
 * Verified against the real Sketchfab GLBs on 2026-09-20 with
 *   node web/tools/model-check.mjs <key> --names --where
 * Both bikes are rigid skins whose joints carry the group names (chassis, bodyshell, forks_l,
 * bikedisc_f, wheel_lf.child, misc_a … misc_i). The unnamed misc_* groups were identified by
 * position + material and are pinned per model below, because misc_d means the side stand on the
 * YZF and the windscreen on the CBR. The Corvette is unskinned and every node is named
 * "<Object>_<Material>_0", so its regexes anchor on the object half.
 */

const BIKE_PARTS = [
  { key: "front-wheel", explode: [0.85, -0.10, 0], meshes: [/wheel_?lf/i, /(^|[^a-z])f(ront)?[_\- ]?(wheel|rim|tyre|tire)/i, /(wheel|rim|tyre|tire)[_\- ]?f(ront)?($|[^a-z])/i] },
  { key: "rear-wheel", explode: [-0.85, -0.10, 0], meshes: [/wheel_?lr/i, /(^|[^a-z])r(ear)?[_\- ]?(wheel|rim|tyre|tire)/i, /(wheel|rim|tyre|tire)[_\- ]?r(ear)?($|[^a-z])/i] },
  { key: "front-brake", explode: [0.75, -0.05, 0.45], meshes: [/bikedisc_?f/i, /front.{0,8}(brake|disc|disk|rotor|caliper)/i, /(brake|disc|disk|rotor|caliper).{0,8}front/i] },
  { key: "rear-brake", explode: [-0.75, -0.05, -0.45], meshes: [/bikedisc_?r/i, /rear.{0,8}(brake|disc|disk|rotor|caliper)/i, /(brake|disc|disk|rotor|caliper).{0,8}rear/i] },
  { key: "front-fork", explode: [0.55, 0.45, 0], meshes: [/forks?_[ul]/i, /\bfork/i, /triple.?clamp/i, /front.{0,8}suspension/i, /steering.?head/i] },
  { key: "rear-shock", explode: [-0.25, 0.55, 0.35], meshes: [/shock/i, /monosh/i, /rear.{0,8}(suspension|spring|damper)/i] },
  { key: "swingarm", explode: [-0.45, -0.30, 0], meshes: [/swing ?arm/i] },
  { key: "chain", explode: [-0.35, -0.10, 0.55], meshes: [/\bchain/i, /drive ?belt/i] },
  { key: "sprocket", explode: [-0.60, -0.15, 0.45], meshes: [/sprocket/i, /pinion/i] },
  { key: "radiator", explode: [0.55, -0.15, 0.40], meshes: [/misc_b/i, /radiator/i, /coolant/i, /\bcooler/i, /\bfan\b/i] },
  { key: "exhaust", explode: [-0.15, -0.35, -0.60], meshes: [/misc_c/i, /exhaust/i, /muffler/i, /silencer/i, /header/i, /\bpipe/i] },
  { key: "clutch", explode: [0.10, -0.35, 0.60], meshes: [/clutch/i] },
  { key: "spark-plug", explode: [0.25, 0.45, -0.50], meshes: [/spark/i, /\bplug\b/i, /ignition.?coil/i] },
  { key: "oil", explode: [0.20, -0.60, -0.45], meshes: [/oil/i, /\bsump\b/i] },
  { key: "air-filter", explode: [0.05, 0.60, 0.55], meshes: [/air ?(box|filter|intake|cleaner)/i, /airbox/i] },
  { key: "engine", explode: [0, -0.65, 0], meshes: [/enginecbr/i, /misc_a/i, /engine/i, /\bmotor\b/i, /crankcase/i, /cylinder/i, /gearbox/i, /transmission/i] },
  { key: "battery", explode: [-0.30, 0.45, -0.55], meshes: [/battery/i] },
  { key: "fuse", explode: [-0.45, 0.45, 0.55], meshes: [/fuse/i, /relay/i] },
  { key: "fuel-tank", explode: [0.05, 0.80, 0], meshes: [/fuel/i, /petrol/i, /gas ?tank/i, /\btank\b/i] },
  { key: "seat", explode: [-0.35, 0.70, 0], meshes: [/seat/i, /saddle/i, /pillion/i] },
  { key: "mirrors", explode: [0.35, 0.95, 0.45], meshes: [/mirror/i] },
  { key: "headlight", explode: [0.90, 0.25, 0], meshes: [/head ?li/i, /head ?la/i] },
  { key: "taillight", explode: [-0.90, 0.30, 0], meshes: [/tail ?li/i, /tail ?la/i, /rear ?li/i, /brake ?li/i, /indicator/i, /blinker/i, /turn ?signal/i] },
  { key: "handlebar", explode: [0.45, 0.75, 0], meshes: [/handle ?bar/i, /\bbars?\b/i, /\blever\b/i, /\bgrip\b/i, /throttle/i, /\bdials?\b/i, /instrument/i, /speedo/i, /dash/i, /cluster/i, /switchgear/i] },
  { key: "footpeg", explode: [-0.10, -0.45, 0.55], meshes: [/foot ?(peg|rest)/i, /\bpeg\b/i, /gear ?(lever|pedal)/i, /shift ?lever/i, /\bstand\b/i] },
  { key: "fairing", explode: [0, 0.35, -0.85], meshes: [/bodyshell/i, /bodywork/i, /fairing/i, /cowl/i, /\bpanel/i, /windscreen/i, /windshield/i, /\bscreen\b/i, /fender/i, /mudguard/i, /plate/i, /\bbody\b/i] },
  { key: "frame", explode: [0, 0, 0], meshes: [/chassis/i, /\bframe/i, /subframe/i, /\bspine\b/i] },
];

const CAR_PARTS = [
  { key: "front-wheel", explode: [0.75, -0.35, 0], meshes: [/^front (left|right) wheel/i, /front.{0,10}(wheel|rim|tyre|tire)/i] },
  { key: "rear-wheel", explode: [-0.75, -0.35, 0], meshes: [/^rear (left|right) wheel/i, /rear.{0,10}(wheel|rim|tyre|tire)/i] },
  { key: "front-brake", explode: [0.62, -0.62, 0], meshes: [/^front (left|right) brake/i, /front.{0,10}(brake|caliper|rotor)/i] },
  { key: "rear-brake", explode: [-0.62, -0.62, 0], meshes: [/^rear (left|right) brake/i, /rear.{0,10}(brake|caliper|rotor)/i] },
  { key: "front-fork", explode: [0, -0.85, 0], meshes: [/^sus ?pension/i, /control ?arm/i, /wishbone/i, /^strut/i, /^(front|rear) (left|right) (spring|damper|shock)/i] },
  { key: "mirrors", explode: [0.15, 0.5, 0.9], meshes: [/^mirror/i, /_mirror_/i, /\[mirror\]/i] },
  { key: "headlight", explode: [0.98, 0.12, 0], meshes: [/^head ?lights?/i, /^day ?lights?/i, /^fog ?lights?/i, /^drl/i] },
  { key: "taillight", explode: [-0.98, 0.12, 0], meshes: [/^tail ?lights?/i, /^brake ?lights?/i, /^reverse ?lights?/i, /^turn ?light/i, /^(left|right) indicator/i, /^licen[sc]e plate light/i] },
  { key: "handlebar", explode: [0.45, 0.4, 0], meshes: [/^steering ?wheel/i, /^speedo/i, /^gauges/i, /^interior digital/i, /^dash/i] },
  { key: "seat", explode: [0.05, 0.15, 0], meshes: [/^interior/i, /^seats?\b/i, /^carpet/i, /^(left|right) door stitches/i, /^(left|right) door_interior/i, /^roof_interior/i] },
  { key: "engine", explode: [-0.55, -0.55, 0], meshes: [/^6\.2l/i, /^engine/i, /\blt2\b/i, /^carbon ?fi?ber/i, /^intercooler/i, /^radiator/i] },
  { key: "exhaust", explode: [-0.85, -0.45, 0], meshes: [/^exhaust/i, /^muffler/i, /tailpipe/i, /catalytic/i] },
  { key: "battery", explode: [0.4, 0.55, -0.6], meshes: [/^battery/i] },
  { key: "fuse", explode: [0.55, 0.55, 0.6], meshes: [/^fuse/i, /^relay/i] },
  { key: "air-filter", explode: [-0.25, 0.7, 0.6], meshes: [/^air ?(box|filter|intake|cleaner)/i] },
  { key: "oil", explode: [0.15, -0.7, -0.5], meshes: [/^oil/i, /^sump/i] },
  { key: "fuel-tank", explode: [-0.35, -0.6, -0.6], meshes: [/^fuel/i, /^petrol/i, /^tank/i] },
  { key: "fairing", explode: [0, 0.95, 0], meshes: [/^main chassis/i, /^(left|right) door/i, /^roof/i, /^trunk/i, /^frunk/i, /^hood/i, /^grille?\s?\d*/i, /^glasses/i, /^windshield/i, /^(left|right) ?wiper/i, /^licen[sc]e plate/i, /^corvette badge/i, /^badges?/i, /^spoiler/i, /^splitter/i, /^bumper/i, /^vent/i, /^body/i] },
  { key: "frame", explode: [0, 0, 0], meshes: [/^chassis/i, /^frame/i, /^subframe/i, /bolt/i] },
];

/**
 * Per-model regexes merged in front of the shared table. The source groups these name carry no
 * meaning in the file itself — each was identified from its position and materials (see the
 * header) and they differ between the two bikes, so they cannot live in the shared table.
 */
const MODEL_EXTRA = {
  "yzf-2021": {
    headlight: [/misc_i/i, /misc_h/i],   // headlight housing; front indicator cluster (light glass)
    mirrors: [/misc_e/i],                // chrome pair, high and wide at the front
    footpeg: [/misc_d/i],                // low, left side, behind the engine: side stand + bracket
    fairing: [/misc_f/i],                // rear top: tail tidy / plate holder
  },
  "honda-cbr650r": {
    headlight: [/extralight/i],          // headlight glass + inner lens
    fairing: [/misc_d/i],                // windscreen + Honda wing badge
    handlebar: [/dials/i],               // digital instrument panel
    frame: [/misc_g/i],                  // brackets and lines running the length of the bike
  },
  "corvette-c8": {},
};

function withExtra(table, extra) {
  return table.map((part) => (extra[part.key] ? { ...part, meshes: [...extra[part.key], ...part.meshes] } : part));
}

const PARTS = {
  "yzf-2021": withExtra(BIKE_PARTS, MODEL_EXTRA["yzf-2021"]),
  "honda-cbr650r": withExtra(BIKE_PARTS, MODEL_EXTRA["honda-cbr650r"]),
  "corvette-c8": CAR_PARTS,
};

/** Every part a model key can show, in explode order. */
export function partsFor(modelKey) {
  return PARTS[modelKey] || BIKE_PARTS;
}

/**
 * Which part key a node belongs to (null = unmatched -> the catch-all group).
 * Pass the names most specific first — joint name, own name, mesh name, then parents — because
 * the first name that matches anything decides, which keeps a generic parent group from
 * swallowing a precisely named child.
 */
export function matchPart(modelKey, ...names) {
  const table = partsFor(modelKey);
  for (const name of names) {
    if (!name) continue;
    for (const part of table) {
      for (const re of part.meshes) if (re.test(name)) return part.key;
    }
  }
  return null;
}

/** Group every unmatched node lands in, so nothing is ever invisible. */
const CATCH_ALL = "frame";

/* ------------------------------------------------------------------ model + part lookup */

const flat = (value) => String(value == null ? "" : value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export function modelFor(bike) {
  const text = bike && typeof bike === "object"
    ? flat([bike.make, bike.brand, bike.model, bike.name, bike.id].filter(Boolean).join(" "))
    : flat(bike);
  if (!text) return "yzf-2021";
  if (/\bcorvette\b/.test(text) || /\bc8\b/.test(text) || /\bstingray\b/.test(text)) return "corvette-c8";
  if (/\bcbr\s?650\s?r?\b/.test(text) && /\bhonda\b/.test(text)) return "honda-cbr650r";
  if (/\bcbr\s?650\b/.test(text)) return "honda-cbr650r";
  return "yzf-2021";
}

const REAR = /\b(rear|back|pillion|tail)\b/;
const pick = (text, front, rear) => (REAR.test(text) ? rear : front);

/** Ordered — the first rule that matches wins, so specific beats generic. */
const RULES = [
  [/\bclutch\b/, "clutch"],
  [/\bchain\b|\bdrive belt\b/, "chain"],
  [/\bsprocket\b|\bpinion\b/, "sprocket"],
  [/head ?li|head ?la|high beam|low beam|main beam|\bdrl\b/, "headlight"],
  [/tail ?li|tail ?la|rear ?li|brake ?li|indicator|turn signal|blinker|hazard|licence plate light|license plate light/, "taillight"],
  [/\bbulb\b|\blamp\b|\bbeam\b/, "headlight"],
  [/\bbrakes?\b|\bbrake |\bpads?\b|\bdiscs?\b|\bdisks?\b|\brotors?\b|\bcalipers?\b/, (t) => pick(t, "front-brake", "rear-brake")],
  [/\btyres?\b|\btires?\b|\bwheels?\b|\brims?\b|\bspokes?\b|\btread\b|pressure|puncture|\bhub\b/, (t) => pick(t, "front-wheel", "rear-wheel")],
  [/swing ?arm/, "swingarm"],
  [/\bforks?\b|triple clamp|steering head|front suspension/, "front-fork"],
  [/\bshocks?\b|monosh|preload|\bdampers?\b|rear suspension|\bsprings?\b|\bsag\b|suspension/, "rear-shock"],
  [/coolant|radiator|antifreeze|cooling|water pump|thermostat/, "radiator"],
  [/spark ?plug|ignition coil|plug gap/, "spark-plug"],
  [/air ?filter|air ?box|airbox|air ?cleaner|\bintake\b|\bsnorkel\b/, "air-filter"],
  [/\bfuses?\b|\brelays?\b|fuse ?box/, "fuse"],
  [/\bbattery\b|charging|jump ?start|\bterminal\b|\bvoltage\b|\balternator\b/, "battery"],
  [/\boil\b|lubricat|\bsump\b|dipstick/, "engine"],
  [/\bmirrors?\b/, "mirrors"],
  [/foot ?peg|foot ?rest|\bpegs?\b|gear ?lever|shift ?lever|gear ?pedal|side ?stand|centre ?stand|center ?stand/, "footpeg"],
  [/handle ?bar|\blevers?\b|\bgrips?\b|throttle|steering|\bcables?\b|switchgear|instrument|\bdash\b|speedo|\bcluster\b|\bhorn\b/, "handlebar"],
  [/\bseats?\b|saddle|\bpillion\b/, "seat"],
  [/\bfuel\b|\btank\b|petrol|gasoline|filler|\bfuel cap\b/, "fuel-tank"],
  [/exhaust|muffler|silencer|\bheaders?\b|catalytic|tailpipe/, "exhaust"],
  [/\bengine\b|\bmotor\b|cylinder|valve clearance|crank|piston|gearbox|transmission|\bidle\b|throttle body|\bcoolant\b/, "engine"],
  [/\bframe\b|chassis|subframe/, "frame"],
  [/fairing|bodywork|\bcowl\b|windscreen|windshield|\bfender\b|mudguard|\bpanels?\b|\bbodywork\b/, "fairing"],
];

export function partFor(title, keywords = []) {
  const list = Array.isArray(keywords) ? keywords : keywords ? [keywords] : [];
  const text = ` ${String(title || "")} ${list.join(" ")} `.toLowerCase().replace(/[\s_/,.;:()\-]+/g, " ");
  for (const [re, out] of RULES) {
    if (re.test(text)) return typeof out === "function" ? out(text) : out;
  }
  return null;
}

/* ------------------------------------------------------------------ three.js loading */

let threePromise = null;
let mapDone = false;

function hasThreeMap() {
  for (const el of document.querySelectorAll('script[type="importmap"]')) {
    try {
      const json = JSON.parse(el.textContent || "{}");
      if (json && json.imports && json.imports.three) return true;
    } catch { /* malformed map — treat as missing */ }
  }
  return false;
}

function ensureImportMap() {
  if (mapDone || typeof document === "undefined") return;
  mapDone = true;
  if (hasThreeMap()) return;
  try {
    const el = document.createElement("script");
    el.type = "importmap";
    el.textContent = JSON.stringify({ imports: IMPORTS });
    document.head.append(el);
  } catch { /* a map is already committed; the URL fallbacks below cover it */ }
}

function loadThree() {
  if (!threePromise) {
    ensureImportMap();
    threePromise = import("three").catch(() => import(/* webpackIgnore: true */ IMPORTS.three));
  }
  return threePromise;
}

async function loadAddon(path) {
  try {
    return await import(`three/addons/${path}`);
  } catch {
    return import(IMPORTS["three/addons/"] + path);
  }
}

/* ------------------------------------------------------------------ small helpers */

const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);

function strut(THREE, a, b, radius, seg = 12) {
  const from = new THREE.Vector3(...a);
  const to = new THREE.Vector3(...b);
  const dir = to.clone().sub(from);
  const len = Math.max(dir.length(), 1e-4);
  const geometry = new THREE.CylinderGeometry(radius, radius, len, seg, 1);
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().divideScalar(len));
  geometry.applyMatrix4(new THREE.Matrix4().compose(from.clone().add(to).multiplyScalar(0.5), quaternion, new THREE.Vector3(1, 1, 1)));
  return geometry;
}

function placed(THREE, geometry, pos = [0, 0, 0], rot = [0, 0, 0]) {
  const matrix = new THREE.Matrix4().compose(
    new THREE.Vector3(...pos),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(...rot)),
    new THREE.Vector3(1, 1, 1),
  );
  geometry.applyMatrix4(matrix);
  return geometry;
}

/* ------------------------------------------------------------------ placeholder assembly
 * Same part keys as the real models, so the Pick screen can be built and demoed before the
 * Sketchfab GLBs land. x = forward (front of the bike is +x), y = up, z = lateral.
 */

function buildPlaceholder(THREE, modelKey) {
  const root = new THREE.Group();
  root.name = `placeholder:${modelKey}`;
  const groups = new Map();
  const meshes = [];
  const materials = new Set();

  const mat = (color, metalness, roughness, extra) =>
    new THREE.MeshStandardMaterial({ color, metalness, roughness, ...extra });
  const steel = mat(0x9aa2ab, 0.9, 0.3);
  const dark = mat(0x33383f, 0.55, 0.5);
  const rubber = mat(0x16181c, 0.05, 0.95);
  const paint = mat(0xe8e3d7, 0.15, 0.45);
  const glass = mat(0xfff3d6, 0.1, 0.15, { emissive: 0x6b5a2a, emissiveIntensity: 0.4 });
  const copper = mat(0xb87333, 0.85, 0.35);
  [steel, dark, rubber, paint, glass, copper].forEach((m) => materials.add(m));

  const add = (key, geometry, material) => {
    let part = groups.get(key);
    if (!part) {
      const node = new THREE.Group();
      node.name = key;
      root.add(node);
      part = { key, label: PART_LABELS[key] || key, node, meshes: [], explode: new THREE.Vector3() };
      groups.set(key, part);
    }
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = `${key}:${part.meshes.length}`;
    mesh.userData.partKey = key;
    part.node.add(mesh);
    part.meshes.push(mesh);
    meshes.push(mesh);
    return mesh;
  };

  const AX_Z = [Math.PI / 2, 0, 0]; // cylinder default axis is +Y; this points it along +Z
  const wheel = (key, x, r) => {
    add(key, placed(THREE, new THREE.TorusGeometry(r, r * 0.24, 10, 28), [x, r, 0]), rubber);
    add(key, placed(THREE, new THREE.CylinderGeometry(r * 0.66, r * 0.66, 0.1, 24), [x, r, 0], AX_Z), steel);
    for (let i = 0; i < 5; i++) {
      const a = (i / 5) * Math.PI * 2;
      add(key, placed(THREE, new THREE.BoxGeometry(r * 1.35, 0.035, 0.05), [x, r, 0], [0, 0, a]), steel);
    }
  };
  const brake = (key, x, r, side) => {
    add(key, placed(THREE, new THREE.CylinderGeometry(r * 0.58, r * 0.58, 0.014, 26), [x, r, side * 0.1], AX_Z), steel);
    add(key, placed(THREE, new THREE.BoxGeometry(0.09, 0.13, 0.07), [x - r * 0.5, r + r * 0.32, side * 0.1]), dark);
  };

  const FR = 0.7;
  const RR = -0.72;
  wheel("front-wheel", FR, 0.33);
  wheel("rear-wheel", RR, 0.33);
  brake("front-brake", FR, 0.33, 1);
  brake("rear-brake", RR, 0.33, -1);

  // forks + steering
  add("front-fork", strut(THREE, [FR, 0.33, 0.12], [0.54, 1.0, 0.12], 0.032), steel);
  add("front-fork", strut(THREE, [FR, 0.33, -0.12], [0.54, 1.0, -0.12], 0.032), steel);
  add("front-fork", strut(THREE, [0.56, 0.92, -0.16], [0.56, 0.92, 0.16], 0.03), dark);
  add("front-fork", placed(THREE, new THREE.BoxGeometry(0.1, 0.06, 0.34), [0.545, 1.02, 0]), dark);

  add("handlebar", strut(THREE, [0.5, 1.06, -0.26], [0.5, 1.06, 0.26], 0.018), steel);
  add("handlebar", placed(THREE, new THREE.CylinderGeometry(0.028, 0.028, 0.1, 14), [0.5, 1.06, 0.23], AX_Z), rubber);
  add("handlebar", placed(THREE, new THREE.CylinderGeometry(0.028, 0.028, 0.1, 14), [0.5, 1.06, -0.23], AX_Z), rubber);
  add("handlebar", placed(THREE, new THREE.BoxGeometry(0.13, 0.08, 0.16), [0.45, 1.11, 0], [-0.5, 0, 0]), dark);

  add("mirrors", strut(THREE, [0.48, 1.09, 0.2], [0.44, 1.24, 0.3], 0.012), dark);
  add("mirrors", placed(THREE, new THREE.BoxGeometry(0.03, 0.08, 0.13), [0.43, 1.26, 0.31]), steel);
  add("mirrors", strut(THREE, [0.48, 1.09, -0.2], [0.44, 1.24, -0.3], 0.012), dark);
  add("mirrors", placed(THREE, new THREE.BoxGeometry(0.03, 0.08, 0.13), [0.43, 1.26, -0.31]), steel);

  // frame + body
  add("frame", strut(THREE, [0.52, 0.95, 0.1], [-0.12, 0.72, 0.16], 0.036), steel);
  add("frame", strut(THREE, [0.52, 0.95, -0.1], [-0.12, 0.72, -0.16], 0.036), steel);
  add("frame", strut(THREE, [-0.12, 0.72, 0.16], [-0.12, 0.42, 0.14], 0.032), steel);
  add("frame", strut(THREE, [-0.12, 0.72, -0.16], [-0.12, 0.42, -0.14], 0.032), steel);
  add("frame", strut(THREE, [-0.12, 0.72, 0], [-0.55, 0.78, 0], 0.028), steel);

  add("fuel-tank", placed(THREE, new THREE.CapsuleGeometry(0.19, 0.3, 6, 18), [0.14, 0.92, 0], [0, 0, Math.PI / 2]), paint);
  add("seat", placed(THREE, new THREE.BoxGeometry(0.44, 0.09, 0.26), [-0.3, 0.87, 0], [0, 0, 0.06]), dark);
  add("seat", placed(THREE, new THREE.BoxGeometry(0.2, 0.1, 0.2), [-0.58, 0.9, 0], [0, 0, 0.18]), dark);

  add("fairing", placed(THREE, new THREE.BoxGeometry(0.3, 0.42, 0.04), [0.52, 0.74, 0.17], [0, 0.22, -0.2]), paint);
  add("fairing", placed(THREE, new THREE.BoxGeometry(0.3, 0.42, 0.04), [0.52, 0.74, -0.17], [0, -0.22, -0.2]), paint);
  add("fairing", placed(THREE, new THREE.BoxGeometry(0.26, 0.1, 0.3), [0.68, 0.62, 0]), paint);
  add("fairing", placed(THREE, new THREE.BoxGeometry(0.3, 0.06, 0.24), [-0.66, 0.84, 0], [0, 0, 0.16]), paint);
  add("fairing", placed(THREE, new THREE.CylinderGeometry(0.2, 0.26, 0.05, 18, 1, false, 0, Math.PI), [FR, 0.62, 0], [Math.PI / 2, 0, 0]), paint);

  // powertrain
  add("engine", placed(THREE, new THREE.BoxGeometry(0.34, 0.3, 0.3), [0.06, 0.52, 0]), dark);
  add("engine", placed(THREE, new THREE.BoxGeometry(0.26, 0.22, 0.26), [0.16, 0.72, 0], [0, 0, -0.5]), dark);
  for (let i = 0; i < 4; i++) {
    add("engine", placed(THREE, new THREE.BoxGeometry(0.03, 0.2, 0.28), [0.08 + i * 0.05, 0.68, 0], [0, 0, -0.5]), steel);
  }
  add("clutch", placed(THREE, new THREE.CylinderGeometry(0.11, 0.11, 0.06, 20), [0.02, 0.5, 0.17], AX_Z), steel);
  add("oil", placed(THREE, new THREE.CylinderGeometry(0.055, 0.055, 0.1, 16), [0.2, 0.42, 0.06], [0, 0, 0.4]), copper);
  add("oil", placed(THREE, new THREE.BoxGeometry(0.28, 0.06, 0.24), [0.05, 0.36, 0]), steel);
  add("spark-plug", placed(THREE, new THREE.CylinderGeometry(0.018, 0.018, 0.09, 10), [0.27, 0.8, 0.07], [0, 0, -0.5]), steel);
  add("spark-plug", placed(THREE, new THREE.CylinderGeometry(0.018, 0.018, 0.09, 10), [0.27, 0.8, -0.07], [0, 0, -0.5]), steel);
  add("radiator", placed(THREE, new THREE.BoxGeometry(0.05, 0.28, 0.28), [0.34, 0.6, 0]), steel);
  add("air-filter", placed(THREE, new THREE.BoxGeometry(0.22, 0.12, 0.24), [0.02, 0.76, 0]), dark);
  add("exhaust", strut(THREE, [0.22, 0.42, 0.06], [-0.2, 0.32, 0.12], 0.028), steel);
  add("exhaust", strut(THREE, [-0.2, 0.32, 0.12], [-0.62, 0.5, 0.16], 0.03), steel);
  add("exhaust", placed(THREE, new THREE.CylinderGeometry(0.075, 0.09, 0.3, 18), [-0.74, 0.55, 0.17], [0, 0, -1.2]), steel);

  // running gear
  add("swingarm", strut(THREE, [-0.18, 0.44, 0.13], [RR, 0.33, 0.13], 0.03), steel);
  add("swingarm", strut(THREE, [-0.18, 0.44, -0.13], [RR, 0.33, -0.13], 0.03), steel);
  add("rear-shock", strut(THREE, [-0.2, 0.46, 0], [-0.3, 0.78, 0], 0.026), dark);
  add("rear-shock", placed(THREE, new THREE.CylinderGeometry(0.05, 0.05, 0.16, 14), [-0.25, 0.62, 0], [0, 0, 0.3]), steel);
  add("sprocket", placed(THREE, new THREE.CylinderGeometry(0.13, 0.13, 0.02, 22), [RR, 0.33, 0.13], AX_Z), steel);
  add("sprocket", placed(THREE, new THREE.CylinderGeometry(0.06, 0.06, 0.02, 16), [-0.14, 0.44, 0.13], AX_Z), steel);
  add("chain", placed(THREE, new THREE.BoxGeometry(0.6, 0.02, 0.03), [-0.43, 0.45, 0.13]), dark);
  add("chain", placed(THREE, new THREE.BoxGeometry(0.6, 0.02, 0.03), [-0.43, 0.22, 0.13]), dark);
  add("chain", placed(THREE, new THREE.TorusGeometry(0.115, 0.014, 6, 20, Math.PI), [RR, 0.33, 0.13], [0, 0, -Math.PI / 2]), dark);
  add("footpeg", placed(THREE, new THREE.CylinderGeometry(0.018, 0.018, 0.11, 10), [-0.16, 0.34, 0.2], AX_Z), steel);
  add("footpeg", placed(THREE, new THREE.CylinderGeometry(0.018, 0.018, 0.11, 10), [-0.16, 0.34, -0.2], AX_Z), steel);

  // electrics + lights
  add("battery", placed(THREE, new THREE.BoxGeometry(0.14, 0.12, 0.1), [-0.22, 0.68, -0.05]), dark);
  add("fuse", placed(THREE, new THREE.BoxGeometry(0.07, 0.05, 0.06), [-0.34, 0.7, 0.05]), copper);
  add("headlight", placed(THREE, new THREE.SphereGeometry(0.11, 18, 12, 0, Math.PI * 2, 0, Math.PI / 2), [0.76, 0.84, 0], [0, 0, -Math.PI / 2]), glass);
  add("taillight", placed(THREE, new THREE.BoxGeometry(0.06, 0.05, 0.14), [-0.76, 0.82, 0]), glass);

  return finishModel(THREE, { root, groups, meshes, materials, modelKey, placeholder: true });
}

/* ------------------------------------------------------------------ GLB loading */

/**
 * Freeze a rigid skin at its imported pose (ported from the reference yzf-model.js).
 * Both bike models are rigid skins: every vertex of a mesh is bound to one joint at full weight,
 * and the joint is what carries the part name. Quantised weights come back as 0.999…, so the
 * dominant joint decides rather than an exact 1.0, and a mesh is never dropped.
 */
function bakeRigid(THREE, mesh) {
  const geometry = mesh.geometry.clone();
  const transform = mesh.matrixWorld.clone();
  if (mesh.isSkinnedMesh && mesh.skeleton) {
    const indices = geometry.getAttribute("skinIndex");
    const weights = geometry.getAttribute("skinWeight");
    const votes = new Map();
    for (let i = 0; i < weights.count; i++) {
      let best = -1;
      let bestWeight = 0;
      for (let k = 0; k < 4; k++) {
        const weight = weights.getComponent(i, k);
        if (weight <= bestWeight) continue;
        bestWeight = weight;
        best = indices.getComponent(i, k);
      }
      if (best >= 0) votes.set(best, (votes.get(best) || 0) + 1);
    }
    let joint = -1;
    let top = 0;
    for (const [index, count] of votes) if (count > top) { top = count; joint = index; }
    const bone = joint >= 0 ? mesh.skeleton.bones[joint] : null;
    if (bone) {
      const skin = new THREE.Matrix4().multiplyMatrices(bone.matrixWorld, mesh.skeleton.boneInverses[joint]);
      transform.multiply(mesh.bindMatrixInverse).multiply(skin).multiply(mesh.bindMatrix);
      geometry.userData.sourceJoint = bone.userData.name || bone.name;
    }
    geometry.deleteAttribute("skinIndex");
    geometry.deleteAttribute("skinWeight");
  }
  geometry.applyMatrix4(transform);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

async function loadGlb(THREE, modelKey, url, onProgress) {
  const [{ GLTFLoader }, meshopt] = await Promise.all([
    loadAddon("loaders/GLTFLoader.js"),
    loadAddon("libs/meshopt_decoder.module.js").catch(() => null),
  ]);
  const loader = new GLTFLoader();
  if (meshopt && meshopt.MeshoptDecoder) loader.setMeshoptDecoder(meshopt.MeshoptDecoder);
  const gltf = await loader.loadAsync(url, onProgress);

  const root = new THREE.Group();
  root.name = modelKey;
  const groups = new Map();
  const meshes = [];
  const materials = new Set();
  const sources = new Set();

  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    sources.add(object.geometry);
    const geometry = bakeRigid(THREE, object);
    if (!geometry) return;
    const names = [
      object.name,
      object.userData && object.userData.name,
      geometry.userData.sourceJoint,
      object.parent && (object.parent.name || (object.parent.userData && object.parent.userData.name)),
    ];
    const key = matchPart(modelKey, ...names) || CATCH_ALL;
    let part = groups.get(key);
    if (!part) {
      const node = new THREE.Group();
      node.name = key;
      root.add(node);
      part = { key, label: PART_LABELS[key] || key, node, meshes: [], explode: new THREE.Vector3() };
      groups.set(key, part);
    }
    const mesh = new THREE.Mesh(geometry, object.material);
    mesh.name = object.name;
    mesh.userData.partKey = key;
    mesh.userData.sourceName = names.filter(Boolean).join(" / ");
    part.node.add(mesh);
    part.meshes.push(mesh);
    meshes.push(mesh);
    for (const material of [].concat(object.material)) materials.add(material);
  });
  sources.forEach((geometry) => geometry.dispose());
  const skeletons = new Set();
  gltf.scene.traverse((object) => { if (object.skeleton) skeletons.add(object.skeleton); });
  skeletons.forEach((skeleton) => skeleton.dispose());
  if (!meshes.length) throw new Error("empty model");

  // the source models face -x; turn them so the front is +x like the placeholder
  const orient = new THREE.Matrix4().makeRotationY(-Math.PI / 2);
  meshes.forEach((mesh) => mesh.geometry.applyMatrix4(orient));
  return finishModel(THREE, { root, groups, meshes, materials, modelKey, placeholder: false });
}

/** Normalise to a unit bounding sphere at the origin and attach explode vectors + bounds. */
function finishModel(THREE, model) {
  const { THREE: _ignored, ...rest } = model;
  void _ignored;
  void rest;
  model.root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(model.root);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const scale = 2 / Math.max(size.length(), 1e-4);
  const matrix = new THREE.Matrix4()
    .makeTranslation(-center.x * scale, -center.y * scale, -center.z * scale)
    .multiply(new THREE.Matrix4().makeScale(scale, scale, scale));
  model.meshes.forEach((mesh) => {
    mesh.applyMatrix4(matrix);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.originalMaterial = mesh.material;
  });
  model.root.updateMatrixWorld(true);

  const table = partsFor(model.modelKey);
  const order = new Map(table.map((part, i) => [part.key, i]));
  for (const part of model.groups.values()) {
    const entry = table.find((row) => row.key === part.key);
    part.explode.set(...(entry ? entry.explode : [0, 0, 0]));
    part.bounds = new THREE.Box3().setFromObject(part.node);
    part.center = part.bounds.getCenter(new THREE.Vector3());
    if (!entry && part.center.lengthSq() > 0) part.explode.copy(part.center).multiplyScalar(1.4);
    part.order = order.has(part.key) ? order.get(part.key) : 99;
  }
  const bounds = new THREE.Box3().setFromObject(model.root);
  model.size = bounds.getSize(new THREE.Vector3());
  model.floor = bounds.min.y;
  model.radius = Math.max(bounds.getBoundingSphere(new THREE.Sphere()).radius, 1e-3);
  return model;
}

function disposeModel(model) {
  const textures = new Set();
  model.meshes.forEach((mesh) => mesh.geometry.dispose());
  model.materials.forEach((material) => {
    for (const value of Object.values(material)) if (value && value.isTexture) textures.add(value);
    material.dispose();
  });
  textures.forEach((texture) => texture.dispose());
  model.groups.clear();
  model.meshes.length = 0;
}

/* ------------------------------------------------------------------ environment + shadow */

function studioEnvironment(THREE, renderer) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const sky = ctx.createLinearGradient(0, 0, 0, 64);
  sky.addColorStop(0, "#ffffff");
  sky.addColorStop(0.45, "#cfd6de");
  sky.addColorStop(0.55, "#8c9099");
  sky.addColorStop(1, "#33363b");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, 128, 64);
  const key = ctx.createRadialGradient(34, 14, 1, 34, 14, 26);
  key.addColorStop(0, "rgba(255,255,255,1)");
  key.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = key;
  ctx.fillRect(0, 0, 128, 64);
  const rim = ctx.createRadialGradient(104, 22, 1, 104, 22, 22);
  rim.addColorStop(0, "rgba(255,226,196,0.85)");
  rim.addColorStop(1, "rgba(255,226,196,0)");
  ctx.fillStyle = rim;
  ctx.fillRect(0, 0, 128, 64);

  const texture = new THREE.CanvasTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const target = pmrem.fromEquirectangular(texture);
  pmrem.dispose();
  texture.dispose();
  return target;
}

function contactShadow(THREE, y, radius) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d");
  const grad = ctx.createRadialGradient(64, 64, 2, 64, 64, 62);
  grad.addColorStop(0, "rgba(20,20,20,0.5)");
  grad.addColorStop(0.55, "rgba(20,20,20,0.2)");
  grad.addColorStop(1, "rgba(20,20,20,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(radius * 3.1, radius * 1.9),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, opacity: 0.9 }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = y - radius * 0.01;
  mesh.renderOrder = -1;
  return mesh;
}

/* ------------------------------------------------------------------ fallback orbit control
 * Only used if three/addons cannot be resolved at all (no import map and the injected one was
 * refused). Same subset of the OrbitControls API this module touches.
 */

function miniOrbit(THREE, camera, dom) {
  const target = new THREE.Vector3();
  const spherical = new THREE.Spherical();
  const delta = { theta: 0, phi: 0 };
  const listeners = { start: [], end: [] };
  let zoom = 1;
  let drag = null;
  let pinch = 0;
  const api = {
    target, enableDamping: true, dampingFactor: 0.08, autoRotate: false, autoRotateSpeed: 0.6,
    minDistance: 0.4, maxDistance: 30, enabled: true,
    addEventListener: (name, fn) => listeners[name] && listeners[name].push(fn),
    update() {
      const offset = camera.position.clone().sub(target);
      spherical.setFromVector3(offset);
      if (api.autoRotate) spherical.theta -= (api.autoRotateSpeed / 60) * 0.1;
      spherical.theta += delta.theta;
      spherical.phi = Math.max(0.08, Math.min(Math.PI - 0.08, spherical.phi + delta.phi));
      spherical.radius = Math.max(api.minDistance, Math.min(api.maxDistance, spherical.radius * zoom));
      delta.theta *= 1 - api.dampingFactor * 3;
      delta.phi *= 1 - api.dampingFactor * 3;
      zoom += (1 - zoom) * 0.25;
      camera.position.copy(target).add(new THREE.Vector3().setFromSpherical(spherical));
      camera.lookAt(target);
      return true;
    },
    dispose() {
      dom.removeEventListener("pointerdown", down);
      dom.removeEventListener("pointermove", move);
      dom.removeEventListener("pointerup", up);
      dom.removeEventListener("wheel", wheel);
      dom.removeEventListener("touchmove", touch);
    },
  };
  const fire = (name) => listeners[name].forEach((fn) => fn());
  function down(event) {
    if (!api.enabled || event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY, id: event.pointerId };
    fire("start");
  }
  function move(event) {
    if (!drag || drag.id !== event.pointerId) return;
    delta.theta -= ((event.clientX - drag.x) / dom.clientWidth) * 3.2;
    delta.phi -= ((event.clientY - drag.y) / dom.clientHeight) * 2.4;
    drag.x = event.clientX;
    drag.y = event.clientY;
  }
  function up() { if (drag) { drag = null; fire("end"); } }
  function wheel(event) {
    if (!api.enabled) return;
    event.preventDefault();
    zoom = 1 + Math.sign(event.deltaY) * 0.12;
    fire("start");
    fire("end");
  }
  function touch(event) {
    if (event.touches.length !== 2) return;
    const dist = Math.hypot(event.touches[0].clientX - event.touches[1].clientX, event.touches[0].clientY - event.touches[1].clientY);
    if (pinch) zoom = 1 + (pinch - dist) / 400;
    pinch = dist;
    fire("start");
  }
  dom.addEventListener("pointerdown", down);
  dom.addEventListener("pointermove", move);
  dom.addEventListener("pointerup", up);
  dom.addEventListener("pointercancel", up);
  dom.addEventListener("wheel", wheel, { passive: false });
  dom.addEventListener("touchmove", touch, { passive: true });
  dom.addEventListener("touchend", () => { pinch = 0; });
  return api;
}

/* ------------------------------------------------------------------ mount */

/**
 * mount(host, modelKey, opts) -> viewer
 *   host: an element the canvas fills (absolute/sticky positioning is the screen's job)
 *   opts: { onReady(), onSelect(partKey), placeholder: boolean }
 * viewer:
 *   explode(on: boolean, spacing = 1)  // exploded view, animated 400 ms
 *   highlight(partKey | null)          // emissive highlight on that part, others dimmed
 *   focus(partKey)                     // highlight + camera fit with slight zoom (animated)
 *   reset()                            // collapse, clear highlight, default camera
 *   resize()
 *   dispose()
 */
export function mount(host, modelKey, opts = {}) {
  const key = MODEL_KEYS.includes(modelKey) ? modelKey : "yzf-2021";
  const wish = { exploded: false, spacing: 1, part: null, focused: false, xray: !!opts.xray };
  let live = null;
  let dead = false;

  host.classList.add("viewer3d");
  host.setAttribute("data-viewer3d", "loading");
  host.setAttribute("data-model", key);

  boot().then((scene) => {
    if (dead) { scene.dispose(); return; }
    live = scene;
    host.setAttribute("data-viewer3d", scene.model.placeholder ? "placeholder" : "ready");
    if (wish.exploded) scene.explode(true, wish.spacing, true);
    if (wish.part) scene.highlight(wish.part);
    if (wish.focused && wish.part) scene.focus(wish.part);
    if (wish.xray) scene.xray(true);
    if (typeof opts.onReady === "function") opts.onReady(api);
  }).catch((error) => {
    host.setAttribute("data-viewer3d", "error");
    if (typeof opts.onError === "function") opts.onError(error);
    else console.warn("viewer3d: could not start", error);
  });

  async function boot() {
    const THREE = await loadThree();
    let model = null;
    if (!opts.placeholder) {
      try {
        model = await loadGlb(THREE, key, opts.url || new URL(`../../store/models/${key}/model.glb`, import.meta.url).href);
      } catch { model = null; }
    }
    if (!model) model = buildPlaceholder(THREE, key);
    if (dead) { disposeModel(model); throw new Error("disposed"); }
    return createScene(THREE, host, model, opts);
  }

  const api = {
    modelKey: key,
    get ready() { return !!live; },
    parts() { return live ? [...live.model.groups.keys()] : partsFor(key).map((part) => part.key); },
    explode(on, spacing = 1) {
      wish.exploded = !!on;
      wish.spacing = Number.isFinite(spacing) ? Math.max(0, spacing) : 1;
      if (live) live.explode(wish.exploded, wish.spacing);
      return api;
    },
    highlight(partKey) {
      wish.part = partKey || null;
      wish.focused = false;
      if (live) live.highlight(wish.part);
      return api;
    },
    focus(partKey) {
      wish.part = partKey || null;
      wish.focused = !!partKey;
      if (live) live.focus(wish.part);
      return api;
    },
    xray(on) {
      wish.xray = !!on;
      if (live) live.xray(wish.xray);
      return api;
    },
    reset() {
      wish.exploded = false;
      wish.spacing = 1;
      wish.part = null;
      wish.focused = false;
      wish.xray = false;
      if (live) live.reset();
      return api;
    },
    capture() { return live ? live.capture() : null; },
    state() { return live ? live.state() : { ready: false, model: key, ...wish }; },
    resize() { if (live) live.resize(); return api; },
    dispose() {
      dead = true;
      host.removeAttribute("data-viewer3d");
      host.removeAttribute("data-model");
      host.classList.remove("viewer3d");
      if (live) { live.dispose(); live = null; }
    },
  };
  return api;
}

/* ------------------------------------------------------------------ the scene itself */

function createScene(THREE, host, model, opts) {
  const scene = new THREE.Scene();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearAlpha(0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.domElement.className = "viewer3d-canvas";
  host.append(renderer.domElement);

  const camera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
  scene.add(model.root);

  const environment = studioEnvironment(THREE, renderer);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.75;

  const hemi = new THREE.HemisphereLight(0xffffff, 0x6b6257, 1.5);
  scene.add(hemi);
  const keyLight = new THREE.DirectionalLight(0xfff4e6, 2.6);
  keyLight.position.set(2.4, 3.6, 2.8);
  scene.add(keyLight);
  const rim = new THREE.DirectionalLight(0xbcd2ff, 1.8);
  rim.position.set(-2.8, 1.6, -2.4);
  scene.add(rim);
  const fill = new THREE.DirectionalLight(0xffffff, 0.7);
  fill.position.set(0.4, -1.8, 1.6);
  scene.add(fill);

  const shadow = contactShadow(THREE, model.floor, model.radius);
  scene.add(shadow);

  let controls = null;
  let controlsDispose = null;

  // materials: one highlight clone and one dim clone per source material
  const hlMaterials = new Map();
  const dimMaterials = new Map();
  for (const material of model.materials) {
    const hl = material.clone();
    if (hl.emissive) { hl.emissive.setHex(ORANGE); hl.emissiveIntensity = 0.55; }
    if (hl.color) hl.color.lerp(new THREE.Color(ORANGE), 0.18);
    hlMaterials.set(material, hl);
    const dim = material.clone();
    dim.transparent = true;
    dim.opacity = DIM_OPACITY;
    dim.depthWrite = false;
    dimMaterials.set(material, dim);
  }
  const xrayMaterial = new THREE.MeshBasicMaterial({
    color: 0x6f7885, transparent: true, opacity: 0.12, depthWrite: false,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });

  let selected = null;
  let xrayOn = false;
  let spacing = 0;
  let spacingTween = null;
  let cameraTween = null;
  let dimTarget = 0;
  let dimNow = 0;
  let idle = 0;
  let visible = true;
  let onScreen = true;
  let frame = 0;
  let disposed = false;
  let lastTime = performance.now();

  const reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  const tmpBox = new THREE.Box3();
  const tmpSphere = new THREE.Sphere();
  const tmpVec = new THREE.Vector3();
  const HOME = new THREE.Vector3(1.35, 0.72, 2.1).normalize();

  function pickGroup(partKey) {
    if (!partKey) return null;
    const seen = new Set();
    let key = PART_ALIASES[partKey] || partKey;
    while (key && !seen.has(key)) {
      if (model.groups.has(key)) return model.groups.get(key);
      seen.add(key);
      key = FALLBACK[key];
    }
    return null;
  }

  function paint() {
    const active = selected ? selected.key : null;
    for (const mesh of model.meshes) {
      const original = mesh.userData.originalMaterial;
      if (!active) { mesh.material = original; continue; }
      if (mesh.userData.partKey === active) { mesh.material = mapMaterial(original, hlMaterials); continue; }
      mesh.material = xrayOn ? xrayMaterial : mapMaterial(original, dimMaterials);
    }
    host.setAttribute("data-part", active || "");
  }

  function mapMaterial(original, table) {
    if (Array.isArray(original)) return original.map((m) => table.get(m) || m);
    return table.get(original) || original;
  }

  function boxFor(group) {
    model.root.updateMatrixWorld(true);
    if (group) return tmpBox.setFromObject(group.node).clone();
    return tmpBox.setFromObject(model.root).clone();
  }

  /**
   * Frame a box exactly: every corner is pushed against the frustum walls rather than fitting the
   * bounding sphere, which on something as long and thin as a motorcycle would leave the model at
   * a third of the frame. Works for any orbit direction and any aspect, so 390x844 and 1280x800
   * both come out filled.
   */
  function fit(box, { instant = false, zoom = 1.08, duration = FOCUS_MS } = {}) {
    const center = box.getCenter(new THREE.Vector3());
    const forward = (controls && camera.position.distanceToSquared(controls.target) > 1e-6
      ? camera.position.clone().sub(controls.target)
      : HOME.clone()).normalize();
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), forward);
    if (right.lengthSq() < 1e-8) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(forward, right).normalize();
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const tanH = tanV * Math.max(camera.aspect, 0.2);
    let distance = 0;
    for (let i = 0; i < 8; i++) {
      tmpVec.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(center);
      const depth = tmpVec.dot(forward);
      distance = Math.max(distance, depth + Math.abs(tmpVec.dot(right)) / tanH, depth + Math.abs(tmpVec.dot(up)) / tanV);
    }
    distance = Math.max(distance * zoom, 0.05);
    const to = forward.clone().multiplyScalar(distance).add(center);
    if (instant || !controls || reduced.matches) {
      camera.position.copy(to);
      if (controls) { controls.target.copy(center); controls.update(); }
      else camera.lookAt(center);
      return;
    }
    cameraTween = {
      start: performance.now(), duration,
      from: camera.position.clone(), to,
      targetFrom: controls.target.clone(), targetTo: center,
    };
  }

  const scene3d = {
    model,
    explode(on, amount = 1, instant = false) {
      const to = on ? amount : 0;
      if (instant || reduced.matches) { spacing = to; spacingTween = null; applySpacing(); host.setAttribute("data-exploded", on ? "on" : "off"); return; }
      spacingTween = { start: performance.now(), from: spacing, to, duration: EXPLODE_MS };
      host.setAttribute("data-exploded", on ? "on" : "off");
    },
    highlight(partKey) {
      selected = pickGroup(partKey);
      dimTarget = selected ? 1 : 0;
      paint();
    },
    focus(partKey) {
      scene3d.highlight(partKey);
      fit(selected ? boxFor(selected) : boxFor(null), { zoom: selected ? 1.02 : 1.08 });
      touch();
    },
    xray(on) { xrayOn = !!on; paint(); },
    reset() {
      selected = null;
      dimTarget = 0;
      xrayOn = false;
      scene3d.explode(false);
      paint();
      host.setAttribute("data-exploded", "off");
      camera.position.copy(HOME);
      if (controls) controls.target.set(0, 0, 0);
      fit(boxFor(null), { duration: FOCUS_MS });
    },
    resize,
    capture() { renderer.render(scene, camera); return renderer.domElement.toDataURL("image/png"); },
    state() {
      return {
        ready: true, model: model.modelKey, placeholder: !!model.placeholder,
        part: selected ? selected.key : null, spacing, xray: xrayOn,
        parts: [...model.groups.keys()], meshes: model.meshes.length,
      };
    },
    dispose,
  };

  function applySpacing() {
    for (const part of model.groups.values()) part.node.position.copy(part.explode).multiplyScalar(spacing);
  }

  /* ---- sizing */
  let lastWidth = 0;
  let lastHeight = 0;
  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height || (width === lastWidth && height === lastHeight)) return;
    lastWidth = width;
    lastHeight = height;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    if (!cameraTween) fit(selected ? boxFor(selected) : boxFor(null), { instant: true, zoom: selected ? 1.02 : 1.08 });
  }
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);

  /* ---- render gating */
  const intersectionObserver = new IntersectionObserver((entries) => {
    onScreen = entries.some((entry) => entry.isIntersecting);
    if (onScreen) run();
  }, { threshold: 0.01 });
  intersectionObserver.observe(host);
  const onVisibility = () => {
    visible = !document.hidden;
    if (visible) run();
  };
  document.addEventListener("visibilitychange", onVisibility);

  /* ---- interaction */
  function touch() { idle = 0; if (controls) controls.autoRotate = false; }
  let down = null;
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const onDown = (event) => {
    cameraTween = null;
    touch();
    down = event.button === 0 ? { x: event.clientX, y: event.clientY, id: event.pointerId } : null;
  };
  const onUp = (event) => {
    const start = down;
    down = null;
    touch();
    if (!start || start.id !== event.pointerId) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(model.meshes, false)[0];
    const key = hit ? hit.object.userData.partKey : null;
    scene3d.highlight(key);
    if (typeof opts.onSelect === "function") opts.onSelect(key);
  };
  renderer.domElement.addEventListener("pointerdown", onDown);
  renderer.domElement.addEventListener("pointerup", onUp);
  renderer.domElement.addEventListener("wheel", touch, { passive: true });
  renderer.domElement.addEventListener("touchstart", touch, { passive: true });

  /* ---- loop */
  function step(now) {
    frame = 0;
    if (disposed) return;
    const dt = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;

    if (spacingTween) {
      const t = clamp01((now - spacingTween.start) / spacingTween.duration);
      spacing = spacingTween.from + (spacingTween.to - spacingTween.from) * easeOut(t);
      if (t === 1) spacingTween = null;
      applySpacing();
    }
    if (cameraTween && controls) {
      const t = clamp01((now - cameraTween.start) / cameraTween.duration);
      const eased = easeInOut(t);
      camera.position.lerpVectors(cameraTween.from, cameraTween.to, eased);
      controls.target.lerpVectors(cameraTween.targetFrom, cameraTween.targetTo, eased);
      if (t === 1) cameraTween = null;
    }
    if (Math.abs(dimNow - dimTarget) > 0.001) {
      dimNow += (dimTarget - dimNow) * Math.min(1, dt * 9);
      const opacity = 1 - (1 - DIM_OPACITY) * dimNow;
      dimMaterials.forEach((material) => { material.opacity = opacity; });
      xrayMaterial.opacity = 0.12 * dimNow;
    }

    idle += dt * 1000;
    if (controls && !cameraTween && !reduced.matches && idle > IDLE_MS && !down) controls.autoRotate = true;
    if (controls) controls.update();
    renderer.render(scene, camera);
    if (visible && onScreen) frame = requestAnimationFrame(step);
  }
  function run() {
    if (disposed || frame || !visible || !onScreen) return;
    lastTime = performance.now();
    frame = requestAnimationFrame(step);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (frame) cancelAnimationFrame(frame);
    resizeObserver.disconnect();
    intersectionObserver.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    renderer.domElement.removeEventListener("pointerdown", onDown);
    renderer.domElement.removeEventListener("pointerup", onUp);
    renderer.domElement.removeEventListener("wheel", touch);
    renderer.domElement.removeEventListener("touchstart", touch);
    if (controlsDispose) controlsDispose();
    hlMaterials.forEach((material) => material.dispose());
    dimMaterials.forEach((material) => material.dispose());
    xrayMaterial.dispose();
    shadow.geometry.dispose();
    shadow.material.map.dispose();
    shadow.material.dispose();
    environment.dispose();
    disposeModel(model);
    renderer.dispose();
    renderer.domElement.remove();
    host.removeAttribute("data-part");
    host.removeAttribute("data-exploded");
  }

  /* ---- controls come from an addon; start rendering either way */
  resize();
  fit(boxFor(null), { instant: true });
  host.setAttribute("data-exploded", "off");
  run();

  loadAddon("controls/OrbitControls.js").then(({ OrbitControls }) => {
    if (disposed) return;
    const made = new OrbitControls(camera, renderer.domElement);
    made.enableDamping = true;
    made.dampingFactor = 0.08;
    made.autoRotateSpeed = 0.6;
    made.enablePan = false;
    made.minDistance = model.radius * 0.6;
    made.maxDistance = model.radius * 12;
    made.maxPolarAngle = Math.PI * 0.92;
    made.addEventListener("start", touch);
    made.addEventListener("end", touch);
    made.target.set(0, 0, 0);
    controls = made;
    controlsDispose = () => made.dispose();
    fit(boxFor(null), { instant: true });
  }).catch(() => {
    if (disposed) return;
    const made = miniOrbit(THREE, camera, renderer.domElement);
    made.minDistance = model.radius * 0.6;
    made.maxDistance = model.radius * 12;
    made.addEventListener("start", touch);
    controls = made;
    controlsDispose = () => made.dispose();
    fit(boxFor(null), { instant: true });
  });

  if (opts.debug && typeof window !== "undefined") window.__viewer3d = { scene, camera, renderer, model, get controls() { return controls; } };

  return scene3d;
}
