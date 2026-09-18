# Phase 9A security/database baseline

Review date: September 18, 2026. Scope: the existing application and final schema
through migration 016. This is a source review and deterministic regression
baseline, not penetration testing, certification, formal RAG evaluation, or a
claim of production usage. Only synthetic, non-confidential fixtures were used.
No new infrastructure, paid billing, provider, or product feature was introduced.

## Threat boundaries and authentication

The business browser holds the intended Supabase Auth session. FastAPI accepts
only ES256/RS256 with project JWKS verification, or legacy HS256 validated by
the project's Auth `/user` endpoint. Issuer, authenticated audience, expiry,
required claims and UUID subject are enforced. The legacy path additionally
binds the signed subject to the server-verified identity; local unverified
decoding is never sufficient authorization. Malformed successful Auth responses
are handled safely. Invalid expiration claim types/non-finite values are rejected
as authentication errors, rather than uncaught dependency conversion exceptions.
JWKS lookup is bounded/cached; provider outages fail closed.
Existing asymmetric signature, algorithm, issuer, audience, expiry, subject and
JWKS tests remain, with new legacy-response/claim regression cases.

Business gateways use the publishable key plus verified caller JWT, not the
server secret. Caller-selected workspace IDs are not authority: SQL derives
permissions from `auth.uid()`. Customer endpoints use a different opaque-session
boundary. Worker/customer gateways have fixed RPC allow-lists and do not expose
arbitrary relation, function, SQL, URL, or privileged database access.

## Final table and tenant matrix

All sixteen public application tables have RLS enabled. Anon and service_role
have no direct application-table CRUD grants after 016. Service operations use
the nineteen narrow owner-executed RPCs below. Normal authenticated mutation
grants are deliberately limited; safe Knowledge Base column grants omit creator,
trusted Storage path, FAQ payload and raw embedding data where applicable.

| Table / resource | Authenticated SELECT | Direct mutations / required RPC boundary |
| --- | --- | --- |
| profiles | Own profile only | Own display_name UPDATE; identity immutable; Auth trigger creates profile |
| workspaces | Member's workspaces | Owner name UPDATE / DELETE; create_workspace derives creator and ownership |
| workspace_members | Own membership row only | No browser INSERT/UPDATE/DELETE |
| knowledge_sources | Workspace members, safe columns | Manager-only lifecycle RPCs derive creator, path, workspace and state |
| knowledge_chunks | Workspace members, safe columns | No browser writes or raw embedding SELECT; processing RPCs check source |
| workspace_chat_configs | Workspace members | Owner/admin widget RPCs; no general browser writes |
| customer_sessions | No direct browser access | Server customer RPCs; hash/expiry/relationship validation |
| conversations | Owner/admin of workspace | Customer session RPCs / owner-admin expected-state lifecycle RPCs |
| conversation_turns | Owner/admin, safe columns | Server turn RPCs; request/session/state validation |
| messages | Owner/admin of workspace | Server turn completion; no browser writes |
| message_citations | Owner/admin of workspace | Completion validates and rebuilds trusted source metadata |
| message_feedback | Owner/admin of workspace | Validated customer/session/message feedback RPC |
| escalations | Owner/admin of workspace | Validated human request / trigger / bounded triage / lifecycle RPC |
| escalation_triage_runs | Owner/admin of workspace | Run/attempt-fenced server triage RPCs |
| escalation_notifications | Owner/admin, safe columns | Attempt-fenced notification RPCs |
| customer_api_rate_limits | No direct browser access | Private derived-identity claims / bounded server cleanup |
| knowledge-files Storage | Workspace members at exact trusted source path | Manager INSERT only while uploading; Storage API DELETE uses manager/trusted-path RLS; direct SQL DELETE blocked by platform; no matching UPDATE policy |

The final matrix exercises anon, authenticated non-member, member, admin, owner,
and service-role paths. Metadata checks cover relevant table/column CRUD grants;
actual row checks use populated A/B fixtures. Owner/admin A cannot read or mutate
B conversations/escalations, manage B widget, extract B knowledge, or retrieve B
chunks. Customer A cannot read B history, start B turn, give B feedback, request
B human support or change B limiter identity. Profile/workspace and Storage
cross-tenant mutations are also tested. A rejected attack preserves B state.
Supabase's direct SQL Storage-delete guard is preserved, not disabled: SQL DELETE
denial, absence of alternate permissive DELETE/ALL browser policies, and the
actual caller's deletion-policy helper are checked. Storage API
HTTP deletion/byte behavior remains an end-to-end check, not claimed by pgTAP.
See [Supabase's deletion guidance](https://supabase.com/docs/guides/storage/management/delete-objects).

## Every current SECURITY DEFINER function

The live catalog inventory contains **60 application functions, 53 SECURITY
DEFINER**, excluding platform/extension and transient pgTAP functions. Every
definer has empty search_path, static schema-qualified application references,
no dynamic EXECUTE, and no PUBLIC execution. Extension vector operators in
retrieval retain the explicit qualification fixed by migration 012; actual
retrieval suites test this, rather than relying only on lexical inspection.

The following groups exhaust all 53 definers; public names have public schema,
and private names have app_private schema. Exact signatures/grants are asserted
or exercised by the catalog matrix and the named functional suites.

Authenticated-only public functions (22 after 016):

- create_workspace
- begin_file_knowledge_source, finalize_file_knowledge_source, cancel_file_knowledge_source
- create_faq_knowledge_source, recover_file_knowledge_source
- begin_knowledge_extraction, complete_knowledge_extraction, fail_knowledge_extraction
- begin_knowledge_indexing, complete_knowledge_indexing, fail_knowledge_indexing
- search_knowledge_chunks
- admin_dashboard_snapshot, admin_list_conversations, admin_get_conversation
- admin_list_escalations, admin_get_escalation
- admin_set_conversation_resolution, admin_set_escalation_status
- admin_get_widget_config, admin_set_widget_enabled

These check caller identity and derive membership/manager/owner-admin authority;
knowledge transitions lock/check the source, vector payloads are dimension/hash
validated, reads are bounded, and lifecycle/widget updates check expected state.

Service-role-only public functions (19), each still necessary:

| Function | Narrow input / trusted relationship and guard |
| --- | --- |
| create_customer_chat_session | Existing enabled public ID, server-created hash, bounded expiry; derive workspace and new conversation |
| begin_customer_chat_turn | Conversation + hash + idempotency ID + bounded question; derive valid session/workspace, lock state, claim quota |
| search_customer_chat_knowledge | Valid conversation/hash + validated vector/provider/model/dimension + bounded matches; derive ready workspace sources |
| complete_customer_chat_turn | Turn/hash + allowed decision + bounded answer/citation list; validate current turn and trusted source relationships |
| fail_customer_chat_turn | Turn/hash + allow-listed safe code; validate processing state and session |
| get_customer_chat_turn_result | Conversation/hash/request ID; validate session and request relationship |
| get_customer_conversation | Conversation/hash; validated session and bounded internal context, not browser history quota |
| get_customer_conversation_history | Same validated identity; public-history quota |
| set_customer_message_feedback | Conversation/hash/message/rating; assistant-message relationship and quota |
| request_customer_human_support | Conversation/hash; enabled valid session, state/idempotency and quota |
| cleanup_customer_api_rate_limits | Integer 1–500 only; indexed expired-window batch, SKIP LOCKED, no caller subject/scope |
| list_recoverable_escalations | Integer 1–20; eligible state, stale/backoff/attempt cap, fixed table |
| begin_escalation_triage | Escalation ID; recheck eligible conversation/workspace/state under lock, derive bounded transcript and fenced run |
| complete_escalation_triage | Escalation/run IDs + validated category/priority/summary/provider/model; derive workspace and current attempt |
| fail_escalation_triage | Escalation/run IDs + safe code; current run/attempt fencing |
| list_recoverable_escalation_notifications | Integer 1–20; fixed outbox, eligible state/backoff/attempt cap |
| begin_escalation_notification | Outbox ID; derive classified escalation and bounded owner/admin recipients, lock current attempt |
| complete_escalation_notification | Outbox ID/expected attempt/provider message ID; current sending-attempt fence |
| fail_escalation_notification | Outbox ID/expected attempt/safe code; current sending-attempt fence |

Private definers (12):

- Authenticated policy helpers (7): is_workspace_member, is_workspace_owner,
  can_manage_knowledge, can_read_knowledge_object, can_upload_knowledge_object,
  can_delete_knowledge_object, can_view_support_operations. Inputs are a UUID or
  object path; authority always derives from auth.uid() and exact source paths.
- Owner-only triggers (4): handle_new_auth_user, create_workspace_chat_config,
  escalate_insufficient_evidence, enqueue_escalation_notification. Trusted NEW
  relationships create constrained rows; no caller-selected target function/table.
- Owner-only consume_customer_rate_limit: fixed scope allow-list and SQL-owned
  constants. Neither browser nor service_role can execute it with arbitrary IDs.

Seven non-definer helpers are owner-only: set_updated_at,
enforce_knowledge_processing_transition, is_valid_customer_citation_locator,
admin_conversation_item, admin_escalation_item, is_recoverable_escalation,
is_recoverable_notification. They have safe search paths and no PUBLIC execution.

**Defect corrected by migration 016:** inherited default service-role CRUD on
five early tables and EXECUTE on thirteen business RPCs was unnecessary. Actual
JWT gateway flows were traced before revocation. Required customer, triage,
notification, trigger and worker flows remain. Applied migrations 001–015 are
unchanged. A leaked Supabase server secret remains a serious platform-wide risk:
managed Storage/Auth privileges and trusted privileged RPCs are not a sandbox
for an attacker possessing that key.

## Customer session, widget and browser storage

X-SupportPilot-Session is generated with 32 random bytes (256-bit entropy).
The browser receives the opaque value; the server stores SHA-256 only. Header
shape, expiry, enabled chat and conversation/session/workspace relationships are
checked. Tokens are not URL parameters or exposed to the external host page.
The iframe persists exactly publicId, conversationId, sessionToken, expiresAt and
workspaceName, without transcript. Business localStorage adds only selected
workspace ID; the Supabase SDK persists the intended authentication session.
Admin transcripts/escalations, server/provider secrets and unnecessary JWT
copies are not persisted. The host script has no customer-state postMessage.
Storage access failure falls back safely to in-memory state. Same-origin XSS or
browser/device compromise can still steal browser credentials; this is not
claimed to be solved by opaque tokens or iframe isolation.

Configured CORS origins are explicit, not wildcard: GET/POST/PUT/PATCH permitted,
external API origins and DELETE rejected, feedback PUT preflight covered.
Customer responses retain no-store/nosniff, safe errors and bounded Retry-After;
SSE retains its existing no-cache behavior. No framing DENY was introduced.

## Uploads, RAG and bounded agent

Existing protections remain: 10 MB approved-type limit; PDF at most 300 pages,
encrypted/malformed rejection and image-only insufficient text (no OCR); DOCX
at most 2,000 ZIP entries, 50 MB total uncompressed and 20 MB per member;
traversal/macros/active content/entity rejection; UTF-8 TXT/Markdown; normalized
text at most 1,000,000 characters and at most 1,000 chunks. New bounded XML
parsing closes UTF-16 DTD/external-relationship and whitespace/entity-escaped
attribute bypasses in the former byte checks. Entity resolution is disabled;
malformed XML fails safely. UTF-8 and UTF-16 malicious fixtures are covered.

Questions and documents are untrusted data. Normal generation config has no
web/search/tools. Evidence is request-local and bounded (eight items, bounded
text), output is structured and validated, and insufficient evidence remains
available. Conversation context is not factual evidence. Citation IDs must
match supplied labels; final citations are rebuilt from trusted retrieval
metadata, not model-provided URLs/fields. Added tests explicitly reject external
URL labels and extra citation metadata. Existing tests cover prompt payload
separation, unknown-ID rejection before streaming deltas and trusted citations.
These are deterministic application boundaries, not proof that an LLM always
obeys instructions or gives correct/fully grounded answers. Formal evaluation
and synthetic live Gemini validation remain Phase 9C.

Triage exposes exactly create_escalation. SDK automatic execution is disabled;
one candidate, forced allowed function, strict category/priority and extra-field
validation, summary at most 1,200 characters, capped output and two transient
retries. Trusted escalation/run IDs are supplied by the server, not the model.
No shell, files, web, code-execution or arbitrary database tools exist.

## Public rate limiting and workers

SQL uses actual database clock_timestamp and epoch-aligned fixed windows. Quotas
remain session creation 30/minute + 300/hour per public ID; turn processing
6/minute + 60/hour per session; history 60/minute; feedback 20/minute; human
request 10/minute. Validated IDs, not caller-selected identities, select quota.
Counters contain no IP/device/hash/transcript/prompt content.

Real last-slot tests use a coordinator row lock and two independent PostgreSQL
transactions. Both contenders must be observed waiting at the lock barrier;
after release exactly one claims and one receives PT429, with final counter at
the limit. Only fresh random synthetic infrastructure rows are committed, then
deleted and absence checked. Existing libpq uses verify-full TLS; PGSSLROOTCERT
selects the trusted Supabase CA downloaded over verified HTTPS (otherwise existing
certifi roots apply). The official Supabase CA is required for this project's
certificate chain. Certificate/hostname verification is never disabled and no
new dependency is installed. See
[Supabase's certificate guidance](https://supabase.com/docs/guides/platform/ssl-enforcement).
This is not mocked Python, HTTP load or AI traffic.
Run separately from **all** CLI operations: even a metadata db query can rotate
the ephemeral CLI login password. Superseded overlapping/failed-connection
runs are not security successes. The transactional runner never resets the DB.

Minute/hour atomicity, processing/completed replay with no added quota, failed
retry with exactly one new attempt, and absence of rejected messages/turns are
checked. New boundary tests seed exhausted previous/future windows and invoke
the real helper at DB time under Pacific/Chatham timezone, checking exact active
window and next-boundary expiry. They do not replace the clock or wait for a
wall-clock hour transition; they assert the epoch boundary selection contract.
Fixed windows can allow adjacent-window bursts; shared public-ID quota can be
exhausted by another visitor, and session spreading is not per-person bot
protection or an aggregate AI budget.

Workers poll every 60 seconds, process at most ten items with concurrency two,
deduplicate IDs, and use DB attempt/backoff/stale-run fences. Recovery RPCs cap
results at twenty and attempts at three. Missing optional providers skip their
work; safe failures do not crash startup. Rate cleanup caps each indexed batch
at 500, at startup/every ten cycles. Polling is intentionally continuous, but
individual work/batches/retries are bounded; capacity/load tuning remains later.

## Secrets, logging and dependencies

Manual review covered SUPABASE_SECRET_KEY, GEMINI_API_KEY, RESEND_API_KEY,
service_role, Authorization, Bearer, apikey, password, token, private_key,
BEGIN PRIVATE KEY and eyJ references. Matches are environment names, constrained
gateway headers, authentication logic or synthetic tests, not committed real
credentials. Secret settings use SecretStr, request credentials hide repr, .env,
private keys and CLI local state are ignored; .env.example has placeholders only.
Application code does not log transcripts, prompts, evidence, token/hash values,
JWTs or SQL/provider payloads; gateways expose allow-listed safe errors. The
widget's only warning is a fixed configuration message. Third-party/hosting
logging and reverse-proxy request/header capture require deployment review.

On September 18, npm audit for the current lockfile reported zero listed
advisories, including development dependencies. pip check reported no broken
requirements. Existing Python tooling reviewed installed/resolved packages;
[OSV's free package/version query API](https://google.github.io/osv.dev/post-v1-querybatch/)
returned no advisories for 44 installed third-party PyPI distributions (runtime,
transitive and development, including pip; local editable application excluded),
with no required pagination. No scanner package or dependency upgrade was added.
There were no findings to classify as reachable/dev-only/transitive/not
applicable. This dated database snapshot is not a zero-vulnerabilities claim;
repeat checks for deployments/updates and assess reachability of future findings.

## Verification record and remaining work

Baseline: 489 backend / 201 frontend tests, Ruff lint/format, frontend lint/build
and whitespace checks passed before healthy code changes. The broad original
database run exposed stale final-schema assumptions: hidden creator/vector
columns, hidden malformed Storage paths, revised safe error wording, and newly
required closed-conversation fields. Tests were corrected without weakening
grants or changing applied migrations. Long hosted tests also needed a refreshed
DB-time history counter before asserting retry metadata after a minute boundary.
Invalid nested data-modifying test CTEs were corrected; current Supabase Storage
SQL-delete guards are asserted, never bypassed or disabled.
Full final results are recorded below after migration preflight/application.

Latest passing post-migration result for every current suite (sixteen suites,
**1,004 assertions**; all synthetic and rolled back, none skipped):

| Suite | Assertions | Result |
| --- | ---: | --- |
| admin_lifecycle_security.test.sql | 69 | PASS |
| admin_operations_security.test.sql | 86 | PASS |
| auth_workspace_rls.test.sql | 9 | PASS |
| customer_chat_security.test.sql | 48 | PASS |
| customer_feedback_handoff_security.test.sql | 38 | PASS |
| escalation_automation_security.test.sql | 54 | PASS |
| escalation_triage_security.test.sql | 60 | PASS |
| final_security_matrix.test.sql | 388 | PASS |
| fixed_window_boundaries.test.sql | 24 | PASS |
| knowledge_embeddings_security.test.sql | 36 | PASS |
| knowledge_extraction_security.test.sql | 36 | PASS |
| knowledge_source_security.test.sql | 26 | PASS |
| knowledge_upload_recovery.test.sql | 16 | PASS |
| public_api_rate_limits.test.sql | 61 | PASS |
| semantic_retrieval_security.test.sql | 28 | PASS |
| widget_configuration_security.test.sql | 25 | PASS |

The full original inventory was inspected and executed, not only the previously
selected Phase 8 suites. Database preflight covered all suites with 016 inside
rolled-back transactions; reviewed dry run contained only 016, and normal hosted
push applied only 016, with no seeds/roles/reset. Initial setup failures and stale
test failures are not counted as successes. The broad final-schema matrix adds
current grant/function/role/storage coverage, and boundary coverage is separate
from the existing public-API atomicity/replay tests.

Final local checks: **521 backend / 201 frontend tests PASS**, Ruff lint/format
including three database test scripts PASS, frontend lint and TypeScript/Vite
build PASS, Git whitespace check PASS. No application frontend or dependency
manifest/lockfile changes were necessary. The bundle-size warning is non-blocking.

**Final real database concurrency result: PASS for both scopes.** Each used two
distinct backend PIDs with actual ungranted locks observed behind the coordinator.
session_minute returned one CLAIMED / one PT429 and final count 30; turn_minute
returned one CLAIMED / one PT429 and final count 6. Both synthetic counters were
removed and absence verified. Earlier certificate and activity-observation setup
failures were UNVERIFIED, not limiter failures or passing tests. The final helper
uses backend PIDs/pg_locks because poolers need not preserve application_name and
transaction activity snapshots are not reliable lock barriers.

**Phase 9A security/database baseline is complete; all Phase 9 is not.** No live
Auth browser, customer/Gemini, Storage API byte-deletion or capacity journey is
claimed. Current configuration presence checks found no customer-server secret,
Gemini key or email key; safely supplied credentials and synthetic authenticated
fixtures are needed before live end-to-end journeys, with email only needed for
notification delivery. No actual configuration values were printed.

To reproduce using an already authenticated/linked development CLI and existing
backend environment, run from the repository root, one command at a time:

```powershell
.\backend\.venv\Scripts\python.exe supabase/tests/run_hosted_security.py
$env:PGSSLROOTCERT = 'C:\path\to\downloaded\prod-ca-2021.crt'
.\backend\.venv\Scripts\python.exe supabase/tests/rate_limit_concurrency.py
```

The race also requires existing psql/libpq on PATH. Its credentials are captured
privately from the existing CLI dry-run connection setup; no secret is written
or printed. Never overlap it with other Supabase CLI commands. Optional
--preflight-016 applies only that grant migration inside test transactions;
--psql selects the existing direct client for diagnostics. Neither resets the
hosted project. Failure/missing execution is FAIL or UNVERIFIED, never PASS.

Phase 9B browser journeys and 9C formal RAG/live synthetic validation are not
started. A possible 9D capacity/performance regression remains. Phase 10 must
recheck genuinely free deployment tiers and validate HTTPS, exact production
CORS, Auth redirect configuration, platform/proxy logs, secret stores, CSP and
frame-ancestors compatible with /embed (never blanket DENY), COOP/COEP/cookie
effects, frontend asset/security headers, cache behavior and widget operation
from an independent origin. The existing frontend bundle-size warning remains.
