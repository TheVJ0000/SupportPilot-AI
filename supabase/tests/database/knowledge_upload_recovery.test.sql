begin;

select plan(16);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('51000000-0000-0000-0000-000000000001', 'recovery-owner@example.test', '{}'),
    ('52000000-0000-0000-0000-000000000002', 'recovery-admin@example.test', '{}'),
    ('53000000-0000-0000-0000-000000000003', 'recovery-member@example.test', '{}'),
    ('54000000-0000-0000-0000-000000000004', 'other-owner@example.test', '{}'),
    ('55000000-0000-0000-0000-000000000005', 'recovery-outsider@example.test', '{}');

create temporary table recovery_test_context (
    key text primary key,
    workspace_id uuid,
    source_id uuid,
    storage_path text,
    recorded_updated_at timestamptz
);
grant select, insert, update on table recovery_test_context to authenticated;

select ok(
    has_function_privilege(
        'authenticated',
        'public.recover_file_knowledge_source(uuid)',
        'EXECUTE'
    ),
    'Authenticated callers can invoke the narrowly scoped recovery RPC'
);

select ok(
    not has_function_privilege(
        'anon',
        'public.recover_file_knowledge_source(uuid)',
        'EXECUTE'
    ),
    'Unauthenticated callers cannot invoke upload recovery'
);

set local role authenticated;
set local request.jwt.claim.sub = '51000000-0000-0000-0000-000000000001';

insert into recovery_test_context (key, workspace_id)
select 'primary-workspace', id from public.create_workspace('Recovery Security Test');

insert into recovery_test_context (key, workspace_id, source_id, storage_path)
select
    'owner-object',
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    source_id,
    storage_path
from public.begin_file_knowledge_source(
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    'Recoverable guide',
    'guide.pdf',
    'application/pdf',
    1024
);

insert into storage.objects (bucket_id, name)
select 'knowledge-files', storage_path
from recovery_test_context
where key = 'owner-object';

select results_eq(
    $$
        select recovery_action, source_status
        from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'owner-object')
        )
    $$,
    $$ values ('finalized'::text, 'pending'::text) $$,
    'An owner recovers an exact existing object by transitioning uploading to pending'
);

select is(
    (
        select status
        from public.knowledge_sources
        where id = (select source_id from recovery_test_context where key = 'owner-object')
    ),
    'pending',
    'Recovery never promotes an uploaded source beyond pending'
);

update recovery_test_context
set recorded_updated_at = (
    select updated_at
    from public.knowledge_sources
    where id = recovery_test_context.source_id
)
where key = 'owner-object';

select results_eq(
    $$
        select recovery_action, source_status
        from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'owner-object')
        )
    $$,
    $$ values ('already_pending'::text, 'pending'::text) $$,
    'A lost finalize response can be confirmed idempotently as already pending'
);

select is(
    (
        select source.updated_at
        from public.knowledge_sources as source
        where source.id = (
            select source_id from recovery_test_context where key = 'owner-object'
        )
    ),
    (
        select recorded_updated_at
        from recovery_test_context
        where key = 'owner-object'
    ),
    'Confirming an already-pending source does not mutate it'
);

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values
    (
        (select workspace_id from recovery_test_context where key = 'primary-workspace'),
        '52000000-0000-0000-0000-000000000002',
        'admin'
    ),
    (
        (select workspace_id from recovery_test_context where key = 'primary-workspace'),
        '53000000-0000-0000-0000-000000000003',
        'member'
    );

set local role authenticated;
set local request.jwt.claim.sub = '52000000-0000-0000-0000-000000000002';

insert into recovery_test_context (key, workspace_id, source_id, storage_path)
select
    requested.key,
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    initialized.source_id,
    initialized.storage_path
from (values ('admin-stale'), ('admin-neighbor')) as requested(key)
cross join lateral public.begin_file_knowledge_source(
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    requested.key,
    requested.key || '.txt',
    'text/plain',
    256
) as initialized;

select results_eq(
    $$
        select recovery_action, source_status
        from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'admin-stale')
        )
    $$,
    $$ values ('removed'::text, null::text) $$,
    'An admin removes only an uploading row whose exact object is absent'
);

select results_eq(
    $$
        select
            exists (
                select 1 from public.knowledge_sources
                where id = (
                    select source_id from recovery_test_context where key = 'admin-stale'
                )
            ),
            exists (
                select 1 from public.knowledge_sources
                where id = (
                    select source_id from recovery_test_context where key = 'admin-neighbor'
                )
            )
    $$,
    $$ values (false, true) $$,
    'Absent-object recovery deletes the target stale row and no neighboring row'
);

set local request.jwt.claim.sub = '53000000-0000-0000-0000-000000000003';

select throws_ok(
    $$
        select * from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'admin-neighbor')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'An ordinary member cannot recover an upload'
);

set local request.jwt.claim.sub = '55000000-0000-0000-0000-000000000005';

select throws_ok(
    $$
        select * from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'admin-neighbor')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'A non-member cannot recover another workspace upload'
);

set local request.jwt.claim.sub = '54000000-0000-0000-0000-000000000004';

insert into recovery_test_context (key, workspace_id)
select 'other-workspace', id from public.create_workspace('Other Recovery Workspace');

select throws_ok(
    $$
        select * from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'admin-neighbor')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'A manager of another workspace cannot target this workspace source'
);

set local request.jwt.claim.sub = '51000000-0000-0000-0000-000000000001';

insert into recovery_test_context (key, workspace_id, source_id, storage_path)
select
    'exact-path-only',
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    source_id,
    storage_path
from public.begin_file_knowledge_source(
    (select workspace_id from recovery_test_context where key = 'primary-workspace'),
    'Exact path check',
    'exact.md',
    'text/markdown',
    128
);

reset role;
insert into storage.objects (bucket_id, name)
select 'knowledge-files', storage_path || '.nearby'
from recovery_test_context
where key = 'exact-path-only';

set local role authenticated;
set local request.jwt.claim.sub = '51000000-0000-0000-0000-000000000001';

select results_eq(
    $$
        select recovery_action, source_status
        from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'exact-path-only')
        )
    $$,
    $$ values ('removed'::text, null::text) $$,
    'A similarly named object cannot satisfy the exact trusted path check'
);

select ok(
    exists (
        select 1
        from storage.objects
        where bucket_id = 'knowledge-files'
          and name = (
              select storage_path || '.nearby'
              from recovery_test_context
              where key = 'exact-path-only'
          )
    ),
    'Recovery does not delete or otherwise mutate a different Storage object'
);

reset role;
update public.knowledge_sources
set status = 'failed'
where id = (select source_id from recovery_test_context where key = 'admin-neighbor');

set local role authenticated;
set local request.jwt.claim.sub = '51000000-0000-0000-0000-000000000001';

select throws_ok(
    $$
        select * from public.recover_file_knowledge_source(
            (select source_id from recovery_test_context where key = 'admin-neighbor')
        )
    $$,
    '22023',
    'Only an uploading source can be recovered',
    'A non-uploading source cannot be changed by recovery'
);

select is(
    (
        select status
        from public.knowledge_sources
        where id = (select source_id from recovery_test_context where key = 'admin-neighbor')
    ),
    'failed',
    'A rejected non-uploading source remains unchanged'
);

select throws_ok(
    $$ select * from public.recover_file_knowledge_source(gen_random_uuid()) $$,
    '22023',
    'File knowledge source was not found',
    'Recovery cannot be redirected with caller-provided workspace, path, or status data'
);

select * from finish();
rollback;
