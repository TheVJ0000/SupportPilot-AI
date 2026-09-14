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

**Phase 3A — secure knowledge-source storage and management.** Authenticated workspaces can now list private knowledge metadata, while owners/admins can upload PDF, DOCX, TXT, and Markdown files or add manual FAQs. Source creation, trusted Storage paths, ownership, lifecycle status, the private 10 MB bucket limit, tenant access, and recovery of interrupted uploads are enforced by database RPCs and RLS. Text extraction, chunking, embeddings, RAG, and reliable general source deletion remain intentionally deferred.

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

The product landing page and public health indicator work without an environment file. To enable registration, login, workspaces, and authenticated API verification, copy `.env.example` to `.env` at the repository root and configure the frontend/backend Supabase URL and publishable-key variables. See `docs/SUPABASE_SETUP.md` for the Free-plan setup and smoke-test checklist.

The Knowledge Base route is `/app/knowledge`. File uploads use the authenticated Supabase client and the private `knowledge-files` bucket. SupportPilot limits each source file to 10 MB, even though the Supabase Free plan currently permits a higher per-file maximum. Owners/admins can use **Recover upload** for an interrupted source still marked `uploading`; the database safely reconciles it against the exact expected private object.

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
