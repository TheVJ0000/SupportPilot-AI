import { apiBaseUrl } from './health'

export type AuthenticatedApiStatus = 'connected' | 'rejected' | 'unavailable'

export interface AuthenticatedIdentity {
  user_id: string
  email: string | null
}

export class AuthenticatedApiError extends Error {
  constructor(public readonly status: AuthenticatedApiStatus) {
    super(status)
    this.name = 'AuthenticatedApiError'
  }
}

export async function getAuthenticatedIdentity(
  accessToken: string,
  signal?: AbortSignal,
): Promise<AuthenticatedIdentity> {
  let response: Response

  try {
    response = await fetch(`${apiBaseUrl}/api/auth/me`, {
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      signal,
    })
  } catch {
    throw new AuthenticatedApiError('unavailable')
  }

  if (response.status === 401) throw new AuthenticatedApiError('rejected')
  if (!response.ok) throw new AuthenticatedApiError('unavailable')

  const data: unknown = await response.json()
  if (
    typeof data !== 'object' ||
    data === null ||
    !('user_id' in data) ||
    typeof data.user_id !== 'string'
  ) {
    throw new AuthenticatedApiError('unavailable')
  }

  return {
    user_id: data.user_id,
    email: 'email' in data && typeof data.email === 'string' ? data.email : null,
  }
}
