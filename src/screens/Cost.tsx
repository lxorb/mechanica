import { useEffect, useState } from 'react'
import type { CostSummary } from '../lib/api'
import { cost } from '../lib/api'

const usd = (n: number): string => (n >= 100 ? n.toFixed(2) : n.toFixed(4))

export default function Cost({ onBack }: { onBack: () => void }) {
  const [summary, setSummary] = useState<CostSummary | null>(null)

  useEffect(() => {
    const control = new AbortController()
    cost(control.signal)
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
    <div className="h-full w-full overflow-hidden bg-[var(--bg)] text-[var(--fg)]">
      <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
        <div className="shrink-0 pt-[env(safe-area-inset-top)]">
          <button onClick={onBack} className="flex h-11 w-11 items-center justify-center text-[17px] leading-none">
            ←
          </button>
        </div>
        <div className="grid min-h-0 flex-1 content-start grid-cols-2 gap-x-4 gap-y-8 px-4 pt-6">
          {cells.map(([label, value]) => (
            <div key={label}>
              <div className="truncate text-[34px] leading-none font-medium tabular-nums">{value}</div>
              <div className="pt-2 text-[13px] text-[var(--muted)]">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
