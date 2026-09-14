import { Navigate, Outlet } from 'react-router-dom'
import { PageLoader } from '../components/PageLoader'
import { useAuth } from './useAuth'

export function PublicOnlyRoute() {
  const { loading, session } = useAuth()

  if (loading) return <PageLoader label="Restoring your session…" />
  if (session) return <Navigate to="/app/workspaces" replace />
  return <Outlet />
}
