import { useBusy } from '../lib/busy'

export default function Progress() {
  const busy = useBusy()
  return (
    <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-50 h-[2px]">
      {busy && (
        <div
          className="h-full bg-[var(--accent)]"
          style={{ animation: 'ttm-progress 6s cubic-bezier(0, 0.7, 0.2, 1) forwards' }}
        />
      )}
    </div>
  )
}
