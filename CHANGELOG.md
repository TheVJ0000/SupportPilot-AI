# Changelog

## v1.0.0 — 2026-09-21

SupportPilot AI's first stable portfolio baseline includes:

- A full-stack, workspace-scoped React and FastAPI application using Supabase Auth and PostgreSQL.
- FAQ and document ingestion, validated extraction, private Storage, Gemini embeddings, and pgvector retrieval.
- Grounded customer chat with structured Gemini generation, SSE streaming, trusted citations, context, retries, feedback, and human handoff.
- A bounded escalation triage agent with one allow-listed tool, durable audits, retry fencing, and optional notification state.
- Role-aware dashboard, knowledge, conversation, feedback, escalation, analytics, and lifecycle operations.
- A dependency-free launcher and sandboxed iframe widget demonstrated on a separate public origin.
- RLS and authenticated database controls, atomic public rate limits, safe API envelopes, input safeguards, and secret-boundary checks.
- Separate pytest, Vitest/React Testing Library, Playwright, pgTAP, PostgreSQL concurrency, and RAG evaluation evidence.
- GitHub Actions CI and a zero-cost public Render/Supabase/Gemini portfolio deployment.

### Known limitations

- Render Free cold starts, free-tier quotas, and provider availability can affect demo latency and availability.
- The public deployment uses synthetic data and has no production SLA, real-customer usage, or commercial-adoption claim.
- RAG results cover a small fictional benchmark and bounded production smoke; they are not universal accuracy claims.
- Optional notification email and documented defense-in-depth/capacity items remain limited as described in [the architecture](docs/ARCHITECTURE.md), [deployment guide](docs/DEPLOYMENT.md), and [RAG evaluation](docs/RAG_EVALUATION.md).
