# SupportPilot AI — Architecture

## Architecture goals

SupportPilot AI should use a simple, maintainable architecture suitable for a professional portfolio project. The design must preserve strong tenant isolation, grounded RAG answers, replaceable AI providers, and a bounded agent model without introducing unnecessary enterprise complexity.

## High-level application architecture

```mermaid
flowchart LR
    U[Admin / Customer Browser] --> FE[React + TypeScript Frontend]
    FE --> API[FastAPI REST API]
    API --> SVC[Application / Service Layer]
    SVC --> DB[(Supabase PostgreSQL)]

    FE -. authentication .-> AUTH[Supabase Auth]
    SVC --> AUTH
    FE -->|Authenticated private uploads| STORAGE[Supabase Storage]
    SVC --> STORAGE
    SVC --> VEC[pgvector]
    SVC --> AI[AI Provider Abstraction]
    AI --> GEM[Gemini API - initial provider]
    SVC --> JOBS[Bounded In-Process Recovery Worker]
    JOBS -. optional .-> EMAIL[Resend Email Notifications]
```

### Responsibilities

- **React frontend:** admin and customer interfaces, client-side interaction, streaming response UX, and authenticated application flows.
- **FastAPI REST API:** trusted backend boundary for validation, authorization, orchestration, and external API behavior.
- **Application/service layer:** business rules, workspace scoping, RAG orchestration, document processing, conversation handling, escalation logic, and provider abstractions.
- **Supabase PostgreSQL:** relational application data.
- **Supabase Auth:** identity and authentication.
- **Supabase Storage:** uploaded source documents.
- **pgvector:** workspace-scoped vector storage and similarity retrieval.
- **AI provider abstraction:** isolates model-provider-specific generation and embedding logic so providers/models remain configurable and replaceable.
- **Background automation:** a bounded FastAPI lifespan worker, with durable work state and eligibility in PostgreSQL rather than an external paid queue.
- **Email notifications:** optional deterministic Resend integration after checking its Free plan; no provider credentials are required to run the app.

## Authentication and workspace foundation

Supabase Auth is the identity provider. A reusable frontend auth provider restores the Supabase-managed session, subscribes to auth changes, and protects `/app` routes without separately storing access tokens. Registration passes `display_name` as user metadata so the existing database trigger owns profile creation. Login, email-confirmation-required, and logout states are handled explicitly.

Browser code uses only the project URL and publishable key. After sign-in, the workspace provider reads `workspaces` through RLS and creates a workspace only through `create_workspace(workspace_name)`. A selected workspace ID may be stored locally for convenience, but it is always revalidated against the currently accessible RLS result and is never treated as authorization.

Authenticated FastAPI requests flow through one API client that applies the active session's bearer token. The backend authentication dependency:

- verifies ES256/RS256 tokens with the project's JWKS endpoint and cached signing keys;
- fixes the accepted algorithms, issuer, `authenticated` audience, expiration, and subject requirements;
- uses Supabase Auth's user endpoint with the publishable key for legacy HS256 projects that cannot be verified by JWKS;
- returns only the verified user ID and optional email from `/api/auth/me`.

No JWT signing secret is requested or stored. `SUPABASE_SECRET_KEY` is not part of ordinary auth, workspace, Knowledge Base, or business RAG request handling. Phase 5A uses it inside a narrow server-side customer-chat RPC gateway because anonymous customers have no Supabase identity; Phase 6 adds separate gateways restricted to four triage and four notification lifecycle/listing RPCs. There is no generic privileged query client.

The initial Phase 2A data model contains only:

- `profiles`, keyed directly to `auth.users.id`;
- `workspaces`, with a recorded creator;
- `workspace_members`, with one `owner`, `admin`, or `member` role per user/workspace pair.

Every table has RLS enabled plus explicit grants and operation-specific policies. Private `SECURITY DEFINER` helpers check the caller's membership or owner role without recursively invoking membership policies. They derive identity from `auth.uid()`, use an empty fixed `search_path`, and expose no caller-supplied user-ID authority.

Workspace creation uses one narrowly scoped RPC. It validates the name, inserts the workspace, and creates the authenticated caller's owner membership atomically. Direct client writes to membership roles are not allowed in this phase.

## Knowledge-source storage foundation

Phase 3A introduces `knowledge_sources` as the workspace-owned record for uploaded files and manual FAQs. It records only source metadata/content needed at this stage—never uploaded binary data or embeddings. Statuses cover `uploading`, `pending`, `processing`, `ready`, and `failed`; Phase 3A creation flows stop at `pending` so the UI never implies that unprocessed material is ready for retrieval.

File uploads use this controlled sequence:

```mermaid
flowchart LR
    UI[Owner/Admin Knowledge UI] --> BEGIN[begin_file_knowledge_source RPC]
    BEGIN --> ROW[Source row: uploading]
    ROW --> STORE[Authenticated Storage API upload]
    STORE --> FINAL[finalize_file_knowledge_source RPC]
    FINAL --> PENDING[Source row: pending]
```

The database generates the creator, source UUID, status, and object path. Objects live in the private `knowledge-files` bucket under `<workspace-id>/<source-id>/<source-id>.<ext>`, are capped at 10 MB, and accept PDF, DOCX, TXT, or Markdown MIME types. Uploads use `upsert: false`; no Storage UPDATE policy exists, so object overwrite is unavailable.

Workspace owners and admins can initialize uploads, add FAQs, and remove failed-upload objects. Members can read permitted source metadata and private objects but cannot create, upload, update, or delete. Non-members have no access. Storage policies authorize an exact trusted source path through workspace membership rather than object ownership or caller-provided paths.

Failed uploads attempt Storage API cleanup before the narrowly scoped cancel RPC removes an `uploading` row. Cleanup checks both Supabase error results and thrown failures; metadata is never canceled unless object removal is explicitly confirmed. If finalization fails after a successful upload, the client makes exactly one recovery call and never reuploads or overwrites the object.

The recovery RPC accepts only a source UUID, derives workspace/status/path from a locked row, and authorizes the caller as that workspace's owner/admin. It checks only the exact trusted path in the private bucket. An existing object moves `uploading` to `pending`; an absent object removes only that stale row. An already-`pending` source with its exact object can be confirmed without mutation, making a lost finalize response idempotent. Other non-uploading states fail closed. Retained `uploading` rows expose a manager-only **Recover upload** action. General source deletion remains deferred because browser-side deletion across Storage and PostgreSQL cannot be made atomic without introducing a misleading partial-delete workflow.

## RAG ingestion flow

```mermaid
flowchart LR
    UP[Document Upload / Manual FAQ] --> STORE[Secure File Storage]
    STORE --> EXTRACT[Text Extraction]
    EXTRACT --> CLEAN[Cleaning / Normalization]
    CLEAN --> CHUNK[Chunking]
    CHUNK --> EMBED[Embedding Provider Abstraction]
    EMBED --> VECTOR[(PostgreSQL + pgvector)]
    VECTOR --> STATUS[Processing / Indexing Status]
```

Phase 3B implements deterministic extraction and chunk storage. Phase 3C completes ingestion with provider-abstracted embeddings and atomic pgvector indexing. Both protected FastAPI endpoints accept only a source UUID. The internal auth context retains the already-verified user access token without serializing, logging, or persisting it. A narrow gateway calls lifecycle RPCs using the publishable key plus that user's bearer token; no secret-key client is used.

`begin_knowledge_extraction` locks the source, derives its workspace, authorizes an owner/admin, moves `pending` or `failed` to `processing`, and rejects a second request unless the prior attempt is over 15 minutes old. File bytes are held in memory and hard-limited to 10 MB. PDFs require a valid signature, are rejected when encrypted or over 300 pages, and preserve 1-based page locators. OCR is not included, so scanned/image-only PDFs fail with no extractable text. DOCX parsing first validates the ZIP container (2,000 entries, 50 MB total expansion, 20 MB per member), rejects traversal, encrypted/macro/embedded-active content and XML entity declarations, then extracts paragraphs and tables in structural order. TXT/Markdown are UTF-8-only and preserve line ranges. FAQs use canonical question/answer text without Storage access.

Normalization uses Unicode NFC, stable newline/whitespace handling, control-character removal, and preserved block boundaries. Deterministic character/paragraph-aware chunking targets 1,400 characters, caps chunks at 2,000 characters (below the 2,200-character database ceiling), and uses up to 180 characters of overlap when it fits. Oversized blocks prefer sentence and word boundaries before a hard character split. Every chunk receives a zero-based index, lowercase SHA-256 digest, exact character count, and an aggregated locator: PDF pages, DOCX structural blocks, text/Markdown lines, or FAQ kind.

`complete_knowledge_extraction` validates the entire JSON chunk set before atomically replacing prior chunks and returning the source to `pending`; that state means extracted and awaiting indexing. Phase 3C's indexing RPC locks the source, returns the complete trusted chunk set in order, and records an explicit indexing stage. Gemini Embedding 2 receives only normalized text and title metadata formatted according to its current retrieval-document guidance, in bounded batches, with 768-dimensional responses checked for count, type, finiteness, and size. Completion rechecks every chunk SHA-256 token and atomically writes all vectors plus the `ready` source metadata. `ready` means all current chunks were successfully embedded. Any failure retains the extracted chunks and uses an indexing-only retry path. Workspace members may read chunks through RLS, while browser roles cannot read or modify raw embeddings.

### Ingestion principles

- Processing must preserve `workspace_id` ownership.
- File type and input validation should happen before processing.
- Extracted text should be cleaned before chunking.
- Chunk metadata should retain enough source information to support later citations.
- Embeddings are generated through an abstraction layer; Gemini embeddings are the initial zero-cost default, not a permanent architectural dependency.
- Raw secrets or privileged storage credentials must never be exposed to the frontend.

## RAG question flow

```mermaid
flowchart LR
    Q[Customer Question] --> QE[Query Embedding]
    QE --> RET[Workspace-Scoped Similarity Retrieval]
    RET --> CHECK{Evidence Available and Sufficient?}
    CHECK -- Yes --> GEN[Grounded Gemini Generation]
    GEN --> VALIDATE[Structured Output Validation]
    VALIDATE --> CIT[Server-Validated Citations]
    CIT --> ANSWER[Grounded Answer]
    CHECK -- No --> FALLBACK[Deterministic Insufficient-Evidence Response]
```

Phase 4A implements the retrieval steps. The provider abstraction formats document chunks as `title: {title} | text: {content}` and questions as `task: question answering | query: {question}` for Gemini Embedding 2, with both sides fixed at 768 dimensions. The protected `/api/rag/retrieve` diagnostic endpoint normalizes a 2–2,000 character question, embeds it once, and calls a single user-JWT-scoped Supabase RPC.

The SQL function verifies workspace membership before searching and includes workspace, `ready` status, non-null vector, provider, model, and dimension compatibility in the ranked query itself. It orders by cosine distance using the existing HNSW index, defaults to eight matches, caps requests at twelve, and returns `1 - cosine_distance` with citation-ready content and unchanged locators. Raw embeddings remain outside the response and ordinary column grants. No answerability threshold is hard-coded because later RAG evaluation must calibrate it; Phase 4B owns evidence evaluation and grounded generation.

Phase 4B adds the protected `/api/rag/answer` endpoint without changing retrieval semantics. It calls the Phase 4A service exactly once, immediately returns a fixed insufficient-evidence message when no chunks exist, and otherwise labels ranked chunks `E1` through `E8`. Only the normalized question and at most 20,000 characters of evidence content plus minimal source metadata are passed to the replaceable generation-provider interface.

The initial implementation uses Gemini `gemini-3.8-flash` with low thinking, a 1,200-token output limit, and a Pydantic structured-output schema. Retrieved documents and the user question are serialized as JSON and explicitly treated as untrusted data. The model receives no tools, function calling, Google Search grounding, URL context, database access, or raw embeddings. Prompt-injection resistance is defense in depth rather than a mathematical guarantee.

The model may return only `answerable` with a bounded answer and request-local evidence labels, or `insufficient_evidence` with no answer or labels. No fixed cosine threshold is used: when matches exist, the model evaluates their actual content rather than answering from general knowledge. The server validates every returned label, removes duplicate references deterministically, restores retrieval order, and constructs citation titles, types, indices, UUIDs, and locators solely from trusted retrieval results. Unknown labels or malformed structured output fail safely; the model never supplies final citation metadata. Phase 5A reuses this same orchestration for anonymous customer turns.

## Customer conversation flow

```mermaid
flowchart LR
    ID[Unpredictable public chat ID] --> SESSION[Opaque seven-day customer session]
    SESSION --> TURN[Idempotent persistent customer turn]
    TURN --> CONTEXT[Bounded recent persisted context plus current question]
    CONTEXT --> EMBED[One query embedding]
    EMBED --> RET[Session-scoped knowledge retrieval]
    RET --> PREFIX[Structured Gemini stream: decision then evidence IDs]
    PREFIX --> VALIDATE[Validate request-local evidence IDs]
    VALIDATE --> DELTA[Stream decoded grounded answer text]
    DELTA --> FINAL[Final structured validation]
    FINAL --> SAVE[Atomic answer and trusted citation snapshot]
    SAVE --> HISTORY[Conversation history API]
    SAVE --> FEEDBACK[Customer rating persisted on assistant message]
    HISTORY --> HANDOFF[Confirmed human request]
    HANDOFF --> PAUSE[human_requested status blocks AI turns]
```

Phase 5A introduces one enabled chat configuration per workspace, SHA-256-only customer-session records, conversations, idempotent turns, customer/assistant messages, and historical citation snapshots. FastAPI generates at least 256 bits of token entropy, returns the raw token only once, hashes it immediately on later requests from `X-SupportPilot-Session`, and never stores or logs the raw value. A conversation is limited to 100 customer turns; messages, answers, citations, and retrieval counts are bounded. Sessions remain anonymous and collect no name, email, phone, IP address, location, or browser fingerprint. Robust public abuse/rate limiting remains Phase 8 work.

The two security paths remain deliberately separate:

- Business/admin operations use a Supabase user JWT, the publishable key, and RLS.
- Anonymous customer operations use an opaque customer session through FastAPI, a fixed allow-list customer-chat gateway, and server-only RPCs invoked with `SUPABASE_SECRET_KEY`.

The secret key bypasses RLS, so it never reaches browser code and cannot be used through a generic privileged client. Direct table privileges are withheld even from the service role. Every public-chat RPC independently derives and validates the session/workspace relationships relevant to its operation, and returns only its bounded safe result. The original member-authorized `search_knowledge_chunks` RPC is unchanged; a separate server-only retrieval RPC derives the workspace from the validated customer session and never returns vectors.

The turn-start RPC creates the processing turn and normalized customer message atomically. Its `(conversation_id, client_message_id)` uniqueness prevents duplicate customer messages and generation: completed retries return the persisted answer, processing retries return a safe conflict, and failed turns can retry without deleting their customer message. The completion RPC validates citation data against current trusted workspace chunks before atomically writing an assistant message, citation snapshots, links, and timestamps. Provider exception details are never persisted.

Phase 5B.1 adds the public `/chat/:publicId` React route outside the business authentication boundary. A dedicated frontend API client calls only session creation, conversation history, and turn submission through FastAPI; the opaque token is sent only through `X-SupportPilot-Session`. A public-ID-namespaced local-storage record contains only public ID, conversation ID, session token, expiry, and workspace name. Messages are always restored from server history rather than cached locally. Expired or rejected sessions are cleared and recreated once, while ambiguous turn failures retain the original `client_message_id` for an explicit Retry action.

Phase 5B.2 loads authoritative history only after a new or failed-retry turn begins, verifies that its final message is the normalized current customer question, and excludes exactly that message from prior context. A deterministic helper adds at most the six immediately preceding messages, newest-first within the existing 2,000-character budget, then presents selected messages chronologically with the complete current question. The composed string is used only for the existing query embedding and grounded generation path: it is never accepted from the browser, persisted, logged, returned, or produced by an extra Gemini rewrite call. Conversation text may clarify references, but it remains untrusted and cannot support factual claims or citations; only retrieved Knowledge Base chunks are evidence.

Phase 5B.3 adds one workspace-scoped feedback row per assistant message. Anonymous customers can insert or change only `positive`/`negative` feedback through a session-validated server-only RPC; workspace members receive read-only RLS access for the later admin dashboard. A separate idempotent RPC locks an open conversation, verifies the opaque session and enabled chat, records `human_requested_at`, and transitions it to `human_requested`. Existing history, citations, and feedback remain intact, while the existing turn-start guard blocks new AI turns.

Phase 5B.4 adds genuine provider streaming through the existing `google-genai` Generate Content API and provider abstraction; it does not animate a completed answer character by character and does not introduce another AI SDK. The strict schema is ordered `decision`, `evidence_ids`, then `answer`, allowing the server to fully parse and validate the decision and request-local labels before exposing any decoded answer text. The incremental parser handles arbitrary chunk boundaries and JSON escapes without regex-based extraction. It accumulates the complete JSON for mandatory final Pydantic validation, confirms the final decision, canonical evidence IDs, and answer exactly match the streamed values, then reconstructs citations only from the retrieved metadata.

The streaming customer endpoint is `POST /api/chat/conversations/{conversation_id}/turns/stream` with the existing `X-SupportPilot-Session` credential and request body. Its minimal SSE contract is `started`, zero or more `delta` events, then one authoritative `complete`, or a safe `error` after headers. Retrieval and turn preparation occur before the response starts. A completed idempotent replay emits only its persisted `complete` result and makes no embedding, retrieval, or Gemini call; a processing duplicate fails before SSE; a failed turn can retry with the same client message ID without duplicating the customer message.

Partial assistant text exists only in process memory and one provisional browser message. It is never stored as events, chunks, or partial messages. On cancellation, malformed output, an unknown evidence label, excess answer length, or another stream failure, the turn is marked failed where possible, no assistant message is committed, and the browser removes the provisional response while retaining the original customer message and retry ID. No provider or database details are sent. If retrieval has no matches, Gemini is skipped; if Gemini chooses insufficient evidence, its answer text is not exposed and the deterministic server-owned message is atomically persisted. Citations and feedback controls appear only after completion.

The hosted UI renders all customer, assistant, and citation text as plain text. Citation locations support PDF pages, DOCX blocks, text/Markdown lines, and FAQs without inventing source URLs. It restores feedback and handoff state from the backend, uses inline confirmation before handoff, and disables the composer and human-request actions while a turn streams. After confirmed handoff it blocks new AI turns without claiming that a person is connected or notified. Phase 5 is complete in application code and automated unit/component tests. Live Gemini streaming, hosted Supabase verification, Playwright end-to-end coverage, and broader security/load validation remain Phase 9 work; Phase 6 will add bounded triage/escalation automation.

### Question-answering principles

The normal support Q&A path is RAG, not an autonomous agent.

1. Embed the customer query.
2. Retrieve relevant chunks only from the correct workspace.
3. Select and evaluate evidence.
4. Determine whether available evidence is sufficient.
5. Generate only a grounded answer from approved evidence.
6. Return relevant source citations.
7. Persist the conversation and answer metadata through the Phase 5A customer-chat flow.

When evidence is insufficient, the system should not fabricate an answer. It should return an appropriate fallback and offer or trigger escalation where applicable.

## Escalation agent flow

```mermaid
flowchart LR
    HUMAN[Customer Requests Human] --> ATOMIC[Atomic human_requested + unique escalation]
    UNRESOLVED[Persisted Insufficient-Evidence Answer] --> AUTO[Atomic unique escalation; conversation stays open]
    ATOMIC --> BACKGROUND[Immediate best-effort task plus recovery worker]
    AUTO --> BACKGROUND
    BACKGROUND --> BEGIN[DB eligibility + locked triage attempt + audit run]
    BEGIN --> CONTEXT[Bounded trusted persisted transcript]
    CONTEXT --> AGENT[Gemini requests create_escalation]
    AGENT --> VALIDATE[Validate one tool call and arguments]
    VALIDATE --> TOOL[Explicit application tool executor]
    TOOL --> COMPLETE[Atomic classification + audit completion + pending outbox]
    COMPLETE --> NOTIFY[Bounded optional deterministic email delivery]
    AGENT -. failure .-> FAILED[Durable escalation retained with safe failure code]
```

Phase 6A uses a dedicated `TriageAgent` abstraction, not the grounded RAG provider. It performs one bounded reasoning step and one controlled action, so native Gemini function calling is sufficient; LangGraph is intentionally not introduced. The model is not merely generating prose: it selects arguments for an explicitly declared application tool, and the application validates and executes that action. The only allowed tool is `create_escalation(category, priority, summary)`, which finalizes a database-owned placeholder rather than letting the model create arbitrary records.

The Gemini adapter uses configurable `GEMINI_TRIAGE_MODEL` (default `gemini-3.8-flash`), medium thinking, and a conservative 700-token output limit. It declares the function explicitly, uses function-calling mode `ANY` restricted to that name, and disables automatic SDK execution. These settings follow the [Generate Content function-calling contract](https://ai.google.dev/gemini-api/docs/generate-content/function-calling). There are no Python callables given to Gemini, built-in tools, search, URL context, shell/code execution, retrieval, notifications, or model database access. Temporary provider failures receive at most two retries; invalid tools/arguments and authentication failures are not retried. There is no agent loop.

Agent input contains only the trigger reason and recent persisted message roles/content/answer status. SQL returns at most 20 recent messages; a pure helper removes older messages first to enforce 12,000 content characters, preserves whole newest messages, and restores chronological order. No session token/hash, JWT, record IDs, emails, vectors, storage paths, or citation metadata is sent. Transcript instructions remain untrusted data. A fixed executor rejects unknown tools, validates strict Pydantic category/priority/summary arguments (summary 1–1200 trimmed characters), and binds escalation/run IDs and provider metadata from trusted application context. PostgreSQL validates them again. This enforces limited authority; it does not claim mathematical prompt-injection immunity.

The human-request RPC preserves session authorization and creates/reuses the escalation in the same transaction as `human_requested`. Internal escalation ID/triage status are stripped from the unchanged anonymous public response. Only then is triage scheduled. Missing Gemini configuration marks the attempt `failed / triage_not_configured` where storage is reachable; any AI error leaves the human request and escalation intact. The background runner owns its own clients, does not rely on request-scoped resources, and never exposes triage errors to the customer.

`begin_escalation_triage` locks the escalation and derives workspace/conversation eligibility: human-request escalations require a human-requested conversation; insufficient-evidence escalations allow open or human-requested conversations. Closed conversations are excluded. Completed/recent-processing attempts exit without Gemini. All callers, including immediate human-request tasks, obey the same database cap/backoff policy below. Stale processing marks the old run `failed / stale_triage_recovered` before starting a new run; completion/failure must match the active attempt number. `complete_escalation_triage` atomically commits classification, matching audit completion and notification creation through an AFTER trigger in its transaction. A failing outbox insertion rolls back the whole completion, never just the outbox. `fail_escalation_triage` stores only allow-listed codes. Audit records never contain prompts, transcript copies, raw payloads or chain-of-thought.

Escalation, audit and outbox tables now have owner/admin-only SELECT RLS (hardened by Phase 7A migration 011) and no direct anon/browser/service-role writes. Existing automation lifecycle RPCs are granted solely to `service_role`, with fixed empty SQL search paths. Migration 010's AFTER INSERT message trigger creates/reuses an insufficient-evidence escalation in the answer-persistence transaction, covering streaming, non-streaming and retries without waiting for triage. It does not change conversation status. A later explicit human request reuses the escalation, preserves classification/audit and stops AI turns.

### Durable recovery policy

The lifespan worker starts only with server-side Supabase URL/secret configuration, runs immediately then sleeps 60 seconds, and is canceled/awaited before clients close. Each cycle handles at most 10 triage IDs, concurrency two, then at most 10 notification IDs, concurrency two. Exceptions never crash API requests or log provider data. Missing Gemini skips both triage listing and claiming; missing/locally-invalid Resend configuration skips notification listing/claiming. The existing immediate human-request background task may record one `triage_not_configured` failure; after configuration/restart the worker recovers eligible work.

Database listing limits are 1–20; both list and locked begin recheck the same policy, protecting against listing/claim races and multiple API instances. Work is best effort while the process is alive; PostgreSQL provides durability. There is no external queue or exactly-once email guarantee.

| Work | Automatic eligibility | Excluded |
| --- | --- | --- |
| Triage | Attempts <3; pending, processing stale ≥15 minutes, or failed ≥15 minutes with `triage_not_configured`, `triage_rate_limited`, `triage_provider_unavailable`, `triage_failed` | Completed, recent processing, auth/invalid-tool failure, closed/resolved escalation, closed conversation, cap exhausted |
| Notification | Attempts <3; pending, sending stale ≥15 minutes, or failed ≥15 minutes with `notification_rate_limited`, `notification_provider_unavailable`, `notification_failed`; related triage must be completed | Sent, recent sending, auth/configuration/no-recipient/delivery-unknown failure, cap exhausted |

Cap-exhausted stale records remain durable for later operational review; Phase 7 manual-recovery UI is not implemented. SQL claim checks apply to immediate tasks too, so repeated human requests cannot burn unlimited AI attempts or bypass backoff. No retries are driven by customer input or Gemini-selected IDs.

### Deterministic notification outbox

`escalation_notifications` has one row per escalation, composite workspace FK, consistent `pending/sending/sent/failed` states, attempts, safe error code, provider/message ID, delivery/sent timestamps and immutable-in-lifecycle first delivery time. Completion triggers atomically enqueue pending state; migration 010 also enqueues already-completed Phase 6A triage. No recipient snapshot, customer content, AI summary, prompt or session information is stored. Only owners/admins may read their workspace's delivery state after migration 011. The server-only notification begin RPC locks the row, rechecks eligibility/completed triage, increments attempts and derives at most 20 distinct normalized, verified, non-deleted owner/admin auth emails from that workspace. Missing recipients records `notification_no_recipients`, with no automatic retry. Safe context is only notification ID, workspace name, category, priority, recipient emails and attempt number. Complete/fail require the active attempt number and completed related escalation; stale workers cannot overwrite a newer attempt. Sent completion can replay only matching attempt/provider/message metadata.

The replaceable `EscalationNotifier` protocol has only optional Resend implemented. Server-only `RESEND_API_KEY` is `SecretStr`; `RESEND_FROM_EMAIL` is optional and syntax-checked without blocking startup. Existing `httpx` sends to fixed HTTPS `/emails` with Bearer, JSON, `SupportPilot-AI/0.1` and deterministic `Idempotency-Key`. Copy is plain deterministic text: workspace name, category, priority and generic sign-in instruction, never the triage summary or customer content. Only trusted managers receive mail: the first normalized address is `to`, remaining addresses are `bcc`; the configured sender is not added as a recipient.

Within one send, up to two retries wait 0.25/0.5 seconds for 429, 408, 5xx or temporary transport failures, with identical key/body. 401/403 map to auth failure; other 4xx/redirects map to configuration failure; 409 maps to delivery unknown rather than changing the key. Connect/pool failures known to precede acceptance map to provider unavailable. Uncertain read/write failures, exhausted 408/5xx, malformed success, cancellation, or unconfirmed DB completion conservatively map to delivery unknown and do not receive long-delay automatic retries. Prior ambiguity remains tracked even if the last response is 429. This avoids treating an accepted-but-unacknowledged send as a safe new delivery.

Database sent state is the long-term duplicate guard. [Resend keys last 24 hours](https://resend.com/docs/dashboard/emails/idempotency-keys); SQL refuses replay after 23 hours from first delivery start, records delivery unknown and retains state for review. Changed recipients/copy/config under the same key can produce a provider conflict, also requiring review. Neither provider idempotency nor the outbox claims mathematically exactly-once delivery. Notification failure never reverts completed triage or the customer conversation. No recipients, raw provider errors or secrets are logged.

The [official Resend Free plan](https://resend.com/pricing) was rechecked for $0, 3,000 transactional emails/month, 100/day and three domains. Its [test sender restriction](https://resend.com/docs/api-reference/errors) permits `onboarding@resend.dev` only to the account email; other recipients require an already-owned verified sender domain. Do not buy a domain, enable billing/pay-as-you-go or claim untested live delivery. Leave credentials blank to keep SupportPilot itself runnable at ₹0. Only synthetic/non-confidential demo conversations go to Gemini's free tier. No LangGraph, additional tools, Slack, CRM, dashboard/widget, deployment, Redis, Celery or paid queue was added.

## Phase 7A: read-only support operations

`owner/admin → authenticated FastAPI → JWT-scoped support operations RPC → explicit workspace authorization → read-only dashboard`.

React reads operations only through `adminApi.ts` and five GET endpoints under `/api/admin/workspaces/{workspace_id}`: `dashboard`, `conversations`, `conversations/{conversation_id}`, `escalations`, and `escalations/{escalation_id}`. Existing bearer verification supplies `AuthenticatedRequestContext`. The dedicated `AdminOperationsGateway` has five fixed read methods and no generic user-supplied RPC/table proxy; headers use the publishable key plus that verified caller JWT. It never references the secret key. Supabase results are untrusted: extra fields, malformed enums/counts/timestamps/UUIDs/locators, wrong workspace/detail IDs, inconsistent pagination/filter matches, and unsafe error codes are rejected. Provider/database errors return generic 502/503, denied roles/workspaces 403, and foreign/absent records the same 404. Authentication failure remains 401.

Migration `202609160011_admin_operations_read.sql` adds `app_private.can_view_support_operations(uuid)`, caller-bound through `auth.uid()` and owner/admin membership. Its security-definer function has an empty search path. Authenticated EXECUTE is needed for PostgreSQL to evaluate RLS as the requesting role; the private schema is not exposed by PostgREST and returns only a boolean. Private JSON shape builders are not executable by browser/server roles. SELECT policies on `conversations`, `conversation_turns`, `messages`, `message_citations`, `message_feedback`, `escalations`, `escalation_triage_runs`, and `escalation_notifications` replace broad member access with this helper. Knowledge Base member reads are unchanged. Every new public read RPC is security-definer with an empty search path, independently checks workspace authorization, scopes all nested rows, and is granted only to `authenticated`. Existing narrowly scoped service-role customer/automation RPCs are unchanged.

| RPC | Bounded safe output |
| --- | --- |
| `admin_dashboard_snapshot` | 13 metrics and ≤5 recent conversations/escalations each; no transcripts or summaries |
| `admin_list_conversations` | Safe metadata/counts/feedback totals/escalation priority, keyset cursor |
| `admin_get_conversation` | Safe metadata, ≤200 messages (existing 100-turn bound), ordered citation snapshots/feedback, associated escalation |
| `admin_list_escalations` | Classification/summary, lifecycle/triage status, attempts, safe error and notification status, keyset cursor |
| `admin_get_escalation` | Escalation, ≤50 newest audit attempts, safe notification state |

Lists default to 25, allow 1–50, and fetch only limit+1 to determine the next cursor. Conversation ordering is `last_message_at DESC NULLS LAST, id DESC`; a timestamp+ID cursor continues through earlier timestamps then the null bucket. An ID-only cursor denotes null activity and continues by descending UUID among null rows. Time without ID is invalid. Escalations order `created_at DESC, id DESC` and require both timestamp/ID or neither. Fixed enum filters reset the cursor; arbitrary SQL/sort/transcript search is unavailable. Matching workspace/time/UUID indexes support these reads. Detail messages order by turn creation, customer before assistant, message creation then UUID; citations order by saved ordinal. Audits order by descending attempt number. No customer session IDs/hash, vectors, storage paths, notification recipients/provider message IDs, raw model/tool/provider payloads, prompts or reasoning are returned.

Metric definitions: total counts workspace conversations; AI answered/insufficient evidence count distinct conversations with an assistant message in the corresponding answer state; escalated counts distinct conversations with an escalation; human requested counts current conversation status. Positive/negative feedback count rating rows. Open escalations is exactly current `status = open` (not `in_progress`). High/urgent counts escalation rows with completed triage and the respective priority, regardless of operational status. Knowledge counts each source's current ready/processing/failed state, excluding pending/uploading. All metrics are nonnegative strict integers. **AI answered ≠ AI resolved:** answer coverage is answered/total, safely 0% when empty; no resolution rate exists in 7A.

Owner/admin `/app` lands on Dashboard; member lands on Knowledge Base and cannot render any direct operations route. Loading avoids redirect loops; no workspace leads to onboarding. AppShell adds responsive Dashboard/Conversations/Escalations navigation and a shared workspace selector. The operations outlet remounts on workspace, role, or authenticated identity/token changes, discarding old data/filter cursors. Resource keys hide old results synchronously before effects; abort plus active-response fencing blocks late completions. Operations stay in React memory only; no transcript/summary localStorage or sessionStorage. All customer/assistant/source/summary text is plain React text. Priority/status badges include text. Notification pending does not imply configured/delivered; only DB `sent` reports sent. AI summaries/classification are explicitly generated and potentially imperfect.

Validation passes 360 backend and 111 frontend tests plus Ruff lint/format, frontend lint/build and Git whitespace checks. New pgTAP fixtures cover owner/admin/member/nonmember/anon, all five RPCs across tenants, eight-table member RLS denial, preserved Knowledge Base access, exact metrics, filters/cursors, transcript/citations/feedback, audit ordering and notification minimization. **pgTAP was not run and hosted Supabase was not tested** (CLI/Docker unavailable). An isolated native PostgreSQL minimal-fixture smoke applied migration 011 and checked metric/page/detail shapes and role/tenant/RLS behavior; it does not replace full Supabase migration/security regression testing.

Phase 7 is **not complete**. Management mutations and final analytics polish remain 7B. No resolve/close/delete/manual classification/reply/contact/notification retry controls, chart dependency, new external service, AI call, widget or deployment is introduced here.

## Multi-tenancy and isolation

Major business-owned entities will use `workspace_id` so every business's content can be scoped consistently.

```mermaid
flowchart TD
    USER[Authenticated User] --> MEMBERSHIP[Workspace Membership]
    MEMBERSHIP --> WS[workspace_id]
    WS --> DOCS[Documents / Chunks]
    WS --> CONV[Conversations / Messages]
    WS --> FB[Feedback]
    WS --> ESC[Escalations]
    WS --> ANALYTICS[Analytics Data]

    APP[Application Authorization] --> WS
    RLS[PostgreSQL / Supabase RLS where appropriate] --> WS
```

Workspace isolation must be enforced at multiple layers:

- application authorization and service-layer queries must scope access by `workspace_id`;
- retrieval must never search embeddings from another workspace;
- storage paths and document ownership should be workspace-aware;
- PostgreSQL/Supabase Row Level Security should be used where appropriate as defense in depth;
- privileged credentials must remain backend-only;
- tests should explicitly verify cross-workspace isolation.

## Provider abstraction

Generation and embeddings should be called through application interfaces rather than directly throughout feature code. Initial defaults are Gemini free-tier models, but configuration should make provider/model replacement possible without rewriting the RAG or application layers.

## Database scope

Phase 3C completes ingestion with explicit lifecycle metadata, replaceable embeddings, 768-dimensional pgvector storage, and one cosine HNSW index. Phase 4 adds authenticated workspace-scoped retrieval, evidence-sufficiency decisions, grounded generation and trusted citations. Phase 5 adds anonymous customer conversation/turn/message/citation/feedback persistence plus narrow session-scoped RPCs. Streaming remains transport-only. Phase 6A adds escalation/audit tables and trusted lifecycle RPCs; Phase 6B adds message/outbox triggers, notification state and shared database recovery/claim eligibility in migration 010 without modifying earlier migrations. Phase 7A adds read-only operations RPCs and owner/admin RLS in migration 011, with no new tables or mutation semantics. Management and final analytics polish remain Phase 7B.
