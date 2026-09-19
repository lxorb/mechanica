import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { Bike, Manual } from '../types'
import type { Model } from '../data'
import { bikeOf, group, makes as allMakes } from '../data'
import { LIMIT, cleanVin, matchingMakes, search } from '../lib/identify'
import type { PhotoHit } from '../lib/source'
import { identifyPhoto, identifyVin, online, suggest } from '../lib/source'
import AddManual from '../components/AddManual'

const VIN_MIN = 6
const SUGGEST_MS = 150
const VIN_MS = 120
const MAKE_CHIPS = 24

export default function Identify({
  catalog,
  onSelect,
  onManual,
}: {
  catalog: Model[]
  onSelect: (bike: Bike) => void
  onManual?: (bike: Bike, manual: Manual) => void
}) {
  const [q, setQ] = useState('')
  const [remote, setRemote] = useState<Model[]>([])
  const [vin, setVin] = useState('')
  const [vinMode, setVinMode] = useState(false)
  const [vinHit, setVinHit] = useState<{ vin: string; bike: Bike | null } | null>(null)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const [hits, setHits] = useState<PhotoHit[]>([])
  const [adding, setAdding] = useState<Bike | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const canAdd = online && Boolean(onManual)
  const typed = useDeferredValue(q)
  const clean = cleanVin(vin)
  const vinBike = vinMode && vinHit?.vin === clean ? vinHit.bike : null

  useEffect(() => {
    if (!photoUrl) return
    return () => URL.revokeObjectURL(photoUrl)
  }, [photoUrl])

  useEffect(() => {
    if (!online || !q.trim()) return
    const control = new AbortController()
    const timer = setTimeout(() => {
      suggest(q, control.signal)
        .then(setRemote)
        .catch(() => {})
    }, SUGGEST_MS)
    return () => {
      clearTimeout(timer)
      control.abort()
    }
  }, [q])

  useEffect(() => {
    if (!vinMode || clean.length < VIN_MIN) return
    let alive = true
    const timer = setTimeout(() => {
      identifyVin(clean).then((bike) => {
        if (alive) setVinHit({ vin: clean, bike })
      })
    }, VIN_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [clean, vinMode])

  useEffect(() => {
    listRef.current?.scrollTo({ top: 0 })
  }, [q, photoUrl])

  const photoRows = useMemo(() => {
    if (hits.length === 0) return { rows: [] as Model[], confidence: new Map<string, number>() }
    const rows = group(hits.map((h) => h.bike))
    const confidence = new Map<string, number>()
    for (const hit of hits) {
      const row = rows.find((r) => r.make === hit.bike.make && r.model === hit.bike.model)
      if (row) confidence.set(row.key, Math.max(confidence.get(row.key) ?? 0, hit.confidence))
    }
    rows.sort((a, z) => (confidence.get(z.key) ?? 0) - (confidence.get(a.key) ?? 0))
    return { rows: rows.slice(0, LIMIT), confidence }
  }, [hits])

  const rows = useMemo(() => {
    if (!typed.trim()) return photoUrl ? photoRows.rows : []
    const base = search(catalog, typed)
    if (remote.length === 0) return base
    const at = new Map(base.map((row, i) => [row.key, i]))
    const out = [...base]
    for (const row of search(remote, typed)) {
      const i = at.get(row.key)
      if (i === undefined) {
        if (out.length < LIMIT) out.push(row)
        continue
      }
      out[i] = {
        ...out[i],
        years: [...new Set([...out[i].years, ...row.years])].sort((a, z) => z - a),
        manuals: { ...out[i].manuals, ...row.manuals },
      }
    }
    return out
  }, [catalog, typed, remote, photoUrl, photoRows])

  const chips = useMemo(() => {
    if (vinMode || photoUrl) return []
    if (!typed.trim()) return allMakes.slice(0, MAKE_CHIPS)
    return matchingMakes(allMakes, typed, MAKE_CHIPS)
  }, [typed, vinMode, photoUrl])

  const reset = () => {
    setQ('')
    setVin('')
    setVinMode(false)
    setVinHit(null)
    setPhotoUrl(null)
    setHits([])
  }

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setQ('')
    setVin('')
    setVinMode(false)
    setVinHit(null)
    setHits([])
    setPhotoUrl(URL.createObjectURL(file))
    const found = await identifyPhoto(file)
    setHits(found)
  }

  const pick = (bike: Bike) => {
    if (bike.manualId) onSelect(bike)
    else if (canAdd) setAdding(bike)
  }

  const year = (row: Model, value: number) => {
    const bike = bikeOf(row, value)
    const has = Boolean(bike.manualId)
    const live = has || canAdd
    return (
      <button
        key={value}
        onClick={() => pick(bike)}
        disabled={!live}
        className={`h-11 shrink-0 rounded-xl border px-4 text-[15px] font-medium tabular-nums transition-colors duration-150 ${
          has
            ? 'border-[var(--accent)] text-[var(--fg)]'
            : live
              ? 'border-[var(--line)] text-[var(--muted)]'
              : 'border-[var(--line)] text-[var(--muted)] opacity-40'
        }`}
      >
        {value}
      </button>
    )
  }

  return (
    <div className="h-full w-full overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
        <div className="shrink-0 px-4 pt-[max(16px,env(safe-area-inset-top))] pb-2">
          <div className="flex items-center gap-2 rounded-xl border border-[var(--line)] pr-1 focus-within:border-[var(--muted)]">
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value)
                if (e.target.value.trim()) {
                  setVinMode(false)
                  setVinHit(null)
                  setPhotoUrl(null)
                  setHits([])
                }
              }}
              placeholder="Make, model"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              enterKeyHint="search"
              className="h-11 min-w-0 flex-1 bg-transparent pl-3 text-[17px] outline-none placeholder:text-[var(--muted)]"
            />
            {q && (
              <button
                onClick={reset}
                aria-label="✕"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[17px] leading-none text-[var(--muted)]"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4">
          {photoUrl && (
            <div className="flex items-center gap-3 py-3">
              <img
                src={photoUrl}
                alt=""
                className="h-14 w-14 shrink-0 rounded-xl border border-[var(--line)] object-cover"
              />
              <div className="flex-1" />
              <button
                onClick={reset}
                aria-label="✕"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[var(--line)] text-[17px] leading-none text-[var(--muted)]"
              >
                ✕
              </button>
            </div>
          )}

          {chips.length > 0 && (
            <div className="flex flex-wrap gap-2 py-2">
              {chips.map((make) => (
                <button
                  key={make}
                  onClick={() => setQ(`${make} `)}
                  className="h-11 rounded-xl border border-[var(--line)] px-4 text-[15px] font-medium"
                >
                  {make}
                </button>
              ))}
            </div>
          )}

          {vinBike && (
            <button
              onClick={() => pick(vinBike)}
              disabled={!vinBike.manualId && !canAdd}
              className="flex min-h-14 w-full items-center justify-between gap-3 border-b border-[var(--line)] py-3 text-left"
            >
              <span className="text-[17px] leading-snug font-medium">
                {vinBike.make} {vinBike.model}
              </span>
              <span
                className={`flex h-11 shrink-0 items-center rounded-xl border px-4 text-[15px] font-medium tabular-nums ${
                  vinBike.manualId ? 'border-[var(--accent)]' : 'border-[var(--line)] text-[var(--muted)]'
                }`}
              >
                {vinBike.year}
              </span>
            </button>
          )}

          {rows.map((row) => (
            <div key={row.key} className="border-b border-[var(--line)] py-3">
              <div className="flex items-center gap-3">
                <span className="min-w-0 flex-1 truncate text-[17px] leading-snug font-medium">
                  {row.make} {row.model}
                </span>
                {photoRows.confidence.has(row.key) && (
                  <span className="h-[2px] w-12 shrink-0 rounded-full bg-[var(--line)]">
                    <span
                      className="block h-full rounded-full bg-[var(--muted)]"
                      style={{ width: `${Math.round((photoRows.confidence.get(row.key) ?? 0) * 100)}%` }}
                    />
                  </span>
                )}
              </div>
              <div
                style={{ scrollbarWidth: 'none' }}
                className="-mx-4 mt-2 flex gap-2 overflow-x-auto px-4 pb-0.5"
              >
                {row.years.map((value) => year(row, value))}
              </div>
            </div>
          ))}

          <div className="h-2" />
        </div>

        <div className="shrink-0 px-4 pt-2 pb-[max(16px,env(safe-area-inset-bottom))]">
          {vinMode ? (
            <div className="flex gap-3">
              <input
                value={vin}
                onChange={(e) => setVin(cleanVin(e.target.value))}
                maxLength={17}
                autoCapitalize="characters"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="done"
                autoFocus
                className="h-14 min-w-0 flex-1 rounded-xl border border-[var(--line)] bg-transparent px-3 font-mono text-[17px] tracking-[0.08em] outline-none focus:border-[var(--muted)]"
              />
              <button
                onClick={reset}
                aria-label="✕"
                className="h-14 w-14 shrink-0 rounded-xl border border-[var(--line)] text-[17px] leading-none text-[var(--muted)]"
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
                  setHits([])
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
