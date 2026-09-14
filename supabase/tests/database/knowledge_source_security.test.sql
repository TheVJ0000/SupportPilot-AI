begin;

select plan(25);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('11000000-0000-0000-0000-000000000001', 'owner@example.test', '{}'),
    ('22000000-0000-0000-0000-000000000002', 'admin@example.test', '{}'),
    ('33000000-0000-0000-0000-000000000003', 'member@example.test', '{}'),
    ('44000000-0000-0000-0000-000000000004', 'outsider@example.test', '{}');

create temporary table knowledge_test_context (
    key text primary key,
    workspace_id uuid,
    source_id uuid,
    storage_path text
);
grant select, insert, update on table knowledge_test_context to authenticated;

select is(
    (select public from storage.buckets where id = 'knowledge-files'),
    false,
    'The knowledge-files bucket is private'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_sources', 'INSERT'),
    'Authenticated callers cannot directly insert a spoofed created_by value'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_sources', 'UPDATE'),
    'Authenticated callers cannot directly choose or alter source status'
);

set local role authenticated;
set local request.jwt.claim.sub = '11000000-0000-0000-0000-000000000001';

insert into knowledge_test_context (key, workspace_id)
select 'workspace', id from public.create_workspace('Knowledge Security Test');

select lives_ok(
    $$
        select public.create_faq_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Refund policy',
            'When are refunds available?',
            'Refunds are available within the documented eligibility window.'
        )
    $$,
    'An owner can create an FAQ source'
);

select is(
    (
        select count(id)::integer
        from public.knowledge_sources
        where workspace_id = (
            select workspace_id from knowledge_test_context where key = 'workspace'
        )
          and created_by = '11000000-0000-0000-0000-000000000001'
          and source_type = 'faq'
          and status = 'pending'
    ),
    1,
    'FAQ creation derives created_by and pending status from trusted database logic'
);

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values
    (
        (select workspace_id from knowledge_test_context where key = 'workspace'),
        '22000000-0000-0000-0000-000000000002',
        'admin'
    ),
    (
        (select workspace_id from knowledge_test_context where key = 'workspace'),
        '33000000-0000-0000-0000-000000000003',
        'member'
    );

set local role authenticated;
set local request.jwt.claim.sub = '22000000-0000-0000-0000-000000000002';

select lives_ok(
    $$
        select public.create_faq_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Shipping times',
            'How long does shipping take?',
            'Standard synthetic-demo shipping takes three to five business days.'
        )
    $$,
    'An admin can manage knowledge by creating an FAQ source'
);

set local request.jwt.claim.sub = '33000000-0000-0000-0000-000000000003';

select is(
    (
        select count(id)::integer
        from public.knowledge_sources
        where workspace_id = (
            select workspace_id from knowledge_test_context where key = 'workspace'
        )
    ),
    2,
    'An ordinary member can read permitted knowledge-source metadata'
);

set local request.jwt.claim.sub = '44000000-0000-0000-0000-000000000004';

select is(
    (select count(id)::integer from public.knowledge_sources),
    0,
    'A non-member cannot read knowledge-source metadata'
);

set local request.jwt.claim.sub = '33000000-0000-0000-0000-000000000003';

select throws_ok(
    $$
        select public.create_faq_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Unauthorized FAQ',
            'Can a member create this FAQ?',
            'No.'
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'An ordinary member cannot create an FAQ source'
);

select throws_ok(
    $$
        select * from public.begin_file_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Unauthorized file',
            'member.pdf',
            'application/pdf',
            512
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'An ordinary member cannot initialize a file source'
);

set local request.jwt.claim.sub = '11000000-0000-0000-0000-000000000001';

select throws_ok(
    $$
        select * from public.begin_file_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Unsupported file',
            'payload.exe',
            'application/octet-stream',
            512
        )
    $$,
    '22023',
    'File extension is not supported',
    'Unsupported file metadata is rejected'
);

select throws_ok(
    $$
        select * from public.begin_file_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Oversized file',
            'large.pdf',
            'application/pdf',
            10485761
        )
    $$,
    '22023',
    'File size must be between 1 byte and 10 MB',
    'Files larger than 10 MB are rejected by trusted database logic'
);

insert into knowledge_test_context (key, workspace_id, source_id, storage_path)
select
    'owner-file',
    (select workspace_id from knowledge_test_context where key = 'workspace'),
    source_id,
    storage_path
from public.begin_file_knowledge_source(
    (select workspace_id from knowledge_test_context where key = 'workspace'),
    'Support guide',
    'guide.pdf',
    'application/pdf',
    1024
);

select ok(
    exists (
        select 1
        from public.knowledge_sources
        where id = (select source_id from knowledge_test_context where key = 'owner-file')
          and created_by = '11000000-0000-0000-0000-000000000001'
          and status = 'uploading'
          and storage_path = (
              workspace_id::text || '/' || id::text || '/' || id::text || '.pdf'
          )
    ),
    'File initialization derives creator, uploading status, source UUID, and trusted path'
);

select ok(
    not app_private.can_upload_knowledge_object('../malformed/path.pdf'),
    'Malformed Storage paths fail closed'
);

set local request.jwt.claim.sub = '33000000-0000-0000-0000-000000000003';

select throws_like(
    $$
        insert into storage.objects (bucket_id, name)
        select 'knowledge-files', storage_path
        from knowledge_test_context
        where key = 'owner-file'
    $$,
    '%row-level security policy%',
    'An ordinary member cannot upload into a manager source path'
);

set local request.jwt.claim.sub = '11000000-0000-0000-0000-000000000001';

select lives_ok(
    $$
        insert into storage.objects (bucket_id, name)
        select 'knowledge-files', storage_path
        from knowledge_test_context
        where key = 'owner-file'
    $$,
    'An owner can upload only to the trusted source path'
);

select lives_ok(
    $$
        select public.finalize_file_knowledge_source(
            (select source_id from knowledge_test_context where key = 'owner-file')
        )
    $$,
    'An owner can finalize an uploaded file source'
);

select is(
    (
        select status
        from public.knowledge_sources
        where id = (select source_id from knowledge_test_context where key = 'owner-file')
    ),
    'pending',
    'Finalization transitions uploading to pending and never to ready'
);

set local request.jwt.claim.sub = '44000000-0000-0000-0000-000000000004';

select is(
    (
        select count(id)::integer
        from storage.objects
        where bucket_id = 'knowledge-files'
    ),
    0,
    'A non-member cannot access another workspace Storage namespace'
);

set local request.jwt.claim.sub = '33000000-0000-0000-0000-000000000003';

select is(
    (
        select count(id)::integer
        from storage.objects
        where bucket_id = 'knowledge-files'
    ),
    1,
    'An ordinary member can read a workspace knowledge object'
);

select is(
    (
        with deleted as (
            delete from storage.objects
            where bucket_id = 'knowledge-files'
            returning id
        )
        select count(*)::integer from deleted
    ),
    0,
    'An ordinary member cannot delete a knowledge object'
);

set local request.jwt.claim.sub = '22000000-0000-0000-0000-000000000002';

select lives_ok(
    $$
        insert into knowledge_test_context (key, workspace_id, source_id, storage_path)
        select
            'admin-file',
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            source_id,
            storage_path
        from public.begin_file_knowledge_source(
            (select workspace_id from knowledge_test_context where key = 'workspace'),
            'Admin notes',
            'notes.md',
            'text/markdown',
            256
        )
    $$,
    'An admin can initialize a file source'
);

select lives_ok(
    $$
        insert into storage.objects (bucket_id, name)
        select 'knowledge-files', storage_path
        from knowledge_test_context
        where key = 'admin-file'
    $$,
    'An admin can upload to an initialized trusted source path'
);

select ok(
    not has_function_privilege(
        'anon',
        'public.begin_file_knowledge_source(uuid,text,text,text,bigint)',
        'EXECUTE'
    ),
    'Unauthenticated callers cannot initialize knowledge source uploads'
);

select ok(
    not has_function_privilege(
        'anon',
        'public.create_faq_knowledge_source(uuid,text,text,text)',
        'EXECUTE'
    ),
    'Unauthenticated callers cannot create FAQ sources'
);

select * from finish();
rollback;
