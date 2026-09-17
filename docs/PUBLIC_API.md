# Public customer API: V1 contract

This contract describes the existing `/api/chat` URLs; there is no new `/v1` prefix, developer API-key feature or general external business REST API. Phase 8 is complete in code/automated tests, not a claim of production/load certification. Use the SupportPilot hosted chat or widget; external host websites must not call these APIs directly.

## Credential and transport boundary

Session creation needs only the enabled public widget/chat UUID. That identifier is public, not an authentication secret. Every conversation operation requires `X-SupportPilot-Session`, an opaque customer credential with at least 256 bits of entropy. Keep it inside the SupportPilot application/iframe, never in host code, iframe URLs, data attributes, postMessage, logs or query parameters. It is distinct from a business JWT and from any Supabase key. The backend hashes it and validates its conversation/workspace relationship and expiry using the existing narrow customer RPCs. Credentials expire after seven days; invalid/expired credentials receive safe 401.

Use HTTPS in production. JSON bodies use `Content-Type: application/json` (optional charset); turn bodies contain at most 2,000 characters of message text. All public mutation bodies are limited to **16 KiB actual bytes**, including missing/chunked or misleading Content-Length. Oversized bodies return 413; inappropriate content type returns 415. Session creation and human requests deliberately allow no body/no content type, or empty JSON `{}`. Extra fields, including scope, subject, limit, window, workspace ID, model or prompt settings, are rejected. Knowledge uploads/authenticated APIs are outside this body-limit/error scope.

## Endpoints

All successful responses are HTTP 200. UUIDs and opaque credentials below are placeholders, not live identifiers.

| Method/path | Credential | Request | Success |
| --- | --- | --- | --- |
| POST `/api/chat/{public_id}/session` | None | No body or `{}` | `conversation_id`, `session_token`, `workspace_name`, `expires_at` |
| GET `/api/chat/conversations/{conversation_id}` | Customer session header | No body | `conversation_id`, `status`, optional `human_requested_at`, `messages` |
| POST `/api/chat/conversations/{conversation_id}/turns` | Customer session header | `client_message_id` UUID, `message` string | Persisted turn result below |
| POST `/api/chat/conversations/{conversation_id}/turns/stream` | Customer session header | Same fields; Accept `text/event-stream` | SSE events below |
| PUT `/api/chat/conversations/{conversation_id}/messages/{message_id}/feedback` | Customer session header | `rating`: `positive` or `negative` | `message_id`, saved `rating` |
| POST `/api/chat/conversations/{conversation_id}/human-request` | Customer session header | No body or `{}` | `conversation_id`, `status: human_requested`, `human_requested_at` |

Example session response:

```json
{
  "conversation_id": "<conversation-uuid>",
  "session_token": "<opaque-customer-credential>",
  "workspace_name": "Synthetic Demo Workspace",
  "expires_at": "<ISO-8601-expiry>"
}
```

History status is `open`, `human_requested` or `closed`. Messages contain `id`, `role` (`customer`/`assistant`), plain `content`, `created_at`, citations and optional assistant `answer_status`/feedback. Answer status is `answered` or `insufficient_evidence`. Citations are saved trusted snapshots: `source_id`, `source_title`, `source_type`, `chunk_index`, typed `locator` (`faq`, `pdf`, `docx`, `text`, `markdown`). Do not interpret customer/assistant/source text as HTML. Human-requested/closed conversations reject new AI turns; existing server disable/session checks always apply.

Persisted turn response contains `conversation_id`, `turn_id`, assistant `message_id`, `client_message_id`, `status`, plain `answer`, trusted `citations` and `is_replay`. Only complete validated answers are persisted. Completion remains atomic with existing escalation behavior; partial text is never stored as a completed answer.

## Idempotency and SSE

Generate one `client_message_id` for an outbound message. Retries must reuse both ID and normalized message content, including after HTTP 429. A different message needs a different ID. A completed existing ID replays saved result without another processing-quota unit or AI call. A processing duplicate returns safe 409 (`turn_in_progress`) without new work/quota. A failed retry can consume another processing unit. Existing 100-turn and one-second new-turn cadence checks still apply; rejection never leaves a newly inserted message/turn solely due to a rate limit.

Before SSE response headers, session/input/rate-limit checks return normal HTTP JSON errors. A rate rejection is HTTP 429, not an SSE stream. Successful streaming is `text/event-stream`, blank-line-delimited JSON frames:

| Event | Data |
| --- | --- |
| `started` | `conversation_id`, `turn_id`, `client_message_id` |
| `delta` | `{ "text": "<provisional-answer-fragment>" }` |
| `complete` | Persisted turn response; this is the authority for final text/citations |
| `error` | `{ "code": "temporarily_unavailable", "message": "I couldn't complete that response right now." }` |

Completed replay may emit only `complete`. Discard provisional assistant text on interruption/error and retry the same outbound ID. Never treat a stream ending without `complete` as success. Once streaming has begun, HTTP status cannot change to 429: safe failures use `error`. The client also accepts the older safe `stream_failed` SSE code for compatibility, but never renders untrusted raw event/error messages. Session credentials remain in request headers only.

## Errors and Retry-After

The six documented customer route/method contracts use a fixed-message envelope. Authenticated admin/auth/RAG errors and unknown URL/method contracts are not rewritten.

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Please try again shortly.",
    "retry_after_seconds": 60
  }
}
```

HTTP 429 also includes `Retry-After: <integer-seconds>`. Actual wait is calculated from the encountered database window, bounded 1–3600; a shorter window may expire while a second/hour quota still prevents a retry. Expiry is not a reservation or guaranteed acceptance. Only meaningful throttling errors include retry seconds. Respect the wait and retry manually, never in a tight loop or by creating repeated sessions.

| Code | Typical HTTP status |
| --- | --- |
| `invalid_request` | 400/422; also 413 body too large or 415 inappropriate media type |
| `invalid_session` | 401 |
| `chat_unavailable` | 404 for absent/disabled public creation ID; 409 for disabled existing chat |
| `conversation_unavailable` | 404 |
| `conversation_not_open` | 409 for existing state/message-limit/cadence conflicts |
| `turn_in_progress` | 409 processing duplicate |
| `rate_limited` | 429 with Retry-After |
| `temporarily_unavailable` | Safe 500/502/503 failures or missing configuration |

No SQL/PostgREST diagnostics, Pydantic field/debug structures, scopes, counter values, session/workspace identifiers or provider payloads appear in errors. Frontend copy is static: session busy state, bounded manual turn cooldown preserving retry ID, safe feedback failure and safe human-request failure. A rejected human request never displays recorded success. Completed previously recorded requests remain intact and repeated calls do not schedule another immediate triage task; existing bounded worker retry policy remains separate.

## Fixed-window quotas

Only existing Supabase/PostgreSQL is used; no paid service, billing change, Redis, SaaS limiter, IP/hash or device fingerprint. Constants are centralized in migration 015's private helper, not supplied/configured by clients.

| Operation | Subject | V1 quota |
| --- | --- | --- |
| Session creation | Public widget/chat ID | 30/minute and 300/hour |
| New or failed-retry AI processing attempt | Validated customer session | 6/minute and 60/hour |
| Public history | Validated customer session | 60/minute |
| Feedback calls | Validated customer session | 20/minute |
| Human-request calls, including repeats | Validated customer session | 10/minute |

Database clock time owns aligned fixed windows. Atomic upserts serialize claims; coupled minute/hour claims and mutations roll back together on rejection. Counts cover successful transactional claims, not rejected traffic. Trusted internal turn-context reads do not consume public history quota. Infrastructure counters have RLS and no direct browser/service table access; only controlled functions use them. Indexed cleanup deletes at most 500 expired rows at startup/every ten existing worker cycles; failures do not crash FastAPI. Cleanup backlog under high traffic remains a tuning concern.

Creation quota is intentionally shared by all visitors to a public ID because no IP/fingerprint/person identity is collected. Fixed-window boundaries permit bursts; attackers can exhaust shared availability or spread work across sessions. These are portfolio/demo controls, not comprehensive bot defense or an aggregate AI-budget guarantee. Production concurrency/load tuning, broader evaluation and stronger privacy-conscious defenses (possibly CAPTCHA if justified) remain Phase 9. No CAPTCHA is integrated now.

## Cache, CORS and verification limits

Covered public responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`; SSE preserves `no-cache, no-store` and disabled proxy buffering. Do not log session headers/tokens/hashes, customer contents, transcripts, prompts or evidence. Local backend runs with `--no-access-log`; independently verify deployment/platform logging. No claim is made about third-party infrastructure logs.

The API keeps explicit configured SupportPilot frontend CORS origins with GET/POST/PATCH/PUT, including feedback PUT; external widget-host origins and DELETE remain denied. Retry-After is exposed only through the existing allowed-origin CORS policy. No wildcard CORS or frontend framing restriction was added. Host websites embed the stable script/SupportPilot-origin iframe and never receive rate/session/transcript state. Deployment framing/CSP remains Phase 10.

Actual Phase 8B validation: 489 backend / 201 frontend tests, Ruff lint/format, frontend lint/build and whitespace checks passed (existing non-blocking bundle warning). Migration 015's reviewed dry run contained only 015; rollback preflight passed 60 assertions, then normal hosted application succeeded. Hosted rollback suites passed public API/rate limits 60, customer chat 48 and widget configuration 25, not the entire DB suite. Bounded synthetic ASGI smoke accepted 30 fixture requests, throttled the next with Retry-After, then accepted a fresh fixture window; this used a test gateway, not live DB-backed HTTP. Live health/frontend/demo returned 200; the live unconfigured session endpoint safely returned 503. External widget shell/iframe/close/reopen/unavailable checks passed. The optional two-connection probe was inconclusive due to stalled CLI initialization; its temporary synthetic infrastructure counter was removed. Live customer/Gemini, complete sandbox storage/streaming journeys and comprehensive concurrent/load tests remain unverified. No Phase 9 implementation was started.
