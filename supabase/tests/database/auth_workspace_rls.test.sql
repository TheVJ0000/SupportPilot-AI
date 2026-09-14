begin;

select plan(9);

insert into auth.users (id, email, raw_user_meta_data)
values
    (
        '10000000-0000-0000-0000-000000000001',
        'user-a@example.test',
        '{"display_name":"User A"}'::jsonb
    ),
    (
        '20000000-0000-0000-0000-000000000002',
        'user-b@example.test',
        '{"display_name":"User B"}'::jsonb
    ),
    (
        '30000000-0000-0000-0000-000000000003',
        'user-c@example.test',
        '{}'::jsonb
    );

create temporary table supportpilot_test_context (
    workspace_id uuid not null
);
grant select, insert on table supportpilot_test_context to authenticated;

set local role authenticated;
set local request.jwt.claim.sub = '10000000-0000-0000-0000-000000000001';

select is(
    (
        select count(*)::integer
        from public.profiles
        where user_id = '10000000-0000-0000-0000-000000000001'
    ),
    1,
    'User A can access User A profile'
);

select is(
    (
        select count(*)::integer
        from public.profiles
        where user_id = '20000000-0000-0000-0000-000000000002'
    ),
    0,
    'User A cannot access User B profile'
);

insert into supportpilot_test_context (workspace_id)
select id from public.create_workspace('  Acme   Support  ');

select is(
    (
        select count(*)::integer
        from public.workspace_members
        where workspace_id = (select workspace_id from supportpilot_test_context)
          and user_id = '10000000-0000-0000-0000-000000000001'
          and role = 'owner'
    ),
    1,
    'create_workspace creates exactly one owner membership for the caller'
);

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values (
    (select workspace_id from supportpilot_test_context),
    '20000000-0000-0000-0000-000000000002',
    'member'
);

set local role authenticated;
set local request.jwt.claim.sub = '20000000-0000-0000-0000-000000000002';

select is(
    (
        select count(*)::integer
        from public.workspaces
        where id = (select workspace_id from supportpilot_test_context)
    ),
    1,
    'A workspace member can read their workspace'
);

set local request.jwt.claim.sub = '30000000-0000-0000-0000-000000000003';

select is(
    (
        select count(*)::integer
        from public.workspaces
        where id = (select workspace_id from supportpilot_test_context)
    ),
    0,
    'A non-member cannot read the workspace'
);

set local request.jwt.claim.sub = '10000000-0000-0000-0000-000000000001';

select results_eq(
    $$
        update public.workspaces
        set name = 'Renamed Workspace'
        where id = (select workspace_id from supportpilot_test_context)
        returning name
    $$,
    $$ values ('Renamed Workspace'::text) $$,
    'The owner can update their workspace'
);

set local request.jwt.claim.sub = '20000000-0000-0000-0000-000000000002';

select is_empty(
    $$
        update public.workspaces
        set name = 'Unauthorized Rename'
        where id = (select workspace_id from supportpilot_test_context)
        returning id
    $$,
    'An ordinary member cannot perform an owner-only update'
);

select ok(
    not has_table_privilege('authenticated', 'public.workspace_members', 'INSERT,UPDATE'),
    'Authenticated users cannot directly insert or manipulate workspace roles'
);

select ok(
    not has_function_privilege('anon', 'public.create_workspace(text)', 'EXECUTE'),
    'Unauthenticated callers cannot execute create_workspace'
);

select * from finish();
rollback;
