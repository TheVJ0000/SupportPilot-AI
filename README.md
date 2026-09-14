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

**Phase 0 — specification and architecture.** Feature development has not started yet.

The initial portfolio-development and public-demo target is **₹0 / $0 infrastructure and AI cost**, using suitable free tiers and replaceable providers.

## Documentation

- [`AGENTS.md`](AGENTS.md) — persistent engineering rules
- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — approved V1 product scope
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — planned system architecture and flows
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — dependency-ordered development plan

## Security note

No production credentials, API keys, passwords, tokens, service-role credentials, or private keys belong in this repository. Real secrets must be supplied through environment variables or deployment secret stores. `.env.example` contains variable names only.
