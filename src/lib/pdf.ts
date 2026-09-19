import { GlobalWorkerOptions, getDocument as loadDocument } from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'

GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const MAX_DPR = 2
const MAX_SHEETS = 10
const DEFAULT_RATIO = 1.4142

const docs = new Map<string, Promise<PDFDocumentProxy>>()
const urls = new WeakMap<PDFDocumentProxy, string>()
const ratios = new Map<string, number>()
const sheets = new Map<string, HTMLCanvasElement>()
const jobs = new Map<string, Promise<HTMLCanvasElement>>()
const wanted = new WeakMap<HTMLCanvasElement, string>()

const dpr = () => Math.min(window.devicePixelRatio || 1, MAX_DPR)
const sheetKey = (url: string, page: number, width: number) => `${url}|${page}|${Math.round(width)}|${dpr()}`

function remember(url: string, page: number, ratio: number) {
  ratios.set(`${url}|${page}`, ratio)
  if (!ratios.has(url)) ratios.set(url, ratio)
  return ratio
}

export function getDocument(url: string): Promise<PDFDocumentProxy> {
  const open = docs.get(url)
  if (open) return open
  const job = loadDocument({ url }).promise.then((doc) => {
    urls.set(doc, url)
    return doc
  })
  docs.set(url, job)
  job.catch(() => docs.delete(url))
  return job
}

export function cachedRatio(url: string, page: number): number {
  return ratios.get(`${url}|${page}`) ?? ratios.get(url) ?? DEFAULT_RATIO
}

export async function pageRatio(doc: PDFDocumentProxy, page: number): Promise<number> {
  const url = urls.get(doc) ?? ''
  const hit = ratios.get(`${url}|${page}`)
  if (hit) return hit
  const view = (await doc.getPage(page)).getViewport({ scale: 1 })
  return remember(url, page, view.height / view.width)
}

function rasterize(doc: PDFDocumentProxy, page: number, cssWidth: number): Promise<HTMLCanvasElement> {
  const url = urls.get(doc) ?? ''
  const key = sheetKey(url, page, cssWidth)
  const hit = sheets.get(key)
  if (hit) {
    sheets.delete(key)
    sheets.set(key, hit)
    return Promise.resolve(hit)
  }
  const running = jobs.get(key)
  if (running) return running
  const job = (async () => {
    const proxy = await doc.getPage(page)
    const base = proxy.getViewport({ scale: 1 })
    remember(url, page, base.height / base.width)
    const viewport = proxy.getViewport({ scale: (Math.round(cssWidth) * dpr()) / base.width })
    const sheet = document.createElement('canvas')
    sheet.width = Math.round(viewport.width)
    sheet.height = Math.round(viewport.height)
    await proxy.render({ canvas: sheet, viewport }).promise
    sheets.set(key, sheet)
    for (const old of sheets.keys()) {
      if (sheets.size <= MAX_SHEETS) break
      const stale = sheets.get(old)
      if (stale) {
        stale.width = 0
        stale.height = 0
      }
      sheets.delete(old)
    }
    return sheet
  })()
  jobs.set(key, job)
  job.then(
    () => jobs.delete(key),
    () => jobs.delete(key),
  )
  return job
}

export function preloadPage(doc: PDFDocumentProxy, page: number, cssWidth: number): Promise<unknown> {
  return rasterize(doc, page, cssWidth)
}

export async function renderPage(
  doc: PDFDocumentProxy,
  page: number,
  cssWidth: number,
  canvas: HTMLCanvasElement,
): Promise<void> {
  const key = sheetKey(urls.get(doc) ?? '', page, cssWidth)
  wanted.set(canvas, key)
  const sheet = await rasterize(doc, page, cssWidth)
  if (wanted.get(canvas) !== key) return
  canvas.width = sheet.width
  canvas.height = sheet.height
  canvas.getContext('2d')?.drawImage(sheet, 0, 0)
}

export function releaseCanvas(canvas: HTMLCanvasElement) {
  wanted.set(canvas, '')
  canvas.width = 0
  canvas.height = 0
}
