# Embedding SupportPilot

Phase 8A is complete in application code and automated tests. Phase 8B (rate limiting, abuse controls, consistent API errors, Retry-After and integration polish) and production deployment are not complete. Use synthetic, non-confidential portfolio content only.

## Configure and copy

Sign in as a workspace owner/admin and select **Widget** at `/app/widget`, after Knowledge Base in navigation. Members cannot open the settings page or call its settings RPCs. The page shows workspace, availability, public widget/chat ID, public chat link and a copyable embed snippet. A public ID is an integration identifier, not a secret, API key or authentication token. It reuses `workspace_chat_configs.public_id`; there is no separate widget identity.

Paste the generated snippet before your website's closing `</body>` tag:

```html
<script
  src="https://YOUR-SUPPORTPILOT-ORIGIN/supportpilot-widget.js"
  data-supportpilot-public-id="<PUBLIC_ID>"
  async
></script>
```

Replace both placeholders with the values copied from Widget settings. The page uses its current `window.location.origin`, so local settings naturally generate `http://localhost:5173/supportpilot-widget.js`. Localhost is only for local testing; a visitor cannot reach your machine's localhost. The public path stays `/supportpilot-widget.js` after a Vite production build. Copy reports success accessibly; if clipboard access is denied/unavailable, select and copy the read-only code field instead.

Optional attributes:

| Attribute | Behavior |
| --- | --- |
| `data-supportpilot-public-id` | Required existing public UUID; invalid/missing values mount nothing and warn at most once. |
| `data-supportpilot-label` | Plain text, trimmed, truncated to 40 characters; default `Support`. |
| `data-supportpilot-position` | `left` or `right`; default/right for other values. |

No HTML, CSS, JavaScript, API/backend URL, origin, workspace ID, model or prompt override is accepted. The script derives the iframe origin from its own script source, not host data attributes. Duplicate execution keeps one launcher; a different second configuration keeps the first and warns once. The loader itself necessarily downloads before it can validate configuration; invalid IDs cause no iframe/chat network requests.

## Availability

Owner/admin Enable/Disable sends strict expected/current-next booleans through verified user JWT plus publishable key to fixed RPCs. A locked database row rejects stale and identical actions, never rotates public_id and never grants general table UPDATE. The page waits for confirmed server state. A conflict says: “The widget configuration changed before this action was completed. Refresh and try again.” Other mutation failures are safe and offer refresh. Workspace/identity changes discard prior configuration and fence late responses; admin widget config is not persisted in browser storage.

Disabling blocks new public customer sessions and makes chat unavailable; existing sessions remain governed by the existing server-side enabled checks. It does not delete conversations or forcibly remove a launcher from every already-open website. Re-enable preserves the identifier. Browser disabled-state smoke was not performed on a real workspace; hosted transactional synthetic tests verify disable/re-enable enforcement.

## Isolation and keyboard behavior

The dependency-free script creates only a Shadow DOM launcher/panel. The React chat runs inside a SupportPilot-origin iframe at `/embed/<public_id>`, reusing hosted chat business logic rather than a second implementation. Shadow DOM isolates presentation; the cross-origin iframe's same-origin policy isolates customer state. The host receives no Supabase/Gemini credentials, JWT, customer session token, conversation ID, retrieved evidence or transcript. No credentials enter iframe query parameters, attributes, the presentation registry or postMessage; no postMessage is used. The launcher does not inspect host text, location, cookies, storage or account information. Shadow DOM is not a security boundary against host scripts; same-origin hosts are not isolated from scripts on that same origin.

The iframe title is `Support chat`, referrer policy is no-referrer, and sandbox is exactly `allow-scripts allow-forms allow-same-origin`. Scripts/fetch/streaming, forms and ordinary-origin storage are required by existing chat. Top navigation, popups and downloads are not permitted. Browsers can still block or partition third-party storage, so reload persistence is best effort; existing storage failure handling remains shared. Automated tests cover embedded history, streaming, citations, feedback and human requests with mocked APIs, plus iframe sandbox attributes. A live sandbox storage/fetch/streaming journey remains unverified until safely configured synthetic customer sessions are available.

Open with the native Support button. Close hides but preserves the iframe during the same page visit and returns focus to the launcher. Escape closes when focus is in the launcher/toolbar. Keys inside the cross-origin iframe cannot bubble to the host; use Shift+Tab back to the Close control if needed. There is no focus trap or credential-bearing message bridge. The panel targets 400×640 on desktop and limits dimensions to the viewport with margins.

API requests come from the SupportPilot iframe origin, not the external website. Keep FastAPI CORS restricted to explicitly configured frontend origins with GET/POST/PATCH/PUT, including feedback PUT. Do not add wildcard CORS or whitelist arbitrary customer websites. Deployment must separately verify that frontend framing headers permit the intended host and the website's CSP permits the script (`script-src`) and iframe (`frame-src`). No deployment provider/header policy has been validated or weakened in Phase 8A.

## Independent local demo

Use the existing setup described in README; run three terminals from the repository root:

```powershell
# Terminal 1: existing backend virtual environment
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2
cd frontend
npm run dev
```

```powershell
# Terminal 3: existing Python, independent synthetic host
cd examples/widget-host
python -m http.server 4174 --bind 127.0.0.1
```

Open `http://localhost:4174/?publicId=<public-id>&supportOrigin=http://localhost:5173`, replacing the ID with a synthetic demo workspace's copied public ID. Host port 4174 and iframe port 5173 are genuinely different origins. The fictional Acme Demo Store has independent styles/content, no checkout, account collection or duplicated chat engine.

Only this demo page accepts `supportOrigin`; it validates HTTP/S, no credentials, a bare origin with no path/query/fragment, and a compatible UUID. The production widget has no origin override. Never add credentials to this URL.

The Phase 8A manual smoke used an unused synthetic UUID, not a real workspace/public identifier. It verified demo rendering, one launcher, unchanged host styles, iframe `/embed` loading, close/reopen, toolbar Escape and host refresh. Safe unavailable state was expected because customer-chat server secret and Gemini are not configured. This verifies the external-origin shell, not live customer sessions, persisted session restoration, grounded answers or authenticated admin browser toggles. No live Gemini call was made.

## Troubleshooting and remaining checks

- No launcher: check script loading, compatible public UUID, browser console's single safe warning and host CSP. Duplicate configurations keep the first widget.
- Wrong destination: use the script from the intended SupportPilot origin; data-origin/data-backend overrides are intentionally ignored.
- Unavailable chat: check enabled settings, public ID, migrations through 014 and existing backend customer-chat setup. Without server-only customer-chat configuration, those endpoints safely return 503. Gemini is separately required for live grounded generation. Never put either server secret in frontend/host code.
- Connection refused: start backend/frontend and the independent demo on their documented ports. Check `/api/health` at port 8000 before investigating chat.
- API/CORS error: configure the actual SupportPilot frontend origin, not the external host; preserve feedback PUT. Host HTTP/S pages must load matching secure resources in production to avoid mixed-content blocking.
- Copy unavailable: manually select the read-only embed code. Copy failures do not change configuration.
- Conflict: refresh settings and retry against returned server state, not a guessed optimistic state.
- Reload loses chat: third-party storage restrictions vary by browser; verify the target browser. No host storage workaround or session-token messaging is provided.

Current validation: 436 backend and 177 frontend tests passed; Ruff lint/format and frontend lint/build passed (non-blocking application bundle-size warning). Hosted migration 014 was applied after a dry run containing only 014, without reset or data deletion. Only widget configuration (25 assertions), admin operations (86) and customer chat (48) pgTAP suites were rerun in rollback transactions for this checkpoint, not the full database suite. No new AI/provider/service was introduced. Live synthetic authenticated/customer journeys, deployment framing/CSP checks and Phase 8B public abuse protection remain before a production-ready public demo.
