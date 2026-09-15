import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { KnowledgeProcessingError } from '../knowledge/processingApi'
import { KnowledgePage } from './KnowledgePage'

const mocks = vi.hoisted(() => ({
  addFaq: vi.fn(),
  recoverUpload: vi.fn(),
  processSource: vi.fn(),
  indexSource: vi.fn(),
  refresh: vi.fn(),
  uploadFile: vi.fn(),
  useKnowledgeSources: vi.fn(),
  useWorkspace: vi.fn(),
}))

vi.mock('../knowledge/useKnowledgeSources', () => ({
  useKnowledgeSources: mocks.useKnowledgeSources,
}))
vi.mock('../workspace/useWorkspace', () => ({ useWorkspace: mocks.useWorkspace }))

const WORKSPACE = {
  id: '20000000-0000-0000-0000-000000000001',
  name: 'Example Workspace',
  created_at: '2026-09-15T00:00:00Z',
  role: 'owner',
}

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.useWorkspace.mockReturnValue({ selectedWorkspace: WORKSPACE, loading: false })
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
      indexSource: mocks.indexSource,
    })
  })

  it('shows the knowledge-base empty state', () => {
    render(<KnowledgePage />)

    expect(screen.getByRole('heading', { name: /your knowledge base is empty/i })).toBeInTheDocument()
    expect(
      screen.getByText(/upload support documents or add faqs to build your business knowledge base/i),
    ).toBeInTheDocument()
  })

  it('renders source type, filename, status, and creation date', () => {
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Support Guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'support-guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)

    expect(screen.getByRole('heading', { name: 'Support Guide' })).toBeInTheDocument()
    expect(screen.getByText(/support-guide\.pdf/i)).toBeInTheDocument()
    expect(screen.getByText('file')).toBeInTheDocument()
    expect(screen.getByText('Pending processing')).toBeInTheDocument()
  })

  it('submits a manual FAQ through the knowledge state abstraction', async () => {
    const user = userEvent.setup()
    mocks.addFaq.mockResolvedValue(undefined)
    render(<KnowledgePage />)

    await user.type(screen.getByLabelText(/^question$/i), 'How do refunds work?')
    await user.type(screen.getByLabelText(/^answer$/i), 'Use the synthetic returns form.')
    await user.click(screen.getByRole('button', { name: /add faq/i }))

    expect(mocks.addFaq).toHaveBeenCalledWith(
      'How do refunds work?',
      'Use the synthetic returns form.',
    )
    expect(await screen.findByText(/faq added and queued/i)).toBeInTheDocument()
  })

  it('hides management controls from an ordinary member', () => {
    mocks.useWorkspace.mockReturnValue({
      selectedWorkspace: { ...WORKSPACE, role: 'member' },
      loading: false,
    })
    render(<KnowledgePage />)

    expect(screen.getByText(/you have read-only access/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /upload document/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add faq/i })).not.toBeInTheDocument()
  })

  it('lets a manager recover an incomplete upload', async () => {
    const user = userEvent.setup()
    mocks.recoverUpload.mockResolvedValue({
      sourceId: '30000000-0000-0000-0000-000000000001',
      action: 'finalized',
      status: 'pending',
    })
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Interrupted upload',
          source_type: 'file',
          status: 'uploading',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)
    await user.click(screen.getByRole('button', { name: /recover upload/i }))

    expect(mocks.recoverUpload).toHaveBeenCalledWith(
      '30000000-0000-0000-0000-000000000001',
    )
    expect(await screen.findByText(/recovered and is now pending processing/i)).toBeInTheDocument()
  })

  it('does not expose upload recovery to an ordinary member', () => {
    mocks.useWorkspace.mockReturnValue({
      selectedWorkspace: { ...WORKSPACE, role: 'member' },
      loading: false,
    })
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Interrupted upload',
          source_type: 'file',
          status: 'uploading',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)

    expect(screen.queryByRole('button', { name: /recover upload/i })).not.toBeInTheDocument()
  })

  it('shows process actions to owners and admins but not members', () => {
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Pending guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    const { unmount } = render(<KnowledgePage />)
    expect(screen.getByRole('button', { name: /process source/i })).toBeInTheDocument()
    unmount()

    mocks.useWorkspace.mockReturnValue({
      selectedWorkspace: { ...WORKSPACE, role: 'admin' },
      loading: false,
    })
    const adminView = render(<KnowledgePage />)
    expect(screen.getByRole('button', { name: /process source/i })).toBeInTheDocument()
    adminView.unmount()

    mocks.useWorkspace.mockReturnValue({
      selectedWorkspace: { ...WORKSPACE, role: 'member' },
      loading: false,
    })
    render(<KnowledgePage />)
    expect(screen.queryByRole('button', { name: /process source/i })).not.toBeInTheDocument()
  })

  it('shows retry processing for a failed source', () => {
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Failed guide',
          source_type: 'file',
          status: 'failed',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)

    expect(screen.getByText('Processing failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry processing/i })).toBeInTheDocument()
  })

  it('processes a pending source once and reports the safe result', async () => {
    const user = userEvent.setup()
    mocks.processSource.mockResolvedValue({
      sourceId: '30000000-0000-0000-0000-000000000001',
      status: 'pending',
      chunkCount: 2,
      extractedCharCount: 2400,
      nextStage: 'embedding',
    })
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Pending guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)
    await user.click(screen.getByRole('button', { name: /process source/i }))

    expect(mocks.processSource).toHaveBeenCalledTimes(1)
    expect(await screen.findByText(/extracted into 2 chunks and is awaiting indexing/i)).toBeInTheDocument()
  })

  it('disables processing actions while a request is active', async () => {
    const user = userEvent.setup()
    mocks.processSource.mockReturnValue(new Promise(() => undefined))
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Pending guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)
    await user.click(screen.getByRole('button', { name: /process source/i }))

    expect(screen.getByRole('button', { name: /processing/i })).toBeDisabled()
    expect(mocks.processSource).toHaveBeenCalledTimes(1)
  })

  it('shows a safe failure without raw parser details', async () => {
    const user = userEvent.setup()
    mocks.processSource.mockRejectedValue(new Error('raw parser stack and private provider path'))
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Pending guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)
    await user.click(screen.getByRole('button', { name: /process source/i }))

    expect(await screen.findByText(/could not be processed safely/i)).toBeInTheDocument()
    expect(screen.queryByText(/raw parser|private provider/i)).not.toBeInTheDocument()
  })

  it('shows extracted pending sources as awaiting indexing', () => {
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Extracted guide',
          source_type: 'file',
          status: 'pending',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: '2026-09-15T01:00:00Z',
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)

    expect(screen.getByText('Extracted · awaiting indexing')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /index source/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /process source/i })).not.toBeInTheDocument()
  })

  it('retries indexing failures without offering extraction', async () => {
    const user = userEvent.setup()
    mocks.indexSource.mockResolvedValue({ sourceId: '30000000-0000-0000-0000-000000000001', status: 'ready', chunkCount: 1 })
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [{
        id: '30000000-0000-0000-0000-000000000001', title: 'Indexed guide',
        source_type: 'file', status: 'failed', original_filename: 'guide.pdf',
        created_at: '2026-09-15T00:00:00Z', extracted_at: '2026-09-15T01:00:00Z',
        last_failure_stage: 'indexing',
      }],
      loading: false, error: null, refresh: mocks.refresh, uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq, recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource, indexSource: mocks.indexSource,
    })

    render(<KnowledgePage />)
    expect(screen.getByText('Indexing failed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry processing/i })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry indexing/i }))
    expect(mocks.indexSource).toHaveBeenCalledTimes(1)
  })

  it('shows indexing for an active indexing stage without duplicate actions', () => {
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [{
        id: '30000000-0000-0000-0000-000000000001', title: 'Indexing guide',
        source_type: 'file', status: 'processing', original_filename: 'guide.pdf',
        created_at: '2026-09-15T00:00:00Z', extracted_at: '2026-09-15T01:00:00Z',
        processing_stage: 'indexing', last_failure_stage: null,
      }],
      loading: false, error: null, refresh: mocks.refresh, uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq, recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource, indexSource: mocks.indexSource,
    })
    render(<KnowledgePage />)
    expect(screen.getByText('Indexing')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /index/i })).not.toBeInTheDocument()
  })

  it('shows an approved processing error without altering it', async () => {
    const user = userEvent.setup()
    mocks.processSource.mockRejectedValue(
      new KnowledgeProcessingError('Encrypted or password-protected PDFs are not supported.'),
    )
    mocks.useKnowledgeSources.mockReturnValue({
      sources: [
        {
          id: '30000000-0000-0000-0000-000000000001',
          title: 'Encrypted guide',
          source_type: 'file',
          status: 'failed',
          original_filename: 'guide.pdf',
          created_at: '2026-09-15T00:00:00Z',
          extracted_at: null,
        },
      ],
      loading: false,
      error: null,
      refresh: mocks.refresh,
      uploadFile: mocks.uploadFile,
      addFaq: mocks.addFaq,
      recoverUpload: mocks.recoverUpload,
      processSource: mocks.processSource,
    })

    render(<KnowledgePage />)
    await user.click(screen.getByRole('button', { name: /retry processing/i }))

    expect(await screen.findByText(/password-protected pdfs are not supported/i)).toBeInTheDocument()
  })
})
