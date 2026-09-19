type Alternative = { transcript: string }
type Result = ArrayLike<Alternative> & { isFinal: boolean }
type ResultEvent = { results: ArrayLike<Result> }

interface Recognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: ResultEvent) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
}

type RecognitionCtor = new () => Recognition

const ctor: RecognitionCtor | undefined =
  typeof window === 'undefined'
    ? undefined
    : (window as unknown as Record<string, RecognitionCtor | undefined>).SpeechRecognition ??
      (window as unknown as Record<string, RecognitionCtor | undefined>).webkitSpeechRecognition

export const supported = ctor !== undefined

let active: Recognition | null = null

export function stop(): void {
  const r = active
  active = null
  if (!r) return
  r.onresult = null
  r.onend = null
  r.onerror = null
  try {
    r.abort()
  } catch {
    r.stop()
  }
}

export function start(onText: (text: string, final: boolean) => void, onEnd: () => void): void {
  if (!ctor) return
  stop()
  const r = new ctor()
  r.lang = 'en-US'
  r.interimResults = true
  r.continuous = false
  r.maxAlternatives = 1
  r.onresult = (e) => {
    let text = ''
    let final = false
    for (let i = 0; i < e.results.length; i++) {
      const result = e.results[i]
      text += result[0].transcript
      if (result.isFinal) final = true
    }
    onText(text.trim(), final)
  }
  const end = () => {
    if (active === r) active = null
    onEnd()
  }
  r.onend = end
  r.onerror = end
  active = r
  try {
    r.start()
  } catch {
    end()
  }
}
