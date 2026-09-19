import { useEffect, useState } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import type { Bike, Manual } from '../types'
import { voiceConfig } from '../lib/deepgram'

type Props = { bike: Bike; manual: Manual; onPage: (page: number) => void }

function Glyph() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11.5a7 7 0 0 0 14 0" />
      <path d="M12 18.5V21" />
    </svg>
  )
}

function Talk({ bike, manual, onPage, agentId }: Props & { agentId: string }) {
  const { status, startSession, endSession } = useConversation({
    clientTools: {
      show_page: (params: { page?: number | string }) => {
        const page = Number(params?.page)
        if (Number.isFinite(page) && page > 0) onPage(page)
      },
    },
  })

  const live = status === 'connected' || status === 'connecting'

  useEffect(() => () => endSession(), [endSession])

  const toggle = async () => {
    if (live) {
      endSession()
      return
    }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      return
    }
    startSession({
      agentId,
      connectionType: 'webrtc',
      dynamicVariables: {
        bike_name: `${bike.make} ${bike.model} ${bike.year}`,
        manual_id: manual.id,
      },
    })
  }

  return (
    <button
      onClick={toggle}
      aria-pressed={live}
      className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full border ${
        live
          ? 'animate-pulse border-[var(--accent)] text-[var(--accent)]'
          : 'border-[var(--line)] text-[var(--muted)]'
      }`}
    >
      <Glyph />
    </button>
  )
}

export default function Voice(props: Props) {
  const [agentId, setAgentId] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    voiceConfig().then((c) => {
      if (alive) setAgentId(c?.elevenlabsAgentId ?? null)
    })
    return () => {
      alive = false
    }
  }, [])

  if (!agentId) return null

  return (
    <ConversationProvider>
      <Talk {...props} agentId={agentId} />
    </ConversationProvider>
  )
}
