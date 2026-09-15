import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/useAuth'
import {
  createFaqKnowledgeSource,
  listKnowledgeSources,
  recoverFileKnowledgeSource,
  uploadKnowledgeFile,
} from './knowledgeApi'
import type { KnowledgeSource } from './types'
import { KnowledgeProcessingError, processKnowledgeSource } from './processingApi'
import { indexKnowledgeSource, KnowledgeIndexingError } from './indexingApi'

export function useKnowledgeSources(workspaceId: string) {
  const { accessToken } = useAuth()
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
        try {
          await uploadKnowledgeFile(workspaceId, file)
        } catch (error) {
          await refresh()
          throw error
        }
        await refresh()
      },
      addFaq: async (question: string, answer: string) => {
        await createFaqKnowledgeSource(workspaceId, question, answer)
        await refresh()
      },
      recoverUpload: async (sourceId: string) => {
        const result = await recoverFileKnowledgeSource(sourceId)
        await refresh()
        return result
      },
      processSource: async (sourceId: string) => {
        if (!accessToken) throw new KnowledgeProcessingError('Your session is no longer active.')
        try {
          const result = await processKnowledgeSource(accessToken, sourceId)
          await refresh()
          return result
        } catch (error) {
          await refresh()
          throw error
        }
      },
      indexSource: async (sourceId: string) => {
        if (!accessToken) throw new KnowledgeIndexingError('Your session is no longer active.')
        try {
          const result = await indexKnowledgeSource(accessToken, sourceId)
          await refresh()
          return result
        } catch (error) {
          await refresh()
          throw error
        }
      },
    }),
    [accessToken, error, loading, refresh, sources, workspaceId],
  )
}
