import { useCallback, useEffect, useRef, useState } from 'react'

const MIN = 1
const MAX = 3
const DOUBLE = 2
const TAP_MS = 320
const TAP_PX = 28

const gap = (a: Touch, b: Touch): number => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)

export function useZoom() {
  const scroller = useRef<HTMLDivElement | null>(null)
  const spacer = useRef<HTMLDivElement | null>(null)
  const inner = useRef<HTMLDivElement | null>(null)
  const zoom = useRef(MIN)
  const width = useRef(0)
  const [zoomed, setZoomed] = useState(false)

  const apply = useCallback((next: number, px: number, py: number) => {
    const view = scroller.current
    const pad = spacer.current
    const el = inner.current
    if (!view || !pad || !el) return
    const from = zoom.current
    const to = Math.min(MAX, Math.max(MIN, next))
    if (Math.abs(to - from) < 0.001) return
    if (from === MIN) width.current = el.offsetWidth
    const rect = view.getBoundingClientRect()
    const cx = (view.scrollLeft + px - rect.left) / from
    const cy = (view.scrollTop + py - rect.top) / from
    zoom.current = to
    if (to === MIN) {
      el.style.transform = ''
      el.style.width = ''
      pad.style.width = ''
      pad.style.height = ''
    } else {
      el.style.width = `${width.current}px`
      el.style.transform = `scale(${to})`
      pad.style.width = `${width.current * to}px`
      pad.style.height = `${el.offsetHeight * to}px`
    }
    view.scrollLeft = cx * to - (px - rect.left)
    view.scrollTop = cy * to - (py - rect.top)
    setZoomed(to > MIN)
  }, [])

  const reset = useCallback(() => {
    const view = scroller.current
    if (!view) return
    const rect = view.getBoundingClientRect()
    apply(MIN, rect.left + rect.width / 2, rect.top)
  }, [apply])

  useEffect(() => {
    const view = scroller.current
    if (!view) return
    let start = 0
    let base = MIN
    let tapAt = 0
    let tapX = 0
    let tapY = 0

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 2) return
      start = gap(e.touches[0], e.touches[1])
      base = zoom.current
    }
    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 2 || start <= 0) return
      e.preventDefault()
      const now = gap(e.touches[0], e.touches[1])
      apply(
        (base * now) / start,
        (e.touches[0].clientX + e.touches[1].clientX) / 2,
        (e.touches[0].clientY + e.touches[1].clientY) / 2,
      )
    }
    const onEnd = (e: TouchEvent) => {
      if (e.touches.length < 2) start = 0
      if (e.touches.length > 0 || e.changedTouches.length !== 1) return
      const touch = e.changedTouches[0]
      const at = Date.now()
      if (at - tapAt < TAP_MS && Math.hypot(touch.clientX - tapX, touch.clientY - tapY) < TAP_PX) {
        e.preventDefault()
        apply(zoom.current > MIN ? MIN : DOUBLE, touch.clientX, touch.clientY)
        tapAt = 0
        return
      }
      tapAt = at
      tapX = touch.clientX
      tapY = touch.clientY
    }
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return
      e.preventDefault()
      apply(zoom.current * (1 - e.deltaY / 240), e.clientX, e.clientY)
    }
    const onDouble = (e: MouseEvent) => {
      apply(zoom.current > MIN ? MIN : DOUBLE, e.clientX, e.clientY)
    }

    view.addEventListener('touchstart', onStart, { passive: true })
    view.addEventListener('touchmove', onMove, { passive: false })
    view.addEventListener('touchend', onEnd, { passive: false })
    view.addEventListener('wheel', onWheel, { passive: false })
    view.addEventListener('dblclick', onDouble)
    return () => {
      view.removeEventListener('touchstart', onStart)
      view.removeEventListener('touchmove', onMove)
      view.removeEventListener('touchend', onEnd)
      view.removeEventListener('wheel', onWheel)
      view.removeEventListener('dblclick', onDouble)
    }
  }, [apply])

  useEffect(() => {
    const el = inner.current
    const pad = spacer.current
    if (!el || !pad) return
    const ro = new ResizeObserver(() => {
      if (zoom.current === MIN) return
      pad.style.height = `${el.offsetHeight * zoom.current}px`
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return { scroller, spacer, inner, zoomed, reset }
}
