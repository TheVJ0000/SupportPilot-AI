import { test, expect } from './fixtures'
test('knowledge states, file validation and FAQ FastAPI extraction', async ({ page, login }) => {
  await login()
  await page.getByRole('link', { name: 'Knowledge Base', exact: true }).click()
  for (const [name, status] of [['Shipping Policy', 'Ready'], ['Returns FAQ', 'Ready'], ['Troubleshooting Guide', 'Processing']]) {
    const source = page.getByRole('article').filter({ has: page.getByRole('heading', { name, exact: true }) })
    await expect(source.getByText(status, { exact: true })).toBeVisible()
  }
  await page.getByLabel('Document', { exact: true }).setInputFiles({ name: 'unsupported.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('synthetic') })
  await page.getByRole('button', { name: 'Upload document' }).click()
  await expect(page.getByText('Choose a PDF, DOCX, TXT, or MD file.', { exact: true })).toBeVisible()
  await page.getByLabel('Document', { exact: true }).setInputFiles({ name: 'oversized.txt', mimeType: 'text/plain', buffer: Buffer.alloc(10 * 1024 * 1024 + 1) })
  await page.getByRole('button', { name: 'Upload document' }).click()
  await expect(page.getByText('Files must be 10 MB or smaller.', { exact: true })).toBeVisible()
  await page.getByLabel('Question', { exact: true }).fill('Synthetic FAQ browser question?')
  await page.getByLabel('Answer', { exact: true }).fill('Synthetic non-confidential answer.')
  await page.getByRole('button', { name: 'Add FAQ', exact: true }).click()
  const row = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Synthetic FAQ browser question?', exact: true }) })
  await expect(row).toContainText('Pending')
  await row.getByRole('button', { name: 'Process source', exact: true }).click()
  await expect(page.getByText(/Source extracted into .* awaiting indexing/)).toBeVisible()
  await expect(row.getByRole('button', { name: 'Index source' })).toBeVisible()
  await expect(row).not.toContainText('Ready')
})
