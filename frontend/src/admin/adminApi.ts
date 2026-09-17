import { apiBaseUrl } from '../api/health'
import type { CitationLocator } from '../chat/customerChatApi'

export type ConversationStatus = 'open' | 'human_requested' | 'closed'
export type ResolutionOutcome = 'unresolved' | 'resolved' | 'closed_unresolved'
export type ResolutionAction = 'resolve' | 'close_unresolved' | 'reopen'
export type EscalationStatus = 'open' | 'in_progress' | 'resolved' | 'closed'
export type TriageStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type Priority = 'low' | 'normal' | 'high' | 'urgent'
export type NotificationStatus = 'pending' | 'sending' | 'sent' | 'failed'
export type TriggerReason = 'human_requested' | 'insufficient_evidence'
export interface ConversationItem {
  id: string
  status: ConversationStatus
  resolution_outcome: ResolutionOutcome
  created_at: string
  updated_at: string
  last_message_at: string | null
  message_count: number
  assistant_message_count: number
  feedback_positive_count: number
  feedback_negative_count: number
  has_escalation: boolean
  escalation_priority: Priority | null
}
export interface EscalationOverview {
  id: string
  conversation_id: string
  trigger_reason: TriggerReason
  status: EscalationStatus
  triage_status: TriageStatus
  category: string | null
  priority: Priority | null
  created_at: string
  triaged_at: string | null
}
export interface EscalationItem extends EscalationOverview {
  summary: string | null
  triage_attempts: number
  updated_at: string
  last_error_code: string | null
  notification_status: NotificationStatus | null
}
export interface Metrics {
  total_conversations: number
  resolved_conversations: number
  closed_unresolved_conversations: number
  ai_answered_conversations: number
  insufficient_evidence_conversations: number
  escalated_conversations: number
  human_requested_conversations: number
  positive_feedback_count: number
  negative_feedback_count: number
  open_escalations: number
  high_priority_escalations: number
  urgent_escalations: number
  knowledge_ready: number
  knowledge_processing: number
  knowledge_failed: number
}
export interface Dashboard {
  workspace_id: string
  metrics: Metrics
  recent_conversations: ConversationItem[]
  recent_escalations: EscalationOverview[]
}
export interface Cursor {
  time: string | null
  id: string
}
export interface Page<T> {
  workspace_id: string
  items: T[]
  next_cursor: Cursor | null
}
export interface Citation {
  source_id: string
  source_title: string
  source_type: 'file' | 'faq'
  chunk_index: number
  locator: CitationLocator
}
export interface Message {
  id: string
  role: 'customer' | 'assistant'
  content: string
  answer_status: 'answered' | 'insufficient_evidence' | null
  created_at: string
  feedback: 'positive' | 'negative' | null
  citations: Citation[]
}
export interface ConversationDetail {
  workspace_id: string
  conversation: Pick<
    ConversationItem,
    'id' | 'status' | 'resolution_outcome' | 'created_at' | 'updated_at' | 'last_message_at'
  > & { human_requested_at: string | null; resolved_at: string | null; closed_at: string | null }
  messages: Message[]
  escalation: EscalationItem | null
}
export interface AuditRun {
  attempt_number: number
  status: 'processing' | 'completed' | 'failed'
  provider: string | null
  model: string | null
  tool_name: 'create_escalation' | null
  safe_error_code: string | null
  started_at: string
  completed_at: string | null
}
export interface Notification {
  status: NotificationStatus
  attempts: number
  provider: string | null
  last_error_code: string | null
  sent_at: string | null
  created_at: string
  updated_at: string
}
export interface EscalationDetail {
  workspace_id: string
  escalation: EscalationItem
  audit_runs: AuditRun[]
  notification: Notification | null
}
export type ConversationFilters = { status: ConversationStatus | 'all' }
export type EscalationFilters = {
  status: EscalationStatus | 'all'
  triage_status: TriageStatus | 'all'
  priority: Priority | 'all'
  trigger_reason: TriggerReason | 'all'
}

export class AdminApiError extends Error {}

async function read<T extends { workspace_id: string }>(
  workspaceId: string,
  token: string,
  path: string,
  signal: AbortSignal,
  body?: object,
): Promise<T> {
  const response = await fetch(
    `${apiBaseUrl}/api/admin/workspaces/${encodeURIComponent(workspaceId)}/${path}`,
    {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { method: 'PATCH', body: JSON.stringify(body) } : {}),
      signal,
    },
  )
  if (!response.ok) {
    const message =
      response.status === 401
        ? 'Your session has expired. Please log in again.'
        : response.status === 403
          ? 'Owner or admin access is required for this workspace.'
          : response.status === 404
            ? 'This support record was not found in this workspace.'
            : response.status === 409
              ? 'This record changed before your action was completed. Refresh and try again.'
              : 'Support operations could not be loaded. Please try again.'
    throw new AdminApiError(message)
  }
  const data = (await response.json()) as T
  if (!data || data.workspace_id !== workspaceId)
    throw new AdminApiError('Support operations returned an unexpected response.')
  return data
}

function listQuery(filters: ConversationFilters | EscalationFilters, cursor: Cursor | null) {
  const query = new URLSearchParams({ limit: '25', ...filters })
  if (cursor) {
    query.set('cursor_id', cursor.id)
    if (cursor.time !== null) query.set('cursor_time', cursor.time)
  }
  return query.toString()
}

export const adminApi = {
  setConversationResolution: async (
    id: string, token: string, recordId: string,
    request: { expected_status: ConversationStatus; expected_resolution_outcome: ResolutionOutcome; action: ResolutionAction },
    signal: AbortSignal,
  ) => {
    const data = await read<ConversationDetail>(id, token, `conversations/${encodeURIComponent(recordId)}/resolution`, signal, request)
    if (data.conversation?.id !== recordId) throw new AdminApiError('Support operations returned an unexpected response.')
    return data
  },
  setEscalationStatus: async (
    id: string, token: string, recordId: string,
    request: { expected_status: EscalationStatus; status: EscalationStatus },
    signal: AbortSignal,
  ) => {
    const data = await read<EscalationDetail>(id, token, `escalations/${encodeURIComponent(recordId)}/status`, signal, request)
    if (data.escalation?.id !== recordId) throw new AdminApiError('Support operations returned an unexpected response.')
    return data
  },
  dashboard: (id: string, token: string, signal: AbortSignal) =>
    read<Dashboard>(id, token, 'dashboard', signal),
  conversations: (
    id: string,
    token: string,
    filters: ConversationFilters,
    cursor: Cursor | null,
    signal: AbortSignal,
  ) =>
    read<Page<ConversationItem>>(id, token, `conversations?${listQuery(filters, cursor)}`, signal),
  conversation: (id: string, token: string, recordId: string, signal: AbortSignal) =>
    read<ConversationDetail>(id, token, `conversations/${encodeURIComponent(recordId)}`, signal),
  escalations: (
    id: string,
    token: string,
    filters: EscalationFilters,
    cursor: Cursor | null,
    signal: AbortSignal,
  ) => read<Page<EscalationItem>>(id, token, `escalations?${listQuery(filters, cursor)}`, signal),
  escalation: (id: string, token: string, recordId: string, signal: AbortSignal) =>
    read<EscalationDetail>(id, token, `escalations/${encodeURIComponent(recordId)}`, signal),
}
