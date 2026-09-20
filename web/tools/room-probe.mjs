/**
 * Prints the geometry of an environment room GLB. Owner: vehicle-models agent.
 *
 *   node web/tools/room-probe.mjs                          # garage-interior.glb
 *   node web/tools/room-probe.mjs <file-in-store/models/env>
 *
 * The viewer normalises every vehicle to a unit bounding sphere and then has to scale a room to
 * suit it. Getting that scale wrong puts the camera inside a wall, so this prints what the room
 * actually is: overall span, the floor plane, and the biggest pieces by extent.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENV = resolve(HERE, "..", "store", "models", "env");
const LIB = process.env.GLTF_LIB
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules";

async function lib(name) {
  const pkg = JSON.parse(readFileSync(join(LIB, name, "package.json"), "utf8"));
  const entry = (pkg.exports && (pkg.exports["."]?.import?.default || pkg.exports["."]?.import
    || pkg.exports["."]?.default || (typeof pkg.exports["."] === "string" ? pkg.exports["."] : null)))
    || pkg.module || pkg.main || "index.js";
  return import(pathToFileURL(join(LIB, name, entry)).href);
}

async function main() {
  const file = join(ENV, process.argv[2] || "garage-interior.glb");
  const { NodeIO } = await lib("@gltf-transform/core");
  const { ALL_EXTENSIONS } = await lib("@gltf-transform/extensions");
  const draco = await lib("draco3dgltf");
  const meshopt = await lib("meshoptimizer");
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    "draco3d.decoder": await draco.createDecoderModule(),
    "meshopt.decoder": meshopt.MeshoptDecoder,
  });
  const document = await io.read(file);
  const root = document.getRoot();

  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  let triangles = 0;
  const pieces = [];
  for (const mesh of root.listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const pos = prim.getAttribute("POSITION");
      if (!pos) continue;
      const lo = pos.getMin([]);
      const hi = pos.getMax([]);
      for (let i = 0; i < 3; i++) { min[i] = Math.min(min[i], lo[i]); max[i] = Math.max(max[i], hi[i]); }
      const indices = prim.getIndices();
      triangles += indices ? indices.getCount() / 3 : pos.getCount() / 3;
      pieces.push({
        name: mesh.getName() || "(unnamed)",
        span: [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]].map((v) => +v.toFixed(2)),
        minY: +lo[1].toFixed(2),
      });
    }
  }
  const span = max.map((v, i) => +(v - min[i]).toFixed(2));
  console.log(`${file.split(/[\\/]/).pop()}`);
  console.log(`  meshes ${root.listMeshes().length} · nodes ${root.listNodes().length} · ${Math.round(triangles).toLocaleString()} tris`);
  console.log(`  min ${min.map((v) => +v.toFixed(2)).join(", ")}`);
  console.log(`  max ${max.map((v) => +v.toFixed(2)).join(", ")}`);
  console.log(`  span ${span.join(" x ")}   (x, y=up?, z)`);
  console.log(`  node transforms: ${root.listNodes().slice(0, 6).map((n) => `${n.getName() || "?"} s=${n.getScale().map((v) => +v.toFixed(2)).join(",")}`).join(" | ")}`);
  console.log("  biggest pieces:");
  for (const piece of pieces.sort((a, b) => Math.max(...b.span) - Math.max(...a.span)).slice(0, 8)) {
    console.log(`    ${piece.name.padEnd(28)} ${piece.span.join(" x ").padEnd(26)} floor y ${piece.minY}`);
  }
}

main().catch((error) => { console.error(error.message); process.exit(1); });
