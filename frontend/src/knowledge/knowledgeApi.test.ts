import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createFaqKnowledgeSource,
  listKnowledgeSources,
  uploadKnowledgeFile,
} from './knowledgeApi'
import { MAX_KNOWLEDGE_FILE_BYTES } from './types'

const mocks = vi.hoisted(() => ({
  eq: vi.fn(),
  from: vi.fn(),
  order: vi.fn(),
  remove: vi.fn(),
  rpc: vi.fn(),
  select: vi.fn(),
  storageFrom: vi.fn(),
  upload: vi.fn(),
}))

vi.mock('../lib/supabase', () => ({
  getSupabaseClient: () => ({
    from: mocks.from,
    rpc: mocks.rpc,
    storage: { from: mocks.storageFrom },
  }),
}))

const WORKSPACE_ID = '20000000-0000-0000-0000-000000000001'
const SOURCE_ID = '30000000-0000-0000-0000-000000000001'
const STORAGE_PATH = `${WORKSPACE_ID}/${SOURCE_ID}/${SOURCE_ID}.pdf`

describe('knowledge source operations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.from.mockReturnValue({ select: mocks.select })
    mocks.select.mockReturnValue({ eq: mocks.eq })
    mocks.eq.mockReturnValue({ order: mocks.order })
    mocks.order.mockResolvedValue({ data: [], error: null })
    mocks.storageFrom.mockReturnValue({ upload: mocks.upload, remove: mocks.remove })
    mocks.upload.mockResolvedValue({ data: { path: STORAGE_PATH }, error: null })
    mocks.remove.mockResolvedValue({ data: [], error: null })
    mocks.rpc.mockImplementation((name: string) => {
      if (name === 'begin_file_knowledge_source') {
        return Promise.resolve({
          data: [{ source_id: SOURCE_ID, storage_path: STORAGE_PATH }],
          error: null,
        })
      }
      return Promise.resolve({ data: true, error: null })
    })
  })

  it('lists only explicit fields for the selected workspace, newest first', async () => {
    const source = {
      id: SOURCE_ID,
      title: 'Support guide',
      source_type: 'file',
      status: 'pending',
      original_filename: 'guide.pdf',
      created_at: '2026-09-15T00:00:00Z',
    }
    mocks.order.mockResolvedValue({ data: [source], error: null })

    await expect(listKnowledgeSources(WORKSPACE_ID)).resolves.toEqual([source])
    expect(mocks.from).toHaveBeenCalledWith('knowledge_sources')
    expect(mocks.select).toHaveBeenCalledWith(
      'id,title,source_type,status,original_filename,created_at',
    )
    expect(mocks.eq).toHaveBeenCalledWith('workspace_id', WORKSPACE_ID)
    expect(mocks.order).toHaveBeenCalledWith('created_at', { ascending: false })
  })

  it('rejects an unsupported extension before initializing an upload', async () => {
    const file = new File(['synthetic'], 'payload.exe', { type: 'application/octet-stream' })

    await expect(uploadKnowledgeFile(WORKSPACE_ID, file)).rejects.toThrow(
      /pdf, docx, txt, or md/i,
    )
    expect(mocks.rpc).not.toHaveBeenCalled()
    expect(mocks.upload).not.toHaveBeenCalled()
  })

  it('rejects a file larger than 10 MB before initializing an upload', async () => {
    const file = new File(['synthetic'], 'large.pdf', { type: 'application/pdf' })
    Object.defineProperty(file, 'size', { value: MAX_KNOWLEDGE_FILE_BYTES + 1 })

    await expect(uploadKnowledgeFile(WORKSPACE_ID, file)).rejects.toThrow(/10 mb or smaller/i)
    expect(mocks.rpc).not.toHaveBeenCalled()
  })

  it('runs begin, private upload with no overwrite, then finalize', async () => {
    const file = new File(['synthetic guide'], 'Support Guide.pdf', {
      type: 'application/pdf',
    })

    await uploadKnowledgeFile(WORKSPACE_ID, file)

    expect(mocks.rpc).toHaveBeenNthCalledWith(1, 'begin_file_knowledge_source', {
      target_workspace_id: WORKSPACE_ID,
      source_title: 'Support Guide',
      file_original_filename: 'Support Guide.pdf',
      file_mime_type: 'application/pdf',
      file_byte_size: file.size,
    })
    expect(mocks.storageFrom).toHaveBeenCalledWith('knowledge-files')
    expect(mocks.upload).toHaveBeenCalledWith(STORAGE_PATH, file, {
      contentType: 'application/pdf',
      upsert: false,
    })
    expect(mocks.rpc).toHaveBeenNthCalledWith(2, 'finalize_file_knowledge_source', {
      target_source_id: SOURCE_ID,
    })
  })

  it('attempts safe cleanup after upload failure without finalizing or claiming ready', async () => {
    const file = new File(['synthetic guide'], 'guide.pdf', { type: 'application/pdf' })
    mocks.upload.mockResolvedValue({ data: null, error: { message: 'private provider detail' } })

    await expect(uploadKnowledgeFile(WORKSPACE_ID, file)).rejects.toThrow(
      /could not be uploaded/i,
    )

    expect(mocks.remove).toHaveBeenCalledWith([STORAGE_PATH])
    expect(mocks.rpc).toHaveBeenCalledWith('cancel_file_knowledge_source', {
      target_source_id: SOURCE_ID,
    })
    expect(mocks.rpc).not.toHaveBeenCalledWith(
      'finalize_file_knowledge_source',
      expect.anything(),
    )
  })

  it('creates an FAQ through the scoped RPC with a derived title', async () => {
    await createFaqKnowledgeSource(
      WORKSPACE_ID,
      'How do I request a refund?',
      'Use the synthetic-demo returns form.',
    )

    expect(mocks.rpc).toHaveBeenCalledWith('create_faq_knowledge_source', {
      target_workspace_id: WORKSPACE_ID,
      source_title: 'How do I request a refund?',
      question: 'How do I request a refund?',
      answer: 'Use the synthetic-demo returns form.',
    })
  })
})
