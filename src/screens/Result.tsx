import type { Bike, Manual, Match } from '../types'
// STUB. Owner: viewer agent. Keep this signature.
export default function Result({
  bike,
  manual,
  query,
  matches,
  onAsk,
  onBack,
}: {
  bike: Bike
  manual: Manual
  query: string
  matches: Match[]
  onAsk: (query: string) => void
  onBack: () => void
}) {
  void bike
  void onAsk
  return (
    <div className="p-4 flex flex-col gap-3">
      <button onClick={onBack}>←</button>
      <div className="text-[var(--muted)]">{query}</div>
      {matches.map((m) => (
        <div key={m.section.id} className="p-4 border border-[var(--line)] rounded-xl">
          {m.section.title} · p. {m.section.pageStart}–{m.section.pageEnd} · {manual.file}
        </div>
      ))}
    </div>
  )
}
