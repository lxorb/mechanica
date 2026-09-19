import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { Bike, Manual } from '../types'
import { ingest } from '../lib/source'
import type { IngestProgress } from '../lib/source'

declare global {
  interface Window {
    Dropbox?: {
      choose(options: {
        success: (files: { link: string; name: string }[]) => void
        cancel?: () => void
        linkType?: 'preview' | 'direct'
        extensions?: string[]
        multiselect?: boolean
      }): void
    }
  }
}

const APP_KEY: string = import.meta.env.VITE_DROPBOX_APP_KEY ?? ''
const CHOOSER = 'https://www.dropbox.com/static/api/2/dropins.js'
const EASE = 150

let loading: Promise<void> | null = null

function chooser(): Promise<void> {
  if (window.Dropbox) return Promise.resolve()
  if (!loading) {
    loading = new Promise<void>((ok, fail) => {
      const el = document.createElement('script')
      el.src = CHOOSER
      el.id = 'dropboxjs'
      el.dataset.appKey = APP_KEY
      el.onload = () => ok()
      el.onerror = () => {
        loading = null
        fail(new Error('chooser'))
      }
      document.head.append(el)
    })
  }
  return loading
}

export default function AddManual({
  bike,
  onDone,
  onClose,
}: {
  bike: Bike
  onDone: (manual: Manual) => void
  onClose: () => void
}) {
  const [progress, setProgress] = useState<IngestProgress | null>(null)
  const [shown, setShown] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)))
    return () => {
      alive.current = false
      cancelAnimationFrame(frame)
    }
  }, [])

  const close = () => {
    setShown(false)
    setTimeout(onClose, EASE)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const start = (source: File | string) => {
    setProgress({ status: 'queued', done: 0, pages: 0, title: null })
    ingest(
      source,
      { make: bike.make, model: bike.model, year: bike.year, market: bike.market },
      (p) => {
        if (alive.current) setProgress(p)
      },
    )
      .then((manual) => {
        if (alive.current) onDone(manual)
      })
      .catch(() => {
        if (alive.current) setProgress(null)
      })
  }

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) start(file)
  }

  const fromDropbox = () => {
    chooser()
      .then(() =>
        window.Dropbox?.choose({
          linkType: 'direct',
          extensions: ['.pdf'],
          multiselect: false,
          success: (files) => {
            if (files[0]) start(files[0].link)
          },
        }),
      )
      .catch(() => {})
  }

  const ratio = progress && progress.pages > 0 ? Math.min(1, progress.done / progress.pages) : 0

  return (
    <div className="fixed inset-0 z-40 flex items-end">
      <button
        onClick={close}
        aria-label="✕"
        className="absolute inset-0 bg-black/60 transition-opacity ease-out"
        style={{ opacity: shown ? 1 : 0, transitionDuration: `${EASE}ms` }}
      />
      <div
        className="relative mx-auto w-full max-w-[430px] rounded-t-xl border-t border-[var(--line)] bg-[var(--bg)] px-4 pt-3 pb-[max(16px,env(safe-area-inset-bottom))] transition-transform ease-out"
        style={{ transform: shown ? 'translateY(0)' : 'translateY(100%)', transitionDuration: `${EASE}ms` }}
      >
        <div className="flex justify-end">
          <button
            onClick={close}
            aria-label="✕"
            className="flex h-11 w-11 items-center justify-center text-[17px] leading-none text-[var(--muted)]"
          >
            ✕
          </button>
        </div>

        {progress ? (
          <div className="pb-3">
            <div className="h-[2px] w-full rounded-full bg-[var(--line)]">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-300"
                style={{ width: `${Math.round(ratio * 100)}%` }}
              />
            </div>
            {progress.title && <div className="truncate pt-3 text-[15px] font-medium">{progress.title}</div>}
          </div>
        ) : (
          <div className={`grid gap-3 pb-3 ${APP_KEY ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <button
              onClick={() => fileRef.current?.click()}
              className="h-14 rounded-xl bg-[var(--accent)] text-[17px] font-medium text-[var(--bg)]"
            >
              PDF
            </button>
            {APP_KEY && (
              <button onClick={fromDropbox} className="h-14 rounded-xl border border-[var(--line)] text-[17px] font-medium">
                Dropbox
              </button>
            )}
          </div>
        )}

        <input ref={fileRef} type="file" accept="application/pdf" onChange={onFile} className="hidden" />
      </div>
    </div>
  )
}
