/**
 * Inspect a vehicle model and show how its nodes land in the viewer's parts table.
 *
 *   node web/tools/model-check.mjs                      # every model key it can find
 *   node web/tools/model-check.mjs yzf-2021             # one key (model.glb, else scene.gltf)
 *   node web/tools/model-check.mjs path/to/any.glb --model corvette-c8
 *   node web/tools/model-check.mjs yzf-2021 --names     # every distinct source name + counts
 *   node web/tools/model-check.mjs yzf-2021 --where     # where each group sits + explode hint
 *   node web/tools/model-check.mjs yzf-2021 --json      # machine readable
 *
 * No dependencies: the GLB container and the glTF JSON are parsed here, and skin joints are read
 * straight out of the buffer when it is not compressed. (@gltf-transform/cli is only needed to
 * *build* model.glb — see web/store/models/CREDITS.md for the exact command.)
 *
 * The point of the tool: after a new GLB is dropped in, run it and look at the UNMATCHED row.
 * Every name listed there needs a regex in the matching model's table in
 * web/counter/js/viewer3d.js (BIKE_PARTS / CAR_PARTS) — nothing else has to change.
 */

import { readFileSync, existsSync, statSync } from "node:fs";
import { resolve, dirname, basename, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { matchPart, partsFor, PART_LABELS, MODEL_KEYS } from "../counter/js/viewer3d.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODELS = resolve(HERE, "..", "store", "models");
const ROOT = resolve(HERE, "..", "..");

const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const value = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const targets = args.filter((arg) => !arg.startsWith("--") && args[args.indexOf(arg) - 1] !== "--model");

const KB = 1024;
const bytes = (n) => (n >= KB * KB ? `${(n / KB / KB).toFixed(1)} MB` : `${Math.round(n / KB)} KB`);
const count = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/* ------------------------------------------------------------------ container parsing */

function readGltf(file) {
  const buffer = readFileSync(file);
  if (buffer.length > 12 && buffer.readUInt32LE(0) === 0x46546c67) {
    const chunks = [];
    let offset = 12;
    while (offset + 8 <= buffer.length) {
      const length = buffer.readUInt32LE(offset);
      const type = buffer.readUInt32LE(offset + 4);
      chunks.push({ type, data: buffer.subarray(offset + 8, offset + 8 + length) });
      offset += 8 + length + ((4 - (length % 4)) % 4) * 0;
    }
    const json = chunks.find((chunk) => chunk.type === 0x4e4f534a);
    const bin = chunks.find((chunk) => chunk.type === 0x004e4942);
    if (!json) throw new Error(`${file}: no JSON chunk`);
    return { gltf: JSON.parse(json.data.toString("utf8")), bin: bin ? bin.data : null, size: buffer.length, glb: true };
  }
  const gltf = JSON.parse(buffer.toString("utf8"));
  let bin = null;
  const uri = gltf.buffers && gltf.buffers[0] && gltf.buffers[0].uri;
  if (uri && !uri.startsWith("data:")) {
    const side = resolve(dirname(file), decodeURIComponent(uri));
    if (existsSync(side)) bin = readFileSync(side);
  } else if (uri) {
    bin = Buffer.from(uri.slice(uri.indexOf(",") + 1), "base64");
  }
  let size = buffer.length + (bin ? bin.length : 0);
  for (const image of gltf.images || []) {
    if (!image.uri || image.uri.startsWith("data:")) continue;
    const side = resolve(dirname(file), decodeURIComponent(image.uri));
    if (existsSync(side)) size += statSync(side).size;
  }
  return { gltf, bin, size, glb: false };
}

const COMPONENT = { 5120: Int8Array, 5121: Uint8Array, 5122: Int16Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array };
const ITEMS = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

/** Read an accessor as a flat typed array, or null when the data is compressed/absent. */
function readAccessor(gltf, bin, index) {
  const accessor = gltf.accessors && gltf.accessors[index];
  if (!accessor || accessor.bufferView == null || !bin) return null;
  const view = gltf.bufferViews[accessor.bufferView];
  if (view.extensions && view.extensions.EXT_meshopt_compression) return null;
  const Type = COMPONENT[accessor.componentType];
  if (!Type) return null;
  const items = ITEMS[accessor.type] || 1;
  const start = (view.byteOffset || 0) + (accessor.byteOffset || 0);
  const stride = view.byteStride || items * Type.BYTES_PER_ELEMENT;
  const out = new Type(accessor.count * items);
  for (let i = 0; i < accessor.count; i++) {
    const at = start + i * stride;
    for (let k = 0; k < items; k++) {
      out[i * items + k] = Type === Float32Array
        ? bin.readFloatLE(at + k * 4)
        : Type.BYTES_PER_ELEMENT === 1 ? bin.readUInt8(at + k)
          : Type.BYTES_PER_ELEMENT === 2 ? bin.readUInt16LE(at + k * 2) : bin.readUInt32LE(at + k * 4);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ world placement
 * Column-major 4x4s, same convention as glTF. Enough to put every mesh where it really sits,
 * including rigid skins (world = jointWorld * inverseBindMatrix), so an unnamed source group
 * can be identified by position alone.
 */

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

function multiply(a, b) {
  const out = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += a[k * 4 + r] * b[c * 4 + k];
      out[c * 4 + r] = sum;
    }
  }
  return out;
}

function localMatrix(node) {
  if (node.matrix) return node.matrix.slice();
  const [x, y, z, w] = node.rotation || [0, 0, 0, 1];
  const [sx, sy, sz] = node.scale || [1, 1, 1];
  const [tx, ty, tz] = node.translation || [0, 0, 0];
  const x2 = x + x, y2 = y + y, z2 = z + z;
  const xx = x * x2, xy = x * y2, xz = x * z2;
  const yy = y * y2, yz = y * z2, zz = z * z2;
  const wx = w * x2, wy = w * y2, wz = w * z2;
  return [
    (1 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0,
    (xy - wz) * sy, (1 - (xx + zz)) * sy, (yz + wx) * sy, 0,
    (xz + wy) * sz, (yz - wx) * sz, (1 - (xx + yy)) * sz, 0,
    tx, ty, tz, 1,
  ];
}

function point(m, x, y, z) {
  return [
    m[0] * x + m[4] * y + m[8] * z + m[12],
    m[1] * x + m[5] * y + m[9] * z + m[13],
    m[2] * x + m[6] * y + m[10] * z + m[14],
  ];
}

/** The viewer turns the source models so the front points at +x; report in that frame. */
const toViewer = ([x, y, z]) => [-z, y, x];

function boxOf(gltf, mesh, matrix) {
  const box = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const primitive of mesh.primitives || []) {
    const accessor = gltf.accessors[primitive.attributes.POSITION];
    if (!accessor || !accessor.min || !accessor.max) continue;
    for (let corner = 0; corner < 8; corner++) {
      const source = [
        corner & 1 ? accessor.max[0] : accessor.min[0],
        corner & 2 ? accessor.max[1] : accessor.min[1],
        corner & 4 ? accessor.max[2] : accessor.min[2],
      ];
      const world = toViewer(point(matrix, ...source));
      for (let i = 0; i < 3; i++) {
        box[i] = Math.min(box[i], world[i]);
        box[i + 3] = Math.max(box[i + 3], world[i]);
      }
    }
  }
  return box[0] === Infinity ? null : box;
}

const growBox = (into, box) => {
  for (let i = 0; i < 3; i++) {
    into[i] = Math.min(into[i], box[i]);
    into[i + 3] = Math.max(into[i + 3], box[i + 3]);
  }
  return into;
};
const emptyBox = () => [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];

function triangles(gltf, primitive) {
  const mode = primitive.mode == null ? 4 : primitive.mode;
  if (mode !== 4) return 0;
  const source = primitive.indices != null ? gltf.accessors[primitive.indices] : gltf.accessors[primitive.attributes.POSITION];
  return source ? Math.floor(source.count / 3) : 0;
}

/* ------------------------------------------------------------------ node walk */

function inspect(file, modelKey) {
  const { gltf, bin, size, glb } = readGltf(file);
  const nodes = gltf.nodes || [];
  const parents = new Map();
  nodes.forEach((node, i) => (node.children || []).forEach((child) => parents.set(child, i)));
  const nameOf = (i) => {
    const node = nodes[i];
    if (!node) return "";
    return node.name || (node.extras && node.extras.name) || "";
  };
  const chain = (i) => {
    const out = [];
    let at = parents.get(i);
    for (let depth = 0; at != null && depth < 3; depth++) {
      const name = nameOf(at);
      if (name) out.push(name);
      at = parents.get(at);
    }
    return out;
  };

  const worlds = new Map();
  const worldOf = (i) => {
    if (worlds.has(i)) return worlds.get(i);
    const parent = parents.get(i);
    const matrix = multiply(parent == null ? IDENTITY : worldOf(parent), localMatrix(nodes[i]));
    worlds.set(i, matrix);
    return matrix;
  };
  const binds = new Map();
  const bindOf = (skinIndex) => {
    if (!binds.has(skinIndex)) {
      const skin = gltf.skins[skinIndex];
      binds.set(skinIndex, skin.inverseBindMatrices != null ? readAccessor(gltf, bin, skin.inverseBindMatrices) : null);
    }
    return binds.get(skinIndex);
  };

  const rows = [];
  const names = new Map();
  const whole = emptyBox();
  let tris = 0;

  nodes.forEach((node, i) => {
    if (node.mesh == null) return;
    const mesh = gltf.meshes[node.mesh];
    const own = nameOf(i);
    const up = chain(i);
    const joints = [];
    let matrix = worldOf(i);
    if (node.skin != null && gltf.skins && gltf.skins[node.skin]) {
      const skin = gltf.skins[node.skin];
      const seen = new Set();
      for (const primitive of mesh.primitives || []) {
        if (primitive.attributes.JOINTS_0 == null) continue;
        const data = readAccessor(gltf, bin, primitive.attributes.JOINTS_0);
        const weights = readAccessor(gltf, bin, primitive.attributes.WEIGHTS_0);
        if (!data) { joints.push("<compressed skin>"); break; }
        for (let v = 0; v < data.length; v += 4) {
          for (let k = 0; k < 4; k++) {
            if (weights && weights[v + k] < 0.5) continue;
            seen.add(data[v + k]);
          }
        }
      }
      const dominant = [...seen][0];
      for (const index of seen) {
        const name = nameOf(skin.joints[index]);
        if (name) joints.push(name);
      }
      const bind = dominant != null ? bindOf(node.skin) : null;
      if (bind) matrix = multiply(worldOf(skin.joints[dominant]), [...bind.slice(dominant * 16, dominant * 16 + 16)]);
    }
    const sources = [...new Set([...joints, own, mesh.name || "", ...up].filter(Boolean))];
    const primitiveTris = (mesh.primitives || []).reduce((n, primitive) => n + triangles(gltf, primitive), 0);
    tris += primitiveTris;
    const key = matchPart(modelKey, ...sources);
    const label = sources.find((name) => !/^Object_\d+$/.test(name)) || sources[0] || `node ${i}`;
    const box = boxOf(gltf, mesh, matrix);
    if (box) growBox(whole, box);
    const used = (mesh.primitives || [])
      .map((primitive) => (primitive.material != null && gltf.materials ? gltf.materials[primitive.material].name : ""))
      .filter(Boolean);
    rows.push({ node: i, name: own, mesh: mesh.name || "", sources, key, tris: primitiveTris, box, materials: used });
    const entry = names.get(label) || { label, meshes: 0, tris: 0, key, box: emptyBox(), materials: new Set() };
    entry.meshes += 1;
    entry.tris += primitiveTris;
    used.forEach((name) => entry.materials.add(name));
    if (box) growBox(entry.box, box);
    names.set(label, entry);
  });

  return {
    file, modelKey, size, glb, rows, names: [...names.values()], tris, whole,
    nodes: nodes.length,
    meshes: (gltf.meshes || []).length,
    materials: (gltf.materials || []).length,
    images: (gltf.images || []).length,
    extensions: gltf.extensionsUsed || [],
    generator: (gltf.asset && gltf.asset.generator) || "",
  };
}

/* ------------------------------------------------------------------ report */

function report(info) {
  const table = partsFor(info.modelKey);
  const buckets = new Map(table.map((part) => [part.key, { key: part.key, meshes: 0, tris: 0, names: new Set() }]));
  const missed = { key: "UNMATCHED", meshes: 0, tris: 0, names: new Set() };
  for (const row of info.rows) {
    const bucket = row.key && buckets.has(row.key) ? buckets.get(row.key) : missed;
    bucket.meshes += 1;
    bucket.tris += row.tris;
    bucket.names.add(row.sources[0] || `node ${row.node}`);
  }

  console.log("");
  console.log(`${info.modelKey}  ${relative(ROOT, info.file).replace(/\\/g, "/")}`);
  console.log(`  ${bytes(info.size)}${info.glb ? " glb" : " gltf + bin + textures"} · nodes ${info.nodes} · meshes ${info.meshes} · materials ${info.materials} · images ${info.images} · ${count(info.tris)} tris`);
  if (info.extensions.length) console.log(`  extensions: ${info.extensions.join(", ")}`);
  if (info.generator) console.log(`  generator: ${info.generator}`);
  console.log("");
  console.log(`  ${"part".padEnd(14)}${"meshes".padStart(7)}${"tris".padStart(8)}  source names`);
  const list = [...buckets.values()].filter((bucket) => bucket.meshes).concat(missed.meshes ? [missed] : []);
  for (const bucket of list) {
    const names = [...bucket.names];
    const shown = names.slice(0, 6).join(", ") + (names.length > 6 ? ` … +${names.length - 6}` : "");
    console.log(`  ${bucket.key.padEnd(14)}${String(bucket.meshes).padStart(7)}${count(bucket.tris).padStart(8)}  ${shown}`);
  }
  const covered = list.filter((bucket) => bucket.key !== "UNMATCHED").length;
  console.log("");
  console.log(`  ${covered}/${table.length} parts present · ${missed.meshes} unmatched meshes (${count(missed.tris)} tris) -> group "${CATCH_ALL_LABEL}"`);
  if (missed.names.has("<compressed skin>")) {
    const source = resolve(dirname(info.file), "scene.gltf");
    console.log(`  NOTE  the skins are meshopt-compressed, so joint names cannot be read here.`);
    console.log(`        the browser decodes them fine — inspect the uncompressed source instead:`);
    console.log(`        node web/tools/model-check.mjs ${relative(ROOT, source).replace(/\\/g, "/")} --model ${info.modelKey} --names --where`);
  } else if (missed.meshes) {
    console.log(`  add a regex for: ${[...missed.names].slice(0, 24).join(", ")}`);
  }
  if (flag("names")) {
    console.log("");
    console.log(`  ${"source name".padEnd(34)}${"meshes".padStart(7)}${"tris".padStart(8)}  ${"part".padEnd(13)}materials`);
    for (const entry of info.names.sort((a, b) => b.tris - a.tris)) {
      const mats = [...entry.materials].slice(0, 4).join(", ");
      console.log(`  ${entry.label.slice(0, 33).padEnd(34)}${String(entry.meshes).padStart(7)}${count(entry.tris).padStart(8)}  ${(entry.key || "-").padEnd(13)}${mats}`);
    }
  }
  if (flag("where")) {
    const middle = [0, 1, 2].map((i) => (info.whole[i] + info.whole[i + 3]) / 2);
    const reach = Math.max(...[0, 1, 2].map((i) => (info.whole[i + 3] - info.whole[i]) / 2)) || 1;
    const at = (entry) => [0, 1, 2].map((i) => ((entry.box[i] + entry.box[i + 3]) / 2 - middle[i]) / reach);
    const span = (entry) => [0, 1, 2].map((i) => (entry.box[i + 3] - entry.box[i]) / reach);
    const fixed = (list) => list.map((n) => (n >= 0 ? " " : "") + n.toFixed(2)).join(" ");
    console.log("");
    console.log("  where each group sits, viewer frame: +x front, +y up, +z left, units = model half-extent");
    console.log(`  ${"source name".padEnd(34)}${"centre x  y  z".padEnd(20)}${"size x  y  z".padEnd(20)}part`);
    for (const entry of info.names.filter((row) => row.box[0] !== Infinity).sort((a, b) => at(b)[0] - at(a)[0])) {
      console.log(`  ${entry.label.slice(0, 33).padEnd(34)}${fixed(at(entry)).padEnd(20)}${fixed(span(entry)).padEnd(20)}${entry.key || "-"}`);
    }
  }
}

const CATCH_ALL_LABEL = "frame";

/* ------------------------------------------------------------------ main */

function fileFor(key) {
  for (const name of ["model.glb", "scene.gltf", "scene.glb"]) {
    const file = resolve(MODELS, key, name);
    if (existsSync(file)) return file;
  }
  return null;
}

const jobs = [];
if (!targets.length) {
  for (const key of MODEL_KEYS) {
    const file = fileFor(key);
    if (file) jobs.push({ file, key });
  }
} else {
  for (const target of targets) {
    if (MODEL_KEYS.includes(target)) {
      const file = fileFor(target);
      if (!file) { console.error(`no model file for ${target}`); process.exitCode = 1; continue; }
      jobs.push({ file, key: target });
      continue;
    }
    const file = resolve(process.cwd(), target);
    if (!existsSync(file)) { console.error(`not found: ${target}`); process.exitCode = 1; continue; }
    jobs.push({ file, key: value("model", MODEL_KEYS.find((key) => file.includes(key)) || "yzf-2021") });
  }
}

if (!jobs.length) {
  console.error("nothing to inspect. drop a model.glb or scene.gltf in web/store/models/<key>/");
  process.exit(1);
}

const results = jobs.map(({ file, key }) => inspect(file, key));
if (flag("json")) {
  console.log(JSON.stringify(results.map((info) => ({
    model: info.modelKey, file: basename(info.file), size: info.size, nodes: info.nodes,
    meshes: info.meshes, materials: info.materials, triangles: info.tris,
    extensions: info.extensions,
    parts: info.rows.reduce((map, row) => { const key = row.key || "UNMATCHED"; map[key] = (map[key] || 0) + 1; return map; }, {}),
    names: info.names.map((entry) => ({ name: entry.label, meshes: entry.meshes, triangles: entry.tris, part: entry.key })),
  })), null, 2));
} else {
  results.forEach(report);
  console.log("");
  console.log(`  part labels: ${Object.keys(PART_LABELS).length} keys · edit BIKE_PARTS / CAR_PARTS in web/counter/js/viewer3d.js`);
  console.log("");
}
