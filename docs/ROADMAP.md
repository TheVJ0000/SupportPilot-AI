# SupportPilot AI — Development Roadmap

The project should be implemented in dependency order. Each phase should be completed and validated before moving to the next unless a later instruction explicitly changes the sequence.

## Phase 0 — Specification and architecture

**Objective:** Establish the durable product scope, engineering rules, high-level architecture, zero-cost constraint, security principles, and implementation roadmap before feature development begins.

**Completion criteria:**

- `AGENTS.md` defines permanent project rules.
- Product specification documents approved V1 capabilities and exclusions.
- Architecture documents application, RAG, escalation, and multi-tenancy flows.
- Repository hygiene and environment templates exist.
- No feature code has been introduced.

## Phase 1 — Frontend/backend application foundation

**Objective:** Create the minimal professional React/TypeScript/Vite frontend and FastAPI/Pydantic backend foundations with clear project structure, local development workflows, basic health checks, configuration handling, and initial testing setup.

**Completion criteria:**

- Frontend and backend run locally using documented commands.
- Basic API connectivity between frontend and backend works.
- Configuration is environment-driven.
- Initial unit/test runners work.
- No authentication or product-specific complexity is prematurely embedded.

## Phase 2 — Authentication and workspace isolation

**Objective:** Add secure authentication, workspace creation/membership, and the tenant-bound authorization foundation required by every later business-owned feature.

**Status:** Complete in the application code and automated unit/component suites. Phase 2A provides the schema, explicit grants, RLS policies, atomic workspace creation, and database security tests. Phase 2B provides registration, login, logout, session restoration, protected routes, authenticated FastAPI identity verification, workspace onboarding, and workspace selection.

The current development machine had neither Docker nor the Supabase CLI, so the existing pgTAP suite was not executed here. No hosted Supabase project was configured for a real-provider smoke test. Those environment-dependent checks remain required after following `docs/SUPABASE_SETUP.md`; this limitation does not imply that they passed.

**Completion criteria:**

- Users can register, sign in, sign out, and maintain sessions.
- Authenticated users can create/use a workspace.
- Workspace-scoped backend authorization is enforced.
- Relevant RLS policies are introduced where appropriate.
- Cross-workspace isolation tests pass.

## Phase 3 — Knowledge-base ingestion

**Objective:** Allow admins to add support knowledge and reliably convert supported content into workspace-scoped, searchable chunks.

**Status:** Complete in application code and automated backend/frontend suites. Phase 3A provides private source storage and recovery; Phase 3B provides hostile-file validation, extraction, normalization, deterministic citation chunks, and atomic replacement; Phase 3C adds explicit stage-aware retries, a source-ID-only indexing endpoint, a replaceable Gemini embedding provider, validated bounded batches, 768-dimensional pgvector storage, content-hash integrity checks, atomic completion, and cosine HNSW indexing. Owners/admins manage ingestion, members remain read-only, and non-members have no access.

The local machine still has neither Docker nor the Supabase CLI, so the pgTAP migrations/security suite and real hosted Supabase/Gemini smoke test remain environment-dependent checks. Phase 4A now builds on this indexed corpus. General two-resource deletion remains deferred to avoid a misleading partial-delete workflow.

**Completion criteria:**

- Supported uploads include PDF, DOCX, TXT, Markdown, and manual FAQs.
- Documents have processing/indexing status.
- Secure storage and text extraction work.
- Cleaning and chunking are implemented.
- Embeddings are generated through the provider abstraction.
- Chunks and metadata are stored in PostgreSQL/pgvector with workspace isolation.
- Documents can be removed; reprocessing path is defined or implemented as appropriate.

## Phase 4 — RAG support engine

**Objective:** Build the grounded support-answering engine that retrieves relevant workspace evidence, checks answerability, generates responses, and returns citations.

**Status:** Complete in application code and automated unit/API suites. Phase 4A provides one-query-embedding, authenticated workspace-scoped cosine retrieval with compatible 768-dimensional Gemini embeddings. Phase 4B adds a replaceable generation provider, Gemini `gemini-3.8-flash` with low thinking and structured output, explicit evidence-sufficiency decisions, deterministic no-evidence handling, prompt-injection defenses, bounded evidence, and citations reconstructed only from trusted retrieval metadata. No fixed similarity threshold is claimed before evaluation data exists, and no external Gemini tools or search are enabled.

The local machine still has neither Docker nor the Supabase CLI, so the pgTAP database suite was not executed. No real Gemini key or hosted Supabase project was configured, so live generation and hosted end-to-end RAG remain unverified. Formal RAG evaluation and complete runtime verification remain Phase 9 validation work; this limitation does not imply those checks passed. Customer chat and conversation persistence begin in Phase 5.

**Completion criteria:**

- Query embeddings and workspace-scoped similarity retrieval work.
- Evidence selection and answerability handling are explicit.
- Generated answers are grounded in retrieved evidence.
- Insufficient-evidence behavior is safe and testable.
- Source citations are returned.
- RAG behavior is covered by dedicated evaluation cases.

## Phase 5 — Customer chat UX

**Objective:** Deliver a polished hosted support-chat experience built on the RAG engine.

**Status:** Complete in application code and automated unit/component tests. Phase 5A and Phase 5B.1–5B.3 provide anonymous persistence, history restoration, idempotent retries, trusted citations, bounded follow-up interpretation, feedback, and confirmed human-request state. Phase 5B.4 adds real `google-genai` structured-output streaming through the generation-provider abstraction and the hosted UI; it does not use fake typing animation.

The server validates the streamed decision and complete request-local evidence-ID list before releasing answer deltas, performs mandatory final structured validation, reconstructs citations only from trusted retrieval metadata, and atomically persists only the completed answer. Partial text is memory/browser-only and is removed after interruption or error. Deterministic insufficient-evidence responses remain server controlled, and completed retries emit only the persisted completion without calling Gemini again. No database migration was required. Live Gemini streaming, hosted Supabase verification, Playwright end-to-end coverage, and broader security/load testing remain Phase 9 work. A human request pauses AI turns but does not connect or notify a person; Phase 6 will add bounded triage and escalation automation.

**Completion criteria:**

- Customers can start and continue multi-turn conversations.
- Responses stream in the UI.
- Citations/sources are visible.
- Conversation state is persisted.
- Feedback controls work.
- Customers can request a human.
- Insufficient-evidence states are handled clearly.

## Phase 6 — Support triage agent and escalation automation

**Objective:** Add bounded agentic behavior only for unresolved/human-requested conversations and automate escalation creation/notification safely.

**Status:** Complete in application code and automated backend tests through Phase 6B. Human requests or persisted insufficient-evidence answers atomically create/reuse one escalation; automatic escalation leaves the conversation open, while explicit human requests pause AI turns and preserve prior triage/audit. The dedicated Gemini agent still requests only `create_escalation`, with automatic SDK execution disabled and trusted IDs supplied by the application. A lifespan recovery worker runs immediately/every 60 seconds, max 10 records per stage with concurrency two. Database locks enforce three-attempt caps, 15-minute stale recovery/failed backoff and safe-error exclusions even across multiple instances. Missing provider configuration consumes no worker attempts.

Completed triage atomically creates a durable pending notification. Optional deterministic Resend HTTPS delivery uses only minimal workspace/category/priority information and verified workspace owner/admin recipients derived at send time. Sent state, attempt fencing and deterministic provider keys prevent safe replays; ambiguous/expired-key delivery requires later review, not endless retry. Resend Free pricing/restrictions were checked; billing, pay-as-you-go and domain purchases were not enabled. SupportPilot runs without email credentials. This in-process worker is best effort, not an external durable queue; database state supplies recovery. No LangGraph/new model tools, Redis/Celery/paid queue, Slack/CRM, dashboard, widget or deployment was added.

Apply migrations 009/010 and run the pgTAP suite on a disposable Supabase environment before relying on database behavior. Supabase CLI/Docker remain unavailable, so pgTAP was not executed. A limited native PostgreSQL fixture smoke verified migration 010 lifecycle/recipient/grant behavior, not full Supabase RLS or pgTAP. Live Gemini triage, live Resend delivery, hosted Supabase and Playwright checks remain unverified. Phase 7 is not started. Runtime validation/configuration and exhausted/ambiguous record review remain operational follow-ups, not claims of production readiness.

**Completion criteria:**

- Triage agent can classify an unresolved issue.
- It can determine priority and summarize the conversation.
- It has only explicitly allowed tools.
- Escalation records are created reliably.
- Notification automation is integrated only after rechecking a suitable free tier.
- Agent actions are testable and auditable.

## Phase 7 — Admin dashboard

**Objective:** Give business/admin users a useful operational view of their support system.

**Completion criteria:**

- Admins can view conversations, sources, feedback, and escalations.
- Escalations can be managed.
- Knowledge-base status is visible.
- Basic support analytics are meaningful and workspace-scoped.
- Dashboard UX is portfolio-quality and responsive.

## Phase 8 — Embeddable widget and API polish

**Objective:** Make SupportPilot usable from an external business website and polish the public API boundaries.

**Completion criteria:**

- Embeddable website support widget works on a sample external page.
- Widget configuration is workspace-aware and secure.
- Public-facing APIs have appropriate authorization and/or rate limiting.
- Integration documentation is clear.
- API error behavior and contracts are consistent.

## Phase 9 — Testing, RAG evaluation and security hardening

**Objective:** Raise the project from working demo to credible professional portfolio quality through broad testing, evaluation, and security review.

**Completion criteria:**

- Backend pytest suite covers critical business/security logic.
- Frontend Vitest and React Testing Library coverage addresses critical UI flows.
- Playwright covers primary end-to-end journeys.
- RAG evaluation suite measures grounding, retrieval, citations, and insufficient-evidence behavior.
- Tenant-isolation tests pass.
- Input validation, authorization, rate limiting, logging, and secret handling are reviewed.
- Known risks and limitations are documented.

## Phase 10 — Zero-cost production deployment and portfolio packaging

**Objective:** Deploy the finished application using verified free-tier services and present it professionally as an Upwork portfolio project.

**Completion criteria:**

- Every chosen deployment/external service has been rechecked for a suitable free tier immediately before adoption.
- No paid billing is required for the initial demo.
- Production configuration contains no committed secrets.
- Application is deployed and smoke-tested.
- CI/CD is appropriate for the final architecture.
- README and portfolio materials accurately describe implemented capabilities without fake usage/client claims.
- Demo data is synthetic/non-confidential.
