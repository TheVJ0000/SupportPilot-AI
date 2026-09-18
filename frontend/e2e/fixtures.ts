import { test as base, expect, type Page, type FrameLocator } from '@playwright/test'
import { randomUUID } from 'node:crypto'
export const ALPHA = '20000000-0000-4000-8000-000000000001'
export const BETA = '20000000-0000-4000-8000-000000000002'
export const PUBLIC = '10000000-0000-4000-8000-000000000001'
export const CONV = '40000000-0000-4000-8000-000000000001'
export const HUMAN = '40000000-0000-4000-8000-000000000002'
export const ESC = '50000000-0000-4000-8000-000000000001'
export const API = 'http://127.0.0.1:8001'
export const ORIGIN = 'http://127.0.0.1:5175'
export const HOST = 'http://127.0.0.1:4175'
type Fixtures = {
  role: 'owner' | 'admin' | 'member'
  scenario: string
  expectedStatuses: number[]
  setup: void
  login: () => Promise<void>
  release: (gate?: number) => Promise<void>
}
export const test = base.extend<Fixtures>({
  role: ['owner', { option: true }], scenario: ['normal', { option: true }], expectedStatuses: [[], { option: true }],
  setup: [async ({ page, request, role, scenario, expectedStatuses }, provide) => {
    const token = randomUUID()
    expect((await request.post(`${API}/_e2e/reset`, { data: { token, role, scenario } })).ok()).toBeTruthy()
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => {
      if (message.type() !== 'error') return
      const status = message.text().match(/^Failed to load resource: the server responded with a status of (\d+)/)
      // Only explicitly expected HTTP failures from our local API, never JS errors.
      if (status && expectedStatuses.includes(Number(status[1])) && message.location().url.startsWith(API)) return
      errors.push(message.text())
    })
    await page.route('https://supportpilot.example.test/**', async route => {
      const url = new URL(route.request().url())
      let body: unknown
      if (url.pathname === '/auth/v1/token') {
        body = {
          access_token: token, refresh_token: randomUUID(), expires_in: 3600,
          expires_at: Math.floor(Date.now() / 1000) + 3600, token_type: 'bearer',
          user: {
            id: '90000000-0000-4000-8000-000000000001', aud: 'authenticated',
            role: 'authenticated', email: `${role}@example.test`,
            user_metadata: { display_name: `Synthetic ${role}` }, app_metadata: {},
            created_at: '2026-09-18T12:00:00Z',
          },
        }
      } else if (url.pathname === '/rest/v1/workspaces') {
        body = [ALPHA, BETA].map((id, index) => ({ id, name: index ? 'Beta Support' : 'Alpha Support', created_at: '2026-09-18T12:00:00Z', workspace_members: [{ role }] }))
      } else if (url.pathname === '/rest/v1/knowledge_sources') {
        body = url.searchParams.get('workspace_id') === `eq.${BETA}` ? [] : await (await request.get(`${API}/_e2e/knowledge`)).json()
      } else if (url.pathname === '/rest/v1/rpc/create_faq_knowledge_source') {
        body = await (await request.post(`${API}/_e2e/faq`, { data: route.request().postDataJSON() })).json()
      } else if (url.pathname === '/auth/v1/logout') { body = {} }
      else { errors.push(`Unexpected external boundary: ${url.pathname}`); await route.abort(); return }
      await route.fulfill({ status: 200, json: body, headers: { 'access-control-allow-origin': ORIGIN } })
    })
    await provide()
    // Release blocked test-provider work even after an assertion fails.
    for (const gate of [0, 1, 2]) await request.post(`${API}/_e2e/release/${gate}`)
    expect(errors, 'Unexpected page or console errors').toEqual([])
  }, { auto: true }],
  login: async ({ page, setup }, provide) => {
    void setup
    await provide(async () => {
      await page.goto('/login')
      await page.getByLabel('Email', { exact: true }).fill('synthetic@example.test')
      await page.getByLabel('Password', { exact: true }).fill(randomUUID())
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(page.getByLabel('Active workspace')).toHaveValue(ALPHA)
      // Login intentionally opens the workspace foundation. The /app index
      // chooses the operations landing page for the selected membership role.
      await expect(page).toHaveURL(/\/app\/workspaces$/)
      await page.goto('/app')
    })
  },
  release: async ({ request }, provide) => {
    await provide(async (gate = 0) => {
      expect((await request.post(`${API}/_e2e/release/${gate}`)).ok()).toBeTruthy()
    })
  },
})
export { expect }
export async function send(page: Page | FrameLocator, text = 'When do orders ship?') {
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill(text)
  await page.getByRole('button', { name: 'Send', exact: true }).click()
}
export async function finish(page: Page | FrameLocator, release: (gate?: number) => Promise<void>) {
  await expect(page.getByLabel('Assistant response in progress')).toContainText('Orders ')
  await release(0)
  await expect(page.getByLabel('Assistant response in progress')).toContainText('Orders ship ')
  await release(1)
  await expect(page.getByText('Orders ship within two days.', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Assistant response in progress')).toHaveCount(0)
}
