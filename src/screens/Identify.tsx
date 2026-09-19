import type { Bike } from '../types'
// STUB. Owner: identify agent. Keep this signature.
export default function Identify({ bikes, onSelect }: { bikes: Bike[]; onSelect: (bike: Bike) => void }) {
  return (
    <div className="p-4 flex flex-col gap-2">
      {bikes
        .filter((b) => b.manualId)
        .map((b) => (
          <button key={b.id} className="text-left p-4 border border-[var(--line)] rounded-xl" onClick={() => onSelect(b)}>
            {b.make} {b.model} {b.year}
          </button>
        ))}
    </div>
  )
}
