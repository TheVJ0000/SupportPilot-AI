import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/useAuth'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi, AdminApiError, type ConversationDetail, type EscalationDetail, type ResolutionAction, type EscalationStatus } from './adminApi'
import { button } from './format'

interface Action { label: string; confirmation?: string; run: (signal: AbortSignal) => Promise<void> }

// The caller keys this component by record, and OperationsGuard keys its entire outlet
// by tenant/role/identity. Abort plus response fencing also covers ignored cancellations.
function Controls({ actions, refresh }: { actions: Action[]; refresh: () => void }) {
  const [confirmation, setConfirmation] = useState<Action | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  async function execute(action: Action) {
    if (controller.current && !controller.current.signal.aborted) return
    const request = new AbortController()
    controller.current = request
    setPending(true)
    setError(null)
    try {
      await action.run(request.signal)
      if (!request.signal.aborted) setConfirmation(null)
    } catch (failure: unknown) {
      if (!request.signal.aborted) setError(failure instanceof AdminApiError ? failure.message : 'Support action could not be completed. Please try again.')
    } finally {
      if (!request.signal.aborted) {
        setPending(false)
        controller.current = null
      }
    }
  }
  return <section aria-label="Lifecycle actions" className="mt-5 border-t border-white/10 pt-5">
    <div className="flex flex-wrap gap-3">
      {actions.map(action => <button type="button" className={button} disabled={pending || !!confirmation} key={action.label}
        onClick={() => action.confirmation ? setConfirmation(action) : void execute(action)}>{action.label}</button>)}
    </div>
    {confirmation && <div role="dialog" aria-label={confirmation.label} className="mt-4 rounded-xl border border-amber-300/20 p-4">
      <p className="text-sm leading-6 text-slate-300">{confirmation.confirmation}</p>
      <div className="mt-4 flex gap-3">
        <button type="button" className={button} disabled={pending} onClick={() => setConfirmation(null)}>Cancel</button>
        <button type="button" className={button} disabled={pending} onClick={() => void execute(confirmation)}>Confirm {confirmation.label.toLowerCase()}</button>
      </div>
    </div>}
    {pending && <p role="status" className="mt-3 text-sm">Saving server-confirmed state…</p>}
    {error && <div className="mt-4"><p role="alert" className="text-sm text-rose-200">{error}</p><button type="button" className={`${button} mt-3`} disabled={pending} onClick={refresh}>Refresh record</button></div>}
  </section>
}

export function ConversationControls({ data, replace, refresh }: { data: ConversationDetail; replace: (value: ConversationDetail) => void; refresh: () => void }) {
  const { accessToken } = useAuth()
  const { selectedWorkspace } = useWorkspace()
  if (!accessToken || selectedWorkspace?.role === 'member' || selectedWorkspace?.id !== data.workspace_id) return null
  const record = data.conversation
  const run = (action: ResolutionAction) => async (signal: AbortSignal) => {
    const result = await adminApi.setConversationResolution(data.workspace_id, accessToken, record.id, {
      expected_status: record.status, expected_resolution_outcome: record.resolution_outcome, action,
    }, signal)
    if (!signal.aborted) replace(result)
  }
  const actions: Action[] = record.status === 'closed' ? [{
    label: 'Reopen conversation',
    confirmation: record.human_requested_at
      ? 'This conversation previously requested human support. Reopening it will return it to human-requested state and AI replies will remain paused.'
      : 'Reopen this conversation? Normal customer AI replies will be available again.',
    run: run('reopen'),
  }] : [
    { label: 'Resolve conversation', confirmation: 'Resolve this conversation? This will close the conversation and record it as resolved by an explicit admin decision, not proof of AI resolution.', run: run('resolve') },
    { label: 'Close unresolved', confirmation: 'Close without resolution? This will close the customer conversation without recording a successful resolution.', run: run('close_unresolved') },
  ]
  return <Controls actions={actions} refresh={refresh} />
}

export function EscalationControls({ data, replace, refresh }: { data: EscalationDetail; replace: (value: EscalationDetail) => void; refresh: () => void }) {
  const { accessToken } = useAuth()
  const { selectedWorkspace } = useWorkspace()
  if (!accessToken || selectedWorkspace?.role === 'member' || selectedWorkspace?.id !== data.workspace_id) return null
  const record = data.escalation
  const options: [string, EscalationStatus][] = record.status === 'open'
    ? [['Start work', 'in_progress'], ['Resolve', 'resolved'], ['Close', 'closed']]
    : record.status === 'in_progress' ? [['Return to queue', 'open'], ['Resolve', 'resolved'], ['Close', 'closed']]
    : record.status === 'resolved' ? [['Reopen', 'open'], ['Close', 'closed']] : [['Reopen', 'open']]
  const actions = options.map(([label, status]): Action => ({ label,
    confirmation: status === 'resolved' || status === 'closed'
      ? `${label} this escalation? This changes only its support work state, not the associated conversation or its resolution outcome.` : undefined,
    run: async signal => {
      const result = await adminApi.setEscalationStatus(data.workspace_id, accessToken, record.id, { expected_status: record.status, status }, signal)
      if (!signal.aborted) replace(result)
    },
  }))
  return <Controls actions={actions} refresh={refresh} />
}
