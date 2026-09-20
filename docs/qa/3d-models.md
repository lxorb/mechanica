# Replacing the four generics that could not explode — 2026-09-20

`docs/qa/3d-parts.md` ends with four rows reading **1 group · no explode**: `generic/cruiser`,
`generic/touring`, `generic/scooter`, `generic/adventure`. Those four were not a regex problem —
the Harley Breakout was literally *one* mesh, the Vespa was seven material sweeps, and the Akt Tt
Ds 200 had 84 good meshes and called every one of them `defaultMaterial`. No table can split
geometry that was never split. They are replaced here, and the KTM's stray mesh is deleted.

Selection rule, from `docs/qa/3d-parts.md`: **mesh count and node naming, never triangle count.**
The measurement that decides it is "how many meshes span more than 60 % of the model" — a model
whose meshes are all whole-bike sweeps is merged by material and cannot come apart, however many
triangles it has.

## Before → after

| model | groups before | groups after | file | what it is now |
| --- | --- | --- | --- | --- |
| `generic/cruiser` | **1** | **18** | 0.95 → 6.67 MB | Harley EL OHV V-Twin, 429 separate meshes |
| `generic/touring` | **1** | **14** | 4.48 → 2.17 MB | Harley Road King police bagger, 81 meshes |
| `generic/scooter` | **1** | **15** | 1.18 → 1.66 MB | Vespa with a fully named node tree, 131 meshes |
| `generic/adventure` | **1** | **13** | 0.93 → 3.13 MB | Honda CB500X, 121 meshes with Honda part names |
| `generic/supermoto` | 14 | 14 | 0.41 → 0.38 MB | unchanged count; the stray mesh is gone, see below |

Nothing else moved. `model-check --summary` for all 14 shipped models after the pass:

```
  yzf-2021              16      generic/enduro        10
  honda-cbr650r         14      generic/motocross     14
  corvette-c8           15      generic/naked         18
  generic/adventure     13      generic/scooter       15
  generic/car            7      generic/sportbike     19
  generic/classic        4      generic/supermoto     14
  generic/cruiser       18      generic/touring       14
```

`partfor-test.mjs` stays **93/93**. `viewer-shots.mjs --states` stays green. A headless load of
each of the five changed models reports `state=ready`, the group count above and **no console
errors** — the only failed request in the whole run is `/favicon.ico`, which viewer-test.html has
never had and which predates this pass.

```
ok  supermoto   generic/supermoto  14 groups ·  43 meshes
ok  scooter     generic/scooter    15 groups · 131 meshes
ok  touring     generic/touring    14 groups ·  80 meshes
ok  adventure   generic/adventure  14 groups · 121 meshes
ok  cruiser     generic/cruiser    18 groups · 429 meshes
```

(The browser finds one group more on `adventure` than `model-check` does: the tool walks three
levels of parent names and the viewer walks one, so on a model whose names sit on the parent node
the two can differ by a group either way. The browser is the one that counts.)

Sheets in `docs/qa/3d-models/`, default / exploded / focused at desktop and phone, from
`viewer-shots.mjs --states3`:

| sheet | shows |
| --- | --- |
| `states3-cruiser-touring.png` (+ `-phone`) | the two Harleys coming apart, front wheel lit |
| `states3-scooter-adventure.png` (+ `-phone`) | the Vespa and the CB500X |
| `states3-supermoto.png` | the KTM at full size, with the stray mesh deleted |

## The four replacements

### `generic/cruiser` — Harley Davidson Motorcycle "EL OHV V-TWIN"
[matias_romero](https://sketchfab.com/matias_romero) · **CC BY 4.0** · 432k faces · 6.67 MB ·
**1 → 18 groups**

The best-structured vehicle in the whole CC pool: **429 separate meshes, none of them spanning
more than 51 % of the bike**, and every node named `<object>_<Material>_0` where the material is
the part — `Gas Tank`, `Front Fork`, `Exhaust Pipes`, `Engine Cylinders`, `Chain Accessories`,
`Oil Tank and Battery`, `Circuit Breaker`, `Vent and Knuckleheads`. Sixteen groups fall out of the
shared `BIKE_PARTS` table with no help at all.

Eight pins in `parts.json` finish it. Both wheels are called "rear" by the author and all their
hardware shares one material, so **the side is decided by position**, not by name: `Wheel Pieces`
at x > +0.3 is the front wheel, at x < −0.3 the rear. `Brake Pedal` → `rear-brake`,
`Circuit Breaker` + `Box Electrical` → `fuse` (a 1940s Harley's fuse is a circuit breaker),
`Gear Shift` → `footpeg`, `Vent and Knuckleheads` → `engine`, `Toolbox` → `fairing`,
`Cables and Tubes` + `Horn` → `frame`.

Built at `--texture-size 768`, not 1024 — it carries **92 images**, and 1024 put the file at
8.85 MB, over the 8 MiB target. 768 lands at 6.67 MB. Every other model here is built at 1024
exactly as `CREDITS.md` specifies.

*Not chosen:* **Harley Davidson Bike** (valerij1987, CC BY, 617k tris) has 400 meshes but only
nine groups — its materials are `Tyres and Wheels`-style sweeps, not per-part names, and its
source is 283 MB. **Harley-Davidson Police** (Comrade1280) is 81 `Object_N` meshes and became the
*touring* pick instead. **ZMN 2K Classic Harley** is 17 `Object_N` meshes, 0 groups. The archive
behind **Harley-Davidson Seventy-Two** is not a motorcycle at all — it unpacks to a Harley Quinn
character.

### `generic/touring` — Harley-Davidson Police
[Comrade1280](https://sketchfab.com/Comrade1280) · **CC BY 4.0** · 651k tris · 2.17 MB ·
**1 → 14 groups**

A Road King bagger: hard panniers, windshield, big V-twin — the touring silhouette, and lighter
on disk than the 4.48 MB Romanian Police it replaces. The node names are all `Object_N` and the
materials are colours (`chrome`, `rubber`, `main_color`), but **80 of its 81 meshes are
localised** — only the author's `floor` plane spans the model, and `strip.mjs` drops it (the
bounding box goes 2946 × 1276 × 3667 → 820 × 1276 × 2031, i.e. the floor was more than half of
what the viewer was normalising to).

So every pin here was read off the viewer-frame table — node → centre x/y → what is at that place
on a bagger. Front wheel and its brake at x +0.69, the front end and triple trees at +0.49, the
white and orange lenses at +0.56, the fairing and light bar at +0.39, bars and gauges at +0.27,
tank at +0.14, engine block at +0.04, frame at −0.20, exhaust run at −0.34, seat at −0.35, shocks
at −0.45, rear wheel at −0.61, panniers at −0.65, tail lights at −0.88 to −0.96. 73 pins, 14
groups.

*Not chosen:* **Electra Glide Police L.A.** and **Road King Special** (both everhard, CC BY,
313k / 164k faces) look the best of any candidate and cannot explode: 18 of 49 and 13 of 53 meshes
span more than 60 % of the bike, because the export is merged by material. **Sport touring
motorcycle HighPoly** (solid3DDD) is 24 meshes / 2 groups; **Yamaha Tracer 9** (alban) is 4;
**BMW K1600 GTL** (appsnation) is 30 meshes in one group at 1.09M triangles; **STZ Motorbike**
is 32 meshes of which 11 are sweeps; **Harley CVO Luxury Bagger** (Tulio Portela) is 3 meshes.

### `generic/scooter` — Worn Out Old School Vespa
[Jakob_Forseth](https://sketchfab.com/Jakob_Forseth) · **CC BY 4.0** · 80k tris · 1.66 MB ·
**1 → 15 groups**

QA-FINAL named the scooter specifically ("every scooter"), and this is the only Creative Commons
scooter whose author named the parts. The mesh nodes are all `defaultMaterial`; the names live one
level up, which is exactly the level `viewer3d.js::buildGroups` passes to `matchPart` —
`Main_body_low`, `Seat_low`, `Front_Light_low`, `Speedomter_low`, `Front_Wheel_low`,
`Back_Rim_low`, `Front_Hydrolics_low`, `Breaks_short_low`, `Exhaust_low`, `Motor_low`.

Two things needed pinning. The author spells brake **"Break"**, so `Break_Output`, `Long_Break`
and `Break_Pull*` are pinned to `front-brake` while `Break_low` — the lever, up on the bar at
y +0.44 — goes to `handlebar`; the pins are written narrow enough that the lever is not swept up
with the drum. And "Back", not "Rear", so `Back_Wheel_low` / `Back_Rim_low` / `Screws_Back` /
`Bolts_Back` are pinned to `rear-wheel` and `Back_Hydrolic*` to `rear-shock`. `M_Case_L/R` and
`Decorative_Line` are the side cowls → `fairing`, not engine.

**Unfixable by name:** `Frame_low` and `Glass_low` each occur twice — once as the speedometer
bezel at x +0.27 and once as the tail-light bezel at x −0.90 — so both pairs stay in the catch-all
rather than being pinned to a group one of them does not belong to.

*Not chosen:* **VESPA** (Stéphane Agullo, CC BY, 342k faces) was the runner-up and is genuinely
good — 91 localised meshes with French part names (`GUIDON`, `FREIN`, `PHARE`, `CADRAN`, `BOUE`) —
but two thirds of its nodes are `Object001…Object035` with nothing to read. **Vespa 150 highpoly**
(Alex_Z) is 53 `Object_N` meshes / 0 groups; **Moped Vespa Piaggio Bravo** has 33 meshes and three
named parents; **Vino** is 10 meshes; **SM Vintage Scooter 01** is 11.

### `generic/adventure` — Honda CB500X
[DevanirGrau](https://sketchfab.com/DevanirGrau) · **CC BY 4.0** · 457k faces · 3.13 MB ·
**1 → 13 groups (14 in the browser)**

The archetypal middleweight adventure bike — beak, tall screen, long-travel forks, top box — and
it is also what `vehicle-type.js` matches on (`cb ?\d{3} ?x` is in the adventure rule). 121
localised meshes carrying Honda's own part names in Portuguese and English: `STD_CB500X_Chain`,
`BASE_CB500X_EngineA`, `BASE_CB500X_Radiator`, `STD_CB500X_Muffler`, `banco` (seat),
`vidro_farol` (headlight glass), `piscas_traseiros` (rear indicators), `protetor_mao` (hand
guard), `tanque_e_carenagem` (tank and bodywork).

Eleven groups come free. Seventeen pins add the rest. The one that matters: the author reuses
`STD_CB500X_BlinkersFront` for the **front** indicators at x +0.42 *and*
`STD_CB500X_BlinkersFront001` for the **rear** ones at x −0.87, and `/indicator|blinker/` put both
in `taillight` — i.e. the tail-light group lit up the front of the bike. The front set is pinned
to `headlight`, which is where the YZF keeps its front indicator cluster too.

**Two limits, both from the author's naming and neither fixable from `parts.json`:** the fork
legs, triple clamp and front axle are all called `BASE_CB500X_FrontWheel006*`, and the front brake
disc is `BASE_CB500X_FrontWheel007_1` with the material `disco_freio`. `front-wheel` is the first
row of `BIKE_PARTS`, so a pin on a later row can never take a name away from it — the fork and the
disc stay inside the front-wheel group. Over-inclusive, not wrong: focusing "front wheel" lights
the whole front end. There is no `front-fork` or `front-brake` group on this model, which is the
honest reading.

*Not chosen:* **Basanti WIP 3** (Belzar Sirus, CC BY) is structurally the best adventure candidate
found — 427 meshes, 17 groups, names down to `Brake Caliper Bracket` and `FrontBreakPadR` — but it
is a work in progress: the Royal Enfield Himalayan it is modelling has no seat and no rear
bodywork yet, just a bare subframe. **Honda Africa Twin** and **BMW F 650 GS** (alban) are 6 and 5
meshes; **BMW R-1200-GS** (AXL) is 2; **BMW F650 GS** (switzerbaden) is 3; **Harley Scrambler
Sportster** (Tulio Portela) is 3; **MOTORCYCLE** (Jelvehkar) is 75 meshes in 2 groups.

## `generic/supermoto` — the stray mesh, deleted

`docs/qa/3d-parts.md` logs it as a known cosmetic bug: `Cube.006_Redbull_0`, a 2 000-triangle
detached piece sitting a bike-length behind the KTM, doubling the bounding box the viewer
normalises to and so rendering the bike at half size.

The source was re-fetched and the node dropped before the conversion. The bounding box is the
proof, straight out of the strip step:

```
  before  span 0.767 x 1.346 x 4.892
  after   span 0.767 x 1.346 x 2.378      <- the bike's own length
  dropped 1: Cube.006_Redbull_0
```

Rebuilt exactly as `CREDITS.md` specifies: 0.41 MB → **0.38 MB**, still 14 groups, and
`states3-supermoto.png` shows it filling the frame. The other `*_Redbull_*` nodes are real parts
(the fork tubes, the graphics, the handlebar path) and are untouched.

## Licences

**All four replacements are CC BY 4.0 — no NC and no SA.** The generic roster is now 10 × CC BY
and one CC BY-NC-SA (`naked`, the Ducati, which predates this pass). Every author's own
`license.txt` from the Sketchfab archive ships next to its `model.glb`, and the credit lines in
`web/store/models/CREDITS.md` were regenerated by `credits-generic.mjs` from the `source.json`
files on disk — so the attribution is what is actually shipping, not what was typed.

| type | model | author | licence |
| --- | --- | --- | --- |
| `cruiser` | Harley Davidson Motorcycle "EL OHV V-TWIN" | matias_romero | CC BY 4.0 |
| `touring` | Harley-Davidson Police | Comrade1280 | CC BY 4.0 |
| `scooter` | Worn Out Old School Vespa | Jakob_Forseth | CC BY 4.0 |
| `adventure` | Honda CB500X | DevanirGrau | CC BY 4.0 |

Total shipped generic weight: **21.7 MB** across 11 models, biggest file 6.67 MB — inside the
25 MiB per-file cap with room to spare.

## One change in the shared parts table

`BIKE_PARTS` matched `engine` on `/cylinder/i`. Blender names every primitive it creates
`Cylinder`, `Cylinder.001`, `Cylinder.002`, and a Sketchfab export keeps those names: on the
Harley EL OHV **229 of its 429 meshes** are a numbered Blender cylinder — fenders, wheel spacers,
the seat, the handlebars — and every one of them was being called the engine. That is the
confident-wrong-answer failure the whole parts pass exists to remove, and a pin cannot fix it
because `engine` sits above `seat`, `fuel-tank`, `handlebar` and `fairing` in the table.

The regex is now `/cylinder(?![.\d])/i`: "Cylinder Head", "Engine_Cylinders" and
"Cylinder_BLACK PLASTICS" still read as the engine; "Cylinder.002_Fenders_0" does not. Verified
against every shipped model — `yzf-2021` 16, `honda-cbr650r` 14, `corvette-c8` 15, `motocross` 14,
`sportbike` 19, `naked` 18, `supermoto` 14, `enduro` 10, `classic` 4, `car` 7 — all unchanged.
`motocross` and `sportbike` both pin their own `Cylinder.*` nodes to `engine` explicitly in
`parts.json`, so they never depended on the loose regex.

## Also in viewer3d.js this pass: the stage colours follow the theme

The 3D panel is the one surface in the app whose colours are not CSS, so it now fetches them.
`docs/ui-themes.md` marks `--grid`, `--grid-bg` and `--accent` as **stage** tokens — declared in
CSS, read by `js/viewer3d.js` — and `stageColor()` reads them at mount and again on the
`mechanica:theme` event (using `detail.tokens` when the event carries them, `getComputedStyle`
otherwise, and the shipped literals when neither resolves, which is the case in
`counter/viewer-test.html` and `counter/solo.html` because neither loads `themes.css`).

What follows the theme: the grid backdrop's three uniforms (`uInk` ← `--grid-bg`, `uLine` ←
`--grid`, `uAccent` ← `--accent`), the highlight tint on a focused part, the x-ray material and
the modelled garage's concrete (`--muted`). The highlight is re-derived from each **source**
material on every change rather than lerped again, so five theme taps do not drift it somewhere no
theme asked for. The listener is removed in `dispose()`.

What deliberately does not follow the theme: the HDRI environments, the four lights and the studio
sky gradient. Those light the vehicle, and tinting them would paint the bike a different colour
per theme instead of restyling the panel around it.

Verified with `theme-shots.mjs`: Night and Blueprint, both viewports, **10 stops each, 0 console
errors**, and the Pick screen's grid is deep blue with cyan lines under Blueprint and near-black
with grey-blue lines under Night. Workshop is pixel-identical by construction — `counter.css`
declares `--grid: #b6bcc4`, `--grid-bg: #1a1f24`, `--accent: #e85d04`, which are the literals the
panel shipped with. `viewer-shots.mjs --states` green.

## Files touched

- `web/store/models/generic/{cruiser,touring,scooter,adventure,supermoto}/model.glb`,
  `license.txt`, `source.json`
- `web/store/models/generic/parts.json` — `rotate` / `orient` / `extra` for the five
- `web/store/models/CREDITS.md` — regenerated generic table and credit lines
- `web/tools/model-shortlist.json` — the four new uids, titles, authors, licences, `orient`,
  `rotate` and the reason each was picked, so a `models-fetch.mjs` re-run reproduces them
- `web/counter/js/viewer3d.js` — the `cylinder` regex above, and the stage-colour theme reading.
  Scene, loading, camera, explode, environment and idle-spin code untouched.
- `docs/qa/3d-models.md`, `docs/qa/3d-models/states3-*.png`

The raw Sketchfab downloads are **not** in the repo. `web/store/models/.gitignore` only ignores
`*/scene.gltf`, which is one directory level and does not cover `generic/<type>/`, so the sources
were converted from a scratch directory and only `model.glb`, `license.txt` and `source.json` were
written into the tree.
