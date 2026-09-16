import { useCallback, useState } from 'react'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi, type ConversationFilters, type Cursor } from './adminApi'
import { ConversationRow, Filter, PageHeading, Pagination, ResourceState } from './components'
import { panel } from './format'
import { useAdminResource } from './useAdminResource'

export function ConversationsPage() {
  const { selectedWorkspace } = useWorkspace()
  const [filters, setFilters] = useState<ConversationFilters>({ status: 'all' })
  const [cursors, setCursors] = useState<(Cursor | null)[]>([null])
  const cursor = cursors.at(-1) ?? null
  const load = useCallback(
    (id: string, token: string, signal: AbortSignal) =>
      adminApi.conversations(id, token, filters, cursor, signal),
    [filters, cursor],
  )
  const resource = useAdminResource(JSON.stringify({ filters, cursor }), load)
  return (
    <>
      <PageHeading
        title="Conversations"
        workspace={selectedWorkspace?.name ?? ''}
        description="Inspect support history, evidence, and feedback. Newest activity first; conversations with no messages appear last."
      />
      <div className="mb-5 flex flex-wrap gap-4">
        <Filter
          name="Conversation status"
          value={filters.status}
          options={['all', 'open', 'human_requested', 'closed']}
          onChange={(value) => {
            setFilters({ status: value as ConversationFilters['status'] })
            setCursors([null])
          }}
        />
      </div>
      <ResourceState {...resource}>
        {resource.data && (
          <section className={panel}>
            {resource.data.items.length ? (
              <ul>
                {resource.data.items.map((item) => (
                  <ConversationRow key={item.id} item={item} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">No conversations match this filter.</p>
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
