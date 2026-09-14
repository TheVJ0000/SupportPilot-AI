import { Link } from 'react-router-dom'

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className="inline-flex items-center gap-3 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
      <span className="grid size-10 place-items-center rounded-xl bg-cyan-300 font-black text-[#07111f] shadow-lg shadow-cyan-950/30">
        S
      </span>
      <span className={compact ? 'text-lg font-semibold' : 'text-xl font-semibold tracking-tight'}>
        SupportPilot <span className="text-cyan-300">AI</span>
      </span>
    </Link>
  )
}
