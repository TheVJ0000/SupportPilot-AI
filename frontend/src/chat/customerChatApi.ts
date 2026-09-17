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

export interface CustomerTurnStartedEvent {
  conversation_id: string
  turn_id: string
  client_message_id: string
}

export type CustomerTurnStreamEvent =
  | { type: 'started'; data: CustomerTurnStartedEvent }
  | { type: 'delta'; data: { text: string } }
  | { type: 'complete'; data: CustomerTurnResult }
  | { type: 'error'; data: { code: 'stream_failed' | 'temporarily_unavailable'; message: string } }

export interface CustomerTurnStreamHandlers {
  onStarted: (event: CustomerTurnStartedEvent) => void
  onDelta: (text: string) => void
  onComplete: (result: CustomerTurnResult) => void
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
  constructor(public readonly kind: 'invalid-session' | 'unavailable' | 'rate-limited', public readonly retryAfterSeconds?: number) {
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

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function parseStreamFrame(frame: string): CustomerTurnStreamEvent {
  let eventName: string | null = null
  let dataText: string | null = null
  for (const line of frame.split(/\r?\n/)) {
    if (line === '') continue
    if (line.startsWith('event:')) {
      if (eventName !== null) throw new CustomerChatApiError('unavailable')
      eventName = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      if (dataText !== null) throw new CustomerChatApiError('unavailable')
      dataText = line.slice('data:'.length).trimStart()
    } else {
      throw new CustomerChatApiError('unavailable')
    }
  }
  if (eventName === null || dataText === null) {
    throw new CustomerChatApiError('unavailable')
  }
  let value: unknown
  try {
    value = JSON.parse(dataText)
  } catch {
    throw new CustomerChatApiError('unavailable')
  }
  if (!isRecord(value)) throw new CustomerChatApiError('unavailable')

  if (eventName === 'started') {
    if (
      !hasOnlyKeys(value, ['conversation_id', 'turn_id', 'client_message_id']) ||
      !isUuid(value.conversation_id) ||
      !isUuid(value.turn_id) ||
      !isUuid(value.client_message_id)
    ) {
      throw new CustomerChatApiError('unavailable')
    }
    return { type: 'started', data: value as unknown as CustomerTurnStartedEvent }
  }
  if (eventName === 'delta') {
    if (!hasOnlyKeys(value, ['text']) || typeof value.text !== 'string' || value.text.length < 1) {
      throw new CustomerChatApiError('unavailable')
    }
    return { type: 'delta', data: { text: value.text } }
  }
  if (eventName === 'complete') {
    return { type: 'complete', data: parseTurn(value) }
  }
  if (eventName === 'error') {
    if (
      !hasOnlyKeys(value, ['code', 'message']) ||
      (value.code !== 'stream_failed' && value.code !== 'temporarily_unavailable') ||
      typeof value.message !== 'string'
    ) {
      throw new CustomerChatApiError('unavailable')
    }
    return { type: 'error', data: { code: value.code, message: value.message } }
  }
  throw new CustomerChatApiError('unavailable')
}

function takeCompleteFrames(buffer: string): { frames: string[]; remainder: string } {
  const frames: string[] = []
  let remainder = buffer
  while (true) {
    const boundary = /\r?\n\r?\n/.exec(remainder)
    if (boundary === null || boundary.index === undefined) break
    frames.push(remainder.slice(0, boundary.index))
    remainder = remainder.slice(boundary.index + boundary[0].length)
  }
  return { frames, remainder }
}

export async function* parseCustomerTurnEventStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<CustomerTurnStreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      try {
        buffer += decoder.decode(value, { stream: true })
      } catch {
        throw new CustomerChatApiError('unavailable')
      }
      const parsed = takeCompleteFrames(buffer)
      buffer = parsed.remainder
      for (const frame of parsed.frames) {
        if (frame.length > 0) yield parseStreamFrame(frame)
      }
    }
    try {
      buffer += decoder.decode()
    } catch {
      throw new CustomerChatApiError('unavailable')
    }
    const parsed = takeCompleteFrames(buffer)
    for (const frame of parsed.frames) {
      if (frame.length > 0) yield parseStreamFrame(frame)
    }
    if (parsed.remainder.trim().length > 0) yield parseStreamFrame(parsed.remainder)
  } finally {
    reader.releaseLock()
  }
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

async function httpFailure(response: Response): Promise<CustomerChatApiError> {
  if (response.status === 401) return new CustomerChatApiError('invalid-session')
  if (response.status === 429) {
    try {
      const payload: unknown = await response.json()
      if (isRecord(payload) && isRecord(payload.error) && payload.error.code === 'rate_limited') {
        const seconds = payload.error.retry_after_seconds
        const header = response.headers?.get('Retry-After')
        const fallback = header && /^[0-9]{1,4}$/.test(header) ? Number(header) : 60
        const bounded = typeof seconds === 'number' && Number.isInteger(seconds) && seconds >= 1 && seconds <= 3600
          ? seconds : fallback >= 1 && fallback <= 3600 ? fallback : 60
        return new CustomerChatApiError('rate-limited', bounded)
      }
    } catch { /* Never use malformed or raw error text for customer messages. */ }
  }
  return new CustomerChatApiError('unavailable')
}

async function readResponse(response: Response): Promise<unknown> {
  if (response.status === 401) throw new CustomerChatApiError('invalid-session')
  if (!response.ok) throw await httpFailure(response)
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

export async function streamCustomerTurn(
  conversationId: string,
  sessionToken: string,
  clientMessageId: string,
  message: string,
  handlers: CustomerTurnStreamHandlers,
  signal?: AbortSignal,
): Promise<CustomerTurnResult> {
  const response = await safeFetch(
    `${apiBaseUrl}/api/chat/conversations/${encodeURIComponent(conversationId)}/turns/stream`,
    {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        [CUSTOMER_SESSION_HEADER]: sessionToken,
      },
      body: JSON.stringify({ client_message_id: clientMessageId, message }),
      signal,
    },
  )
  if (response.status === 401) throw new CustomerChatApiError('invalid-session')
  if (!response.ok) throw await httpFailure(response)
  if (!response.body) throw new CustomerChatApiError('unavailable')
  if (!response.headers.get('content-type')?.toLowerCase().includes('text/event-stream')) {
    throw new CustomerChatApiError('unavailable')
  }

  let state: 'initial' | 'started' | 'complete' = 'initial'
  let completed: CustomerTurnResult | null = null
  for await (const event of parseCustomerTurnEventStream(response.body)) {
    if (event.type === 'started') {
      if (state !== 'initial') throw new CustomerChatApiError('unavailable')
      state = 'started'
      handlers.onStarted(event.data)
    } else if (event.type === 'delta') {
      if (state !== 'started') throw new CustomerChatApiError('unavailable')
      handlers.onDelta(event.data.text)
    } else if (event.type === 'complete') {
      if (state === 'complete') throw new CustomerChatApiError('unavailable')
      state = 'complete'
      completed = event.data
    } else {
      throw new CustomerChatApiError('unavailable')
    }
  }
  if (state !== 'complete' || completed === null) {
    throw new CustomerChatApiError('unavailable')
  }
  handlers.onComplete(completed)
  return completed
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
