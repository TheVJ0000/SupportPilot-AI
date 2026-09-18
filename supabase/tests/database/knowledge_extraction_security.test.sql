begin;

select plan(36);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('61000000-0000-0000-0000-000000000001', 'extraction-owner@example.test', '{}'),
    ('62000000-0000-0000-0000-000000000002', 'extraction-admin@example.test', '{}'),
    ('63000000-0000-0000-0000-000000000003', 'extraction-member@example.test', '{}'),
    ('64000000-0000-0000-0000-000000000004', 'extraction-outsider@example.test', '{}'),
    ('65000000-0000-0000-0000-000000000005', 'other-workspace-owner@example.test', '{}');

create temporary table extraction_test_context (
    key text primary key,
    workspace_id uuid,
    source_id uuid
);
grant select, insert, update on table extraction_test_context to authenticated;

select ok(
    (select relrowsecurity from pg_class where oid = 'public.knowledge_chunks'::regclass),
    'Knowledge chunks have row-level security enabled'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_chunks', 'INSERT'),
    'Authenticated browser callers cannot directly insert chunks'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_chunks', 'UPDATE'),
    'Authenticated browser callers cannot directly update chunks'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_chunks', 'DELETE'),
    'Authenticated browser callers cannot directly delete chunks'
);

select ok(
    not has_function_privilege(
        'anon', 'public.begin_knowledge_extraction(uuid)', 'EXECUTE'
    ),
    'Anonymous callers cannot begin extraction'
);

select ok(
    not has_function_privilege(
        'anon', 'public.complete_knowledge_extraction(uuid,jsonb,integer)', 'EXECUTE'
    ),
    'Anonymous callers cannot complete extraction'
);

select ok(
    not has_function_privilege(
        'anon', 'public.fail_knowledge_extraction(uuid,text)', 'EXECUTE'
    ),
    'Anonymous callers cannot fail extraction'
);

set local role authenticated;
set local request.jwt.claim.sub = '61000000-0000-0000-0000-000000000001';

insert into extraction_test_context (key, workspace_id)
select 'primary-workspace', id from public.create_workspace('Extraction Security Test');

insert into extraction_test_context (key, workspace_id, source_id)
select
    'owner-faq',
    (select workspace_id from extraction_test_context where key = 'primary-workspace'),
    public.create_faq_knowledge_source(
        (select workspace_id from extraction_test_context where key = 'primary-workspace'),
        'Refund policy',
        'How do refunds work?',
        'Use the synthetic returns form within the eligibility window.'
    );

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values
    (
        (select workspace_id from extraction_test_context where key = 'primary-workspace'),
        '62000000-0000-0000-0000-000000000002',
        'admin'
    ),
    (
        (select workspace_id from extraction_test_context where key = 'primary-workspace'),
        '63000000-0000-0000-0000-000000000003',
        'member'
    );

set local role authenticated;
set local request.jwt.claim.sub = '65000000-0000-0000-0000-000000000005';

insert into extraction_test_context (key, workspace_id)
select 'other-workspace', id from public.create_workspace('Other Extraction Workspace');

set local request.jwt.claim.sub = '61000000-0000-0000-0000-000000000001';

select lives_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    'An owner can begin extraction for their workspace source'
);

select results_eq(
    $$
        select status, processing_attempts, processing_started_at is not null
        from public.knowledge_sources
        where id = (select source_id from extraction_test_context where key = 'owner-faq')
    $$,
    $$ values ('processing'::text, 1, true) $$,
    'Beginning extraction records the active lifecycle and first attempt'
);

select throws_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    '55000',
    'Knowledge extraction is already active',
    'A recent processing source cannot start a concurrent extraction'
);

reset role;
update public.knowledge_sources
set processing_started_at = now() - interval '16 minutes'
where id = (select source_id from extraction_test_context where key = 'owner-faq');

set local role authenticated;
set local request.jwt.claim.sub = '61000000-0000-0000-0000-000000000001';

select lives_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    'A conservatively stale processing source can be restarted'
);

select is(
    (
        select processing_attempts
        from public.knowledge_sources
        where id = (select source_id from extraction_test_context where key = 'owner-faq')
    ),
    2,
    'Restarting stale processing increments the attempt count'
);

select throws_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[{"chunk_index":0,"content":"Missing fields"}]'::jsonb,
            14
        )
    $$,
    '22023',
    'Chunk payload contains malformed fields',
    'Malformed chunk payloads are rejected before replacement'
);

select throws_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[{
                "chunk_index":1,
                "content":"Wrong index",
                "content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "char_count":11,
                "locator":{"kind":"faq"}
            }]'::jsonb,
            11
        )
    $$,
    '22023',
    'Chunk indexes must be sequential and begin at zero',
    'Chunk indexes must be sequential from zero'
);

select throws_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            (
                select jsonb_agg(jsonb_build_object(
                    'chunk_index', item,
                    'content', 'x',
                    'content_sha256', repeat('a', 64),
                    'char_count', 1,
                    'locator', jsonb_build_object('kind', 'faq')
                ))
                from generate_series(0, 1000) as item
            ),
            1001
        )
    $$,
    '22023',
    'Chunk payload must contain between 1 and 1000 chunks',
    'Excessive chunk payloads are rejected'
);

select results_eq(
    $$
        select status, chunk_count, extracted_char_count
        from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[
                {
                    "chunk_index":0,
                    "content":"First chunk",
                    "content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "char_count":11,
                    "locator":{"kind":"faq"}
                },
                {
                    "chunk_index":1,
                    "content":"Second chunk",
                    "content_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "char_count":12,
                    "locator":{"kind":"faq"}
                }
            ]'::jsonb,
            25
        )
    $$,
    $$ values ('pending'::text, 2, 25) $$,
    'Valid completion stores chunks and returns pending rather than ready'
);

select results_eq(
    $$
        select count(*)::integer, min(chunk_index), max(chunk_index),
               bool_and(workspace_id = (
                   select workspace_id from extraction_test_context where key = 'primary-workspace'
               ))
        from public.knowledge_chunks
        where source_id = (select source_id from extraction_test_context where key = 'owner-faq')
    $$,
    $$ values (2, 0, 1, true) $$,
    'Stored chunks have sequential indexes and the source-derived workspace'
);

select results_eq(
    $$
        select status, extracted_at is not null, extracted_char_count, chunk_count,
               processing_started_at is null, last_error_code is null
        from public.knowledge_sources
        where id = (select source_id from extraction_test_context where key = 'owner-faq')
    $$,
    $$ values ('pending'::text, true, 25, 2, true, true) $$,
    'Completion records safe extraction metadata and leaves the source pending'
);

select throws_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[]'::jsonb,
            1
        )
    $$,
    '55000',
    'Only a processing source can complete extraction',
    'Completion only works from processing state'
);

set local request.jwt.claim.sub = '63000000-0000-0000-0000-000000000003';

select is(
    (
        select count(*)::integer
        from public.knowledge_chunks
        where source_id = (select source_id from extraction_test_context where key = 'owner-faq')
    ),
    2,
    'A workspace member can read permitted chunk data'
);

select throws_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'An ordinary member cannot begin extraction'
);

set local request.jwt.claim.sub = '64000000-0000-0000-0000-000000000004';

select is(
    (select count(*)::integer from public.knowledge_chunks),
    0,
    'A non-member cannot read another workspace chunk data'
);

select throws_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'A non-member cannot process another workspace source'
);

set local request.jwt.claim.sub = '65000000-0000-0000-0000-000000000005';

select throws_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    '42501',
    'Knowledge management permission is required',
    'A manager cannot target a source in a different workspace'
);

set local request.jwt.claim.sub = '62000000-0000-0000-0000-000000000002';

insert into extraction_test_context (key, workspace_id, source_id)
select
    'admin-faq',
    (select workspace_id from extraction_test_context where key = 'primary-workspace'),
    public.create_faq_knowledge_source(
        (select workspace_id from extraction_test_context where key = 'primary-workspace'),
        'Shipping policy',
        'How quickly does shipping arrive?',
        'Synthetic standard shipping takes three to five business days.'
    );

select lives_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'admin-faq')
        )
    $$,
    'An admin can begin extraction'
);

select throws_ok(
    $$
        select public.fail_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'admin-faq'),
            'raw stack trace / private path'
        )
    $$,
    '22023',
    'Extraction error code is not allowed',
    'Failure rejects raw or unapproved error strings'
);

select lives_ok(
    $$
        select public.fail_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'admin-faq'),
            'malformed_document'
        )
    $$,
    'An approved failure code can be stored from processing state'
);

select results_eq(
    $$
        select status, processing_started_at is null, last_error_code
        from public.knowledge_sources
        where id = (select source_id from extraction_test_context where key = 'admin-faq')
    $$,
    $$ values ('failed'::text, true, 'malformed_document'::text) $$,
    'Failure stores only the safe code and clears active processing'
);

select throws_ok(
    $$
        select public.fail_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'admin-faq'),
            'malformed_document'
        )
    $$,
    '55000',
    'Only active extraction can be failed',
    'Failure only works from processing state'
);

select lives_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'admin-faq')
        )
    $$,
    'A failed source can be retried by an admin'
);

set local request.jwt.claim.sub = '61000000-0000-0000-0000-000000000001';

select lives_ok(
    $$
        select * from public.begin_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq')
        )
    $$,
    'An already-extracted pending source can begin deliberate reprocessing'
);

select throws_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[{
                "chunk_index":1,
                "content":"Invalid replacement",
                "content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "char_count":19,
                "locator":{"kind":"faq"}
            }]'::jsonb,
            19
        )
    $$,
    '22023',
    'Chunk indexes must be sequential and begin at zero',
    'An invalid reprocessing payload rolls back before replacing chunks'
);

select results_eq(
    $$
        select count(*)::integer, min(content), max(content)
        from public.knowledge_chunks
        where source_id = (select source_id from extraction_test_context where key = 'owner-faq')
    $$,
    $$ values (2, 'First chunk'::text, 'Second chunk'::text) $$,
    'Failed reprocessing preserves the entire previous chunk set'
);

select lives_ok(
    $$
        select * from public.complete_knowledge_extraction(
            (select source_id from extraction_test_context where key = 'owner-faq'),
            '[{
                "chunk_index":0,
                "content":"Replacement chunk",
                "content_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "char_count":17,
                "locator":{"kind":"faq"}
            }]'::jsonb,
            17
        )
    $$,
    'Successful reprocessing atomically replaces chunks'
);

select results_eq(
    $$
        select count(*)::integer, min(content)
        from public.knowledge_chunks
        where source_id = (select source_id from extraction_test_context where key = 'owner-faq')
    $$,
    $$ values (1, 'Replacement chunk'::text) $$,
    'Only the complete replacement chunk set remains'
);

reset role;

select throws_like(
    $$
        insert into public.knowledge_chunks (
            source_id, workspace_id, chunk_index, content, content_sha256, char_count, locator
        )
        values (
            (select source_id from extraction_test_context where key = 'owner-faq'),
            (select workspace_id from extraction_test_context where key = 'other-workspace'),
            99,
            'Cross workspace',
            repeat('e', 64),
            15,
            '{"kind":"faq"}'::jsonb
        )
    $$,
    '%knowledge_chunks_source_workspace_fk%',
    'A chunk workspace must match its source workspace'
);

select * from finish();
rollback;
