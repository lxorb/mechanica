import { useCallback, useEffect, useRef, useState } from 'react'
import type { Bike, Manual, Match } from './types'
import type { Model } from './data'
import { models as localModels } from './data'
import { ask as askSource, loadCatalog, loadManual } from './lib/source'
import Identify from './screens/Identify'
import Ask from './screens/Ask'
import Result from './screens/Result'
import Cost from './screens/Cost'
import Progress from './components/Progress'

type Frame =
  | { step: 'identify' }
  | { step: 'ask'; bike: Bike; manual: Manual }
  | { step: 'result'; bike: Bike; manual: Manual; matches: Match[] }

const ROOT: Frame = { step: 'identify' }

const depthOf = (): number => {
  const state = window.history.state as { d?: unknown } | null
  return typeof state?.d === 'number' ? state.d : 0
}

export default function App() {
  const [catalog, setCatalog] = useState<Model[]>(localModels)
  const [frame, setFrame] = useState<Frame>(ROOT)
  const [hash, setHash] = useState(() => window.location.hash)
  const frames = useRef<Frame[]>([ROOT])
  const depth = useRef(0)
  const moved = useRef(false)

  useEffect(() => {
    let alive = true
    loadCatalog().then((next) => {
      if (alive) setCatalog(next)
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (typeof (window.history.state as { d?: unknown } | null)?.d !== 'number') {
      window.history.replaceState({ d: 0 }, '')
    }
    const onPop = () => {
      const d = depthOf()
      depth.current = d
      setHash(window.location.hash)
      setFrame(frames.current[Math.min(d, frames.current.length - 1)] ?? ROOT)
    }
    const onHash = () => {
      if (typeof (window.history.state as { d?: unknown } | null)?.d !== 'number') {
        moved.current = true
        window.history.replaceState({ d: depth.current }, '')
      }
      setHash(window.location.hash)
    }
    window.addEventListener('popstate', onPop)
    window.addEventListener('hashchange', onHash)
    return () => {
      window.removeEventListener('popstate', onPop)
      window.removeEventListener('hashchange', onHash)
    }
  }, [])

  const push = useCallback((next: Frame) => {
    const d = depth.current + 1
    frames.current = [...frames.current.slice(0, d), next]
    depth.current = d
    moved.current = true
    window.history.pushState({ d }, '')
    setFrame(next)
  }, [])

  const back = useCallback(() => {
    if (moved.current) {
      window.history.back()
      return
    }
    window.history.replaceState({ d: 0 }, '', window.location.pathname + window.location.search)
    depth.current = 0
    setHash('')
    setFrame(ROOT)
  }, [])

  const select = useCallback(
    async (bike: Bike) => {
      const manual = await loadManual(bike)
      if (manual) push({ step: 'ask', bike, manual })
    },
    [push],
  )

  const open = useCallback(
    (bike: Bike, manual: Manual) => {
      push({ step: 'ask', bike, manual })
    },
    [push],
  )

  const ask = useCallback(
    async (bike: Bike, manual: Manual, query: string) => {
      const matches = await askSource(manual, query)
      push({ step: 'result', bike, manual, matches })
    },
    [push],
  )

  const screen = () => {
    if (hash === '#cost') return <Cost onBack={back} />
    if (frame.step === 'identify') return <Identify catalog={catalog} onSelect={select} onManual={open} />
    if (frame.step === 'ask')
      return (
        <Ask
          bike={frame.bike}
          manual={frame.manual}
          onAsk={(query) => ask(frame.bike, frame.manual, query)}
          onBack={back}
        />
      )
    return <Result bike={frame.bike} manual={frame.manual} matches={frame.matches} onBack={back} />
  }

  return (
    <>
      <Progress />
      {screen()}
    </>
  )
}
