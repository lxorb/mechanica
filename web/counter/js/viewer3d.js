/**
 * 3D vehicle viewer for the Pick screen. Owner: vehicle-models agent (was: 3d agent). Ported from
 * rexheng/hackmit@threejs (web/src/bikes/assembly-scene.js + yzf-model.js): exploded view,
 * per-part highlight, focus fit.
 *
 * Models live in ../store/models/<modelKey>/model.glb (Sketchfab, see ../store/models/CREDITS.md).
 * There are two kinds:
 *   - EXACT, the bike itself:  yzf-2021, honda-cbr650r, corvette-c8
 *   - GENERIC, one per vehicle type: generic/<name>, e.g. generic/motocross, generic/scooter
 * Which one a bike gets is not decided here — ./vehicle-type.js owns that, because classifying
 * 22.3k bikes is a data problem, not a rendering one. This module re-exports its `modelFor(bike)`
 * so callers keep the one import they had:
 *
 *   modelFor(bike) -> { key, url, exact, type, tint, parts, label }
 *
 * and mount() takes either that descriptor or a bare model key. See vehicle-type.js for the full
 * contract. `tint` is applied to the paint groups only — base colour, never roughness/metalness.
 *
 * While the GLB comes down the wire the panel shows the environment plus a progress ring
 * (.viewer3d-load in css/viewer3d.css, fed by the loader's onProgress) and NOTHING standing in
 * for the vehicle. There used to be a procedural schematic of grouped primitives here; it is
 * gone, deliberately and entirely. A stack of grey cylinders pretending to be a motorcycle reads
 * as a broken app, and it was on screen for every first paint. If the GLB never arrives the
 * backdrop and the ring stay, the ring goes quiet, and tapping it retries — no prose, no
 * primitives, nothing to explain away.
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
/**
 * How far the unselected parts fade when one part is focused. 0.35 made the exploded view
 * unreadable — everything that was not the answer went to a silhouette, and against the ink grid
 * backdrop that is close to invisible. 0.62 still says "this one, not those" while leaving the
 * rest of the bike legible, which is the point of an exploded view.
 * Nothing dims on explode alone: coming apart is not the same as choosing.
 */
const DIM_OPACITY = 0.62;
const EXPLODE_MS = 400;
const FOCUS_MS = 600;
const IDLE_MS = 3000;
const EXPLODE_SCALE = 0.8;   // how far the per-part vectors actually throw parts apart

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

/**
 * When a model has no group for a key, the next best thing — but ONLY where the next best thing
 * is genuinely the same component. Every entry here answers "where does a mechanic find this?"
 * and the answer has to be right: the oil, the spark plug, the clutch and the air filter are all
 * parts of the engine, and a tyre is the wheel.
 *
 * What used to be here and is deliberately gone: front-brake -> front-wheel, chain -> rear-wheel,
 * seat -> fairing, handlebar -> frame, headlight -> fairing, exhaust -> engine, frame -> engine.
 * Those are not fallbacks, they are wrong answers. Searching a Yamaha MT-09 for "brake fluid" lit
 * up the wheel, because the model has no brake mesh and the table quietly substituted one. An
 * unhighlighted part is a gap; a confidently highlighted WRONG part is a lie, and the user has no
 * way to tell which they are looking at. So a key with no group now highlights nothing.
 */
const FALLBACK = {
  tire: "front-wheel",
  oil: "engine",
  "spark-plug": "engine",
  clutch: "engine",
  "air-filter": "engine",
  radiator: "engine",
};

/** The exact models. Generic keys are "generic/<name>" and come from ../store/models/generic. */
export const MODEL_KEYS = ["yzf-2021", "honda-cbr650r", "corvette-c8"];

const isGeneric = (key) => typeof key === "string" && key.startsWith("generic/");

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

/**
 * The generic models are other people's Sketchfab uploads, so their node names are whatever each
 * author happened to type — "Tank_low", "Circle.018", "polySurface42". The shared BIKE_PARTS /
 * CAR_PARTS regexes catch the well-named ones; the rest are pinned per model in
 * ../store/models/generic/parts.json, written by web/tools/models-fetch.mjs from the node names
 * it reads out of each converted GLB. Shape:
 *
 *   { "motocross": { "kind": "bike", "extra": { "fuel-tank": ["^tank"], … },
 *                    "paint": ["fuel-tank", "fairing"], "orient": 90 } }
 *
 * `orient` is the extra Y rotation in degrees that turns that model's nose to +x like the others.
 * Registered at boot by registerGenericParts(); until it lands a generic still renders, it just
 * drops more of its meshes into the catch-all group.
 */
const GENERIC_PARTS = new Map();

/** Groups that carry the paint, and so are what a tint is allowed to touch. */
const DEFAULT_PAINT = ["fuel-tank", "fairing", "frame"];

/**
 * registerGenericParts(table) — hand over the parsed generic/parts.json. Safe to call twice and
 * safe to call with junk: anything malformed is skipped rather than thrown.
 */
export function registerGenericParts(table) {
  if (!table || typeof table !== "object") return;
  for (const [name, row] of Object.entries(table)) {
    if (!row || typeof row !== "object") continue;
    const base = row.kind === "car" ? CAR_PARTS : BIKE_PARTS;
    const extra = {};
    for (const [key, list] of Object.entries(row.extra || {})) {
      if (!Array.isArray(list)) continue;
      const res = [];
      for (const source of list) {
        try { res.push(new RegExp(source, "i")); } catch { /* a bad regex is not a dead viewer */ }
      }
      if (res.length) extra[key] = res;
    }
    GENERIC_PARTS.set(`generic/${name}`, {
      table: withExtra(base, extra),
      paint: Array.isArray(row.paint) && row.paint.length ? row.paint : DEFAULT_PAINT,
      paintMaterials: Array.isArray(row.paintMaterials) ? row.paintMaterials : [],
      rotate: Array.isArray(row.rotate) && row.rotate.length === 3 ? row.rotate : null,
      orient: Number.isFinite(row.orient) ? row.orient : 0,
      kind: row.kind === "car" ? "car" : "bike",
    });
  }
}

/** Every part a model key can show, in explode order. */
export function partsFor(modelKey) {
  if (PARTS[modelKey]) return PARTS[modelKey];
  const generic = GENERIC_PARTS.get(modelKey);
  if (generic) return generic.table;
  return CAR_KEY.test(String(modelKey)) ? CAR_PARTS : BIKE_PARTS;
}

/** Generic keys whose model is a car, when parts.json has not been registered yet. */
const CAR_KEY = /(corvette|^generic\/(car|sedan|suv|pickup|coupe|truck))/;

/** Which groups a tint may repaint on this model. */
function paintGroupsFor(modelKey) {
  const generic = GENERIC_PARTS.get(modelKey);
  if (generic) return generic.paint;
  return CAR_KEY.test(String(modelKey)) ? ["fairing"] : DEFAULT_PAINT;
}

/** The named paint materials on this model. Empty = do not tint it at all; see tintModel(). */
function paintMaterialsFor(modelKey) {
  const generic = GENERIC_PARTS.get(modelKey);
  return generic ? generic.paintMaterials : [];
}

/**
 * The matrix that stands a model up the viewer's way: x = length with the nose at +x, y = up,
 * z = width. Two parts, and they are separate because only one of them can be computed:
 *
 *   rotate  which axis is up. Derived from the model's own proportions by
 *           web/tools/models-fetch.mjs — a motorcycle is longer than it is tall and taller than
 *           it is wide, so the sorted bounding box says which exporter convention it came from.
 *           The Yamaha YZ450F arrives Z-up and would otherwise render as a plan view.
 *   orient  which END is the front. A bounding box cannot tell you, so it is set by eye in
 *           web/tools/model-shortlist.json.
 *
 * The three Sketchfab vehicles the app started with are all Y-up facing -x, hence the -90°.
 */
function orientMatrix(THREE, modelKey) {
  const rad = (deg) => (deg * Math.PI) / 180;
  const generic = GENERIC_PARTS.get(modelKey);
  if (!generic) {
    // the -90 belongs to the three exact models and to them only. A generic that gets here has
    // simply not had parts.json registered yet — applying the exact models' convention to it
    // would lay it on its side, and that raced visibly whenever the fetch was slow.
    return new THREE.Matrix4().makeRotationY(isGeneric(modelKey) ? 0 : rad(-90));
  }
  const matrix = new THREE.Matrix4().makeRotationY(rad(generic.orient || 0));
  if (generic.rotate) {
    const [rx, ry, rz] = generic.rotate;
    matrix.multiply(new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(rad(rx), rad(ry), rad(rz), "XYZ")));
  }
  return matrix;
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

/**
 * Group every unmatched node lands in, so nothing is ever invisible.
 *
 * It is called "frame" because on a well-named model the leftovers really are frame and brackets,
 * but a group that was BUILT from leftovers must never be the answer to a question. On a generic
 * whose author named nothing, the catch-all is the entire motorcycle — highlighting it for
 * "brake fluid" would light the whole bike up orange and call that the brakes. pickGroup() below
 * refuses to select a catch-all group, so those models explode and rotate but do not pretend to
 * know where anything is.
 */
const CATCH_ALL = "frame";

/* ------------------------------------------------------------------ model + part lookup */

const flat = (value) => String(value == null ? "" : value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/**
 * modelFor(bike) -> the descriptor from ./vehicle-type.js (see this file's header, and that
 * module's, for the contract). Re-exported here so every caller keeps its single import.
 *
 * The result is memoised per bike, and that is load-bearing, not an optimisation: the Pick screen
 * holds the last value and remounts when `modelFor(bike) !== previous`. A fresh object every call
 * would tear the viewer down and rebuild it on every render.
 */
const descriptors = new Map();

export function modelFor(bike) {
  const id = bike && typeof bike === "object"
    ? `${bike.id || ""}|${bike.make || bike.brand || ""}|${bike.model || bike.name || ""}`
    : String(bike ?? "");
  const cached = descriptors.get(id);
  if (cached) return cached;
  const made = describe(bike);
  descriptors.set(id, made);
  return made;
}

/** Everything modelFor needs from ./vehicle-type.js, once it has loaded. */
let vehicleType = null;

function describe(bike) {
  if (vehicleType) return vehicleType.modelFor(bike);
  // vehicle-type.js is imported at module load and resolves in the same tick as the first mount;
  // this only runs if something asks before it lands, and the exact models cover the demo bikes.
  const text = bike && typeof bike === "object"
    ? flat([bike.make, bike.brand, bike.model, bike.name, bike.id].filter(Boolean).join(" "))
    : flat(bike);
  const key = /\bcorvette\b|\bc8\b|\bstingray\b/.test(text)
    ? "corvette-c8"
    : /\bcbr ?650\b/.test(text)
      ? "honda-cbr650r"
      : "yzf-2021";
  return {
    key,
    url: new URL(`../../store/models/${key}/model.glb`, import.meta.url).href,
    exact: true,
    type: key === "corvette-c8" ? "car" : "sportbike",
    tint: null,
    parts: key === "corvette-c8" ? "car" : "bike",
    label: text,
  };
}

/**
 * Loading ./vehicle-type.js and the two tables it wants. Kicked off on import — it is ~12 KB of
 * module plus two JSON fetches, and every one of them is optional: if any of it fails, describe()
 * above still answers and the viewer still renders, just with the exact models only.
 */
const typesReady = import("./vehicle-type.js")
  .then(async (module) => {
    vehicleType = module;
    descriptors.clear();
    await module.ready();
    descriptors.clear();
    const res = await fetch(new URL("../../store/models/generic/parts.json", import.meta.url));
    if (res.ok) registerGenericParts(await res.json());
  })
  .catch(() => { /* exact models only; see describe() */ });

export { typesReady };

const REAR = /\b(rear|back|pillion|tail)\b/;
const pick = (text, front, rear) => (REAR.test(text) ? rear : front);

/** Ordered — the first rule that matches wins, so specific beats generic. */
const RULES = [
  [/\bclutch\b/, "clutch"],
  [/\bchain\b|\bdrive belt\b/, "chain"],
  [/\bsprocket\b|\bpinion\b/, "sprocket"],
  [/head ?li|head ?la|high beam|low beam|main beam|\bdrl\b/, "headlight"],
  // "brake ?li" used to live here and swallowed "brake LININGS" — brake pads routed to the tail
  // light. Lights have to name themselves now, and a bare "indicator" is a dashboard warning lamp
  // far more often than it is a turn signal, so it no longer matches on its own.
  [/tail ?light|tail ?lamp|rear ?light|rear ?lamp|brake ?light|brake ?lamp|turn ?signal|turn ?indicator|direction ?indicator|blinker|hazard ?(light|lamp|warning)|licen[sc]e plate light/, "taillight"],
  [/\bbulb\b|\blamp\b|\bbeam\b/, "headlight"],
  // handbrake and footbrake are one word, so \bbrake\b never saw them and they fell through to
  // the lever and footpeg rules — "Adjusting handbrake lever" came out as the handlebar
  [/\bbrakes?\b|\bbrake |handbrake|footbrake|hand ?brake|foot ?brake|\bbrake ?lin(?:ing|er)s?\b|\bpads?\b|\bdiscs?\b|\bdisks?\b|\brotors?\b|\bcalipers?\b/, (t) => pick(t, "front-brake", "rear-brake")],
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

/**
 * Words that decide nothing on their own. "Front", "check", "level", "replacing", "adjustment"
 * appear in half the headings in a manual and belong to whatever noun follows them — a rule that
 * fires on one of these is matching the grammar, not the component.
 */
const EMPTY_WORDS = /^(the|a|an|and|or|of|for|to|in|on|at|your|its|front|rear|left|right|upper|lower|check|checking|checks|inspect|inspection|replace|replacing|replacement|adjust|adjusting|adjustment|clean|cleaning|remove|removing|removal|install|installing|installation|fit|fitting|level|levels|change|changing|service|servicing|maintenance|general|before|after|every|when|how|what|part|parts|system|procedure|note|warning|caution|if|is|are|be|not|no|yes|with|without|from|by|about|during)$/;

/**
 * partFor(title, keywords) -> part key | null
 *
 * Which component a manual heading is about. **Null is the normal answer for anything ambiguous**
 * and it is not a failure: the Pick screen explodes the model and highlights nothing, which is
 * honest. The thing this must never do is answer confidently and wrongly — "Brake fluid level" on
 * a Yamaha MT-09 highlighted the front wheel, and to a rider that is the app saying the brake
 * fluid is in the wheel.
 *
 * Two rules keep it honest:
 *   1. the decision is noun-driven. The RULES below are ordered most-specific first and every one
 *      of them matches a component NOUN. Front/rear only pick a side once a noun has decided the
 *      component, which is what `pick()` does.
 *   2. a heading made only of EMPTY_WORDS returns null before any rule runs, so "Checking the
 *      front" and "Before every ride" cannot land on a part through an incidental word.
 *
 * `opts.debug` logs the decision, which is how the regression table in web/tools/partfor-test.mjs
 * gets reviewed.
 */
export function partFor(title, keywords = [], opts = {}) {
  const list = Array.isArray(keywords) ? keywords : keywords ? [keywords] : [];
  const raw = `${String(title || "")} ${list.join(" ")}`;
  const text = ` ${raw} `.toLowerCase().replace(/[\s_/,.;:()-]+/g, " ");

  // nothing here names a component: "Before every ride", "Checking the front", "General notes"
  const meaningful = text.trim().split(" ").filter((word) => word && !EMPTY_WORDS.test(word));
  if (!meaningful.length) return null;

  for (const [re, out] of RULES) {
    if (!re.test(text)) continue;
    const key = typeof out === "function" ? out(text) : out;
    if (opts.debug) console.info(`viewer3d: partFor(${JSON.stringify(raw)}) -> ${key}`);
    return key;
  }
  if (opts.debug) console.info(`viewer3d: partFor(${JSON.stringify(raw)}) -> null`);
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

let dracoLoader = null;

async function loadGlb(THREE, modelKey, url, onProgress) {
  const [{ GLTFLoader }, meshopt, dracoModule] = await Promise.all([
    loadAddon("loaders/GLTFLoader.js"),
    loadAddon("libs/meshopt_decoder.module.js").catch(() => null),
    loadAddon("loaders/DRACOLoader.js").catch(() => null),
  ]);
  const loader = new GLTFLoader();
  if (meshopt && meshopt.MeshoptDecoder) loader.setMeshoptDecoder(meshopt.MeshoptDecoder);
  // the shipped GLBs are Draco-compressed (see ../store/models/CREDITS.md); meshopt is wired up
  // too so an older or re-encoded model.glb still opens.
  if (!dracoLoader && dracoModule && dracoModule.DRACOLoader) {
    dracoLoader = new dracoModule.DRACOLoader();
    dracoLoader.setDecoderPath(`${IMPORTS["three/addons/"]}libs/draco/`);
  }
  // kept across model switches: disposing it would re-fetch and re-compile the wasm every time
  if (dracoLoader) loader.setDRACOLoader(dracoLoader);
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
    const matched = matchPart(modelKey, ...names);
    const key = matched || CATCH_ALL;
    let part = groups.get(key);
    if (!part) {
      const node = new THREE.Group();
      node.name = key;
      root.add(node);
      part = {
        key, label: PART_LABELS[key] || key, node, meshes: [],
        explode: new THREE.Vector3(),
        // true until some mesh actually matches this key by name. A group that only ever
        // collected leftovers is not something the viewer knows the identity of.
        catchAll: !matched,
      };
      groups.set(key, part);
    }
    if (matched) part.catchAll = false;
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

  const orient = orientMatrix(THREE, modelKey);
  meshes.forEach((mesh) => mesh.geometry.applyMatrix4(orient));

  // unlit materials are swapped for standard ones, so the meshes have to be pointed at the swaps
  const swaps = fixShading(THREE, materials);
  if (swaps.size) {
    const swap = (material) => swaps.get(material) || material;
    for (const mesh of meshes) {
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(swap) : swap(mesh.material);
    }
  }
  return finishModel(THREE, { root, groups, meshes, materials, modelKey });
}

/* ------------------------------------------------------------------ shading
 * Raw Sketchfab exports are not consistent, and three renders exactly what they say. Three
 * failure modes turned models black or flat in this app:
 *
 *   metalness 1 + roughness 0   a mirror with nothing to reflect. Correct in the author's
 *                               renderer, and pure black here for the first frames while the
 *                               PMREM is still building — and permanently if the env map never
 *                               lands. A chrome exhaust genuinely is metal, so the fix is to cap
 *                               the combination rather than to stop believing the material.
 *   KHR_materials_unlit         MeshBasicMaterial: ignores every light and every env map, so it
 *                               cannot be lit at all and reads as a flat sticker next to a lit one.
 *   envMapIntensity 0 / unset   nothing from the HDRI reaches the surface.
 *
 * None of this touches the geometry or the textures. It only makes the materials answer to the
 * lighting the scene actually has.
 */
function fixShading(THREE, materials) {
  const replaced = new Map();
  for (const material of [...materials]) {
    if (!material) continue;
    let fixed = material;

    // unlit -> standard, keeping the map so the model looks the same but can now be lit
    if (material.isMeshBasicMaterial) {
      fixed = new THREE.MeshStandardMaterial({
        name: material.name,
        map: material.map || null,
        color: material.color ? material.color.clone() : undefined,
        transparent: material.transparent,
        opacity: material.opacity,
        alphaMap: material.alphaMap || null,
        side: material.side,
        metalness: 0,
        roughness: 0.75,
      });
      replaced.set(material, fixed);
      materials.delete(material);
      materials.add(fixed);
      material.dispose();
    }

    if (!fixed.isMeshStandardMaterial && !fixed.isMeshPhysicalMaterial) continue;

    // a perfect mirror has nothing to show until the PMREM is ready, and goes black without one
    if (fixed.metalness > 0.9 && fixed.roughness < 0.08) {
      fixed.metalness = 0.9;
      fixed.roughness = 0.12;
    }
    fixed.envMapIntensity = 1.15;
    if (fixed.emissive && fixed.emissiveIntensity > 0 && fixed.emissive.getHex() === 0) {
      fixed.emissiveIntensity = 0;       // a black emissive is a no-op that still costs a branch
    }
    // three needs to be told a colour texture is sRGB; a linear one renders dark and desaturated
    for (const slot of ["map", "emissiveMap", "specularColorMap", "sheenColorMap"]) {
      const texture = fixed[slot];
      if (texture && texture.colorSpace !== THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
    }
    fixed.needsUpdate = true;
  }
  return replaced;
}

/**
 * Repaint the bike's paint to `hex` — base colour only. Roughness, metalness, the normal map and
 * the AO map are what make a tank look like a tank rather than a coloured shape, so they are left
 * exactly as the author set them.
 *
 * It tints a material only when that material's own NAME says it is paint — parts.json's
 * `paintMaterials`, written by web/tools/models-fetch.mjs from a strict name match. A model with
 * no such material is not tinted at all, and that is deliberate: three multiplies baseColorTexture
 * by material.color, so tinting a material whose texture is bright red with a pale green gives a
 * muddy red, not a green bike. Of the models we ship exactly one has a material called
 * "…Carpaint…". Guessing on the others would make them look broken, not personalised.
 *
 * Materials are shared between meshes inside a GLB, so each is cloned once before it is
 * recoloured; the clone joins model.materials, which is what disposeModel() walks, so nothing
 * leaks. Called after finishModel(), so userData.originalMaterial is already set and is updated
 * here to match — otherwise clearing a highlight would put the untinted material back.
 */
function tintModel(THREE, model, hex) {
  if (!hex) return model;
  const named = paintMaterialsFor(model.modelKey);
  if (!named.length) return model;
  let color;
  try {
    color = new THREE.Color(hex);
  } catch {
    return model;
  }
  const wanted = new Set(named);
  const allowed = new Set(paintGroupsFor(model.modelKey));
  const clones = new Map();
  const isPaint = (material) =>
    material && material.color && wanted.has(material.name) && material.name;

  for (const mesh of model.meshes) {
    // the material name decides, and the part group is the safety net: a material called "paint"
    // on the wheels is still not the paint
    if (allowed.size && !allowed.has(mesh.userData.partKey)) continue;
    const swap = (material) => {
      if (!isPaint(material)) return material;
      let clone = clones.get(material);
      if (!clone) {
        clone = material.clone();
        clone.color.copy(color);
        clones.set(material, clone);
        model.materials.add(clone);
      }
      return clone;
    };
    const next = Array.isArray(mesh.material) ? mesh.material.map(swap) : swap(mesh.material);
    if (next === mesh.material) continue;
    mesh.material = next;
    mesh.userData.originalMaterial = next;
  }
  return model;
}

/** Normalise to a unit bounding sphere at the origin and attach explode vectors + bounds. */
function finishModel(THREE, model) {
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

  /**
   * Where each part flies to when the assembly comes apart.
   *
   * The hand-tuned vectors in BIKE_PARTS / CAR_PARTS are right for the three models they were
   * measured on. A generic is somebody else's mesh split by regex, so a part called "fairing"
   * there may be half the bike — sending it along the table's vector can push it across another
   * part or straight out of frame. So: take the table direction, but make sure it actually points
   * away from the model centre (flip it if it points inward), and cap every vector at 1.2, which
   * is 1.2 x the normalised model radius. Nothing travels further than the bike is long.
   */
  const table = partsFor(model.modelKey);
  const order = new Map(table.map((part, i) => [part.key, i]));
  const MAX_TRAVEL = 1.2;
  for (const part of model.groups.values()) {
    const entry = table.find((row) => row.key === part.key);
    part.bounds = new THREE.Box3().setFromObject(part.node);
    part.center = part.bounds.getCenter(new THREE.Vector3());
    part.explode.set(...(entry ? entry.explode : [0, 0, 0]));
    const outward = part.center.lengthSq() > 1e-6 ? part.center.clone().normalize() : null;
    if (!entry || part.explode.lengthSq() < 1e-6) {
      // no vector for this key: straight out from the centre of the vehicle
      if (outward) part.explode.copy(outward).multiplyScalar(0.9 + part.center.length() * 0.5);
    } else if (outward && part.explode.dot(outward) < 0) {
      // the table wants it one way and the geometry sits the other way — geometry wins
      part.explode.reflect(outward).negate();
    }
    if (part.explode.length() > MAX_TRAVEL) part.explode.setLength(MAX_TRAVEL);
    part.order = order.has(part.key) ? order.get(part.key) : 99;
  }
  const bounds = new THREE.Box3().setFromObject(model.root);
  model.size = bounds.getSize(new THREE.Vector3());
  model.floor = bounds.min.y;
  model.radius = Math.max(bounds.getBoundingSphere(new THREE.Sphere()).radius, 1e-3);
  return model;
}

/**
 * The scene before any GLB has arrived. Same shape as a real model — an empty root, empty groups,
 * empty meshes — so every caller below reads it without a null check, and `empty: true` is the
 * one flag that says "there is nothing to frame yet", which is all fit() and the picker need.
 */
function emptyModel(THREE, modelKey) {
  const root = new THREE.Group();
  root.name = `empty:${modelKey}`;
  return {
    root,
    groups: new Map(),
    meshes: [],
    materials: new Set(),
    modelKey,
    empty: true,
    size: new THREE.Vector3(1, 1, 1),
    floor: -0.5,
    radius: 1,
  };
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

/* ------------------------------------------------------------------ real environment
 * A Poly Haven HDRI (CC0, see ../store/models/CREDITS.md) does two jobs: the .hdr drives
 * image-based lighting and the metal reflections through PMREM, and a tonemapped .jpg of the same
 * shot is the visible background — far sharper per byte than sampling the HDR for pixels you only
 * ever see blurred. 1k/2k on phones, 2k/4k on desktop. Both are cached per name, so switching
 * models re-uses them; opts.environment: false keeps the transparent studio look instead.
 */

/* ------------------------------------------------------------------ technical backdrop
 * What you look at once the vehicle comes apart. The garage panorama is right for a bike standing
 * in a garage and wrong for one floating in pieces — it competes with the parts and it stops
 * reading as a place. So exploding cross-fades to this: ink, a faint grid on the ground plane in
 * true perspective, a thin orange horizon, and a vignette.
 *
 * It is an inverted sphere drawn before everything else with depthWrite off, not a change to
 * scene.background, because that is what makes a 400 ms cross-fade possible — the panorama stays
 * exactly where it is and this fades in over the top of it. The environment map is untouched, so
 * the parts keep the garage's lighting and reflections while they float in the grid.
 */

const GRID_VERT = `
varying vec3 vDir;
void main() {
  vDir = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const GRID_FRAG = `
varying vec3 vDir;
uniform float uOpacity;
uniform vec3 uInk;
uniform vec3 uLine;
uniform vec3 uAccent;

// one grid line, antialiased against how fast the coordinate changes on screen
float grid(vec2 uv, float width) {
  vec2 d = fwidth(uv);
  vec2 g = abs(fract(uv - 0.5) - 0.5) / max(d, vec2(1e-5));
  return 1.0 - min(min(g.x, g.y) / width, 1.0);
}

void main() {
  vec3 dir = normalize(vDir);
  vec3 color = uInk;

  // the floor: intersect the view ray with y = -1 and draw a grid on it, so the lines converge
  // at the horizon the way a real floor does
  if (dir.y < -0.002) {
    float t = -1.0 / dir.y;
    vec2 floorUv = vec2(dir.x, dir.z) * t;
    float fade = 1.0 / (1.0 + t * t * 0.02);          // distance fog, or it aliases into moire
    color = mix(color, uLine, grid(floorUv * 0.5, 1.4) * 0.55 * fade);
    color = mix(color, uAccent, grid(floorUv * 2.0, 1.1) * 0.18 * fade);
  } else {
    // above the horizon: a much fainter lat/long grid, just enough to say "technical"
    vec2 sky = vec2(atan(dir.z, dir.x) * 2.5, asin(clamp(dir.y, -1.0, 1.0)) * 4.0);
    color = mix(color, uLine, grid(sky, 1.2) * 0.14);
  }

  // the horizon itself, thin and orange
  float horizon = 1.0 - smoothstep(0.0, 0.006, abs(dir.y));
  color = mix(color, uAccent, horizon * 0.40);

  // vignette towards the poles so the frame edges settle down, but gently — the parts are lit by
  // the environment map, not by this, and a heavy vignette just makes the panel feel unlit
  color *= 1.0 - smoothstep(0.45, 1.0, abs(dir.y)) * 0.22;

  // The colours above are picked in sRGB, the way a designer picks them, but a raw ShaderMaterial
  // gets none of three's automatic output conversion — writing them straight out treats them as
  // linear and renders roughly a third as bright. #1a1f24 came out near black, which is precisely
  // what the grid backdrop must not be. So convert here, explicitly.
  color = pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.2));
  gl_FragColor = vec4(color, uOpacity);
}`;

function technicalBackdrop(THREE) {
  const material = new THREE.ShaderMaterial({
    vertexShader: GRID_VERT,
    fragmentShader: GRID_FRAG,
    uniforms: {
      uOpacity: { value: 0 },
      // mid-dark slate, not black: the parts floating in front of it are themselves dark, and
      // black behind dark metal is a silhouette. The grid lines have to be visible too — a grid
      // you cannot see is just a dark rectangle.
      uInk: { value: new THREE.Color(0x1a1f24) },
      uLine: { value: new THREE.Color(0xb6bcc4) },
      uAccent: { value: new THREE.Color(ORANGE) },
    },
    side: THREE.BackSide,
    transparent: true,
    // depthWrite off so it never occludes anything; depthTest ON so the vehicle occludes IT.
    // With depthTest off this sphere painted straight over the bike — three draws transparent
    // objects after opaque ones, so at full opacity the exploded view was a flat dark rectangle
    // with the parts hidden behind it. That is exactly what "everything is so dark you can't see
    // a thing" looked like.
    depthWrite: false,
    depthTest: true,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(40, 48, 32), material);
  mesh.renderOrder = -1;       // behind the vehicle, in front of scene.background
  mesh.frustumCulled = false;
  mesh.visible = false;
  return mesh;
}

/* ------------------------------------------------------------------ environments
 * Where the vehicle is standing. Four of them, switchable without reloading the model, and the
 * choice is remembered per browser.
 *
 * Three are Poly Haven HDRIs (CC0): the .hdr lights the vehicle through PMREM, the tonemapped
 * .jpg is the picture behind it. The fourth is an actual 3D room — a GLB loaded into the scene
 * with the vehicle placed on its floor — lit by the auto_service HDRI, because a room modelled
 * without materials has nothing to light itself with.
 *
 * `scene` on an entry means "this environment is geometry, not just a background".
 */
export const ENVIRONMENTS = [
  { id: "auto_service", label: "Service", swatch: "#b08d5e" },
  { id: "autoshop_01", label: "Garage", swatch: "#8f9196" },
  { id: "studio_small_09", label: "Studio", swatch: "#e6e2da" },
  { id: "empty_warehouse_01", label: "Warehouse", swatch: "#6f7680" },
];

/**
 * `scene: "<file>.glb"` on an entry makes it a modelled room instead of a panorama — loadRoom()
 * below scales it to the vehicle, floors it, gives it a concrete material and fences the camera
 * in. That path is live and tested; what it needs is a room GLB that is actually a room.
 *
 * The one we were given, store/models/env/garage-interior.glb, is not: 98k triangles in a single
 * unnamed mesh with no materials, and the geometry is a field of spikes rather than walls, floor
 * and a door — decimated past the point of being an interior. Rendering it put the bike in the
 * middle of what looks like a cave. So the Garage slot is an HDRI of a real workshop for now, and
 * dropping a usable GLB in here is a one-line change:
 *
 *   { id: "garage", label: "Garage", swatch: "#8f9196", scene: "<file>.glb", lighting: "auto_service" }
 */

export const DEFAULT_ENV = "auto_service";
const ENV_STORAGE_KEY = "mechanica.viewer3d.env";

const envById = (id) => ENVIRONMENTS.find((row) => row.id === id) || ENVIRONMENTS[0];

/** The remembered choice, or the default. Storage can throw in private mode; it is not important. */
function rememberedEnv() {
  try {
    const saved = localStorage.getItem(ENV_STORAGE_KEY);
    if (saved && ENVIRONMENTS.some((row) => row.id === saved)) return saved;
  } catch { /* private mode, or storage disabled */ }
  return DEFAULT_ENV;
}

function rememberEnv(id) {
  try { localStorage.setItem(ENV_STORAGE_KEY, id); } catch { /* not important enough to handle */ }
}

const envCache = new Map();
const roomCache = new Map();

/**
 * The "Garage" environment: a real room around the vehicle rather than a photograph of one.
 *
 * garage-interior.glb is 98k triangles and ships with no materials at all, so it gets one — matte
 * light concrete, which is what a garage interior is and which takes the HDRI's light without
 * competing with the bike for attention.
 *
 * Placing it is the fiddly half. The viewer normalises every vehicle to a unit bounding sphere at
 * the origin, so the room has to be scaled and moved to suit the vehicle, not the other way
 * round: scale it so its floor is a sensible size next to a 2-unit motorcycle, then drop it so
 * its floor sits exactly at the vehicle's wheels. Floor height is read from the geometry — the
 * lowest large horizontal extent — rather than assumed to be y = 0, because it rarely is.
 */
async function loadRoom(THREE, file, radius, height) {
  const key = `${file}:${radius.toFixed(2)}:${height.toFixed(2)}`;
  if (roomCache.has(key)) return roomCache.get(key);
  const job = (async () => {
    const url = new URL(`../../store/models/env/${file}`, import.meta.url).href;
    const { GLTFLoader } = await loadAddon("loaders/GLTFLoader.js");
    const gltf = await new GLTFLoader().loadAsync(url);
    const root = gltf.scene;

    const concrete = new THREE.MeshStandardMaterial({
      color: 0x9fa2a6, roughness: 0.92, metalness: 0.0,
      // FrontSide, not DoubleSide: this is a modelled interior, and rendering both sides of every
      // wall means seeing the backs of the far ones through the near ones, which turns a room
      // into a pile of shapes
      side: THREE.FrontSide,
    });
    root.traverse((object) => {
      if (!object.isMesh) return;
      object.material = concrete;
      // the GLB carries no materials and may carry no normals either; without them a standard
      // material has nothing to shade with and the whole room reads as flat white
      if (!object.geometry.getAttribute("normal")) object.geometry.computeVertexNormals();
      object.castShadow = false;
      object.receiveShadow = true;
    });

    root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());

    /**
     * Scale by the room's HEIGHT, not its footprint.
     *
     * garage-interior.glb is 19 x 2.6 x 20 — a wide, low room, which is what a garage is. Scaling
     * its footprint to a sensible multiple of the vehicle put the ceiling at 1.5 units while the
     * camera orbits at about 3, so the camera sat above the roof looking down through it and the
     * panel filled with white shapes. Matching the ceiling to roughly twice the vehicle's height
     * fixes both ends at once: the bike stands in a room with headroom, and the footprint that
     * comes with it is far larger than anywhere the camera can reach.
     */
    const roomHeight = Math.max(size.y, 1e-3);
    const scale = (height * 2.2) / roomHeight;
    root.scale.setScalar(scale);
    // floor exactly at the vehicle's wheels, vehicle in the middle of the open area
    root.position.set(-centre.x * scale, -box.min.y * scale, -centre.z * scale);
    root.updateMatrixWorld(true);
    const placed = new THREE.Box3().setFromObject(root);
    return {
      root,
      // how far the camera may go before it is inside a wall or through the ceiling
      limit: Math.min(placed.max.y * 0.9, Math.min(placed.max.x, placed.max.z) * 0.8),
      dispose: () => { concrete.dispose(); },
    };
  })();
  roomCache.set(key, job);
  job.catch(() => roomCache.delete(key));
  return job;
}

function loadEnvironment(THREE, renderer, name, big) {
  const id = `${name}:${big ? "big" : "small"}`;
  if (envCache.has(id)) return envCache.get(id);
  const base = new URL("../../store/models/env/", import.meta.url).href;
  const job = (async () => {
    const { RGBELoader } = await loadAddon("loaders/RGBELoader.js");
    const hdr = await new RGBELoader().loadAsync(`${base}${name}-${big ? "2k" : "1k"}.hdr`);
    hdr.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const environment = pmrem.fromEquirectangular(hdr);
    pmrem.dispose();
    /**
     * The visible panorama, in two passes. The 4k (2.0 MB) is on screen in about a second and is
     * already sharp at phone size; on desktop the 8k (4.8 MB) is fetched behind it and swapped in
     * when it lands, which is `upgrade` below. Phones stop at 4k — an 8k equirect is a 32 megapixel
     * texture and not worth the memory on a handset.
     *
     * Both are Poly Haven's tonemapped export, not the HDR: the viewer now renders the backdrop
     * with backgroundBlurriness = 0, so what you see is the actual pixels, and a tonemapped JPEG
     * carries far more of them per byte than an HDR does.
     */
    const panorama = async (size) => {
      const texture = await new THREE.TextureLoader().loadAsync(`${base}${name}-${size}.jpg`);
      texture.mapping = THREE.EquirectangularReflectionMapping;
      texture.colorSpace = THREE.SRGBColorSpace;
      return texture;
    };
    const background = await panorama(big ? "4k" : "2k").catch(() => panorama("4k")).catch(() => hdr);
    if (background !== hdr) hdr.dispose();
    // desktop only, and only once the 4k is already up
    const upgrade = big ? panorama("8k").catch(() => null) : Promise.resolve(null);
    return { environment, background, upgrade };
  })();
  envCache.set(id, job);
  job.catch(() => envCache.delete(id));
  return job;
}

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

/* ------------------------------------------------------------------ the loading ring
 * One SVG ring over the panel while the GLB downloads. It is deliberately the only thing on
 * screen besides the environment: showing a stand-in bike that is about to be replaced by a
 * different bike reads as a glitch, and a model that is honestly still arriving does not.
 * The ring reports the real byte fraction from the loader; before the first Content-Length it
 * spins indeterminately, which is the truth rather than a fake 0%.
 */

const RING_R = 22;
const RING_C = 2 * Math.PI * RING_R;

function progressRing(host) {
  const wrap = document.createElement("div");
  wrap.className = "viewer3d-load";
  wrap.setAttribute("role", "progressbar");
  wrap.setAttribute("aria-label", "Loading the 3D model");
  wrap.innerHTML =
    `<svg class="viewer3d-load-ring" viewBox="0 0 56 56" aria-hidden="true">` +
    `<circle class="viewer3d-load-track" cx="28" cy="28" r="${RING_R}"></circle>` +
    `<circle class="viewer3d-load-arc" cx="28" cy="28" r="${RING_R}"` +
    ` stroke-dasharray="${RING_C.toFixed(1)}" stroke-dashoffset="${(RING_C * 0.75).toFixed(1)}"></circle>` +
    `</svg><b class="viewer3d-load-pct"></b>`;
  host.append(wrap);
  const arc = wrap.querySelector(".viewer3d-load-arc");
  const pct = wrap.querySelector(".viewer3d-load-pct");
  let known = false;
  let retry = null;

  // the error state is a tap target, so it is the only time the ring takes pointer events
  const onTap = () => {
    const again = retry;
    retry = null;
    if (again) again();
  };
  wrap.addEventListener("click", onTap);

  const api = {
    set(fraction) {
      if (fraction == null || !Number.isFinite(fraction)) return;
      if (!known) { known = true; wrap.classList.add("is-known"); }
      const value = Math.max(0, Math.min(1, fraction));
      arc.setAttribute("stroke-dashoffset", (RING_C * (1 - value)).toFixed(1));
      pct.textContent = `${Math.round(value * 100)}%`;
      wrap.setAttribute("aria-valuenow", String(Math.round(value * 100)));
    },
    /** Back to the indeterminate spin, for a retry. */
    reset() {
      known = false;
      retry = null;
      wrap.classList.remove("is-known", "is-failed");
      wrap.removeAttribute("aria-valuenow");
      wrap.removeAttribute("title");
      arc.setAttribute("stroke-dashoffset", (RING_C * 0.75).toFixed(1));
      pct.textContent = "";
    },
    /**
     * Quiet failure: the ring stops, dims, and a tap tries again. No prose — the backdrop is
     * still there and still looks like a garage, so an error message would be the loudest thing
     * on the panel for something the user can fix by tapping it.
     */
    fail(again) {
      known = true;                       // stop the spin
      retry = typeof again === "function" ? again : null;
      wrap.classList.remove("is-known");
      wrap.classList.add("is-failed");
      arc.setAttribute("stroke-dashoffset", "0");
      pct.textContent = "";
      wrap.setAttribute("title", "Tap to load the 3D model again");
    },
    remove() {
      wrap.removeEventListener("click", onTap);
      wrap.remove();
    },
  };
  return api;
}

/* ------------------------------------------------------------------ environment picker
 * Four dots in the corner of the stage. No labels on screen — the swatch colours are the
 * environments, and the name is on the tooltip and on the accessible name, because four words
 * of chrome over a 3D panel is four words competing with the vehicle.
 */

function environmentPicker(host, onPick) {
  const wrap = document.createElement("div");
  wrap.className = "viewer3d-envs";
  wrap.setAttribute("role", "radiogroup");
  wrap.setAttribute("aria-label", "Stage environment");
  const buttons = new Map();
  for (const entry of ENVIRONMENTS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "viewer3d-env";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", "false");
    button.setAttribute("aria-label", entry.label);
    button.title = entry.label;
    button.style.setProperty("--swatch", entry.swatch);
    button.addEventListener("click", () => onPick(entry.id));
    wrap.append(button);
    buttons.set(entry.id, button);
  }
  host.append(wrap);
  return {
    select(id) {
      for (const [key, button] of buttons) button.setAttribute("aria-checked", String(key === id));
    },
    remove() { wrap.remove(); },
  };
}

/* ------------------------------------------------------------------ mount */

/**
 * mount(host, model, opts) -> viewer
 *   host:  an element the canvas fills (absolute/sticky positioning is the screen's job)
 *   model: a model key ("yzf-2021", "generic/scooter") OR a modelFor(bike) descriptor, which is
 *          the normal case — it carries the url and the tint alongside the key.
 *   opts: { onReady(viewer),      // the scene is up: environment lit, loader running
 *           onUpgrade(viewer),    // the GLB arrived and is on screen
 *           onProgress(0..1|null),// download fraction; null while the size is unknown
 *           onSelect(partKey),    // a tap landed on a part (null = background)
 *           onError(error),       // the GLB could not be loaded; the schematic is revealed
 *           environment: false | "<polyhaven name>",  // false = transparent canvas, no HDRI
 *           url: string,          // override the GLB url (dev)
 *           tint: "#rrggbb"|null, // override the descriptor's tint
 *           xray: boolean, debug: boolean }
 *   The viewer is returned synchronously and every call is safe immediately: anything asked for
 *   before the scene exists is replayed once it does.
 * viewer:
 *   explode(on: boolean, spacing = 1)  // exploded view, animated 400 ms
 *   highlight(partKey | null)          // emissive highlight on that part, others dimmed
 *   focus(partKey)                     // highlight + camera fit with slight zoom (animated)
 *   reset()                            // collapse, clear highlight, default camera
 *   resize()
 *   dispose()
 */
export function mount(host, model, opts = {}) {
  const descriptor = model && typeof model === "object" ? model : null;
  const key = (descriptor ? descriptor.key : model) || "yzf-2021";
  const url = opts.url || (descriptor && descriptor.url) || new URL(`../../store/models/${key}/model.glb`, import.meta.url).href;
  const tint = opts.tint !== undefined ? opts.tint : descriptor && descriptor.tint;
  const wish = { exploded: false, spacing: 1, part: null, focused: false, xray: !!opts.xray };
  let live = null;
  let dead = false;
  let three = null;

  host.classList.add("viewer3d");
  host.setAttribute("data-viewer3d", "loading");
  host.setAttribute("data-model", key);
  const loader = progressRing(host);

  boot().then((scene) => {
    if (dead) { scene.dispose(); return; }
    live = scene;
    if (wish.exploded) scene.explode(true, wish.spacing, true);
    if (wish.part) scene.highlight(wish.part);
    if (wish.focused && wish.part) scene.focus(wish.part);
    if (wish.xray) scene.xray(true);
    if (typeof opts.onReady === "function") opts.onReady(api);
  }).catch((error) => {
    loader.fail(() => fetchModel());
    host.setAttribute("data-viewer3d", "error");
    if (typeof opts.onError === "function") opts.onError(error);
    else console.warn("viewer3d: could not start", error);
  });

  /**
   * The environment comes up first — cached across mounts, and it reads as the garage the bike is
   * standing in — and the GLB downloads in front of the progress ring. Nothing stands in for the
   * vehicle in the meantime: a stack of grey primitives pretending to be a motorcycle looks like
   * a bug, and an honest loader does not. If the model never arrives, the backdrop and the ring
   * stay, the ring goes quiet, and tapping it tries again.
   */
  async function boot() {
    three = await loadThree();
    if (dead) throw new Error("disposed");
    const scene = createScene(three, host, null, opts);
    fetchModel(scene);
    return scene;
  }

  function fetchModel(scene = live) {
    if (dead || !scene || !three) return;
    host.setAttribute("data-viewer3d", "loading");
    loader.reset();
    loadGlb(three, key, url, (event) => {
      const fraction = event && event.lengthComputable && event.total ? event.loaded / event.total : null;
      loader.set(fraction);
      if (typeof opts.onProgress === "function") opts.onProgress(fraction);
    }).then((real) => {
      tintModel(three, real, tint);
      if (dead || !scene.adopt(real)) { disposeModel(real); return; }
      loader.remove();
      host.setAttribute("data-viewer3d", "ready");
      if (typeof opts.onUpgrade === "function") opts.onUpgrade(api);
    }).catch((error) => {
      if (dead) return;
      loader.fail(() => fetchModel(scene));
      host.setAttribute("data-viewer3d", "error");
      console.warn(`viewer3d: ${key} did not load (${url})`, error && error.message ? error.message : error);
      if (typeof opts.onError === "function") opts.onError(error);
    });
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

function createScene(THREE, host, initialModel, opts) {
  // null = nothing has loaded yet: the backdrop lights and renders, the panel is not empty, and
  // adopt() drops the real model in when it lands
  let model = initialModel || emptyModel(THREE, opts.modelKey || "");
  const scene = new THREE.Scene();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearAlpha(0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.className = "viewer3d-canvas";
  host.append(renderer.domElement);

  const camera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
  scene.add(model.root);

  // procedural studio light, up instantly; the HDRI replaces it when it arrives
  const environment = studioEnvironment(THREE, renderer);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.75;

  /**
   * Three lights that never switch off, even once the HDRI is doing the real work. They used to
   * drop to almost nothing when the environment arrived, and any material that does not answer
   * to an env map — an unlit export, a mirror-metal with roughness 0 — went black. These are the
   * floor: a key from the upper front-left, a fill opposite it, and a hemisphere so the shadow
   * side of a tank is still readable.
   */
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

  // the grid the panorama cross-fades to when the vehicle comes apart
  const gridBackdrop = technicalBackdrop(THREE);
  scene.add(gridBackdrop);
  let gridNow = 0;
  let gridTarget = 0;

  /**
   * The panorama. backgroundBlurriness stays at 0 — the founder's note was that it looked like
   * "blurry pixelated stuff", and it was: a 2k JPEG blurred by the renderer. A sharp, properly
   * sampled panorama is the point, so this asks for mipmaps and the highest anisotropy the GPU
   * offers, which is what keeps it crisp while the camera swings.
   */
  function setBackdrop(texture) {
    if (!texture) return;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(16, renderer.capabilities.getMaxAnisotropy());
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.generateMipmaps = true;
    texture.needsUpdate = true;
    scene.background = texture;
    scene.backgroundBlurriness = 0;
  }

  /* ------------------------------------------------------------- auto exposure
   * A safety net, not a look. Some Sketchfab exports come out legible and some come out as a
   * silhouette, and which is which cannot be known before the thing is on screen — it depends on
   * the author's metalness values, whether the textures are sRGB, and what is behind it.
   *
   * So after the first frames, read back the pixels where the model is and compare their mean
   * luminance to the backdrop's. If the vehicle is darker than 35% of its surroundings it is
   * unreadable whatever the intent, and the exposure and the fill light come up until it is not.
   * Re-armed on every model swap and whenever the assembly explodes, because exploding changes
   * both what is on screen and what is behind it.
   */
  let exposureChecked = false;
  let exposureLift = 0;
  const BASE_EXPOSURE = 1.1;

  function luminanceOf(pixels, predicate) {
    let sum = 0;
    let n = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      const a = pixels[i + 3];
      if (!predicate(a)) continue;
      sum += (pixels[i] * 0.2126 + pixels[i + 1] * 0.7152 + pixels[i + 2] * 0.0722) / 255;
      n += 1;
    }
    return n ? { mean: sum / n, count: n } : { mean: 0, count: 0 };
  }

  /**
   * Render the model alone on a transparent target to get its mask and its brightness, then the
   * backdrop alone for the reference. Two offscreen renders at 96x96, once per model — cheap
   * enough to be invisible and far more reliable than guessing from material values.
   */
  function checkExposure() {
    if (exposureChecked || !model.meshes.length || exposureLift >= 0.6) return;
    exposureChecked = true;
    try {
      const size = 96;
      const target = new THREE.WebGLRenderTarget(size, size, { colorSpace: THREE.SRGBColorSpace });
      const buffer = new Uint8Array(size * size * 4);

      const background = scene.background;
      const gridWasVisible = gridBackdrop.visible;
      scene.background = null;
      gridBackdrop.visible = false;
      renderer.setRenderTarget(target);
      renderer.setClearAlpha(0);
      renderer.clear();
      renderer.render(scene, camera);
      renderer.readRenderTargetPixels(target, 0, 0, size, size, buffer);
      const vehicle = luminanceOf(buffer, (a) => a > 200);

      model.root.visible = false;
      shadow.visible = false;
      scene.background = background;
      gridBackdrop.visible = gridWasVisible;
      renderer.clear();
      renderer.render(scene, camera);
      renderer.readRenderTargetPixels(target, 0, 0, size, size, buffer);
      const behind = luminanceOf(buffer, () => true);

      model.root.visible = true;
      shadow.visible = true;
      renderer.setRenderTarget(null);
      target.dispose();

      // too little of the model on screen to judge, or the backdrop is itself black
      if (vehicle.count < size * size * 0.02 || behind.mean < 0.05) return;
      const ratio = vehicle.mean / behind.mean;
      if (ratio >= 0.35) return;

      const lift = Math.min(0.6, (0.35 / Math.max(ratio, 0.05) - 1) * 0.35);
      exposureLift = Math.min(0.6, exposureLift + lift);
      renderer.toneMappingExposure = BASE_EXPOSURE + exposureLift;
      fill.intensity = 0.6 + exposureLift * 1.6;
      hemi.intensity = 0.4 + exposureLift * 1.2;
      console.info(
        `viewer3d: ${model.modelKey} read ${(ratio * 100).toFixed(0)}% of the backdrop's brightness; ` +
        `exposure ${(BASE_EXPOSURE + exposureLift).toFixed(2)}`,
      );
      run();
    } catch (error) {
      // a readback can fail on a lost context; it is a safety net, not a feature
      if (opts.debug) console.warn("viewer3d: exposure check skipped", error && error.message);
    }
  }

  /** A new scene.environment only reaches materials that are told to recompile. */
  function applyEnvironment() {
    for (const material of model.materials) material.needsUpdate = true;
    hlMaterials.forEach((material) => { material.needsUpdate = true; });
    dimMaterials.forEach((material) => { material.needsUpdate = true; });
  }

  /**
   * Switch environment. Called once at mount and again whenever the picker is used — the model
   * is never touched, so switching is a texture swap (and, for the garage, a scene graph swap),
   * not a reload. `token` guards against a slow environment landing after a faster one the user
   * chose afterwards.
   */
  let envToken = 0;
  let envId = opts.environment === false ? null : typeof opts.environment === "string" ? opts.environment : rememberedEnv();
  let room = null;

  async function useEnvironment(id) {
    const entry = envById(id);
    const token = ++envToken;
    envId = entry.id;
    host.setAttribute("data-env", entry.id);
    if (picker) picker.select(entry.id);

    // a 3D room replaces the panorama entirely; leaving a photograph behind its walls would show
    // through every doorway and window
    if (room) { scene.remove(room.root); room.dispose(); room = null; }

    const big = Math.max(window.innerWidth || 0, 1) >= 900;
    const lighting = entry.lighting || entry.id;
    try {
      const loaded = await loadEnvironment(THREE, renderer, lighting, big);
      if (disposed || token !== envToken) return;
      scene.environment = loaded.environment.texture;
      scene.environmentIntensity = 1;
      scene.backgroundIntensity = 1;
      // the HDRI leads, but the hand lights stay up: see the block where they are created
      hemi.intensity = 0.4;
      keyLight.intensity = 2.0;
      rim.intensity = 0.8;
      fill.intensity = 0.6;
      shadow.material.opacity = 1;
      renderer.toneMappingExposure = BASE_EXPOSURE + exposureLift;

      if (entry.scene) {
        const built = await loadRoom(THREE, entry.scene, model.radius, Math.max(model.size.y, 0.4));
        if (disposed || token !== envToken) return;
        room = built;
        scene.add(room.root);
        scene.background = null;
        scene.backgroundBlurriness = 0;
        // you cannot orbit through a wall you can see
        if (controls && room.limit > model.radius) controls.maxDistance = Math.min(controls.maxDistance, room.limit);
      } else {
        setBackdrop(loaded.background);
        // the 8k, when it arrives, replaces the 4k in place — same framing, more pixels
        if (loaded.upgrade) {
          loaded.upgrade.then((texture) => {
            if (disposed || token !== envToken || !texture) return;
            setBackdrop(texture);
            host.setAttribute("data-env-detail", "8k");
            run();
          });
        }
      }
      applyEnvironment();
      exposureChecked = false;
      settled = 0;
      run();
    } catch {
      /* the procedural studio light stays; the panel still renders the vehicle */
    }
  }

  const picker = opts.environment === false || opts.picker === false
    ? null
    : environmentPicker(host, (id) => { rememberEnv(id); useEnvironment(id); });

  if (envId) useEnvironment(envId);

  let controls = null;
  let controlsDispose = null;

  let selected = null;
  let xrayOn = false;
  let spacing = 0;
  let target = 0;
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
  let settled = 0;

  // materials: one highlight clone and one dim clone per source material
  const hlMaterials = new Map();
  const dimMaterials = new Map();
  function cloneMaterials() {
    for (const material of model.materials) {
      const hl = material.clone();
      if (hl.emissive) { hl.emissive.setHex(ORANGE); hl.emissiveIntensity = 0.55; }
      if (hl.color) hl.color.lerp(new THREE.Color(ORANGE), 0.18);
      hlMaterials.set(material, hl);
      const dim = material.clone();
      dim.transparent = true;
      dim.opacity = 1 - (1 - DIM_OPACITY) * dimNow;
      dim.depthWrite = false;
      dimMaterials.set(material, dim);
    }
  }
  cloneMaterials();

  /**
   * Compile the highlight and dim shader variants up front.
   *
   * Cloning a material is cheap; the first frame that RENDERS the clone is not, because that is
   * when three compiles a new program for it. On a 100-mesh model that landed as one long frame
   * the moment a part was first tapped — the camera tween kept running underneath it, so the view
   * appeared to hang and then jump to the end. Pre-warming moves that cost to load time, where a
   * few milliseconds behind the progress ring cost nothing.
   */
  function warmMaterials() {
    if (!model.meshes.length) return;
    const originals = model.meshes.map((mesh) => mesh.material);
    for (const variants of [hlMaterials, dimMaterials]) {
      let swapped = false;
      model.meshes.forEach((mesh, i) => {
        const clone = variants.get(originals[i]);
        if (clone) { mesh.material = clone; swapped = true; }
      });
      if (swapped) renderer.compile(scene, camera);
      model.meshes.forEach((mesh, i) => { mesh.material = originals[i]; });
    }
  }

  const xrayMaterial = new THREE.MeshBasicMaterial({
    color: 0x6f7885, transparent: true, opacity: 0.12, depthWrite: false,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });

  const reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  const tmpBox = new THREE.Box3();
  const tmpVec = new THREE.Vector3();
  const HOME = new THREE.Vector3(1.35, 0.72, 2.1).normalize();

  /**
   * The group a part key selects, or null. Null is a real answer — see FALLBACK and CATCH_ALL:
   * the viewer would rather highlight nothing than highlight the wrong thing.
   */
  function pickGroup(partKey) {
    if (!partKey) return null;
    const seen = new Set();
    let key = PART_ALIASES[partKey] || partKey;
    while (key && !seen.has(key)) {
      const group = model.groups.get(key);
      if (group && !group.catchAll) return group;
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
   * The box the assembly will occupy once it has finished spreading, so the camera can pull back
   * in the same 400 ms rather than letting parts sail out of frame and then chasing them.
   */
  /**
   * The box the assembly occupies at a given explode spacing, without touching the scene graph.
   *
   * This used to move every part node, call Box3.setFromObject on the whole tree and move them
   * all back — three full world-matrix updates per call, and it is called on every focus, every
   * explode and every resize. Each part's own bounds are already computed once at load
   * (finishModel), and exploding only ever translates a part, so the answer is just those boxes
   * shifted by their vectors. That is the difference between a click costing milliseconds and a
   * click costing a dropped frame.
   */
  function boxAtSpacing(value, group) {
    const box = new THREE.Box3();
    const offset = new THREE.Vector3();
    const shifted = new THREE.Box3();
    for (const part of model.groups.values()) {
      if (group && part !== group) continue;
      if (!part.bounds || part.bounds.isEmpty()) continue;
      offset.copy(part.explode).multiplyScalar(value * EXPLODE_SCALE);
      shifted.copy(part.bounds).translate(offset);
      box.union(shifted);
    }
    return box.isEmpty() ? boxFor(group) : box;
  }

  /**
   * Frame a box exactly: every corner is pushed against the frustum walls rather than fitting the
   * bounding sphere, which on something as long and thin as a motorcycle would leave the model at
   * a third of the frame. Works for any orbit direction and any aspect, so 390x844 and 1280x800
   * both come out filled.
   */
  function fit(box, { instant = false, zoom = 1.08, duration = FOCUS_MS, direction = null } = {}) {
    /**
     * Nothing has loaded yet, or the group has no geometry. An empty Box3 is (+Inf, -Inf), which
     * would put the camera at NaN, so it gets a unit box at the origin instead of nothing at all.
     *
     * "Instead of nothing at all" is the important half. Returning early here left the camera at
     * its constructor position (0,0,0) with the target also at (0,0,0), and OrbitControls derives
     * its spherical angles from that difference when it is created — a zero vector gives phi = 0,
     * which is straight overhead, and controls.update() then re-imposed that every frame. Every
     * vehicle rendered as a plan view, including the ones whose geometry had not changed at all.
     */
    if (!box || box.isEmpty()) {
      box = new THREE.Box3(
        new THREE.Vector3(-model.radius, -model.radius, -model.radius),
        new THREE.Vector3(model.radius, model.radius, model.radius),
      );
    }
    const center = box.getCenter(new THREE.Vector3());
    const forward = (direction ? direction.clone()
      : controls && camera.position.distanceToSquared(controls.target) > 1e-6
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
    get model() { return model; },
    /**
     * Hide or show the vehicle without tearing the scene down. mount() hides it while the GLB
     * downloads — the environment keeps rendering behind the loading ring, and the schematic
     * underneath is only revealed if the download never lands.
     */
    showModel(on) {
      model.root.visible = !!on;
      shadow.visible = !!on;
      run();
    },
    /** Swap the schematic for the real model, keeping the current explode/highlight state. */
    adopt(next) {
      if (disposed || !next || !next.meshes.length) return false;
      const key = selected ? selected.key : null;
      scene.remove(model.root);
      disposeModel(model);
      hlMaterials.forEach((material) => material.dispose());
      hlMaterials.clear();
      dimMaterials.forEach((material) => material.dispose());
      dimMaterials.clear();
      model = next;
      cloneMaterials();
      scene.add(model.root);
      model.root.visible = true;
      shadow.visible = true;
      shadow.position.y = model.floor - model.radius * 0.01;
      warmMaterials();
      applyEnvironment();
      exposureChecked = false;
      applySpacing();
      selected = pickGroup(key);
      dimTarget = selected ? 1 : 0;
      paint();
      if (controls) {
        controls.minDistance = model.radius * 0.6;
        controls.maxDistance = model.radius * 12;
      }
      fit(boxAtSpacing(target, selected), { instant: true, zoom: selected ? 1.02 : target ? 1.03 : 1.08 });
      run();
      return true;
    },
    explode(on, amount = 1, instant = false) {
      const to = on ? amount : 0;
      target = to;
      host.setAttribute("data-exploded", on ? "on" : "off");
      gridTarget = on ? 1 : 0;              // cross-fade the panorama to the technical grid
      gridBackdrop.visible = true;
      exposureChecked = false;               // ink behind the parts is a different exposure problem
      settled = 0;
      if (instant || reduced.matches) {
        spacing = to;
        spacingTween = null;
        gridNow = gridTarget;
        gridBackdrop.material.uniforms.uOpacity.value = gridNow;
        gridBackdrop.visible = gridNow > 0.001;
        applySpacing();
      } else {
        spacingTween = { start: performance.now(), from: spacing, to, duration: EXPLODE_MS };
      }
      // 1.12 rather than 1.03: the camera tween and the parts move at the same time, so a frame
      // mid-flight has parts further out than the final box. The padding is what stops them
      // being clipped on the way, and the refit when the tween lands tightens it back up.
      fit(boxAtSpacing(to, null), {
        instant: instant || reduced.matches,
        duration: EXPLODE_MS,
        zoom: to ? 1.12 : 1.08,
      });
    },
    highlight(partKey) {
      selected = pickGroup(partKey);
      dimTarget = selected ? 1 : 0;
      paint();
    },
    focus(partKey) {
      scene3d.highlight(partKey);
      fit(boxAtSpacing(target, selected), { zoom: selected ? 1.02 : 1.08 });
      touch();
    },
    xray(on) { xrayOn = !!on; paint(); },
    reset() {
      selected = null;
      dimTarget = 0;
      xrayOn = false;
      target = 0;
      paint();
      host.setAttribute("data-exploded", "off");
      if (reduced.matches) { spacing = 0; spacingTween = null; applySpacing(); }
      else spacingTween = { start: performance.now(), from: spacing, to: 0, duration: EXPLODE_MS };
      fit(boxAtSpacing(0, null), { duration: FOCUS_MS, direction: HOME });
    },
    resize,
    capture() { renderer.render(scene, camera); return renderer.domElement.toDataURL("image/png"); },
    state() {
      return {
        ready: true, model: model.modelKey, empty: !!model.empty,
        part: selected ? selected.key : null, spacing, xray: xrayOn,
        parts: [...model.groups.keys()], meshes: model.meshes.length,
      };
    },
    dispose,
  };

  function applySpacing() {
    for (const part of model.groups.values()) part.node.position.copy(part.explode).multiplyScalar(spacing * EXPLODE_SCALE);
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
    if (!cameraTween) fit(boxAtSpacing(target, null), { instant: true });
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
      applySpacing();
      if (t === 1) {
        spacingTween = null;
        // the parts have landed: frame what is actually there now, rather than the padded box
        // the camera was aimed at while they were still moving
        if (!cameraTween) {
          fit(boxAtSpacing(target, selected), { duration: 260, zoom: selected ? 1.06 : target ? 1.06 : 1.08 });
        }
      }
    }

    // panorama <-> technical grid, on the same clock as the explode
    if (Math.abs(gridNow - gridTarget) > 0.002) {
      const step = dt * (1000 / EXPLODE_MS);
      gridNow += Math.sign(gridTarget - gridNow) * Math.min(Math.abs(gridTarget - gridNow), step);
      gridBackdrop.material.uniforms.uOpacity.value = easeInOut(clamp01(gridNow));
      gridBackdrop.visible = gridNow > 0.002;
    }
    if (cameraTween && controls) {
      // cubic ease-out: leaves immediately and settles, which reads as the camera moving rather
      // than as the view being repositioned. easeInOut spends the first third barely moving,
      // which on a 600 ms move is indistinguishable from a stall followed by a jump.
      const t = clamp01((now - cameraTween.start) / cameraTween.duration);
      const eased = easeOut(t);
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

    // once the model, the environment and any tween have settled, check it is actually visible
    if (!exposureChecked && !spacingTween && !cameraTween && model.meshes.length) {
      settled += 1;
      if (settled > 3) { settled = 0; checkExposure(); }
    }
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
    if (picker) picker.remove();
    if (room) { scene.remove(room.root); room.dispose(); room = null; }
    gridBackdrop.geometry.dispose();
    gridBackdrop.material.dispose();
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
    host.removeAttribute("data-env");
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
    fit(boxAtSpacing(target, selected), { instant: true });
  }).catch(() => {
    if (disposed) return;
    const made = miniOrbit(THREE, camera, renderer.domElement);
    made.minDistance = model.radius * 0.6;
    made.maxDistance = model.radius * 12;
    made.addEventListener("start", touch);
    controls = made;
    controlsDispose = () => made.dispose();
    fit(boxAtSpacing(target, selected), { instant: true });
  });

  if (opts.debug && typeof window !== "undefined") window.__viewer3d = { scene, camera, renderer, get model() { return model; }, get controls() { return controls; } };

  return scene3d;
}
