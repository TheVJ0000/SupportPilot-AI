# Supabase setup

SupportPilot AI uses the **Supabase Free plan** for its initial portfolio development and public demo. Recheck the current free-plan limits before deployment and do not enable paid billing for this stage.

## Create the project

1. Sign in to the [Supabase Dashboard](https://supabase.com/dashboard) and create a Free project manually.
2. Keep the generated database password in a password manager. Never commit it.
3. Open the project's **Connect** dialog to copy the Project URL and default publishable key. Individual keys are managed under **Settings → API Keys**.
4. Copy the repository's `.env.example` to `.env` and add only your local values.

No real client or confidential data should be used during the portfolio stage. Use synthetic demonstration content only.

## Key placement

Publishable keys identify a public application component. They do not grant user identity and remain constrained by database grants and Row Level Security.

| Runtime | Variables | Rule |
| --- | --- | --- |
| Browser | `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Publishable key only; values are bundled into client code. |
| FastAPI server | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Used to verify authenticated user JWTs. The publishable key supports the documented legacy-token fallback. |
| Privileged customer-chat operations | `SUPABASE_SECRET_KEY` | Server-only; bypasses RLS and is used only by the Phase 5A fixed allow-list RPC gateway. |

Never place `SUPABASE_SECRET_KEY` in a `VITE_` variable or frontend source. Normal user requests carry the user's Supabase access token and rely on RLS or verified FastAPI identity rather than a secret-key client. The backend does not need the JWT signing secret.

For Phase 5A, set a current Supabase secret key in the FastAPI environment only. The narrow gateway sends it only as the Data API `apikey`; it does not combine it with a customer JWT or put it in an `Authorization` header. Secret keys map to the privileged service role and bypass RLS, so the migration removes generic direct table privileges and grants that role only the named customer-chat `SECURITY DEFINER` functions. If the variable is missing, the application still starts and only customer-chat persistence endpoints return `503`.

See Supabase's current [API key guide](https://supabase.com/docs/guides/getting-started/api-keys) for key creation and rotation details.

## Apply the migration

The versioned migration is in `supabase/migrations/`. With the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started) installed:

```bash
supabase login
supabase link --project-ref <your-project-ref>
supabase db push --dry-run
supabase db push
```

Do not commit the project reference, database password, access token, or generated local credentials. Review the dry run before applying the migration.

## Verify schema and RLS

The migration must result in:

- RLS enabled on `profiles`, `workspaces`, and `workspace_members`;
- browser roles receiving only the explicit grants defined in the migration;
- authenticated users seeing only their own profile and membership row;
- workspace reads limited to members and workspace management limited to owners;
- direct browser insertion or role changes in `workspace_members` remaining unavailable;
- `create_workspace` atomically creating the workspace and its caller-owned membership.
- one unpredictable `workspace_chat_configs.public_id` being backfilled/generated per workspace and visible only to that workspace's authenticated members;
- no raw customer-session token column, a strictly formatted SHA-256 hash, and a maximum seven-day expiry;
- no direct `anon`, `authenticated`, or service-role table access to customer session/conversation data beyond member-scoped RLS reads of safe conversation tables;
- all seven customer-chat RPCs executable only by `service_role`, with each independently deriving and validating the session/workspace relationships relevant to its operation;
- idempotent turn creation, bounded messages/turn counts, atomic answer/citation completion, safe retryable failure codes, and no vectors in customer retrieval results;
- RLS enabled on `knowledge_sources`, with member reads and no direct browser mutation grants;
- owners/admins creating sources only through the scoped RPCs;
- members unable to create, upload, update, or delete knowledge sources;
- non-members unable to read another workspace's source metadata or private objects;
- the `knowledge-files` bucket remaining private with a 10 MB file limit.
- `recover_file_knowledge_source(uuid)` executable only by authenticated callers and authorizing only owners/admins of the source's derived workspace;
- interrupted upload recovery checking the exact stored path, moving an existing object only to `pending`, or removing only an absent-object `uploading` row.
- extraction lifecycle metadata constrained to safe counts and approved machine-readable error codes;
- `knowledge_chunks` bound to its source workspace by a composite foreign key, readable only to workspace members, with no browser mutation grants;
- extraction lifecycle RPCs deriving workspace and manager authorization from the locked source row;
- completion validating the full chunk payload before atomic replacement and returning the source to `pending`, never `ready`.

The pgTAP suite is in `supabase/tests/database/`. Local database tests require Docker and the Supabase CLI:

```bash
supabase start
supabase db reset
supabase test db
```

The local stack is development-only. Do not expose it to external traffic. After applying the migrations to a remote development project, repeat the access scenarios with separate test users before beginning Phase 4.

## Configure private knowledge storage

The Phase 3A migration creates and configures `knowledge-files` as a private bucket. Do not make it public in the Dashboard. SupportPilot enforces a 10 MB maximum and supports:

- PDF (`application/pdf`);
- DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`);
- TXT (`text/plain`);
- Markdown (`text/markdown`, with `text/plain` accepted for browser compatibility).

The database generates object paths in the form `<workspace-id>/<source-id>/<source-id>.<ext>`. The original filename is metadata only and never becomes an arbitrary Storage key. Owners/admins can upload and delete initialized objects; members have read-only access; non-members have no access. All browser operations use the signed-in user's JWT, the publishable key, and RLS.

Creation flows stop at `pending`. Extraction uses `processing_stage=extraction` and successful extraction returns to `pending`; indexing uses `processing_stage=indexing` and only atomic vector completion reaches `ready`. Extension and MIME validation are not treated as proof of file contents; downloaded bytes are validated before extraction.

General source deletion is not exposed in Phase 3A. Failed upload initialization can be canceled only after the Storage API confirms removal of the expected object, avoiding direct edits to Storage metadata or a database-only delete. If an `uploading` row remains after an interrupted request, an owner/admin can select **Recover upload**. The recovery RPC accepts only the source ID, locks and authorizes the stored row, and checks its exact private object path: an existing object becomes `pending`, while an absent object removes only that stale row. It also confirms an already-`pending` source without mutation after a lost finalize response.

## Configure Phase 3B extraction

The FastAPI server requires the existing `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. It reuses each request's verified bearer token to call the scoped extraction RPCs and download the exact private object. `SUPABASE_SECRET_KEY` is not used by this workflow. Install backend dependencies again after pulling Phase 3B so `pypdf` and `python-docx` are available.

Processing remains explicit through **Process source** or **Retry processing**. Actual downloads are capped at 10 MB regardless of metadata. PDFs are limited to 300 pages; encrypted, malformed, scanned, or image-only PDFs are rejected, and OCR is not currently supported. DOCX containers allow at most 2,000 entries, 50 MB total uncompressed data, and 20 MB for an individual member, with traversal and unsafe active/entity content rejected. TXT and Markdown require UTF-8 (a BOM is accepted). No files are extracted to permanent disk.

Normalized text is capped at 1,000,000 characters and produces at most 1,000 deterministic chunks. Locators use 1-based PDF pages, 1-based DOCX structural blocks, source line ranges for text/Markdown, or `{ "kind": "faq" }`. Successful extraction returns to `pending` with `extracted_at`, counts, and chunks populated. This means **extracted and awaiting indexing**.

## Configure Phase 3C indexing

Set `GEMINI_API_KEY` only in the backend environment. Keep `EMBEDDING_PROVIDER=gemini`, `GEMINI_EMBEDDING_MODEL=gemini-embedding-2`, and `GEMINI_EMBEDDING_DIMENSION=768` unless a future migration deliberately changes the stored vector dimension. Never create a `VITE_` Gemini variable. The app starts without the key; indexing then returns a controlled unavailable response. Document chunks use the model's current retrieval-document title/text format; query embeddings remain deferred to Phase 4.

The migration enables pgvector, adds a 768-dimensional vector column and one cosine HNSW index, and exposes only scoped lifecycle RPCs. Apply migrations before testing indexing. Use only synthetic/demo/non-confidential content on the free Gemini tier, do not enable paid billing, and verify the active project quota in Google AI Studio before a public demo.

## Configure authentication

1. Put the same project URL and publishable key in both frontend and backend variables in the local `.env` file. Do not add the secret key.
2. In the Supabase Auth URL settings, set the local site URL to `http://localhost:5173` while developing. Add only explicit redirect URLs that the application actually uses.
3. Choose whether email confirmation is required for the development project. The registration UI supports both an immediate session and a confirmation-required response.
4. Start FastAPI and the frontend with the commands in the repository README.

## Configure Phase 5A customer chat

Apply the Phase 5A migration, then add `SUPABASE_SECRET_KEY` only to the backend process. An anonymous browser starts with `POST /api/chat/{public_id}/session`; the raw opaque token is returned once and must be retained only by the browser client. Subsequent non-streaming turn and history calls send it in `X-SupportPilot-Session`. They must not use a Supabase bearer token for this credential.

The supported flow is:

```text
public chat ID
→ anonymous opaque customer session
→ persistent conversation and idempotent turn
→ customer-session-scoped retrieval
→ existing grounded RAG engine
→ atomically persisted assistant answer and citation snapshots
```

Use only synthetic/non-confidential content. Phase 5A does not include a hosted chat UI, streaming, conversation-aware query rewriting, feedback, or human-request handling.

For modern asymmetric signing keys, FastAPI validates tokens with the project's `/auth/v1/.well-known/jwks.json` endpoint using a cached JWKS client and fixed ES256/RS256 algorithms. Legacy HS256 tokens are validated by Supabase Auth's `/auth/v1/user` endpoint with the publishable key. Issuer, audience, expiration, subject, and signature/provider validity are not bypassed.

## Hosted smoke-test checklist

### Phase 6 triage and recovery configuration

Apply `202609160009_escalation_triage_foundation.sql` after the existing migrations; do not edit or reapply earlier migrations manually. It backfills pending escalation placeholders for existing `human_requested` conversations and replaces the human-request RPC with an internal result carrying escalation metadata. The public customer contract remains unchanged.

Then apply `202609160010_escalation_automation.sql`. It atomically escalates newly persisted insufficient-evidence answers without changing conversation status, generalizes triage eligibility and adds the recovery/notification RPCs plus outbox. It does not retroactively escalate every historical insufficient-evidence message; it does enqueue already-completed triage notifications. Earlier migrations are unchanged.

Use server-only `GEMINI_API_KEY` and optional `GEMINI_TRIAGE_MODEL=gemini-3.8-flash`; never define `VITE_GEMINI_*`. This uses the existing Gemini free-tier integration and server-only `SUPABASE_SECRET_KEY` through fixed scoped RPC allow-lists. Do not enable billing or paid fallback; use synthetic/non-confidential transcripts. Missing Gemini leaves worker triage pending and consumes no attempts. The immediate human-request task may safely record `triage_not_configured`; after configuration/restart, eligible failures recover after 15 minutes. The app still starts without AI or Supabase configured.

On a disposable Supabase test environment, run `supabase db reset` and `supabase test db`, including `escalation_triage_security.test.sql`. Then verify a repeated human request produces one escalation, the anonymous response contains no internal triage fields, and a successful native tool call completes the matching audit attempt. Exercise missing-key/provider failure and confirm the escalation remains durable. Workspace nonmembers and anonymous browsers must not read escalation/audit rows; browser writes and triage RPC calls must be denied.

The lifespan worker runs immediately and every 60 seconds with at most 10 triage records then 10 notifications, concurrency two per stage. Database list and locked begin share caps/backoff: maximum three attempts, processing/sending stale by 15 minutes, transient failed backoff 15 minutes. Triage retries only not-configured/rate-limited/provider-unavailable/failed errors. Notification retries only rate-limited/provider-unavailable/failed errors. Auth, invalid tool, invalid email configuration, no recipients and delivery unknown are not automatically retried. Immediate human-request claims obey the same triage policy. Exhausted/stale-cap records remain durable for later review. No paid queue is used. See [exact policy](ARCHITECTURE.md#durable-recovery-policy).

Include `escalation_automation_security.test.sql` in `supabase test db`: verify trigger uniqueness/open status, later human-request reuse, generalized eligibility, failed backoff/caps, member-only outbox SELECT, denied writes/RPC access, verified owner/admin recipients, no-recipient state, stale-send fencing and sent idempotency. Test streaming/non-streaming customer answers without exposing escalation internals. These pgTAP and hosted/Gemini checks have not been claimed as executed locally.

### Optional Resend delivery at zero cost

Leave `RESEND_API_KEY` and `RESEND_FROM_EMAIL` blank to keep notifications pending without external delivery. These are server-only; the API key is `SecretStr` and must never use a `VITE_` variable. Invalid local sender configuration disables attempts rather than failing startup. No new SDK is required: existing `httpx` sends deterministic plain-text email over HTTPS after completed triage only. Recipients are at most 20 deduplicated, verified, non-deleted workspace owner/admin auth emails derived inside a service-role-only security-definer RPC. Ordinary members, other workspaces and anonymous customers cannot choose recipients. Addresses are not persisted in the outbox; no customer transcript, triage summary or session data is emailed.

[Resend's current official Free plan](https://resend.com/pricing) provides $0, 3,000 transactional emails/month, 100/day and three domains (rechecked September 17, 2026); the [transactional product page](https://resend.com/products/transactional-emails) confirms no credit card is required. Select only Free, and do not enable paid billing/pay-as-you-go or buy a domain. Review active quota before any demo; recipients count toward email limits. The [default testing sender](https://resend.com/docs/api-reference/errors), `onboarding@resend.dev`, sends only to the Resend account email. Arbitrary workspace manager delivery needs an already-owned domain verified in Resend and an address on it. If that domain is unavailable, keep delivery disabled; SupportPilot itself does not require a paid domain or a card.

Provider requests reuse `supportpilot-escalation/<notification-id>`, with at most two short immediate retries. Database sent state is final; attempt-number checks fence stale delivery results. Read/write/network ambiguity, exhausted 408/5xx, malformed success, 409 conflict, cancellation or unconfirmed DB completion stops automatic retries with delivery unknown. Because [Resend keys expire after 24 hours](https://resend.com/docs/dashboard/emails/idempotency-keys), database recovery refuses resend beyond a conservative 23-hour first-attempt window, even after long downtime. Changed recipient/configuration payloads under a key may need later review. This is not an exactly-once delivery guarantee.

No live Resend email or arbitrary-recipient delivery was tested. Before enabling optional delivery, use synthetic manager accounts and an appropriate verified sender, confirm deterministic minimal copy, recipient isolation, sent idempotency and safe errors. Email failure must leave triage completed and customer data intact. Apply/test the migration in a disposable Supabase project first. A limited native PostgreSQL fixture smoke applied migration 010 and exercised trigger/triage/outbox/recipient/backoff/fencing/grant behavior; it is not the full Supabase/pgTAP RLS suite, and its temporary server was stopped afterward.

On September 16, 2026, an isolated native PostgreSQL instance successfully applied the Phase 6A migration using minimal prerequisite fixtures and checked the RPC lifecycle, stale-worker fencing, audit consistency, and grants. This limited smoke check did not run the full Supabase migrations, member RLS suite, or pgTAP tests. The temporary instance was shut down afterward. Google's [current Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) lists standard `gemini-3.8-flash` input/output (including thinking) as free of charge on the Free tier; keep the project on that tier and verify its active quota before any demo. No live model call or billing change was made.

Use synthetic accounts only, then verify:

- registration creates the user profile through the database trigger;
- both immediate-session and email-confirmation behavior match the project setting;
- login survives a page reload and protected routes remain inaccessible after logout;
- a new account sees workspace onboarding and `create_workspace` produces owner membership;
- one workspace auto-selects, multiple accessible workspaces can be selected, and inaccessible IDs are discarded;
- the application shell reports `Authenticated API connected` while `/api/auth/me` rejects missing or invalid bearer tokens;
- a second test user cannot read the first user's profile, membership, or workspace.
- a workspace member can read only their safe public chat configuration, while another workspace cannot discover it;
- session creation works from the public chat ID without exposing an internal workspace ID or token hash;
- a wrong, expired, cross-workspace, or disabled-chat session credential cannot start a turn or restore history;
- retrying one client message ID never duplicates its customer message or completed assistant answer;
- customer retrieval returns only compatible ready chunks from the session-derived workspace and no vectors;
- completed answers restore in chronological history with their exact trusted citation snapshots;
- an owner and admin can add file/FAQ sources while an ordinary member sees read-only controls;
- unsupported or oversized files are rejected before upload and again by trusted infrastructure;
- private object reads/uploads/deletes follow the workspace role policies;
- an interrupted upload exposes recovery only to owners/admins, and a member/non-member cannot invoke the recovery RPC successfully;
- recovery moves an exact existing object to `pending`, removes only an absent-object stale row, and does not change other lifecycle states;
- owners/admins can process pending and failed sources while members/non-members cannot start extraction;
- malformed, encrypted, oversized, non-UTF-8, binary-like, and no-text fixtures fail with an approved safe code and no raw parser detail;
- completed extraction stores sequential workspace-bound chunks with truthful locators and leaves the source `pending`;
- retrying replaces the old chunk set atomically, while a failed replacement preserves the prior complete set;
- successful files remain `pending`, not `ready`, until a later processing phase.

This repository run did not have a hosted project configured, so these checks have not been claimed as executed.
