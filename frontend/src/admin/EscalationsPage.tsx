import { useCallback, useState } from 'react'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi, type Cursor, type EscalationFilters } from './adminApi'
import { Badge, EscalationRow, Filter, PageHeading, Pagination, ResourceState } from './components'
import { panel } from './format'
import { useAdminResource } from './useAdminResource'

const filterOptions = {
  status: ['all', 'open', 'in_progress', 'resolved', 'closed'],
  triage_status: ['all', 'pending', 'processing', 'completed', 'failed'],
  priority: ['all', 'low', 'normal', 'high', 'urgent'],
  trigger_reason: ['all', 'human_requested', 'insufficient_evidence'],
}
const filterLabels = {
  status: 'Escalation status',
  triage_status: 'Triage status',
  priority: 'Priority',
  trigger_reason: 'Trigger reason',
}
export function EscalationsPage() {
  const { selectedWorkspace } = useWorkspace()
  const [filters, setFilters] = useState<EscalationFilters>({
    status: 'all',
    triage_status: 'all',
    priority: 'all',
    trigger_reason: 'all',
  })
  const [cursors, setCursors] = useState<(Cursor | null)[]>([null])
  const cursor = cursors.at(-1) ?? null
  const load = useCallback(
    (id: string, token: string, signal: AbortSignal) =>
      adminApi.escalations(id, token, filters, cursor, signal),
    [filters, cursor],
  )
  const resource = useAdminResource(JSON.stringify({ filters, cursor }), load)
  return (
    <>
      <PageHeading
        title="Escalations"
        workspace={selectedWorkspace?.name ?? ''}
        description="Read unresolved support triage and delivery state. Classification and summaries are AI-generated, not guaranteed judgments."
      />
      <div className="mb-5 flex flex-wrap gap-4">
        {(Object.keys(filterOptions) as (keyof EscalationFilters)[]).map((name) => (
          <Filter
            key={name}
            name={filterLabels[name]}
            value={filters[name]}
            options={filterOptions[name]}
            onChange={(value) => {
              setFilters((old) => ({ ...old, [name]: value }))
              setCursors([null])
            }}
          />
        ))}
      </div>
      <ResourceState {...resource}>
        {resource.data && (
          <section className={panel}>
            {resource.data.items.length ? (
              <ul>
                {resource.data.items.map((item) => (
                  <li key={item.id} className="border-b border-white/10 pb-4 last:border-0">
                    <ul>
                      <EscalationRow item={item} />
                    </ul>
                    {item.summary && (
                      <p className="mb-3 whitespace-pre-wrap break-words text-sm text-slate-400">
                        AI triage summary: {item.summary}
                      </p>
                    )}
                    <p className="text-xs text-slate-500">
                      Attempts: {item.triage_attempts} · Triaged:{' '}
                      {item.triaged_at ? new Date(item.triaged_at).toLocaleString() : '—'}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      Notification:{' '}
                      {item.notification_status ? (
                        <Badge value={item.notification_status} />
                      ) : (
                        'No notification record'
                      )}
                      {item.last_error_code && <span>Safe error: {item.last_error_code}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">No escalations match these filters.</p>
            )}
          </section>
        )}
      </ResourceState>
      <Pagination
        page={cursors.length - 1}
        hasNext={!!resource.data?.next_cursor}
        loading={resource.loading}
        previous={() => setCursors((values) => values.slice(0, -1))}
        next={() => {
          const nextCursor = resource.data?.next_cursor
          if (nextCursor) setCursors((values) => [...values, nextCursor])
        }}
      />
    </>
  )
}
