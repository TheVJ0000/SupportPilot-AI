import { afterEach, describe, expect, it, vi } from 'vitest'
import { adminApi } from './adminApi'

afterEach(() => vi.unstubAllGlobals())
describe('authenticated operations REST client', () => {
  it('sends only caller bearer authorization and bounded enum filters/cursor', async () => {
    const mock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ workspace_id: 'workspace-1', items: [], next_cursor: null }),
    })
    vi.stubGlobal('fetch', mock)
    const controller = new AbortController()
    await adminApi.escalations(
      'workspace-1',
      'caller-token',
      {
        status: 'open',
        triage_status: 'completed',
        priority: 'urgent',
        trigger_reason: 'human_requested',
      },
      { time: '2026-09-16T12:00:00Z', id: 'record-1' },
      controller.signal,
    )
    const [url, options] = mock.mock.calls[0]
    expect(new URL(url).pathname).toBe('/api/admin/workspaces/workspace-1/escalations')
    expect(new URL(url).searchParams.get('limit')).toBe('25')
    expect(new URL(url).searchParams.get('priority')).toBe('urgent')
    expect(new URL(url).searchParams.get('cursor_id')).toBe('record-1')
    expect(options.headers).toEqual({
      Authorization: 'Bearer caller-token',
      Accept: 'application/json',
    })
    expect(options.signal).toBe(controller.signal)
  })
  it('omits the time for a null-activity conversation cursor', async () => {
    const mock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ workspace_id: 'workspace-1', items: [], next_cursor: null }),
    })
    vi.stubGlobal('fetch', mock)
    await adminApi.conversations(
      'workspace-1',
      'token',
      { status: 'all' },
      { time: null, id: 'record-1' },
      new AbortController().signal,
    )
    expect(new URL(mock.mock.calls[0][0]).searchParams.has('cursor_time')).toBe(false)
  })
  it.each([401, 403, 404, 409, 502, 503])(
    'maps %s without showing provider payloads',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: false,
          status,
          json: async () => ({ detail: 'private database error' }),
        }),
      )
      await expect(
        adminApi.dashboard('workspace-1', 'token', new AbortController().signal),
      ).rejects.toThrow(/session|access|not found|could not be loaded|changed/)
    },
  )
  it('rejects a mismatched workspace', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ workspace_id: 'workspace-2' }) }),
    )
    await expect(
      adminApi.dashboard('workspace-1', 'token', new AbortController().signal),
    ).rejects.toThrow('unexpected response')
  })
})

describe('fixed lifecycle REST writes', () => {
  it.each(['conversation','escalation'] as const)('sends a scoped %s PATCH with expected server state', async kind => {
    const mock = vi.fn().mockResolvedValue({ok:true,json:async()=>({workspace_id:'workspace-1',conversation:{id:'record-1'},escalation:{id:'record-1'}})})
    vi.stubGlobal('fetch',mock)
    const signal = new AbortController().signal
    const request = kind === 'conversation' ? {expected_status:'open' as const,expected_resolution_outcome:'unresolved' as const,action:'resolve' as const} : {expected_status:'open' as const,status:'in_progress' as const}
    if (kind === 'conversation') await adminApi.setConversationResolution('workspace-1','token','record-1',request as Parameters<typeof adminApi.setConversationResolution>[3],signal)
    else await adminApi.setEscalationStatus('workspace-1','token','record-1',request as Parameters<typeof adminApi.setEscalationStatus>[3],signal)
    const [url,init] = mock.mock.calls[0]
    expect(new URL(url).pathname).toBe(`/api/admin/workspaces/workspace-1/${kind === 'conversation' ? 'conversations/record-1/resolution' : 'escalations/record-1/status'}`)
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual(request)
    expect(init.headers).toEqual({Authorization:'Bearer token',Accept:'application/json','Content-Type':'application/json'})
    expect(init.signal).toBe(signal)
  })
  it('never exposes the conflict response body', async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:409,json:async()=>({detail:'private SQL'})}))
    await expect(adminApi.setEscalationStatus('workspace-1','token','record-1',{expected_status:'open',status:'closed'},new AbortController().signal)).rejects.toThrow('This record changed before your action was completed. Refresh and try again.')
  })
})
