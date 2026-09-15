import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  CUSTOMER_SESSION_HEADER,
  CustomerChatApiError,
  createCustomerSession,
  getCustomerConversation,
  requestCustomerHumanSupport,
  setCustomerMessageFeedback,
  submitCustomerTurn,
} from './customerChatApi'

const CONVERSATION_ID = '40000000-0000-4000-8000-000000000001'
const CLIENT_MESSAGE_ID = '50000000-0000-4000-8000-000000000001'
const TURN_ID = '60000000-0000-4000-8000-000000000001'
const MESSAGE_ID = '90000000-0000-4000-8000-000000000001'
const PUBLIC_ID = '10000000-0000-4000-8000-000000000001'
const SESSION_TOKEN = 'A'.repeat(43)

function response(json: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => json } as Response
}

describe('customer chat API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('creates a public session without an authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        conversation_id: CONVERSATION_ID,
        session_token: SESSION_TOKEN,
        workspace_name: 'Example Help',
        expires_at: '2099-09-22T00:00:00Z',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await createCustomerSession(PUBLIC_ID)

    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/chat/${PUBLIC_ID}/session`,
      expect.objectContaining({ method: 'POST', headers: { Accept: 'application/json' } }),
    )
    expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty('Authorization')
  })

  it('uses only the dedicated session header for history and turns', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          conversation_id: CONVERSATION_ID,
          status: 'open',
          human_requested_at: null,
          messages: [],
        }),
      )
      .mockResolvedValueOnce(
        response({
          conversation_id: CONVERSATION_ID,
          turn_id: TURN_ID,
          message_id: MESSAGE_ID,
          client_message_id: CLIENT_MESSAGE_ID,
          status: 'insufficient_evidence',
          answer: 'Not enough verified information.',
          citations: [],
          is_replay: false,
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await getCustomerConversation(CONVERSATION_ID, SESSION_TOKEN)
    await submitCustomerTurn(CONVERSATION_ID, SESSION_TOKEN, CLIENT_MESSAGE_ID, 'Question?')

    for (const call of fetchMock.mock.calls) {
      expect(call[1].headers[CUSTOMER_SESSION_HEADER]).toBe(SESSION_TOKEN)
      expect(call[1].headers).not.toHaveProperty('Authorization')
    }
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      client_message_id: CLIENT_MESSAGE_ID,
      message: 'Question?',
    })
  })

  it('uses the session header for feedback and human requests', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ message_id: MESSAGE_ID, rating: 'positive' }))
      .mockResolvedValueOnce(
        response({
          conversation_id: CONVERSATION_ID,
          status: 'human_requested',
          human_requested_at: '2026-09-15T12:05:00Z',
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await setCustomerMessageFeedback(CONVERSATION_ID, SESSION_TOKEN, MESSAGE_ID, 'positive')
    await requestCustomerHumanSupport(CONVERSATION_ID, SESSION_TOKEN)

    expect(fetchMock.mock.calls[0][0]).toContain(`/messages/${MESSAGE_ID}/feedback`)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'PUT',
      body: JSON.stringify({ rating: 'positive' }),
    })
    expect(fetchMock.mock.calls[1][0]).toContain('/human-request')
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
    for (const call of fetchMock.mock.calls) {
      expect(call[1].headers[CUSTOMER_SESSION_HEADER]).toBe(SESSION_TOKEN)
      expect(call[1].headers).not.toHaveProperty('Authorization')
    }
  })

  it('classifies invalid sessions and hides raw backend errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response({ detail: 'SQL provider token details' }, 401)),
    )

    await expect(getCustomerConversation(CONVERSATION_ID, SESSION_TOKEN)).rejects.toEqual(
      new CustomerChatApiError('invalid-session'),
    )
  })
})
