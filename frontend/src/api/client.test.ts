import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthenticatedApiError, getAuthenticatedIdentity } from './client'

describe('authenticated API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('adds the active bearer token in one centralized request path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        user_id: '10000000-0000-0000-0000-000000000001',
        email: 'owner@example.test',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getAuthenticatedIdentity('test-session-value')).resolves.toEqual({
      user_id: '10000000-0000-0000-0000-000000000001',
      email: 'owner@example.test',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/auth/me',
      expect.objectContaining({
        headers: {
          Accept: 'application/json',
          Authorization: 'Bearer test-session-value',
        },
      }),
    )
  })

  it('classifies a rejected session without exposing the response body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))

    await expect(getAuthenticatedIdentity('rejected-test-value')).rejects.toMatchObject<
      Partial<AuthenticatedApiError>
    >({ status: 'rejected' })
  })
})
