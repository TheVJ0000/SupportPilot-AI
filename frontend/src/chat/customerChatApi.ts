import { apiBaseUrl } from '../api/health'

export const CUSTOMER_SESSION_HEADER = 'X-SupportPilot-Session'
export const CUSTOMER_MESSAGE_LIMIT = 2_000

export type AnswerStatus = 'answered' | 'insufficient_evidence'
export type ConversationStatus = 'open' | 'human_requested' | 'closed'
export type FeedbackRating = 'positive' | 'negative'

export type CitationLocator =
  | { kind: 'faq' }
  | { kind: 'pdf'; page_start: number; page_end: number }
  | { kind: 'docx'; block_start: number; block_end: number }
  | { kind: 'text' | 'markdown'; line_start: number; line_end: number }

export interface CustomerCitation {
  source_id: string
  source_title: string
  source_type: 'file' | 'faq'
  chunk_index: number
  locator: CitationLocator
}

export interface CustomerMessage {
  id: string
  role: 'customer' | 'assistant'
  content: string
  answer_status?: AnswerStatus
  created_at: string
  citations: CustomerCitation[]
  feedback?: FeedbackRating | null
}

export interface CustomerConversation {
  conversation_id: string
  status: ConversationStatus
  human_requested_at?: string | null
  messages: CustomerMessage[]
}

export interface CreatedCustomerSession {
  conversation_id: string
  session_token: string
  workspace_name: string
  expires_at: string
}

export interface CustomerTurnResult {
  conversation_id: string
  turn_id: string
  message_id: string
  client_message_id: string
  status: AnswerStatus
  answer: string
  citations: CustomerCitation[]
  is_replay: boolean
}

export interface CustomerFeedbackResult {
  message_id: string
  rating: FeedbackRating
}

export interface CustomerHumanRequestResult {
  conversation_id: string
  status: 'human_requested'
  human_requested_at: string
}

export class CustomerChatApiError extends Error {
  constructor(public readonly kind: 'invalid-session' | 'unavailable') {
    super(kind)
    this.name = 'CustomerChatApiError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  )
}

function isPositiveRange(start: unknown, end: unknown): start is number {
  return (
    typeof start === 'number' &&
    Number.isInteger(start) &&
    start >= 1 &&
    typeof end === 'number' &&
    Number.isInteger(end) &&
    end >= start
  )
}

function isLocator(value: unknown): value is CitationLocator {
  if (!isRecord(value) || typeof value.kind !== 'string') return false
  if (value.kind === 'faq') return Object.keys(value).length === 1
  if (value.kind === 'pdf') return isPositiveRange(value.page_start, value.page_end)
  if (value.kind === 'docx') return isPositiveRange(value.block_start, value.block_end)
  if (value.kind === 'text' || value.kind === 'markdown') {
    return isPositiveRange(value.line_start, value.line_end)
  }
  return false
}

function isCitation(value: unknown): value is CustomerCitation {
  return (
    isRecord(value) &&
    isUuid(value.source_id) &&
    typeof value.source_title === 'string' &&
    value.source_title.length >= 1 &&
    (value.source_type === 'file' || value.source_type === 'faq') &&
    typeof value.chunk_index === 'number' &&
    Number.isInteger(value.chunk_index) &&
    value.chunk_index >= 0 &&
    isLocator(value.locator)
  )
}

function isMessage(value: unknown): value is CustomerMessage {
  if (
    !isRecord(value) ||
    !isUuid(value.id) ||
    (value.role !== 'customer' && value.role !== 'assistant') ||
    typeof value.content !== 'string' ||
    typeof value.created_at !== 'string' ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isCitation)
  ) {
    return false
  }
  const validFeedback =
    value.feedback === undefined ||
    value.feedback === null ||
    value.feedback === 'positive' ||
    value.feedback === 'negative'
  if (value.role === 'customer') {
    return (
      value.answer_status === undefined &&
      (value.feedback === undefined || value.feedback === null)
    )
  }
  return (
    validFeedback &&
    (value.answer_status === 'answered' || value.answer_status === 'insufficient_evidence')
  )
}

function parseCreatedSession(value: unknown): CreatedCustomerSession {
  if (
    !isRecord(value) ||
    !isUuid(value.conversation_id) ||
    typeof value.session_token !== 'string' ||
    !/^[A-Za-z0-9_-]{43,128}$/.test(value.session_token) ||
    typeof value.workspace_name !== 'string' ||
    value.workspace_name.length < 1 ||
    typeof value.expires_at !== 'string' ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    Date.parse(value.expires_at) <= Date.now()
  ) {
    throw new CustomerChatApiError('unavailable')
  }
  return value as unknown as CreatedCustomerSession
}

function parseConversation(value: unknown): CustomerConversation {
  if (
    !isRecord(value) ||
    !isUuid(value.conversation_id) ||
    !['open', 'human_requested', 'closed'].includes(String(value.status)) ||
    !(
      value.human_requested_at === undefined ||
      value.human_requested_at === null ||
      (typeof value.human_requested_at === 'string' &&
        Number.isFinite(Date.parse(value.human_requested_at)))
    ) ||
    (value.status === 'open' &&
      value.human_requested_at !== undefined &&
      value.human_requested_at !== null) ||
    (value.status === 'human_requested' && typeof value.human_requested_at !== 'string') ||
    !Array.isArray(value.messages) ||
    !value.messages.every(isMessage)
  ) {
    throw new CustomerChatApiError('unavailable')
  }
  return value as unknown as CustomerConversation
}

function parseTurn(value: unknown): CustomerTurnResult {
  if (
    !isRecord(value) ||
    !isUuid(value.conversation_id) ||
    !isUuid(value.turn_id) ||
    !isUuid(value.message_id) ||
    !isUuid(value.client_message_id) ||
    (value.status !== 'answered' && value.status !== 'insufficient_evidence') ||
    typeof value.answer !== 'string' ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isCitation) ||
    typeof value.is_replay !== 'boolean'
  ) {
    throw new CustomerChatApiError('unavailable')
  }
  return value as unknown as CustomerTurnResult
}

function parseFeedback(value: unknown): CustomerFeedbackResult {
  if (
    !isRecord(value) ||
    !isUuid(value.message_id) ||
    (value.rating !== 'positive' && value.rating !== 'negative')
  ) {
    throw new CustomerChatApiError('unavailable')
  }
  return value as unknown as CustomerFeedbackResult
}

function parseHumanRequest(value: unknown): CustomerHumanRequestResult {
  if (
    !isRecord(value) ||
    !isUuid(value.conversation_id) ||
    value.status !== 'human_requested' ||
    typeof value.human_requested_at !== 'string' ||
    !Number.isFinite(Date.parse(value.human_requested_at))
  ) {
    throw new CustomerChatApiError('unavailable')
  }
  return value as unknown as CustomerHumanRequestResult
}

async function readResponse(response: Response): Promise<unknown> {
  if (response.status === 401) throw new CustomerChatApiError('invalid-session')
  if (!response.ok) throw new CustomerChatApiError('unavailable')
  try {
    return await response.json()
  } catch {
    throw new CustomerChatApiError('unavailable')
  }
}

async function safeFetch(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch {
    throw new CustomerChatApiError('unavailable')
  }
}

export async function createCustomerSession(
  publicId: string,
  signal?: AbortSignal,
): Promise<CreatedCustomerSession> {
  const response = await safeFetch(`${apiBaseUrl}/api/chat/${encodeURIComponent(publicId)}/session`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    signal,
  })
  return parseCreatedSession(await readResponse(response))
}

export async function getCustomerConversation(
  conversationId: string,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<CustomerConversation> {
  const response = await safeFetch(
    `${apiBaseUrl}/api/chat/conversations/${encodeURIComponent(conversationId)}`,
    {
      headers: {
        Accept: 'application/json',
        [CUSTOMER_SESSION_HEADER]: sessionToken,
      },
      signal,
    },
  )
  return parseConversation(await readResponse(response))
}

export async function submitCustomerTurn(
  conversationId: string,
  sessionToken: string,
  clientMessageId: string,
  message: string,
): Promise<CustomerTurnResult> {
  const response = await safeFetch(
    `${apiBaseUrl}/api/chat/conversations/${encodeURIComponent(conversationId)}/turns`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        [CUSTOMER_SESSION_HEADER]: sessionToken,
      },
      body: JSON.stringify({ client_message_id: clientMessageId, message }),
    },
  )
  return parseTurn(await readResponse(response))
}

export async function setCustomerMessageFeedback(
  conversationId: string,
  sessionToken: string,
  messageId: string,
  rating: FeedbackRating,
): Promise<CustomerFeedbackResult> {
  const response = await safeFetch(
    `${apiBaseUrl}/api/chat/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/feedback`,
    {
      method: 'PUT',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        [CUSTOMER_SESSION_HEADER]: sessionToken,
      },
      body: JSON.stringify({ rating }),
    },
  )
  return parseFeedback(await readResponse(response))
}

export async function requestCustomerHumanSupport(
  conversationId: string,
  sessionToken: string,
): Promise<CustomerHumanRequestResult> {
  const response = await safeFetch(
    `${apiBaseUrl}/api/chat/conversations/${encodeURIComponent(conversationId)}/human-request`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        [CUSTOMER_SESSION_HEADER]: sessionToken,
      },
    },
  )
  return parseHumanRequest(await readResponse(response))
}
