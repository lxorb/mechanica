import type { Bike, Candidate } from '../types'

const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]/g, '')

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
  return Promise.resolve(
    ranked.map((r, i) => ({ bikeId: r.id, confidence: confidenceAt(i) })),
  )
}

export function fromVin(bikes: Bike[], vin: string): Bike | null {
  const v = vin.toUpperCase().replace(/[^A-Z0-9]/g, '')
  if (!v) return null
  let best: Bike | null = null
  let bestLen = 0
  for (const bike of bikes) {
    for (const prefix of bike.vins ?? []) {
      const p = prefix.toUpperCase().replace(/[^A-Z0-9]/g, '')
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

export function search(bikes: Bike[], q: string): Bike[] {
  const tokens = q.split(/\s+/).map(norm).filter(Boolean)
  if (tokens.length === 0) return []
  const nq = norm(q)
  const ranked: { bike: Bike; rank: number }[] = []
  for (const bike of bikes) {
    const full = norm(`${bike.make} ${bike.model}`)
    const model = norm(bike.model)
    const year = String(bike.year)
    let rank = -1
    if (full.startsWith(nq) || model.startsWith(nq)) rank = 0
    else if (full.includes(nq) || model.includes(nq)) rank = 1
    else if (tokens.every((t) => full.includes(t) || year.includes(t))) rank = 2
    else if (tokens.every((t) => subsequence(full, t) || year.includes(t))) rank = 3
    if (rank >= 0) ranked.push({ bike, rank })
  }
  return ranked
    .sort(
      (a, z) =>
        a.rank - z.rank ||
        a.bike.make.localeCompare(z.bike.make) ||
        a.bike.model.localeCompare(z.bike.model) ||
        a.bike.year - z.bike.year,
    )
    .map((r) => r.bike)
}

export function years(bikes: Bike[], bike: Bike): Bike[] {
  return bikes
    .filter((b) => norm(b.make) === norm(bike.make) && norm(b.model) === norm(bike.model))
    .sort((a, z) => a.year - z.year)
}
