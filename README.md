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

**Phase 5 — customer chat UX, complete in application code and automated tests.** Anonymous customers get persistent idempotent conversations, bounded conversation-aware RAG, genuine structured Gemini answer streaming, trusted citations, feedback, safe retries, and confirmed human-request state. The streaming path validates the model's decision and request-local evidence IDs before releasing answer text, performs final structured validation, and atomically persists only the complete answer and trusted citations. It is not fake typing animation: partial text exists only in memory and the browser, is removed on failure, and is never written to Supabase. Completed retries return the persisted result without calling embeddings, retrieval, or Gemini again.

**Phase 6A — bounded support triage and reliable escalation foundation, implemented in application code and automated tests.** Requesting a human atomically pauses AI replies and creates one durable escalation placeholder. A best-effort FastAPI background task runs a dedicated triage agent with Gemini native function calling (`gemini-3.8-flash`, medium thinking). Gemini selects category, priority, and summary arguments for exactly one declared `create_escalation` tool; the application validates and explicitly executes that action. IDs and authority never come from the model. SDK automatic tool execution is disabled; no LangGraph, search, shell, code execution, direct model database access, or notifications are enabled. Audit runs store action/status metadata, not prompts, transcripts, raw tool payloads, or chain-of-thought.

AI failure never loses the human request. Escalations remain pending/failed and recoverable; database locking prevents duplicate active/completed triage, with 15-minute stale-attempt recovery. Background tasks are best effort, **not a durable queue**. No person is connected or notified. Phase 6 as a whole is not complete: insufficient-evidence auto-triage and remaining automation are deferred to Phase 6B, and management UI to Phase 7.

No live Gemini stream/tool call, hosted Supabase flow, or Playwright browser journey was exercised on this development machine. Supabase CLI/Docker are unavailable, so pgTAP tests have not been run here. Those runtime, end-to-end, security, and load checks remain required; this does not imply they passed. Apply the new Phase 6A migration before running the updated backend against Supabase.

Phase 6A local validation: 245 backend tests and 78 frontend tests passed, as did Ruff, frontend lint/build, and Git whitespace checks. An isolated native PostgreSQL smoke test applied the new migration against minimal prerequisite fixtures and exercised human-request idempotency, triage begin/retry/stale recovery/completion, audit consistency, and grants. It is not a full Supabase or pgTAP security-suite run; the temporary server was stopped afterward.

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
