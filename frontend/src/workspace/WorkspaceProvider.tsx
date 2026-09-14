import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { getSupabaseClient } from '../lib/supabase'
import { WorkspaceContext, type Workspace, type WorkspaceRole } from './WorkspaceContext'

const STORAGE_PREFIX = 'supportpilot:selected-workspace:'

interface WorkspaceRecord {
  id: string
  name: string
  created_at: string
  workspace_members: Array<{ role: WorkspaceRole }>
}

function isWorkspaceRole(value: unknown): value is WorkspaceRole {
  return value === 'owner' || value === 'admin' || value === 'member'
}

function isWorkspaceRecord(value: unknown): value is WorkspaceRecord {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof value.id === 'string' &&
    'name' in value &&
    typeof value.name === 'string' &&
    'created_at' in value &&
    typeof value.created_at === 'string' &&
    'workspace_members' in value &&
    Array.isArray(value.workspace_members) &&
    value.workspace_members.length === 1 &&
    typeof value.workspace_members[0] === 'object' &&
    value.workspace_members[0] !== null &&
    'role' in value.workspace_members[0] &&
    isWorkspaceRole(value.workspace_members[0].role)
  )
}

function toWorkspace(record: WorkspaceRecord): Workspace {
  return {
    id: record.id,
    name: record.name,
    created_at: record.created_at,
    role: record.workspace_members[0].role,
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const applyWorkspaceList = useCallback(
    (nextWorkspaces: Workspace[], preferredId?: string) => {
      if (!user) return
      const storageKey = `${STORAGE_PREFIX}${user.id}`
      const savedId = localStorage.getItem(storageKey)
      const savedIsValid = nextWorkspaces.some((workspace) => workspace.id === savedId)
      if (savedId && !savedIsValid) localStorage.removeItem(storageKey)

      setWorkspaces(nextWorkspaces)
      setSelectedWorkspace((current) => {
        const next =
          nextWorkspaces.find((workspace) => workspace.id === preferredId) ??
          nextWorkspaces.find((workspace) => workspace.id === savedId) ??
          nextWorkspaces.find((workspace) => workspace.id === current?.id) ??
          nextWorkspaces[0] ??
          null

        if (next) localStorage.setItem(storageKey, next.id)
        else localStorage.removeItem(storageKey)
        return next
      })
    },
    [user],
  )

  const loadWorkspaces = useCallback(
    async (preferredId?: string) => {
      if (!user) {
        setWorkspaces([])
        setSelectedWorkspace(null)
        setLoading(false)
        return
      }

      setLoading(true)
      setError(null)
      try {
        const { data, error: queryError } = await getSupabaseClient()
          .from('workspaces')
          .select('id,name,created_at,workspace_members!inner(role)')
          .order('created_at', { ascending: true })

        if (queryError) throw queryError
        if (!Array.isArray(data) || !data.every(isWorkspaceRecord)) {
          throw new Error('Invalid response')
        }
        applyWorkspaceList(data.map(toWorkspace), preferredId)
      } catch {
        setError('We could not load your workspaces. Please try again.')
      } finally {
        setLoading(false)
      }
    },
    [applyWorkspaceList, user],
  )

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void loadWorkspaces(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadWorkspaces])

  const createWorkspace = useCallback(
    async (name: string) => {
      const normalizedName = name.trim().replace(/\s+/g, ' ')
      setError(null)

      try {
        const { data, error: rpcError } = await getSupabaseClient().rpc('create_workspace', {
          workspace_name: normalizedName,
        })
        if (rpcError) throw rpcError

        const created = Array.isArray(data) ? data[0] : data
        if (
          typeof created !== 'object' ||
          created === null ||
          !('id' in created) ||
          typeof created.id !== 'string'
        ) {
          throw new Error('Invalid response')
        }
        await loadWorkspaces(created.id)
      } catch {
        setError('We could not create your workspace. Please try again.')
        throw new Error('Workspace creation failed')
      }
    },
    [loadWorkspaces],
  )

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      if (!user) return
      const workspace = workspaces.find((candidate) => candidate.id === workspaceId)
      if (!workspace) return
      localStorage.setItem(`${STORAGE_PREFIX}${user.id}`, workspace.id)
      setSelectedWorkspace(workspace)
    },
    [user, workspaces],
  )

  const value = useMemo(
    () => ({
      workspaces,
      selectedWorkspace,
      loading,
      error,
      refreshWorkspaces: () => loadWorkspaces(),
      createWorkspace,
      selectWorkspace,
    }),
    [createWorkspace, error, loadWorkspaces, loading, selectWorkspace, selectedWorkspace, workspaces],
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}
