import { isUuid, type CreatedCustomerSession } from './customerChatApi'

export interface StoredCustomerChatSession {
  publicId: string
  conversationId: string
  sessionToken: string
  expiresAt: string
  workspaceName: string
}

function storageKey(publicId: string): string {
  return `supportpilot:chat-session:${publicId}`
}

function isStoredSession(value: unknown, publicId: string): value is StoredCustomerChatSession {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return (
    Object.keys(record).length === 5 &&
    record.publicId === publicId &&
    isUuid(record.publicId) &&
    isUuid(record.conversationId) &&
    typeof record.sessionToken === 'string' &&
    /^[A-Za-z0-9_-]{43,128}$/.test(record.sessionToken) &&
    typeof record.expiresAt === 'string' &&
    Number.isFinite(Date.parse(record.expiresAt)) &&
    Date.parse(record.expiresAt) > Date.now() &&
    typeof record.workspaceName === 'string' &&
    record.workspaceName.length >= 1
  )
}

export function loadCustomerChatSession(publicId: string): StoredCustomerChatSession | null {
  const key = storageKey(publicId)
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (isStoredSession(parsed, publicId)) return parsed
  } catch {
    // Invalid browser state is discarded and recreated from the server.
  }
  try {
    localStorage.removeItem(key)
  } catch {
    // The in-memory session can still be used when browser storage is unavailable.
  }
  return null
}

export function saveCustomerChatSession(
  publicId: string,
  created: CreatedCustomerSession,
): StoredCustomerChatSession {
  const stored: StoredCustomerChatSession = {
    publicId,
    conversationId: created.conversation_id,
    sessionToken: created.session_token,
    expiresAt: created.expires_at,
    workspaceName: created.workspace_name,
  }
  try {
    localStorage.setItem(storageKey(publicId), JSON.stringify(stored))
  } catch {
    // Persistence is best effort; do not prevent the current chat from working.
  }
  return stored
}

export function clearCustomerChatSession(publicId: string): void {
  try {
    localStorage.removeItem(storageKey(publicId))
  } catch {
    // Nothing else should be retained or logged when storage is unavailable.
  }
}
