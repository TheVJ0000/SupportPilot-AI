import { test, expect } from './fixtures'
test('landing, labelled login and owner app boot', async ({ page, login }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: /log in/i }).first()).toBeVisible()
  await login()
  await expect(page).toHaveURL(/\/app\/dashboard$/)
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  await expect(page.getByText('Authenticated API connected')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Support metrics' })).toContainText('Total conversations')
})
for (const role of ['owner', 'admin', 'member'] as const) {
  test.describe(role, () => {
    test.use({ role })
    test('role navigation and direct route guards', async ({ page, login }) => {
      await login()
      const nav = page.getByRole('navigation', { name: 'Application' })
      await expect(nav.getByRole('link', { name: 'Knowledge Base' })).toBeVisible()
      await expect(nav.getByRole('link', { name: 'Workspace', exact: true })).toBeVisible()
      for (const name of ['Dashboard', 'Conversations', 'Escalations', 'Widget']) {
        if (role === 'member') await expect(nav.getByRole('link', { name, exact: true })).toHaveCount(0)
        else await expect(nav.getByRole('link', { name, exact: true })).toBeVisible()
      }
      if (role === 'member') for (const path of ['dashboard', 'conversations', 'escalations', 'widget']) {
        await page.goto(`/app/${path}`)
        await expect(page).toHaveURL(/\/app\/knowledge$/)
        await expect(page.getByRole('heading', { name: 'Knowledge Base', exact: true })).toBeVisible()
      }
    })
  })
}
