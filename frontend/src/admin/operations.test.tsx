import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { User } from '@supabase/supabase-js'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthContext } from '../auth/AuthContext'
import { AppShell } from '../components/AppShell'
import { WorkspaceContext, type Workspace, type WorkspaceRole } from '../workspace/WorkspaceContext'
import {
  adminApi,
  AdminApiError,
  type ConversationItem,
  type ConversationDetail,
  type EscalationStatus,
  type Dashboard,
  type EscalationItem,
} from './adminApi'
import { AppLanding, OperationsGuard } from './OperationsGuard'
import { DashboardPage } from './DashboardPage'
import { ConversationsPage } from './ConversationsPage'
import { ConversationDetailPage } from './ConversationDetailPage'
import { EscalationsPage } from './EscalationsPage'
import { EscalationDetailPage } from './EscalationDetailPage'
import { citationLocation } from './format'

const A = '20000000-0000-4000-8000-000000000001'
const B = '20000000-0000-4000-8000-000000000002'
const C = '40000000-0000-4000-8000-000000000001'
const E = '50000000-0000-4000-8000-000000000001'
const TIME = '2026-09-16T12:00:00Z'
const conversation: ConversationItem & { resolved_at: null; closed_at: null } = {
  id: C,
  status: 'open',
  resolution_outcome: 'unresolved',
  resolved_at: null,
  closed_at: null,
  created_at: TIME,
  updated_at: TIME,
  last_message_at: TIME,
  message_count: 2,
  assistant_message_count: 1,
  feedback_positive_count: 1,
  feedback_negative_count: 0,
  has_escalation: true,
  escalation_priority: 'high',
}
const escalation: EscalationItem = {
  id: E,
  conversation_id: C,
  trigger_reason: 'insufficient_evidence',
  status: 'open',
  triage_status: 'completed',
  category: 'billing',
  priority: 'high',
  summary: 'Synthetic triage summary.',
  triage_attempts: 2,
  created_at: TIME,
  updated_at: TIME,
  triaged_at: TIME,
  last_error_code: null,
  notification_status: 'pending',
}
const zero: Dashboard = {
  workspace_id: A,
  metrics: {
    total_conversations: 0,
    resolved_conversations: 0,
    closed_unresolved_conversations: 0,
    ai_answered_conversations: 0,
    insufficient_evidence_conversations: 0,
    escalated_conversations: 0,
    human_requested_conversations: 0,
    positive_feedback_count: 0,
    negative_feedback_count: 0,
    open_escalations: 0,
    high_priority_escalations: 0,
    urgent_escalations: 0,
    knowledge_ready: 0,
    knowledge_processing: 0,
    knowledge_failed: 0,
  },
  recent_conversations: [],
  recent_escalations: [],
}

function Harness({
  path = '/app/dashboard',
  role = 'owner',
  loading = false,
  noWorkspace = false,
}: {
  path?: string
  role?: WorkspaceRole
  loading?: boolean
  noWorkspace?: boolean
}) {
  const [id, setId] = useState(A)
  const [token, setToken] = useState('caller-token')
  const workspaces: Workspace[] = [
    { id: A, name: 'Workspace A', role, created_at: TIME },
    { id: B, name: 'Workspace B', role, created_at: TIME },
  ]
  return (
    <AuthContext.Provider
      value={{
        accessToken: token,
        user: { id: 'user-1', user_metadata: {}, email: 'owner@example.test' } as User,
        session: null,
        loading: false,
        configurationError: null,
        signIn: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
      }}
    >
      <WorkspaceContext.Provider
        value={{
          selectedWorkspace: noWorkspace ? null : workspaces.find((item) => item.id === id)!,
          workspaces: noWorkspace ? [] : workspaces,
          loading,
          error: null,
          selectWorkspace: setId,
          createWorkspace: vi.fn(),
          refreshWorkspaces: vi.fn(),
        }}
      >
        <button onClick={() => setToken('new-caller-token')}>Change identity</button>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/app" element={<AppShell />}>
              <Route index element={<AppLanding />} />
              <Route path="knowledge" element={<h1>Knowledge Base access</h1>} />
              <Route path="workspaces" element={<h1>Workspace onboarding</h1>} />
              <Route element={<OperationsGuard />}>
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="conversations" element={<ConversationsPage />} />
                <Route path="conversations/:conversationId" element={<ConversationDetailPage />} />
                <Route path="escalations" element={<EscalationsPage />} />
                <Route path="escalations/:escalationId" element={<EscalationDetailPage />} />
              </Route>
            </Route>
          </Routes>
        </MemoryRouter>
      </WorkspaceContext.Provider>
    </AuthContext.Provider>
  )
}

beforeEach(() => {
  vi.spyOn(adminApi, 'setConversationResolution')
  vi.spyOn(adminApi, 'setEscalationStatus')
  vi.spyOn(adminApi, 'dashboard').mockImplementation(async (id) => ({ ...zero, workspace_id: id }))
  vi.spyOn(adminApi, 'conversations').mockImplementation(async (id) => ({
    workspace_id: id,
    items: [],
    next_cursor: null,
  }))
  vi.spyOn(adminApi, 'escalations').mockImplementation(async (id) => ({
    workspace_id: id,
    items: [],
    next_cursor: null,
  }))
  vi.spyOn(adminApi, 'conversation').mockResolvedValue({
    workspace_id: A,
    conversation: { ...conversation, human_requested_at: null },
    messages: [],
    escalation: null,
  })
  vi.spyOn(adminApi, 'escalation').mockResolvedValue({
    workspace_id: A,
    escalation,
    audit_runs: [],
    notification: null,
  })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ user_id: 'user-1', email: 'owner@example.test' }),
    }),
  )
  localStorage.clear()
  sessionStorage.clear()
})

function detail(status: 'open' | 'human_requested' | 'closed' = 'open', outcome: 'unresolved' | 'resolved' | 'closed_unresolved' = 'unresolved', human = false): ConversationDetail {
  return { workspace_id: A, conversation: { ...conversation, status, resolution_outcome: outcome,
    human_requested_at: human ? TIME : null, resolved_at: outcome === 'resolved' ? TIME : null, closed_at: status === 'closed' ? TIME : null }, messages: [], escalation: null }
}

describe('explicit conversation lifecycle', () => {
  it.each(['open', 'human_requested'] as const)('offers only appropriate unresolved %s actions', async status => {
    vi.mocked(adminApi.conversation).mockResolvedValue(detail(status, 'unresolved', status === 'human_requested'))
    render(<Harness path={`/app/conversations/${C}`} />)
    expect(await screen.findByRole('button', { name: 'Resolve conversation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close unresolved' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reopen conversation' })).not.toBeInTheDocument()
  })
  it('allows confirmation cancellation without a mutation', async () => {
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Resolve conversation' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('explicit admin decision')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(adminApi.setConversationResolution).not.toHaveBeenCalled()
  })
  it.each([
    ['Resolve conversation', 'resolve', 'resolved'], ['Close unresolved', 'close_unresolved', 'closed_unresolved'],
  ] as const)('updates only from successful server %s state', async (label, action, outcome) => {
    vi.mocked(adminApi.setConversationResolution).mockResolvedValue(detail('closed', outcome))
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: label }))
    await userEvent.click(screen.getByRole('button', { name: `Confirm ${label.toLowerCase()}` }))
    expect(await screen.findByRole('button', { name: 'Reopen conversation' })).toBeInTheDocument()
    expect(adminApi.setConversationResolution).toHaveBeenCalledWith(A, 'caller-token', C,
      { expected_status: 'open', expected_resolution_outcome: 'unresolved', action }, expect.any(AbortSignal))
    if (outcome === 'closed_unresolved') expect(screen.getByText('Closed without resolution')).toBeInTheDocument()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
  it.each([false, true])('reopens with correct human-history messaging (%s)', async human => {
    vi.mocked(adminApi.conversation).mockResolvedValue(detail('closed', 'resolved', human))
    vi.mocked(adminApi.setConversationResolution).mockResolvedValue(detail(human ? 'human_requested' : 'open', 'unresolved', human))
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Reopen conversation' }))
    expect(screen.getByRole('dialog')).toHaveTextContent(human ? 'AI replies will remain paused' : 'Normal customer AI replies')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm reopen conversation' }))
    expect(await screen.findByRole('button', { name: 'Resolve conversation' })).toBeInTheDocument()
    expect(adminApi.setConversationResolution).toHaveBeenCalledWith(A, 'caller-token', C,
      { expected_status: 'closed', expected_resolution_outcome: 'resolved', action: 'reopen' }, expect.any(AbortSignal))
  })
  it('shows closed-without-resolution outcome and offers reopen', async () => {
    vi.mocked(adminApi.conversation).mockResolvedValue(detail('closed', 'closed_unresolved'))
    render(<Harness path={`/app/conversations/${C}`} />)
    expect(await screen.findByText('Closed without resolution')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reopen conversation' })).toBeInTheDocument()
  })
  it('handles stale mutation with refresh and no optimistic success', async () => {
    vi.mocked(adminApi.setConversationResolution).mockRejectedValue(new AdminApiError('This record changed before your action was completed. Refresh and try again.'))
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Resolve conversation' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm resolve conversation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This record changed')
    expect(screen.queryByRole('button', { name: 'Reopen conversation' })).not.toBeInTheDocument()
    vi.mocked(adminApi.conversation).mockResolvedValue(detail('closed', 'resolved'))
    await userEvent.click(screen.getByRole('button', { name: 'Refresh record' }))
    expect(await screen.findByRole('button', { name: 'Reopen conversation' })).toBeInTheDocument()
  })
  it('hides raw mutation failures', async () => {
    vi.mocked(adminApi.setConversationResolution).mockRejectedValue(new Error('private SQL/provider credentials'))
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Close unresolved' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm close unresolved' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Support action could not be completed')
    expect(screen.queryByText(/private SQL/)).not.toBeInTheDocument()
  })
  it('disables pending controls and fences a late result after workspace switching', async () => {
    let late!: (value: ConversationDetail) => void
    vi.mocked(adminApi.setConversationResolution).mockImplementation(() => new Promise(resolve => { late = resolve }))
    vi.mocked(adminApi.conversation).mockImplementation(async id => ({ ...detail(), workspace_id: id }))
    render(<Harness path={`/app/conversations/${C}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Resolve conversation' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm resolve conversation' }))
    expect(screen.getByRole('button', { name: 'Confirm resolve conversation' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Reopen conversation' })).not.toBeInTheDocument()
    const signal = vi.mocked(adminApi.setConversationResolution).mock.calls[0][4]
    await userEvent.selectOptions(screen.getByLabelText('Active workspace'), B)
    expect(signal.aborted).toBe(true)
    await screen.findByRole('button', { name: 'Resolve conversation' })
    await act(async () => late(detail('closed', 'resolved')))
    expect(screen.queryByRole('button', { name: 'Reopen conversation' })).not.toBeInTheDocument()
  })
})

describe('escalation lifecycle', () => {
  it.each([
    ['open', ['Start work','Resolve','Close']], ['in_progress', ['Return to queue','Resolve','Close']],
    ['resolved', ['Reopen','Close']], ['closed', ['Reopen']],
  ] as [EscalationStatus, string[]][])('shows correct %s controls', async (status, controls) => {
    vi.mocked(adminApi.escalation).mockResolvedValue({ workspace_id:A, escalation:{...escalation,status}, audit_runs:[],notification:null })
    render(<Harness path={`/app/escalations/${E}`} />)
    for (const name of controls) expect(await screen.findByRole('button',{name})).toBeInTheDocument()
    for (const name of ['Start work','Return to queue','Resolve','Close','Reopen'].filter(name => !controls.includes(name)))
      expect(screen.queryByRole('button',{name})).not.toBeInTheDocument()
  })
  it.each([
    ['open','Start work','in_progress'], ['in_progress','Return to queue','open'], ['open','Resolve','resolved'],
    ['in_progress','Close','closed'], ['closed','Reopen','open'],
  ] as [EscalationStatus,string,EscalationStatus][])('handles %s / %s through server confirmation', async (before, label, after) => {
    vi.mocked(adminApi.escalation).mockResolvedValue({workspace_id:A,escalation:{...escalation,status:before},audit_runs:[],notification:null})
    vi.mocked(adminApi.setEscalationStatus).mockResolvedValue({workspace_id:A,escalation:{...escalation,status:after},audit_runs:[],notification:null})
    render(<Harness path={`/app/escalations/${E}`} />)
    await userEvent.click(await screen.findByRole('button',{name:label}))
    if (after === 'resolved' || after === 'closed') {
      expect(screen.getByRole('dialog')).toHaveTextContent('not the associated conversation')
      await userEvent.click(screen.getByRole('button',{name:`Confirm ${label.toLowerCase()}`}))
    }
    await waitFor(() => expect(adminApi.setEscalationStatus).toHaveBeenCalledWith(A,'caller-token',E,{expected_status:before,status:after},expect.any(AbortSignal)))
    expect(await screen.findByText(after.replaceAll('_',' '),{selector:'span'})).toBeInTheDocument()
  })
  it('disables pending actions, permits cancelling close confirmation, and displays conflicts safely', async () => {
    let reject!: (error: Error) => void
    vi.mocked(adminApi.setEscalationStatus).mockImplementation(() => new Promise((_resolve,rejection) => { reject = rejection }))
    render(<Harness path={`/app/escalations/${E}`} />)
    await userEvent.click(await screen.findByRole('button',{name:'Close'}))
    await userEvent.click(screen.getByRole('button',{name:'Cancel'}))
    expect(adminApi.setEscalationStatus).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button',{name:'Start work'}))
    for (const name of ['Start work','Resolve','Close']) expect(screen.getByRole('button',{name})).toBeDisabled()
    await act(async () => reject(new AdminApiError('This record changed before your action was completed. Refresh and try again.')))
    expect(await screen.findByRole('alert')).toHaveTextContent('This record changed')
    expect(screen.getByRole('button',{name:'Refresh record'})).toBeInTheDocument()
  })
})

describe('honest resolution analytics', () => {
  it('uses explicit outcomes for resolution and keeps AI answer coverage separate', async () => {
    vi.mocked(adminApi.dashboard).mockResolvedValue({...zero,metrics:{...zero.metrics,total_conversations:4,resolved_conversations:1,closed_unresolved_conversations:1,ai_answered_conversations:3}})
    render(<Harness />)
    expect(await screen.findByText('25%')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('Resolved conversations')).toBeInTheDocument()
    expect(screen.getByText('Overall conversation resolution')).toBeInTheDocument()
    expect(screen.getByText('AI answer coverage')).toBeInTheDocument()
    expect(screen.queryByText(/AI resolution rate/i)).not.toBeInTheDocument()
  })
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('operations permissions and navigation', () => {
  it.each(['owner', 'admin'] as const)(
    'shows %s operational navigation and the default dashboard',
    async (role) => {
      render(<Harness path="/app" role={role} />)
      expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
      const navigation = within(screen.getByRole('navigation', { name: 'Application' }))
      for (const name of [
        'Dashboard',
        'Conversations',
        'Escalations',
        'Knowledge Base',
        'Workspace',
      ])
        expect(navigation.getByRole('link', { name })).toBeInTheDocument()
    },
  )
  it.each([
    '/app',
    '/app/dashboard',
    '/app/conversations',
    `/app/conversations/${C}`,
    '/app/escalations',
    `/app/escalations/${E}`,
  ])('keeps member out of %s', async (path) => {
    render(<Harness path={path} role="member" />)
    expect(
      await screen.findByRole('heading', { name: 'Knowledge Base access' }),
    ).toBeInTheDocument()
    const navigation = within(screen.getByRole('navigation', { name: 'Application' }))
    for (const name of ['Dashboard', 'Conversations', 'Escalations'])
      expect(navigation.queryByRole('link', { name })).not.toBeInTheDocument()
    expect(adminApi.dashboard).not.toHaveBeenCalled()
    expect(adminApi.conversation).not.toHaveBeenCalled()
    expect(adminApi.escalation).not.toHaveBeenCalled()
  })
  it('waits for workspace loading without redirecting', () => {
    render(<Harness loading />)
    expect(screen.getByText('Loading workspace…')).toBeInTheDocument()
    expect(adminApi.dashboard).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: 'Workspace onboarding' })).not.toBeInTheDocument()
  })
  it('routes users with no workspace to onboarding', async () => {
    render(<Harness noWorkspace />)
    expect(await screen.findByRole('heading', { name: 'Workspace onboarding' })).toBeInTheDocument()
  })
})

describe('dashboard', () => {
  it('renders zero counts and 0% coverage, without inventing resolution', async () => {
    render(<Harness />)
    expect(await screen.findAllByText('0%')).toHaveLength(2)
    expect(screen.getByText('No conversations yet.')).toBeInTheDocument()
    expect(screen.getByText('No escalations yet.')).toBeInTheDocument()
    expect(screen.getByText('AI answered conversations')).toBeInTheDocument()
    expect(screen.queryByText(/AI resolution rate/i)).not.toBeInTheDocument()
  })
  it('calculates coverage and links recent records', async () => {
    vi.mocked(adminApi.dashboard).mockResolvedValue({
      ...zero,
      metrics: { ...zero.metrics, total_conversations: 4, ai_answered_conversations: 3 },
      recent_conversations: [conversation],
      recent_escalations: [escalation],
    })
    render(<Harness />)
    expect(await screen.findByText('75%')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View conversation' })).toHaveAttribute(
      'href',
      `/app/conversations/${C}`,
    )
    expect(screen.getByRole('link', { name: 'View escalation' })).toHaveAttribute(
      'href',
      `/app/escalations/${E}`,
    )
  })
  it('shows safe errors and supports reload', async () => {
    vi.mocked(adminApi.dashboard).mockRejectedValueOnce(
      new AdminApiError('Owner or admin access is required for this workspace.'),
    )
    render(<Harness />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Owner or admin access')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findAllByText('0%')).toHaveLength(2)
  })
  it('synchronously removes old records on switching and ignores a late old response', async () => {
    let late!: (value: Dashboard) => void
    vi.mocked(adminApi.dashboard).mockImplementation((id) =>
      id === A
        ? new Promise((resolve) => {
            late = resolve
          })
        : Promise.resolve({ ...zero, workspace_id: B }),
    )
    render(<Harness />)
    await waitFor(() => expect(adminApi.dashboard).toHaveBeenCalled())
    const oldSignal = vi.mocked(adminApi.dashboard).mock.calls[0][2]
    await userEvent.selectOptions(screen.getByLabelText('Active workspace'), B)
    expect(oldSignal.aborted).toBe(true)
    expect(await screen.findAllByText('0%')).toHaveLength(2)
    await act(async () =>
      late({
        ...zero,
        metrics: { ...zero.metrics, total_conversations: 999 },
        recent_conversations: [conversation],
      }),
    )
    expect(screen.queryByText('999')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View conversation' })).not.toBeInTheDocument()
  })
  it('does not show loaded old workspace or identity data while new data is pending', async () => {
    vi.mocked(adminApi.dashboard)
      .mockResolvedValueOnce({ ...zero, metrics: { ...zero.metrics, total_conversations: 111 } })
      .mockImplementation(() => new Promise(() => {}))
    render(<Harness />)
    expect(await screen.findByText('111')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Active workspace'), B)
    expect(screen.queryByText('111')).not.toBeInTheDocument()
    expect(screen.getByText('Loading support operations…')).toBeInTheDocument()
  })
  it('discards data when authenticated identity changes in the same workspace', async () => {
    vi.mocked(adminApi.dashboard)
      .mockResolvedValueOnce({ ...zero, metrics: { ...zero.metrics, total_conversations: 222 } })
      .mockImplementation(() => new Promise(() => {}))
    render(<Harness />)
    expect(await screen.findByText('222')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Change identity' }))
    expect(screen.queryByText('222')).not.toBeInTheDocument()
  })
})

describe('conversation and escalation lists', () => {
  it('paginates escalation records and resets cursors after a filter change', async () => {
    const cursor = { time: TIME, id: E }
    vi.mocked(adminApi.escalations).mockImplementation(async (id, _token, _filters, current) => ({
      workspace_id: id,
      items: [escalation],
      next_cursor: current ? null : cursor,
    }))
    render(<Harness path="/app/escalations" />)
    await screen.findByRole('link', { name: 'View escalation' })
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(adminApi.escalations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        expect.any(Object),
        cursor,
        expect.any(AbortSignal),
      ),
    )
    await screen.findByRole('link', { name: 'View escalation' })
    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await waitFor(() =>
      expect(adminApi.escalations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        expect.any(Object),
        null,
        expect.any(AbortSignal),
      ),
    )
    await userEvent.selectOptions(screen.getByLabelText('Priority'), 'urgent')
    await waitFor(() =>
      expect(adminApi.escalations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        expect.objectContaining({ priority: 'urgent' }),
        null,
        expect.any(AbortSignal),
      ),
    )
  })
  it('uses server filters and next/previous cursors, resetting pagination on filter and workspace changes', async () => {
    const cursor = { time: TIME, id: C }
    vi.mocked(adminApi.conversations).mockImplementation(async (id, _token, _filters, current) => ({
      workspace_id: id,
      items: [conversation],
      next_cursor: current ? null : cursor,
    }))
    render(<Harness path="/app/conversations" />)
    expect(await screen.findByRole('link', { name: 'View conversation' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(adminApi.conversations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        { status: 'all' },
        cursor,
        expect.any(AbortSignal),
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await userEvent.selectOptions(screen.getByLabelText('Conversation status'), 'human_requested')
    await waitFor(() =>
      expect(adminApi.conversations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        { status: 'human_requested' },
        null,
        expect.any(AbortSignal),
      ),
    )
    await userEvent.selectOptions(screen.getByLabelText('Active workspace'), B)
    await waitFor(() =>
      expect(adminApi.conversations).toHaveBeenLastCalledWith(
        B,
        'caller-token',
        { status: 'all' },
        null,
        expect.any(AbortSignal),
      ),
    )
  })
  it('shows escalation summaries, notification badges, and all four server filters', async () => {
    vi.mocked(adminApi.escalations).mockResolvedValue({
      workspace_id: A,
      items: [escalation],
      next_cursor: null,
    })
    render(<Harness path="/app/escalations" />)
    expect(await screen.findByText(/AI triage summary: Synthetic/)).toBeInTheDocument()
    for (const [name, value] of [
      ['Escalation status', 'open'],
      ['Triage status', 'completed'],
      ['Priority', 'high'],
      ['Trigger reason', 'insufficient_evidence'],
    ])
      await userEvent.selectOptions(screen.getByLabelText(name), value)
    await waitFor(() =>
      expect(adminApi.escalations).toHaveBeenLastCalledWith(
        A,
        'caller-token',
        {
          status: 'open',
          triage_status: 'completed',
          priority: 'high',
          trigger_reason: 'insufficient_evidence',
        },
        null,
        expect.any(AbortSignal),
      ),
    )
    expect(screen.getByText('pending', { selector: 'span' })).toBeInTheDocument()
  })
})

describe('read-only details', () => {
  it('renders transcript, citations, feedback, and escalation as plain text without browser persistence', async () => {
    const unsafe = '<img src=x onerror="alert(1)">'
    vi.mocked(adminApi.conversation).mockResolvedValue({
      workspace_id: A,
      conversation: { ...conversation, human_requested_at: TIME },
      messages: [
        {
          id: 'message-1',
          role: 'customer',
          content: unsafe,
          answer_status: null,
          created_at: TIME,
          feedback: null,
          citations: [],
        },
        {
          id: 'message-2',
          role: 'assistant',
          content: 'Synthetic answer.',
          answer_status: 'answered',
          created_at: TIME,
          feedback: 'positive',
          citations: [
            {
              source_id: C,
              source_title: unsafe,
              source_type: 'file',
              chunk_index: 0,
              locator: { kind: 'pdf', page_start: 2, page_end: 3 },
            },
          ],
        },
      ],
      escalation: { ...escalation, summary: unsafe },
    })
    const { container } = render(<Harness path={`/app/conversations/${C}`} />)
    expect(await screen.findByText(unsafe)).toBeInTheDocument()
    expect(screen.getByText(/Pages 2–3/)).toBeInTheDocument()
    expect(screen.getByText('Customer feedback: Helpful')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View escalation and audit' })).toHaveAttribute(
      'href',
      `/app/escalations/${E}`,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(
      screen.queryByRole('button', { name: /delete|reply/i }),
    ).not.toBeInTheDocument()
  })
  it('renders audit attempts, safe errors and pending notification honestly', async () => {
    vi.mocked(adminApi.escalation).mockResolvedValue({
      workspace_id: A,
      escalation,
      audit_runs: [
        {
          attempt_number: 2,
          status: 'completed',
          provider: 'gemini',
          model: 'demo-model',
          tool_name: 'create_escalation',
          safe_error_code: null,
          started_at: TIME,
          completed_at: TIME,
        },
        {
          attempt_number: 1,
          status: 'failed',
          provider: null,
          model: null,
          tool_name: null,
          safe_error_code: 'triage_rate_limited',
          started_at: TIME,
          completed_at: TIME,
        },
      ],
      notification: {
        status: 'pending',
        attempts: 0,
        provider: null,
        last_error_code: null,
        sent_at: null,
        created_at: TIME,
        updated_at: TIME,
      },
    })
    render(<Harness path={`/app/escalations/${E}`} />)
    expect(await screen.findByText('Attempt 2')).toBeInTheDocument()
    expect(screen.getByText('Attempt 1')).toBeInTheDocument()
    expect(screen.getByText(/gemini \/ demo-model/)).toBeInTheDocument()
    expect(screen.getByText(/Allowed tool: create_escalation/)).toBeInTheDocument()
    expect(screen.getByText('Safe error: triage_rate_limited')).toBeInTheDocument()
    expect(
      screen.getByText(/does not confirm that notifications are configured/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Notification sent.')).not.toBeInTheDocument()
  })
  it.each(['sending', 'sent', 'failed'] as const)(
    'shows actual %s notification state',
    async (status) => {
      vi.mocked(adminApi.escalation).mockResolvedValue({
        workspace_id: A,
        escalation,
        audit_runs: [],
        notification: {
          status,
          attempts: 1,
          provider: status === 'sent' ? 'resend' : null,
          last_error_code: status === 'failed' ? 'notification_failed' : null,
          sent_at: status === 'sent' ? TIME : null,
          created_at: TIME,
          updated_at: TIME,
        },
      })
      render(<Harness path={`/app/escalations/${E}`} />)
      expect(await screen.findByText(status)).toBeInTheDocument()
      expect(screen.queryByText('Notification sent.') !== null).toBe(status === 'sent')
    },
  )
  it('formats all citation locator kinds without fabricated links', () => {
    const base = {
      source_id: C,
      source_title: 'Demo',
      source_type: 'file' as const,
      chunk_index: 0,
    }
    expect(
      citationLocation({ ...base, locator: { kind: 'docx', block_start: 1, block_end: 2 } }),
    ).toBe('Blocks 1–2')
    expect(
      citationLocation({ ...base, locator: { kind: 'text', line_start: 4, line_end: 4 } }),
    ).toBe('Line 4')
    expect(
      citationLocation({ ...base, locator: { kind: 'markdown', line_start: 2, line_end: 3 } }),
    ).toBe('Lines 2–3')
    expect(citationLocation({ ...base, source_type: 'faq', locator: { kind: 'faq' } })).toBe('FAQ')
  })
})
