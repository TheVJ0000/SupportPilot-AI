import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useKnowledgeSources } from './useKnowledgeSources'

const mocks = vi.hoisted(() => ({
  accessToken: 'test-access-token',
  createFaqKnowledgeSource: vi.fn(),
  listKnowledgeSources: vi.fn(),
  recoverFileKnowledgeSource: vi.fn(),
  uploadKnowledgeFile: vi.fn(),
  processKnowledgeSource: vi.fn(),
  indexKnowledgeSource: vi.fn(),
}))

vi.mock('./knowledgeApi', () => mocks)
vi.mock('./processingApi', () => ({
  KnowledgeProcessingError: class extends Error {},
  processKnowledgeSource: mocks.processKnowledgeSource,
}))
vi.mock('./indexingApi', () => ({
  KnowledgeIndexingError: class extends Error {},
  indexKnowledgeSource: mocks.indexKnowledgeSource,
}))
vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({ accessToken: mocks.accessToken }),
}))

const WORKSPACE_ID = '20000000-0000-0000-0000-000000000001'
const SOURCE_ID = '30000000-0000-0000-0000-000000000001'

describe('useKnowledgeSources', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listKnowledgeSources.mockResolvedValue([])
  })

  it('refreshes the source list after recovering an upload', async () => {
    const uploadingSource = {
      id: SOURCE_ID,
      title: 'Interrupted upload',
      source_type: 'file' as const,
      status: 'uploading' as const,
      original_filename: 'guide.pdf',
      created_at: '2026-09-15T00:00:00Z',
    }
    const pendingSource = { ...uploadingSource, status: 'pending' as const }
    mocks.listKnowledgeSources
      .mockResolvedValueOnce([uploadingSource])
      .mockResolvedValueOnce([pendingSource])
    mocks.recoverFileKnowledgeSource.mockResolvedValue({
      sourceId: SOURCE_ID,
      action: 'finalized',
      status: 'pending',
    })

    const { result } = renderHook(() => useKnowledgeSources(WORKSPACE_ID))
    await waitFor(() => expect(result.current.sources).toEqual([uploadingSource]))

    await act(async () => {
      await result.current.recoverUpload(SOURCE_ID)
    })

    expect(mocks.recoverFileKnowledgeSource).toHaveBeenCalledWith(SOURCE_ID)
    expect(mocks.listKnowledgeSources).toHaveBeenCalledTimes(2)
    expect(result.current.sources).toEqual([pendingSource])
  })

  it('uses the active token and refreshes source state after processing', async () => {
    mocks.processKnowledgeSource.mockResolvedValue({
      sourceId: SOURCE_ID,
      status: 'pending',
      chunkCount: 2,
      extractedCharCount: 2400,
      nextStage: 'embedding',
    })
    const { result } = renderHook(() => useKnowledgeSources(WORKSPACE_ID))
    await waitFor(() => expect(mocks.listKnowledgeSources).toHaveBeenCalledTimes(1))

    await act(async () => {
      await result.current.processSource(SOURCE_ID)
    })

    expect(mocks.processKnowledgeSource).toHaveBeenCalledWith('test-access-token', SOURCE_ID)
    expect(mocks.listKnowledgeSources).toHaveBeenCalledTimes(2)
  })

  it('uses the active token and refreshes after indexing succeeds', async () => {
    mocks.indexKnowledgeSource.mockResolvedValue({
      sourceId: SOURCE_ID,
      status: 'ready',
      chunkCount: 1,
      embeddingProvider: 'gemini',
      embeddingModel: 'gemini-embedding-2',
      embeddingDimension: 768,
    })
    const { result } = renderHook(() => useKnowledgeSources(WORKSPACE_ID))
    await waitFor(() => expect(mocks.listKnowledgeSources).toHaveBeenCalledTimes(1))

    await act(async () => {
      await result.current.indexSource(SOURCE_ID)
    })

    expect(mocks.indexKnowledgeSource).toHaveBeenCalledWith('test-access-token', SOURCE_ID)
    expect(mocks.listKnowledgeSources).toHaveBeenCalledTimes(2)
  })
})
