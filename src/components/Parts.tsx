import { useEffect, useMemo, useState } from 'react'
import type { Manual } from '../types'

const EASE = 150

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
  const [mounted, setMounted] = useState(false)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    if (live) {
      setMounted(true)
      const frame = requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)))
      return () => cancelAnimationFrame(frame)
    }
    setShown(false)
    const timer = setTimeout(() => setMounted(false), EASE)
    return () => clearTimeout(timer)
  }, [live])

  useEffect(() => {
    if (!live) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [live, onClose])

  if (!mounted) return null

  return (
    <div className="fixed inset-0 z-40 flex flex-col justify-end">
      <button
        onClick={onClose}
        aria-label="✕"
        className="absolute inset-0 bg-black/60 transition-opacity ease-out"
        style={{ opacity: shown ? 1 : 0, transitionDuration: `${EASE}ms` }}
      />
      <div
        className="relative mx-auto max-h-[70%] w-full max-w-[430px] overflow-y-auto overscroll-contain rounded-t-xl border-t border-[var(--line)] bg-[var(--bg)] transition-transform ease-out"
        style={{ transform: shown ? 'translateY(0)' : 'translateY(100%)', transitionDuration: `${EASE}ms` }}
      >
        <div className="sticky top-0 z-10 flex justify-end bg-[var(--bg)] px-2 pt-2">
          <button
            onClick={onClose}
            aria-label="✕"
            className="flex h-11 w-11 items-center justify-center text-[17px] leading-none text-[var(--muted)]"
          >
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-5 px-4 pt-1 pb-[max(20px,env(safe-area-inset-bottom))]">
          {parts.map((p) => (
            <div key={p.id} className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[15px] leading-snug font-medium">{p.name}</span>
                <span className="shrink-0 rounded-lg border border-[var(--line)] px-2 py-1 text-[13px] tabular-nums text-[var(--muted)]">
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
                      className="flex min-h-11 items-center rounded-xl border border-[var(--line)] px-4 text-[13px]"
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
