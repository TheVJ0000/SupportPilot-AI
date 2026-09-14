import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App health status', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a loading state before reporting a healthy backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', service: 'supportpilot-api' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(screen.getByText(/checking backend connection/i)).toBeInTheDocument()
    expect(await screen.findByText(/connected to/i)).toBeInTheDocument()
    expect(screen.getByText('supportpilot-api')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/health',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('shows a clear error when the backend cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<App />)

    expect(await screen.findByText(/backend unavailable/i)).toBeInTheDocument()
  })
})
