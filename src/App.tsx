import { useEffect, useState } from 'react'
import type { Bike, Manual, Match } from './types'
import { ask as askSource, loadBikes, loadManual } from './lib/source'
import Identify from './screens/Identify'
import Ask from './screens/Ask'
import Result from './screens/Result'

type State =
  | { step: 'identify' }
  | { step: 'ask'; bike: Bike; manual: Manual }
  | { step: 'result'; bike: Bike; manual: Manual; query: string; matches: Match[] }

export default function App() {
  const [bikes, setBikes] = useState<Bike[] | null>(null)
  const [s, set] = useState<State>({ step: 'identify' })

  useEffect(() => {
    loadBikes().then(setBikes)
  }, [])

  if (!bikes) return null

  if (s.step === 'identify') {
    return (
      <Identify
        bikes={bikes}
        onSelect={async (bike) => {
          const manual = await loadManual(bike)
          if (manual) set({ step: 'ask', bike, manual })
        }}
      />
    )
  }

  const ask = async (query: string) => {
    const matches = await askSource(s.manual, query)
    set({ step: 'result', bike: s.bike, manual: s.manual, query, matches })
  }

  if (s.step === 'ask') {
    return <Ask bike={s.bike} manual={s.manual} onAsk={ask} onBack={() => set({ step: 'identify' })} />
  }

  return (
    <Result
      bike={s.bike}
      manual={s.manual}
      query={s.query}
      matches={s.matches}
      onAsk={ask}
      onBack={() => set({ step: 'ask', bike: s.bike, manual: s.manual })}
    />
  )
}
