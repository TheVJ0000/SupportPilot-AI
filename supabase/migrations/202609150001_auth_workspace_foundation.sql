-- SupportPilot AI Phase 2A: authentication profile and workspace isolation foundation.

create schema if not exists app_private;

revoke all on schema app_private from public;
revoke all on schema app_private from anon;
revoke all on schema app_private from authenticated;
grant usage on schema app_private to authenticated;

create table public.profiles (
    user_id uuid primary key references auth.users (id) on delete cascade,
    display_name text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint profiles_display_name_length check (
        display_name is null
        or char_length(btrim(display_name)) between 1 and 100
    )
);

create table public.workspaces (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_by uuid not null references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint workspaces_name_format check (
        name = btrim(name)
        and char_length(name) between 2 and 100
    )
);

create table public.workspace_members (
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    role text not null,
    created_at timestamptz not null default now(),
    primary key (workspace_id, user_id),
    constraint workspace_members_role_allowed check (role in ('owner', 'admin', 'member'))
);

create index workspace_members_user_id_idx
    on public.workspace_members (user_id);

create function app_private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function app_private.set_updated_at();

create trigger workspaces_set_updated_at
before update on public.workspaces
for each row execute function app_private.set_updated_at();

create function app_private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_display_name text;
begin
    normalized_display_name := nullif(
        left(
            btrim(
                coalesce(
                    new.raw_user_meta_data ->> 'display_name',
                    new.raw_user_meta_data ->> 'full_name',
                    ''
                )
            ),
            100
        ),
        ''
    );

    insert into public.profiles (user_id, display_name)
    values (new.id, normalized_display_name)
    on conflict (user_id) do nothing;

    return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function app_private.handle_new_auth_user();

create function app_private.is_workspace_member(target_workspace_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.workspace_members as membership
        where membership.workspace_id = target_workspace_id
          and membership.user_id = (select auth.uid())
    );
$$;

create function app_private.is_workspace_owner(target_workspace_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.workspace_members as membership
        where membership.workspace_id = target_workspace_id
          and membership.user_id = (select auth.uid())
          and membership.role = 'owner'
    );
$$;

create function public.create_workspace(workspace_name text)
returns table (
    id uuid,
    name text,
    created_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_user_id uuid := (select auth.uid());
    normalized_name text;
    created_workspace_id uuid;
    workspace_created_at timestamptz;
begin
    if caller_user_id is null then
        raise exception 'Authentication is required to create a workspace'
            using errcode = '28000';
    end if;

    normalized_name := regexp_replace(btrim(coalesce(workspace_name, '')), '\s+', ' ', 'g');

    if char_length(normalized_name) < 2 or char_length(normalized_name) > 100 then
        raise exception 'Workspace name must contain between 2 and 100 characters'
            using errcode = '22023';
    end if;

    insert into public.workspaces (name, created_by)
    values (normalized_name, caller_user_id)
    returning public.workspaces.id, public.workspaces.created_at
    into created_workspace_id, workspace_created_at;

    insert into public.workspace_members (workspace_id, user_id, role)
    values (created_workspace_id, caller_user_id, 'owner');

    id := created_workspace_id;
    name := normalized_name;
    created_at := workspace_created_at;
    return next;
end;
$$;

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;

revoke all on table public.profiles from public, anon, authenticated;
revoke all on table public.workspaces from public, anon, authenticated;
revoke all on table public.workspace_members from public, anon, authenticated;

grant select on table public.profiles to authenticated;
grant update (display_name) on table public.profiles to authenticated;

grant select on table public.workspaces to authenticated;
grant update (name) on table public.workspaces to authenticated;
grant delete on table public.workspaces to authenticated;

grant select on table public.workspace_members to authenticated;

create policy profiles_select_own
on public.profiles
for select
to authenticated
using ((select auth.uid()) = user_id);

create policy profiles_update_own
on public.profiles
for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy workspaces_select_for_members
on public.workspaces
for select
to authenticated
using ((select app_private.is_workspace_member(id)));

create policy workspaces_update_for_owners
on public.workspaces
for update
to authenticated
using ((select app_private.is_workspace_owner(id)))
with check ((select app_private.is_workspace_owner(id)));

create policy workspaces_delete_for_owners
on public.workspaces
for delete
to authenticated
using ((select app_private.is_workspace_owner(id)));

create policy workspace_members_select_own
on public.workspace_members
for select
to authenticated
using ((select auth.uid()) = user_id);

revoke all on function app_private.set_updated_at() from public, anon, authenticated;
revoke all on function app_private.handle_new_auth_user() from public, anon, authenticated;
revoke all on function app_private.is_workspace_member(uuid) from public, anon, authenticated;
revoke all on function app_private.is_workspace_owner(uuid) from public, anon, authenticated;
revoke all on function public.create_workspace(text) from public, anon, authenticated;

grant execute on function app_private.is_workspace_member(uuid) to authenticated;
grant execute on function app_private.is_workspace_owner(uuid) to authenticated;
grant execute on function public.create_workspace(text) to authenticated;
