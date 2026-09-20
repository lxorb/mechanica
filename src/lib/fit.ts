import { useEffect, useRef } from 'react'

const FLOOR = 11

export function useFit(from: number, key: string) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      for (let size = from; size >= FLOOR; size--) {
        el.style.fontSize = `${size}px`
        el.style.fontStretch = size <= from - 2 ? '84%' : ''
        if (el.scrollWidth <= el.clientWidth) return
      }
    }
    fit()
    window.addEventListener('resize', fit)
    document.fonts?.ready.then(fit).catch(() => {})
    return () => window.removeEventListener('resize', fit)
  }, [from, key])

  return ref
}
