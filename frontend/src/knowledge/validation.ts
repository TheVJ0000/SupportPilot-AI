import { MAX_KNOWLEDGE_FILE_BYTES, type ValidatedKnowledgeFile } from './types'

const MIME_TYPES_BY_EXTENSION: Record<string, readonly string[]> = {
  pdf: ['application/pdf'],
  docx: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  txt: ['text/plain'],
  md: ['text/markdown', 'text/plain'],
}

export class KnowledgeValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'KnowledgeValidationError'
  }
}

export function validateKnowledgeFile(file: File): ValidatedKnowledgeFile {
  const filename = file.name.trim()
  if (!filename || filename.includes('/') || filename.includes('\\') || filename.includes('..')) {
    throw new KnowledgeValidationError('Choose a file with a valid filename.')
  }

  if (file.size < 1) {
    throw new KnowledgeValidationError('The selected file is empty.')
  }
  if (file.size > MAX_KNOWLEDGE_FILE_BYTES) {
    throw new KnowledgeValidationError('Files must be 10 MB or smaller.')
  }

  const extension = filename.split('.').pop()?.toLowerCase() ?? ''
  const allowedMimeTypes = MIME_TYPES_BY_EXTENSION[extension]
  if (!allowedMimeTypes) {
    throw new KnowledgeValidationError('Choose a PDF, DOCX, TXT, or MD file.')
  }

  const reportedMimeType = file.type.trim().toLowerCase()
  const mimeType =
    reportedMimeType || (extension === 'md' ? 'text/markdown' : extension === 'txt' ? 'text/plain' : '')
  if (!allowedMimeTypes.includes(mimeType)) {
    throw new KnowledgeValidationError('The file type does not match its extension.')
  }

  const title = filename.slice(0, -(extension.length + 1)).trim().replace(/\s+/g, ' ')
  return {
    mimeType,
    title: title.length >= 2 ? title.slice(0, 200) : 'Uploaded document',
  }
}
