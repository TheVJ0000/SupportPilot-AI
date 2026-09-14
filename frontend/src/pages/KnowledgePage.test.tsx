import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { KnowledgePage } from './KnowledgePage'

const mocks = vi.hoisted(() => ({
  addFaq: vi.fn(),
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
    })

    render(<KnowledgePage />)

    expect(screen.getByRole('heading', { name: 'Support Guide' })).toBeInTheDocument()
    expect(screen.getByText(/support-guide\.pdf/i)).toBeInTheDocument()
    expect(screen.getByText('file')).toBeInTheDocument()
    expect(screen.getByText('pending')).toBeInTheDocument()
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
})
