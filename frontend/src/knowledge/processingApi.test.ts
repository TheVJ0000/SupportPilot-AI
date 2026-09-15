import { afterEach, describe, expect, it, vi } from 'vitest'
import { KnowledgeProcessingError, processKnowledgeSource } from './processingApi'

const SOURCE_ID = '30000000-0000-0000-0000-000000000001'

describe('knowledge processing API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts only the source path parameter with the active bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        source_id: SOURCE_ID,
        status: 'pending',
        chunk_count: 3,
        extracted_char_count: 4200,
        next_stage: 'embedding',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(processKnowledgeSource('test-access-token', SOURCE_ID)).resolves.toEqual({
      sourceId: SOURCE_ID,
      status: 'pending',
      chunkCount: 3,
      extractedCharCount: 4200,
      nextStage: 'embedding',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/knowledge/${SOURCE_ID}/process`,
      {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          Authorization: 'Bearer test-access-token',
        },
      },
    )
  })

  it('does not expose a raw backend or parser response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'raw parser secret path' }),
      }),
    )

    const result = processKnowledgeSource('test-access-token', SOURCE_ID)
    await expect(result).rejects.toBeInstanceOf(KnowledgeProcessingError)
    await expect(result).rejects.not.toThrow(/raw parser|secret path/i)
  })

  it('rejects malformed success responses safely', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'ready' }) }),
    )

    await expect(processKnowledgeSource('test-access-token', SOURCE_ID)).rejects.toThrow(
      /could not be processed safely/i,
    )
  })
})
