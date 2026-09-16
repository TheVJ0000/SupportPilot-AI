# SupportPilot AI

SupportPilot AI is a full-stack Generative AI customer-support platform being built as a personal portfolio project. It is designed to demonstrate production-minded RAG, bounded AI agents, full-stack application development, APIs, authentication, databases, automation, testing, security basics, and deployment.

## Planned capabilities

- Business authentication and isolated workspaces
- Support knowledge ingestion from documents and FAQs
- Workspace-scoped RAG with grounded answers and citations
- Hosted customer support chat with streaming responses
- Multi-turn conversations and customer feedback
- Safe insufficient-evidence handling
- Bounded Support Triage Agent for escalation workflows
- Admin views for conversations, feedback, sources, escalations, and basic analytics
- Embeddable website support widget

## Planned stack

**Frontend:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui  
**Backend:** Python, FastAPI, Pydantic  
**Data:** Supabase PostgreSQL, Supabase Auth, Supabase Storage, pgvector  
**AI:** Gemini initially, RAG, Gemini embeddings, provider abstraction, LangGraph only where justified  
**Testing:** pytest, Vitest, React Testing Library, Playwright, dedicated RAG evaluation cases

## Current status

**Phase 7A — secure read-only admin operations dashboard, implemented in application code and automated tests.** Workspace owners/admins can view metrics, recent activity, paginated conversations, persisted transcripts/citations/feedback, escalations, bounded triage audit attempts, actual notification status, and knowledge lifecycle counts. Members keep Knowledge Base access but cannot read support operations. The frontend calls authenticated FastAPI REST endpoints; the backend uses the publishable key and verified caller JWT, never a secret key for these reads. Migration 011 tightens SELECT RLS on all eight support tables and adds five explicitly authorized, workspace-scoped read RPCs.

**AI answered ≠ AI resolved.** AI answered counts distinct conversations with at least one assistant `answered` message. AI answer coverage divides that count by total conversations (0% when empty); neither is a resolution rate. Open escalations means exactly `status = open`, excluding `in_progress`. High/urgent counts require completed triage. Knowledge counts are current `ready`, `processing`, and `failed` sources; pending/uploading are not counted as processing.

Owners/admins land on `/app/dashboard`; members land on `/app/knowledge`. Operational navigation adds Conversations and Escalations with detail routes and a shared workspace selector. Lists use server-controlled enums and keyset pagination (25 default, 50 maximum), not transcript search. Workspace/identity changes discard old views, reset cursors, cancel requests, and fence late responses. Customer content/source titles/AI summaries render as plain text and are never persisted in browser storage. There are no resolve/close/delete/reply/contact/retry controls, chart dependencies, new AI calls, or new external services.

**Phase 7 is not complete.** Management mutations and final analytics polish remain Phase 7B; widget/deployment work has not begun. Apply all migrations through `202609160011_admin_operations_read.sql` before using the dashboard. Local validation now passes 360 backend tests, 111 frontend tests, Ruff lint/format, frontend lint/build, and Git whitespace checks. An isolated native PostgreSQL smoke applied migration 011 and checked exact tenant-scoped metrics, timestamp/UUID/null cursor ordering, transcript ordering/citations/feedback, audit/notification shapes, foreign-workspace/record denial, admin success, and member denial across all eight RLS tables. This limited prerequisite fixture is not Supabase: **pgTAP and hosted Supabase were not tested** because Supabase CLI/Docker are unavailable. Run reset/migrations and the full pgTAP security suite in a disposable Supabase environment before relying on it. No live Gemini/Resend calls were made.

**Phase 5 — customer chat UX, complete in application code and automated tests.** Anonymous customers get persistent idempotent conversations, bounded conversation-aware RAG, genuine structured Gemini answer streaming, trusted citations, feedback, safe retries, and confirmed human-request state. The streaming path validates the model's decision and request-local evidence IDs before releasing answer text, performs final structured validation, and atomically persists only the complete answer and trusted citations. It is not fake typing animation: partial text exists only in memory and the browser, is removed on failure, and is never written to Supabase. Completed retries return the persisted result without calling embeddings, retrieval, or Gemini again.

**Phase 6 — support triage and escalation automation, complete in application code and automated backend tests.** A human request or a successfully persisted insufficient-evidence assistant answer atomically creates/reuses one durable escalation per conversation. Automatic unresolved escalation leaves the conversation `open`; only an explicit human request pauses AI replies. Gemini still has exactly one declared `create_escalation` tool with automatic SDK execution disabled. The application validates category/priority/summary and supplies trusted IDs; the model has no email, search, shell, code, or direct database authority. Audit runs store action/status metadata, not prompts, transcripts, raw tool payloads, or chain-of-thought.

The FastAPI lifespan worker runs immediately, then every 60 seconds, processing at most 10 triage records and 10 notifications sequentially in separate batches with concurrency two. PostgreSQL—not an in-memory timer—owns retry eligibility, locking and attempt fencing: maximum three attempts, 15-minute stale recovery/failed backoff, and no automatic retries for invalid tool/auth failures. Missing Gemini leaves worker triage untouched; immediate human-request triage remains best effort. Completed triage atomically creates one pending notification. Missing/invalid optional Resend configuration leaves that outbox pending. No paid queue, Redis, Celery, LangGraph, new AI tools, or frontend production changes were added. Management UI remains Phase 7.

Optional Resend delivery uses existing `httpx` directly over HTTPS and deterministic minimal copy: workspace name, category, priority, generic review instruction, and at most 20 verified workspace owner/admin emails derived at delivery time. No customer transcript, triage summary, session data or customer PII goes to Resend; recipient snapshots are not stored. Database `sent` is final, completion/failure is attempt-fenced, and immediate retries reuse `supportpilot-escalation/<notification-id>`. Ambiguous delivery stops automatic retry; database recovery refuses replay beyond a conservative 23-hour window because [Resend retains idempotency keys for 24 hours](https://resend.com/docs/dashboard/emails/idempotency-keys). See the exact retry/error policy in [architecture](docs/ARCHITECTURE.md).

Resend is optional and was checked against its [official pricing](https://resend.com/pricing): Free is $0, 3,000 emails/month, 100/day and three domains. Do not enable paid billing or pay-as-you-go. `onboarding@resend.dev` can only test delivery to the Resend account email; arbitrary admins require an already-owned verified sender domain. No paid domain is needed to run SupportPilot without sending email. See [setup and provider restrictions](docs/SUPABASE_SETUP.md).

No live Gemini stream/tool call, live Resend email, hosted Supabase flow, or Playwright browser journey was exercised on this development machine. Supabase CLI/Docker are unavailable, so pgTAP tests have not been run here. Those runtime, end-to-end, security, and load checks remain required; this does not imply they passed. Apply migrations 009 and 010 in order before running the updated backend against Supabase. New database tests cover automation, outbox authorization, recipient minimization, recovery and attempt fencing but remain unexecuted in a full Supabase environment.

Phase 6B validation: 295 backend tests and 78 frontend tests passed at that checkpoint, along with Ruff lint/format checks, frontend lint/build and Git whitespace checks. An isolated native PostgreSQL smoke test applied migration 010 against minimal prerequisite fixtures and exercised automatic escalation with an open conversation, generalized triage, duplicate claims, atomic outbox creation, recipient filtering, notification backoff/recovery, stale-attempt fencing, sent idempotency and grants. It is not a full Supabase or pgTAP security-suite run; the temporary server was stopped afterward.

The initial portfolio-development and public-demo target is **₹0 / $0 infrastructure and AI cost**, using suitable free tiers and replaceable providers.

## Documentation

- [`AGENTS.md`](AGENTS.md) — persistent engineering rules
- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — approved V1 product scope
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — planned system architecture and flows
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — dependency-ordered development plan
- [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md) — Free-plan project, key, migration, and RLS setup

## Security note

No production credentials, API keys, passwords, tokens, secret keys, or private keys belong in this repository. Real secrets must be supplied through environment variables or deployment secret stores. Browser code may use only the Supabase publishable key; `SUPABASE_SECRET_KEY` is server-only and bypasses RLS. `.env.example` contains variable names only.

## Local development

The applications run locally without Docker, paid services, or external accounts. Expected addresses are:

- Frontend: `http://localhost:5173`
- Backend: `http://127.0.0.1:8000`
- Public health endpoint: `http://127.0.0.1:8000/api/health`
- Protected identity endpoint: `http://127.0.0.1:8000/api/auth/me`

The product landing page and public health indicator work without an environment file. To enable registration, login, workspaces, and authenticated API verification, copy `.env.example` to `.env` at the repository root and configure the frontend/backend Supabase URL and publishable-key variables. Add a server-only Gemini API key to enable indexing, retrieval embeddings, and grounded answer generation. Set `SUPABASE_SECRET_KEY` only on FastAPI to enable the Phase 5A customer-chat persistence endpoints; when it is absent, only those endpoints return a controlled `503` and the rest of the application still starts. The grounded generation call has no web search, URL context, tools, or function access and receives only the normalized standalone question, or bounded server-owned context for a customer follow-up, plus retrieved evidence. Customer chat uses `POST /api/chat/conversations/{conversation_id}/turns/stream` with `text/event-stream` and `started`, `delta`, `complete`, or safe `error` events; the existing non-streaming turn endpoint remains available. See `docs/SUPABASE_SETUP.md` for the Free-plan setup and smoke-test checklist.

The Knowledge Base route is `/app/knowledge`. File uploads use the authenticated Supabase client and the private `knowledge-files` bucket. SupportPilot limits each source file to 10 MB, even though the Supabase Free plan currently permits a higher per-file maximum. Owners/admins can recover interrupted uploads and explicitly process pending/failed sources. PDF extraction is limited to 300 pages and does not use OCR, so scanned/image-only PDFs are rejected safely. DOCX files receive ZIP-container safety checks before parsing. TXT and Markdown must be valid UTF-8.

### Backend

Requires Python 3.12 or newer.

```bash
cd backend
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` on Windows PowerShell or `source .venv/bin/activate` on macOS/Linux, then run:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend checks:

```bash
pytest
ruff check .
ruff format --check .
```

### Frontend

Requires Node.js 22.12 or newer.

```bash
cd frontend
npm install
npm run dev
```

Frontend checks:

```bash
npm test
npm run lint
npm run build
```
