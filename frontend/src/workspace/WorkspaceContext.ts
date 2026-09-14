import { createContext } from 'react'

export interface Workspace {
  id: string
  name: string
  created_at: string
  role: WorkspaceRole
}

export type WorkspaceRole = 'owner' | 'admin' | 'member'

export interface WorkspaceContextValue {
  workspaces: Workspace[]
  selectedWorkspace: Workspace | null
  loading: boolean
  error: string | null
  refreshWorkspaces: () => Promise<void>
  createWorkspace: (name: string) => Promise<void>
  selectWorkspace: (workspaceId: string) => void
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)
