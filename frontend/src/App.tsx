import { useEffect, useState } from 'react'
import { getHealth } from './api/health'

type ConnectionState =
  | { status: 'loading' }
  | { status: 'online'; service: string }
  | { status: 'offline' }

function ConnectionStatus({ state }: { state: ConnectionState }) {
  if (state.status === 'loading') {
    return (
      <div aria-live="polite" className="flex items-center gap-3 text-slate-300">
        <span className="size-2.5 animate-pulse rounded-full bg-amber-300 shadow-[0_0_18px_rgba(252,211,77,0.75)]" />
        <span>Checking backend connection…</span>
      </div>
    )
  }

  if (state.status === 'online') {
    return (
      <div aria-live="polite" className="flex items-center gap-3 text-emerald-200">
        <span className="size-2.5 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.8)]" />
        <span>
          Connected to <strong className="font-semibold text-white">{state.service}</strong>
        </span>
      </div>
    )
  }

  return (
    <div aria-live="assertive" className="flex items-start gap-3 text-rose-200">
      <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-rose-300 shadow-[0_0_18px_rgba(253,164,175,0.75)]" />
      <span>Backend unavailable. Start the API and confirm the configured URL.</span>
    </div>
  )
}

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    async function checkConnection() {
      try {
        const health = await getHealth(controller.signal)
        setConnection({ status: 'online', service: health.service })
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setConnection({ status: 'offline' })
      }
    }

    void checkConnection()
    return () => controller.abort()
  }, [])

  return (
    <main className="relative flex min-h-screen items-center overflow-hidden bg-[#07111f] px-5 py-12 text-white sm:px-8">
      <div className="pointer-events-none absolute inset-0 opacity-80 [background-image:radial-gradient(circle_at_15%_20%,rgba(45,212,191,0.16),transparent_32%),radial-gradient(circle_at_85%_75%,rgba(56,189,248,0.14),transparent_34%)]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.035)_1px,transparent_1px)] bg-[size:48px_48px]" />

      <section className="relative mx-auto grid w-full max-w-6xl gap-12 lg:grid-cols-[1.35fr_0.65fr] lg:items-center">
        <div>
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/5 px-3.5 py-2 text-sm font-medium text-cyan-100">
            <span className="size-1.5 rounded-full bg-cyan-300" />
            Phase 1 · Application foundation
          </div>

          <p className="mb-5 text-sm font-semibold uppercase tracking-[0.24em] text-teal-300">
            Grounded support, thoughtfully built
          </p>
          <h1 className="max-w-4xl text-5xl font-semibold tracking-[-0.045em] text-balance sm:text-6xl lg:text-7xl">
            SupportPilot <span className="text-cyan-300">AI</span>
          </h1>
          <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300 sm:text-xl">
            An AI-powered customer-support platform designed to deliver useful answers from trusted business knowledge.
          </p>
        </div>

        <aside className="rounded-3xl border border-white/10 bg-white/[0.055] p-6 shadow-2xl shadow-cyan-950/30 backdrop-blur-xl sm:p-8">
          <div className="mb-8 flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-slate-400">System status</p>
              <h2 className="mt-1 text-xl font-semibold text-white">API health</h2>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 font-mono text-xs text-slate-400">
              GET /api/health
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
            <ConnectionStatus state={connection} />
          </div>

          <p className="mt-6 text-sm leading-6 text-slate-400">
            This connection confirms the React frontend can reach the FastAPI service. Product capabilities will be added incrementally in later phases.
          </p>
        </aside>
      </section>
    </main>
  )
}
