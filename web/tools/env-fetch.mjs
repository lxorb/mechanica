/**
 * Fetches the Poly Haven panorama the 3D viewer stands its vehicles in. Owner: vehicle-models.
 *
 *   node web/tools/env-fetch.mjs                 # auto_service, every size the viewer wants
 *   node web/tools/env-fetch.mjs kloppenheim_06  # a different one
 *
 * Writes web/store/models/env/<name>-{1k,2k}.hdr and -{4k,8k}.jpg. Poly Haven is CC0; it is
 * credited in web/store/models/CREDITS.md anyway.
 *
 * Why four files. The .hdr and the .jpg are not two resolutions of one thing, they are two jobs:
 *
 *   .hdr  drives the lighting. It goes through PMREMGenerator into scene.environment and is never
 *         looked at directly, so 1k on phones and 2k on desktop is already more than the
 *         roughness-blurred mips can show.
 *   .jpg  IS the picture. It is what you actually see behind the bike, and since the founder's
 *         note the viewer renders it with backgroundBlurriness = 0 — nothing hides the pixels any
 *         more. Poly Haven's own tonemapped export is 8192x4096 and about 5 MB, which is the
 *         sharpest per byte this gets; the 4k is a resize of the same file and loads first.
 *
 * The 8k is only fetched on desktop at runtime (see loadEnvironment in js/viewer3d.js), after the
 * 4k is already on screen.
 */

import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENV = resolve(HERE, "..", "store", "models", "env");
const SHARP = process.env.SHARP_DIR
  || "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/sharp/dist/index.cjs";

const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

async function grab(url, file) {
  if (existsSync(file) && statSync(file).size > 50_000) {
    console.log(`  = ${file.split(/[\\/]/).pop()} ${mb(statSync(file).size)}`);
    return file;
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  writeFileSync(file, Buffer.from(await res.arrayBuffer()));
  console.log(`  + ${file.split(/[\\/]/).pop()} ${mb(statSync(file).size)}`);
  return file;
}

async function main() {
  const name = process.argv[2] || "auto_service";
  mkdirSync(ENV, { recursive: true });
  const res = await fetch(`https://api.polyhaven.com/files/${name}`);
  if (!res.ok) throw new Error(`no such Poly Haven asset: ${name}`);
  const files = await res.json();

  for (const size of ["1k", "2k"]) {
    const url = files.hdri?.[size]?.hdr?.url;
    if (url) await grab(url, join(ENV, `${name}-${size}.hdr`));
    else console.log(`  ! no ${size} hdr`);
  }

  // the tonemapped export is 8192x4096 — exactly the 8k backdrop, no resizing needed
  const tone = files.tonemapped?.url;
  if (!tone) { console.log("  ! no tonemapped jpg offered"); return; }
  const eight = await grab(tone, join(ENV, `${name}-8k.jpg`));

  const four = join(ENV, `${name}-4k.jpg`);
  if (existsSync(four) && statSync(four).size > 50_000) {
    console.log(`  = ${name}-4k.jpg ${mb(statSync(four).size)}`);
  } else {
    const sharp = (await import(`file:///${SHARP.replace(/\\/g, "/")}`)).default;
    await sharp(eight)
      .resize({ width: 4096, height: 2048, fit: "fill", kernel: "lanczos3" })
      .jpeg({ quality: 90, mozjpeg: true, chromaSubsampling: "4:4:4" })
      .toFile(four);
    console.log(`  + ${name}-4k.jpg ${mb(statSync(four).size)}`);
  }

  console.log(`\n${name}: hdr for the light, jpg for the picture. Set DEFAULT_ENV in js/viewer3d.js.`);
}

main().catch((error) => { console.error(error.message); process.exit(1); });
