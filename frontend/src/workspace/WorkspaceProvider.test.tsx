import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspacePage } from '../pages/WorkspacePage'
import { WorkspaceProvider } from './WorkspaceProvider'

const mocks = vi.hoisted(() => ({
  getSupabaseClient: vi.fn(),
  order: vi.fn(),
  rpc: vi.fn(),
  useAuth: vi.fn(),
}))

vi.mock('../auth/useAuth', () => ({ useAuth: mocks.useAuth }))
vi.mock('../lib/supabase', () => ({ getSupabaseClient: mocks.getSupabaseClient }))

const USER_ID = '10000000-0000-0000-0000-000000000001'
const WORKSPACE_A = {
  id: '20000000-0000-0000-0000-000000000001',
  name: 'Alpha Support',
  created_at: '2026-09-15T00:00:00Z',
}
const WORKSPACE_B = {
  id: '20000000-0000-0000-0000-000000000002',
  name: 'Beta Support',
  created_at: '2026-09-15T00:01:00Z',
}

function renderWorkspaces() {
  return render(
    <WorkspaceProvider>
      <WorkspacePage />
    </WorkspaceProvider>,
  )
}

describe('workspace state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mocks.useAuth.mockReturnValue({ user: { id: USER_ID } })
    mocks.getSupabaseClient.mockReturnValue({
      from: () => ({
        select: () => ({ order: mocks.order }),
      }),
      rpc: mocks.rpc,
    })
    mocks.order.mockResolvedValue({ data: [], error: null })
  })

  it('shows onboarding when the user has no accessible workspace', async () => {
    renderWorkspaces()

    expect(
      await screen.findByRole('heading', { name: /create your first workspace/i }),
    ).toBeInTheDocument()
  })

  it('creates a workspace through the RPC and selects the refreshed record', async () => {
    const user = userEvent.setup()
    mocks.order
      .mockResolvedValueOnce({ data: [], error: null })
      .mockResolvedValueOnce({ data: [WORKSPACE_A], error: null })
    mocks.rpc.mockResolvedValue({ data: [WORKSPACE_A], error: null })
    renderWorkspaces()

    await user.type(await screen.findByLabelText(/workspace name/i), 'Alpha Support')
    await user.click(screen.getByRole('button', { name: /create workspace/i }))

    expect(await screen.findByRole('heading', { name: 'Alpha Support' })).toBeInTheDocument()
    expect(mocks.rpc).toHaveBeenCalledWith('create_workspace', {
      workspace_name: 'Alpha Support',
    })
    expect(localStorage.getItem(`supportpilot:selected-workspace:${USER_ID}`)).toBe(
      WORKSPACE_A.id,
    )
  })

  it('loads and automatically selects a single accessible workspace', async () => {
    mocks.order.mockResolvedValue({ data: [WORKSPACE_A], error: null })
    renderWorkspaces()

    expect(await screen.findByRole('heading', { name: 'Alpha Support' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/current workspace/i)).not.toBeInTheDocument()
  })

  it('allows selection among multiple accessible workspaces', async () => {
    const user = userEvent.setup()
    mocks.order.mockResolvedValue({ data: [WORKSPACE_A, WORKSPACE_B], error: null })
    renderWorkspaces()

    const selector = await screen.findByLabelText(/current workspace/i)
    expect(selector).toHaveValue(WORKSPACE_A.id)
    await user.selectOptions(selector, WORKSPACE_B.id)

    expect(selector).toHaveValue(WORKSPACE_B.id)
    expect(screen.getByRole('heading', { name: 'Beta Support' })).toBeInTheDocument()
  })

  it('discards a stale locally stored workspace id', async () => {
    const staleId = '20000000-0000-0000-0000-000000000099'
    const storageKey = `supportpilot:selected-workspace:${USER_ID}`
    localStorage.setItem(storageKey, staleId)
    mocks.order.mockResolvedValue({ data: [WORKSPACE_A, WORKSPACE_B], error: null })
    renderWorkspaces()

    expect(await screen.findByLabelText(/current workspace/i)).toHaveValue(WORKSPACE_A.id)
    expect(localStorage.getItem(storageKey)).toBe(WORKSPACE_A.id)
    expect(screen.queryByDisplayValue(staleId)).not.toBeInTheDocument()
  })
})
