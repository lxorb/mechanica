import { useEffect, useRef, useState } from 'react'
import type { Highlight } from '../types'
import { cachedRatio, getDocument, pageRatio, releaseCanvas, renderPage } from '../lib/pdf'

function scrollParent(el: HTMLElement) {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY
    if (overflow === 'auto' || overflow === 'scroll') return node
  }
  return null
}

export default function PdfPage({
  file,
  page,
  highlights,
  width,
}: {
  file: string
  page: number
  highlights: Highlight[]
  width: number
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [ratio, setRatio] = useState(() => cachedRatio(file, page))
  const [near, setNear] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const io = new IntersectionObserver((entries) => setNear(entries[entries.length - 1].isIntersecting), {
      root: scrollParent(host),
      rootMargin: '120% 0px',
    })
    io.observe(host)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !near || width <= 0) return
    let alive = true
    getDocument(file)
      .then(async (doc) => {
        const measured = await pageRatio(doc, page)
        if (!alive) return
        setRatio(measured)
        await renderPage(doc, page, width, canvas)
        if (alive) setReady(true)
      })
      .catch(() => {})
    return () => {
      alive = false
      setReady(false)
      releaseCanvas(canvas)
    }
  }, [file, page, width, near])

  return (
    <div
      ref={hostRef}
      className="relative overflow-hidden rounded-[2px] bg-white"
      style={{ width, aspectRatio: `1 / ${ratio}` }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 block h-full w-full" />
      {ready &&
        highlights.map((h, i) => (
          <div
            key={i}
            className="pointer-events-none absolute rounded-[3px] mix-blend-multiply"
            style={{
              left: `${h.x * 100}%`,
              top: `${h.y * 100}%`,
              width: `${h.w * 100}%`,
              height: `${h.h * 100}%`,
              background: 'var(--mark)',
            }}
          />
        ))}
    </div>
  )
}
