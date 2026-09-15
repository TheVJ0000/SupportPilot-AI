import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useParams } from 'react-router-dom'
import { Brand } from '../components/Brand'
import {
  CUSTOMER_MESSAGE_LIMIT,
  CustomerChatApiError,
  createCustomerSession,
  getCustomerConversation,
  submitCustomerTurn,
  type CitationLocator,
  type CustomerCitation,
  type CustomerMessage,
  type CustomerTurnResult,
} from '../chat/customerChatApi'
import {
  clearCustomerChatSession,
  loadCustomerChatSession,
  saveCustomerChatSession,
  type StoredCustomerChatSession,
} from '../chat/sessionStorage'

interface OutboundMessage {
  clientMessageId: string
  message: string
}

function formatRange(singular: string, plural: string, start: number, end: number): string {
  return start === end ? `${singular} ${start}` : `${plural} ${start}–${end}`
}

function formatCitationLocator(locator: CitationLocator): string {
  if (locator.kind === 'faq') return 'FAQ'
  if (locator.kind === 'pdf') {
    return formatRange('page', 'pages', locator.page_start, locator.page_end)
  }
  if (locator.kind === 'docx') {
    return formatRange('block', 'blocks', locator.block_start, locator.block_end)
  }
  return formatRange('line', 'lines', locator.line_start, locator.line_end)
}

function CitationList({ citations }: { citations: CustomerCitation[] }) {
  if (citations.length === 0) return null
  return (
    <div className="mt-4 border-t border-slate-200 pt-3">
      <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-500">Sources</p>
      <ol className="mt-2 space-y-1.5 text-sm text-slate-600">
        {citations.map((citation, index) => (
          <li key={`${citation.source_id}:${citation.chunk_index}:${index}`}>
            {index + 1}. {citation.source_title} — {formatCitationLocator(citation.locator)}
          </li>
        ))}
      </ol>
    </div>
  )
}

function MessageBubble({ message }: { message: CustomerMessage }) {
  const isCustomer = message.role === 'customer'
  return (
    <article
      className={`max-w-[88%] whitespace-pre-wrap break-words rounded-3xl px-5 py-4 shadow-sm sm:max-w-[78%] ${
        isCustomer
          ? 'ml-auto rounded-br-lg bg-cyan-600 text-white'
          : 'mr-auto rounded-bl-lg border border-slate-200 bg-white text-slate-800'
      }`}
    >
      <p className="leading-7">{message.content}</p>
      {!isCustomer && <CitationList citations={message.citations} />}
    </article>
  )
}

function localCustomerMessage(outbound: OutboundMessage): CustomerMessage {
  return {
    id: outbound.clientMessageId,
    role: 'customer',
    content: outbound.message,
    created_at: new Date().toISOString(),
    citations: [],
  }
}

function assistantMessage(result: CustomerTurnResult): CustomerMessage {
  return {
    id: `assistant-${result.turn_id}`,
    role: 'assistant',
    content: result.answer,
    answer_status: result.status,
    created_at: new Date().toISOString(),
    citations: result.citations,
  }
}

export function CustomerChatPage() {
  const { publicId } = useParams<{ publicId: string }>()
  const [session, setSession] = useState<StoredCustomerChatSession | null>(null)
  const [messages, setMessages] = useState<CustomerMessage[]>([])
  const [draft, setDraft] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>(
    publicId ? 'loading' : 'unavailable',
  )
  const [sending, setSending] = useState(false)
  const [failedOutbound, setFailedOutbound] = useState<OutboundMessage | null>(null)
  const sendingRef = useRef(false)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!publicId) {
      return
    }
    const controller = new AbortController()
    let active = true

    async function createFreshSession(): Promise<void> {
      const created = await createCustomerSession(publicId!, controller.signal)
      if (!active) return
      const stored = saveCustomerChatSession(publicId!, created)
      setSession(stored)
      setMessages([])
      setState('ready')
    }

    async function initialize(): Promise<void> {
      const stored = loadCustomerChatSession(publicId!)
      if (stored === null) {
        await createFreshSession()
        return
      }
      try {
        const conversation = await getCustomerConversation(
          stored.conversationId,
          stored.sessionToken,
          controller.signal,
        )
        if (!active) return
        if (conversation.conversation_id !== stored.conversationId) {
          throw new CustomerChatApiError('unavailable')
        }
        setSession(stored)
        setMessages(conversation.messages)
        setState('ready')
      } catch (caught) {
        if (!(caught instanceof CustomerChatApiError) || caught.kind !== 'invalid-session') {
          throw caught
        }
        clearCustomerChatSession(publicId!)
        await createFreshSession()
      }
    }

    void initialize().catch(() => {
      if (active) setState('unavailable')
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [publicId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [messages, sending])

  async function submitOutbound(outbound: OutboundMessage, isRetry: boolean): Promise<void> {
    if (!publicId || !session || sendingRef.current) return
    if (!isRetry) {
      setMessages((current) => [...current, localCustomerMessage(outbound)])
      setFailedOutbound(null)
    }
    sendingRef.current = true
    setSending(true)

    try {
      let activeSession = session
      let result: CustomerTurnResult
      try {
        result = await submitCustomerTurn(
          activeSession.conversationId,
          activeSession.sessionToken,
          outbound.clientMessageId,
          outbound.message,
        )
      } catch (caught) {
        if (!(caught instanceof CustomerChatApiError) || caught.kind !== 'invalid-session') {
          throw caught
        }
        clearCustomerChatSession(publicId)
        const created = await createCustomerSession(publicId)
        activeSession = saveCustomerChatSession(publicId, created)
        setSession(activeSession)
        setMessages([localCustomerMessage(outbound)])
        result = await submitCustomerTurn(
          activeSession.conversationId,
          activeSession.sessionToken,
          outbound.clientMessageId,
          outbound.message,
        )
      }
      if (
        result.conversation_id !== activeSession.conversationId ||
        result.client_message_id !== outbound.clientMessageId
      ) {
        throw new CustomerChatApiError('unavailable')
      }
      setMessages((current) => [...current, assistantMessage(result)])
      setFailedOutbound(null)
    } catch {
      setFailedOutbound(outbound)
    } finally {
      sendingRef.current = false
      setSending(false)
      window.setTimeout(() => composerRef.current?.focus(), 0)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    const normalized = draft.trim().replace(/\s+/g, ' ')
    if (!normalized || normalized.length > CUSTOMER_MESSAGE_LIMIT || sendingRef.current) return
    const outbound = { clientMessageId: crypto.randomUUID(), message: normalized }
    setDraft('')
    void submitOutbound(outbound, false)
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  if (state === 'loading') {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-100 px-5 text-slate-700">
        <p aria-live="polite" className="font-medium">Opening support chat…</p>
      </main>
    )
  }

  if (state === 'unavailable' || session === null) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-100 px-5 text-slate-800">
        <section className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-xl shadow-slate-300/30">
          <div className="flex justify-center"><Brand compact /></div>
          <h1 className="mt-8 text-2xl font-bold">Support chat unavailable</h1>
          <p className="mt-3 leading-7 text-slate-600">This support assistant is currently unavailable.</p>
        </section>
      </main>
    )
  }

  const normalizedDraft = draft.trim().replace(/\s+/g, ' ')
  const canSend = normalizedDraft.length > 0 && normalizedDraft.length <= CUSTOMER_MESSAGE_LIMIT && !sending

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#cffafe_0,#f8fafc_42%,#e2e8f0_100%)] px-3 py-3 text-slate-900 sm:px-6 sm:py-7">
      <section className="mx-auto flex min-h-[calc(100vh-1.5rem)] max-w-4xl flex-col overflow-hidden rounded-[2rem] border border-white/80 bg-slate-50/95 shadow-2xl shadow-slate-400/25 backdrop-blur sm:min-h-[calc(100vh-3.5rem)]">
        <header className="flex items-center justify-between gap-5 border-b border-slate-200 bg-white px-5 py-4 sm:px-7">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-700">Support assistant</p>
            <h1 className="mt-1 truncate text-lg font-bold text-slate-900 sm:text-xl">{session.workspaceName}</h1>
          </div>
          <div className="shrink-0 scale-90 text-slate-900 sm:scale-100"><Brand compact /></div>
        </header>

        <div
          aria-label="Conversation messages"
          aria-live="polite"
          aria-relevant="additions text"
          className="flex-1 overflow-y-auto px-4 py-6 sm:px-8"
          role="log"
        >
          {messages.length === 0 ? (
            <div className="mx-auto mt-[12vh] max-w-lg text-center">
              <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-cyan-100 text-2xl" aria-hidden="true">?</div>
              <h2 className="mt-5 text-2xl font-bold tracking-tight text-slate-900">How can we help?</h2>
              <p className="mt-3 leading-7 text-slate-600">Ask a question and I'll answer using this business's support knowledge.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
            </div>
          )}

          {sending && (
            <div aria-live="polite" className="mt-4 mr-auto w-fit rounded-3xl rounded-bl-lg border border-slate-200 bg-white px-5 py-4 text-sm text-slate-500 shadow-sm">
              Finding a grounded answer…
            </div>
          )}
          {failedOutbound && !sending && (
            <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" role="alert">
              <p>I couldn't complete that response right now. Please try again.</p>
              <button className="mt-2 font-bold text-cyan-800 underline underline-offset-4" onClick={() => void submitOutbound(failedOutbound, true)} type="button">Retry</button>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form className="border-t border-slate-200 bg-white p-4 sm:p-6" onSubmit={handleSubmit}>
          <label className="sr-only" htmlFor="customer-message">Message</label>
          <div className="flex items-end gap-3 rounded-2xl border border-slate-300 bg-slate-50 p-2 focus-within:border-cyan-500 focus-within:ring-4 focus-within:ring-cyan-100">
            <textarea
              className="max-h-36 min-h-12 min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 leading-6 text-slate-900 outline-none placeholder:text-slate-400 disabled:opacity-60"
              disabled={sending}
              id="customer-message"
              maxLength={CUSTOMER_MESSAGE_LIMIT}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask a support question…"
              ref={composerRef}
              rows={1}
              value={draft}
            />
            <button className="min-h-12 rounded-xl bg-cyan-600 px-5 font-bold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:bg-slate-300" disabled={!canSend} type="submit">
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
          <p className="mt-2 text-right text-xs text-slate-500">{draft.length.toLocaleString()} / {CUSTOMER_MESSAGE_LIMIT.toLocaleString()}</p>
        </form>
      </section>
    </main>
  )
}
