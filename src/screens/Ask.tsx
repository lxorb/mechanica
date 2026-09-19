import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { Bike, Manual, Section } from '../types'
import * as speech from '../lib/speech'
import * as deepgram from '../lib/deepgram'
import { identifyPart } from '../lib/api'
import { track } from '../lib/busy'
import { online } from '../lib/source'

type Stt = {
  supported: boolean
  start: (onText: (text: string, final: boolean) => void, onEnd: () => void) => void
  stop: () => void
}

const CHIPS = 16

const PHRASE: Record<string, string> = {
  brake_pad: 'brake pads',
  chain: 'chain tension',
  spark_plug: 'spark plug',
  battery_terminal: 'battery',
  fuse_box: 'fuses',
  disc: 'brake disc',
  forks: 'front fork',
  radiator: 'coolant',
  shock_absorbers: 'rear suspension',
  brake_oil_reservoir: 'brake fluid',
}

const phraseOf = (label: string): string => PHRASE[label] ?? label.replace(/_/g, ' ')

const chapterOf = (chapter: string): [string, string] => {
  const hit = /^([\d.]+)\s+(\S.*)$/.exec(chapter)
  return hit ? [hit[1], hit[2]] : ['', chapter]
}

const fade = {
  maskImage: 'linear-gradient(to bottom, #000 calc(100% - 24px), transparent)',
  WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 24px), transparent)',
  scrollbarWidth: 'none' as const,
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

function Cam() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M3.8 8.6h3l1.4-2.3h5.6l1.4 2.3h3c.7 0 1.2.5 1.2 1.2v7.6c0 .7-.5 1.2-1.2 1.2H3.8c-.7 0-1.2-.5-1.2-1.2V9.8c0-.7.5-1.2 1.2-1.2Z" />
      <circle cx="12" cy="13.6" r="3.1" />
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
  onAsk: (query: string) => Promise<void>
  onBack: () => void
}) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stt, setStt] = useState<Stt>(speech)
  const input = useRef<HTMLInputElement>(null)
  const camRef = useRef<HTMLInputElement>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    if (!window.matchMedia('(pointer: coarse)').matches) input.current?.focus()
    return () => {
      alive.current = false
      speech.stop()
      deepgram.stop()
    }
  }, [])

  useEffect(() => {
    let live = true
    deepgram.voiceConfig().then((config) => {
      if (!live || !config?.deepgram || !deepgram.supported) return
      deepgram.prime(manual)
      setStt(deepgram)
    })
    return () => {
      live = false
    }
  }, [manual])

  const groups = useMemo(() => {
    const out: { key: string; number: string; words: string; items: Section[] }[] = []
    for (const section of manual.sections.slice(0, CHIPS)) {
      const last = out[out.length - 1]
      if (last && last.key === section.chapter) {
        last.items.push(section)
        continue
      }
      const [number, words] = chapterOf(section.chapter)
      out.push({ key: section.chapter, number, words, items: [section] })
    }
    return out
  }, [manual.sections])

  const fire = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    stt.stop()
    setListening(false)
    setBusy(true)
    onAsk(trimmed).finally(() => {
      if (alive.current) setBusy(false)
    })
  }

  const send = (q: string) => {
    if (busy) return
    fire(q)
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

  const onPart = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || busy) return
    if (!online) {
      input.current?.focus()
      return
    }
    stt.stop()
    setListening(false)
    setBusy(true)
    track(identifyPart(file))
      .then((found) => {
        if (!alive.current) return
        const top = found[0]
        if (!top) {
          setBusy(false)
          input.current?.focus()
          return
        }
        onAsk(phraseOf(top.label)).finally(() => {
          if (alive.current) setBusy(false)
        })
      })
      .catch(() => {
        if (!alive.current) return
        setBusy(false)
        input.current?.focus()
      })
  }

  const ready = text.trim().length > 0 && !busy

  return (
    <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
      <header className="shrink-0 px-4 pt-[max(22px,calc(env(safe-area-inset-top)+12px))]">
        <button
          onClick={onBack}
          aria-label="←"
          className="-ml-[10px] flex h-11 w-11 items-center justify-center text-[19px] leading-none"
        >
          ←
        </button>
        <div className="truncate text-[13px] leading-snug text-[var(--muted)]">
          {bike.make} {bike.model} {bike.year}
        </div>
        <div className="cover truncate pt-1 pb-2 text-[17px] leading-tight">{manual.title}</div>
      </header>

      <div
        style={fade}
        className={`hairline min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3 transition-opacity duration-150 ${
          busy ? 'pointer-events-none opacity-40' : ''
        }`}
      >
        {groups.map((g) => (
          <div key={g.key} className="flex flex-col gap-2 pb-2">
            <div className="sticky top-0 z-10 -mx-4 bg-[var(--ink)] px-4 pt-1 pb-2">
              <span className="inline-flex items-center gap-2 rounded-lg bg-[var(--ink-1)] px-[10px] py-[5px] align-middle">
                {g.number && <span className="d text-[18px] leading-none font-bold text-[var(--accent)]">{g.number}</span>}
                <span className="text-[11px] leading-[1.2] tracking-[0.08em] text-[var(--muted)] uppercase">{g.words}</span>
              </span>
            </div>
            {g.items.map((s) => (
              <button
                key={s.id}
                onClick={() => send(s.title)}
                className="flex min-h-14 w-full items-center gap-3 rounded-[14px] border border-transparent bg-[var(--ink-1)] py-3 pr-3 pl-[14px] text-left transition-colors duration-150 active:border-[var(--accent)]/35"
              >
                <span className="min-w-0 flex-1 text-[15px] leading-snug">{s.title}</span>
                <span className="flex h-7 shrink-0 items-baseline gap-[3px] rounded-lg bg-[var(--ink-2)] px-[9px]">
                  <span className="text-[12px] text-[var(--muted)]">p.</span>
                  <span className="d text-[15px] font-semibold">{s.pageStart}</span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>

      <div className="shrink-0 px-4 pt-2 pb-[max(14px,env(safe-area-inset-bottom))]">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
          className="flex items-center gap-[2px] rounded-2xl border border-[var(--line)] bg-[var(--ink-1)] p-1 focus-within:border-[var(--accent)]/45"
        >
          {stt.supported && (
            <button
              type="button"
              onClick={mic}
              aria-pressed={listening}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--muted)] ${
                listening ? 'animate-[ring_2s_ease-in-out_infinite]' : ''
              }`}
            >
              <Mic on={listening} />
            </button>
          )}
          <button
            type="button"
            onClick={() => camRef.current?.click()}
            aria-label="Photo"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[var(--muted)]"
          >
            <Cam />
          </button>
          <input
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            enterKeyHint="go"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            className="min-w-0 flex-1 bg-transparent py-3 pl-1 text-[17px] outline-none placeholder:text-[var(--muted)]"
            placeholder="What do you want to do?"
          />
          <button
            type="submit"
            aria-label="↑"
            disabled={!ready}
            className={`d flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[19px] leading-none transition-colors duration-150 ${
              ready ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'bg-[var(--ink-2)] text-[var(--muted)]'
            }`}
          >
            ↑
          </button>
        </form>
      </div>

      <input ref={camRef} type="file" accept="image/*" capture="environment" onChange={onPart} className="hidden" />
    </div>
  )
}
