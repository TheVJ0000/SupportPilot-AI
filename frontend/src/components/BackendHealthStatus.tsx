import { useEffect, useState } from 'react'
import { getHealth } from '../api/health'

export function BackendHealthStatus() {
  const [status, setStatus] = useState<'loading' | 'online' | 'offline'>('loading')

  useEffect(() => {
    const controller = new AbortController()
    void getHealth(controller.signal)
      .then(() => setStatus('online'))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) setStatus('offline')
      })
    return () => controller.abort()
  }, [])

  const labels = {
    loading: 'Checking service',
    online: 'Service online',
    offline: 'Service unavailable',
  }

  return (
    <div aria-live="polite" className="inline-flex items-center gap-2 text-xs text-slate-400">
      <span
        className={`size-2 rounded-full ${
          status === 'online'
            ? 'bg-emerald-300'
            : status === 'offline'
              ? 'bg-rose-300'
              : 'animate-pulse bg-amber-300'
        }`}
      />
      {labels[status]}
    </div>
  )
}
