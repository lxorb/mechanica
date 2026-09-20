/**
 * Sketchfab shortlist builder for the generic vehicle models. Owner: vehicle-models agent.
 *
 *   node web/tools/sketchfab-search.mjs            # search, write the candidate pool
 *   node web/tools/sketchfab-search.mjs --shots    # also download 1024px thumbnails to look at
 *
 * Unauthenticated /v3/search. Downloads need a user token (see model-sources.md); this script
 * only shortlists. Output: web/tools/.sketchfab-candidates.json (gitignored scratch).
 */

import { writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, ".sketchfab-candidates.json");
const SHOTS = join(HERE, ".sketchfab-shots");

/** Licences we may ship. Sketchfab slugs. */
const OK_LICENSE = new Set(["cc0", "by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"]);
const SHIPPABLE = new Set(["cc0", "by", "by-sa", "by-nc-sa", "by-nc"]);

/** type -> the queries that actually surface that shape of vehicle. */
const QUERIES = {
  motocross: ["motocross", "dirt bike", "ktm sx", "yamaha yz", "honda crf", "kawasaki kx", "mx bike", "cross motorcycle"],
  enduro: ["enduro motorcycle", "ktm exc", "dual sport motorcycle", "enduro bike", "husqvarna motorcycle", "off road motorcycle"],
  supermoto: ["supermoto", "motard", "ktm smc", "supermotard"],
  sportbike: ["sport bike", "yamaha r1", "yamaha r6", "kawasaki ninja", "ducati panigale", "suzuki gsxr", "superbike", "honda cbr", "sportbike motorcycle", "bmw s1000rr"],
  naked: ["naked bike", "ktm duke", "streetfighter motorcycle", "yamaha mt", "ducati monster", "naked motorcycle", "roadster motorcycle", "kawasaki z900"],
  adventure: ["adventure motorcycle", "bmw gs", "africa twin", "adventure bike", "tenere", "v-strom", "dual purpose motorcycle"],
  touring: ["touring motorcycle", "gold wing", "bagger motorcycle", "bmw k1600", "grand tourer motorcycle", "sport touring motorcycle"],
  cruiser: ["cruiser motorcycle", "harley davidson", "chopper motorcycle", "bobber motorcycle", "harley", "indian motorcycle", "custom motorcycle"],
  scooter: ["scooter", "vespa", "motor scooter", "maxi scooter", "moped", "piaggio", "yamaha nmax", "honda pcx"],
  classic: ["cafe racer", "classic motorcycle", "vintage motorcycle", "royal enfield", "triumph bonneville", "retro motorcycle", "old motorcycle"],
  trial: ["trial motorcycle", "trials bike", "montesa cota", "gas gas trial"],
  minibike: ["honda grom", "mini bike", "monkey bike", "pit bike", "pocket bike", "minibike motorcycle"],
  car: ["sports car", "corvette", "porsche 911", "supercar", "coupe", "muscle car"],
  sedan: ["sedan", "saloon car", "bmw sedan", "family car", "hatchback"],
  suv: ["suv", "crossover suv", "range rover", "jeep", "4x4 suv"],
  pickup: ["pickup truck", "ford f150", "pickup", "chevrolet silverado"],
};

/** Tags/words that mean "this is not the vehicle, it is a scene, a part or an animal". */
const REJECT = /\b(helmet|hornet|wasp|insect|bee|diorama|scene|city|street|garage|room|house|building|interior|track|map|level|environment|character|rider|person|man|woman|glove|jacket|boot|tire only|wheel only|engine only|logo|badge|sign|toy|lego|minecraft|voxel|sticker|poster|showroom|parking)\b/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function search(q, count = 24, cursor = 0) {
  const url = new URL("https://api.sketchfab.com/v3/search");
  url.searchParams.set("type", "models");
  url.searchParams.set("q", q);
  url.searchParams.set("downloadable", "true");
  url.searchParams.set("sort_by", "-likeCount");
  url.searchParams.set("count", String(count));
  url.searchParams.set("categories", "cars-vehicles");
  if (cursor) url.searchParams.set("cursor", String(cursor));
  url.searchParams.set("archives_flavours", "false");
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (res.status === 429) { await sleep(3000 * (attempt + 1)); continue; }
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const body = await res.json();
      return body.results || [];
    } catch (error) {
      if (attempt === 2) { console.warn(`  ! ${q}: ${error.message}`); return []; }
      await sleep(1500 * (attempt + 1));
    }
  }
  return [];
}

/**
 * /v3/search does not return license, faceCount or textureCount — only /v3/models/{uid} does,
 * and those three are exactly what decides whether a model is shippable and web-sized. So the
 * search is a cheap net and this is the second pass over what it caught.
 */
async function detail(uid) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(`https://api.sketchfab.com/v3/models/${uid}`, { headers: { Accept: "application/json" } });
      if (res.status === 429) { await sleep(2500 * (attempt + 1)); continue; }
      if (!res.ok) return null;
      return await res.json();
    } catch {
      await sleep(1200 * (attempt + 1));
    }
  }
  return null;
}

async function pooled(items, limit, worker) {
  const out = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: limit }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await worker(items[i], i);
    }
  }));
  return out;
}

const thumbOf = (m, want = 1024) => {
  const images = (m.thumbnails && m.thumbnails.images) || [];
  const sorted = [...images].sort((a, b) => a.width - b.width);
  return (sorted.find((i) => i.width >= want) || sorted[sorted.length - 1] || {}).url || null;
};

function score(row) {
  // likes dominate (the only proxy we have for "well modelled"), views break ties, and a face
  // count in the 25k-900k band is what survives a Draco pass under 5 MB without looking like a
  // toy. Textures matter as much as geometry here: an untextured model cannot read as a bike.
  const faces = row.faces || 0;
  const band = faces >= 25000 && faces <= 900000 ? 1 : faces > 900000 ? 0.5 : faces >= 8000 ? 0.45 : 0.2;
  const tex = row.textures >= 3 ? 1 : row.textures > 0 ? 0.75 : 0.35;
  const junk = REJECT.test(`${row.name} ${(row.tags || []).join(" ")}`) ? 0.15 : 1;
  const picked = row.staffpicked ? 1.15 : 1;
  return Math.round(
    (Math.log10((row.likes || 0) + 1) * 100 + Math.log10((row.views || 0) + 1) * 20) * band * tex * junk * picked,
  );
}

const lic = (m) => (m.license && (m.license.slug || m.license.label)) || "";

async function main() {
  const wantShots = process.argv.includes("--shots");
  const pool = new Map();
  for (const [type, queries] of Object.entries(QUERIES)) {
    for (const q of queries) {
      const results = [...(await search(q)), ...(await search(q, 24, 24))];
      for (const m of results) {
        const prev = pool.get(m.uid);
        pool.set(m.uid, {
          uid: m.uid,
          name: m.name,
          author: (m.user && (m.user.displayName || m.user.username)) || "",
          authorUrl: (m.user && m.user.profileUrl) || "",
          url: m.viewerUrl,
          likes: m.likeCount || 0,
          views: m.viewCount || 0,
          animated: (m.animationCount || 0) > 0,
          staffpicked: !!m.staffpickedAt,
          tags: (m.tags || []).map((t) => t.slug).slice(0, 12),
          thumb: thumbOf(m),
          types: prev ? [...new Set([...prev.types, type])] : [type],
          queries: prev ? [...new Set([...prev.queries, q])] : [q],
        });
      }
      process.stdout.write(`. ${type}/${q} -> ${results.length}\n`);
      await sleep(200);
    }
  }

  // second pass: the fields that decide shippability only exist on the detail endpoint
  const found = [...pool.values()]
    .filter((r) => !REJECT.test(`${r.name} ${r.tags.join(" ")}`))
    .sort((a, b) => b.likes - a.likes)
    .slice(0, 700);
  console.log(`\n${pool.size} hits, fetching detail for the top ${found.length}…`);
  let done = 0;
  await pooled(found, 8, async (row) => {
    const d = await detail(row.uid);
    done += 1;
    if (done % 60 === 0) process.stdout.write(`  ${done}/${found.length}\n`);
    if (!d) return;
    row.license = lic(d);
    row.licenseLabel = (d.license && d.license.label) || "";
    row.shippable = SHIPPABLE.has(row.license);
    row.faces = d.faceCount || 0;
    row.vertices = d.vertexCount || 0;
    row.textures = d.textureCount || 0;
    row.score = score(row);
  });

  const rows = found.filter((r) => OK_LICENSE.has(r.license || "")).sort((a, b) => b.score - a.score);
  await writeFile(OUT, JSON.stringify(rows, null, 2));
  console.log(`\n${rows.length} candidates -> ${OUT}`);
  const byType = {};
  for (const r of rows) for (const t of r.types) (byType[t] ||= []).push(r);
  for (const [t, list] of Object.entries(byType)) {
    console.log(`\n== ${t} (${list.length})`);
    for (const r of list.slice(0, 8)) {
      console.log(`  ${r.score.toString().padStart(4)} ${r.license.padEnd(8)} ${String(r.likes).padStart(5)}♥ ${String(Math.round(r.faces / 1000)).padStart(4)}kf  ${r.name.slice(0, 44).padEnd(44)} ${r.author.slice(0, 20)}  ${r.uid}`);
    }
  }
  if (wantShots) {
    await mkdir(SHOTS, { recursive: true });
    const top = [];
    for (const list of Object.values(byType)) top.push(...list.slice(0, 8));
    const seen = new Set();
    for (const r of top) {
      if (seen.has(r.uid) || !r.thumb) continue;
      seen.add(r.uid);
      const res = await fetch(r.thumb);
      if (!res.ok) continue;
      const buf = Buffer.from(await res.arrayBuffer());
      await writeFile(join(SHOTS, `${r.types[0]}-${r.uid.slice(0, 8)}.jpg`), buf);
    }
    console.log(`\n${seen.size} thumbnails -> ${SHOTS}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
