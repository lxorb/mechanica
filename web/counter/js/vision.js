/**
 * Vision stub — the in-browser ONNX part classifier is not shipped.
 *
 * Real implementation (ONNX Runtime Web + AswinG5/moto-parts-30cls) is
 * parked in tools/vision-real/: vision.js, export-model.py,
 * test-vision.html, test-imgs/, model/.
 *
 * Identical exported API and result shapes, nothing loaded:
 *   loadPartModel(options, onProgress) → { provider: null, meta: null, ready: false, stub: true }
 *   classifyPart()                     → []
 *   identifyBike()                     → null
 *   isVisionAvailable()                → false
 */

function progressFn(options, onProgress) {
  if (typeof options === "function") return options;
  if (typeof onProgress === "function") return onProgress;
  if (options && typeof options.onProgress === "function") {
    return options.onProgress;
  }
  return null;
}

/** @param {Function|{onProgress?: Function}} [options] */
export async function loadPartModel(options = {}, onProgress) {
  const cb = progressFn(options, onProgress);
  if (cb) cb(1);
  return { provider: null, meta: null, ready: false, stub: true };
}

/** @param {HTMLImageElement | HTMLCanvasElement | ImageBitmap} [imageSource] */
export async function classifyPart(imageSource) {
  void imageSource;
  return [];
}

/** Bike photo-ID is not this module. Always null. */
export async function identifyBike(imageSource, bikes) {
  void imageSource;
  void bikes;
  return null;
}

export function isVisionAvailable() {
  return false;
}
