# Phase 9B browser integration

Phase 9B validates the real browser → React → HTTP → FastAPI path with synthetic
external-provider boundaries. It is **deterministic browser integration**, not
live hosted Supabase, Gemini, Resend, or production validation. No account,
provider credential, billing, or AI quota is required.

## Run locally

Use Node >=22.12 and Python >=3.12. Install the existing backend development
dependencies into `backend/.venv` first (see README). The configuration uses
`.venv/Scripts/python.exe` on Windows and `.venv/bin/python` elsewhere.

From `frontend`:

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
# Optional visible Chromium:
npm run test:e2e:headed
```

Only Chromium is installed for this phase. Version 1.63.0 is locked in the
frontend development dependencies; browser binaries stay in Playwright's local
cache, not Git. On Linux, Chromium may additionally need OS libraries installed
using Playwright's documented `install-deps chromium` workflow.

[Playwright webServer orchestration](https://playwright.dev/docs/test-webserver)
starts and stops three loopback servers:

| Surface | URL | Entry point |
| --- | --- | --- |
| React/Vite | `http://127.0.0.1:5175` | Existing frontend development script |
| FastAPI test instance | `http://127.0.0.1:8001` | `tests/e2e_app.py` |
| Independent synthetic store | `http://127.0.0.1:4175` | Existing `examples/widget-host` |

The ports deliberately avoid normal local development at 5173/8000/4174. All
must be free: `reuseExistingServer: false` prevents silently testing a user's
ordinary application instance. Do not stop an unrelated server to free a port.
The backend requires no Docker. Test servers are temporary; they do not replace
the normal local application or configure its authentication.

## Boundary and security

`backend/tests/e2e_app.py` creates a **separate FastAPI instance**. It includes
the real API router, copies the existing middleware configuration, and replaces
only external dependencies on that test instance. The production app's routes
and dependency overrides are not changed. Its lifespan worker is not started,
and immediate triage is replaced with a no-op callable: neither Gemini nor
notification delivery can run.

Admin requests use the real authenticated dependencies, routes, Pydantic models
and `AdminOperationsGateway`; `httpx.MockTransport` replaces its Supabase RPC
transport. Customer requests use the real session/token hashing, chat service,
request validation, error mapper and SSE serialization, with in-memory
persistence/retrieval plus deterministic embeddings and generation. FAQ
extraction uses the real processing endpoint and extractor/chunker, ending in
pending/awaiting indexing rather than pretending Gemini indexing succeeded.

The browser intercepts only `https://supportpilot.example.test`, the synthetic
Supabase Auth/PostgREST boundary used by the **existing** frontend client. Own
FastAPI `/api` requests are never intercepted. Each test gets a new random opaque
bearer token and password, synthetic `@example.test` identity, fresh browser
context and reset fixture state. The test verifier accepts only that reset's
token; the production verifier remains unchanged. Synthetic publishable-key
placeholders and fake UUIDs are not usable credentials.

Two workspace fixtures have different dashboard counts, separate widget IDs
and availability, and separate list/knowledge results. Alpha contains open,
human-requested and closed/resolved conversations, and open/in-progress/resolved
escalation states. Beta cannot retrieve Alpha detail records. Expected-state
mutations and explicit release gates expose pending updates and a delayed Alpha
response without sleeps. Tests use one worker and zero retries: do not override
the worker count while sharing this in-memory harness.

Test-only `/_e2e/*` controls reset/release/observe synthetic state. They are not
authenticated management APIs and must **never be deployed or bound publicly**.
The documented runner binds 127.0.0.1 only. Backend regressions assert fresh
normal startup has no harness import, overrides, E2E OpenAPI routes, bypass
controls or fixture credential constants; loading the harness does not mutate
production, and its old/random/missing tokens fail. Backend packaging includes
`app*`, not tests. Frontend E2E sources are outside application imports and
Vitest collection, but are included in TypeScript and ESLint validation.

## Coverage and observations

The nine spec files under `frontend/e2e` cover 24 Chromium tests:

- `auth`: labelled login, normal Workspace sign-in destination followed by the
  role-aware `/app` landing, owner/admin/member navigation and member route guards.
- `workspace-isolation`: Alpha transcript removal, Beta list, and late Alpha
  dashboard response unable to overwrite Beta.
- `knowledge`: ready/processing sources, unsupported and >10 MiB file validation,
  FAQ creation at the external database boundary, real FastAPI extraction and
  safe pending/indexable state. No successful live Storage upload is claimed.
- `conversations`: list/disabled pagination, transcript roles, trusted page
  citation, feedback, resolution, reopening, historical handoff staying paused,
  plus a safe 409 and refresh.
- `escalations`: disabled pending control, server-confirmed start, resolve,
  reopen and close.
- `widget-admin`: current-origin/public-ID snippet, copy action, and availability
  changes that wait for server confirmation.
- `customer-chat`: actual `text/event-stream`, gated multiple deltas then
  completion, citations/feedback/history reload, failed partial removal,
  same-ID retry with one customer message, rejected feedback, insufficient
  evidence plus confirmed handoff, manual 429 cooldown and closed history.
- `external-widget`: one launcher even after duplicate script execution,
  host-style isolation, titled/sandboxed separate-origin iframe, exchange,
  feedback, close/reopen, toolbar Escape/focus return and host reload. Host
  storage stays empty, no host `message` event carries customer state, and its
  document contains no transcript/token/credential data. No same-origin
  protections are bypassed. Disabled widgets show safe unavailable copy.
- `mobile`: 390×844 dashboard navigation, hosted chat and embedded panel/composer
  usability with no horizontal overflow. This is not a cross-device matrix.

The 429 test advances the browser clock through a two-second fixture cooldown,
checks no automatic requests occurred, then manually retries the same ID. This
is UX validation, not a replacement for Phase 9A's real PostgreSQL limiter races.
The internal-error case returns a controlled SQL/provider-looking gateway code
through real FastAPI mapping and asserts no raw payload appears in the browser.

Every test fails on `pageerror` or unexpected `console.error`. The only allowance
is Chromium's exact failed-resource HTTP-status message from the local API,
when a specific negative scenario explicitly expects 404, 409, 429 or 502.
JavaScript errors and other origins/statuses are never ignored. A cancelled
request can cause Windows Python Proactor `WinError 10054` terminal noise; it is
not a browser error and does not change assertions. There are no fixed sleeps;
locators, polling and test-server release gates synchronize state.

Semantic labels, navigation, dialog confirmation, textbox/send, launcher,
iframe title, close and Escape controls exercise accessibility basics. No WCAG
certification or automated accessibility audit is claimed. Clipboard-denied
browsers must show the existing safe manual-copy fallback.

## Results and artifacts

September 18, 2026: **24 browser tests passed, 0 failed**; separately **524 backend
pytest** and **203 frontend Vitest/RTL tests passed**. Ruff lint/format, ESLint,
TypeScript/Vite build and Git whitespace checks pass. The existing >500 kB bundle
warning remains non-blocking. A genuine closed-chat UX gap was fixed narrowly:
customers now see a closed/read-only explanation and disabled-composer
placeholder, with hosted and embedded component regressions.

HTML reports are under `frontend/playwright-report`; failure screenshots and
optional retry traces are under `frontend/test-results`. Both, `blob-report` and
`.e2e-state` are gitignored. Video is off. Trace is `on-first-retry`; default
retries are zero, so use `--retries=1` deliberately when collecting a failure
trace. Inspect locally with `npx playwright show-report` or `show-trace`.

Phase 9A's 16 hosted pgTAP suites/1,004 assertions and two PostgreSQL concurrency
races are a separate prior verification record. No SQL boundary changed here;
those checks were not rerun and migration 017 was unnecessary. No safe live
synthetic authenticated credentials were available, so the optional hosted
browser smoke remains unverified. Live Gemini is untested and was not required.
Phase 9 overall remains incomplete: formal RAG evaluation and safe synthetic
live Gemini validation are Phase 9C; deployment/CSP/free-tier checks are Phase 10.
