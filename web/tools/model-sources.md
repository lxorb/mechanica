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

Eleven generic models ship, covering every type but two. Author, licence, size and triangle count
are in `web/store/models/CREDITS.md`, generated from what is on disk; this is the working record
of which model was chosen and why.

| type | model | author | licence | size | why this one |
| --- | --- | --- | --- | --- | --- |
| `sportbike` | [Kawasaki Ninja ZX-6R](https://sketchfab.com/3d-models/kawasaki-ninja-zx-6r-4af2b6840b8045a5af5e8df8a85f04fa) | valvetin | by | 2.33 MB | 336k faces, full fairing, Kawasaki lime — the clearest sportbike silhouette in the CC pool |
| `naked` | [2024 Ducati Streetfighter V4 S](https://sketchfab.com/3d-models/2024-ducati-streetfighter-v4-s-c501252f8af64c559bf91dc306c3a550) | OUTPISTON | by-nc-sa | 1.45 MB | 102k faces, exposed engine and trellis frame — the naked shape, and the app's biggest bucket |
| `cruiser` | [Harley Davidson Breakout](https://sketchfab.com/3d-models/harley-davidson-breakout-7d446ec9135c4e35892714d117b37268) | FWSean | by | 0.95 MB | 43k faces, V-twin, raked forks, fat rear — reads as a cruiser at a glance |
| `scooter` | [Vespa](https://sketchfab.com/3d-models/vespa-hp-5431bb42de5743088c849ba080e7ac33) | fox_amelie | by | 1.18 MB | 131k faces, step-through monocoque — the scooter everyone pictures; 8.3% of the roster |
| `classic` | [Cafe Racer](https://sketchfab.com/3d-models/cafe-racer-c02dec85ac0541b8ab6dd56098706b50) | Andrei Milin | by | 1.37 MB | 95k faces — the Triumph Bonneville it replaced needed join+simplify to fit the budget and came out as a black slab |
| `motocross` | [2022 Yamaha YZ450F](https://sketchfab.com/3d-models/2022-yamaha-yz450f-dfff1637219f44d6bfa3ed3c9708d523) | Res1n | by | 1.16 MB | 180k faces, 5 textures — long-travel forks, knobbly tyres, number plates: the MX shape |
| `enduro` | [Honda NXR Bros 2003](https://sketchfab.com/3d-models/none-2e88ff65e98e4d0c802242bdeccaf28d) | andersonfo | by | 1.91 MB | dual-sport trail bike with a headlight and mirrors — the enduro, not the race MX |
| `supermoto` | [KTM REDBULL](https://sketchfab.com/3d-models/ktm-redbull-8d755ea9d6c249a29cf771a921116a41) | LEKSA | by | 0.41 MB | the Husqvarna FS 450 it replaced ships welded to a paddock stand that dominates the frame |
| `touring` | [Yamaha Tracer 9 Moto](https://sketchfab.com/3d-models/yamaha-tracer-9-moto-5611ae9df1ef471da647a0d8b1e9c235) | alban | by | 1.38 MB | sport-tourer: fairing, screen, upright bars — the Polizei model it replaced converted to flat panels |
| `adventure` | [Akt Tt Ds 200 repainted](https://sketchfab.com/3d-models/akt-tt-ds-200-repainted-c32f7b87090d4ce4b10c76e844dc86cd) | e-restrepo1114 | by | 0.93 MB | dual-sport: tall stance, beak front mudguard, wire wheels — the adventure shape |
| `car` | [Mazda RX-7 FC](https://sketchfab.com/3d-models/mazda-rx-7-fc-8ac0df459f514950ab83ac37109a06ab) | Lexyc16 | by | 0.46 MB | 41k faces — the non-Corvette car, for any four-wheeler that is not a Stingray |

Two types have no model of their own and point at the nearest silhouette in
`vehicle-type.js` — `trial -> enduro` and `minibike -> naked`. A trials bike is an enduro without
a seat and a Grom is a small naked, so at viewer scale both read correctly; between them they are
2% of the roster. Neither has a usable CC-licensed, downloadable model on Sketchfab: "trial"
mostly returns free-trial marketing assets, and the minibike results are untextured.

### Three that had to be replaced after rendering them

A model can look right on its Sketchfab thumbnail and be unusable once converted. These were
caught by `node web/tools/viewer-shots.mjs --sheet`, which is the reason that tool exists.

| type | rejected | what went wrong |
| --- | --- | --- |
| classic | Triumph Bonneville (zizian) | 3,900 tiny primitives. Draco *tripled* it (21 MB -> 50 MB), meshopt got it to 8.5 MB, and joining + simplifying to fit 5 MB turned it into a black slab. |
| touring | Polizei Motorbike (solid3DDD) | converted to a set of flat panels — unrecognisable as a motorcycle. |
| supermoto | Husqvarna FS 450 (OUTPISTON) | modelled welded to a paddock stand, which dominates the frame and cannot be stripped by shape. |

### Two things that had to be handled per model, and one that did not

- **Scenery.** Sketchfab authors park the vehicle on a ground plane or a turntable and publish
  the lot. The viewer normalises whatever it loads to a unit bounding sphere, so a 300-unit floor
  under a 2-unit motorcycle makes the motorcycle a speck — the Harley rendered thumbnail-sized.
  `stripScenery()` drops meshes named like scenery and any huge flat slab; it caught a
  `pPlane1_Floor_0` and a `Mesh473_Groundcover_BarkChips_0`.
- **Which way is up.** Exporters disagree, and the Yamaha YZ450F arrived Z-up and rendered as a
  plan view. `uprightRotation()` guesses from the proportions, but the guess is only a
  *suggestion*: it wanted to lay the Vespa on its side, because a scooter is nearly as wide as it
  is tall. So the shortlist's `rotate` always wins, and every value in it was chosen by looking at
  `node web/tools/viewer-shots.mjs --rotations <name>` — nine candidate rotations on one sheet.
- **Which end is the front.** Not guessable at all; `orient` is set by eye the same way.

### Compression

Draco and meshopt win on completely different models, so both are tried and the smaller file
wins — Draco on the Kawasaki (217 clean meshes), meshopt on anything built from thousands of tiny
primitives, where Draco's per-primitive headers cost more than they save. Every stage is kept only
if it actually shrank the file.

