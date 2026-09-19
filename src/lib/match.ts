import type { Manual, Match } from '../types'
// STUB. Owner: ask agent. Keep this signature. Pure, synchronous, no network.
export function match(manual: Manual, query: string): Match[] {
  const q = query.toLowerCase()
  return manual.sections
    .map((section) => ({ section, score: section.keywords.some((k) => q.includes(k)) ? 1 : 0 }))
    .filter((m) => m.score > 0)
}
