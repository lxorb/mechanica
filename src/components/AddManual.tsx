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
const EASE = 220

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
        className="absolute inset-0 bg-black/62 transition-opacity ease-out"
        style={{ opacity: shown ? 1 : 0, transitionDuration: `${EASE}ms` }}
      />
      <div
        className="relative mx-auto w-full max-w-[430px] rounded-t-[20px] border-t border-[var(--line)] bg-[var(--ink-1)] px-4 pb-[max(16px,env(safe-area-inset-bottom))] transition-transform"
        style={{
          transform: shown ? 'translateY(0)' : 'translateY(100%)',
          transitionDuration: `${EASE}ms`,
          transitionTimingFunction: 'cubic-bezier(0.2,0.8,0.2,1)',
        }}
      >
        <div className="relative flex h-11 items-center justify-center">
          <span className="h-1 w-9 rounded-full bg-[var(--line)]" />
          <button
            onClick={close}
            aria-label="✕"
            className="absolute top-0 right-1 flex h-11 w-11 items-center justify-center text-[15px] leading-none text-[var(--muted)]"
          >
            ✕
          </button>
        </div>

        {progress ? (
          <div className="pt-2 pb-4">
            <div className="h-[3px] w-full overflow-hidden rounded-full bg-[var(--line)]">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-[220ms]"
                style={{ width: `${Math.round(ratio * 100)}%` }}
              />
            </div>
            {progress.title && <div className="cover truncate pt-4 text-[15px]">{progress.title}</div>}
          </div>
        ) : (
          <div className={`grid gap-3 pt-1 pb-4 ${APP_KEY ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <button
              onClick={() => fileRef.current?.click()}
              className="lab h-14 rounded-[14px] bg-[var(--accent)] text-[var(--accent-ink)] active:opacity-90"
            >
              PDF
            </button>
            {APP_KEY && (
              <button
                onClick={fromDropbox}
                className="lab h-14 rounded-[14px] border border-[var(--line)] bg-[var(--ink-2)] active:bg-[var(--line)]"
              >
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
