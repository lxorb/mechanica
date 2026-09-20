# 3D model credits

Every vehicle in the counter app is a Sketchfab model, used under its own licence and
recompressed for the web. The per-model `license.txt` next to each `model.glb` is the author's
original file and ships with it — keep both.

There are two kinds:

- **exact** — the bike itself, for the three we have a model of
- **generic** — one per vehicle type in `web/counter/js/vehicle-type.js`, under `generic/<type>/`,
  which stands in for every bike of that type. A KTM 450 SX-F gets `generic/motocross`, a Vespa
  gets `generic/scooter`. How they were found and converted: `web/tools/model-sources.md`.

## Exact models

| key | model | author | licence |
| --- | --- | --- | --- |
| `yzf-2021` | [Yamaha YZF 2021](https://sketchfab.com/3d-models/yamaha-yzf-2021-0af46985abc54219be3aaf0991f5a3de) | [VTX](https://sketchfab.com/VTX_car) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| `honda-cbr650r` | [Honda CBR650R](https://sketchfab.com/3d-models/honda-cbr650r-b9ec190f902d4180aa527659af3f5089) | [VTX](https://sketchfab.com/VTX_car) | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| `corvette-c8` | [2019 Chevrolet Corvette C8 Stingray](https://sketchfab.com/3d-models/2019-chevrolet-corvette-c8-stingray-790c40ccff6843eab0b7b4bd18421ff8) | [Hari](https://sketchfab.com/Hari31) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Credit lines to reproduce wherever the models are shown:

> This work is based on "Yamaha YZF 2021" by VTX, licensed under CC-BY-NC-SA-4.0.
> This work is based on "Honda CBR650R" by VTX, licensed under CC-BY-NC-SA-4.0.
> This work is based on "2019 Chevrolet Corvette C8 Stingray" by Hari, licensed under CC-BY-4.0.

Two of the three are **NC — non-commercial**, and share-alike. Fine for the hackathon demo; swap
them before anything is sold. The vehicles are visual references, not manufacturer parts
catalogues: the source groups say "bodyshell" and "misc_a", not verified service parts.

## Generic models, one per vehicle type

<!-- GENERIC-TABLE-START — written by web/tools/credits-generic.mjs, do not hand-edit -->
_None shipped yet — run `node web/tools/models-fetch.mjs`._
<!-- GENERIC-TABLE-END -->

Every generic carries its author's own `license.txt` and a `source.json` with the Sketchfab uid,
the licence slug and the triangle count. `generic/parts.json` maps each model's node names onto
the part keys in `js/viewer3d.js`, which is what makes explode / highlight / focus work on a
model none of us named the meshes in.

**Attribution is not optional on the CC BY and CC BY-NC-SA ones.** The credit lines above and in
the generic table are what has to appear wherever the models are shown.

## The GLBs are Draco-compressed

`model.glb` is geometry-compressed with `KHR_draco_mesh_compression` and its textures are
`EXT_texture_webp`. **A loader must wire up a decoder or nothing will appear.**
`js/viewer3d.js` wires up both, so either encoding opens:

```js
loader.setDRACOLoader(new DRACOLoader().setDecoderPath(CDN + "examples/jsm/libs/draco/"));
loader.setMeshoptDecoder(MeshoptDecoder);   // three/addons/libs/meshopt_decoder.module.js
```

The Draco decoder wasm is fetched from the same jsdelivr CDN as three itself.

| key | source | shipped | meshes | triangles |
| --- | --- | --- | --- | --- |
| `yzf-2021` | 29.9 MB | 4.2 MB | 100 | 372k |
| `honda-cbr650r` | 30.0 MB | 2.0 MB | 104 | 367k |
| `corvette-c8` | 13.5 MB | 1.5 MB | 104 | 264k |


## Environment (HDRI)

The viewer lights and backgrounds the model with a Poly Haven HDRI, **CC0** — no attribution
required, credited anyway.

**[Auto Service](https://polyhaven.com/a/auto_service)** by Sergej Majboroda, Poly Haven, CC0.

| file | what | size |
| --- | --- | --- |
| `env/auto_service-2k.hdr` | lighting + reflections, desktop (RGBELoader → PMREMGenerator) | 6.1 MB |
| `env/auto_service-1k.hdr` | the same, phones | 1.6 MB |
| `env/auto_service-4k.jpg` | the visible background, desktop (tonemapped, resized from 8k) | 2.0 MB |
| `env/auto_service-2k.jpg` | the same, phones | 0.5 MB |

Why two files per size: the .hdr carries the light values that make the metal read as metal, and
the .jpg carries pixels you only ever see behind `scene.backgroundBlurriness = 0.15` — a tonemapped
JPEG is a fraction of the bytes of an HDR at the same apparent sharpness.

Chosen by rendering the YZF against six garage/workshop candidates (autoshop_01, auto_service,
workshop, industrial_workshop_foundry, empty_warehouse_01, studio_small_09) at 390x844 and
1280x800: auto_service is the only one that is warm, keeps the floor low-contrast and puts no
blown highlight behind the bike. industrial_workshop_foundry throws yellow-green blotches,
studio_small_09 blows out white, workshop casts green on the bodywork.

Rebuild after picking a different one — `https://api.polyhaven.com/files/<name>` lists every
resolution; take `hdri.1k.hdr.url`, `hdri.2k.hdr.url` and `tonemapped.url`, then:

```sh
# the tonemapped download is 8192x4096; resize it, do not ship it as-is
node -e "const sharp=require('sharp');sharp('<name>.jpg') \
  .resize({width:4096,height:2048,fit:'fill',kernel:'lanczos3'}) \
  .jpeg({quality:92,mozjpeg:true,chromaSubsampling:'4:4:4'}) \
  .toFile('env/<name>-4k.jpg')"
```

Then set `DEFAULT_ENV` in `web/counter/js/viewer3d.js`. `mount(host, key, { environment: false })`
turns the whole thing off and goes back to a transparent canvas over the page background;
`{ environment: "<name>" }` picks a different one.

## Rebuilding a GLB

The raw Sketchfab download (`scene.gltf` + `scene.bin` + `textures/`) is gitignored; only
`model.glb` and `license.txt` ship. To rebuild after dropping a new download in:

```sh
cd web/store/models
npx --yes @gltf-transform/cli@4 optimize <key>/scene.gltf <key>/_tex.glb \
  --compress false --texture-compress webp --texture-size 1024 \
  --join false --flatten false --instance false --palette false --simplify false --weld false
npx --yes @gltf-transform/cli@4 draco <key>/_tex.glb <key>/model.glb
rm <key>/_tex.glb
```

Every flag there is load-bearing:

- **`--join false --flatten false`** — joining merges meshes and throws the node names away, and
  the node names *are* the parts table. Without this the viewer sees one blob.
- **`draco`, not `meshopt`** — meshopt compression quantizes positions and compensates with a
  transform the viewer cannot see once it bakes each part into its own group: eight parts of the
  YZF (both wheels, both tail lights, two bodyshell panels) came out stretched the whole length of
  the bike. Draco dequantizes to the original coordinates and has no such transform. Verified:
  uncompressed 0 stretched meshes, meshopt 8, Draco 0. Do not switch back without re-checking.
- **`--instance false --palette false`** — both rewrite meshes and materials into shared forms
  that break the per-part material swap the highlight relies on.
- **`--texture-size 1024`** — the source textures are 4k and dominate the download.

Then check what the viewer makes of it:

```sh
node web/tools/model-check.mjs <key>                                   # part coverage of the GLB
node web/tools/model-check.mjs web/store/models/<key>/scene.gltf --model <key> --names --where
```

The second form reads the uncompressed source, because Draco hides the skin joints (which is
where the bikes keep their group names) from a plain JSON parse. `UNMATCHED` rows are node names
with no home yet — give each one a regex in `BIKE_PARTS` / `CAR_PARTS` /
`MODEL_EXTRA` in `web/counter/js/viewer3d.js`, and nothing else has to change.
