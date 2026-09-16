import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { useWorkspace } from '../workspace/useWorkspace'

export function OperationsGuard() {
  const { selectedWorkspace, loading, error } = useWorkspace()
  const { user, accessToken, loading: authLoading } = useAuth()
  if (loading || authLoading) return <p role="status">Loading workspace…</p>
  if (error) return <p role="alert">Unable to load your workspace. Visit Workspace to try again.</p>
  if (!selectedWorkspace) return <Navigate to="/app/workspaces" replace />
  if (selectedWorkspace.role === 'member') return <Navigate to="/app/knowledge" replace />
  // Remount even when only the role or authenticated identity changes. Never retain a tenant's transcript.
  return (
    <div key={`${user?.id}:${accessToken}:${selectedWorkspace.id}:${selectedWorkspace.role}`}>
      <Outlet />
    </div>
  )
}

export function AppLanding() {
  const { selectedWorkspace, loading, error } = useWorkspace()
  if (loading) return <p role="status">Loading workspace…</p>
  if (error || !selectedWorkspace) return <Navigate to="/app/workspaces" replace />
  return (
    <Navigate
      to={selectedWorkspace.role === 'member' ? '/app/knowledge' : '/app/dashboard'}
      replace
    />
  )
}
