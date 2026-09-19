import type { Bike, Manual, Match } from '../types'
import type { Model } from '../data'
import {
  bikeById,
  bikes as localBikes,
  group,
  manualFor,
  manuals as mockManuals,
  merge,
  models as localModels,
  remember,
} from '../data'
import { match } from './match'
import { fromPhoto, fromVin } from './identify'
import { track } from './busy'
import * as api from './api'

export const online = Boolean(import.meta.env.VITE_API_URL)

export interface IngestMeta {
  make: string
  model: string
  year: number
  market?: string
}

export interface IngestProgress {
  status: api.IngestJob['status']
  done: number
  pages: number
  title: string | null
}

export interface PhotoHit {
  bike: Bike
  confidence: number
}

const POLL = 1000
const MAX_POLLS = 900

const resolved = (manual: Manual): Manual => {
  if (!api.base) return manual
  try {
    const url = new URL(manual.file, api.base)
    const apiBase = new URL(api.base)
    const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname)
    const file = local && url.origin !== apiBase.origin ? apiBase.origin + url.pathname : url.toString()
    return { ...manual, file }
  } catch {
    return manual
  }
}

export async function loadCatalog(): Promise<Model[]> {
  if (!online) return localModels
  try {
    const list = await api.catalog()
    if (list.length === 0) return localModels
    remember(list)
    return merge(localModels, group(list))
  } catch {
    return localModels
  }
}

export async function suggest(q: string, signal?: AbortSignal): Promise<Model[]> {
  if (!online) return []
  const list = await api.suggest(q, signal)
  remember(list)
  return group(list)
}

export async function loadManual(bike: Bike): Promise<Manual | null> {
  if (!bike.manualId) return null
  if (!online) return manualFor(bike)
  try {
    return resolved(await track(api.manual(bike.manualId)))
  } catch {
    return mockManuals[bike.manualId] ?? manualFor(bike)
  }
}

export async function ask(manual: Manual, query: string): Promise<Match[]> {
  if (!online) return match(manual, query)
  try {
    return (await track(api.ask(manual.id, query))).matches
  } catch {
    return match(manual, query)
  }
}

export async function identifyPhoto(file: File): Promise<PhotoHit[]> {
  const found = await (online
    ? track(api.identifyPhoto(file))
        .then((r) => r.candidates)
        .catch(() => fromPhoto(localBikes, file))
    : fromPhoto(localBikes, file))
  const out: PhotoHit[] = []
  for (const candidate of found) {
    const bike = bikeById(candidate.bikeId)
    if (bike) out.push({ bike, confidence: candidate.confidence })
  }
  return out
}

export async function identifyVin(vin: string): Promise<Bike | null> {
  if (!online) return fromVin(localBikes, vin)
  try {
    const res = await track(api.identifyVin(vin))
    if (res.bike) {
      remember([res.bike])
      return res.bike
    }
    const top = res.candidates[0]
    return (top && bikeById(top.bikeId)) ?? fromVin(localBikes, vin)
  } catch {
    return fromVin(localBikes, vin)
  }
}

const wait = (ms: number) => new Promise((done) => setTimeout(done, ms))

export function ingest(
  source: File | string,
  meta: IngestMeta,
  onProgress?: (progress: IngestProgress) => void,
): Promise<Manual> {
  return track(run(source, meta, onProgress))
}

async function run(
  source: File | string,
  meta: IngestMeta,
  onProgress?: (progress: IngestProgress) => void,
): Promise<Manual> {
  const job =
    typeof source === 'string' ? await api.ingestUrl(source, meta) : await api.ingestUpload(source, meta)
  let title: string | null = null
  let state = job
  for (let i = 0; i < MAX_POLLS; i++) {
    if (!title && state.status === 'running' && state.done > 0) {
      title = await api
        .manual(state.manualId)
        .then((m) => m.title)
        .catch(() => null)
    }
    onProgress?.({ status: state.status, done: state.done, pages: state.pages, title })
    if (state.status === 'done') return resolved(await api.manual(state.manualId))
    if (state.status === 'error') throw new Error(state.error ?? 'ingest')
    await wait(POLL)
    state = await api.ingestJob(job.id)
  }
  throw new Error('ingest')
}
