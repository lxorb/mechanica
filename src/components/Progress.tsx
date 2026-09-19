import { useEffect, useState } from 'react'
import { useBusy } from '../lib/busy'

const STEPS = [0, 1, 2]

export default function Progress({ step = 1 }: { step?: number }) {
  const busy = useBusy()
  const [width, setWidth] = useState(1)

  useEffect(() => {
    if (!busy) {
      setWidth(1)
      return
    }
    setWidth(0)
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setWidth(0.92)))
    return () => cancelAnimationFrame(frame)
  }, [busy])

  const live = Math.min(Math.max(step, 1), STEPS.length) - 1

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-50 flex gap-1 px-4 pt-[max(14px,calc(env(safe-area-inset-top)+8px))]"
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
              className="h-full rounded-full bg-[var(--accent)]"
              style={{
                width: `${width * 100}%`,
                transition: busy
                  ? 'width 6000ms cubic-bezier(0,0.7,0.2,1)'
                  : 'width 220ms cubic-bezier(0.2,0.8,0.2,1)',
              }}
            />
          )}
        </div>
      ))}
    </div>
  )
}
