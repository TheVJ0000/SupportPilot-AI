import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const html = readFileSync('../examples/widget-host/index.html', 'utf8')
const parsed = new DOMParser().parseFromString(html,'text/html')
const code = parsed.scripts[0].textContent!
const publicId='10000000-0000-4000-8000-000000000001'
beforeEach(() => {
  document.body.replaceChildren(...Array.from(parsed.body.children).filter(node => node.tagName !== 'SCRIPT').map(node => document.importNode(node,true)))
})
function run(query: string) {
  window.history.replaceState(null,'',`/?${query}`)
  window.eval(code)
  return document.querySelector('script')
}
describe('synthetic independent widget host', () => {
  it('loads only the stable widget asset from a validated demo origin', () => {
    const script=run(`publicId=${publicId}&supportOrigin=${encodeURIComponent('https://support.example')}`)!
    expect(script.src).toBe('https://support.example/supportpilot-widget.js')
    expect(script.getAttribute('data-supportpilot-public-id')).toBe(publicId)
    expect(document.body.textContent).toContain('Acme Demo Store')
    expect(document.body.textContent).toContain('Not a real business')
    expect(code).not.toMatch(/fetch\(|sessionToken|Authorization|Supabase|Gemini/)
  })
  it.each(['publicId=bad',`publicId=${publicId}&supportOrigin=javascript:alert(1)`,`publicId=${publicId}&supportOrigin=${encodeURIComponent('https://user:password@evil.example')}`])('rejects unsafe local demo setup %s', query => {
    expect(run(query)).toBeNull()
  })
  it('does not call chat APIs directly', () => {
    const fetch=vi.fn()
    vi.stubGlobal('fetch',fetch)
    run(`publicId=${publicId}`)
    expect(fetch).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
