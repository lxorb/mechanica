# Where the 3D vehicle models come from

Owner: vehicle-models agent. Companion to `web/store/models/CREDITS.md` — that file is the
attribution we owe the authors, this one is the working record: what was searched, what was
rejected and why, and what is still missing.

## The shape of the problem

The app knows 22.3k bikes and ships 3 models. `web/counter/js/vehicle-type.js` sorts every bike
into one of 13 types, and each type gets one **generic** model that stands in for it — a
motocrosser for a KTM 450 SX-F, a scooter for a Vespa. Three bikes get their **exact** model.
So the target is ~14-30 models, not 22,300.

| | |
| --- | --- |
| budget | ≤ 5 MB per GLB after Draco + 1024px webp textures |
| licences we may ship | CC0, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA (hackathon demo — the NC ones must be swapped before anything is sold) |
| licences we may **not** ship | anything ND (no derivatives): recompressing the mesh *is* a derivative |
| must have | recognisable silhouette for its type, textures, node names we can map to part groups |

## Why Sketchfab and not the CC0 asset packs

The first pass looked at the no-account sources: **poly.pizza**, **Quaternius**, **Kenney**,
**glTF Sample Assets**. All four are genuinely free and genuinely downloadable without a login,
and all four are wrong for this app. Their vehicle packs are *stylised low-poly* — a Kenney car is
about 400 triangles with flat-colour materials and no part separation at all. Next to the 372k-tri
Sketchfab YZF the app already ships, a Kenney scooter next to it does not read as "the same app
showing a different bike", it reads as a broken asset. They also have no motorcycle coverage worth
the name: no motocrosser, no enduro, no supermoto, no trials bike.

So: Sketchfab, with the founder's API token for the download endpoint.

## The pipeline

```sh
node web/tools/sketchfab-search.mjs --shots   # unauthenticated /v3/search -> candidate pool
                                              # + 1024px thumbnails to look at
# curate by eye into web/tools/model-shortlist.json
node web/tools/models-fetch.mjs               # /v3/models/{uid}/download -> zip -> convert
node web/tools/viewer-shots.mjs               # render each one in headless Chrome
```

`/v3/search` does **not** return `license`, `faceCount` or `textureCount` — the three fields that
decide whether a model is shippable and web-sized — so `sketchfab-search.mjs` uses the search as a
cheap net (64 queries x 48 results, filtered to `categories=cars-vehicles`) and then fetches
`/v3/models/{uid}` for the top 700 by likes. Candidates are ranked by

```
log10(likes) * 100 + log10(views) * 20   x  face-count band  x  texture factor  x  junk penalty
```

where the face-count band prefers 25k-900k triangles (what survives Draco under 5 MB without
looking like a toy), the texture factor halves anything untextured, and the junk penalty kills the
helmets, dioramas, city scenes and — genuinely — the *Vespa crabro* hornets that a search for
"vespa" returns.

The token is read from `C:\Users\me\agent-secrets\sketchfab.txt` at call time, never printed and
never written into any output file. Search needs no token; only the download endpoint does.

### Conversion

`gltf-transform` 4.5: `dedup` → `instance` → `resize 1024` → `webp` → `draco`. Two things are
deliberately **not** in that list:

- **`join` / `flatten`** — they merge meshes, and the node tree *is* the part structure the viewer
  matches `front-wheel` / `fuel-tank` / `exhaust` against. Joining a model saves a megabyte and
  destroys explode, highlight and focus on it.
- **aggressive `--quantize`** — faceting shows on a fuel tank, which is the one surface a viewer
  looks straight at.

If the result is still over 5 MB the textures are retried at 512px.

## Status

See `web/store/models/CREDITS.md` for the models that actually shipped, with author, licence,
size and triangle count. Anything in the shortlist that is not in CREDITS.md either failed to
download, failed to convert under budget, or turned out to be the wrong shape once rendered — the
run log of `models-fetch.mjs` says which.

### Known gaps

- **trials** and **supermoto** are the thinnest categories on Sketchfab. A trials bike is a niche
  machine and "trial" as a search word mostly returns free-trial marketing assets; supermoto
  returns motocrossers with road wheels, which is *nearly* right and is what we take. If neither
  yields something good, `vehicle-type.js` can point both at the enduro generic — the silhouettes
  are one wheel-swap apart — by editing `GENERIC.trial` / `GENERIC.supermoto`.
- **minibike** has one real candidate family (Honda Grom / monkey-bike clones).
- **touring** is well covered by Gold Wing and bagger models, but most of the good ones are
  1M+ triangles and need the 512px texture pass.
- Cars beyond the Corvette (sedan / SUV / pickup) are the *best*-covered category on Sketchfab by
  a wide margin — the app has almost no cars in its roster, so they are the lowest priority.

## Rejected, and why

| what | why |
| --- | --- |
| Kenney Car Kit, Quaternius vehicle packs | CC0 and instant, but 300-800 tri flat-shaded — cannot sit next to the existing Sketchfab models |
| poly.pizza | same problem; its motorcycle coverage is a handful of stylised scooters |
| glTF Sample Assets | no vehicles beyond the 2CV and the Toy Car; both are test fixtures, not catalogue models |
| anything CC BY-ND / CC BY-NC-ND | recompressing is a derivative work, so ND rules it out however good the model |
| models with `animationCount > 0` and rigged riders | the rider is part of the mesh and cannot be separated cheaply |
