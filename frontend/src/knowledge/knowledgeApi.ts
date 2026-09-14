import { getSupabaseClient } from '../lib/supabase'
import { KNOWLEDGE_BUCKET, type KnowledgeSource, type KnowledgeSourceStatus } from './types'
import { validateKnowledgeFile } from './validation'

const SOURCE_STATUSES: readonly KnowledgeSourceStatus[] = [
  'uploading',
  'pending',
  'processing',
  'ready',
  'failed',
]

export class KnowledgeOperationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'KnowledgeOperationError'
  }
}

export type KnowledgeRecoveryAction = 'finalized' | 'already_pending' | 'removed'

export interface KnowledgeRecoveryResult {
  sourceId: string
  action: KnowledgeRecoveryAction
  status: 'pending' | null
}

function isKnowledgeSource(value: unknown): value is KnowledgeSource {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    typeof value.id === 'string' &&
    'title' in value &&
    typeof value.title === 'string' &&
    'source_type' in value &&
    (value.source_type === 'file' || value.source_type === 'faq') &&
    'status' in value &&
    typeof value.status === 'string' &&
    SOURCE_STATUSES.includes(value.status as KnowledgeSourceStatus) &&
    'original_filename' in value &&
    (value.original_filename === null || typeof value.original_filename === 'string') &&
    'created_at' in value &&
    typeof value.created_at === 'string'
  )
}

function readUploadInitialization(value: unknown): { sourceId: string; storagePath: string } {
  const row = Array.isArray(value) ? value[0] : value
  if (
    typeof row !== 'object' ||
    row === null ||
    !('source_id' in row) ||
    typeof row.source_id !== 'string' ||
    !('storage_path' in row) ||
    typeof row.storage_path !== 'string'
  ) {
    throw new KnowledgeOperationError('The upload could not be initialized. Please try again.')
  }
  return { sourceId: row.source_id, storagePath: row.storage_path }
}

export async function listKnowledgeSources(workspaceId: string): Promise<KnowledgeSource[]> {
  const { data, error } = await getSupabaseClient()
    .from('knowledge_sources')
    .select('id,title,source_type,status,original_filename,created_at')
    .eq('workspace_id', workspaceId)
    .order('created_at', { ascending: false })

  if (error || !Array.isArray(data) || !data.every(isKnowledgeSource)) {
    throw new KnowledgeOperationError('We could not load this knowledge base. Please try again.')
  }
  return data
}

function readRecoveryResult(value: unknown): KnowledgeRecoveryResult {
  const row = Array.isArray(value) ? value[0] : value
  if (
    typeof row !== 'object' ||
    row === null ||
    !('source_id' in row) ||
    typeof row.source_id !== 'string' ||
    !('recovery_action' in row) ||
    (row.recovery_action !== 'finalized' &&
      row.recovery_action !== 'already_pending' &&
      row.recovery_action !== 'removed') ||
    !('source_status' in row) ||
    (row.source_status !== 'pending' && row.source_status !== null)
  ) {
    throw new KnowledgeOperationError('The upload recovery result could not be confirmed.')
  }
  return {
    sourceId: row.source_id,
    action: row.recovery_action,
    status: row.source_status,
  }
}

async function cleanupFailedUpload(sourceId: string, storagePath: string): Promise<boolean> {
  try {
    const removal = await getSupabaseClient().storage.from(KNOWLEDGE_BUCKET).remove([storagePath])
    if (removal.error || !Array.isArray(removal.data)) return false
  } catch {
    return false
  }

  try {
    const cancellation = await getSupabaseClient().rpc('cancel_file_knowledge_source', {
      target_source_id: sourceId,
    })
    return !cancellation.error && cancellation.data === true
  } catch {
    return false
  }
}

export async function recoverFileKnowledgeSource(
  sourceId: string,
): Promise<KnowledgeRecoveryResult> {
  try {
    const { data, error } = await getSupabaseClient().rpc('recover_file_knowledge_source', {
      target_source_id: sourceId,
    })
    if (error) throw new KnowledgeOperationError('The upload could not be recovered safely.')
    const result = readRecoveryResult(data)
    if (result.sourceId !== sourceId) {
      throw new KnowledgeOperationError('The upload recovery result could not be confirmed.')
    }
    return result
  } catch (error) {
    if (error instanceof KnowledgeOperationError) throw error
    throw new KnowledgeOperationError('The upload could not be recovered safely.')
  }
}

export async function uploadKnowledgeFile(workspaceId: string, file: File): Promise<void> {
  const validated = validateKnowledgeFile(file)
  const client = getSupabaseClient()
  const { data, error: beginError } = await client.rpc('begin_file_knowledge_source', {
    target_workspace_id: workspaceId,
    source_title: validated.title,
    file_original_filename: file.name.trim(),
    file_mime_type: validated.mimeType,
    file_byte_size: file.size,
  })

  if (beginError) {
    throw new KnowledgeOperationError('The upload could not be started. Please try again.')
  }

  const { sourceId, storagePath } = readUploadInitialization(data)
  const { error: uploadError } = await client.storage
    .from(KNOWLEDGE_BUCKET)
    .upload(storagePath, file, { contentType: validated.mimeType, upsert: false })

  if (uploadError) {
    const cleanupCompleted = await cleanupFailedUpload(sourceId, storagePath)
    throw new KnowledgeOperationError(
      cleanupCompleted
        ? 'The file could not be uploaded. Please try again.'
        : 'The upload did not complete. Its recovery record was kept; use Recover upload.',
    )
  }

  try {
    const { error: finalizeError } = await client.rpc('finalize_file_knowledge_source', {
      target_source_id: sourceId,
    })
    if (!finalizeError) return
  } catch {
    // A single recovery attempt below reconciles a possibly committed request.
  }

  try {
    const recovery = await recoverFileKnowledgeSource(sourceId)
    if (recovery.action === 'finalized' || recovery.action === 'already_pending') return
  } catch {
    // A safe message below replaces provider/database details.
  }
  throw new KnowledgeOperationError(
    'The file upload could not be confirmed. Use Recover upload before trying again.',
  )
}

export async function createFaqKnowledgeSource(
  workspaceId: string,
  question: string,
  answer: string,
): Promise<void> {
  const normalizedQuestion = question.trim()
  const normalizedAnswer = answer.trim()
  if (normalizedQuestion.length < 5 || normalizedQuestion.length > 1000) {
    throw new KnowledgeOperationError('Question must be between 5 and 1,000 characters.')
  }
  if (normalizedAnswer.length < 1 || normalizedAnswer.length > 20000) {
    throw new KnowledgeOperationError('Answer must be between 1 and 20,000 characters.')
  }

  const { error } = await getSupabaseClient().rpc('create_faq_knowledge_source', {
    target_workspace_id: workspaceId,
    source_title: normalizedQuestion.slice(0, 200),
    question: normalizedQuestion,
    answer: normalizedAnswer,
  })
  if (error) {
    throw new KnowledgeOperationError('The FAQ could not be added. Please try again.')
  }
}
