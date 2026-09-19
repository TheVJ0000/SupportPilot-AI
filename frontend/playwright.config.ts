import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'

const backend = path.resolve(import.meta.dirname, '../backend')
const configuredPython = process.env.SUPPORTPILOT_E2E_PYTHON
const localPython = path.join(
  backend,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
const python =
  configuredPython ??
  (existsSync(localPython) ? localPython : process.platform === 'win32' ? 'python' : 'python3')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5175',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn e2e_app:app --app-dir tests --host 127.0.0.1 --port 8001 --no-access-log`,
      cwd: backend,
      url: 'http://127.0.0.1:8001/_e2e/state',
      reuseExistingServer: false,
      env: { FRONTEND_URL: 'http://127.0.0.1:5175' },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5175 --strictPort',
      url: 'http://127.0.0.1:5175',
      reuseExistingServer: false,
      env: {
        VITE_API_BASE_URL: 'http://127.0.0.1:8001',
        VITE_SUPABASE_URL: 'https://supportpilot.example.test',
        VITE_SUPABASE_PUBLISHABLE_KEY: 'synthetic-publishable-placeholder',
      },
    },
    {
      command: `"${python}" -m http.server 4175 --bind 127.0.0.1`,
      cwd: path.resolve(backend, '../examples/widget-host'),
      url: 'http://127.0.0.1:4175',
      reuseExistingServer: false,
    },
  ],
})
