import { afterEach, describe, expect, it, vi } from 'vitest'
import { indexKnowledgeSource, KnowledgeIndexingError } from './indexingApi'

const SOURCE_ID = '30000000-0000-0000-0000-000000000001'

describe('knowledge indexing API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts only the source path with the active bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        source_id: SOURCE_ID,
        status: 'ready',
        chunk_count: 2,
        embedding_provider: 'gemini',
        embedding_model: 'gemini-embedding-2',
        embedding_dimension: 768,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(indexKnowledgeSource('test-access-token', SOURCE_ID)).resolves.toMatchObject({
      sourceId: SOURCE_ID,
      status: 'ready',
      chunkCount: 2,
      embeddingDimension: 768,
    })
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/knowledge/${SOURCE_ID}/index`,
      {
        method: 'POST',
        headers: { Accept: 'application/json', Authorization: 'Bearer test-access-token' },
      },
    )
  })

  it('maps missing configuration without exposing backend details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))

    const result = indexKnowledgeSource('test-access-token', SOURCE_ID)
    await expect(result).rejects.toBeInstanceOf(KnowledgeIndexingError)
    await expect(result).rejects.toThrow(/not configured|temporarily unavailable/i)
  })

  it('rejects malformed successful responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ vectors: [] }) }),
    )
    await expect(indexKnowledgeSource('test-access-token', SOURCE_ID)).rejects.toThrow(
      /could not be indexed safely/i,
    )
  })
})
