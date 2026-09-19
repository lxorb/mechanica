import { useEffect, useMemo, useRef, useState } from 'react'
import type { Bike, Highlight, Manual, Match, OutlineNode, Section } from '../types'
import PdfPage from '../components/PdfPage'
import Parts from '../components/Parts'
import { cachedRatio, getDocument, pageRatio, preloadPage } from '../lib/pdf'

type Entry = { title: string; page: number; depth: number }

function flatten(nodes: OutlineNode[], depth: number, out: Entry[]) {
  for (const node of nodes) {
    out.push({ title: node.title, page: node.page, depth })
    if (node.children) flatten(node.children, depth + 1, out)
  }
  return out
}

function trail(nodes: OutlineNode[], page: number) {
  let best: string[] = []
  const walk = (list: OutlineNode[], path: string[]) => {
    for (const node of list) {
      if (node.page > page) continue
      const next = [...path, node.title]
      best = next
      if (node.children) walk(node.children, next)
    }
  }
  walk(nodes, [])
  return best
}

function reading(manual: Manual, matches: Match[]) {
  const byId = new Map(manual.sections.map((s) => [s.id, s]))
  const list: Section[] = []
  const seen = new Set<string>()
  const add = (section: Section | undefined) => {
    if (!section || seen.has(section.id)) return
    seen.add(section.id)
    list.push(section)
  }
  for (const m of matches) add(byId.get(m.section.id) ?? m.section)
  for (const m of matches) for (const id of m.section.related ?? []) add(byId.get(id))
  return list
}

function spread(sections: Section[], total: number) {
  const pages: number[] = []
  const seen = new Set<number>()
  for (const section of sections) {
    const last = Math.min(total, Math.max(section.pageStart, section.pageEnd))
    for (let p = Math.max(1, section.pageStart); p <= last; p++) {
      if (seen.has(p)) continue
      seen.add(p)
      pages.push(p)
    }
  }
  return pages
}

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
  void query
  void onAsk

  const sections = useMemo(() => reading(manual, matches), [manual, matches])
  const outline = useMemo(() => flatten(manual.outline, 0, []), [manual.outline])
  const [chapter, setChapter] = useState<number[] | null>(null)

  const pages = useMemo(() => {
    const matched = spread(sections, manual.pages)
    return matched.length > 0 ? matched : (chapter ?? [])
  }, [sections, manual.pages, chapter])

  const marks = useMemo(() => {
    const map = new Map<number, Highlight[]>()
    for (const section of sections) {
      for (const h of section.highlights) {
        const list = map.get(h.page)
        if (list) list.push(h)
        else map.set(h.page, [h])
      }
    }
    return map
  }, [sections])

  const partSections = useMemo(
    () => matches.filter((m) => (m.section.partIds?.length ?? 0) > 0).map((m) => m.section.id),
    [matches],
  )

  const scrollerRef = useRef<HTMLDivElement>(null)
  const stripRef = useRef<HTMLDivElement>(null)
  const pageEls = useRef(new Map<number, HTMLElement>())
  const chipEls = useRef(new Map<number, HTMLElement>())
  const seen = useRef(new Map<number, number>())

  const [box, setBox] = useState({ w: 0, h: 0 })
  const [ratio, setRatio] = useState(() => cachedRatio(manual.file, 1))
  const [picked, setPicked] = useState(0)
  const [parts, setParts] = useState(false)

  const current = pages.includes(picked) ? picked : (pages[0] ?? 0)

  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    const measure = () => setBox({ w: scroller.clientWidth, h: scroller.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(scroller)
    return () => ro.disconnect()
  }, [pages.length])

  const first = pages[0] ?? 1

  useEffect(() => {
    let alive = true
    getDocument(manual.file)
      .then((doc) => pageRatio(doc, first))
      .then((measured) => {
        if (alive) setRatio(measured)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [manual.file, first])

  const width = useMemo(() => {
    if (box.w <= 0 || box.h <= 0) return 0
    return Math.max(0, Math.min(box.w - 12, Math.floor((box.h - 16) / ratio), 720))
  }, [box, ratio])

  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller || pages.length === 0) return
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          seen.current.set(Number((entry.target as HTMLElement).dataset.page), entry.intersectionRatio)
        }
        let best = 0
        let top = 0
        for (const [page, amount] of seen.current) {
          if (amount > best) {
            best = amount
            top = page
          }
        }
        if (top > 0) setPicked(top)
      },
      { root: scroller, threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] },
    )
    for (const el of pageEls.current.values()) io.observe(el)
    return () => io.disconnect()
  }, [pages])

  useEffect(() => {
    if (width <= 0) return
    const next = pages[pages.indexOf(current) + 1]
    if (!next) return
    getDocument(manual.file)
      .then((doc) => preloadPage(doc, next, width))
      .catch(() => {})
  }, [current, pages, width, manual.file])

  useEffect(() => {
    const strip = stripRef.current
    const chip = chipEls.current.get(current)
    if (!strip || !chip) return
    strip.scrollTo({ left: chip.offsetLeft - strip.clientWidth / 2 + chip.offsetWidth / 2, behavior: 'smooth' })
  }, [current])

  const jump = (page: number) => {
    setPicked(page)
    pageEls.current.get(page)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const open = (index: number) => {
    const start = outline[index].page
    const after = outline.slice(index + 1).find((entry) => entry.page > start)?.page ?? manual.pages + 1
    const last = Math.max(start, Math.min(manual.pages, after - 1))
    const list: number[] = []
    for (let p = start; p <= last; p++) list.push(p)
    seen.current.clear()
    setPicked(start)
    setChapter(list)
  }

  const path = useMemo(() => (current > 0 ? trail(manual.outline, current) : []), [manual.outline, current])

  const header = (
    <header className="shrink-0 border-b border-[var(--line)] pt-[env(safe-area-inset-top)]">
      <div className="mx-auto flex w-full max-w-[720px] items-center gap-1 px-2">
        <button
          onClick={chapter ? () => setChapter(null) : onBack}
          className="flex h-11 w-11 shrink-0 items-center justify-center text-[17px] leading-none"
        >
          ←
        </button>
        <div className="min-w-0 flex-1 truncate text-[15px] font-medium">{manual.title}</div>
        {current > 0 && (
          <div className="shrink-0 pr-2 text-[13px] tabular-nums text-[var(--muted)]">
            p. {current}/{manual.pages}
          </div>
        )}
      </div>
      {path.length > 0 && (
        <div className="mx-auto w-full max-w-[720px] truncate px-4 pb-2 text-[13px] leading-snug text-[var(--muted)]">
          {path.join(' · ')}
        </div>
      )}
    </header>
  )

  if (pages.length === 0) {
    return (
      <div className="flex h-full w-full flex-col overflow-hidden">
        {header}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="mx-auto w-full max-w-[720px] pb-[max(16px,env(safe-area-inset-bottom))]">
            {outline.map((entry, index) => (
              <button
                key={`${entry.page}-${index}`}
                onClick={() => open(index)}
                style={{ paddingLeft: 16 + entry.depth * 14 }}
                className={`flex min-h-11 w-full items-center border-b border-[var(--line)] py-3 pr-4 text-left leading-snug ${
                  entry.depth > 0 ? 'text-[15px] text-[var(--muted)]' : 'text-[17px] font-medium'
                }`}
              >
                {entry.title}
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {header}

      <div
        ref={scrollerRef}
        style={{ scrollbarWidth: 'none' }}
        className="min-h-0 flex-1 snap-y snap-mandatory overflow-y-auto overscroll-contain"
      >
        {pages.map((page) => (
          <div
            key={page}
            data-page={page}
            ref={(el) => {
              if (el) pageEls.current.set(page, el)
              else pageEls.current.delete(page)
            }}
            className="flex snap-start items-center justify-center py-2"
          >
            {width > 0 && <PdfPage file={manual.file} page={page} highlights={marks.get(page) ?? []} width={width} />}
          </div>
        ))}
      </div>

      <div className="shrink-0 border-t border-[var(--line)] pb-[max(8px,env(safe-area-inset-bottom))]">
        <div className="mx-auto flex w-full max-w-[720px] items-center gap-2 px-2 pt-2">
          <div ref={stripRef} style={{ scrollbarWidth: 'none' }} className="flex min-w-0 flex-1 gap-2 overflow-x-auto">
            {pages.map((page) => (
              <button
                key={page}
                ref={(el) => {
                  if (el) chipEls.current.set(page, el)
                  else chipEls.current.delete(page)
                }}
                onClick={() => jump(page)}
                className={`h-11 min-w-11 shrink-0 rounded-xl border px-3 text-[15px] tabular-nums ${
                  page === current
                    ? 'border-[var(--accent)] bg-[var(--accent)] font-medium text-[#0a0a0a]'
                    : 'border-[var(--line)] text-[var(--muted)]'
                }`}
              >
                {page}
              </button>
            ))}
          </div>
          {partSections.length > 0 && (
            <button
              onClick={() => setParts(true)}
              className="h-11 shrink-0 rounded-xl border border-[var(--line)] px-4 text-[15px] font-medium"
            >
              Parts
            </button>
          )}
        </div>
      </div>

      {parts && (
        <div className="fixed inset-0 z-10 flex flex-col justify-end bg-black/60" onClick={() => setParts(false)}>
          <div
            onClick={(e) => e.stopPropagation()}
            className="mx-auto max-h-[72%] w-full max-w-[720px] overflow-y-auto rounded-t-xl border-t border-[var(--line)] bg-[var(--bg)] pb-[env(safe-area-inset-bottom)]"
          >
            <Parts manual={manual} sectionIds={partSections} onClose={() => setParts(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
