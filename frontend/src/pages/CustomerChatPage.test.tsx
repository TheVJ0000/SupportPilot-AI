import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CustomerChatApiError, type CustomerConversation } from '../chat/customerChatApi'
import { CustomerChatPage } from './CustomerChatPage'

const mocks = vi.hoisted(() => ({
  createCustomerSession: vi.fn(),
  getCustomerConversation: vi.fn(),
  submitCustomerTurn: vi.fn(),
}))

vi.mock('../chat/customerChatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../chat/customerChatApi')>()
  return {
    ...actual,
    createCustomerSession: mocks.createCustomerSession,
    getCustomerConversation: mocks.getCustomerConversation,
    submitCustomerTurn: mocks.submitCustomerTurn,
  }
})

const PUBLIC_ID = '10000000-0000-4000-8000-000000000001'
const CONVERSATION_ID = '40000000-0000-4000-8000-000000000001'
const NEW_CONVERSATION_ID = '40000000-0000-4000-8000-000000000002'
const CLIENT_MESSAGE_ID = '50000000-0000-4000-8000-000000000001'
const TURN_ID = '60000000-0000-4000-8000-000000000001'
const SESSION_TOKEN = 'A'.repeat(43)
const NEW_SESSION_TOKEN = 'B'.repeat(43)
const STORAGE_KEY = `supportpilot:chat-session:${PUBLIC_ID}`

function createdSession(conversationId = CONVERSATION_ID, token = SESSION_TOKEN) {
  return {
    conversation_id: conversationId,
    session_token: token,
    workspace_name: 'Example Help',
    expires_at: '2099-09-22T00:00:00Z',
  }
}

function storedSession(expiresAt = '2099-09-22T00:00:00Z') {
  return {
    publicId: PUBLIC_ID,
    conversationId: CONVERSATION_ID,
    sessionToken: SESSION_TOKEN,
    expiresAt,
    workspaceName: 'Example Help',
  }
}

function conversation(messages: CustomerConversation['messages'] = []): CustomerConversation {
  return { conversation_id: CONVERSATION_ID, status: 'open', messages }
}

function renderChat() {
  return render(
    <MemoryRouter initialEntries={[`/chat/${PUBLIC_ID}`]}>
      <Routes>
        <Route path="/chat/:publicId" element={<CustomerChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('hosted customer chat page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mocks.createCustomerSession.mockResolvedValue(createdSession())
    mocks.getCustomerConversation.mockResolvedValue(conversation())
    mocks.submitCustomerTurn.mockResolvedValue({
      conversation_id: CONVERSATION_ID,
      turn_id: TURN_ID,
      client_message_id: CLIENT_MESSAGE_ID,
      status: 'answered',
      answer: 'Use the account reset link.',
      citations: [],
      is_replay: false,
    })
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(CLIENT_MESSAGE_ID)
  })

  it('creates and stores the minimum session state when none exists', async () => {
    renderChat()

    expect(await screen.findByRole('heading', { name: 'Example Help' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /how can we help/i })).toBeInTheDocument()
    expect(mocks.createCustomerSession).toHaveBeenCalledWith(PUBLIC_ID, expect.any(AbortSignal))
    expect(mocks.getCustomerConversation).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual(storedSession())
  })

  it('restores a valid stored session and server message history', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(
      conversation([
        {
          id: '90000000-0000-4000-8000-000000000001',
          role: 'customer',
          content: 'Where is my receipt?',
          created_at: '2026-09-15T12:00:00Z',
          citations: [],
        },
        {
          id: '90000000-0000-4000-8000-000000000002',
          role: 'assistant',
          content: 'Receipts are in Billing.',
          answer_status: 'answered',
          created_at: '2026-09-15T12:00:01Z',
          citations: [],
        },
      ]),
    )

    renderChat()

    expect(await screen.findByText('Where is my receipt?')).toBeInTheDocument()
    expect(screen.getByText('Receipts are in Billing.')).toBeInTheDocument()
    expect(mocks.getCustomerConversation).toHaveBeenCalledWith(
      CONVERSATION_ID,
      SESSION_TOKEN,
      expect.any(AbortSignal),
    )
    expect(mocks.createCustomerSession).not.toHaveBeenCalled()
  })

  it('replaces an expired stored session without requesting its history', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession('2020-01-01T00:00:00Z')))
    renderChat()

    expect(await screen.findByRole('heading', { name: 'Example Help' })).toBeInTheDocument()
    expect(mocks.getCustomerConversation).not.toHaveBeenCalled()
    expect(mocks.createCustomerSession).toHaveBeenCalledOnce()
  })

  it('recreates once after a 401 while restoring a conversation', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockRejectedValue(new CustomerChatApiError('invalid-session'))
    mocks.createCustomerSession.mockResolvedValue(
      createdSession(NEW_CONVERSATION_ID, NEW_SESSION_TOKEN),
    )

    renderChat()

    expect(await screen.findByRole('heading', { name: 'Example Help' })).toBeInTheDocument()
    expect(mocks.getCustomerConversation).toHaveBeenCalledOnce()
    expect(mocks.createCustomerSession).toHaveBeenCalledOnce()
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toMatchObject({
      conversationId: NEW_CONVERSATION_ID,
      sessionToken: NEW_SESSION_TOKEN,
    })
  })

  it('prevents blank and duplicate sends and uses one browser UUID', async () => {
    let resolveTurn!: (value: unknown) => void
    mocks.submitCustomerTurn.mockReturnValue(
      new Promise((resolve) => {
        resolveTurn = resolve
      }),
    )
    const user = userEvent.setup()
    renderChat()
    const composer = await screen.findByLabelText('Message')

    await user.type(composer, '   ')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(mocks.submitCustomerTurn).not.toHaveBeenCalled()

    await user.clear(composer)
    await user.type(composer, 'How do I reset my password?')
    await user.keyboard('{Enter}{Enter}')

    expect(mocks.submitCustomerTurn).toHaveBeenCalledOnce()
    expect(mocks.submitCustomerTurn).toHaveBeenCalledWith(
      CONVERSATION_ID,
      SESSION_TOKEN,
      CLIENT_MESSAGE_ID,
      'How do I reset my password?',
    )
    expect(crypto.randomUUID).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()

    await act(async () => {
      resolveTurn({
        conversation_id: CONVERSATION_ID,
        turn_id: TURN_ID,
        client_message_id: CLIENT_MESSAGE_ID,
        status: 'answered',
        answer: 'Use the account reset link.',
        citations: [],
        is_replay: false,
      })
    })
    expect(await screen.findByText('Use the account reset link.')).toBeInTheDocument()
  })

  it('enforces the 2,000-character composer limit', async () => {
    renderChat()
    const composer = await screen.findByLabelText('Message')
    expect(composer).toHaveAttribute('maxlength', '2000')

    fireEvent.change(composer, { target: { value: 'x'.repeat(2_000) } })
    expect(screen.getByText('2,000 / 2,000')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
  })

  it('renders insufficient-evidence answers as normal assistant messages', async () => {
    mocks.submitCustomerTurn.mockResolvedValue({
      conversation_id: CONVERSATION_ID,
      turn_id: TURN_ID,
      client_message_id: CLIENT_MESSAGE_ID,
      status: 'insufficient_evidence',
      answer: 'I do not have enough verified information to answer that.',
      citations: [],
      is_replay: false,
    })
    const user = userEvent.setup()
    renderChat()

    await user.type(await screen.findByLabelText('Message'), 'Unknown question')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(
      await screen.findByText('I do not have enough verified information to answer that.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('formats PDF, DOCX, text, Markdown, and FAQ citation locations', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(
      conversation([
        {
          id: '90000000-0000-4000-8000-000000000003',
          role: 'assistant',
          content: 'Grounded answer.',
          answer_status: 'answered',
          created_at: '2026-09-15T12:00:00Z',
          citations: [
            { source_id: '70000000-0000-4000-8000-000000000001', source_title: 'PDF Policy', source_type: 'file', chunk_index: 0, locator: { kind: 'pdf', page_start: 3, page_end: 3 } },
            { source_id: '70000000-0000-4000-8000-000000000002', source_title: 'DOCX Guide', source_type: 'file', chunk_index: 1, locator: { kind: 'docx', block_start: 4, block_end: 7 } },
            { source_id: '70000000-0000-4000-8000-000000000003', source_title: 'Text Help', source_type: 'file', chunk_index: 2, locator: { kind: 'text', line_start: 12, line_end: 20 } },
            { source_id: '70000000-0000-4000-8000-000000000004', source_title: 'Markdown Help', source_type: 'file', chunk_index: 3, locator: { kind: 'markdown', line_start: 8, line_end: 8 } },
            { source_id: '70000000-0000-4000-8000-000000000005', source_title: 'Account Help', source_type: 'faq', chunk_index: 4, locator: { kind: 'faq' } },
          ],
        },
      ]),
    )

    renderChat()

    expect(await screen.findByText(/PDF Policy.*page 3/)).toBeInTheDocument()
    expect(screen.getByText(/DOCX Guide.*blocks 4–7/)).toBeInTheDocument()
    expect(screen.getByText(/Text Help.*lines 12–20/)).toBeInTheDocument()
    expect(screen.getByText(/Markdown Help.*line 8/)).toBeInTheDocument()
    expect(screen.getByText(/Account Help.*FAQ/)).toBeInTheDocument()
  })

  it('offers a safe Retry that reuses the original client message ID', async () => {
    mocks.submitCustomerTurn
      .mockRejectedValueOnce(new Error('raw backend SQL and Gemini details'))
      .mockResolvedValueOnce({
        conversation_id: CONVERSATION_ID,
        turn_id: TURN_ID,
        client_message_id: CLIENT_MESSAGE_ID,
        status: 'answered',
        answer: 'Recovered persisted answer.',
        citations: [],
        is_replay: true,
      })
    const user = userEvent.setup()
    renderChat()

    await user.type(await screen.findByLabelText('Message'), 'Can I retry this?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText(/raw backend|sql|gemini/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Recovered persisted answer.')).toBeInTheDocument()
    expect(mocks.submitCustomerTurn).toHaveBeenCalledTimes(2)
    expect(mocks.submitCustomerTurn.mock.calls[0][2]).toBe(CLIENT_MESSAGE_ID)
    expect(mocks.submitCustomerTurn.mock.calls[1][2]).toBe(CLIENT_MESSAGE_ID)
    expect(crypto.randomUUID).toHaveBeenCalledOnce()
  })

  it('recreates an invalid session once while preserving the outbound message ID', async () => {
    mocks.createCustomerSession
      .mockResolvedValueOnce(createdSession())
      .mockResolvedValueOnce(createdSession(NEW_CONVERSATION_ID, NEW_SESSION_TOKEN))
    mocks.submitCustomerTurn
      .mockRejectedValueOnce(new CustomerChatApiError('invalid-session'))
      .mockResolvedValueOnce({
        conversation_id: NEW_CONVERSATION_ID,
        turn_id: TURN_ID,
        client_message_id: CLIENT_MESSAGE_ID,
        status: 'answered',
        answer: 'Answered after a fresh session.',
        citations: [],
        is_replay: false,
      })
    const user = userEvent.setup()
    renderChat()

    await user.type(await screen.findByLabelText('Message'), 'Keep this question')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Answered after a fresh session.')).toBeInTheDocument()
    expect(mocks.createCustomerSession).toHaveBeenCalledTimes(2)
    expect(mocks.submitCustomerTurn.mock.calls[1]).toEqual([
      NEW_CONVERSATION_ID,
      NEW_SESSION_TOKEN,
      CLIENT_MESSAGE_ID,
      'Keep this question',
    ])
    expect(crypto.randomUUID).toHaveBeenCalledOnce()
  })

  it('shows a friendly unavailable state without raw errors', async () => {
    mocks.createCustomerSession.mockRejectedValue(new Error('provider stack trace'))
    renderChat()

    expect(await screen.findByText('This support assistant is currently unavailable.')).toBeInTheDocument()
    expect(screen.queryByText(/provider stack trace/i)).not.toBeInTheDocument()
  })
})
