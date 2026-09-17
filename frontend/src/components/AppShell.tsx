import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  getAuthenticatedIdentity,
  AuthenticatedApiError,
  type AuthenticatedApiStatus,
} from '../api/client'
import { useAuth } from '../auth/useAuth'
import { Brand } from './Brand'
import { useWorkspace } from '../workspace/useWorkspace'

function ApiStatus({ status }: { status: AuthenticatedApiStatus | 'checking' }) {
  const labels = {
    checking: 'Checking authenticated API',
    connected: 'Authenticated API connected',
    rejected: 'Authenticated API rejected the session',
    unavailable: 'Authenticated API unavailable',
  }
  const colors = {
    checking: 'bg-amber-300',
    connected: 'bg-emerald-300',
    rejected: 'bg-rose-300',
    unavailable: 'bg-slate-400',
  }
  return (
    <div aria-live="polite" className="flex items-center gap-2 text-xs text-slate-400">
      <span
        className={`size-2 rounded-full ${colors[status]} ${status === 'checking' ? 'animate-pulse' : ''}`}
      />
      {labels[status]}
    </div>
  )
}

export function AppShell() {
  const { accessToken, user, signOut } = useAuth()
  const {
    selectedWorkspace,
    workspaces,
    selectWorkspace,
    loading: workspaceLoading,
  } = useWorkspace()
  const canViewOperations =
    !workspaceLoading && !!selectedWorkspace && selectedWorkspace.role !== 'member'
  const navigate = useNavigate()
  const [apiStatus, setApiStatus] = useState<AuthenticatedApiStatus | 'checking'>('checking')
  const [signOutError, setSignOutError] = useState<string | null>(null)

  useEffect(() => {
    if (!accessToken) return
    const controller = new AbortController()
    void getAuthenticatedIdentity(accessToken, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setApiStatus('connected')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setApiStatus(error instanceof AuthenticatedApiError ? error.status : 'unavailable')
      })
    return () => controller.abort()
  }, [accessToken])

  async function handleSignOut() {
    setSignOutError(null)
    try {
      await signOut()
      navigate('/login', { replace: true })
    } catch {
      setSignOutError('Unable to sign out. Please try again.')
    }
  }

  const displayName =
    typeof user?.user_metadata.display_name === 'string'
      ? user.user_metadata.display_name
      : (user?.email ?? 'Signed-in user')

  return (
    <main className="min-h-screen bg-[#07111f] text-white">
      <header className="border-b border-white/10 bg-slate-950/30 px-5 py-4 backdrop-blur-xl sm:px-8">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <Brand compact />
          <div className="flex items-center gap-4">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-semibold">{displayName}</p>
              <p className="text-xs text-slate-500">{user?.email}</p>
            </div>
            <button
              className="rounded-xl border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300 hover:bg-white/5 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
              onClick={() => void handleSignOut()}
              type="button"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <div className="mb-9 flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
          <nav aria-label="Application" className="flex flex-wrap items-center gap-2">
            {[
              ...(canViewOperations
                ? [
                    { label: 'Dashboard', to: '/app/dashboard' },
                    { label: 'Conversations', to: '/app/conversations' },
                    { label: 'Escalations', to: '/app/escalations' },
                  ]
                : []),
              { label: 'Knowledge Base', to: '/app/knowledge' },
              ...(canViewOperations ? [{ label: 'Widget', to: '/app/widget' }] : []),
              { label: 'Workspace', to: '/app/workspaces' },
            ].map((item) => (
              <NavLink
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm font-semibold transition ${
                    isActive
                      ? 'bg-cyan-300/10 text-cyan-200'
                      : 'text-slate-400 hover:bg-white/5 hover:text-white'
                  }`
                }
                key={item.to}
                to={item.to}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <ApiStatus status={apiStatus} />
        </div>
        {workspaces.length > 0 && (
          <label className="mb-7 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            Active workspace
            <select
              aria-label="Active workspace"
              disabled={workspaceLoading}
              value={selectedWorkspace?.id ?? ''}
              onChange={(event) => selectWorkspace(event.target.value)}
              className="max-w-full rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-sm text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              {!selectedWorkspace && <option value="">Select a workspace</option>}
              {workspaces.map((workspace) => (
                <option value={workspace.id} key={workspace.id}>
                  {workspace.name} ({workspace.role})
                </option>
              ))}
            </select>
          </label>
        )}
        {signOutError && (
          <p aria-live="assertive" className="mb-5 text-sm text-rose-300">
            {signOutError}
          </p>
        )}
        <Outlet />
      </div>
    </main>
  )
}
