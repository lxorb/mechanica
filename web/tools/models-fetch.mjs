/**
 * Downloads the curated generic models from Sketchfab, converts them for the web and writes
 * everything the viewer needs. Owner: vehicle-models agent.
 *
 *   node web/tools/models-fetch.mjs                 # every model in SHORTLIST that is missing
 *   node web/tools/models-fetch.mjs --only scooter  # just these
 *   node web/tools/models-fetch.mjs --force         # re-download and re-convert
 *   node web/tools/models-fetch.mjs --parts         # only re-read node names and rewrite parts.json
 *
 * The token lives at C:\Users\me\agent-secrets\sketchfab.txt (or $SKETCHFAB_TOKEN) and is never
 * printed, never written into any output file and never committed. Search is unauthenticated —
 * see sketchfab-search.mjs — but `GET /v3/models/{uid}/download` needs it.
 *
 * What it writes, per model:
 *   web/store/models/generic/<name>/model.glb    Draco geometry, webp textures <= 1024, <= 5 MB
 *   web/store/models/generic/<name>/license.txt  the author's own licence file from the zip
 *   web/store/models/generic/<name>/source.json  uid, author, licence, counts — what CREDITS reads
 * and once, for all of them:
 *   web/store/models/generic/parts.json          node-name -> part-key hints per model
 *
 * Pipeline, per model (gltf-transform 4.x):
 *   dedup -> instance -> flatten/join off (the part groups ARE the node tree, joining destroys
 *   them) -> resize textures to 1024 -> webp -> draco. Node names are preserved throughout; that
 *   is the whole reason `join` and `weld --no-names` are avoided, because the viewer matches part
 *   groups on those names.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";



const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const GENERIC = join(ROOT, "web", "store", "models", "generic");
const WORK = join(HERE, ".models-work");
const SHORTLIST_FILE = join(HERE, "model-shortlist.json");
const TOKEN_FILE = process.env.SKETCHFAB_TOKEN_FILE || "C:\\Users\\me\\agent-secrets\\sketchfab.txt";

const GLTF_TRANSFORM = process.env.GLTF_TRANSFORM
  || join("C:", "Users", "me", "AppData", "Local", "Temp", "claude", "C--Users-me",
          "4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be", "scratchpad", "node_modules", ".bin", "gltf-transform.cmd");

const MAX_BYTES = 5 * 1024 * 1024;

/* ------------------------------------------------------------------ token */

function token() {
  if (process.env.SKETCHFAB_TOKEN) return process.env.SKETCHFAB_TOKEN.trim();
  if (!existsSync(TOKEN_FILE)) throw new Error(`no Sketchfab token at ${TOKEN_FILE}`);
  const raw = readFileSync(TOKEN_FILE, "utf8").trim();
  // the file may be "token: abc" or a bare token; take the last whitespace-delimited word
  const value = raw.split(/\s+/).filter(Boolean).pop();
  if (!value || value.length < 20) throw new Error("the Sketchfab token file looks empty");
  return value;
}

/* ------------------------------------------------------------------ download */

async function downloadUrl(uid) {
  const res = await fetch(`https://api.sketchfab.com/v3/models/${uid}/download`, {
    headers: { Authorization: `Token ${token()}`, Accept: "application/json" },
  });
  if (res.status === 401 || res.status === 403) throw new Error(`${res.status}: the token was rejected`);
  if (!res.ok) throw new Error(`download endpoint said ${res.status} ${res.statusText}`);
  const body = await res.json();
  const url = (body.gltf && body.gltf.url) || (body.glb && body.glb.url);
  if (!url) throw new Error(`no gltf archive offered (got ${Object.keys(body).join(", ") || "nothing"})`);
  return url;
}

/**
 * The S3 archive links are short-lived and undici aborts the stream ("terminated") often enough
 * on a 20-40 MB download that streaming straight to disk is not worth it. These are tens of
 * megabytes, once, on a dev machine: buffer them and retry.
 */
async function fetchTo(url, file, tries = 3) {
  let last;
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`zip ${res.status} ${res.statusText}`);
      writeFileSync(file, Buffer.from(await res.arrayBuffer()));
      return statSync(file).size;
    } catch (error) {
      last = error;
      await new Promise((r) => setTimeout(r, 2000 * (i + 1)));
    }
  }
  throw new Error(`download failed: ${last && last.message}`);
}

/**
 * Windows ships tar(1), which reads zip — no extra dependency for one unzip. `--force-local` is
 * required: without it tar reads "C:\work\model.zip" as host "C" and tries to resolve it.
 * PowerShell's Expand-Archive is the fallback for the odd archive bsdtar chokes on.
 */
function unzip(zip, into) {
  mkdirSync(into, { recursive: true });
  try {
    execFileSync("tar", ["--force-local", "-xf", zip, "-C", into], { stdio: "pipe" });
  } catch {
    execFileSync("powershell", ["-NoProfile", "-Command",
      `Expand-Archive -LiteralPath '${zip}' -DestinationPath '${into}' -Force`], { stdio: "pipe" });
  }
}

function findScene(dir) {
  const stack = [dir];
  const found = [];
  while (stack.length) {
    for (const entry of readdirSync(stack.pop(), { withFileTypes: true })) {
      const path = join(entry.parentPath || entry.path || dir, entry.name);
      if (entry.isDirectory()) stack.push(path);
      else if (/\.(gltf|glb)$/i.test(entry.name)) found.push(path);
    }
  }
  if (!found.length) throw new Error("no .gltf or .glb inside the archive");
  // prefer scene.gltf, then the biggest — some archives ship a lowpoly preview alongside
  found.sort((a, b) => (basename(b) === "scene.gltf") - (basename(a) === "scene.gltf") || statSync(b).size - statSync(a).size);
  return found[0];
}

function licenseIn(dir) {
  const stack = [dir];
  while (stack.length) {
    for (const entry of readdirSync(stack.pop(), { withFileTypes: true })) {
      const path = join(entry.parentPath || entry.path || dir, entry.name);
      if (entry.isDirectory()) stack.push(path);
      else if (/^licen[sc]e/i.test(entry.name)) return path;
    }
  }
  return null;
}

/* ------------------------------------------------------------------ convert */

const run = (args, label) => {
  try {
    execFileSync(GLTF_TRANSFORM, args, { stdio: "pipe", maxBuffer: 1 << 26, shell: true });
    return true;
  } catch (error) {
    const text = String(error.stderr || error.stdout || error.message).split("\n").slice(-4).join(" ").trim();
    console.log(`      ${label} skipped: ${text.slice(0, 160)}`);
    return false;
  }
};

const size = (file) => statSync(file).size;
const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

/** Run a stage and keep its output only if the stage ran AND the file actually got smaller. */
function stage(args, label, input, output, { mustShrink = true, quiet = false } = {}) {
  if (!run([args[0], input, output, ...args.slice(1)], label)) return input;
  if (!existsSync(output)) return input;
  if (mustShrink && size(output) >= size(input)) {
    if (!quiet) console.log(`      ${label} made it bigger (${mb(size(input))} -> ${mb(size(output))}), keeping the input`);
    return input;
  }
  return output;
}

/**
 * Geometry compression. Draco and meshopt win on completely different models and the viewer
 * decodes both, so both are tried and the smaller file wins. On the Kawasaki (217 clean meshes)
 * Draco wins outright; on the Triumph (3,900 tiny primitives) Draco *triples* the file and
 * meshopt cuts it by 88% — guessing which is which up front is not worth the wrong answer.
 */
function compress(input, work, tag) {
  const candidates = [
    ["draco", stage(["draco"], "draco", input, join(work, `${tag}-draco.glb`), { quiet: true })],
    ["meshopt", stage(["meshopt"], "meshopt", input, join(work, `${tag}-meshopt.glb`), { quiet: true })],
  ].filter(([, file]) => file !== input);
  if (!candidates.length) return input;
  candidates.sort((a, b) => size(a[1]) - size(b[1]));
  const [name, file] = candidates[0];
  console.log(`      ${name} ${mb(size(input))} -> ${mb(size(file))}`);
  return file;
}

/**
 * Textures at 1024 first, then 512 if the result is still over MAX_BYTES, and `join` only as the
 * last resort because it merges meshes by material and the node tree IS the part structure.
 *
 * Draco is applied conditionally, not unconditionally. On a model built from thousands of tiny
 * primitives — the Triumph Bonneville here has 3,900 named nodes — Draco's per-primitive header
 * costs more than the vertex data it saves and the file more than doubles: 21 MB in, 50 MB out.
 * So every stage above is kept only if it shrank the file.
 */
async function convert(source, out, work) {
  // step 0, and it has to be first: a Sketchfab .gltf keeps its geometry in a .bin and its
  // textures in a folder, so the FILE is a few KB while the model is 40 MB. Every size
  // comparison below would be meaningless against it. Pack it into a .glb once, then measure.
  const packed = join(work, "packed.glb");
  if (!run(["copy", source, packed], "pack")) throw new Error("could not pack the source into a glb");
  console.log(`      packed ${mb(size(packed))}`);

  // before anything else: a ground plane under the vehicle would dominate the bounding sphere
  // the viewer normalises to, and shrink the vehicle to a speck
  const stripped = await stripScenery(packed, join(work, "stripped.glb"));

  let current = stripped || packed;
  current = stage(["dedup"], "dedup", current, join(work, "a.glb"));
  current = stage(["instance"], "instance", current, join(work, "b.glb"));

  for (const [px, quality, label] of [[1024, "82", "1024px"], [512, "72", "512px"]]) {
    let step = current;
    step = stage(["resize", "--width", String(px), "--height", String(px)], `resize ${px}`, step, join(work, `c${px}.glb`));
    step = stage(["webp", "--quality", quality], "webp", step, join(work, `d${px}.glb`));
    step = compress(step, work, `t${px}`);
    writeFileSync(out, readFileSync(step));
    console.log(`      ${label} -> ${mb(size(out))}`);
    if (size(out) <= MAX_BYTES) return size(out);
  }

  // Still too big, so spend the two things worth spending, in the order they cost least:
  // `join` merges meshes by material, which costs the fine-grained part groups; `simplify` cuts
  // the triangle count in half, which costs silhouette detail. Both are last resorts, and a
  // model nobody can download is worth less than a coarse one.
  console.log("      still over budget, joining and simplifying (part groups will be coarse)");
  let step = stage(["weld"], "weld", current, join(work, "w.glb"), { mustShrink: false });
  step = stage(["join"], "join", step, join(work, "j.glb"), { mustShrink: false });
  step = stage(["resize", "--width", "1024", "--height", "1024"], "resize 1024", step, join(work, "jc.glb"));
  step = stage(["webp", "--quality", "80"], "webp", step, join(work, "jd.glb"));
  const whole = compress(step, work, "j");
  if (size(whole) <= MAX_BYTES) {
    writeFileSync(out, readFileSync(whole));
    console.log(`      joined -> ${mb(size(out))}`);
    return size(out);
  }
  const simplified = stage(["simplify", "--ratio", "0.5", "--error", "0.002"], "simplify", step, join(work, "s.glb"), { mustShrink: false });
  writeFileSync(out, readFileSync(compress(simplified, work, "s")));
  console.log(`      joined + simplified -> ${mb(size(out))}`);
  return size(out);
}

/* ------------------------------------------------------------------ parts */

/**
 * @gltf-transform lives beside the CLI, not in this repo — web/ has no build and no node_modules,
 * and a 176-package dev dependency does not belong in it for a one-off conversion. So the
 * libraries are imported from wherever the CLI was installed.
 */
const LIB = dirname(dirname(GLTF_TRANSFORM));   // .../node_modules/.bin/x -> .../node_modules

/** import a package out of LIB by absolute path — bare specifiers would not resolve from here. */
async function lib(name) {
  const pkg = JSON.parse(readFileSync(join(LIB, name, "package.json"), "utf8"));
  const entry = (pkg.exports && (pkg.exports["."]?.import?.default || pkg.exports["."]?.import
    || pkg.exports["."]?.default || (typeof pkg.exports["."] === "string" ? pkg.exports["."] : null)))
    || pkg.module || pkg.main || "index.js";
  return import(pathToFileURL(join(LIB, name, entry)).href);
}

/**
 * Sketchfab authors very often park the vehicle on a ground plane, a turntable or a studio
 * backdrop and publish the lot as one model. The viewer normalises whatever it loads to a unit
 * bounding sphere, so a 300-unit floor under a 2-unit motorcycle makes the motorcycle a speck —
 * the Harley came in with a `pPlane1_Floor_0` and rendered the size of a thumbnail.
 *
 * There is no gltf-transform CLI command for "delete that node", so this does it through the API:
 * drop every mesh whose name or material says scenery, then anything left that is a huge flat
 * slab (one axis under 2% of the longest, and covering most of the footprint).
 */
async function stripScenery(file, out) {
  const io = await readerIO();
  const document = await io.read(file);
  const root = document.getRoot();
  const SCENERY = /floor|ground|backdrop|\bplane\b|podium|pedestal|turntable|platform|shadow ?catcher|studio|cyclorama|shadowplane/i;
  const dropped = [];

  const span = (prim) => {
    const pos = prim.getAttribute("POSITION");
    if (!pos) return null;
    const lo = pos.getMin([]);
    const hi = pos.getMax([]);
    return [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
  };

  // how big the whole model is, so "flat and wide" can be judged relative to it
  let longest = 0;
  for (const mesh of root.listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const s = span(prim);
      if (s) longest = Math.max(longest, ...s);
    }
  }

  for (const node of root.listNodes()) {
    const mesh = node.getMesh();
    if (!mesh) continue;
    const names = [node.getName() || "", mesh.getName() || "",
      ...mesh.listPrimitives().map((p) => (p.getMaterial() ? p.getMaterial().getName() || "" : ""))];
    let scenery = names.some((n) => SCENERY.test(n));
    if (!scenery) {
      for (const prim of mesh.listPrimitives()) {
        const s = span(prim);
        if (!s || !longest) continue;
        const flat = Math.min(...s) < longest * 0.02;
        const wide = s.filter((v) => v > longest * 0.55).length >= 2;
        if (flat && wide) { scenery = true; break; }
      }
    }
    if (scenery) { dropped.push(names.find(Boolean) || "(unnamed)"); node.dispose(); }
  }
  if (!dropped.length) return null;
  await io.write(out, document);
  console.log(`      stripped scenery: ${dropped.slice(0, 5).join(", ")}${dropped.length > 5 ? ` +${dropped.length - 5}` : ""}`);
  return out;
}

/**
 * Which way is up, computed rather than typed.
 *
 * Sketchfab takes uploads from Blender, 3ds Max, Maya and half a dozen exporters, and they do not
 * agree on an up axis — the Yamaha YZ450F came in Z-up and rendered as a plan view of a
 * motocrosser. But a vehicle's proportions give the answer away: a motorcycle is much longer than
 * it is tall and much taller than it is wide, and a car is longer than it is wide and wider than
 * it is tall. So sort the bounding box and map the axes onto the viewer's convention
 * (x = length, y = up, z = width).
 *
 * Returns the Euler XYZ rotation in degrees, or null when the model is already right. What it
 * cannot tell you is which END is the front — from a bounding box a bike is symmetric — so that
 * stays the hand-set `orient` in model-shortlist.json.
 */
function uprightRotation(span, kind) {
  const order = [0, 1, 2].sort((a, b) => span[b] - span[a]);   // longest .. shortest
  const [long, mid, short] = order;
  // motorcycle: length > height > width. car: length > width > height.
  const wanted = kind === "car"
    ? { [long]: "x", [mid]: "z", [short]: "y" }
    : { [long]: "x", [mid]: "y", [short]: "z" };
  const axis = [wanted[0], wanted[1], wanted[2]].join("");
  // the handful of permutations an exporter actually produces, as a rotation the viewer can apply
  const ROTATIONS = {
    xyz: null,                  // already ours
    xzy: [-90, 0, 0],           // Z-up (Blender, 3ds Max): z is height
    yxz: [0, 0, 90],            // Y is length
    zyx: [0, 90, 0],            // Z is length
    yzx: [0, 90, 90],
    zxy: [90, 90, 0],
  };
  return ROTATIONS[axis] === undefined ? null : ROTATIONS[axis];
}

let readerIOPromise = null;
function readerIO() {
  if (!readerIOPromise) {
    readerIOPromise = (async () => {
      const { NodeIO } = await lib("@gltf-transform/core");
      const { ALL_EXTENSIONS } = await lib("@gltf-transform/extensions");
      const draco = await lib("draco3dgltf");
      const meshopt = await lib("meshoptimizer");
      return new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
        "draco3d.decoder": await draco.createDecoderModule(),
        "draco3d.encoder": await draco.createEncoderModule(),
        "meshopt.decoder": meshopt.MeshoptDecoder,
        "meshopt.encoder": meshopt.MeshoptEncoder,
      });
    })();
  }
  return readerIOPromise;
}

/** The part each node name belongs to, read back out of the converted GLB. */
async function inspect(file, { bounds = false } = {}) {
  // the shared IO has both decoders registered, which matters because compress() picks whichever
  // of draco/meshopt won per model and this has to read back whatever it wrote
  const io = await readerIO();
  const document = await io.read(file);
  const names = new Set();
  for (const mesh of document.getRoot().listMeshes()) if (mesh.getName()) names.add(mesh.getName());
  for (const node of document.getRoot().listNodes()) if (node.getName()) names.add(node.getName());
  const materials = document.getRoot().listMaterials().map((m) => m.getName()).filter(Boolean);
  let triangles = 0;
  for (const mesh of document.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const indices = prim.getIndices();
      triangles += indices ? indices.getCount() / 3 : (prim.getAttribute("POSITION")?.getCount() || 0) / 3;
    }
  }
  const out = { names: [...names], materials, triangles: Math.round(triangles) };
  if (bounds) {
    // which way the model points, and how big its materials are: the two things that have to be
    // decided per model and cannot be guessed from a name
    const min = [1e9, 1e9, 1e9];
    const max = [-1e9, -1e9, -1e9];
    const area = new Map();
    for (const mesh of document.getRoot().listMeshes()) {
      for (const prim of mesh.listPrimitives()) {
        const pos = prim.getAttribute("POSITION");
        if (!pos) continue;
        const lo = pos.getMin([]);
        const hi = pos.getMax([]);
        for (let i = 0; i < 3; i++) { min[i] = Math.min(min[i], lo[i]); max[i] = Math.max(max[i], hi[i]); }
        const name = prim.getMaterial() ? prim.getMaterial().getName() || "?" : "(none)";
        area.set(name, (area.get(name) || 0) + (pos.getCount() || 0));
      }
    }
    out.span = max.map((v, i) => +(v - min[i]).toFixed(2));
    out.longest = ["x", "y", "z"][out.span.indexOf(Math.max(...out.span))];
    out.materialWeight = [...area].sort((a, b) => b[1] - a[1]);
    out.textured = new Set(
      document.getRoot().listMaterials().filter((m) => m.getBaseColorTexture()).map((m) => m.getName() || "?"),
    );
  }
  return out;
}

/**
 * `--names`: print every model's node names, material names and bounding span. This is the input
 * to two decisions that cannot be automated — the `orient` that turns a model's nose to +x, and
 * which material is the paint — so it prints rather than guesses.
 */
async function names() {
  for (const name of readdirSync(GENERIC).sort()) {
    const file = join(GENERIC, name, "model.glb");
    if (!existsSync(file)) continue;
    try {
      const info = await inspect(file, { bounds: true });
      console.log(`\n=== ${name}  (${info.triangles.toLocaleString()} tris, ${mb(size(file))})`);
      console.log(`  span x,y,z ${info.span.join(", ")} — longest axis ${info.longest}`);
      console.log(`  materials by vertex count:`);
      for (const [material, verts] of info.materialWeight.slice(0, 12)) {
        console.log(`    ${String(verts).padStart(7)}  ${material}${info.textured.has(material) ? "  [baseColorTexture]" : ""}`);
      }
      console.log(`  node/mesh names (${info.names.length}): ${info.names.slice(0, 44).join(" | ")}`);
    } catch (error) {
      console.log(`=== ${name}: ${error.message}`);
    }
  }
}

/**
 * Turn the node names into per-part regex hints. The shared BIKE_PARTS table in viewer3d.js
 * already matches anything sensibly named, so this only has to add what it would otherwise miss —
 * which is exactly the names below that match a keyword the shared table does not carry.
 */
const HINTS = [
  ["front-wheel", /(front|^f[_.-]|\bfr\b).{0,10}(wheel|rim|tyre|tire)|wheel.{0,6}(f|front)\b/i],
  ["rear-wheel", /(rear|back|^r[_.-]).{0,10}(wheel|rim|tyre|tire)|wheel.{0,6}(r|rear|back)\b/i],
  ["front-fork", /fork|suspension.{0,6}front|triple.?(clamp|tree)|telescop/i],
  ["rear-shock", /shock|mono.?shock|rear.{0,6}(spring|damper)/i],
  ["swingarm", /swing.?arm/i],
  ["chain", /\bchain\b|sprocket|drive.?belt/i],
  ["engine", /engine|motor|cylinder|crank|gearbox|block/i],
  ["exhaust", /exhaust|muffler|silencer|pipe|header/i],
  ["fuel-tank", /\btank\b|fuel|petrol|gas.?tank/i],
  ["seat", /\bseat\b|saddle|pillion/i],
  ["handlebar", /handle|\bbar\b|lever|grip|throttle|dash|speedo|instrument|mirror/i],
  ["headlight", /head.?(light|lamp)|front.?light/i],
  ["taillight", /tail.?(light|lamp)|rear.?light|brake.?light|indicator|blinker/i],
  ["fairing", /fairing|cowl|body|shell|panel|fender|mudguard|screen|shield|plastic/i],
  ["frame", /frame|chassis|subframe/i],
  ["front-brake", /front.{0,8}(brake|disc|disk|rotor|caliper)|brake.{0,6}front/i],
  ["rear-brake", /rear.{0,8}(brake|disc|disk|rotor|caliper)|brake.{0,6}rear/i],
];

/** Names the shared table in viewer3d.js already matches — no point repeating them. */
const ALREADY = /wheel|rim|tyre|tire|fork|shock|swing ?arm|chain|sprocket|engine|motor|exhaust|muffler|tank|fuel|seat|handle|mirror|head ?li|tail ?li|fairing|cowl|panel|fender|frame|chassis|brake|disc|caliper|body/i;

const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Which materials are the paint, by name. Deliberately strict.
 *
 * The brief is "tint the obvious paint material when the GLB has one clearly named material;
 * otherwise skip", and the reason to be strict is that a base-colour tint multiplies the
 * baseColorTexture: setting a pale green on a material whose texture is bright red gives a muddy
 * red, not a green bike. So only a material that says in its own name that it is paint gets
 * tinted, and a model with no such material is simply not tinted. Of the five shipped models
 * exactly one qualifies — MAT_Ducati_StreetFighter_V4S_Carpaint_Red — and that is the honest
 * answer, not a shortfall to be papered over.
 */
const PAINT_NAME = /car[_ ]?paint|(^|[_ .])paint([_ .]|$)|body[_ ]?paint|lacquer|\bcarrosserie\b|\bpaintwork\b/i;
const NOT_PAINT = /tyre|tire|rubber|glass|chrome|metal|engine|exhaust|brake|seat|leather|light|lamp|decal|sticker|plastic|carbon|floor|ground/i;

function paintMaterialsIn(info) {
  return (info.materials || []).filter((name) => PAINT_NAME.test(name) && !NOT_PAINT.test(name));
}

function hintsFor(names) {
  const extra = {};
  for (const name of names) {
    if (ALREADY.test(name)) continue;
    for (const [key, re] of HINTS) {
      if (!re.test(name)) continue;
      (extra[key] ||= []).push(`^${escape(name)}$`);
      break;
    }
  }
  return extra;
}

/* ------------------------------------------------------------------ main */

function shortlist() {
  if (!existsSync(SHORTLIST_FILE)) throw new Error(`no shortlist at ${SHORTLIST_FILE} — run sketchfab-search.mjs and curate it first`);
  return JSON.parse(readFileSync(SHORTLIST_FILE, "utf8"));
}

async function main() {
  const args = process.argv.slice(2);
  const force = args.includes("--force");
  const only = args.includes("--only") ? args[args.indexOf("--only") + 1].split(",") : null;
  const partsOnly = args.includes("--parts");
  if (args.includes("--names")) return names();
  const list = shortlist().filter((row) => !only || only.includes(row.name));

  mkdirSync(GENERIC, { recursive: true });
  mkdirSync(WORK, { recursive: true });

  const parts = existsSync(join(GENERIC, "parts.json"))
    ? JSON.parse(readFileSync(join(GENERIC, "parts.json"), "utf8"))
    : {};
  const done = [];

  for (const row of list) {
    const dir = join(GENERIC, row.name);
    const glb = join(dir, "model.glb");
    const have = existsSync(glb);
    if (have && !force && !partsOnly) {
      console.log(`  = ${row.name} already there (${(statSync(glb).size / 1024 / 1024).toFixed(2)} MB)`);
      done.push({ ...row, bytes: statSync(glb).size });
      continue;
    }
    if (!have && partsOnly) continue;
    try {
      if (!partsOnly) {
        console.log(`  > ${row.name}  ${row.title}`);
        mkdirSync(dir, { recursive: true });
        const work = join(WORK, row.name);
        mkdirSync(work, { recursive: true });
        const zip = join(work, "model.zip");
        // the zip is kept between runs: 20-40 MB over a metered link, and the conversion is what
        // usually needs another go, not the download
        const bytes = existsSync(zip) && statSync(zip).size > 100_000
          ? statSync(zip).size
          : await fetchTo(await downloadUrl(row.uid), zip);
        console.log(`      zip ${(bytes / 1024 / 1024).toFixed(1)} MB`);
        rmSync(join(work, "src"), { recursive: true, force: true });
        unzip(zip, join(work, "src"));
        const scene = findScene(join(work, "src"));
        const license = licenseIn(join(work, "src"));
        if (license) writeFileSync(join(dir, "license.txt"), readFileSync(license));
        await convert(scene, glb, work);
      }
      const info = await inspect(glb, { bounds: true });
      // the shortlist wins when it says something: `rotate: null` there means "verified upright,
      // do not guess". uprightRotation() only fills the gap for a model nobody has looked at yet.
      const upright = "rotate" in row ? row.rotate : uprightRotation(info.span, row.kind);
      if (upright) console.log(`      upright: span ${info.span.join("x")} -> rotate ${upright.join(", ")}°`);
      parts[row.name] = {
        kind: row.kind || "bike",
        // Euler XYZ in degrees that stands the model up the viewer's way (x = length, y = up).
        // Computed from the bounding box — see uprightRotation().
        rotate: upright,
        // and then the Y flip that decides which end is the front, which a bounding box cannot
        // tell you. Set by eye in model-shortlist.json.
        orient: row.orient || 0,
        paint: row.paint || (row.kind === "car" ? ["fairing"] : ["fuel-tank", "fairing", "frame"]),
        paintMaterials: paintMaterialsIn(info),
        extra: hintsFor(info.names),
      };
      writeFileSync(join(dir, "source.json"), JSON.stringify({
        uid: row.uid, title: row.title, author: row.author, authorUrl: row.authorUrl,
        url: row.url, license: row.license, type: row.type, kind: row.kind || "bike",
        triangles: info.triangles, materials: info.materials.length,
        bytes: statSync(glb).size,
      }, null, 2));
      console.log(`      ok · ${info.triangles.toLocaleString()} tris · ${info.names.length} named nodes · ${(statSync(glb).size / 1024 / 1024).toFixed(2)} MB`);
      done.push({ ...row, bytes: statSync(glb).size, triangles: info.triangles });
    } catch (error) {
      console.log(`  ! ${row.name}: ${error.message}`);
    }
  }

  writeFileSync(join(GENERIC, "parts.json"), JSON.stringify(parts, null, 1));
  console.log(`\n${done.length}/${list.length} models · parts.json has ${Object.keys(parts).length} entries`);
  const total = done.reduce((sum, row) => sum + (row.bytes || 0), 0);
  console.log(`total ${(total / 1024 / 1024).toFixed(1)} MB, biggest ${(Math.max(0, ...done.map((r) => r.bytes || 0)) / 1024 / 1024).toFixed(2)} MB`);
}

main().catch((error) => { console.error(error.message); process.exit(1); });
