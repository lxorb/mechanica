/**
 * Per-type shortlist for the generic models. Owner: vehicle-models agent.
 *
 *   node web/tools/sketchfab-pick.mjs            # shortlist -> .sketchfab-picks.json + a table
 *   node web/tools/sketchfab-pick.mjs --shots    # also save each candidate's 1024px thumbnail
 *
 * The broad sweep in sketchfab-search.mjs fetches /v3/models/{uid} for 700 uids and gets rate
 * limited doing it. This one asks for far less: `license=` IS supported as a search filter, so
 * the licence check happens server-side, and only the top few per (type, licence) need a detail
 * call for their face count. ~16 types x 5 licences x 1 search + ~120 details, not 700.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, ".sketchfab-picks.json");
const SHOTS = join(HERE, ".sketchfab-shots");

/** In preference order: CC0 first because it carries no obligation at all. */
const LICENSES = ["cc0", "by", "by-sa", "by-nc-sa", "by-nc"];

/** type -> queries. Kept short: one detail call per result is the expensive part. */
const QUERIES = {
  motocross: ["motocross", "dirt bike", "motocross bike ktm", "enduro cross bike"],
  enduro: ["enduro motorcycle", "off road motorcycle", "dual sport motorcycle"],
  supermoto: ["supermoto", "motard motorcycle"],
  sportbike: ["sport bike", "superbike motorcycle", "racing motorcycle", "sportbike"],
  naked: ["naked motorcycle", "streetfighter motorcycle", "roadster motorcycle", "street motorcycle"],
  adventure: ["adventure motorcycle", "adventure touring bike", "rally motorcycle"],
  touring: ["touring motorcycle", "bagger motorcycle", "gold wing motorcycle"],
  cruiser: ["cruiser motorcycle", "chopper motorcycle", "bobber motorcycle", "harley davidson"],
  scooter: ["scooter", "vespa scooter", "moped scooter"],
  classic: ["cafe racer motorcycle", "vintage motorcycle", "classic motorcycle"],
  trial: ["trial motorcycle", "trials motorcycle"],
  minibike: ["mini bike motorcycle", "honda grom", "pit bike"],
  car: ["sports car", "supercar", "coupe car"],
  sedan: ["sedan car", "hatchback car"],
  suv: ["suv car", "offroad suv"],
  pickup: ["pickup truck"],
};

const REJECT = /\b(helmet|hornet|wasp|insect|bee|crabro|diorama|scene|city|street kit|garage|room|house|building|interior|track|map|level|environment|character|rider|glove|jacket|boot|logo|badge|sign|lego|minecraft|voxel|sticker|poster|showroom|parking|wheel$|tire$|engine$|seat$|helmet$)\b/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function get(url, tries = 4) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (res.status === 429) { await sleep(4000 * (i + 1)); continue; }
      if (!res.ok) return null;
      return await res.json();
    } catch {
      await sleep(1500 * (i + 1));
    }
  }
  return null;
}

async function search(q, license, count = 12) {
  const url = new URL("https://api.sketchfab.com/v3/search");
  url.searchParams.set("type", "models");
  url.searchParams.set("q", q);
  url.searchParams.set("downloadable", "true");
  url.searchParams.set("sort_by", "-likeCount");
  url.searchParams.set("categories", "cars-vehicles");
  url.searchParams.set("license", license);
  url.searchParams.set("count", String(count));
  url.searchParams.set("archives_flavours", "false");
  const body = await get(url);
  return (body && body.results) || [];
}

const thumbOf = (m, want = 1024) => {
  const images = [...(((m.thumbnails || {}).images) || [])].sort((a, b) => a.width - b.width);
  return (images.find((i) => i.width >= want) || images.at(-1) || {}).url || null;
};

function score(row) {
  const faces = row.faces || 0;
  const band = faces >= 25000 && faces <= 900000 ? 1 : faces > 900000 ? 0.55 : faces >= 8000 ? 0.4 : 0.15;
  const tex = row.textures >= 3 ? 1 : row.textures > 0 ? 0.7 : 0.3;
  const free = row.license === "cc0" ? 1.1 : row.license === "by" ? 1.05 : 1;
  return Math.round(Math.log10((row.likes || 0) + 1) * 100 * band * tex * free + Math.log10((row.views || 0) + 1) * 10);
}

async function main() {
  const wantShots = process.argv.includes("--shots");
  const pool = new Map();
  for (const [type, queries] of Object.entries(QUERIES)) {
    for (const license of LICENSES) {
      for (const q of queries) {
        for (const m of await search(q, license)) {
          if (REJECT.test(m.name)) continue;
          const prev = pool.get(m.uid);
          pool.set(m.uid, {
            uid: m.uid, name: m.name, license,
            author: (m.user || {}).displayName || (m.user || {}).username || "",
            authorUrl: (m.user || {}).profileUrl || "",
            url: m.viewerUrl, likes: m.likeCount || 0, views: m.viewCount || 0,
            animated: (m.animationCount || 0) > 0, staffpicked: !!m.staffpickedAt,
            tags: (m.tags || []).map((t) => t.slug).slice(0, 10),
            thumb: thumbOf(m),
            types: prev ? [...new Set([...prev.types, type])] : [type],
          });
        }
        await sleep(120);
      }
    }
    process.stdout.write(`. ${type} -> ${[...pool.values()].filter((r) => r.types.includes(type)).length}\n`);
  }

  // detail only for the best few per type — that is where the rate limit bites
  const wanted = new Set();
  for (const type of Object.keys(QUERIES)) {
    const list = [...pool.values()].filter((r) => r.types.includes(type)).sort((a, b) => b.likes - a.likes).slice(0, 10);
    for (const row of list) wanted.add(row.uid);
  }
  console.log(`\n${pool.size} candidates, detail for ${wanted.size}…`);
  let n = 0;
  for (const uid of wanted) {
    const d = await get(`https://api.sketchfab.com/v3/models/${uid}`, 3);
    const row = pool.get(uid);
    if (d) {
      row.faces = d.faceCount || 0;
      row.vertices = d.vertexCount || 0;
      row.textures = d.textureCount || 0;
      row.license = (d.license && d.license.slug) || row.license;
    }
    row.score = score(row);
    if (++n % 25 === 0) process.stdout.write(`  ${n}/${wanted.size}\n`);
    await sleep(90);
  }

  const rows = [...pool.values()].filter((r) => wanted.has(r.uid)).sort((a, b) => b.score - a.score);
  await writeFile(OUT, JSON.stringify(rows, null, 2));
  console.log(`\n${rows.length} -> ${OUT}\n`);
  for (const type of Object.keys(QUERIES)) {
    const list = rows.filter((r) => r.types.includes(type)).slice(0, 7);
    console.log(`== ${type}`);
    for (const r of list) {
      console.log(`  ${String(r.score).padStart(4)} ${r.license.padEnd(8)} ${String(r.likes).padStart(5)}h ${String(Math.round((r.faces || 0) / 1000)).padStart(4)}kf ${String(r.textures || 0).padStart(2)}t  ${r.name.slice(0, 40).padEnd(40)} ${r.author.slice(0, 18).padEnd(18)} ${r.uid}`);
    }
  }

  if (wantShots) {
    await mkdir(SHOTS, { recursive: true });
    for (const type of Object.keys(QUERIES)) {
      for (const r of rows.filter((x) => x.types.includes(type)).slice(0, 7)) {
        if (!r.thumb) continue;
        const res = await fetch(r.thumb).catch(() => null);
        if (!res || !res.ok) continue;
        await writeFile(join(SHOTS, `${type}-${String(r.score).padStart(4, "0")}-${r.uid.slice(0, 8)}.jpg`), Buffer.from(await res.arrayBuffer()));
      }
    }
    console.log(`\nthumbnails -> ${SHOTS}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
