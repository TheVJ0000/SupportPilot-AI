export const KNOWLEDGE_BUCKET = 'knowledge-files'
export const MAX_KNOWLEDGE_FILE_BYTES = 10 * 1024 * 1024

export type KnowledgeSourceType = 'file' | 'faq'
export type KnowledgeSourceStatus = 'uploading' | 'pending' | 'processing' | 'ready' | 'failed'

export interface KnowledgeSource {
  id: string
  title: string
  source_type: KnowledgeSourceType
  status: KnowledgeSourceStatus
  original_filename: string | null
  created_at: string
  processing_started_at: string | null
  processing_attempts: number
  extracted_at: string | null
  extracted_char_count: number | null
  chunk_count: number
  last_error_code: string | null
}

export interface ValidatedKnowledgeFile {
  mimeType: string
  title: string
}
