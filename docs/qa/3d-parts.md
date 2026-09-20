# 3D part groups, every shipped model — 2026-09-20

Answers QA-FINAL open item 1: *"on `generic/naked` — the KTM 390 Duke, the demo bike — there is no
`chain` or `front-brake` group … on the seven single-group models nothing explodes at all."*

Measured with `node web/tools/model-check.mjs --summary`. The numbers match what the browser
reports in `node web/tools/viewer-shots.mjs <model>` — checked model by model, e.g.
`ok naked generic/naked #ff6600 18 groups · 42 meshes`, `ok enduro generic/enduro 10 groups`,
`ok car corvette-c8 15 groups`.

Render sheets in `docs/qa/3d-parts/` — default / exploded / focused, desktop, from
`viewer-shots.mjs --states3`:

| sheet | shows |
| --- | --- |
| `states3-naked.png` | the demo bike: the fix, full width |
| `states3-naked-sportbike-supermoto.png` (+ `-phone`) | the three biggest gains |
| `states3-enduro-classic-car.png` | the material-merged bikes and the RX-7 |
| `states3-adventure-scooter.png`, `states3-cruiser-touring-motocross.png` | the four "no explode" models, identical in all three states, next to a working one |
| `orientation-sheet.png` | all 14 models, every nose now pointing `+x` |

`--states3` can only select generics, so the Corvette has no sheet here; its 12 → 15 was confirmed
in the browser by the `viewer-shots.mjs` run above.

## Before → after

| model | groups before | groups after | what changed |
| --- | --- | --- | --- |
| `yzf-2021` | 16 | 16 | unchanged, reference |
| `honda-cbr650r` | 14 | 14 | unchanged, reference |
| `corvette-c8` | 12 | **15** | doors, bonnet/boot and glass split out of the body shell |
| `generic/naked` **(demo bike)** | **7** | **18** | orientation, `\b` fix, 10 pins — see below |
| `generic/sportbike` | 16 | **19** | front brake, air filter, footpegs; steering top → handlebar |
| `generic/supermoto` | 5 | **14** | orientation, and the Finnish node names finally read |
| `generic/motocross` | 13–14 | 14 | unchanged |
| `generic/enduro` | **1** | **10** | 12 material-merged meshes pinned by node |
| `generic/car` | **1** | **7** | 4 wheels, glass, interior, tail lights, body |
| `generic/classic` | **1** | **4** | only 3 of its 23 meshes are a single component |
| `generic/adventure` | **1** | **1** | **no explode** — see below |
| `generic/scooter` | **1** | **1** | **no explode** |
| `generic/cruiser` | **1** | **1** | **no explode** |
| `generic/touring` | **1** | **1** | **no explode** |

`frame` is the catch-all. A row of `1` means that one group is the whole vehicle, and
`pickGroup()` refuses to select a catch-all group — so those models render and rotate but
highlight nothing, which is the honest answer rather than a wrong one.

## Three bugs behind the demo-path failure

**1. Six of eleven generics were facing the wrong way.** `+x` is the nose in the viewer frame and
every explode vector is written in it — `front-wheel` is `[0.85, -0.10, 0]`. `generic/naked` had
`orient: 180`, so the Ducati stood nose-at-`-x`: the default camera looked at its tail, and
*focus front-wheel* pointed at the rear of the bike. `sportbike`, `classic`, `touring` and
`supermoto` were 90° out (their length lay along `z`), and `adventure` was reversed. Fixed in
`web/store/models/generic/parts.json` and, so a re-run of `models-fetch.mjs` does not undo it,
in `web/tools/model-shortlist.json` (which is where `orient` is authored):

| model | orient was | is |
| --- | --- | --- |
| `naked` | 180 | **0** |
| `adventure` | 180 | **0** |
| `sportbike` | 180 | **90** |
| `classic` | 0 | **90** |
| `touring` | 0 | **90** |
| `supermoto` | 180 | **−90** |

`model-check --where` / `--each` used to report every generic in the *exact* models' frame
(a flat −90° about Y) and so could not have caught this; it now applies each model's own
`rotate` + `orient`, exactly as `viewer3d.js::orientMatrix()` does, and prints the
viewer-frame span with a warning when the longest axis is not `x`.

**2. `\b` does not break on `_`.** Sketchfab node names are almost all `SM_Fork_0000.001_9`, and
`/\bfork/` never matched one: the `_` before `F` is a word character on both sides, so there is no
boundary there. `/\bframe/`, `/\btank\b/`, `/\bpipe/`, `/\bpanel/`, `/\bbody\b/` and nine more had
the same hole. That alone is why the demo bike had no fork, no frame and no tank group.
`viewer3d.js` now builds those with `w()` / `ww()` helpers — `(^|[^a-z])body($|[^a-z])` — which
break on `_`, `.` and `-` as well.

**3. A section's keywords outvoted its own heading.** `partFor(title, keywords)` concatenated both
into one blob. Three real KTM 390 Duke headings came out wrong:

| heading | was | is | the keyword that did it |
| --- | --- | --- | --- |
| Checking tire pressure | `rear-wheel` | `front-wheel` | "rear tire pressure" |
| Engine tightening torques | `spark-plug` | `engine` | "spark plug torque" |
| Chassis tightening torques | `sprocket` | `frame` | "sprocket nut torque" |

Same failure as the founder's original report — a confident, wrong part — with the loose word
coming from the synonym list instead of the rule. `partFor` now runs the rules on the **title
alone** first, front/rear included, and only falls back to title + keywords when the title names no
component at all.

## partFor, verified against the live manual

`GET https://mechanica.emilvinu.ch/api/manuals/ktm-390-duke-2024-om-en` — **all 20 `sections[]`
(title + keywords, the way `screens/pick.js` passes them) and all 30 `outline[]` rows**, 50 titles,
every one either the right group or `null`. No heading containing "brake" maps to anything but a
brake; no heading containing "chain" maps to a wheel.

```
engine       Checking the engine oil level          front-brake  Checking the front brake fluid level
engine       Changing the engine oil and oil filter front-brake  Adding front brake fluid
radiator     Checking the coolant level             front-brake  …brake linings of the front brake…
chain        Cleaning the chain                     rear-brake   Checking the rear brake fluid level
chain        Checking the chain tension             rear-brake   …brake linings of the rear brake…
chain        Adjusting the chain tension            front-wheel  Checking tire pressure
front-wheel  Checking the tire condition            rear-wheel   Removing the rear wheel
battery      Charging the 12-V battery              fuse         Changing the fuses…
headlight    Adjusting the headlight range          -            Service work
engine       Engine tightening torques              frame        Chassis tightening torques
```

All 50 are now cases in `web/tools/partfor-test.mjs` (**93/93 green**, up from 53), which grew an
optional third column for a section's keyword list so the three regressions above stay fixed.
`node web/tools/partfor-test.mjs --live` sweeps four real manuals: the only "brake" title that is
not a brake is *Adjusting the Brake Light Switch* → `taillight`, which is correct.

## Per model

### `generic/naked` — 2024 Ducati Streetfighter V4 S · 7 → 18 groups
The demo bike. Clean `SM_*` group names; the sub-meshes are `Object_N`, so ten pins were read off
`model-check --each` (position in the viewer frame + material name) and live in `parts.json`:

| pin | evidence | group |
| --- | --- | --- |
| `Object_36` | `MAT_Tire_Brake`, x +0.58, at the front wheel | `front-brake` |
| `Object_6` | `MAT_Tire_Brake`, x −0.64, at the rear wheel | `rear-brake` |
| `Object_7` | x −0.39, 0.79 long, 0.10 thin, offset in z — a chain run | `chain` |
| `Object_41` | `MAT_Details_Grid`, upright, in front of the engine | `radiator` |
| `Object_37` | x +0.45, y +0.25, 0.78 wide | `handlebar` |
| `Object_34` | `MAT_Glass`, high and wide, a pair | `mirrors` |
| `Object_20`, `Object_21` | lights + lens at x −0.61 | `taillight` |
| `SM_FrontKit` | cowl, lens, DRL | `headlight` |
| `SM_RearKit` | `MAT_Details_Seat` + tail section | `seat` |
| `SM_Base` | tank and airbox covers, y +0.20 | `fuel-tank` |

Now has front-wheel, rear-wheel, front-brake, rear-brake, front-fork, swingarm, chain, radiator,
exhaust, engine, fuel-tank, seat, mirrors, headlight, taillight, handlebar, fairing, frame.
No sprocket and no rear shock: the model has no separate mesh for either.
*Repro from QA-FINAL now passes:* `brake fluid` → `front-brake` → a lit caliper and a camera refit
(`docs/qa/3d-parts/states3-naked.png`, third tile).

### `generic/sportbike` — Kawasaki ZX-6R · 16 → 19
The author's names are honest but eccentric. `Brakes`, `Brakes Too`, `Brake Holder?`, `Brake Pads`
are all at x +0.58…0.71 → `front-brake` (the rear set already says "Rear"). Everything called
"Steering Wheel" sits at x +0.42, y +0.30, 0.66 wide → `handlebar`, not a fork. `Filter` →
`air-filter`, `Pedal?` / `Leg` → `footpeg`, `Lights at front or whatever` → `headlight`.
16 meshes named `Umm`, `Wharever`, `Aaaaaa Thing`, `Man` stay in the catch-all, honestly.

### `generic/supermoto` — KTM REDBULL · 5 → 14
Finnish node names, now readable with the frame corrected: `Etujarru` (front brake) →
`front-brake`, `Takaiskari` (rear damper) → `rear-shock`, `kone` (engine) → `engine`,
`putki` (pipe) → `exhaust`, `Kytkin` (clutch) → `clutch`, `Etulokari` (front fender) → `fairing`,
`Tuppi`/`Tupet` (grips) + `NurbsPath` → `handlebar`, `wheel_*` → `front-wheel`.
The `Cylinder.0xx` pins that said `engine` were wrong — they sit at x +0.63…0.82, i.e. the fork
tubes, triple clamps and front axle; they are `front-fork` now.
**Known cosmetic bug, not fixable from the parts table:** `Cube.006_Redbull_0` is a 2k-triangle
detached piece sitting a whole bike-length behind the bike (x −0.87 with the bike at +0.20…0.85).
It doubles the bounding box, so the KTM renders at half size with a stray fragment in the corner.
Needs the mesh deleted from the GLB.

### `generic/enduro` — Honda NXR Bros 2003 · 1 → 10
Exported OBJ, **merged by material**: one mesh per material, node names `Object_N`. Eight materials
are localised and pinned — `BrakeDisk` → `front-brake`, `FrontLight` → `headlight`,
`FrontSuspension` → `front-fork`, `Dashboard` → `handlebar`, `Engine`+`Carburettor` → `engine`,
`ChainMat` → `chain`, `Sprocket` → `sprocket`, `IndicatorRearLantern` → `taillight`,
`FairingGasTank` → `fairing`.
**No wheel groups:** `TireMat` is a single mesh containing *both* tyres (1.94 of 2.00 along x), and
`Mirror`, `Chrome`, `ScratchedSteel`, `PlasticScratch` are the same — whole-bike material sweeps.
Splitting them needs connected components, see below.

### `generic/car` — Mazda RX-7 FC · 1 → 7
22 meshes, all `Object_N`, all cleanly separated. Pinned by position: four wheels at x +0.57 /
−0.54 and z ±0.37 → `front-wheel` / `rear-wheel`; the greenhouse shell → `glass`; cabin floor and
interior → `seat`; the three small meshes at x −0.85 spanning 0.61 in z → `taillight`; the shell
and both bumpers → `fairing`. No engine bay and no separate headlights: this RX-7 has pop-ups, and
they are modelled closed inside the front bumper.

### `generic/classic` — Honda CB 750 F · 1 → 4
Same OBJ material merge as the enduro, but only three of its 23 material sweeps are localised:
`mirrors` (y +0.50, 0.80 wide) → `mirrors`, `brakelight` (x −1.00) → `taillight`,
`front_wing_doubleside` (x +0.64) → `fairing`. Everything else — `tex_chrome`, `tex_plastic`,
`tex_seat`, `headlights`, `bolts` — spans 1.2 to 1.9 of the bike's 2.0 length, so any group built
from it would light most of the motorcycle. Left unmatched on purpose.

### `generic/adventure` — Akt Tt Ds 200 · no explode
**Geometry is fine, names are not.** 84 separate, well-placed meshes — the best-structured generic
we ship — but *every one of the 84 nodes is named `defaultMaterial`*, and 78 of them share the
parent `VENTANA`. No regex can tell them apart, so nothing can be pinned.
Fix, cheapest first: rewrite the node names in the GLB's JSON chunk (geometry and the Draco
payload are untouched — only the JSON chunk and its 4-byte padding change), naming each node from
its bounding box the way the pins above were derived. Or re-fetch the Collada source with
`web/tools/models-fetch.mjs` and check whether the names survive a local conversion.

### `generic/scooter` — Vespa · no explode
Licence CC BY 4.0, so splitting is allowed, but there is nothing to split by name: 7 meshes,
3 materials (`…lambert2SG`, `…lambert2SG2`, `…lambert3SG`), and six of the seven span 1.5–2.0 of
the model's 2.0 length. One mesh (`Object_3`, 87k of 131k triangles) *is* the whole scooter.
QA-FINAL calls this one out by name ("every scooter"), so it is the first replacement to make.

### `generic/cruiser` — Harley Davidson Breakout · no explode
**One mesh. 79k triangles. One material called `Bike`.** Nothing to work with at all.

### `generic/touring` — Romanian Police Motorbike · no explode
6 meshes, each spanning 1.85–1.90 of 2.00, materials `plch`, `parts`, `base_mesh`, `transparent`,
`wheel`, `plate`. `Object_8` alone is 579k of the model's 783k triangles — it is also the heaviest
generic we ship at 4.48 MB.

## What "no explode" would take

Four models (`adventure`, `scooter`, `cruiser`, `touring`) and the whole-bike sweeps in `classic`
and `enduro` need the geometry split, not a better regex. Two routes:

1. **Split by connected components.** All four are CC BY 4.0, so it is permitted. The source is
   Draco-compressed, so the step has to decode first — `@gltf-transform/cli` plus `draco3dgltf`,
   both already in the dev tree:
   ```sh
   cd web/store/models
   npx --yes @gltf-transform/cli@4 copy generic/<type>/model.glb /tmp/<type>-raw.glb   # decodes Draco
   # then: weld by position, union-find over the index buffer, one node per component,
   # name each node from its bounding box, and re-encode
   npx --yes @gltf-transform/cli@4 draco /tmp/<type>-split.glb generic/<type>/model.glb
   ```
   Keep `--join false --flatten false --instance false --palette false` on any re-optimise, and
   stay under the 25 MiB per-file cap (see `web/store/models/CREDITS.md`). **Not done here:** the
   naming heuristic is the hard half — on a Vespa there is no fuel tank to find, and a wrongly
   named component is exactly the confident-wrong-answer the founder reported.
2. **Replace the model.** `web/tools/model-shortlist.json` currently holds exactly one candidate
   per type, so there is no alternate to swap in; `web/tools/sketchfab-pick.mjs` re-runs the search
   (token at `C:\Users\me\agent-secrets\sketchfab.txt`) and `web/tools/models-fetch.mjs` downloads
   and converts. Select on **mesh count**, not triangle count — that is the number that decides
   whether a model explodes. The eight-plus-mesh, per-part-named uploads are the ones to keep.

## model-check changes

`web/tools/model-check.mjs` now:

- knows the generic keys (`generic/<type>`, or just `<type>`) and registers
  `generic/parts.json` the way the browser does at boot — without that, every generic was checked
  against the bare `BIKE_PARTS` table and its pins silently did not count;
- prefers `scene.gltf` over the shipped Draco `model.glb` when one is there, because Draco hides
  the skin joints and the two exact bikes keep their group names in them (the tool used to report
  3 groups for a model the browser splits into 16). `--shipped` forces `model.glb`;
- places every mesh in each model's *own* viewer frame and prints the viewer-frame span with a
  warning when the longest axis is not `x`;
- `--each` — one line per mesh: node name, triangles, centre, size, part, materials. This is the
  view the unnamed uploads need, and every pin in `parts.json` was read off it;
- `--summary` — one line per model: group count and the group list, marking the catch-all `frame`
  with `*` when nothing named itself into it. This is the number QA counts;
- matches on the same names the viewer does (joint, node, parent). It used to feed the mesh name
  in as well, and glTF-Transform numbers meshes and nodes in two separate sequences — node
  `Object_10` carries mesh `Object_8` — so a `^Object_8$` pin matched a mesh the browser never
  would, and the tool reported groups that do not exist on the page.

## Files touched

- `web/counter/js/viewer3d.js` — `PART_KEYS` / `PART_LABELS` (+`glass`, `door`, `hood`),
  `BIKE_PARTS`, `CAR_PARTS`, `partFor`. Scene, loading, environment, idle-spin and context code
  untouched.
- `web/store/models/generic/parts.json` — `orient` for six models, `extra` pins for seven.
- `web/tools/model-shortlist.json` — the same six `orient` values, so a `models-fetch.mjs` re-run
  reproduces them.
- `web/tools/model-check.mjs`, `web/tools/partfor-test.mjs`.
- `docs/qa/3d-parts.md`, `docs/qa/3d-parts/states3-*.png`.
