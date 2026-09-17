import { useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi } from './adminApi'
import { Badge, PageHeading, ResourceState } from './components'
import { label, panel, textLink, timestamp } from './format'
import { useAdminResource } from './useAdminResource'
import { EscalationControls } from './LifecycleControls'

export function EscalationDetailPage() {
  const { escalationId = '' } = useParams()
  const { selectedWorkspace } = useWorkspace()
  const load = useCallback(
    (id: string, token: string, signal: AbortSignal) =>
      adminApi.escalation(id, token, escalationId, signal),
    [escalationId],
  )
  const resource = useAdminResource(`escalation:${escalationId}`, load)
  const data = resource.data
  const escalation = data?.escalation
  const notification = data?.notification
  return (
    <>
      <Link className={textLink} to="/app/escalations">
        ← Escalations
      </Link>
      <div className="mt-5">
        <PageHeading
          title="Escalation detail"
          workspace={selectedWorkspace?.name ?? ''}
          description="Manage support work state independently of conversation resolution. Classification, agent audits, and notification delivery remain view-only."
        />
      </div>
      <ResourceState {...resource}>
        {data && escalation && (
          <>
            <section className={panel}>
              <div className="flex flex-wrap gap-2">
                <Badge value={escalation.status} />
                <Badge value={escalation.triage_status} />
                <Badge value={escalation.priority} />
              </div>
              <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
                {[
                  ['Trigger reason', label(escalation.trigger_reason)],
                  [
                    'Category',
                    escalation.category ? label(escalation.category) : 'Awaiting classification',
                  ],
                  ['Triage attempts', escalation.triage_attempts],
                  ['Created', timestamp(escalation.created_at)],
                  ['Updated', timestamp(escalation.updated_at)],
                  ['Triaged', timestamp(escalation.triaged_at)],
                ].map(([name, value]) => (
                  <div key={name}>
                    <dt className="text-xs text-slate-500">{name}</dt>
                    <dd className="mt-1 capitalize text-slate-200">{value}</dd>
                  </div>
                ))}
              </dl>
              {escalation.last_error_code && (
                <p className="mt-4 text-xs text-amber-200">
                  Safe error: {escalation.last_error_code}
                </p>
              )}
              <h2 className="mt-6 font-semibold">AI triage summary</h2>
              <p className="mt-1 text-xs text-slate-500">
                Generated from the conversation for support triage; classification may be imperfect.
              </p>
              <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-300">
                {escalation.summary ?? 'No AI summary yet.'}
              </p>
              <Link
                className={`${textLink} mt-5 inline-block text-sm`}
                to={`/app/conversations/${escalation.conversation_id}`}
              >
                View conversation
              </Link>
              <EscalationControls key={escalation.id} data={data} replace={resource.replace} refresh={resource.retry} />
            </section>
            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <section className={panel}>
                <h2 className="text-lg font-semibold">Agent audit</h2>
                <p className="mt-2 text-xs text-slate-500">
                  Newest attempt first. Up to 50 attempts; no prompts or hidden reasoning.
                </p>
                {data.audit_runs.length ? (
                  <ol className="mt-4 space-y-5">
                    {data.audit_runs.map((run) => (
                      <li className="border-t border-white/10 pt-4" key={run.attempt_number}>
                        <div className="flex items-center justify-between gap-2">
                          <h3 className="text-sm font-semibold">Attempt {run.attempt_number}</h3>
                          <Badge value={run.status} />
                        </div>
                        <p className="mt-3 break-words text-xs leading-6 text-slate-400">
                          {run.provider && `${run.provider} / ${run.model}`}
                          <br />
                          {run.tool_name && `Allowed tool: ${run.tool_name}`}
                          <br />
                          Started: {timestamp(run.started_at)}
                          <br />
                          Completed: {timestamp(run.completed_at)}
                        </p>
                        {run.safe_error_code && (
                          <p className="mt-2 text-xs text-amber-200">
                            Safe error: {run.safe_error_code}
                          </p>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No triage attempts yet.</p>
                )}
              </section>
              <section className={panel}>
                <h2 className="text-lg font-semibold">Notification delivery</h2>
                {notification ? (
                  <>
                    <div className="mt-4">
                      <Badge value={notification.status} />
                    </div>
                    <p className="mt-4 text-sm text-slate-300">
                      {notification.status === 'sent'
                        ? 'Notification sent.'
                        : notification.status === 'sending'
                          ? 'Delivery is in progress.'
                          : notification.status === 'failed'
                            ? 'Delivery failed or requires review.'
                            : 'Pending delivery. This does not confirm that notifications are configured.'}
                    </p>
                    <dl className="mt-4 space-y-3 text-xs text-slate-400">
                      <div>
                        <dt>Attempts</dt>
                        <dd>{notification.attempts}</dd>
                      </div>
                      <div>
                        <dt>Provider</dt>
                        <dd>{notification.provider ?? '—'}</dd>
                      </div>
                      <div>
                        <dt>Sent</dt>
                        <dd>{timestamp(notification.sent_at)}</dd>
                      </div>
                      <div>
                        <dt>Created</dt>
                        <dd>{timestamp(notification.created_at)}</dd>
                      </div>
                      <div>
                        <dt>Updated</dt>
                        <dd>{timestamp(notification.updated_at)}</dd>
                      </div>
                    </dl>
                    {notification.last_error_code && (
                      <p className="mt-4 break-words text-xs text-amber-200">
                        Safe error: {notification.last_error_code}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No notification record yet.</p>
                )}
              </section>
            </div>
          </>
        )}
      </ResourceState>
    </>
  )
}
