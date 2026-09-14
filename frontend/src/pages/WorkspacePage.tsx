import { useState, type FormEvent } from 'react'
import { useWorkspace } from '../workspace/useWorkspace'

export function WorkspacePage() {
  const {
    workspaces,
    selectedWorkspace,
    loading,
    error,
    createWorkspace,
    refreshWorkspaces,
    selectWorkspace,
  } = useWorkspace()
  const [workspaceName, setWorkspaceName] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const normalizedName = workspaceName.trim().replace(/\s+/g, ' ')
    if (normalizedName.length < 2 || normalizedName.length > 100) {
      setValidationError('Workspace name must be between 2 and 100 characters.')
      return
    }

    setValidationError(null)
    setSubmitting(true)
    try {
      await createWorkspace(normalizedName)
      setWorkspaceName('')
    } catch {
      // The provider exposes a safe user-facing error.
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <p aria-live="polite" className="text-slate-400">Loading your workspaces…</p>
  }

  if (error && workspaces.length === 0) {
    return (
      <div className="rounded-2xl border border-rose-300/20 bg-rose-300/5 p-6">
        <p aria-live="assertive" className="text-rose-200">{error}</p>
        <button className="mt-4 font-semibold text-cyan-300 hover:text-cyan-200" onClick={() => void refreshWorkspaces()} type="button">
          Try again
        </button>
      </div>
    )
  }

  if (workspaces.length === 0) {
    return (
      <section className="max-w-xl rounded-3xl border border-white/10 bg-white/[0.055] p-6 shadow-xl backdrop-blur-xl sm:p-8">
        <p className="text-sm font-semibold text-cyan-300">Workspace onboarding</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Create your first workspace</h1>
        <p className="mt-3 leading-7 text-slate-400">Use your business or team name. You will become the workspace owner automatically.</p>
        <form className="mt-7" onSubmit={handleCreate}>
          <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="workspace-name">Workspace name</label>
          <input
            id="workspace-name"
            className="w-full rounded-xl border border-white/10 bg-slate-950/50 px-4 py-3 text-white outline-none focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/20"
            value={workspaceName}
            onChange={(event) => setWorkspaceName(event.target.value)}
            autoComplete="organization"
            disabled={submitting}
            required
          />
          <div aria-live="polite" className="mt-2 min-h-6 text-sm text-rose-300">{validationError ?? error}</div>
          <button className="mt-3 rounded-xl bg-cyan-300 px-5 py-3 font-bold text-[#07111f] hover:bg-cyan-200 disabled:opacity-60" disabled={submitting} type="submit">
            {submitting ? 'Creating workspace…' : 'Create workspace'}
          </button>
        </form>
      </section>
    )
  }

  return (
    <section>
      <p className="text-sm font-semibold text-cyan-300">Workspace</p>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{selectedWorkspace?.name}</h1>
          <p className="mt-2 text-slate-400">Your authenticated application foundation is ready.</p>
        </div>
        {workspaces.length > 1 && (
          <div>
            <label className="mb-2 block text-sm text-slate-400" htmlFor="workspace-selector">Current workspace</label>
            <select
              id="workspace-selector"
              className="min-w-56 rounded-xl border border-white/10 bg-slate-900 px-4 py-3 text-white outline-none focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/20"
              value={selectedWorkspace?.id ?? ''}
              onChange={(event) => selectWorkspace(event.target.value)}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="mt-8 rounded-3xl border border-white/10 bg-white/[0.045] p-6 sm:p-8">
        <h2 className="text-lg font-semibold">Workspace ready</h2>
        <p className="mt-2 max-w-2xl leading-7 text-slate-400">Authentication and tenant selection are connected. Knowledge ingestion and support features will arrive in later phases.</p>
      </div>
    </section>
  )
}
