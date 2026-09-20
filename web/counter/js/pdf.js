const PDFJS_SRC = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.min.mjs";
const PDFJS_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/build/pdf.worker.min.mjs";
const PDFJS_FONTS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/standard_fonts/";
const PDFJS_CMAPS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4/cmaps/";

let pdfjsMod = null;
let pdfjsLoading = null;
const docs = new Map();
const renders = new WeakMap();

function loadPdfjs() {
  if (pdfjsMod) return Promise.resolve(pdfjsMod);
  if (!pdfjsLoading) {
    pdfjsLoading = import(PDFJS_SRC)
      .then((mod) => {
        mod.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        pdfjsMod = mod;
        return mod;
      })
      .catch((err) => {
        pdfjsLoading = null;
        throw err;
      });
  }
  return pdfjsLoading;
}

function getDoc(pdfjs, url) {
  let task = docs.get(url);
  if (!task) {
    task = pdfjs.getDocument({
      url,
      withCredentials: false,
      standardFontDataUrl: PDFJS_FONTS,
      cMapUrl: PDFJS_CMAPS,
      cMapPacked: true,
    });
    docs.set(url, task);
  }
  return task.promise;
}

function targetCssWidth(canvas) {
  const w = canvas && (canvas.clientWidth || canvas.parentElement?.clientWidth);
  return w > 0 ? w : 360;
}

export async function renderPage(manualFileUrl, n, canvas, scale) {
  const pdfjs = await loadPdfjs();
  const pdf = await getDoc(pdfjs, manualFileUrl);
  const page = await pdf.getPage(n);

  const prev = renders.get(canvas);
  if (prev) {
    try {
      prev.cancel();
    } catch {
      /* already finished */
    }
  }

  const base = page.getViewport({ scale: 1 });
  const pageW = base.width || 1;
  let usedScale;
  if (typeof scale === "number" && scale > 0) {
    usedScale = scale;
  } else {
    const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
    usedScale = (targetCssWidth(canvas) * dpr) / pageW;
  }
  if (!Number.isFinite(usedScale) || usedScale <= 0) usedScale = 1;

  const viewport = page.getViewport({ scale: usedScale });
  const ctx = canvas.getContext("2d", { alpha: false });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  if (ctx) ctx.fillStyle = "#fff";
  if (ctx) ctx.fillRect(0, 0, canvas.width, canvas.height);

  const task = page.render({ canvasContext: ctx, canvas, viewport });
  renders.set(canvas, task);
  try {
    await task.promise;
  } catch (err) {
    if (err && err.name === "RenderingCancelledException") return canvas;
    throw err;
  } finally {
    if (renders.get(canvas) === task) renders.delete(canvas);
  }
  return canvas;
}
