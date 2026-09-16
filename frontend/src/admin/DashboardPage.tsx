import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi } from './adminApi'
import { ConversationRow, EscalationRow, PageHeading, ResourceState } from './components'
import { panel } from './format'
import { useAdminResource } from './useAdminResource'

export function DashboardPage() {
  const { selectedWorkspace } = useWorkspace()
  const resource = useAdminResource('dashboard', adminApi.dashboard)
  const data = resource.data
  const metrics = data?.metrics
  const cards = metrics
    ? ([
        ['Total conversations', metrics.total_conversations],
        ['AI answered conversations', metrics.ai_answered_conversations],
        ['Insufficient evidence', metrics.insufficient_evidence_conversations],
        ['Escalated conversations', metrics.escalated_conversations],
        ['Human requested', metrics.human_requested_conversations],
        ['Helpful feedback', metrics.positive_feedback_count],
        ['Not helpful feedback', metrics.negative_feedback_count],
        ['Open escalations', metrics.open_escalations],
        ['High-priority escalations', metrics.high_priority_escalations],
        ['Urgent escalations', metrics.urgent_escalations],
        ['Knowledge ready', metrics.knowledge_ready],
        ['Knowledge processing', metrics.knowledge_processing],
        ['Knowledge failed', metrics.knowledge_failed],
      ] as const)
    : []
  const coverage =
    metrics && metrics.total_conversations > 0
      ? Math.round((metrics.ai_answered_conversations / metrics.total_conversations) * 100)
      : 0
  return (
    <>
      <PageHeading
        title="Dashboard"
        workspace={selectedWorkspace?.name ?? ''}
        description="A clear view of support activity, evidence coverage, escalations, and knowledge readiness."
      />
      <ResourceState {...resource}>
        {data && (
          <>
            <section
              aria-label="Support metrics"
              className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
            >
              {cards.map(([name, count]) => (
                <article className={panel} key={name}>
                  <h2 className="text-xs font-medium text-slate-400">{name}</h2>
                  <p className="mt-3 text-3xl font-semibold tabular-nums">{count}</p>
                </article>
              ))}
              <article className={`${panel} border-cyan-300/20`}>
                <h2 className="text-xs text-cyan-200">AI answer coverage</h2>
                <p className="mt-3 text-3xl font-semibold">{coverage}%</p>
                <p className="mt-3 text-xs leading-5 text-slate-400">
                  Conversations with an evidence-backed AI answer, not a measure of resolution.
                </p>
              </article>
            </section>
            <p className="mt-4 text-xs leading-5 text-slate-500">
              Counts describe current workspace records. Open escalations excludes in-progress
              records. Priority counts include only completed triage. Knowledge counts use each
              source’s current state.
            </p>
            <div className="mt-7 grid gap-5 lg:grid-cols-2">
              <section className={panel}>
                <h2 className="text-lg font-semibold">Recent conversations</h2>
                {data.recent_conversations.length ? (
                  <ul>
                    {data.recent_conversations.map((item) => (
                      <ConversationRow item={item} key={item.id} />
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No conversations yet.</p>
                )}
              </section>
              <section className={panel}>
                <h2 className="text-lg font-semibold">Recent escalations</h2>
                {data.recent_escalations.length ? (
                  <ul>
                    {data.recent_escalations.map((item) => (
                      <EscalationRow item={item} key={item.id} />
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No escalations yet.</p>
                )}
              </section>
            </div>
          </>
        )}
      </ResourceState>
    </>
  )
}
