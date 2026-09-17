import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CustomerChatApiError, type CustomerConversation } from '../chat/customerChatApi'
import { AppRoutes } from '../App'

const mocks = vi.hoisted(() => ({
  createCustomerSession: vi.fn(),
  getCustomerConversation: vi.fn(),
  requestCustomerHumanSupport: vi.fn(),
  setCustomerMessageFeedback: vi.fn(),
  streamDriver: vi.fn(),
  submitCustomerTurn: vi.fn(),
}))

vi.mock('../chat/customerChatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../chat/customerChatApi')>()
  return {
    ...actual,
    createCustomerSession: mocks.createCustomerSession,
    getCustomerConversation: mocks.getCustomerConversation,
    requestCustomerHumanSupport: mocks.requestCustomerHumanSupport,
    setCustomerMessageFeedback: mocks.setCustomerMessageFeedback,
    streamCustomerTurn: async (...args: Parameters<typeof actual.streamCustomerTurn>) => {
      if (mocks.streamDriver.getMockImplementation()) {
        return mocks.streamDriver(...args)
      }
      const [conversationId, token, clientMessageId, message, handlers] = args
      const result = await mocks.submitCustomerTurn(
        conversationId,
        token,
        clientMessageId,
        message,
      )
      if (!result.is_replay) {
        handlers.onStarted({
          conversation_id: result.conversation_id,
          turn_id: result.turn_id,
          client_message_id: result.client_message_id,
        })
        if (result.answer) handlers.onDelta(result.answer)
      }
      handlers.onComplete(result)
      return result
    },
  }
})

const PUBLIC_ID = '10000000-0000-4000-8000-000000000001'
const CONVERSATION_ID = '40000000-0000-4000-8000-000000000001'
const NEW_CONVERSATION_ID = '40000000-0000-4000-8000-000000000002'
const CLIENT_MESSAGE_ID = '50000000-0000-4000-8000-000000000001'
const TURN_ID = '60000000-0000-4000-8000-000000000001'
const ASSISTANT_MESSAGE_ID = '90000000-0000-4000-8000-000000000002'
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

function conversation(
  messages: CustomerConversation['messages'] = [],
  status: CustomerConversation['status'] = 'open',
): CustomerConversation {
  return {
    conversation_id: CONVERSATION_ID,
    status,
    human_requested_at: status === 'human_requested' ? '2026-09-15T12:05:00Z' : null,
    messages,
  }
}

function renderChat(mode: 'hosted' | 'embedded' = 'hosted') {
  return render(
    <MemoryRouter initialEntries={[`/${mode === 'embedded' ? 'embed' : 'chat'}/${PUBLIC_ID}`]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

describe('hosted customer chat page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.streamDriver.mockReset()
    localStorage.clear()
    mocks.createCustomerSession.mockResolvedValue(createdSession())
    mocks.getCustomerConversation.mockResolvedValue(conversation())
    mocks.submitCustomerTurn.mockResolvedValue({
      conversation_id: CONVERSATION_ID,
      turn_id: TURN_ID,
      message_id: ASSISTANT_MESSAGE_ID,
      client_message_id: CLIENT_MESSAGE_ID,
      status: 'answered',
      answer: 'Use the account reset link.',
      citations: [],
      is_replay: false,
    })
    mocks.setCustomerMessageFeedback.mockImplementation(
      (_conversationId, _token, messageId, rating) =>
        Promise.resolve({ message_id: messageId, rating }),
    )
    mocks.requestCustomerHumanSupport.mockResolvedValue({
      conversation_id: CONVERSATION_ID,
      status: 'human_requested',
      human_requested_at: '2026-09-15T12:05:00Z',
    })
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(CLIENT_MESSAGE_ID)
  })

  it.each(['hosted','embedded'] as const)('shows safe %s session throttling without creating repeated sessions', async mode => {
    mocks.createCustomerSession.mockRejectedValue(new CustomerChatApiError('rate-limited', 30))
    renderChat(mode)
    expect(await screen.findByText('Support is receiving a lot of requests right now. Please try again shortly.')).toBeInTheDocument()
    expect(mocks.createCustomerSession).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
  it.each(['hosted','embedded'] as const)('keeps %s throttled turn and retries the same client_message_id after cooldown', async mode => {
    mocks.submitCustomerTurn.mockRejectedValueOnce(new CustomerChatApiError('rate-limited', 1))
    renderChat(mode)
    await userEvent.type(await screen.findByRole('textbox',{name:'Message'}), 'Demo throttled question')
    await userEvent.click(screen.getByRole('button',{name:'Send'}))
    expect(await screen.findByText('Too many requests. Please try again shortly.')).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Retry in 1s'})).toBeDisabled()
    expect(screen.getByText('Demo throttled question')).toBeInTheDocument()
    expect(mocks.submitCustomerTurn).toHaveBeenCalledTimes(1)
    const retry = await screen.findByRole('button',{name:'Retry'}, { timeout: 2500 })
    await userEvent.click(retry)
    expect(await screen.findByText('Use the account reset link.')).toBeInTheDocument()
    const first = mocks.submitCustomerTurn.mock.calls[0]
    expect(mocks.submitCustomerTurn.mock.calls[1]).toEqual(first)
  })
  it.each(['hosted','embedded'] as const)('shows safe %s feedback/human throttling without false success', async mode => {
    renderChat(mode)
    await userEvent.type(await screen.findByRole('textbox',{name:'Message'}), 'Demo question')
    await userEvent.click(screen.getByRole('button',{name:'Send'}))
    await screen.findByText('Use the account reset link.')
    mocks.setCustomerMessageFeedback.mockRejectedValue(new CustomerChatApiError('rate-limited', 10))
    await userEvent.click(screen.getByRole('button',{name:/mark this answer as helpful/i}))
    expect(await screen.findByText("We couldn't save that feedback yet. Please try again shortly.")).toBeInTheDocument()
    expect(mocks.setCustomerMessageFeedback).toHaveBeenCalledTimes(1)
    mocks.requestCustomerHumanSupport.mockRejectedValue(new CustomerChatApiError('rate-limited', 10))
    await userEvent.click(screen.getByRole('button',{name:'Request a human'}))
    await userEvent.click(screen.getByRole('button',{name:'Confirm'}))
    expect(await screen.findByText("We couldn't record the request yet. Please try again shortly.")).toBeInTheDocument()
    expect(screen.queryByText('AI messaging is paused for this conversation.')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox',{name:'Message'})).not.toBeDisabled()
    expect(mocks.requestCustomerHumanSupport).toHaveBeenCalledTimes(1)
  })
  it.each(['hosted','embedded'] as const)('routes %s chat through shared session initialization with the correct presentation', async mode => {
    renderChat(mode)
    expect(await screen.findByRole('heading',{name:'Example Help'})).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveAttribute('data-chat-mode',mode)
    if (mode === 'embedded') expect(screen.getByRole('main')).toHaveClass('h-dvh','overflow-hidden')
    expect(mocks.createCustomerSession).toHaveBeenCalledWith(PUBLIC_ID,expect.any(AbortSignal))
  })
  it('restores embedded history, citations and feedback and records a human request', async () => {
    localStorage.setItem(STORAGE_KEY,JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(conversation([{
      id:ASSISTANT_MESSAGE_ID,role:'assistant',content:'Embedded synthetic answer.',answer_status:'answered',created_at:'2026-09-15T12:00:00Z',feedback:null,
      citations:[{source_id:PUBLIC_ID,source_title:'Demo returns policy',source_type:'faq',chunk_index:0,locator:{kind:'faq'}}],
    }]))
    renderChat('embedded')
    expect(await screen.findByText('Embedded synthetic answer.')).toBeInTheDocument()
    expect(screen.getByText(/Demo returns policy/)).toBeInTheDocument()
    expect(mocks.createCustomerSession).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button',{name:/mark this answer as helpful/i}))
    expect(mocks.setCustomerMessageFeedback).toHaveBeenCalledWith(CONVERSATION_ID,SESSION_TOKEN,ASSISTANT_MESSAGE_ID,'positive')
    await userEvent.click(screen.getByRole('button',{name:'Request a human'}))
    await userEvent.click(screen.getByRole('button',{name:'Confirm'}))
    expect(await screen.findByText('AI messaging is paused for this conversation.')).toBeInTheDocument()
    expect(screen.getByRole('textbox',{name:'Message'})).toBeDisabled()
  })
  it('keeps streaming and completion on the shared embedded chat path', async () => {
    renderChat('embedded')
    const input=await screen.findByRole('textbox',{name:'Message'})
    await userEvent.type(input,'How do I reset my account?')
    await userEvent.click(screen.getByRole('button',{name:'Send'}))
    expect(await screen.findByText('Use the account reset link.')).toBeInTheDocument()
    expect(mocks.submitCustomerTurn).toHaveBeenCalledWith(CONVERSATION_ID,SESSION_TOKEN,CLIENT_MESSAGE_ID,'How do I reset my account?')
    expect(screen.getByRole('button',{name:/mark this answer as helpful/i})).toBeInTheDocument()
  })
  it('uses the shared safe embedded unavailable state', async () => {
    mocks.createCustomerSession.mockRejectedValue(new Error('private provider detail'))
    renderChat('embedded')
    expect(await screen.findByText('This support assistant is currently unavailable.')).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveAttribute('data-chat-mode','embedded')
    expect(screen.queryByText(/private provider/)).not.toBeInTheDocument()
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
          feedback: null,
        },
        {
          id: '90000000-0000-4000-8000-000000000002',
          role: 'assistant',
          content: 'Receipts are in Billing.',
          answer_status: 'answered',
          created_at: '2026-09-15T12:00:01Z',
          citations: [],
          feedback: null,
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
        message_id: ASSISTANT_MESSAGE_ID,
        client_message_id: CLIENT_MESSAGE_ID,
        status: 'answered',
        answer: 'Use the account reset link.',
        citations: [],
        is_replay: false,
      })
    })
    expect(await screen.findByText('Use the account reset link.')).toBeInTheDocument()
  })

  it('shows one provisional stream before completion and adds citations and feedback only after', async () => {
    let finish!: () => void
    const gate = new Promise<void>((resolve) => {
      finish = resolve
    })
    mocks.streamDriver.mockImplementation(
      async (_conversationId, _token, _clientMessageId, _message, handlers) => {
        handlers.onStarted({
          conversation_id: CONVERSATION_ID,
          turn_id: TURN_ID,
          client_message_id: CLIENT_MESSAGE_ID,
        })
        handlers.onDelta('Reset links ')
        await gate
        handlers.onDelta('expire after 30 minutes.')
        const result = {
          conversation_id: CONVERSATION_ID,
          turn_id: TURN_ID,
          message_id: ASSISTANT_MESSAGE_ID,
          client_message_id: CLIENT_MESSAGE_ID,
          status: 'answered' as const,
          answer: 'Reset links expire after 30 minutes.',
          citations: [
            {
              source_id: '70000000-0000-4000-8000-000000000001',
              source_title: 'Reset FAQ',
              source_type: 'faq' as const,
              chunk_index: 0,
              locator: { kind: 'faq' as const },
            },
          ],
          is_replay: false,
        }
        handlers.onComplete(result)
        return result
      },
    )
    const user = userEvent.setup()
    renderChat()

    await user.type(await screen.findByLabelText('Message'), 'How long does reset last?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Reset links')).toBeInTheDocument()
    expect(screen.queryByText('Reset FAQ — FAQ')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark this answer as helpful' })).toBeNull()

    await act(async () => finish())

    expect(await screen.findByText('Reset links expire after 30 minutes.')).toBeInTheDocument()
    expect(
      screen.getByText((_text, node) => node?.tagName === 'LI' && node.textContent?.includes('Reset FAQ — FAQ') === true),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark this answer as helpful' })).toBeVisible()
    expect(screen.queryByLabelText('Assistant response in progress')).toBeNull()
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
      message_id: ASSISTANT_MESSAGE_ID,
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
          feedback: null,
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
        message_id: ASSISTANT_MESSAGE_ID,
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

  it('removes interrupted provisional text and retries with the same message ID', async () => {
    let interrupt!: (error: Error) => void
    const interruption = new Promise<never>((_resolve, reject) => {
      interrupt = reject
    })
    mocks.streamDriver
      .mockImplementationOnce(
        async (_conversationId, _token, _clientMessageId, _message, handlers) => {
          handlers.onStarted({
            conversation_id: CONVERSATION_ID,
            turn_id: TURN_ID,
            client_message_id: CLIENT_MESSAGE_ID,
          })
          handlers.onDelta('Unfinished private text')
          return interruption
        },
      )
      .mockImplementationOnce(
        async (_conversationId, _token, _clientMessageId, _message, handlers) => {
          const result = {
            conversation_id: CONVERSATION_ID,
            turn_id: TURN_ID,
            message_id: ASSISTANT_MESSAGE_ID,
            client_message_id: CLIENT_MESSAGE_ID,
            status: 'answered' as const,
            answer: 'Recovered authoritative answer.',
            citations: [],
            is_replay: false,
          }
          handlers.onStarted({
            conversation_id: CONVERSATION_ID,
            turn_id: TURN_ID,
            client_message_id: CLIENT_MESSAGE_ID,
          })
          handlers.onDelta(result.answer)
          handlers.onComplete(result)
          return result
        },
      )
    const user = userEvent.setup()
    renderChat()

    await user.type(await screen.findByLabelText('Message'), 'Please retry safely')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Unfinished private text')).toBeInTheDocument()

    await act(async () => interrupt(new Error('connection closed')))

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText('Unfinished private text')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Recovered authoritative answer.')).toBeInTheDocument()
    expect(mocks.streamDriver).toHaveBeenCalledTimes(2)
    expect(mocks.streamDriver.mock.calls[0][2]).toBe(CLIENT_MESSAGE_ID)
    expect(mocks.streamDriver.mock.calls[1][2]).toBe(CLIENT_MESSAGE_ID)
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
        message_id: ASSISTANT_MESSAGE_ID,
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

  it('shows accessible feedback only for assistant messages and allows rating changes', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(
      conversation([
        {
          id: '90000000-0000-4000-8000-000000000001',
          role: 'customer',
          content: 'Can you help?',
          created_at: '2026-09-15T12:00:00Z',
          citations: [],
          feedback: null,
        },
        {
          id: ASSISTANT_MESSAGE_ID,
          role: 'assistant',
          content: 'Here is the grounded answer.',
          answer_status: 'answered',
          created_at: '2026-09-15T12:00:01Z',
          citations: [],
          feedback: null,
        },
      ]),
    )
    const user = userEvent.setup()
    renderChat()

    const helpful = await screen.findByRole('button', { name: /mark this answer as helpful/i })
    const notHelpful = screen.getByRole('button', { name: /mark this answer as not helpful/i })
    expect(screen.getAllByText('Was this helpful?')).toHaveLength(1)
    expect(helpful).toHaveAttribute('aria-pressed', 'false')

    await user.click(helpful)
    expect(mocks.setCustomerMessageFeedback).toHaveBeenCalledWith(
      CONVERSATION_ID,
      SESSION_TOKEN,
      ASSISTANT_MESSAGE_ID,
      'positive',
    )
    expect(helpful).toHaveAttribute('aria-pressed', 'true')

    await user.click(notHelpful)
    expect(mocks.setCustomerMessageFeedback).toHaveBeenLastCalledWith(
      CONVERSATION_ID,
      SESSION_TOKEN,
      ASSISTANT_MESSAGE_ID,
      'negative',
    )
    expect(notHelpful).toHaveAttribute('aria-pressed', 'true')
    expect(helpful).toHaveAttribute('aria-pressed', 'false')
  })

  it('restores selected feedback and hides raw feedback API failures', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(
      conversation([
        {
          id: ASSISTANT_MESSAGE_ID,
          role: 'assistant',
          content: 'Saved answer.',
          answer_status: 'answered',
          created_at: '2026-09-15T12:00:01Z',
          citations: [],
          feedback: 'positive',
        },
      ]),
    )
    mocks.setCustomerMessageFeedback.mockRejectedValue(
      new Error('raw SQL service-role token details'),
    )
    const user = userEvent.setup()
    renderChat()

    expect(
      await screen.findByRole('button', { name: /mark this answer as helpful/i }),
    ).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: /mark this answer as not helpful/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Feedback couldn't be saved right now.",
    )
    expect(screen.queryByText(/raw sql|service-role|token details/i)).not.toBeInTheDocument()
  })

  it('cancels or confirms a human request and pauses the composer after confirmation', async () => {
    const user = userEvent.setup()
    renderChat()
    const composer = await screen.findByLabelText('Message')

    await user.click(screen.getByRole('button', { name: 'Request a human' }))
    expect(screen.getByText(/request human support and pause ai messaging/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(mocks.requestCustomerHumanSupport).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Request a human' }))
    await user.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(mocks.requestCustomerHumanSupport).toHaveBeenCalledWith(
      CONVERSATION_ID,
      SESSION_TOKEN,
    )
    expect(
      await screen.findByText('A human support request has been recorded.'),
    ).toBeInTheDocument()
    expect(screen.getByText('AI messaging is paused for this conversation.')).toBeInTheDocument()
    expect(composer).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Request a human' })).not.toBeInTheDocument()
  })

  it('blocks an already-open human confirmation while a turn is streaming', async () => {
    let rejectTurn!: (reason: Error) => void
    mocks.submitCustomerTurn.mockReturnValue(new Promise((_resolve, reject) => {
      rejectTurn = reject
    }))
    const user = userEvent.setup()
    renderChat()
    const composer = await screen.findByLabelText('Message')
    await user.click(screen.getByRole('button', { name: 'Request a human' }))
    await user.type(composer, 'How do I reset my password?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(mocks.requestCustomerHumanSupport).not.toHaveBeenCalled()
    await act(async () => rejectTurn(new Error('stream interrupted')))
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeEnabled()
  })

  it('restores human-requested state while leaving assistant feedback usable', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storedSession()))
    mocks.getCustomerConversation.mockResolvedValue(
      conversation(
        [
          {
            id: ASSISTANT_MESSAGE_ID,
            role: 'assistant',
            content: 'Earlier answer.',
            answer_status: 'answered',
            created_at: '2026-09-15T12:00:01Z',
            citations: [],
            feedback: null,
          },
        ],
        'human_requested',
      ),
    )
    const user = userEvent.setup()
    renderChat()

    expect(
      await screen.findByText('A human support request has been recorded.'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Message')).toBeDisabled()
    const helpful = screen.getByRole('button', { name: /mark this answer as helpful/i })
    expect(helpful).toBeEnabled()
    await user.click(helpful)
    expect(mocks.setCustomerMessageFeedback).toHaveBeenCalledOnce()
  })

  it('offers a human-request CTA after an insufficient-evidence answer', async () => {
    mocks.submitCustomerTurn.mockResolvedValue({
      conversation_id: CONVERSATION_ID,
      turn_id: TURN_ID,
      message_id: ASSISTANT_MESSAGE_ID,
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

    expect(await screen.findAllByRole('button', { name: 'Request a human' })).toHaveLength(2)
  })

  it('shows a friendly unavailable state without raw errors', async () => {
    mocks.createCustomerSession.mockRejectedValue(new Error('provider stack trace'))
    renderChat()

    expect(await screen.findByText('This support assistant is currently unavailable.')).toBeInTheDocument()
    expect(screen.queryByText(/provider stack trace/i)).not.toBeInTheDocument()
  })
})
