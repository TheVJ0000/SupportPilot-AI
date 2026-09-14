import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Session, User } from '@supabase/supabase-js'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './App'
import { AuthProvider } from './auth/AuthProvider'

const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  order: vi.fn(),
  rpc: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
  unsubscribe: vi.fn(),
}))

vi.mock('./lib/supabase', () => ({
  SupabaseConfigurationError: class SupabaseConfigurationError extends Error {},
  getSupabaseClient: () => ({
    auth: {
      getSession: mocks.getSession,
      onAuthStateChange: mocks.onAuthStateChange,
      signInWithPassword: mocks.signInWithPassword,
      signOut: mocks.signOut,
      signUp: mocks.signUp,
    },
    from: () => ({
      select: () => ({ order: mocks.order }),
    }),
    rpc: mocks.rpc,
  }),
}))

const TEST_USER_ID = '10000000-0000-0000-0000-000000000001'

function makeUser(): User {
  return {
    id: TEST_USER_ID,
    email: 'owner@example.test',
    user_metadata: { display_name: 'Test Owner' },
  } as unknown as User
}

function makeSession(): Session {
  return {
    access_token: 'test-session-value',
    user: makeUser(),
  } as unknown as Session
}

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('authentication routes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mocks.getSession.mockResolvedValue({ data: { session: null }, error: null })
    mocks.onAuthStateChange.mockReturnValue({
      data: { subscription: { unsubscribe: mocks.unsubscribe } },
    })
    mocks.order.mockResolvedValue({ data: [], error: null })
    mocks.signOut.mockResolvedValue({ error: null })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          service: 'supportpilot-api',
          user_id: TEST_USER_ID,
          email: 'owner@example.test',
        }),
      }),
    )
  })

  it('shows login and registration paths to an unauthenticated visitor', () => {
    renderRoute('/')

    expect(screen.getAllByRole('link', { name: /log in/i }).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /create an account/i })).toHaveAttribute(
      'href',
      '/register',
    )
  })

  it('does not expose a protected route without a restored session', async () => {
    renderRoute('/app/workspaces')

    expect(screen.getByText(/restoring your session/i)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    expect(screen.queryByText(/authenticated workspace/i)).not.toBeInTheDocument()
  })

  it('moves a successful login into workspace onboarding', async () => {
    const user = userEvent.setup()
    const session = makeSession()
    mocks.signInWithPassword.mockResolvedValue({
      data: { session, user: session.user },
      error: null,
    })
    renderRoute('/login')

    await user.type(await screen.findByLabelText(/^email$/i), 'owner@example.test')
    await user.type(screen.getByLabelText(/^password$/i), 'a-secure-password')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(
      await screen.findByRole('heading', { name: /create your first workspace/i }),
    ).toBeInTheDocument()
    expect(mocks.signInWithPassword).toHaveBeenCalledWith({
      email: 'owner@example.test',
      password: 'a-secure-password',
    })
  })

  it('shows a safe message after failed login', async () => {
    const user = userEvent.setup()
    mocks.signInWithPassword.mockResolvedValue({
      data: { session: null, user: null },
      error: { message: 'provider-specific details' },
    })
    renderRoute('/login')

    await user.type(await screen.findByLabelText(/^email$/i), 'owner@example.test')
    await user.type(screen.getByLabelText(/^password$/i), 'incorrect-password')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(
      await screen.findByText(/unable to sign in\. check your email and password/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/provider-specific details/i)).not.toBeInTheDocument()
  })

  it('handles registration when email confirmation is required', async () => {
    const user = userEvent.setup()
    mocks.signUp.mockResolvedValue({
      data: { session: null, user: makeUser() },
      error: null,
    })
    renderRoute('/register')

    await user.type(await screen.findByLabelText(/display name/i), 'Test Owner')
    await user.type(screen.getByLabelText(/^email$/i), 'owner@example.test')
    await user.type(screen.getByLabelText(/^password$/i), 'a-secure-password')
    await user.type(screen.getByLabelText(/confirm password/i), 'a-secure-password')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('heading', { name: /check your email/i })).toBeInTheDocument()
    expect(mocks.signUp).toHaveBeenCalledWith({
      email: 'owner@example.test',
      password: 'a-secure-password',
      options: { data: { display_name: 'Test Owner' } },
    })
  })

  it('returns to the login screen after logout', async () => {
    const user = userEvent.setup()
    mocks.getSession.mockResolvedValue({ data: { session: makeSession() }, error: null })
    mocks.order.mockResolvedValue({
      data: [
        {
          id: '20000000-0000-0000-0000-000000000001',
          name: 'Example Workspace',
          created_at: '2026-09-15T00:00:00Z',
        },
      ],
      error: null,
    })
    renderRoute('/app/workspaces')

    await user.click(await screen.findByRole('button', { name: /log out/i }))

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    expect(screen.queryByText('Example Workspace')).not.toBeInTheDocument()
    expect(mocks.signOut).toHaveBeenCalledOnce()
  })
})
