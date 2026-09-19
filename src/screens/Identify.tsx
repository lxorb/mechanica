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
const STEP_MS = 24

const fade = {
  maskImage: 'linear-gradient(to bottom, #000 calc(100% - 26px), transparent)',
  WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 26px), transparent)',
}

const fadeRight = {
  maskImage: 'linear-gradient(to right, #000 calc(100% - 26px), transparent)',
  WebkitMaskImage: 'linear-gradient(to right, #000 calc(100% - 26px), transparent)',
  scrollbarWidth: 'none' as const,
}

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
  const [focused, setFocused] = useState(false)
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

  const bare = chips.length > 0 && !typed.trim()

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
        className={`d h-10 shrink-0 rounded-[10px] px-[14px] text-[15px] transition-colors duration-150 ${
          has
            ? 'bg-[var(--accent)] font-bold text-[var(--accent-ink)]'
            : live
              ? 'bg-[var(--ink-2)] font-semibold text-[var(--fg)] active:bg-[var(--line)]'
              : 'bg-[var(--ink-2)] font-semibold text-[var(--muted)] opacity-45'
        }`}
      >
        {value}
      </button>
    )
  }

  return (
    <div className="h-full w-full overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[430px] flex-col">
        <div className="shrink-0 px-4 pt-[max(28px,calc(env(safe-area-inset-top)+18px))] pb-1">
          <div
            className={`flex h-[52px] items-center gap-1 rounded-[14px] border bg-[var(--ink-1)] pr-[6px] pl-[14px] transition-colors duration-150 ${
              focused ? 'border-[var(--accent)]' : 'border-[var(--line)]'
            }`}
          >
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
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder="Make, model"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              enterKeyHint="search"
              className="h-full min-w-0 flex-1 bg-transparent text-[17px] outline-none placeholder:text-[var(--muted)]"
            />
            {q && (
              <button
                onClick={reset}
                aria-label="✕"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--ink-2)] text-[15px] leading-none text-[var(--muted)]"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        <div
          ref={listRef}
          style={{ ...fade, scrollbarWidth: 'none' }}
          className={`hairline min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pt-3 ${
            bare ? 'flex flex-col justify-end pb-1' : ''
          }`}
        >
          {photoUrl && (
            <div className="flex items-center gap-3 pb-3">
              <img
                src={photoUrl}
                alt=""
                className="h-16 w-16 shrink-0 rounded-[14px] border border-[var(--line)] object-cover"
              />
              <div className="flex-1" />
              <button
                onClick={reset}
                aria-label="✕"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] bg-[var(--ink-1)] text-[17px] leading-none text-[var(--muted)]"
              >
                ✕
              </button>
            </div>
          )}

          {chips.length > 0 && (
            <div className="flex flex-wrap gap-2 pb-2">
              {chips.map((make, i) => (
                <button
                  key={make}
                  onClick={() => setQ(`${make} `)}
                  style={bare ? { animationDelay: `${i * STEP_MS}ms` } : undefined}
                  className={`flex h-11 items-center rounded-xl bg-[var(--ink-1)] px-4 text-[15px] font-medium active:bg-[var(--ink-2)] ${
                    bare ? 'deal' : ''
                  }`}
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
              className="mb-2 flex w-full items-center justify-between gap-3 rounded-[14px] bg-[var(--ink-1)] py-3 pr-3 pl-[14px] text-left"
            >
              <span className="min-w-0 flex-1 truncate text-[17px] leading-snug font-medium">
                {vinBike.make} {vinBike.model}
              </span>
              <span
                className={`d flex h-10 shrink-0 items-center rounded-[10px] px-[14px] text-[15px] ${
                  vinBike.manualId
                    ? 'bg-[var(--accent)] font-bold text-[var(--accent-ink)]'
                    : 'bg-[var(--ink-2)] font-semibold text-[var(--muted)]'
                }`}
              >
                {vinBike.year}
              </span>
            </button>
          )}

          {rows.length > 0 && (
            <div className="flex flex-col gap-2">
              {rows.map((row) => (
                <div key={row.key} className="rounded-[14px] bg-[var(--ink-1)] py-3 pl-[14px]">
                  <div className="flex items-center gap-3 pr-[14px]">
                    <span className="min-w-0 flex-1 truncate text-[17px] leading-snug font-medium">
                      {row.make} {row.model}
                    </span>
                    {photoRows.confidence.has(row.key) && (
                      <span className="flex shrink-0 gap-[3px]">
                        {[0, 1, 2, 3, 4].map((i) => (
                          <i
                            key={i}
                            className={`block h-[3px] w-[6px] rounded-full ${
                              i < Math.round((photoRows.confidence.get(row.key) ?? 0) * 5)
                                ? 'bg-[var(--accent)]'
                                : 'bg-[var(--ink-2)]'
                            }`}
                          />
                        ))}
                      </span>
                    )}
                  </div>
                  <div style={fadeRight} className="hairline mt-[10px] flex gap-2 overflow-x-auto pr-[14px]">
                    {row.years.map((value) => year(row, value))}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="h-2 shrink-0" />
        </div>

        <div className="shrink-0 px-4 pt-3 pb-[max(16px,env(safe-area-inset-bottom))]">
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
                className="d h-14 min-w-0 flex-1 rounded-[14px] border border-[var(--line)] bg-[var(--ink-1)] px-4 text-[17px] font-semibold tracking-[0.1em] outline-none focus:border-[var(--accent)]"
              />
              <button
                onClick={reset}
                aria-label="✕"
                className="h-14 w-14 shrink-0 rounded-[14px] bg-[var(--ink-1)] text-[17px] leading-none text-[var(--muted)]"
              >
                ✕
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => fileRef.current?.click()}
                className="lab h-14 rounded-[14px] bg-[var(--accent)] text-[var(--accent-ink)] active:opacity-90"
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
                className="lab h-14 rounded-[14px] border border-[var(--line)] bg-[var(--ink-1)] text-[var(--fg)] active:bg-[var(--ink-2)]"
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
