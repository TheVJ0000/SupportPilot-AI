import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { PageLoader } from '../components/PageLoader'
import { useAuth } from './useAuth'

export function ProtectedRoute() {
  const { loading, session } = useAuth()
  const location = useLocation()

  if (loading) return <PageLoader label="Restoring your session…" />
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}
