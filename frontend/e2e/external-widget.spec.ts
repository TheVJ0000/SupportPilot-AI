import { test, expect, HOST, ORIGIN, PUBLIC, API, send, finish } from './fixtures'

export const hostUrl = `${HOST}/?publicId=${PUBLIC}&supportOrigin=${encodeURIComponent(ORIGIN)}`

test('separate-origin launcher, isolation, embedded exchange and preserved session', async ({ page, release }) => {
  await page.addInitScript(() => {
    const messages: unknown[] = []
    Object.defineProperty(window, '__observedHostMessages', { value: messages })
    window.addEventListener('message', event => messages.push(event.data))
  })
  await page.goto(hostUrl)
  const store = page.getByRole('button', { name: 'Demo store button' })
  const style = await store.evaluate(element => ({ color: getComputedStyle(element).backgroundColor, font: getComputedStyle(element).fontFamily }))
  const launcher = page.getByRole('button', { name: 'Support', exact: true })
  await expect(launcher).toHaveCount(1)
  // Re-loading the real script must not duplicate its launcher.
  await page.evaluate(({ origin, publicId }) => new Promise<void>(resolve => {
    const script = document.createElement('script')
    script.src = `${origin}/supportpilot-widget.js`
    script.dataset.supportpilotPublicId = publicId
    script.onload = () => resolve()
    document.body.append(script)
  }), { origin: ORIGIN, publicId: PUBLIC })
  await expect(launcher).toHaveCount(1)
  await launcher.click()
  const iframe = page.locator('iframe[title="Support chat"]')
  await expect(iframe).toHaveAttribute('src', `${ORIGIN}/embed/${PUBLIC}`)
  await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin')
  await expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer')
  const chat = page.frameLocator('iframe[title="Support chat"]')
  await send(chat)
  await finish(chat, release)
  await expect(chat.getByRole('listitem').filter({ hasText: /^1\. Shipping Policy — page 2$/ })).toBeVisible()
  await chat.getByRole('button', { name: 'Mark this answer as helpful', exact: true }).click()
  await expect(chat.getByRole('button', { name: 'Mark this answer as helpful', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Close support chat' }).click()
  await expect(iframe).toBeHidden()
  await expect(launcher).toBeFocused()
  await launcher.click()
  await expect(chat.getByText('Orders ship within two days.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close support chat' }).press('Escape')
  await expect(iframe).toBeHidden()
  expect(await store.evaluate(element => ({ color: getComputedStyle(element).backgroundColor, font: getComputedStyle(element).fontFamily }))).toEqual(style)
  const hostState = await page.evaluate(() => ({
    local: Object.keys(localStorage), session: Object.keys(sessionStorage),
    messages: Reflect.get(window, '__observedHostMessages') as unknown[],
    text: document.body.innerText,
  }))
  expect(hostState.local).toEqual([])
  expect(hostState.session).toEqual([])
  expect(hostState.messages).toEqual([])
  expect(hostState.text).not.toMatch(/X-SupportPilot-Session|Orders ship within two days|When do orders ship|access_token|conversation_token|publishable-placeholder/)
  await page.reload()
  await expect(launcher).toHaveCount(1)
  await launcher.click()
  await expect(chat.getByText('Orders ship within two days.', { exact: true })).toBeVisible()
  await expect(chat.getByText('When do orders ship?', { exact: true })).toHaveCount(1)
})

test.describe('unavailable widget', () => {
  test.use({ expectedStatuses: [404] })
  test('disabled public widget displays only safe unavailable copy', async ({ page, request, login }) => {
    await login()
    await page.goto('/app/widget')
    await page.getByRole('button', { name: 'Disable widget', exact: true }).click()
    await expect(page.getByText('Disabled', { exact: true })).toBeVisible()
    await page.goto(hostUrl)
    await page.getByRole('button', { name: 'Support', exact: true }).click()
    const chat = page.frameLocator('iframe[title="Support chat"]')
    await expect(chat.getByText('Support chat unavailable', { exact: true })).toBeVisible()
    await expect(chat.locator('body')).not.toContainText(/Alpha|Beta|P0002|SQL|token_hash/)
    expect((await (await request.get(`${API}/_e2e/state`)).json()).messages).toBe(0)
  })
})
