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

Apply migrations 009/010 and run the pgTAP suite on a disposable Supabase environment before relying on database behavior. Supabase CLI/Docker remain unavailable, so pgTAP was not executed. A limited native PostgreSQL fixture smoke verified migration 010 lifecycle/recipient/grant behavior, not full Supabase RLS or pgTAP. Live Gemini triage, live Resend delivery, hosted Supabase and Playwright checks remain unverified. Runtime validation/configuration and exhausted/ambiguous record review remain operational follow-ups, not claims of production readiness.

**Completion criteria:**

- Triage agent can classify an unresolved issue.
- It can determine priority and summarize the conversation.
- It has only explicitly allowed tools.
- Escalation records are created reliably.
- Notification automation is integrated only after rechecking a suitable free tier.
- Agent actions are testable and auditable.

## Phase 7 — Admin dashboard

**Status: Complete in application code and automated tests through Phase 7B.** The operations dashboard includes workspace metrics, recent activity, paginated lists, transcripts/citations/feedback, triage audit and notification state, knowledge counts, explicit conversation outcomes, and escalation lifecycle management. Owner/admin navigation, authenticated FastAPI, and explicitly authorized JWT-scoped RPCs preserve migration 011's eight-table SELECT RLS; Knowledge Base member access and server chat/automation RPCs remain intact. Migration 013 adds constrained outcomes/timestamps and row-locked expected-state mutations, never general UPDATE access.

AI answered ≠ AI resolved: answer coverage remains distinct from overall resolution (`resolved_conversations / total_conversations`, empty = 0%), which counts only explicit owner/admin decisions. Conversations can resolve or close unresolved, then reopen; historical human requests restore the human-requested status with AI paused. Escalations allow open → in_progress/resolved/closed; in_progress → open/resolved/closed; resolved → open/closed; closed → open. Neither lifecycle rewrites the other. Confirmations, disabled pending controls, server-confirmed results, 409 refresh, and workspace/identity fencing protect actions. Lists remain bounded (25 default/50 max). Operational data is not stored in browser storage.

Validation: 403 backend and 137 frontend tests, Ruff lint/format, frontend lint/build, and whitespace checks pass. Hosted migration 013 was reviewed by dry run and applied without reset. Rolled-back synthetic pgTAP suites passed: lifecycle 69, admin operations 86, feedback/handoff 38, chat 48, retrieval 28; a separate transactional preflight tested historical backfill. Both local HTTP endpoints were checked. This is not a claim that the full database suite or manual owner/admin browser lifecycle actions were tested. No live AI/email call, chart dependency, new provider, widget, or deployment was introduced.

Phase 7B's implementation checkpoint is complete. A synthetic authenticated browser smoke and broader integration checks remain unverified; no personal account/data was used. The subsequent Phase 8A instruction permits proceeding with the isolated widget foundation while reporting those limits. Manual customer replies, AI-triage editing, and notification retry controls were deliberately not added.

**Objective:** Give business/admin users a useful operational view of their support system.

**Completion criteria:**

- Admins can view conversations, sources, feedback, and escalations.
- Escalations can be managed.
- Knowledge-base status is visible.
- Basic support analytics are meaningful and workspace-scoped.
- Dashboard UX is portfolio-quality and responsive.

## Phase 8 — Embeddable widget and API polish

**Preflight completed (September 17, 2026):** The missing feedback PUT CORS method was fixed in `80ce1576de28a0577d8ed13517f2f26e66866136`. Configured-origin-only access, GET/POST/PATCH/PUT, and denied external-origin/DELETE checks remain intact. The later Phase 8A instruction explicitly authorized continuation after that fix.

**Phase 8A status: complete in application code and automated tests.** Migration 014 reuses `workspace_chat_configs.public_id` and adds owner/admin-only safe configuration and expected-state toggle RPCs, without public-ID rotation or general table UPDATE grants. FastAPI GET/PATCH widget routes use the publishable key plus verified caller JWT. `/app/widget` supplies configuration, current-origin embed code, accessible copy fallback, server-confirmed toggles, safe conflicts, and workspace/identity fencing. A dependency-free stable script mounts one Shadow DOM launcher and sandboxed SupportPilot-origin iframe; `/embed/:publicId` reuses all customer chat business logic. The separate synthetic store demo runs on port 4174.

Validation: 436 backend tests and 177 frontend tests pass, with Ruff lint/format, frontend lint/build and whitespace checks. The application build has a non-blocking chunk-size warning. Only migration 014 was pending in the reviewed dry run; it reached linked Free Supabase normally, without reset or hosted data deletion. Rolled-back synthetic pgTAP suites actually rerun: widget configuration 25, admin operations 86, customer chat 48 assertions. Independent-origin browser smoke covered one launcher, host styling, iframe loading, close/reopen, toolbar Escape, host refresh and safe unavailable presentation with an unused synthetic ID. Disabled-session enforcement passed database tests; no real workspace was toggled in a browser. Customer-chat secret/Gemini configuration is absent, so no live customer session/answer, live sandbox storage/streaming journey, authenticated admin browser action, or full database suite is claimed.

**Phase 8B and Phase 8 overall: complete in application code and automated tests.** Migration 015 adds RLS-protected infrastructure counters and private atomic fixed-window claims with database time. Quotas are fixed centrally in SQL: session creation 30/minute + 300/hour per public widget ID; new/failed-retry processing 6/minute + 60/hour per customer session; public history 60/minute; feedback 20/minute; human requests 10/minute per session. Completed/processing replays do not consume AI quota. Trusted turn-context history is separate from browser quota; mutations derive validated relationships, not client scope/subject. Bounded cleanup runs at startup/every ten existing worker cycles (500 rows maximum), tolerating failures. No IP/hash, fingerprint, request contents or token hashes enter counters, and no paid/new external service or AI/provider change was added.

Scoped public JSON errors, 429/Retry-After, 16 KiB actual-body protection (including absent/chunked Content-Length), content-type checks, no-store/nosniff, pre-SSE quota enforcement and safe post-start errors are implemented. The shared customer API client parses only safe throttling metadata; hosted/embed sessions show safe busy state, turn retry retains its ID with a manual cooldown, and feedback/human actions never claim rejected success. Public documentation is in `PUBLIC_API.md`; widget boundaries/CORS remain intact, including feedback PUT, denied external origins and DELETE. No developer API keys, CAPTCHA, or host-page rate logic were added.

Final checks: **489 backend / 201 frontend tests**, Ruff lint/format, frontend lint/build and whitespace checks pass; the application bundle-size warning remains non-blocking. Reviewed dry run contained only 015; a rollback preflight passed 60 assertions before normal hosted application. Rerun hosted pgTAP suites: public API/rate limits 60, customer chat 48, widget configuration 25, using synthetic fixtures and rollback. Synthetic ASGI runtime smoke accepted 30 fixture sessions, throttled the next with Retry-After, then succeeded in a fresh fixture window; this is not a live DB-backed HTTP journey. Live frontend/health/demo returned 200 and the unconfigured live session endpoint safely returned 503. External widget shell, CSS isolation, iframe, close/reopen and unavailable behavior passed browser smoke. The optional two-connection last-slot test was inconclusive (one CLI initialization stalled and was cancelled); its temporary counter was removed. The full DB suite and live customer/Gemini journey were not exercised.

**Before Phase 9:** no new code blocker was found. Safely configured customer-chat/Gemini credentials and synthetic authenticated access are still needed for live end-to-end validation. Fixed-window boundary bursts and shared-public-ID availability limits are V1 tradeoffs, not comprehensive bot protection or an aggregate AI budget. Real concurrency/load tuning and broader security/RAG/browser evaluation remain Phase 9; framing/CSP and free-tier deployment verification remain Phase 10. Stop after 8B; neither later phase was begun.

**Objective:** Make SupportPilot usable from an external business website and polish the public API boundaries.

**Completion criteria:**

- Embeddable website support widget works on a sample external page.
- Widget configuration is workspace-aware and secure.
- Public-facing APIs have appropriate authorization and/or rate limiting.
- Integration documentation is clear.
- API error behavior and contracts are consistent.

## Phase 9 — Testing, RAG evaluation and security hardening

**Phase 9A — security/database baseline complete (September 18, 2026).**
All sixteen hosted rollback pgTAP suites pass **1,004 assertions**, with none
skipped. The final-schema matrix covers sixteen application tables and private
Storage, every application function (60 total / 53 SECURITY DEFINER), relevant
CRUD/RPC grants, and cross-workspace owner/admin/customer attacks. Both real
PostgreSQL last-slot races PASS: two independent sessions wait on locks, one
claims and one receives PT429, counters finish at 30/6, and fixtures are removed.
Database-time minute/hour selection, dual-limit atomicity and replay/retry pass.
Migration 016 removes unnecessary inherited service-role table/business-RPC
grants without editing migrations 001–015. JWT malformed/legacy claim and encoded
DOCX XML gaps are fixed. Final validation: **521 backend / 201 frontend tests**,
Ruff lint/format, frontend lint/build and Git whitespace checks PASS. No new
feature, paid service, dependency or provider was introduced. See
[the complete review, suite inventory and residual risks](SECURITY_REVIEW.md).

**Phase 9B — primary browser integration complete (September 18, 2026).**
All 24 Chromium tests pass across nine specs: roles and route guards, workspace
switch/late-response fencing, KB validation/FAQ extraction, conversation and
escalation lifecycles, safe 409 refresh, widget snippet/availability, real SSE,
same-ID retries, citations, feedback, confirmed handoff, cooldown, closed state,
independent-origin embedding/privacy/session restoration and mobile usability.
External auth/database/AI boundaries are synthetic in a separate test-only
FastAPI instance; own frontend/FastAPI requests are real. Production auth has no
test bypass. Closed-chat explanation was fixed with lower-level regressions.
Final checks: 524 backend, 203 frontend and 24 browser tests; lint/format/build/
whitespace PASS. No SQL change or migration 017; Phase 9A hosted DB checks were
not rerun. No live Gemini/Resend or hosted authenticated browser smoke ran. See
[the reproducible E2E guide and limitations](E2E_TESTING.md).

**Phase 9C — deterministic evaluation complete; live embeddings/hosted retrieval
validated, generation incomplete (September 18, 2026).** Version 1.0.0 retains
36 synthetic cases and independent metric gates. Offline lexical Hit@8 100%,
Recall@8 98.39% and its source miss remain labelled fixture measurements.
Separate live semantic retrieval passed Hit@1 93.55%, Hit@8/Recall@8 100%,
MRR 0.96774, Beta isolation control and rollback. Fixture setup role restoration
and installed-SDK request serialization were fixed with regressions. Original
generation failed HTTP 400; corrected generation failed HTTP 503 after only
the existing bounded retries, then stopped. No successful live answer/stream,
customer HTTP/persistence journey or triage smoke is claimed. Gemini is private,
free tier/billing disabled verified; the server-only Supabase secret is missing.
583 backend, 203 frontend and 24 browser tests pass; lint/format/build pass.
No prompt/model/threshold/DB schema/grant change, migration 017, new dependency,
email or paid billing. Phase 9C is not complete. See
[the formal evaluation report](RAG_EVALUATION.md).

**9D not currently justified by measured evidence.** No load/resource failure
was observed; 9A's real final-slot races and 9B's serial SSE/cooldown tests do not
prove concurrent-stream capacity. Complete the blocked live 9C baseline first,
then reassess if measurements or a concrete target-load requirement justify it.
9D was not started; Phase 10 remains unstarted.

**Phase 9 is not complete.** Successful live generation/streaming and private
customer-server configuration are needed before the real synthetic customer
journey (email configuration only for optional notification delivery).
Storage API HTTP byte-deletion is not claimed by SQL tests. Fixed-window bursts,
shared-widget availability, aggregate AI-budget/bot protection, XSS/key compromise
and production capacity remain limitations. Deployment/framing/CSP, exact hosted
CORS/Auth redirects, logs and renewed free-tier checks remain Phase 10.

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
