import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { Bike, Candidate, Manual } from '../types'
import { search, years } from '../lib/identify'
import { identifyPhoto, identifyVin, online } from '../lib/source'
import AddManual from '../components/AddManual'

type Row = { key: string; make: string; model: string; models: Bike[]; confidence?: number }

const LIMIT = 30
const VIN_MIN = 8

const keyOf = (b: Bike) => `${b.make}|${b.model}`.toLowerCase()

const span = (list: Bike[]) => {
  if (list.length === 0) return ''
  const a = list[0].year
  const z = list[list.length - 1].year
  return a === z ? `${a}` : `${a}–${z}`
}

export default function Identify({
  bikes,
  onSelect,
  onManual,
}: {
  bikes: Bike[]
  onSelect: (bike: Bike) => void
  onManual?: (bike: Bike, manual: Manual) => void
}) {
  const [q, setQ] = useState('')
  const [vin, setVin] = useState('')
  const [vinMode, setVinMode] = useState(false)
  const [vinHit, setVinHit] = useState<{ vin: string; bike: Bike | null } | null>(null)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState<Bike | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const canAdd = online && Boolean(onManual)

  useEffect(() => {
    if (!photoUrl) return
    return () => URL.revokeObjectURL(photoUrl)
  }, [photoUrl])

  const clean = vin.replace(/[^A-Za-z0-9]/g, '').toUpperCase()
  const vinBike = vinMode && vinHit?.vin === clean ? vinHit.bike : null

  useEffect(() => {
    if (!vinMode || clean.length < VIN_MIN) return
    let alive = true
    const timer = setTimeout(() => {
      identifyVin(bikes, clean).then((bike) => {
        if (alive) setVinHit({ vin: clean, bike })
      })
    }, 300)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [bikes, clean, vinMode])

  const byId = useMemo(() => new Map(bikes.map((b) => [b.id, b])), [bikes])

  const rows = useMemo<Row[]>(() => {
    const build = (list: Bike[], confidence?: (b: Bike) => number): Row[] => {
      const out: Row[] = []
      const seen = new Set<string>()
      for (const b of list) {
        const key = keyOf(b)
        if (seen.has(key)) continue
        seen.add(key)
        out.push({ key, make: b.make, model: b.model, models: years(bikes, b), confidence: confidence?.(b) })
        if (out.length === LIMIT) break
      }
      return out
    }
    if (q.trim()) return build(search(bikes, q))
    if (photoUrl) {
      const list = candidates.map((c) => byId.get(c.bikeId)).filter((b): b is Bike => !!b)
      const conf = new Map(candidates.map((c) => [c.bikeId, c.confidence]))
      return build(list, (b) => conf.get(b.id) ?? 0)
    }
    return []
  }, [bikes, byId, candidates, photoUrl, q])

  const reset = () => {
    setQ('')
    setVin('')
    setVinMode(false)
    setVinHit(null)
    setPhotoUrl(null)
    setCandidates([])
    setOpen(null)
  }

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const url = URL.createObjectURL(file)
    setQ('')
    setVin('')
    setVinMode(false)
    setVinHit(null)
    setOpen(null)
    setCandidates([])
    setPhotoUrl(url)
    const found = await identifyPhoto(bikes, file)
    setCandidates(found)
  }

  const pick = (bike: Bike) => {
    if (bike.manualId) onSelect(bike)
    else if (canAdd) setAdding(bike)
  }

  return (
    <div className="h-full w-full overflow-hidden bg-[var(--bg)] text-[var(--fg)]">
      <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
        <div className="px-4 pt-4 pb-2">
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setOpen(null)
              if (e.target.value.trim()) {
                setVinMode(false)
                setVinHit(null)
                setPhotoUrl(null)
                setCandidates([])
              }
            }}
            placeholder="Make, model"
            autoCorrect="off"
            spellCheck={false}
            className="h-[44px] w-full rounded-xl border border-[var(--line)] bg-transparent px-3 text-[17px] outline-none placeholder:text-[var(--muted)] focus:border-[var(--muted)]"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4">
          {photoUrl && !q.trim() && (
            <div className="flex items-center gap-3 py-3">
              <img src={photoUrl} alt="" className="h-[56px] w-[56px] rounded-xl border border-[var(--line)] object-cover" />
              <div className="flex-1" />
              <button
                onClick={reset}
                aria-label="✕"
                className="flex h-[44px] w-[44px] items-center justify-center rounded-xl border border-[var(--line)] text-[17px] text-[var(--muted)]"
              >
                ✕
              </button>
            </div>
          )}

          {vinBike && (
            <button
              onClick={() => pick(vinBike)}
              disabled={!vinBike.manualId && !canAdd}
              className={`flex min-h-[56px] w-full items-center justify-between gap-3 border-b border-[var(--line)] py-3 text-left ${
                vinBike.manualId ? '' : 'text-[var(--muted)] opacity-50'
              }`}
            >
              <span className="text-[17px] font-medium">
                {vinBike.make} {vinBike.model}
              </span>
              <span className="text-[13px] text-[var(--muted)]">{vinBike.year}</span>
            </button>
          )}

          {rows.map((row) => (
            <div key={row.key} className="border-b border-[var(--line)]">
              <button
                onClick={() => setOpen(open === row.key ? null : row.key)}
                className="flex min-h-[56px] w-full items-center justify-between gap-3 py-3 text-left"
              >
                <span className="flex-1 text-[17px] font-medium">
                  {row.make} {row.model}
                </span>
                <span className="text-[13px] text-[var(--muted)]">{open === row.key ? '' : span(row.models)}</span>
              </button>
              {row.confidence !== undefined && (
                <div className="mb-3 h-[2px] w-[64px] rounded-full bg-[var(--line)]">
                  <div className="h-full rounded-full bg-[var(--muted)]" style={{ width: `${Math.round(row.confidence * 100)}%` }} />
                </div>
              )}
              {open === row.key && (
                <div className="flex flex-wrap gap-2 pb-3">
                  {row.models.map((b) =>
                    b.manualId || canAdd ? (
                      <button
                        key={b.id}
                        onClick={() => pick(b)}
                        className={`min-h-[44px] rounded-xl border border-[var(--line)] px-4 text-[15px] font-medium ${
                          b.manualId ? '' : 'text-[var(--muted)] opacity-60'
                        }`}
                      >
                        {b.year}
                      </button>
                    ) : (
                      <span
                        key={b.id}
                        className="flex min-h-[44px] items-center rounded-xl border border-[var(--line)] px-4 text-[15px] text-[var(--muted)] opacity-40"
                      >
                        {b.year}
                      </span>
                    ),
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="px-4 pt-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
          {vinMode ? (
            <div className="flex gap-3">
              <input
                value={vin}
                onChange={(e) => setVin(e.target.value)}
                maxLength={17}
                autoCapitalize="characters"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                className="h-14 min-w-0 flex-1 rounded-xl border border-[var(--line)] bg-transparent px-3 font-mono text-[17px] tracking-[0.08em] uppercase outline-none focus:border-[var(--muted)]"
              />
              <button
                onClick={reset}
                aria-label="✕"
                className="h-14 w-14 shrink-0 rounded-xl border border-[var(--line)] text-[17px] text-[var(--muted)]"
              >
                ✕
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => fileRef.current?.click()}
                className="h-14 rounded-xl bg-[var(--accent)] text-[17px] font-medium text-[var(--bg)]"
              >
                Photo
              </button>
              <button
                onClick={() => {
                  setVinMode(true)
                  setQ('')
                  setPhotoUrl(null)
                  setCandidates([])
                  setOpen(null)
                }}
                className="h-14 rounded-xl border border-[var(--line)] text-[17px] font-medium"
              >
                VIN
              </button>
            </div>
          )}
        </div>

        <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" />

        {adding && onManual && (
          <AddManual
            bike={adding}
            onDone={(manual) => {
              const bike = adding
              setAdding(null)
              onManual(bike, manual)
            }}
            onClose={() => setAdding(null)}
          />
        )}
      </div>
    </div>
  )
}
