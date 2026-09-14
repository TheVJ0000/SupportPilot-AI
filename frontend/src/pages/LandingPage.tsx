import { Link } from 'react-router-dom'
import { BackendHealthStatus } from '../components/BackendHealthStatus'
import { Brand } from '../components/Brand'

export function LandingPage() {
  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#07111f] px-5 py-8 text-white sm:px-8">
      <div className="pointer-events-none absolute inset-0 opacity-80 [background-image:radial-gradient(circle_at_15%_20%,rgba(45,212,191,0.16),transparent_32%),radial-gradient(circle_at_85%_75%,rgba(56,189,248,0.14),transparent_34%)]" />
      <div className="relative mx-auto flex w-full max-w-6xl flex-col">
        <header className="flex items-center justify-between gap-4">
          <Brand compact />
          <nav aria-label="Account" className="flex items-center gap-3">
            <Link className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-300 hover:text-white" to="/login">
              Log in
            </Link>
            <Link className="rounded-xl bg-cyan-300 px-4 py-2.5 text-sm font-bold text-[#07111f] hover:bg-cyan-200" to="/register">
              Get started
            </Link>
          </nav>
        </header>

        <section className="grid flex-1 items-center gap-12 py-20 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.24em] text-teal-300">
              Grounded support, thoughtfully built
            </p>
            <h1 className="max-w-4xl text-5xl font-semibold tracking-[-0.045em] text-balance sm:text-6xl lg:text-7xl">
              Answers your customers can <span className="text-cyan-300">trust.</span>
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300 sm:text-xl">
              SupportPilot AI turns approved business knowledge into clear, grounded customer-support answers with visible sources and safe escalation paths.
            </p>
            <div className="mt-9 flex flex-wrap gap-4">
              <Link className="rounded-xl bg-cyan-300 px-6 py-3.5 font-bold text-[#07111f] hover:bg-cyan-200" to="/register">
                Create an account
              </Link>
              <Link className="rounded-xl border border-white/15 bg-white/5 px-6 py-3.5 font-semibold hover:bg-white/10" to="/login">
                Log in
              </Link>
            </div>
          </div>

          <aside className="rounded-3xl border border-white/10 bg-white/[0.055] p-7 shadow-2xl shadow-cyan-950/30 backdrop-blur-xl">
            <p className="text-sm font-semibold text-cyan-300">Built for responsible AI support</p>
            <ul className="mt-6 space-y-5 text-slate-300">
              {[
                'Answers grounded in business-approved knowledge',
                'Clear source context instead of unsupported claims',
                'Workspace isolation designed into every layer',
              ].map((item) => (
                <li className="flex gap-3" key={item}>
                  <span className="mt-2 size-1.5 shrink-0 rounded-full bg-teal-300" />
                  {item}
                </li>
              ))}
            </ul>
          </aside>
        </section>

        <footer className="flex items-center justify-between border-t border-white/10 py-5 text-xs text-slate-500">
          <span>Personal portfolio project · Phase 2</span>
          <BackendHealthStatus />
        </footer>
      </div>
    </main>
  )
}
