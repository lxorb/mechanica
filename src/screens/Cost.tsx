import { useEffect, useState } from 'react'
import type { CostSummary } from '../lib/api'
import { cost } from '../lib/api'
import { track } from '../lib/busy'

const usd = (n: number): string => (n >= 100 ? n.toFixed(2) : n.toFixed(4))

export default function Cost({ onBack }: { onBack: () => void }) {
  const [summary, setSummary] = useState<CostSummary | null>(null)

  useEffect(() => {
    const control = new AbortController()
    track(cost(control.signal))
      .then(setSummary)
      .catch(() => {})
    return () => control.abort()
  }, [])

  const cells: [string, string][] = summary
    ? [
        ['total', usd(summary.total)],
        ['per ask', usd(summary.asks > 0 ? summary.total / summary.asks : 0)],
        ['naive per ask', usd(summary.naivePerAsk)],
        ['calls', String(summary.count)],
      ]
    : []

  return (
    <div className="h-full w-full overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
        <div className="shrink-0 px-2 pt-[max(22px,calc(env(safe-area-inset-top)+12px))]">
          <button
            onClick={onBack}
            aria-label="←"
            className="flex h-11 w-11 items-center justify-center text-[19px] leading-none"
          >
            ←
          </button>
        </div>
        <div className="grid min-h-0 flex-1 content-start grid-cols-2 gap-3 px-4 pt-4">
          {cells.map(([label, value]) => (
            <div key={label} className="rounded-[14px] bg-[var(--ink-1)] px-4 py-4">
              <div className="d truncate text-[30px] leading-none font-bold [font-stretch:112%]">{value}</div>
              <div className="lab pt-3 text-[var(--muted)]">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
