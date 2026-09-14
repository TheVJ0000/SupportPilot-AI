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

**Phase 2A — authentication data/security foundation.** Supabase configuration, the initial workspace schema, RLS policies, atomic workspace creation, and integration scaffolding are prepared. User-facing registration, login, sessions, protected routes, and workspace UX remain for Phase 2B.

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
- Health endpoint: `http://127.0.0.1:8000/api/health`

The Phase 1 health screen still works without an environment file. To override local configuration, copy `.env.example` to `.env` at the repository root and set `FRONTEND_URL` and `VITE_API_BASE_URL`. Supabase functionality remains dormant until its URL and publishable-key variables are configured; see `docs/SUPABASE_SETUP.md`.

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
