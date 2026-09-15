import { useState, type FormEvent } from 'react'
import { KnowledgeOperationError } from '../knowledge/knowledgeApi'
import { KnowledgeProcessingError } from '../knowledge/processingApi'
import { KnowledgeIndexingError } from '../knowledge/indexingApi'
import type { KnowledgeSource, KnowledgeSourceStatus } from '../knowledge/types'
import { KnowledgeValidationError } from '../knowledge/validation'
import { useKnowledgeSources } from '../knowledge/useKnowledgeSources'
import { useWorkspace } from '../workspace/useWorkspace'

const STATUS_STYLES: Record<KnowledgeSourceStatus, string> = {
  uploading: 'border-amber-300/20 bg-amber-300/10 text-amber-200',
  pending: 'border-cyan-300/20 bg-cyan-300/10 text-cyan-200',
  processing: 'border-violet-300/20 bg-violet-300/10 text-violet-200',
  ready: 'border-emerald-300/20 bg-emerald-300/10 text-emerald-200',
  failed: 'border-rose-300/20 bg-rose-300/10 text-rose-200',
}

function sourceStatusLabel(source: KnowledgeSource): string {
  if (source.status === 'pending') {
    return source.extracted_at ? 'Extracted · awaiting indexing' : 'Pending processing'
  }
  if (source.status === 'failed') {
    return source.last_failure_stage === 'indexing' ? 'Indexing failed' : 'Processing failed'
  }
  if (source.status === 'processing') {
    return source.processing_stage === 'indexing' ? 'Indexing' : 'Processing'
  }
  if (source.status === 'uploading') return 'Uploading'
  return 'Ready'
}

function KnowledgeWorkspace({ workspaceId, canManage }: { workspaceId: string; canManage: boolean }) {
  const { sources, loading, error, refresh, uploadFile, addFaq, recoverUpload, processSource, indexSource } =
    useKnowledgeSources(workspaceId)
  const [file, setFile] = useState<File | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [uploading, setUploading] = useState(false)
  const [addingFaq, setAddingFaq] = useState(false)
  const [uploadMessage, setUploadMessage] = useState<string | null>(null)
  const [faqMessage, setFaqMessage] = useState<string | null>(null)
  const [recoveringSourceId, setRecoveringSourceId] = useState<string | null>(null)
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null)
  const [processingSourceId, setProcessingSourceId] = useState<string | null>(null)
  const [processingMessage, setProcessingMessage] = useState<string | null>(null)
  const [indexingSourceId, setIndexingSourceId] = useState<string | null>(null)
  const [indexingMessage, setIndexingMessage] = useState<string | null>(null)

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    if (!file || uploading) {
      setUploadMessage('Choose a PDF, DOCX, TXT, or MD file.')
      return
    }
    setUploading(true)
    setUploadMessage(null)
    try {
      await uploadFile(file)
      setFile(null)
      setUploadMessage('File uploaded securely and queued for future processing.')
      form.reset()
    } catch (caught) {
      setUploadMessage(
        caught instanceof KnowledgeValidationError || caught instanceof KnowledgeOperationError
          ? caught.message
          : 'The file could not be uploaded. Please try again.',
      )
    } finally {
      setUploading(false)
    }
  }

  async function handleFaq(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (addingFaq) return
    setAddingFaq(true)
    setFaqMessage(null)
    try {
      await addFaq(question, answer)
      setQuestion('')
      setAnswer('')
      setFaqMessage('FAQ added and queued for future processing.')
    } catch (caught) {
      setFaqMessage(
        caught instanceof KnowledgeOperationError
          ? caught.message
          : 'The FAQ could not be added. Please try again.',
      )
    } finally {
      setAddingFaq(false)
    }
  }

  async function handleRecovery(sourceId: string) {
    if (recoveringSourceId) return
    setRecoveringSourceId(sourceId)
    setRecoveryMessage(null)
    try {
      const result = await recoverUpload(sourceId)
      setRecoveryMessage(
        result.action === 'removed'
          ? 'The incomplete upload record was safely removed.'
          : 'The uploaded file was recovered and is now pending processing.',
      )
    } catch {
      setRecoveryMessage('The upload could not be recovered safely. Please try again.')
    } finally {
      setRecoveringSourceId(null)
    }
  }

  async function handleProcessing(sourceId: string) {
    if (processingSourceId) return
    setProcessingSourceId(sourceId)
    setProcessingMessage(null)
    try {
      const result = await processSource(sourceId)
      setProcessingMessage(
        `Source extracted into ${result.chunkCount} ${result.chunkCount === 1 ? 'chunk' : 'chunks'} and is awaiting indexing.`,
      )
    } catch (caught) {
      setProcessingMessage(
        caught instanceof KnowledgeProcessingError
          ? caught.message
          : 'The source could not be processed safely. Please try again.',
      )
    } finally {
      setProcessingSourceId(null)
    }
  }

  async function handleIndexing(sourceId: string) {
    if (indexingSourceId) return
    setIndexingSourceId(sourceId)
    setIndexingMessage(null)
    try {
      const result = await indexSource(sourceId)
      setIndexingMessage(
        `Source indexed successfully with ${result.chunkCount} ${result.chunkCount === 1 ? 'chunk' : 'chunks'}.`,
      )
    } catch (caught) {
      setIndexingMessage(
        caught instanceof KnowledgeIndexingError
          ? caught.message
          : 'The source could not be indexed safely. Please try again.',
      )
    } finally {
      setIndexingSourceId(null)
    }
  }

  return (
    <>
      {canManage ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <form className="rounded-3xl border border-white/10 bg-white/[0.045] p-6" onSubmit={handleUpload}>
            <p className="text-sm font-semibold text-cyan-300">Upload document</p>
            <h2 className="mt-2 text-xl font-semibold">Add a private source file</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">PDF, DOCX, TXT, or MD · maximum 10 MB</p>
            <label className="mt-5 block text-sm font-medium text-slate-200" htmlFor="knowledge-file">Document</label>
            <input
              accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
              className="mt-2 block w-full rounded-xl border border-dashed border-white/15 bg-slate-950/40 px-4 py-4 text-sm text-slate-300 file:mr-4 file:rounded-lg file:border-0 file:bg-cyan-300 file:px-3 file:py-2 file:font-semibold file:text-[#07111f]"
              disabled={uploading}
              id="knowledge-file"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null)
                setUploadMessage(null)
              }}
              type="file"
            />
            <p aria-live="polite" className="mt-3 min-h-6 text-sm text-slate-300">{uploadMessage}</p>
            <button className="mt-2 rounded-xl bg-cyan-300 px-5 py-3 font-bold text-[#07111f] hover:bg-cyan-200 disabled:opacity-60" disabled={uploading} type="submit">
              {uploading ? 'Uploading securely…' : 'Upload document'}
            </button>
          </form>

          <form className="rounded-3xl border border-white/10 bg-white/[0.045] p-6" onSubmit={handleFaq}>
            <p className="text-sm font-semibold text-teal-300">Manual knowledge</p>
            <h2 className="mt-2 text-xl font-semibold">Add an FAQ</h2>
            <label className="mt-5 block text-sm font-medium text-slate-200" htmlFor="faq-question">Question</label>
            <input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/50 px-4 py-3 outline-none focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/20" disabled={addingFaq} id="faq-question" maxLength={1000} onChange={(event) => setQuestion(event.target.value)} required value={question} />
            <label className="mt-4 block text-sm font-medium text-slate-200" htmlFor="faq-answer">Answer</label>
            <textarea className="mt-2 min-h-32 w-full resize-y rounded-xl border border-white/10 bg-slate-950/50 px-4 py-3 outline-none focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/20" disabled={addingFaq} id="faq-answer" maxLength={20000} onChange={(event) => setAnswer(event.target.value)} required value={answer} />
            <p aria-live="polite" className="mt-3 min-h-6 text-sm text-slate-300">{faqMessage}</p>
            <button className="mt-2 rounded-xl border border-cyan-300/30 bg-cyan-300/10 px-5 py-3 font-bold text-cyan-100 hover:bg-cyan-300/15 disabled:opacity-60" disabled={addingFaq} type="submit">
              {addingFaq ? 'Adding FAQ…' : 'Add FAQ'}
            </button>
          </form>
        </div>
      ) : (
        <div className="rounded-2xl border border-cyan-300/15 bg-cyan-300/5 p-5 text-sm leading-6 text-cyan-100">
          You have read-only access. Workspace owners and admins can add knowledge sources.
        </div>
      )}

      <section className="mt-8" aria-labelledby="source-list-title">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-cyan-300">Sources</p>
            <h2 className="mt-2 text-2xl font-semibold" id="source-list-title">Business knowledge</h2>
          </div>
          {error && <button className="text-sm font-semibold text-cyan-300" onClick={() => void refresh()} type="button">Try again</button>}
        </div>
        <p aria-live="polite" className="mt-3 min-h-6 text-sm text-slate-300">{recoveryMessage}</p>
        <p aria-live="polite" className="min-h-6 text-sm text-slate-300">{processingMessage}</p>
        <p aria-live="polite" className="min-h-6 text-sm text-slate-300">{indexingMessage}</p>

        {loading ? (
          <p aria-live="polite" className="mt-6 text-slate-400">Loading knowledge sources…</p>
        ) : error ? (
          <p aria-live="assertive" className="mt-6 rounded-2xl border border-rose-300/20 bg-rose-300/5 p-5 text-rose-200">{error}</p>
        ) : sources.length === 0 ? (
          <div className="mt-6 rounded-3xl border border-dashed border-white/15 bg-white/[0.025] p-8 text-center sm:p-12">
            <h3 className="text-xl font-semibold">Your knowledge base is empty</h3>
            <p className="mx-auto mt-3 max-w-xl leading-7 text-slate-400">Upload support documents or add FAQs to build your business knowledge base.</p>
          </div>
        ) : (
          <div className="mt-6 grid gap-3">
            {sources.map((source) => (
              <article className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-white/[0.035] p-5" key={source.id}>
                <div>
                  <h3 className="font-semibold text-slate-100">{source.title}</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    {source.source_type === 'file' ? source.original_filename : 'Manual FAQ'}
                    {' · '}
                    {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(source.created_at))}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-300">{source.source_type}</span>
                  <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${STATUS_STYLES[source.status]}`}>{sourceStatusLabel(source)}</span>
                  {canManage && source.status === 'uploading' && (
                    <button
                      className="rounded-lg border border-amber-300/25 px-3 py-1 text-xs font-semibold text-amber-100 hover:bg-amber-300/10 disabled:opacity-60"
                      disabled={recoveringSourceId !== null}
                      onClick={() => void handleRecovery(source.id)}
                      type="button"
                    >
                      {recoveringSourceId === source.id ? 'Recovering…' : 'Recover upload'}
                    </button>
                  )}
                  {canManage &&
                    ((source.status === 'pending' && !source.extracted_at) ||
                      (source.status === 'failed' && source.last_failure_stage !== 'indexing')) && (
                    <button
                      className="rounded-lg border border-cyan-300/25 px-3 py-1 text-xs font-semibold text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-60"
                      disabled={processingSourceId !== null}
                      onClick={() => void handleProcessing(source.id)}
                      type="button"
                    >
                      {processingSourceId === source.id
                        ? 'Processing…'
                        : source.status === 'failed'
                          ? 'Retry processing'
                          : 'Process source'}
                    </button>
                  )}
                  {canManage &&
                    ((source.status === 'pending' && !!source.extracted_at) ||
                      (source.status === 'failed' && source.last_failure_stage === 'indexing')) && (
                    <button
                      className="rounded-lg border border-violet-300/25 px-3 py-1 text-xs font-semibold text-violet-100 hover:bg-violet-300/10 disabled:opacity-60"
                      disabled={indexingSourceId !== null}
                      onClick={() => void handleIndexing(source.id)}
                      type="button"
                    >
                      {indexingSourceId === source.id
                        ? 'Indexing…'
                        : source.status === 'failed'
                          ? 'Retry indexing'
                          : 'Index source'}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  )
}

export function KnowledgePage() {
  const { selectedWorkspace, loading } = useWorkspace()

  if (loading) return <p aria-live="polite" className="text-slate-400">Loading workspace…</p>
  if (!selectedWorkspace) {
    return <p className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5 text-amber-100">Create a workspace before adding knowledge sources.</p>
  }

  const canManage = selectedWorkspace.role === 'owner' || selectedWorkspace.role === 'admin'
  return (
    <section>
      <p className="text-sm font-semibold text-cyan-300">{selectedWorkspace.name}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Knowledge Base</h1>
      <p className="mt-3 mb-8 max-w-2xl leading-7 text-slate-400">Manage the private source material that future SupportPilot answers will be grounded in.</p>
      <KnowledgeWorkspace canManage={canManage} key={selectedWorkspace.id} workspaceId={selectedWorkspace.id} />
    </section>
  )
}
