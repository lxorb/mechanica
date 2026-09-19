import type { Manual } from '../types'

export type VoiceConfig = { elevenlabsAgentId: string | null; deepgram: boolean }

const base = import.meta.env.VITE_API_URL as string | undefined
const RATE = 16000
const FRAME = 1280
const MAX_KEYTERMS = 40

const STOP = new Set([
  'the', 'and', 'for', 'with', 'from', 'your', 'that', 'this', 'into', 'onto', 'over', 'when', 'work',
  'works', 'after', 'before', 'using', 'each', 'both', 'only', 'more', 'than', 'also', 'must', 'have',
])

const WORKLET = `class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel && channel.length) {
      const copy = new Float32Array(channel)
      this.port.postMessage(copy, [copy.buffer])
    }
    return true
  }
}
registerProcessor('ttm-tap', Tap)`

let configOnce: Promise<VoiceConfig | null> | null = null

export function voiceConfig(): Promise<VoiceConfig | null> {
  if (!base) return Promise.resolve(null)
  if (!configOnce) {
    configOnce = fetch(`${base}/voice/config`)
      .then((r) => (r.ok ? (r.json() as Promise<VoiceConfig>) : null))
      .catch(() => null)
  }
  return configOnce
}

export const supported =
  typeof window !== 'undefined' &&
  typeof WebSocket !== 'undefined' &&
  typeof AudioContext !== 'undefined' &&
  Boolean(navigator?.mediaDevices?.getUserMedia) &&
  Boolean(base)

let keyterms: string[] = []

export function prime(manual: Manual): void {
  const out: string[] = []
  const seen = new Set<string>()
  for (const source of [...manual.sections.map((s) => s.title), ...manual.parts.map((p) => p.name)]) {
    for (const raw of source.split(/[^A-Za-z0-9-]+/)) {
      const word = raw.replace(/^-+|-+$/g, '')
      const low = word.toLowerCase()
      if (word.length < 4 || STOP.has(low) || seen.has(low)) continue
      seen.add(low)
      out.push(word)
      if (out.length >= MAX_KEYTERMS) {
        keyterms = out
        return
      }
    }
  }
  keyterms = out
}

type Session = {
  ws: WebSocket | null
  ctx: AudioContext | null
  stream: MediaStream | null
  node: AudioNode | null
  src: AudioNode | null
  worklet: string | null
  dead: boolean
}

let live: Session | null = null

function tear(s: Session): void {
  s.dead = true
  const ws = s.ws
  s.ws = null
  if (ws) {
    ws.onmessage = null
    ws.onerror = null
    ws.onclose = null
    try {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'CloseStream' }))
    } catch {
      /* closed */
    }
    try {
      ws.close()
    } catch {
      /* closed */
    }
  }
  try {
    s.src?.disconnect()
    s.node?.disconnect()
  } catch {
    /* detached */
  }
  for (const track of s.stream?.getTracks() ?? []) track.stop()
  s.ctx?.close().catch(() => {})
  if (s.worklet) URL.revokeObjectURL(s.worklet)
  s.worklet = null
}

export function stop(): void {
  const s = live
  live = null
  if (s) tear(s)
}

function pcm16(input: Float32Array, from: number): ArrayBuffer {
  const ratio = from / RATE
  const count = Math.floor(input.length / ratio)
  const out = new Int16Array(count)
  for (let i = 0; i < count; i++) {
    const sample = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]))
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }
  return out.buffer
}

export function start(onText: (text: string, final: boolean) => void, onEnd: () => void): void {
  stop()
  const session: Session = { ws: null, ctx: null, stream: null, node: null, src: null, worklet: null, dead: false }
  live = session

  const finish = () => {
    if (session.dead) return
    if (live === session) live = null
    tear(session)
    onEnd()
  }

  run(session, onText, finish).catch(finish)
}

async function run(session: Session, onText: (text: string, final: boolean) => void, finish: () => void) {
  const res = await fetch(`${base}/voice/deepgram-token`, { method: 'POST' })
  if (!res.ok) throw new Error('deepgram token')
  const { key } = (await res.json()) as { key: string }
  if (session.dead) return

  session.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  })
  if (session.dead) {
    tear(session)
    return
  }

  const ctx = new AudioContext({ sampleRate: RATE })
  session.ctx = ctx

  const params = new URLSearchParams({
    model: 'flux-general-en',
    encoding: 'linear16',
    sample_rate: String(RATE),
  })
  for (const term of keyterms) params.append('keyterm', term)

  const ws = new WebSocket(`wss://api.deepgram.com/v2/listen?${params.toString()}`, ['token', key])
  ws.binaryType = 'arraybuffer'
  session.ws = ws

  ws.onmessage = (event) => {
    if (typeof event.data !== 'string') return
    let msg: { type?: string; event?: string; transcript?: string }
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }
    if (msg.type === 'Error' || msg.type === 'ConfigureFailure') {
      finish()
      return
    }
    if (msg.type !== 'TurnInfo') return
    const text = (msg.transcript ?? '').trim()
    const done = msg.event === 'EndOfTurn'
    if (text) onText(text, done)
    if (done) finish()
  }
  ws.onerror = () => finish()
  ws.onclose = () => finish()

  const need = Math.max(1, Math.round(FRAME * (ctx.sampleRate / RATE)))
  let queue = new Float32Array(0)
  const push = (chunk: Float32Array) => {
    const merged = new Float32Array(queue.length + chunk.length)
    merged.set(queue)
    merged.set(chunk, queue.length)
    queue = merged
    while (queue.length >= need) {
      if (ws.readyState === WebSocket.OPEN) ws.send(pcm16(queue.subarray(0, need), ctx.sampleRate))
      queue = queue.slice(need)
    }
  }

  let node: AudioNode
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    session.worklet = url
    await ctx.audioWorklet.addModule(url)
    if (session.dead) {
      tear(session)
      return
    }
    const tap = new AudioWorkletNode(ctx, 'ttm-tap')
    tap.port.onmessage = (e) => push(e.data as Float32Array)
    node = tap
  } catch {
    const proc = ctx.createScriptProcessor(4096, 1, 1)
    proc.onaudioprocess = (e) => push(new Float32Array(e.inputBuffer.getChannelData(0)))
    node = proc
  }

  const sink = ctx.createGain()
  sink.gain.value = 0
  node.connect(sink)
  sink.connect(ctx.destination)

  const src = ctx.createMediaStreamSource(session.stream)
  src.connect(node)
  session.src = src
  session.node = node
  if (ctx.state === 'suspended') await ctx.resume()
}
