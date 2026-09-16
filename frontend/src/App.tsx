import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { PublicOnlyRoute } from './auth/PublicOnlyRoute'
import { AppShell } from './components/AppShell'
import { LandingPage } from './pages/LandingPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { CustomerChatPage } from './pages/CustomerChatPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { WorkspaceProvider } from './workspace/WorkspaceProvider'
import { AppLanding, OperationsGuard } from './admin/OperationsGuard'
import { DashboardPage } from './admin/DashboardPage'
import { ConversationsPage } from './admin/ConversationsPage'
import { ConversationDetailPage } from './admin/ConversationDetailPage'
import { EscalationsPage } from './admin/EscalationsPage'
import { EscalationDetailPage } from './admin/EscalationDetailPage'

function AuthenticatedApplication() {
  return (
    <WorkspaceProvider>
      <AppShell />
    </WorkspaceProvider>
  )
}

function BusinessAuthBoundary() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/chat/:publicId" element={<CustomerChatPage />} />
      <Route element={<BusinessAuthBoundary />}>
        <Route element={<PublicOnlyRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route path="/app" element={<AuthenticatedApplication />}>
            <Route index element={<AppLanding />} />
            <Route path="workspaces" element={<WorkspacePage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route element={<OperationsGuard />}>
              <Route path="dashboard" element={<DashboardPage />} />
              <Route path="conversations" element={<ConversationsPage />} />
              <Route path="conversations/:conversationId" element={<ConversationDetailPage />} />
              <Route path="escalations" element={<EscalationsPage />} />
              <Route path="escalations/:escalationId" element={<EscalationDetailPage />} />
            </Route>
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
