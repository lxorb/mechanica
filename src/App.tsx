import { useState } from 'react'
import type { Bike, Manual, Match } from './types'
import { bikes, manualFor } from './data'
import { match } from './lib/match'
import Identify from './screens/Identify'
import Ask from './screens/Ask'
import Result from './screens/Result'

type State =
  | { step: 'identify' }
  | { step: 'ask'; bike: Bike; manual: Manual }
  | { step: 'result'; bike: Bike; manual: Manual; query: string; matches: Match[] }

export default function App() {
  const [s, set] = useState<State>({ step: 'identify' })

  if (s.step === 'identify') {
    return (
      <Identify
        bikes={bikes}
        onSelect={(bike) => {
          const manual = manualFor(bike)
          if (manual) set({ step: 'ask', bike, manual })
        }}
      />
    )
  }

  const ask = (query: string) =>
    set({ step: 'result', bike: s.bike, manual: s.manual, query, matches: match(s.manual, query) })

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
