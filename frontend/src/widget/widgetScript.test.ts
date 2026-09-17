import source from '../../public/supportpilot-widget.js?raw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const publicId = '10000000-0000-4000-8000-000000000001'
const registry = window as unknown as Record<string, unknown>
function initialize(attributes: Record<string, string> = {}, src = 'https://support.example/supportpilot-widget.js') {
  const script = document.createElement('script')
  script.src = src
  script.setAttribute('data-supportpilot-public-id', publicId)
  for (const [name, value] of Object.entries(attributes)) script.setAttribute(name, value)
  vi.spyOn(document, 'currentScript', 'get').mockReturnValue(script)
  window.eval(source)
  return document.getElementById('supportpilot-widget-root')
}
function controls() {
  const shadow = document.getElementById('supportpilot-widget-root')!.shadowRoot!
  return { shadow, launcher: shadow.querySelector<HTMLButtonElement>('.launcher')!, panel: shadow.querySelector<HTMLElement>('.panel')!, close: shadow.querySelector<HTMLButtonElement>('.close')! }
}
beforeEach(() => {
  document.body.replaceChildren()
  delete registry.__supportpilotWidgetV1
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('standalone SupportPilot launcher', () => {
  it('creates one shadow-isolated, keyboard-native launcher without an eager iframe', () => {
    const root = initialize()!
    expect(root.shadowRoot).not.toBeNull()
    expect(root.style.right).toBe('16px')
    expect(controls().launcher.tagName).toBe('BUTTON')
    expect(controls().launcher.textContent).toBe('Support')
    expect(controls().launcher.getAttribute('aria-expanded')).toBe('false')
    expect(root.shadowRoot!.querySelector('iframe')).toBeNull()
    expect(root.querySelector('style')).toBeNull()
  })
  it.each(['', 'not-a-uuid', '10000000-0000-0000-0000-000000000001'])('rejects invalid ID %s quietly before iframe/network creation', id => {
    expect(initialize({ 'data-supportpilot-public-id': id })).toBeNull()
    expect(initialize({ 'data-supportpilot-public-id': id })).toBeNull()
    expect(console.warn).toHaveBeenCalledTimes(1)
  })
  it('handles a missing attribute safely', () => {
    const script = document.createElement('script')
    script.src = 'https://support.example/supportpilot-widget.js'
    vi.spyOn(document,'currentScript','get').mockReturnValue(script)
    window.eval(source)
    expect(document.getElementById('supportpilot-widget-root')).toBeNull()
  })
  it.each(['javascript:alert(1)', 'https://user:password@support.example/widget.js'])('rejects unsafe script source %s', url => {
    expect(initialize({}, url)).toBeNull()
  })
  it('uses trimmed, capped text labels without HTML execution', () => {
    initialize({ 'data-supportpilot-label': '  <img src=x onerror=alert(1)>Text ' })
    expect(controls().launcher.textContent).toBe('<img src=x onerror=alert(1)>Text')
    expect(controls().shadow.querySelector('img')).toBeNull()
    expect(controls().launcher.children).toHaveLength(0)
  })
  it('caps long labels at 40 characters', () => {
    initialize({ 'data-supportpilot-label': 'a'.repeat(60) })
    expect(controls().launcher.textContent).toHaveLength(40)
  })
  it.each([['left','left'],['right','right'],['evil','right']] as const)('handles %s position as %s', (value, expected) => {
    const root = initialize({ 'data-supportpilot-position': value })!
    expect(root.style.getPropertyValue(expected)).toBe('16px')
  })
  it('opens only the script-origin iframe, with a conservative sandbox and no host backend override', () => {
    initialize({ 'data-api-url':'https://evil.example', 'data-origin':'https://evil.example', 'data-backend':'https://evil.example' })
    const { launcher,panel,close,shadow } = controls()
    launcher.click()
    const iframe = shadow.querySelector('iframe')!
    expect(iframe.src).toBe(`https://support.example/embed/${publicId}`)
    expect(iframe.title).toBe('Support chat')
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts allow-forms allow-same-origin')
    expect(iframe.referrerPolicy).toBe('no-referrer')
    expect(panel.hidden).toBe(false)
    expect(launcher.getAttribute('aria-expanded')).toBe('true')
    expect(shadow.activeElement).toBe(close)
    close.click()
    expect(panel.hidden).toBe(true)
    expect(launcher.getAttribute('aria-expanded')).toBe('false')
    expect(shadow.activeElement).toBe(launcher)
    launcher.click()
    expect(shadow.querySelector('iframe')).toBe(iframe)
    close.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))
    expect(panel.hidden).toBe(true)
  })
  it('preserves the first valid widget and warns once on conflicting installations', () => {
    const first = initialize()
    expect(initialize()).toBe(first)
    initialize({ 'data-supportpilot-public-id':'10000000-0000-4000-8000-000000000002' })
    initialize({ 'data-supportpilot-public-id':'10000000-0000-4000-8000-000000000003' })
    expect(document.querySelectorAll('#supportpilot-widget-root')).toHaveLength(1)
    expect(console.warn).toHaveBeenCalledTimes(1)
  })
  it('does not access host storage/cookies/content or call APIs', () => {
    const storage = vi.spyOn(Storage.prototype,'getItem')
    const cookie = vi.spyOn(document,'cookie','get')
    const fetch = vi.fn()
    vi.stubGlobal('fetch',fetch)
    initialize({ 'data-session-token':'private-test-value','data-api-key':'private-test-value' })
    controls().launcher.click()
    expect(storage).not.toHaveBeenCalled()
    expect(cookie).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
    expect(controls().shadow.textContent).not.toContain('private-test-value')
    expect(controls().shadow.querySelector('iframe')!.src).not.toContain('?')
    expect(source).not.toMatch(/postMessage|innerHTML|document\.write|Authorization|sessionToken/)
  })
})
