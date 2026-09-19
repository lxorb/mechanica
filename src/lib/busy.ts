import { useSyncExternalStore } from 'react'

let depth = 0
const listeners = new Set<() => void>()

const emit = () => {
  for (const fn of listeners) fn()
}

const subscribe = (fn: () => void): (() => void) => {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function begin(): void {
  depth++
  if (depth === 1) emit()
}

export function end(): void {
  if (depth === 0) return
  depth--
  if (depth === 0) emit()
}

export async function track<T>(work: Promise<T>): Promise<T> {
  begin()
  try {
    return await work
  } finally {
    end()
  }
}

export function useBusy(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => depth > 0,
    () => false,
  )
}
