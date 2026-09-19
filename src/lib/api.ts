import type { Bike, Candidate, Manual, Match } from '../types'

export const base = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

export interface ManualSummary {
  id: string
  title: string
  bikeIds: string[]
  pages: number
  sections: number
}

export interface AskResponse {
  matches: Match[]
  intent?: string | null
  usd?: number
}

export interface IdentifyResponse {
  candidates: Candidate[]
  bike?: Bike | null
}

export interface PartClass {
  label: string
  confidence: number
}

export interface IngestMeta {
  make: string
  model: string
  year: number
  market?: string
}

export interface IngestJob {
  id: string
  manualId: string
  status: 'queued' | 'running' | 'done' | 'error'
  pages: number
  done: number
  error?: string | null
}

export interface RegistryEntry {
  id: string
  make: string
  model: string
  years: number[]
  market: string
  type: 'owner' | 'service'
  lang: string
  url: string
  access: 'free' | 'paid' | 'subscription' | 'dealer'
  price?: string | null
  site: string
  title?: string | null
}

export interface CostSummary {
  total: number
  count: number
  byRoute: Record<string, number>
  byModel: Record<string, number>
  naivePerAsk: number
  asks: number
}

const TIMEOUT = 10000

type Options = { method?: string; body?: BodyInit; json?: unknown; timeout?: number; signal?: AbortSignal }

async function call<T>(path: string, options: Options = {}): Promise<T> {
  if (!base) throw new Error('no api')
  const control = new AbortController()
  const timer = setTimeout(() => control.abort(), options.timeout ?? TIMEOUT)
  const onAbort = () => control.abort()
  options.signal?.addEventListener('abort', onAbort)
  try {
    const res = await fetch(base + path, {
      method: options.method ?? (options.body || options.json !== undefined ? 'POST' : 'GET'),
      headers: options.json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: options.json !== undefined ? JSON.stringify(options.json) : options.body,
      signal: control.signal,
    })
    if (!res.ok) throw new Error(`${path} ${res.status}`)
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', onAbort)
  }
}

const query = (params: Record<string, string | number | undefined>): string => {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') usp.set(k, String(v))
  const s = usp.toString()
  return s ? `?${s}` : ''
}

const upload = (file: File | Blob, name = 'file'): FormData => {
  const form = new FormData()
  form.append(name, file, file instanceof File ? file.name : 'upload.bin')
  return form
}

export const health = (): Promise<{ ok: boolean }> => call('/health')

export const catalog = (signal?: AbortSignal): Promise<Bike[]> => call('/catalog', { signal })

export const suggest = (q: string, signal?: AbortSignal): Promise<Bike[]> =>
  call(`/catalog/suggest${query({ q })}`, { signal })

export const manuals = (): Promise<ManualSummary[]> => call('/manuals')

export const manual = (manualId: string, signal?: AbortSignal): Promise<Manual> =>
  call(`/manuals/${encodeURIComponent(manualId)}`, { signal })

export const manualFile = (manualId: string): string => `${base}/manuals/${encodeURIComponent(manualId)}/file`

export const ask = (manualId: string, q: string, signal?: AbortSignal): Promise<AskResponse> =>
  call('/ask', { json: { manualId, query: q }, signal })

export const identifyPhoto = (file: File | Blob, signal?: AbortSignal): Promise<IdentifyResponse> =>
  call('/identify/photo', { body: upload(file), signal, timeout: 20000 })

export const identifyVin = (vin: string, signal?: AbortSignal): Promise<IdentifyResponse> =>
  call('/identify/vin', { json: { vin }, signal })

export const identifyPart = (file: File | Blob, signal?: AbortSignal): Promise<PartClass[]> =>
  call('/identify/part', { body: upload(file), signal, timeout: 20000 })

export const ingestUrl = (url: string, meta: IngestMeta): Promise<IngestJob> =>
  call('/ingest', { json: { url, market: 'EU', ...meta } })

export const ingestUpload = (file: File, meta: IngestMeta): Promise<IngestJob> =>
  call(`/ingest/upload${query({ market: 'EU', ...meta })}`, { body: upload(file), timeout: 120000 })

export const ingestJob = (jobId: string, signal?: AbortSignal): Promise<IngestJob> =>
  call(`/ingest/${encodeURIComponent(jobId)}`, { signal, timeout: 30000 })

export const registry = (make?: string, model?: string, year?: number): Promise<RegistryEntry[]> =>
  call(`/registry${query({ make, model, year })}`)

export const cost = (signal?: AbortSignal): Promise<CostSummary> => call('/cost', { signal })

export const voiceConfig = (): Promise<{ elevenlabsAgentId: string | null; deepgram: boolean }> =>
  call('/voice/config')
