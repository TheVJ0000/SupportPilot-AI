import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createFaqKnowledgeSource,
  listKnowledgeSources,
  uploadKnowledgeFile,
} from './knowledgeApi'
import type { KnowledgeSource } from './types'

export function useKnowledgeSources(workspaceId: string) {
  const [sources, setSources] = useState<KnowledgeSource[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setSources(await listKnowledgeSources(workspaceId))
    } catch {
      setSources([])
      setError('We could not load this knowledge base. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refresh(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [refresh])

  return useMemo(
    () => ({
      sources,
      loading,
      error,
      refresh,
      uploadFile: async (file: File) => {
        await uploadKnowledgeFile(workspaceId, file)
        await refresh()
      },
      addFaq: async (question: string, answer: string) => {
        await createFaqKnowledgeSource(workspaceId, question, answer)
        await refresh()
      },
    }),
    [error, loading, refresh, sources, workspaceId],
  )
}
