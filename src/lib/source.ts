import type { Bike, Candidate, Manual, Match } from '../types'
import { bikes as mockBikes, manualFor, manuals as mockManuals } from '../data'
import { match } from './match'
import { fromPhoto, fromVin } from './identify'
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

export async function loadBikes(): Promise<Bike[]> {
  if (!online) return mockBikes
  try {
    const bikes = await api.catalog()
    return bikes.length > 0 ? bikes : mockBikes
  } catch {
    return mockBikes
  }
}

export async function loadManual(bike: Bike): Promise<Manual | null> {
  if (!bike.manualId) return null
  if (!online) return manualFor(bike)
  try {
    return resolved(await api.manual(bike.manualId))
  } catch {
    return mockManuals[bike.manualId] ?? null
  }
}

export async function ask(manual: Manual, query: string): Promise<Match[]> {
  if (!online) return match(manual, query)
  try {
    return (await api.ask(manual.id, query)).matches
  } catch {
    return match(manual, query)
  }
}

export async function identifyPhoto(bikes: Bike[], file: File): Promise<Candidate[]> {
  if (!online) return fromPhoto(bikes, file)
  try {
    const res = await api.identifyPhoto(file)
    return res.candidates
  } catch {
    return fromPhoto(bikes, file)
  }
}

export async function identifyVin(bikes: Bike[], vin: string): Promise<Bike | null> {
  if (!online) return fromVin(bikes, vin)
  try {
    const res = await api.identifyVin(vin)
    if (res.bike) return res.bike
    const top = res.candidates[0]
    return (top && bikes.find((b) => b.id === top.bikeId)) ?? null
  } catch {
    return fromVin(bikes, vin)
  }
}

const wait = (ms: number) => new Promise((done) => setTimeout(done, ms))

export async function ingest(
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
