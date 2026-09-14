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
| FastAPI server | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Prepared for authenticated user/JWT flows in Phase 2B. |
| Privileged server operations | `SUPABASE_SECRET_KEY` | Server-only; bypasses RLS and should remain unset until a narrowly scoped operation genuinely requires it. |

Never place `SUPABASE_SECRET_KEY` in a `VITE_` variable or frontend source. Normal user requests should carry the user's Supabase access token and rely on RLS rather than a secret-key client.

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

The pgTAP suite is in `supabase/tests/database/`. Local database tests require Docker and the Supabase CLI:

```bash
supabase start
supabase db reset
supabase test db
```

The local stack is development-only. Do not expose it to external traffic. After applying the migration to a remote development project, repeat the access scenarios with separate test users before beginning Phase 2B.
