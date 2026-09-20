/**
 * 3D vehicle viewer for the Pick screen. Owner: 3d agent. Ported from rexheng/hackmit@threejs
 * (web/src/bikes/assembly-scene.js + yzf-model.js): exploded view, per-part highlight, focus fit.
 *
 * Models live in ../store/models/<modelKey>/model.glb (Sketchfab, see ../store/models/CREDITS.md):
 *   yzf-2021 (Yamaha YZF, generic motorcycle fallback), honda-cbr650r, corvette-c8.
 * modelFor(bike) picks the key: Honda CBR650R -> honda-cbr650r, Chevrolet Corvette -> corvette-c8,
 * everything else -> yzf-2021. Until the real GLBs are dropped in, a procedural placeholder assembly
 * (grouped primitives with the same part keys) renders so the screen can be built and tested.
 *
 * Part keys (stable, used by the Pick screen to map manual sections -> 3D parts):
 *   front-wheel, rear-wheel, front-brake, rear-brake, front-fork, rear-shock, swingarm, chain,
 *   sprocket, engine, exhaust, radiator, fuel-tank, seat, handlebar, mirrors, headlight, taillight,
 *   battery, air-filter, frame, fairing, footpeg, clutch, oil, spark-plug, fuse, tire (alias of wheel)
 *
 * partFor(sectionTitle, keywords[]) -> part key | null   (keyword table lives here so the mapping is
 * one place; "Checking the front brake fluid level" -> front-brake, "chain tension" -> chain, ...)
 */

export const PART_KEYS = [];

export function modelFor(bike) {}                       // -> modelKey
export function partFor(title, keywords = []) {}        // -> part key | null

/**
 * mount(host, modelKey, opts) -> viewer
 *   host: an element the canvas fills (absolute/sticky positioning is the screen's job)
 *   opts: { onReady(), onSelect(partKey), placeholder: boolean }
 * viewer:
 *   explode(on: boolean, spacing = 1)  // exploded view, animated 400 ms
 *   highlight(partKey | null)          // emissive highlight on that part, others dimmed
 *   focus(partKey)                     // highlight + camera fit with slight zoom (animated)
 *   reset()                            // collapse, clear highlight, default camera
 *   resize()
 *   dispose()
 */
export function mount(host, modelKey, opts = {}) {}
