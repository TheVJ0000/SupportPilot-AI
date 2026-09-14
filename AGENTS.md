# AGENTS.md

## Project identity

SupportPilot AI is a personal portfolio project, not a paid-client project. It must ultimately be polished, deployable, testable, and credible enough to demonstrate professional Generative AI and full-stack engineering capabilities to Upwork clients.

## Product principles

- Avoid fake claims about users, customers, revenue, production usage, or client results.
- Implement the project incrementally rather than attempting everything at once.
- Preserve previously approved product requirements unless a later instruction explicitly changes them.
- Prefer simple, maintainable architecture over unnecessary complexity.
- Do not silently remove or simplify approved functionality to make implementation easier.

## Cost constraint

The portfolio development and initial public demo have a strict target of **₹0 / $0 total infrastructure and AI cost**.

Therefore:

- Prefer genuinely usable free tiers.
- Do not enable paid billing merely to increase capacity.
- Do not introduce a paid dependency when a suitable free solution exists.
- Do not purchase a custom domain during the initial portfolio stage.
- Before adding any external service, verify that the required functionality is currently available for free.
- If a planned service would require payment, stop and report that before implementing it.
- Design external integrations so providers can be changed later.

## Security

- Never commit API keys, passwords, tokens, service-role credentials, private keys, or other secrets.
- Real secrets must only come from environment variables or deployment secret stores.
- `.env` files containing secrets must be gitignored.
- `.env.example` may contain variable names but never real secret values.
- Browser code may use only the Supabase project URL and publishable key. Never reference `SUPABASE_SECRET_KEY` in frontend code or a `VITE_` variable.
- `SUPABASE_SECRET_KEY` is server-only, bypasses Row Level Security, and must be used only for narrowly scoped privileged operations when no safer option exists.
- Minimize privileged secret-key usage. Normal user operations must use authenticated user JWTs with Row Level Security rather than bypassing RLS.
- Apply least-privilege principles.
- Validate user and API input.
- Treat tenant isolation as a security requirement.
- Public APIs must eventually receive appropriate authorization and/or rate limiting.
- Do not log secrets or confidential document contents unnecessarily.

## AI engineering principles

SupportPilot AI must not be implemented as a simple ChatGPT wrapper.

The normal customer question-answering flow must use **RAG**, not an autonomous agent:

customer question
→ retrieve relevant business knowledge
→ evaluate evidence
→ generate grounded answer
→ provide source citations
→ store conversation

Use an AI agent only where agentic behavior adds genuine value.

The primary planned agent is a bounded **Support Triage Agent** that can analyze unresolved conversations, classify them, determine priority, summarize them, and create an escalation using explicitly allowed tools.

Do not give agents unrestricted database, shell, internet, or infrastructure access.

## AI provider architecture

Use an abstraction layer so the application is not permanently tied to one LLM provider.

Current zero-cost development defaults are:

- Generation: Google Gemini API free tier, currently `gemini-3.8-flash`
- Embeddings: Gemini API free tier, currently `gemini-embedding-2`

These provider and model selections must remain configurable and replaceable. Do not hard-code provider-specific logic throughout the application.

Use only synthetic, demo, or non-confidential knowledge-base content while relying on free AI tiers whose terms permit submitted content to be used for product improvement.

## Planned stack

### Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

### Backend

- Python
- FastAPI
- Pydantic

### Data/platform

- Supabase PostgreSQL
- Supabase Auth
- Supabase Storage
- pgvector

### AI

- Gemini API initially
- RAG architecture
- Gemini embeddings
- provider abstraction
- LangGraph only where an actual stateful agent workflow is justified

### Testing

- pytest
- Vitest
- React Testing Library
- Playwright
- dedicated RAG evaluation cases

### Version control / CI

- Git
- GitHub
- GitHub Actions eventually

Any deployment, background-processing, email, or rate-limiting service must be rechecked for a suitable free tier immediately before adoption.
