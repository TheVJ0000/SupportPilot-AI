import { apiBaseUrl } from '../api/health'

export interface KnowledgeProcessingResult {
  sourceId: string
  status: 'pending'
  chunkCount: number
  extractedCharCount: number
  nextStage: 'embedding'
}

export class KnowledgeProcessingError extends Error {
  constructor(message = 'The source could not be processed safely. Please try again.') {
    super(message)
    this.name = 'KnowledgeProcessingError'
  }
}

export async function processKnowledgeSource(
  accessToken: string,
  sourceId: string,
): Promise<KnowledgeProcessingResult> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/knowledge/${encodeURIComponent(sourceId)}/process`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
    })
  } catch {
    throw new KnowledgeProcessingError()
  }

  if (!response.ok) {
    throw new KnowledgeProcessingError(
      response.status === 409
        ? 'This source is already processing or cannot be processed yet.'
        : undefined,
    )
  }

  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new KnowledgeProcessingError()
  }
  if (
    typeof data !== 'object' ||
    data === null ||
    !('source_id' in data) ||
    data.source_id !== sourceId ||
    !('status' in data) ||
    data.status !== 'pending' ||
    !('chunk_count' in data) ||
    typeof data.chunk_count !== 'number' ||
    !Number.isInteger(data.chunk_count) ||
    data.chunk_count < 1 ||
    !('extracted_char_count' in data) ||
    typeof data.extracted_char_count !== 'number' ||
    !Number.isInteger(data.extracted_char_count) ||
    data.extracted_char_count < 1 ||
    !('next_stage' in data) ||
    data.next_stage !== 'embedding'
  ) {
    throw new KnowledgeProcessingError()
  }

  return {
    sourceId: data.source_id,
    status: data.status,
    chunkCount: data.chunk_count,
    extractedCharCount: data.extracted_char_count,
    nextStage: data.next_stage,
  }
}
