import { useBusy } from '../lib/busy'

const STEPS = [0, 1, 2]
const SWEEP = 'ttm-progress 6s cubic-bezier(0, 0.7, 0.2, 1) forwards'

export default function Progress({ step = 1 }: { step?: number }) {
  const busy = useBusy()
  const live = Math.min(Math.max(step, 1), STEPS.length) - 1

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-50 mx-auto flex w-full max-w-[720px] gap-1 px-4 pt-[max(14px,calc(env(safe-area-inset-top)+8px))]"
    >
      {STEPS.map((i) => (
        <div
          key={i}
          className={`h-[3px] flex-1 overflow-hidden rounded-full transition-colors duration-[220ms] ${
            i < live ? 'bg-[var(--paper)]' : 'bg-[var(--line)]'
          }`}
        >
          {i === live && (
            <div
              className="h-full w-full rounded-full bg-[var(--accent)]"
              style={busy ? { animation: SWEEP } : undefined}
            />
          )}
        </div>
      ))}
    </div>
  )
}
