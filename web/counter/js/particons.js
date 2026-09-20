/**
 * Part icons. Owner: part-icons agent.
 *
 * One consistent line-art family for "what does this part look like": 36 SVGs in
 * ../store/icons-parts/, 96x96, 2.5 px ink strokes, one orange accent each.
 * Pairs with ../css/particons.css (the .part-icon tile) and PREVIEW.html.
 *
 *   import { iconFor, iconEl } from "../particons.js";
 *   row.prepend(iconEl(iconFor(part.name), "sm"));
 *
 * iconFor() takes manual language as it is actually written — part names
 * ("Engine oil (SAE 15W/50)", "main fuse 30 A") and section titles
 * ("Checking that the brake linings of the front brake are secured") — plus the
 * section's keywords[], and answers with one of PART_ICONS. It never throws and
 * never returns null: unmatched text falls back to "generic-part".
 */

export const PART_ICONS = [
  "engine-oil",
  "oil-filter",
  "air-filter",
  "spark-plug",
  "brake-pads",
  "brake-disc",
  "brake-fluid",
  "brake-caliper",
  "brake-lever",
  "clutch-lever",
  "clutch-cable",
  "chain",
  "sprocket",
  "tire",
  "wheel",
  "front-fork",
  "rear-shock",
  "swingarm",
  "battery",
  "fuse",
  "bulb-headlight",
  "taillight",
  "coolant",
  "radiator",
  "fuel-tank",
  "fuel-filter",
  "exhaust",
  "mirror",
  "handlebar",
  "seat",
  "footpeg",
  "throttle-cable",
  "bearing",
  "bolt-torque",
  "tool-kit",
  "generic-part",
];

const KNOWN = new Set(PART_ICONS);
const FALLBACK = "generic-part";
const BASE = "../store/icons-parts/";

const SIZES = { sm: 32, md: 48, lg: 96 };

/**
 * Ordered: the first pattern that hits wins, so the specific reading of a word
 * sits above the loose one ("oil filter" above "oil", "clutch cable" above
 * "clutch", "fork oil" above "oil"). Patterns run against normalised text, so
 * "brake-pad", "oil-level" and "TYRE PRESSURE" all arrive lower-cased and
 * space-separated.
 */
const RULES = [
  ["brake-fluid", /brake fluid|fluid,? (?:front|rear) brake|\bdot ?[45](?: ?\d)?\b|fluid level,? (?:front|rear)/],
  ["brake-pads", /brake (?:pad|lining|shoe)|(?:pad|lining) (?:material|thickness|wear)|brake ?pad|friction material/],
  ["brake-disc", /brake (?:disc|disk|rotor)|(?:disc|disk|rotor) (?:thickness|runout)|\bbrake discs?\b/],
  ["brake-caliper", /calip|calliper|brake cylinder|master cylinder/],
  ["clutch-cable", /clutch (?:cable|play|free travel|adjust|actuation|fluid|slave|master)/],
  ["clutch-lever", /clutch lever|\bclutch\b/],
  ["brake-lever", /brake lever|hand brake|\blevers?\b/],
  ["throttle-cable", /throttle|twist ?grip|grip play|accelerator|bowden|cable play|cable routing/],
  ["engine-oil", /engine oil|motor oil|oil level|oil change|chang\w* the .*\boil\b|oil quantity|oil grade|oil capacity|oil pressure|oil sight glass|oil dipstick/],
  ["oil-filter", /oil filter|oil screen|oil strainer|filter cartridge/],
  ["air-filter", /air (?:filter|cleaner|box|element|intake)|intake filter|airbox/],
  ["fuel-filter", /fuel filter|petrol filter|gasoline filter/],
  ["spark-plug", /spark ?plug|ignition plug|glow plug|\bplugs?\b(?!.*(?:socket|connector|charg))/],
  ["front-fork", /\bforks?\b|telescopic|stanchion|triple clamp|upside ?down|\busd\b|front suspension|fork oil/],
  ["rear-shock", /shock|suspension|damping|\bdamper\b|spring ?(?:pre)?load|preload|spring strut|monoshock|rebound|ride height|\bdsa\b/],
  ["swingarm", /swing ?arm|single ?sided swing/],
  ["chain", /\bchains?\b/],
  ["sprocket", /sprocket|chain ?wheel|\bpinion\b/],
  ["tire", /\btyres?\b|\btires?\b|\btread\b|\brdc\b|tpms|puncture|wheel balanc/],
  ["wheel", /\bwheels?\b|\brims?\b|\bspokes?\b|wheel hub/],
  ["bearing", /bearing|steering head|head race/],
  ["battery", /batter|\bagm\b|accumulator|charger|charging|jump ?start|trickle/],
  ["fuse", /\bfuses?\b|fuse ?box|fusebox|circuit breaker/],
  ["bulb-headlight", /head ?(?:light|lamp)|\bbulbs?\b|low beam|high beam|main beam|dipped beam|daytime running|driving light/],
  ["taillight", /tail ?(?:light|lamp)|rear light|brake light|turn (?:indicator|signal)|indicator light|flasher|number plate light|licen[cs]e plate/],
  ["coolant", /coolant|antifreeze|cooling (?:system|liquid|fluid)|water pump|expansion tank|engine temperature|overheat/],
  ["radiator", /radiator|cooling fin|\bcooler\b|\bfans?\b/],
  ["fuel-tank", /\bfuel\b|petrol|gasolin|unleaded|\bron\b|filler (?:cap|neck)|refuel|\btanks?\b|reserve|octane/],
  ["exhaust", /exhaust|muffler|silencer|catalyt|emission|tail ?pipe|\bmanifold\b/],
  ["mirror", /mirrors?/],
  ["handlebar", /handle ?bar|\brisers?\b|bar end|\bgrips?\b|steering damp/],
  ["seat", /\bseats?\b|saddle|\bbench\b|pillion/],
  ["footpeg", /foot ?(?:peg|rest|board)|\bpegs?\b/],
  ["engine-oil", /\boils?\b|lubricant|lubricat|\bgrease\b|\bfluid\b/],
  ["brake-disc", /\bbrakes?\b|braking|\babs\b/],
  ["bolt-torque", /torque|tighten|\bscrews?\b|\bbolts?\b|\bnuts?\b|fastener|\bclamps?\b|encapsulated|thread ?lock|locking compound/],
  ["tool-kit", /\btools?\b|tool ?kit|on ?board kit|repair kit|workshop|maintenance|servicing|service (?:work|schedule|due|display|interval|requirement|instruction)/],
];

/** Lower-case, strip punctuation, collapse whitespace: "brake-pad" -> "brake pad". */
function normalise(value) {
  return String(value == null ? "" : value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function haystack(name, keywords) {
  const parts = [normalise(name)];
  const list = Array.isArray(keywords) ? keywords : keywords == null ? [] : [keywords];
  for (const item of list) {
    const text = normalise(item);
    if (text) parts.push(text);
  }
  return parts.filter(Boolean).join(" ");
}

/**
 * iconFor("Engine oil (SAE 15W/50)")        -> "engine-oil"
 * iconFor("brake linings")                  -> "brake-pads"
 * iconFor("tyre pressure")                  -> "tire"
 * iconFor("spark plug BOSCHVR6NEU")         -> "spark-plug"
 * iconFor("main fuse 30 A")                 -> "fuse"
 * iconFor("Adjusting the chain tension")    -> "chain"
 * iconFor("microencapsulated screws")       -> "bolt-torque"
 * iconFor("anything else")                  -> "generic-part"
 */
export function iconFor(name, keywords = []) {
  const text = haystack(name, keywords);
  if (!text) return FALLBACK;
  for (const [id, pattern] of RULES) {
    if (pattern.test(text)) return id;
  }
  return FALLBACK;
}

/** Path from the counter app (/counter/) to the icon file in /store/. */
export function iconUrl(id) {
  return `${BASE}${KNOWN.has(id) ? id : FALLBACK}.svg`;
}

function sizeKey(size) {
  if (typeof size === "number") {
    if (size <= 36) return "sm";
    if (size <= 64) return "md";
    return "lg";
  }
  const key = String(size || "md").toLowerCase();
  return SIZES[key] ? key : "md";
}

/** A decorative <img> already wearing .part-icon and its size class. */
export function iconEl(id, size = "md") {
  const key = sizeKey(size);
  const px = SIZES[key];
  const img = document.createElement("img");
  img.className = `part-icon ${key}`;
  img.src = iconUrl(id);
  img.width = px;
  img.height = px;
  img.alt = "";
  img.decoding = "async";
  img.loading = "lazy";
  img.draggable = false;
  img.setAttribute("aria-hidden", "true");
  return img;
}

/** iconEl(iconFor(...)) in one step, for list rows. */
export function iconElFor(name, keywords = [], size = "md") {
  return iconEl(iconFor(name, keywords), size);
}
