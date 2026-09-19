import type { Bike, Manual } from '../types'
// STUB. Owner: ask agent. Keep this signature.
export default function Ask({
  bike,
  manual,
  onAsk,
  onBack,
}: {
  bike: Bike
  manual: Manual
  onAsk: (query: string) => void
  onBack: () => void
}) {
  return (
    <div className="p-4 flex flex-col gap-3">
      <button onClick={onBack}>←</button>
      <div className="text-[var(--muted)]">
        {bike.make} {bike.model} {bike.year}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          onAsk(new FormData(e.currentTarget).get('q') as string)
        }}
      >
        <input
          name="q"
          autoFocus
          className="w-full p-4 bg-transparent border border-[var(--line)] rounded-xl"
          placeholder="What do you want to do?"
        />
      </form>
      <div className="text-[var(--muted)] text-sm">{manual.title}</div>
    </div>
  )
}
