export interface HealthResponse {
  status: 'ok'
  service: string
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

export const apiBaseUrl = (configuredBaseUrl || 'http://127.0.0.1:8000').replace(/\/$/, '')

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/api/health`, {
    headers: { Accept: 'application/json' },
    signal,
  })

  if (!response.ok) {
    throw new Error(`Health check returned HTTP ${response.status}`)
  }

  const data: unknown = await response.json()

  if (
    typeof data !== 'object' ||
    data === null ||
    !('status' in data) ||
    data.status !== 'ok' ||
    !('service' in data) ||
    typeof data.service !== 'string'
  ) {
    throw new Error('Health check returned an unexpected response')
  }

  return { status: data.status, service: data.service }
}
