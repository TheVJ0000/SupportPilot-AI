# Supabase setup

SupportPilot AI uses the **Supabase Free plan** for its initial portfolio development and public demo. Recheck the current free-plan limits before deployment and do not enable paid billing for this stage.

## Create the project

1. Sign in to the [Supabase Dashboard](https://supabase.com/dashboard) and create a Free project manually.
2. Keep the generated database password in a password manager. Never commit it.
3. Open the project's **Connect** dialog to copy the Project URL and default publishable key. Individual keys are managed under **Settings → API Keys**.
4. Copy the repository's `.env.example` to `.env` and add only your local values.

No real client or confidential data should be used during the portfolio stage. Use synthetic demonstration content only.

## Key placement

Publishable keys identify a public application component. They do not grant user identity and remain constrained by database grants and Row Level Security.

| Runtime | Variables | Rule |
| --- | --- | --- |
| Browser | `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Publishable key only; values are bundled into client code. |
| FastAPI server | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Used to verify authenticated user JWTs. The publishable key supports the documented legacy-token fallback. |
| Privileged server operations | `SUPABASE_SECRET_KEY` | Server-only; bypasses RLS and should remain unset until a narrowly scoped operation genuinely requires it. |

Never place `SUPABASE_SECRET_KEY` in a `VITE_` variable or frontend source. Normal user requests carry the user's Supabase access token and rely on RLS or verified FastAPI identity rather than a secret-key client. The backend does not need the JWT signing secret.

See Supabase's current [API key guide](https://supabase.com/docs/guides/getting-started/api-keys) for key creation and rotation details.

## Apply the migration

The versioned migration is in `supabase/migrations/`. With the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started) installed:

```bash
supabase login
supabase link --project-ref <your-project-ref>
supabase db push --dry-run
supabase db push
```

Do not commit the project reference, database password, access token, or generated local credentials. Review the dry run before applying the migration.

## Verify schema and RLS

The migration must result in:

- RLS enabled on `profiles`, `workspaces`, and `workspace_members`;
- browser roles receiving only the explicit grants defined in the migration;
- authenticated users seeing only their own profile and membership row;
- workspace reads limited to members and workspace management limited to owners;
- direct browser insertion or role changes in `workspace_members` remaining unavailable;
- `create_workspace` atomically creating the workspace and its caller-owned membership.
- RLS enabled on `knowledge_sources`, with member reads and no direct browser mutation grants;
- owners/admins creating sources only through the scoped RPCs;
- members unable to create, upload, update, or delete knowledge sources;
- non-members unable to read another workspace's source metadata or private objects;
- the `knowledge-files` bucket remaining private with a 10 MB file limit.
- `recover_file_knowledge_source(uuid)` executable only by authenticated callers and authorizing only owners/admins of the source's derived workspace;
- interrupted upload recovery checking the exact stored path, moving an existing object only to `pending`, or removing only an absent-object `uploading` row.

The pgTAP suite is in `supabase/tests/database/`. Local database tests require Docker and the Supabase CLI:

```bash
supabase start
supabase db reset
supabase test db
```

The local stack is development-only. Do not expose it to external traffic. After applying the migrations to a remote development project, repeat the access scenarios with separate test users before beginning Phase 3B.

## Configure private knowledge storage

The Phase 3A migration creates and configures `knowledge-files` as a private bucket. Do not make it public in the Dashboard. SupportPilot enforces a 10 MB maximum and supports:

- PDF (`application/pdf`);
- DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`);
- TXT (`text/plain`);
- Markdown (`text/markdown`, with `text/plain` accepted for browser compatibility).

The database generates object paths in the form `<workspace-id>/<source-id>/<source-id>.<ext>`. The original filename is metadata only and never becomes an arbitrary Storage key. Owners/admins can upload and delete initialized objects; members have read-only access; non-members have no access. All browser operations use the signed-in user's JWT, the publishable key, and RLS.

Creation flows stop at `pending`. `processing`, `ready`, and `failed` are reserved for the later ingestion lifecycle. Phase 3B will add actual content validation, extraction, and chunking. Do not treat extension or MIME validation as proof of file contents.

General source deletion is not exposed in Phase 3A. Failed upload initialization can be canceled only after the Storage API confirms removal of the expected object, avoiding direct edits to Storage metadata or a database-only delete. If an `uploading` row remains after an interrupted request, an owner/admin can select **Recover upload**. The recovery RPC accepts only the source ID, locks and authorizes the stored row, and checks its exact private object path: an existing object becomes `pending`, while an absent object removes only that stale row. It also confirms an already-`pending` source without mutation after a lost finalize response.

## Configure authentication

1. Put the same project URL and publishable key in both frontend and backend variables in the local `.env` file. Do not add the secret key.
2. In the Supabase Auth URL settings, set the local site URL to `http://localhost:5173` while developing. Add only explicit redirect URLs that the application actually uses.
3. Choose whether email confirmation is required for the development project. The registration UI supports both an immediate session and a confirmation-required response.
4. Start FastAPI and the frontend with the commands in the repository README.

For modern asymmetric signing keys, FastAPI validates tokens with the project's `/auth/v1/.well-known/jwks.json` endpoint using a cached JWKS client and fixed ES256/RS256 algorithms. Legacy HS256 tokens are validated by Supabase Auth's `/auth/v1/user` endpoint with the publishable key. Issuer, audience, expiration, subject, and signature/provider validity are not bypassed.

## Hosted smoke-test checklist

Use synthetic accounts only, then verify:

- registration creates the user profile through the database trigger;
- both immediate-session and email-confirmation behavior match the project setting;
- login survives a page reload and protected routes remain inaccessible after logout;
- a new account sees workspace onboarding and `create_workspace` produces owner membership;
- one workspace auto-selects, multiple accessible workspaces can be selected, and inaccessible IDs are discarded;
- the application shell reports `Authenticated API connected` while `/api/auth/me` rejects missing or invalid bearer tokens;
- a second test user cannot read the first user's profile, membership, or workspace.
- an owner and admin can add file/FAQ sources while an ordinary member sees read-only controls;
- unsupported or oversized files are rejected before upload and again by trusted infrastructure;
- private object reads/uploads/deletes follow the workspace role policies;
- an interrupted upload exposes recovery only to owners/admins, and a member/non-member cannot invoke the recovery RPC successfully;
- recovery moves an exact existing object to `pending`, removes only an absent-object stale row, and does not change other lifecycle states;
- successful files remain `pending`, not `ready`, until a later processing phase.

This repository run did not have a hosted project configured, so these checks have not been claimed as executed.
