import { useEffect, useRef, useState } from 'react'
import type { Bike, Manual } from '../types'
import * as speech from '../lib/speech'
import * as deepgram from '../lib/deepgram'

const MAX_CHIPS = 12

type Stt = {
  supported: boolean
  start: (onText: (text: string, final: boolean) => void, onEnd: () => void) => void
  stop: () => void
}

function Mic({ on }: { on: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke={on ? 'var(--accent)' : 'currentColor'}
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11.5a7 7 0 0 0 14 0" />
      <path d="M12 18.5V21" />
    </svg>
  )
}

export default function Ask({
  bike,
  manual,
  onAsk,
  onBack,
}: {
  bike: Bike
  manual: Manual
  onAsk: (query: string) => void
  onBack: () => void
}) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [stt, setStt] = useState<Stt>(speech)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!window.matchMedia('(pointer: coarse)').matches) input.current?.focus()
    return () => {
      speech.stop()
      deepgram.stop()
    }
  }, [])

  useEffect(() => {
    let alive = true
    deepgram.voiceConfig().then((config) => {
      if (!alive || !config?.deepgram || !deepgram.supported) return
      deepgram.prime(manual)
      setStt(deepgram)
    })
    return () => {
      alive = false
    }
  }, [manual])

  const send = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    stt.stop()
    setListening(false)
    onAsk(trimmed)
  }

  const mic = () => {
    if (listening) {
      stt.stop()
      setListening(false)
      return
    }
    setText('')
    setListening(true)
    stt.start(
      (t) => setText(t),
      () => setListening(false),
    )
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
      <header className="shrink-0 px-4 pt-[max(8px,env(safe-area-inset-top))]">
        <button onClick={onBack} className="flex h-11 w-11 items-center text-[17px] leading-none">
          ←
        </button>
        <div className="text-[13px] leading-snug text-[var(--muted)]">
          {bike.make} {bike.model} {bike.year}
        </div>
        <div className="pb-3 text-[17px] font-medium leading-snug">{manual.title}</div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
        <div className="flex flex-col gap-2">
          {manual.sections.slice(0, MAX_CHIPS).map((s) => (
            <button
              key={s.id}
              onClick={() => onAsk(s.title)}
              className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-[var(--line)] px-4 py-3 text-left active:border-[var(--muted)]"
            >
              <span className="text-[15px] leading-snug">{s.title}</span>
              <span className="shrink-0 text-[13px] text-[var(--muted)]">p. {s.pageStart}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="shrink-0 border-t border-[var(--line)] bg-[var(--bg)] px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
          className="flex items-center gap-1 rounded-xl border border-[var(--line)] pr-1.5 pl-1.5"
        >
          {stt.supported && (
            <button
              type="button"
              onClick={mic}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--muted)]"
            >
              <Mic on={listening} />
            </button>
          )}
          <input
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            enterKeyHint="go"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            className={`min-w-0 flex-1 bg-transparent py-3 text-[17px] outline-none placeholder:text-[var(--muted)] ${
              stt.supported ? '' : 'pl-2.5'
            }`}
            placeholder="What do you want to do?"
          />
          <button
            type="submit"
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[17px] leading-none ${
              text.trim()
                ? 'bg-[var(--accent)] text-[#0a0a0a]'
                : 'border border-[var(--line)] text-[var(--muted)]'
            }`}
          >
            ↑
          </button>
        </form>
      </div>
    </div>
  )
}
