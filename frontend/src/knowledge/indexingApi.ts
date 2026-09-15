import { apiBaseUrl } from '../api/health'

export interface KnowledgeIndexingResult {
  sourceId: string
  status: 'ready'
  chunkCount: number
  embeddingProvider: string
  embeddingModel: string
  embeddingDimension: 768
}

export class KnowledgeIndexingError extends Error {
  constructor(message = 'The source could not be indexed safely. Please try again.') {
    super(message)
    this.name = 'KnowledgeIndexingError'
  }
}

export async function indexKnowledgeSource(
  accessToken: string,
  sourceId: string,
): Promise<KnowledgeIndexingResult> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/knowledge/${encodeURIComponent(sourceId)}/index`, {
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
    })
  } catch {
    throw new KnowledgeIndexingError()
  }

  if (!response.ok) {
    throw new KnowledgeIndexingError(
      response.status === 503
        ? 'AI indexing is not configured yet or is temporarily unavailable.'
        : response.status === 409
          ? 'This source is already indexing or cannot be indexed yet.'
          : undefined,
    )
  }

  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new KnowledgeIndexingError()
  }
  if (
    typeof data !== 'object' || data === null ||
    !('source_id' in data) || data.source_id !== sourceId ||
    !('status' in data) || data.status !== 'ready' ||
    !('chunk_count' in data) || typeof data.chunk_count !== 'number' ||
    !Number.isInteger(data.chunk_count) || data.chunk_count < 1 ||
    !('embedding_provider' in data) || typeof data.embedding_provider !== 'string' ||
    !('embedding_model' in data) || typeof data.embedding_model !== 'string' ||
    !('embedding_dimension' in data) || data.embedding_dimension !== 768
  ) {
    throw new KnowledgeIndexingError()
  }
  return {
    sourceId: data.source_id,
    status: data.status,
    chunkCount: data.chunk_count,
    embeddingProvider: data.embedding_provider,
    embeddingModel: data.embedding_model,
    embeddingDimension: data.embedding_dimension,
  }
}
