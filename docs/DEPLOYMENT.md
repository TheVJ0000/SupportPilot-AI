# SupportPilot AI deployment guide

## Architecture

The zero-cost portfolio deployment uses three Render resources from `render.yaml`:

- `supportpilot-api`: a Free Python web service running FastAPI;
- `supportpilot-web`: a free static site containing the React/Vite application;
- `supportpilot-widget-demo`: a second free static site proving that the widget can be embedded from a different public origin.

The existing Supabase Free project remains the only database, Auth, Storage and pgvector platform. Gemini remains the configurable generation and embedding provider. Resend remains optional and disabled when its settings are absent. Render does not host a database, queue, persistent disk or key-value service for this project.

## Live portfolio endpoints

- Application: <https://supportpilot-web-6w61.onrender.com>
- API health: <https://supportpilot-api-ytih.onrender.com/api/health>
- External widget demonstration: <https://supportpilot-widget-demo.onrender.com>

These are public demo URLs, not evidence of commercial customers, uptime or an
always-on production SLA.

## Why Render was chosen

Render currently provides Free web services and free static sites, supports monorepo root directories and Blueprint configuration, supplies managed HTTPS `onrender.com` URLs, and can run the existing Python and Vite build commands. This is suitable for a portfolio demonstration without buying a domain or enabling a paid compute plan.

Configuration was checked against Render's current official documentation for
[Free services](https://render.com/docs/free), the
[Blueprint specification](https://render.com/docs/blueprint-spec),
[Python version pinning](https://render.com/docs/python-version),
[static-site rewrites](https://render.com/docs/redirects-rewrites), and
[health checks](https://render.com/docs/health-checks) on September 19, 2026.

## Free-tier limitations

Render's Free web service sleeps after 15 minutes without inbound traffic and can take about one minute to wake. Its filesystem is ephemeral. Free instance hours, bandwidth and build minutes have account limits; without a payment method, exhaustion can suspend services or builds rather than create a bill. Free services can restart at any time and are not an always-on production SLA.

Static sites are free but still consume included bandwidth and pipeline minutes. Private-repository GitHub Actions minutes are also subject to the GitHub account's included allowance. The project uses only standard GitHub-hosted runners and does not assume unlimited CI.

Do not add keep-alive traffic to defeat sleeping. Do not add a payment method, paid Render plan, Render database, persistent disk, Redis/Key Value, paid monitoring, paid queue or custom domain for the initial demo.

## Prerequisites

1. A Render account connected to the GitHub account that can read this repository.
2. The existing Supabase Free project migrated through `202609180016_security_hardening.sql`.
3. The existing Supabase project URL, publishable key and a server-only secret key.
4. The Gemini API key from the billing-disabled Free project.
5. Optional Resend settings only if a free, safely verified sender is already available.
6. A successful GitHub Actions run on `main`.

No migration 017 is needed for deployment. Never run `supabase db reset` against the hosted project.

## Render Blueprint deployment

1. In Render, choose **New → Blueprint** and connect `TheVJ0000/SupportPilot-AI`.
2. Select branch `main` and Blueprint path `render.yaml`.
3. Review that there are exactly three resources and no database: one Free Python web service and two static sites. If a resource name is already taken in the workspace, adjust only the non-sensitive Render service name.
4. Supply each `sync: false` value in Render's protected environment-variable UI. Do not paste secrets into GitHub, a commit, frontend settings or chat.
5. Keep automatic deploys off for the first deployment. Render's current Blueprint setting is `autoDeployTrigger: off`.
6. Create/sync the Blueprint. Record the HTTPS URL Render assigns to `supportpilot-api`, `supportpilot-web` and `supportpilot-widget-demo`—do not infer or guess them.
7. Set `FRONTEND_URL` on `supportpilot-api` to the exact `supportpilot-web` HTTPS origin, with no path or wildcard.
8. Set `VITE_API_BASE_URL` on `supportpilot-web` to the exact `supportpilot-api` HTTPS origin. Because Vite bakes variables in at build time, redeploy the static site after changing it.
9. Confirm the remaining required values, then manually deploy the backend and frontend. Deploy the demo site after the frontend URL is known.
10. After CI and the first production smoke test pass, automatic deployment may be changed to deploy only after checks pass. It is intentionally off in Phase 10A.

Render's Blueprint service references expose private host/port values, not a supported public external URL for this static-to-public-web pairing. Therefore the two public origins are deliberately `sync: false` and entered once their real URLs exist.

## Required backend secrets and configuration

Enter these only for `supportpilot-api`:

| Variable | Purpose |
| --- | --- |
| `FRONTEND_URL` | Exact deployed frontend HTTPS origin and only CORS origin |
| `SUPABASE_URL` | Existing Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Token verification and caller-scoped operations |
| `SUPABASE_SECRET_KEY` | Server-only customer-chat and worker operations |
| `GEMINI_API_KEY` | Server-only embeddings, generation and triage |

`APP_ENV=production`, the selected model names, embedding provider/dimension and Python 3.12.14 are non-secret values committed in the Blueprint. `RESEND_API_KEY` and `RESEND_FROM_EMAIL` are optional; leave them unset to retain pending notifications without attempting email delivery.

`SUPABASE_SECRET_KEY` bypasses Row Level Security and is the most sensitive Supabase credential in this deployment. It must never be placed in a `VITE_*` variable, HTML, JavaScript, a widget snippet, source control or a frontend service setting.

## Required frontend build variables

Enter only these browser-safe values for `supportpilot-web`:

- `VITE_SUPABASE_URL`: existing Supabase URL;
- `VITE_SUPABASE_PUBLISHABLE_KEY`: browser publishable key, constrained by RLS;
- `VITE_API_BASE_URL`: exact deployed backend HTTPS origin.

They are build-time variables. A change requires a new static-site build. The production build scans `dist` for server-secret names and safe secret markers without printing secret values.

## How to obtain backend and frontend URLs

Open each resource in the Render Dashboard and copy its displayed `https://…onrender.com` URL. Use the displayed value exactly. Service names can collide and Render URLs are platform-assigned, so this guide intentionally contains no guessed hostname.

## CORS configuration

The API accepts only `FRONTEND_URL`, strips a trailing slash, and permits `GET`, `POST`, `PUT` and `PATCH`. Do not use `*`, add the external business/widget-host origin, or enable credentials. The external page loads an iframe from the SupportPilot frontend; browser API requests still originate from the SupportPilot frontend origin.

## Supabase Auth URL configuration

After the real frontend URL exists, open the existing Supabase project’s Auth URL settings:

1. Set **Site URL** to the exact deployed frontend HTTPS origin.
2. Add the production redirect URL needed by the app, using that same origin (for this client-side flow, the origin/root is sufficient).
3. Preserve `http://localhost:5173` as an allowed development redirect.

Do not invent a production URL or remove localhost until local development is intentionally retired.

## Post-deployment smoke tests

Run these once after all real URLs and secret-store values are configured:

1. Open the backend `/api/health`; require HTTP 200 and the expected small JSON response.
2. Open the frontend root, then directly refresh `/login`, `/register`, `/app`, `/chat/<synthetic-public-id>` and `/embed/<synthetic-public-id>` to confirm the SPA rewrite.
3. Register or sign in with an approved synthetic test identity and verify workspace isolation.
4. Upload only a small synthetic Northstar document, process it and verify citations.
5. Perform exactly one bounded Gemini generation check. If the provider again returns a transient error, record it and stop—do not repeatedly retry manually.
6. Verify a synthetic customer session, streaming answer, history, feedback and confirmed human request using the server-only Supabase configuration.
7. Check browser network/CORS behavior and confirm no secret, JWT, raw session token, transcript, evidence or prompt appears in page source, the host page, URLs or public logs.
8. Verify the external widget demo as described below.
9. Inspect Render logs for safe errors only and confirm no verbose/debug logging is enabled.

The health probe is deliberately local and lightweight. It does not call Gemini, Supabase or Resend and therefore consumes no external quota.

## Widget demo

Use a synthetic workspace widget public ID from the application’s widget admin page. Open:

```text
https://<widget-demo-origin>/?publicId=<synthetic-public-id>&supportOrigin=https%3A%2F%2F<supportpilot-frontend-origin>
```

The existing page validates the UUID-shaped public ID and the HTTP(S) SupportPilot origin before loading `/supportpilot-widget.js`. Never put a workspace UUID, JWT, Supabase key, customer session token or backend secret in this URL. `publicId` is the public widget identifier, not the workspace identifier.

## Security headers and CSP

Both static sites set `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and a conservative `Permissions-Policy` that disables camera, microphone and geolocation. There is intentionally no global `X-Frame-Options: DENY`, because `/embed/:publicId` must be frameable by external sites.

A Content Security Policy is deferred until Render assigns the exact frontend/API origins and the deployed Supabase origin is confirmed. The post-deployment policy must narrowly allow the frontend, API and Supabase connections while preserving the external widget iframe. Do not use a wildcard `connect-src` or deploy a guessed CSP.

## Cold-start behavior

After 15 idle minutes, the first backend request can show Render’s loading page and take about one minute. Retry the user action once the service is awake. Static frontend assets remain CDN-hosted, but API-backed features wait for the backend cold start.

## Background-worker limitation

Triage and notification recovery run inside the FastAPI process only while it is awake. Pending work and attempt fences live in Supabase, not memory or local disk. Startup immediately resumes eligible work and the worker continues at its bounded interval while awake. During free-tier sleep, automation is not continuously processed; the next backend wake/startup resumes pending work. This is acceptable for the portfolio demo and is not an always-on automation claim.

## Persistence and logs

Application persistence remains in Supabase Postgres and private Supabase Storage. Render's ephemeral filesystem is not used for durable application data; discardable runtime/build files may be ephemeral. There is no SQLite database or local durable queue.

Production configuration does not enable debug logging. Application code does not log secret settings, raw customer session tokens, JWTs, transcripts, retrieved evidence, full prompts, `PGPASSWORD` or provider payloads. Review Render proxy/platform logging after deployment, because third-party platform behavior is outside the repository’s control.

## Secret rotation

Rotate a credential in its provider first, update the corresponding Render backend environment value, and redeploy/restart the backend. Rotate the browser publishable key only with coordinated backend/frontend updates and rebuild the frontend. Treat any value shown in logs, source control, screenshots or a browser bundle as compromised. Never put the replacement into Git.

## Rollback

Render Free web services retain only limited recent rollback history. Roll back to a previously healthy commit in the Render Dashboard or redeploy a reviewed Git commit. Database migrations are not run by the Blueprint; never solve an application rollback with `supabase db reset`. If a schema rollback is ever needed, design a new forward migration after review.

## Troubleshooting

- **Backend will not start:** confirm all required backend values are on the API service, Python is 3.12.14, and the start command uses `$PORT` without `--reload`.
- **Frontend calls localhost:** set the real `VITE_API_BASE_URL` and trigger a new frontend build.
- **CORS failure:** make `FRONTEND_URL` exactly match the browser’s frontend origin, including HTTPS and excluding paths/trailing wildcard.
- **Direct route returns 404:** confirm the `/*` → `/index.html` rule is a rewrite.
- **Auth redirect fails:** add the real frontend origin in Supabase Auth while preserving localhost.
- **Customer chat returns controlled 503:** configure `SUPABASE_SECRET_KEY` on the backend only.
- **Generation returns 503:** confirm Gemini configuration once; respect bounded retries and provider availability instead of looping calls.
- **Widget does not load:** use the real HTTPS frontend origin as `supportOrigin` and a synthetic public widget ID, not a workspace ID.
- **Worker seems delayed:** wake the backend and allow startup recovery; free-tier sleep means it is not always running.

## Zero-cost rules and known limitations

Keep billing disabled where already confirmed, remain on free plans, monitor included usage manually, and use synthetic/non-confidential data only. No custom domain is required; Render’s HTTPS static-site URL is suitable for a portfolio or client demo.

## Phase 10B production record — September 21, 2026

The Blueprint is deployed in the authorized Render workspace with three free
resources and manual deploys:

- Frontend portfolio: <https://supportpilot-web-6w61.onrender.com>
- Backend health: <https://supportpilot-api-ytih.onrender.com/api/health>
- External widget demo: <https://supportpilot-widget-demo.onrender.com>

The API, frontend and widget were deployed from reviewed commit
`35671811115dfee83ce787c81349371b72719771` before this documentation-only
checkpoint. The original deploy exposed one real configuration-parsing defect:
Pydantic rejected Render's string form of the fixed 768 embedding dimension.
The narrow fix and regression are in that commit. No migration 017 was needed.

Production verification passed the provider-free health route, landing page,
direct `/login`, `/register` and authenticated SPA routes, exact Supabase Site
URL and production redirect while retaining `http://localhost:5173`, synthetic
authentication/session restoration, and protected-route behavior. A synthetic
`Northstar Outfitters — Synthetic Demo` workspace processed and indexed five
small FAQ sources. One bounded supported question completed through Gemini,
SSE, pgvector and persistence with the correct FAQ citation. One deliberately
absent price-match question returned the controlled insufficient-evidence text.
Feedback, history reload, human request, durable escalation creation, admin
dashboard/lists/detail, and resolve/reopen lifecycle all passed. The separate
widget host loaded the SupportPilot-origin iframe and passed close/reopen; its
host storage contained no customer state and host text contained no transcript.

The escalation's optional Gemini triage classification recorded two safe
provider-unavailable attempts before the worker's third automatic attempt
completed successfully as a low-priority policy issue. The durable audit trail
and manual lifecycle remained available throughout. Resend was not configured,
so the resulting notification stayed pending and no email was sent.

Production CORS accepted only the exact frontend origin and returned no allow
origin for a random untrusted origin. Allowed methods remained GET, POST, PATCH
and PUT; DELETE was absent. Frontend and widget responses returned `nosniff`,
`strict-origin-when-cross-origin`, and `camera=(), microphone=(), geolocation=()`;
neither set a global `X-Frame-Options: DENY`. The deployed bundle contained the
expected public API/Supabase URL and no server secret-key, Gemini-key or
Resend-key names/values. Render log review found no secret names, JWTs, customer
session tokens, transcript text, retrieved evidence or prompts.

A CSP remains intentionally unshipped. The same frontend hosts the authenticated
app, public chat and arbitrary-customer `/embed` surface; a single safe policy
must preserve Supabase HTTPS/WSS Auth traffic and explicitly support third-party
embedding without broad `connect-src *` or `frame-ancestors 'none'`. The smoke
proved the current demo origin but did not establish the complete future host
allow-list, so a guessed header would be less secure than the documented gap.

One authenticated admin load observed the documented Render Free wake delay of
roughly 50 seconds; warm static and health checks were under one second to a few
seconds. No keep-alive was added. The in-process triage/outbox worker still runs
only while the backend is awake and resumes durable eligible work on startup; it
is not represented as always-on processing.

Phase 10 is complete for the zero-cost public portfolio baseline. Remaining
limitations are CSP finalization for an explicit embedding-host policy, Render
Free cold starts/worker sleep, optional email delivery, aggregate AI-budget/bot
protection, and unmeasured production capacity. Automatic deploys remain off;
no paid billing, database, disk, cache, queue, domain or artificial traffic was
introduced.
