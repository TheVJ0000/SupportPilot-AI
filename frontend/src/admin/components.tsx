import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ConversationItem, EscalationOverview } from './adminApi'
import { button, label, panel, textLink, timestamp } from './format'

export function Badge({ value }: { value: string | null }) {
  const color =
    value === 'urgent'
      ? 'bg-rose-400/15 text-rose-200'
      : value === 'high' || value === 'failed'
        ? 'bg-amber-400/15 text-amber-200'
        : value === 'completed' || value === 'sent' || value === 'answered'
          ? 'bg-emerald-400/15 text-emerald-200'
          : 'bg-slate-700/50 text-slate-200'
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs capitalize ${color}`}>
      {value ? label(value) : 'Not classified'}
    </span>
  )
}
export function PageHeading({
  title,
  description,
  workspace,
}: {
  title: string
  description: string
  workspace: string
}) {
  return (
    <header className="mb-7">
      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-cyan-300">
        {workspace} · Support operations
      </p>
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">{description}</p>
    </header>
  )
}
export function ResourceState({
  loading,
  error,
  retry,
  children,
}: {
  loading: boolean
  error?: string
  retry: () => void
  children: ReactNode
}) {
  if (loading)
    return (
      <div className={panel}>
        <p role="status" className="text-slate-400">
          Loading support operations…
        </p>
      </div>
    )
  if (error)
    return (
      <div className={panel}>
        <p role="alert" className="mb-4 text-rose-200">
          {error}
        </p>
        <button className={button} onClick={retry}>
          Try again
        </button>
      </div>
    )
  return <>{children}</>
}
export function ConversationRow({ item }: { item: ConversationItem }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 py-4 last:border-0">
      <div>
        <Link className={textLink} to={`/app/conversations/${item.id}`}>
          View conversation
        </Link>
        <p className="mt-1 text-xs text-slate-400">
          Last activity: {timestamp(item.last_message_at)} · {item.message_count} messages ·{' '}
          {item.assistant_message_count} assistant messages
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Helpful: {item.feedback_positive_count} · Not helpful: {item.feedback_negative_count}
          {item.has_escalation ? ' · Escalated' : ''}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge value={item.status} />
        <Badge value={item.resolution_outcome} />
        {item.has_escalation && <Badge value={item.escalation_priority} />}
      </div>
    </li>
  )
}
export function EscalationRow({ item }: { item: EscalationOverview }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 py-4 last:border-0">
      <div>
        <Link className={textLink} to={`/app/escalations/${item.id}`}>
          View escalation
        </Link>
        <p className="mt-1 text-xs text-slate-400 capitalize">
          {label(item.trigger_reason)} ·{' '}
          {item.category ? label(item.category) : 'Awaiting classification'}
        </p>
        <p className="mt-1 text-xs text-slate-500">Created: {timestamp(item.created_at)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge value={item.status} />
        <Badge value={item.triage_status} />
        {item.priority && <Badge value={item.priority} />}
      </div>
    </li>
  )
}
export function Filter({
  name,
  value,
  options,
  onChange,
}: {
  name: string
  value: string
  options: readonly string[]
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-2 text-xs text-slate-400">
      {name}
      <select
        className="rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-sm capitalize text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {label(option)}
          </option>
        ))}
      </select>
    </label>
  )
}
export function Pagination({
  page,
  hasNext,
  loading,
  next,
  previous,
}: {
  page: number
  hasNext: boolean
  loading: boolean
  next: () => void
  previous: () => void
}) {
  return (
    <div className="mt-5 flex items-center justify-between gap-3">
      <button className={button} disabled={loading || page === 0} onClick={previous}>
        Previous
      </button>
      <p className="text-xs text-slate-400">Page {page + 1}</p>
      <button className={button} disabled={loading || !hasNext} onClick={next}>
        Next
      </button>
    </div>
  )
}
