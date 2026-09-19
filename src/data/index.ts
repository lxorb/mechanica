import type { Bike, Manual } from '../types'
import bikesJson from './bikes.json'
import catalogRaw from './catalog.json?raw'
import ktm from './manuals/ktm-390-duke-2024-om-en.json'
import bmw from './manuals/bmw-r12gs-2025-rm-en.json'

export interface Model {
  key: string
  make: string
  model: string
  years: number[]
  manuals: Record<number, string>
  markets: Record<number, string>
  market: string
  full: string
  short: string
  spaced: string
  ranked: number
}

type Row = {
  make: string
  model: string
  years: number[]
  manuals?: Record<string, string>
  market?: string
  markets?: Record<string, string>
}

const DEFAULT_MARKET = 'WW'

export const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '')
const spacedOf = (s: string): string => ` ${s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()} `
export const modelKey = (make: string, model: string): string => norm(`${make} ${model}`)
export const bikeId = (make: string, model: string, year: number): string =>
  `${make} ${model} ${year}`
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

function shape(make: string, model: string): Model {
  return {
    key: modelKey(make, model),
    make,
    model,
    years: [],
    manuals: {},
    markets: {},
    market: DEFAULT_MARKET,
    full: norm(`${make}${model}`),
    short: norm(model),
    spaced: spacedOf(`${make} ${model}`),
    ranked: 1,
  }
}

function place(into: Map<string, Model>, make: string, model: string): Model {
  const key = modelKey(make, model)
  const hit = into.get(key)
  if (hit) return hit
  const made = shape(make, model)
  into.set(key, made)
  return made
}

function put(into: Map<string, Model>, bike: Pick<Bike, 'make' | 'model' | 'year' | 'market' | 'manualId'>) {
  const row = place(into, bike.make, bike.model)
  if (!row.years.includes(bike.year)) row.years.push(bike.year)
  if (bike.manualId) {
    row.manuals[bike.year] = bike.manualId
    row.ranked = 0
  }
  if (bike.market && bike.market !== DEFAULT_MARKET) row.markets[bike.year] = bike.market
}

function seal(row: Model): Model {
  row.years.sort((a, z) => z - a)
  return row
}

export const bikes: Bike[] = bikesJson as Bike[]

const ids = new Map<string, Bike>(bikes.map((b) => [`${modelKey(b.make, b.model)}|${b.year}`, b]))
const byId = new Map<string, Bike>(bikes.map((b) => [b.id, b]))

const base = new Map<string, Model>()
for (const row of JSON.parse(catalogRaw) as Row[]) {
  const made = place(base, row.make, row.model)
  for (const year of row.years) if (!made.years.includes(year)) made.years.push(year)
  for (const [year, manualId] of Object.entries(row.manuals ?? {})) {
    made.manuals[Number(year)] = manualId
    made.ranked = 0
  }
  if (row.market) made.market = row.market
  for (const [year, market] of Object.entries(row.markets ?? {})) made.markets[Number(year)] = market
}
for (const bike of bikes) put(base, bike)

export const models: Model[] = [...base.values()].map(seal).sort(sortModels)

export function sortModels(a: Model, z: Model): number {
  return a.ranked - z.ranked || a.make.localeCompare(z.make) || a.model.localeCompare(z.model)
}

export function marketOf(row: Model, year: number): string {
  return row.markets[year] ?? row.market
}

export function bikeOf(row: Model, year: number): Bike {
  const known = ids.get(`${row.key}|${year}`)
  if (known) return known
  return {
    id: bikeId(row.make, row.model, year),
    make: row.make,
    model: row.model,
    year,
    market: marketOf(row, year),
    manualId: row.manuals[year] ?? null,
  }
}

export function group(list: Bike[]): Model[] {
  const made = new Map<string, Model>()
  for (const bike of list) put(made, bike)
  return [...made.values()].map(seal)
}

export function merge(into: Model[], extra: Model[]): Model[] {
  if (extra.length === 0) return into
  const at = new Map<string, number>()
  for (let i = 0; i < into.length; i++) at.set(into[i].key, i)
  let changed = false
  const out = [...into]
  for (const row of extra) {
    const i = at.get(row.key)
    if (i === undefined) {
      at.set(row.key, out.push(row) - 1)
      changed = true
      continue
    }
    const hit = out[i]
    const years = [...new Set([...hit.years, ...row.years])].sort((a, z) => z - a)
    const manuals = { ...hit.manuals, ...row.manuals }
    if (years.length === hit.years.length && Object.keys(manuals).length === Object.keys(hit.manuals).length) continue
    out[i] = {
      ...hit,
      years,
      manuals,
      markets: { ...hit.markets, ...row.markets },
      ranked: Object.keys(manuals).length > 0 ? 0 : hit.ranked,
    }
    changed = true
  }
  return changed ? out.sort(sortModels) : into
}

export function remember(list: Bike[]): void {
  for (const bike of list) {
    ids.set(`${modelKey(bike.make, bike.model)}|${bike.year}`, bike)
    byId.set(bike.id, bike)
  }
}

export function bikeById(id: string): Bike | undefined {
  return byId.get(id)
}

export const makes: string[] = (() => {
  const count = new Map<string, { n: number; manuals: number }>()
  for (const row of models) {
    const hit = count.get(row.make) ?? { n: 0, manuals: 0 }
    hit.n += row.years.length
    hit.manuals += Object.keys(row.manuals).length
    count.set(row.make, hit)
  }
  return [...count.entries()]
    .sort((a, z) => z[1].manuals - a[1].manuals || z[1].n - a[1].n || a[0].localeCompare(z[0]))
    .map(([make]) => make)
})()

export const manuals: Record<string, Manual> = Object.fromEntries(
  [ktm, bmw].map((m) => [m.id, m as Manual]),
)
export const manualFor = (bike: Bike): Manual | null => (bike.manualId ? (manuals[bike.manualId] ?? null) : null)
