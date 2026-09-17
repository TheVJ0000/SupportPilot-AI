import { useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi } from './adminApi'
import { Badge, PageHeading, ResourceState } from './components'
import { citationLocation, panel, textLink, timestamp } from './format'
import { useAdminResource } from './useAdminResource'
import { ConversationControls } from './LifecycleControls'

export function ConversationDetailPage() {
  const { conversationId = '' } = useParams()
  const { selectedWorkspace } = useWorkspace()
  const load = useCallback(
    (id: string, token: string, signal: AbortSignal) =>
      adminApi.conversation(id, token, conversationId, signal),
    [conversationId],
  )
  const resource = useAdminResource(`conversation:${conversationId}`, load)
  const data = resource.data
  return (
    <>
      <Link className={textLink} to="/app/conversations">
        ← Conversations
      </Link>
      <div className="mt-5">
        <PageHeading
          title="Conversation detail"
          workspace={selectedWorkspace?.name ?? ''}
          description="The persisted transcript, in turn order, with customer messages before the corresponding assistant answer."
        />
      </div>
      <ResourceState {...resource}>
        {data && (
          <>
            <section className={`${panel} mb-5`}>
              <Badge value={data.conversation.status} />
              <span className="ml-2"><Badge value={data.conversation.resolution_outcome} /></span>
              <p className="mt-4 text-xs leading-6 text-slate-400">
                Created: {timestamp(data.conversation.created_at)}
                <br />
                Updated: {timestamp(data.conversation.updated_at)}
                <br />
                Last activity: {timestamp(data.conversation.last_message_at)}
                <br />
                Human requested: {timestamp(data.conversation.human_requested_at)}
                <br />
                Resolved: {timestamp(data.conversation.resolved_at)}
                <br />
                Closed: {timestamp(data.conversation.closed_at)}
              </p>
              <ConversationControls key={data.conversation.id} data={data} replace={resource.replace} refresh={resource.retry} />
            </section>
            <section aria-label="Conversation transcript" className="space-y-4">
              {data.messages.length ? (
                data.messages.map((message) => (
                  <article
                    className={`${panel} ${message.role === 'assistant' ? 'border-cyan-300/15' : ''}`}
                    key={message.id}
                  >
                    <header className="flex flex-wrap items-center justify-between gap-3">
                      <h2 className="font-semibold">
                        {message.role === 'customer' ? 'Customer' : 'SupportPilot AI'}
                      </h2>
                      <time className="text-xs text-slate-500" dateTime={message.created_at}>
                        {timestamp(message.created_at)}
                      </time>
                    </header>
                    {message.answer_status && (
                      <div className="mt-3">
                        <Badge value={message.answer_status} />
                      </div>
                    )}
                    <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-200">
                      {message.content}
                    </p>
                    {message.citations.length > 0 && (
                      <section className="mt-5 border-t border-white/10 pt-4">
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                          Sources
                        </h3>
                        <ul className="mt-2 space-y-2">
                          {message.citations.map((citation, index) => (
                            <li
                              className="break-words text-xs text-slate-300"
                              key={`${citation.source_id}:${index}`}
                            >
                              {citation.source_title} · {citationLocation(citation)} · Chunk{' '}
                              {citation.chunk_index + 1}
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                    {message.feedback && (
                      <p className="mt-4 text-xs text-slate-400">
                        Customer feedback:{' '}
                        {message.feedback === 'positive' ? 'Helpful' : 'Not helpful'}
                      </p>
                    )}
                  </article>
                ))
              ) : (
                <p className={panel}>No messages yet.</p>
              )}
            </section>
            {data.escalation && (
              <section className={`${panel} mt-5`}>
                <h2 className="mb-3 font-semibold">Escalation</h2>
                <div className="mb-4 flex flex-wrap gap-2">
                  <Badge value={data.escalation.status} />
                  <Badge value={data.escalation.triage_status} />
                  {data.escalation.priority && <Badge value={data.escalation.priority} />}
                </div>
                {data.escalation.summary && (
                  <p className="mb-4 whitespace-pre-wrap break-words text-sm text-slate-400">
                    AI triage summary: {data.escalation.summary}
                  </p>
                )}
                <Link className={textLink} to={`/app/escalations/${data.escalation.id}`}>
                  View escalation and audit
                </Link>
              </section>
            )}
          </>
        )}
      </ResourceState>
    </>
  )
}
