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
}

export interface ValidatedKnowledgeFile {
  mimeType: string
  title: string
}
