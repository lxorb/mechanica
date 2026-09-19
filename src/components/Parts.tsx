import { useEffect, useMemo } from 'react'
import type { Manual } from '../types'

const EASE = 220

export default function Parts({
  manual,
  sectionIds,
  open,
  onClose,
}: {
  manual: Manual
  sectionIds: string[]
  open: boolean
  onClose: () => void
}) {
  const parts = useMemo(() => {
    const wanted = new Set(sectionIds)
    const ids = new Set(manual.sections.filter((s) => wanted.has(s.id)).flatMap((s) => s.partIds ?? []))
    return manual.parts.filter((p) => ids.has(p.id))
  }, [manual, sectionIds])

  const live = open && parts.length > 0

  useEffect(() => {
    if (!live) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [live, onClose])

  if (parts.length === 0) return null

  return (
    <div
      className={`fixed inset-0 z-40 flex flex-col justify-end transition-[visibility] duration-[220ms] ${
        live ? '' : 'invisible'
      }`}
    >
      <button
        onClick={onClose}
        aria-label="✕"
        className="absolute inset-0 bg-black/62 transition-opacity ease-out"
        style={{ opacity: live ? 1 : 0, transitionDuration: `${EASE}ms` }}
      />
      <div
        style={{
          transform: live ? 'translateY(0)' : 'translateY(100%)',
          transitionDuration: `${EASE}ms`,
          transitionTimingFunction: 'cubic-bezier(0.2,0.8,0.2,1)',
          scrollbarWidth: 'none',
        }}
        className="hairline relative mx-auto max-h-[72%] w-full max-w-[430px] overflow-y-auto overscroll-contain rounded-t-[20px] border-t border-[var(--line)] bg-[var(--ink-1)] transition-transform"
      >
        <div className="sticky top-0 z-10 flex h-11 items-center justify-center bg-[var(--ink-1)]">
          <span className="h-1 w-9 rounded-full bg-[var(--line)]" />
          <button
            onClick={onClose}
            aria-label="✕"
            className="absolute top-0 right-1 flex h-11 w-11 items-center justify-center text-[15px] leading-none text-[var(--muted)]"
          >
            ✕
          </button>
        </div>
        <div className="px-4 pb-[max(20px,env(safe-area-inset-bottom))]">
          {parts.map((p) => (
            <div key={p.id} className="border-b border-[var(--line)] py-4 last:border-b-0">
              <div className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 text-[15px] leading-snug font-medium">{p.name}</span>
                <span className="flex h-7 shrink-0 items-baseline gap-[3px] rounded-lg bg-[var(--ink-2)] px-[9px]">
                  <span className="text-[12px] text-[var(--muted)]">p.</span>
                  <span className="d text-[15px] font-semibold">{p.page}</span>
                </span>
              </div>
              <div className="pt-[6px] text-[13px] leading-snug text-[var(--muted)]">{p.spec}</div>
              {p.links.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-[10px]">
                  {p.links.map((l) => (
                    <a
                      key={l.shop + l.url}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="flex h-11 items-center rounded-xl bg-[var(--ink-2)] px-[14px] text-[13px] active:bg-[var(--line)]"
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
