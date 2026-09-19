import { useEffect } from 'react'
import type { Manual } from '../types'

export default function Parts({
  manual,
  sectionIds,
  onClose,
}: {
  manual: Manual
  sectionIds: string[]
  onClose: () => void
}) {
  const wanted = new Set(sectionIds)
  const ids = new Set(manual.sections.filter((s) => wanted.has(s.id)).flatMap((s) => s.partIds ?? []))
  const parts = manual.parts.filter((p) => ids.has(p.id))
  const empty = parts.length === 0

  useEffect(() => {
    if (empty) onClose()
  }, [empty, onClose])

  if (empty) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div className="relative mx-auto max-h-[70vh] w-full max-w-[430px] overflow-y-auto overscroll-contain rounded-t-xl border-t border-[var(--line)] bg-[var(--bg)]">
        <div className="sticky top-0 flex justify-end bg-[var(--bg)] px-2 pt-2">
          <button onClick={onClose} className="flex h-11 w-11 items-center justify-center text-[17px] leading-none">
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-5 px-4 pt-1 pb-[max(20px,env(safe-area-inset-bottom))]">
          {parts.map((p) => (
            <div key={p.id} className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[15px] leading-snug font-medium">{p.name}</span>
                <span className="shrink-0 rounded-lg border border-[var(--line)] px-2 py-1 text-[13px] text-[var(--muted)]">
                  p. {p.page}
                </span>
              </div>
              <div className="text-[13px] leading-snug text-[var(--muted)]">{p.spec}</div>
              {p.links.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {p.links.map((l) => (
                    <a
                      key={l.shop + l.url}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="flex min-h-11 items-center rounded-full border border-[var(--line)] px-4 text-[13px]"
                    >
                      {l.shop}
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
