import type { Bike, Candidate } from '../types'
import type { Model } from '../data'

export const LIMIT = 30
const TIERS = 5

const hash = (s: string): number => {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const CONFIDENCE = [0.9, 0.6, 0.4, 0.3, 0.2]

const confidenceAt = (i: number): number =>
  CONFIDENCE[i] ?? Math.max(0.05, Number((0.2 - 0.05 * (i - CONFIDENCE.length + 1)).toFixed(2)))

export function fromPhoto(bikes: Bike[], file: File): Promise<Candidate[]> {
  const seed = hash(`${file.size}:${file.name}`)
  const ranked = bikes
    .filter((b) => (b.cues?.length ?? 0) > 0)
    .map((b) => ({ id: b.id, key: hash(`${seed}:${b.id}`) }))
    .sort((a, z) => a.key - z.key || a.id.localeCompare(z.id))
  return Promise.resolve(ranked.map((r, i) => ({ bikeId: r.id, confidence: confidenceAt(i) })))
}

export const cleanVin = (vin: string): string => vin.toUpperCase().replace(/[^A-Z0-9]/g, '')

export function fromVin(bikes: Bike[], vin: string): Bike | null {
  const v = cleanVin(vin)
  if (!v) return null
  let best: Bike | null = null
  let bestLen = 0
  for (const bike of bikes) {
    for (const prefix of bike.vins ?? []) {
      const p = cleanVin(prefix)
      if (p && p.length > bestLen && v.startsWith(p)) {
        best = bike
        bestLen = p.length
      }
    }
  }
  return best
}

const subsequence = (hay: string, needle: string): boolean => {
  let i = 0
  for (let j = 0; j < hay.length && i < needle.length; j++) if (hay[j] === needle[i]) i++
  return i === needle.length
}

const yearHit = (row: Model, token: string): boolean => {
  if (token.length === 4) return row.years.includes(Number(token))
  if (token.length === 2) return row.years.some((y) => y % 100 === Number(token))
  return false
}

const digits = (token: string): boolean => /^\d+$/.test(token)

function tier(row: Model, nq: string, tokens: string[]): number {
  if (row.full.startsWith(nq) || row.short.startsWith(nq)) return 0
  if (tokens.every((t) => row.spaced.includes(` ${t}`) || (digits(t) && yearHit(row, t)))) return 1
  if (row.full.includes(nq) || row.short.includes(nq)) return 2
  if (tokens.every((t) => row.full.includes(t) || (digits(t) && yearHit(row, t)))) return 3
  if (nq.length >= 3 && tokens.every((t) => subsequence(row.full, t) || (digits(t) && yearHit(row, t)))) return 4
  return -1
}

export const tokenize = (q: string): string[] =>
  q.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean)

export function search(list: Model[], q: string, limit = LIMIT): Model[] {
  const tokens = tokenize(q)
  if (tokens.length === 0) return []
  const nq = tokens.join('')
  const buckets: Model[][] = Array.from({ length: TIERS }, () => [])
  for (const row of list) {
    const t = tier(row, nq, tokens)
    if (t < 0) continue
    const slot = row.ranked === 0 ? Math.max(0, t - 1) : t
    const bucket = buckets[slot]
    if (bucket.length < limit) bucket.push(row)
    if (slot === 0 && bucket.length === limit) break
  }
  const out: Model[] = []
  for (const bucket of buckets) {
    for (const row of bucket) {
      out.push(row)
      if (out.length === limit) return out
    }
  }
  return out
}

export function matchingMakes(list: string[], q: string, limit: number): string[] {
  const head = q.toLowerCase().replace(/[^a-z0-9]+/g, '')
  if (!head) return list.slice(0, limit)
  const out = list.filter((make) => make.toLowerCase().replace(/[^a-z0-9]+/g, '').startsWith(head))
  return out.length > 1 ? out.slice(0, limit) : []
}
