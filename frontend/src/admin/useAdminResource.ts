import { useEffect, useState } from 'react'
import { useAuth } from '../auth/useAuth'
import { useWorkspace } from '../workspace/useWorkspace'
import { AdminApiError } from './adminApi'

export function useAdminResource<T>(
  requestKey: string,
  load: (id: string, token: string, signal: AbortSignal) => Promise<T>,
) {
  const { accessToken, user } = useAuth()
  const { selectedWorkspace } = useWorkspace()
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<{ key: string; data?: T; error?: string } | null>(null)
  const id = selectedWorkspace?.id ?? ''
  const key = `${user?.id}:${accessToken}:${id}:${requestKey}:${revision}`
  useEffect(() => {
    if (!id || !accessToken) return
    const controller = new AbortController()
    let active = true
    void load(id, accessToken, controller.signal)
      .then((data) => {
        if (active && !controller.signal.aborted) setResult({ key, data })
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted)
          setResult({
            key,
            error:
              error instanceof AdminApiError
                ? error.message
                : 'Support operations could not be loaded. Please try again.',
          })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [id, accessToken, key, load])
  // The key check hides old data synchronously, before effects can run on a workspace/filter change.
  return {
    data: result?.key === key ? result.data : undefined,
    error: result?.key === key ? result.error : undefined,
    loading: result?.key !== key,
    retry: () => setRevision((value) => value + 1),
  }
}
