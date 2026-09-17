import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/useAuth'
import { useWorkspace } from '../workspace/useWorkspace'
import { adminApi, AdminApiError, type WidgetConfig } from './adminApi'
import { PageHeading, ResourceState } from './components'
import { button, panel, textLink } from './format'
import { useAdminResource } from './useAdminResource'

function WidgetSettings({ config, replace, refresh }: {
  config: WidgetConfig; replace: (value: WidgetConfig) => void; refresh: () => void
}) {
  const { accessToken } = useAuth()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copyState, setCopyState] = useState('')
  const request = useRef<AbortController | null>(null)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => { active.current = false; request.current?.abort() }
  }, [])
  const origin = window.location.origin
  const chatUrl = `${origin}/chat/${config.public_id}`
  const snippet = `<script\n  src="${origin}/supportpilot-widget.js"\n  data-supportpilot-public-id="${config.public_id}"\n  async\n></script>`

  async function copy() {
    setCopyState('')
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(snippet)
      if (active.current) setCopyState('Embed code copied.')
    } catch {
      if (active.current) setCopyState('Copy is unavailable. Select and copy the embed code below.')
    }
  }
  async function toggle() {
    if (!accessToken || request.current) return
    const controller = new AbortController()
    request.current = controller
    setPending(true)
    setError(null)
    try {
      const result = await adminApi.setWidgetEnabled(config.workspace_id, accessToken, {
        expected_enabled: config.is_enabled, enabled: !config.is_enabled,
      }, controller.signal)
      if (!controller.signal.aborted) replace(result)
    } catch (failure: unknown) {
      if (!controller.signal.aborted) setError(failure instanceof AdminApiError
        ? failure.message : "We couldn't update the support widget right now.")
    } finally {
      if (!controller.signal.aborted) { request.current = null; setPending(false) }
    }
  }
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
      <section className={panel}>
        <h2 className="text-lg font-semibold">Availability</h2>
        <p className="mt-4"><span className={`rounded-full px-3 py-1 text-sm ${config.is_enabled ? 'bg-emerald-300/10 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}>{config.is_enabled ? 'Enabled' : 'Disabled'}</span></p>
        <p className="mt-4 text-sm leading-6 text-slate-400">Disabling makes public chat unavailable, including new widget sessions. It does not remove conversations or change the public identifier.</p>
        <button type="button" className={`${button} mt-5`} disabled={pending} onClick={() => void toggle()}>{pending ? 'Saving…' : config.is_enabled ? 'Disable widget' : 'Enable widget'}</button>
        {error && <div className="mt-4"><p role="alert" className="text-sm text-rose-200">{error}</p><button type="button" className={`${button} mt-3`} disabled={pending} onClick={refresh}>Refresh widget configuration</button></div>}
        <h3 className="mt-7 text-sm font-semibold">Public widget/chat ID</h3>
        <p className="mt-2 break-all font-mono text-xs text-slate-400">{config.public_id}</p>
        <p className="mt-2 text-xs leading-5 text-slate-500">A public integration identifier, not an authentication credential.</p>
        <h3 className="mt-6 text-sm font-semibold">Public chat URL</h3>
        <a className={`${textLink} mt-2 block break-all text-xs`} href={chatUrl}>{chatUrl}</a>
      </section>
      <section className={panel}>
        <h2 className="text-lg font-semibold">Add support to your website</h2>
        <p className="mt-3 text-sm leading-6 text-slate-400">Add this script to your website before the closing &lt;/body&gt; tag.</p>
        <button type="button" className={`${button} mt-5`} onClick={() => void copy()}>Copy embed code</button>
        <p role="status" className="mt-3 text-xs text-cyan-200">{copyState}</p>
        <label className="mt-4 block text-xs text-slate-400" htmlFor="widget-embed-code">Embed code</label>
        <textarea id="widget-embed-code" aria-label="Embed code" readOnly rows={6} value={snippet} className="mt-2 w-full resize-none rounded-xl border border-white/10 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-200" onFocus={event => event.currentTarget.select()} />
        <p className="mt-4 text-xs leading-6 text-slate-400">The launcher opens an isolated SupportPilot iframe. Customer state stays on the SupportPilot origin; your website needs no Supabase or AI credentials.</p>
        <p className="mt-3 text-xs leading-6 text-slate-500">Optional attributes: data-supportpilot-label (plain text, up to 40 characters) and data-supportpilot-position (left or right).</p>
      </section>
    </div>
  )
}

export function WidgetPage() {
  const { selectedWorkspace } = useWorkspace()
  const resource = useAdminResource('widget', adminApi.getWidgetConfig)
  return <>
    <PageHeading title="Support widget" workspace={selectedWorkspace?.name ?? ''} description="Connect your business website to the same grounded customer support chat." />
    <ResourceState {...resource}>
      {resource.data && <WidgetSettings key={resource.data.workspace_id} config={resource.data} replace={resource.replace} refresh={resource.retry} />}
    </ResourceState>
  </>
}
