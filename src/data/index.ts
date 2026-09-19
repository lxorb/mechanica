import type { Bike, Manual } from '../types'
import bikesJson from './bikes.json'
import ktm from './manuals/ktm-390-duke-2024-om-en.json'
import bmw from './manuals/bmw-r12gs-2025-rm-en.json'

export const bikes: Bike[] = bikesJson as Bike[]
export const manuals: Record<string, Manual> = Object.fromEntries(
  [ktm, bmw].map((m) => [m.id, m as Manual]),
)
export const manualFor = (bike: Bike): Manual | null => (bike.manualId ? manuals[bike.manualId] ?? null : null)
