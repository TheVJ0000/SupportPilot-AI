begin;

select plan(28);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('81000000-0000-0000-0000-000000000001', 'retrieval-owner@example.test', '{}'),
    ('82000000-0000-0000-0000-000000000002', 'retrieval-member@example.test', '{}'),
    ('83000000-0000-0000-0000-000000000003', 'retrieval-outsider@example.test', '{}');

create temporary table retrieval_test_context (
    key text primary key,
    workspace_id uuid
);
grant select, insert on table retrieval_test_context to authenticated;

create function pg_temp.vector_json(first_value numeric, second_value numeric)
returns jsonb
language sql
immutable
as $$
    select jsonb_agg(
        case position
            when 1 then first_value
            when 2 then second_value
            else 0
        end
        order by position
    )
    from generate_series(1, 768) as series(position);
$$;

select ok(
    not has_function_privilege(
        'anon', 'public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer)',
        'EXECUTE'
    ),
    'Anonymous callers cannot execute semantic retrieval'
);

select ok(
    has_function_privilege(
        'authenticated',
        'public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer)',
        'EXECUTE'
    ),
    'Authenticated callers can invoke the scoped retrieval function'
);

select ok(
    not has_column_privilege(
        'authenticated', 'public.knowledge_chunks', 'embedding', 'SELECT'
    ),
    'Semantic retrieval does not expose direct embedding-column access'
);

select ok(
    to_regclass('public.knowledge_chunks_embedding_hnsw_idx') is not null,
    'The existing HNSW index remains available'
);

select matches(
    pg_get_indexdef('public.knowledge_chunks_embedding_hnsw_idx'::regclass),
    'USING hnsw.*vector_cosine_ops',
    'The existing HNSW index remains cosine compatible'
);

set local role authenticated;
set local request.jwt.claim.sub = '81000000-0000-0000-0000-000000000001';
insert into retrieval_test_context (key, workspace_id)
select 'primary', id from public.create_workspace('Retrieval Workspace');

set local request.jwt.claim.sub = '83000000-0000-0000-0000-000000000003';
insert into retrieval_test_context (key, workspace_id)
select 'other', id from public.create_workspace('Other Retrieval Workspace');

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values (
    (select workspace_id from retrieval_test_context where key = 'primary'),
    '82000000-0000-0000-0000-000000000002',
    'member'
);

insert into public.knowledge_sources (
    id, workspace_id, created_by, source_type, title, status, faq_question, faq_answer,
    extracted_at, extracted_char_count, chunk_count, indexed_at,
    embedding_provider, embedding_model, embedding_dimension, last_failure_stage,
    processing_stage, processing_started_at
)
values
    ('84000000-0000-0000-0000-000000000001',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Best match', 'ready',
     'Where is the reset link?', 'Use the account page.', now(), 21, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('84000000-0000-0000-0000-000000000002',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Second match', 'ready',
     'How does recovery work?', 'Use the recovery form.', now(), 22, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('84000000-0000-0000-0000-000000000003',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Pending excluded', 'pending',
     'Pending question?', 'Pending answer.', now(), 15, 1, null,
     null, null, null, null, null, null),
    ('84000000-0000-0000-0000-000000000004',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Failed excluded', 'failed',
     'Failed question?', 'Failed answer.', now(), 14, 1, null,
     null, null, null, 'indexing', null, null),
    ('84000000-0000-0000-0000-000000000005',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Processing excluded', 'processing',
     'Processing question?', 'Processing answer.', now(), 18, 1, null,
     null, null, null, null, 'indexing', now()),
    ('84000000-0000-0000-0000-000000000006',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Null vector excluded', 'ready',
     'Null vector question?', 'Null vector answer.', now(), 19, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('84000000-0000-0000-0000-000000000007',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Model excluded', 'ready',
     'Old model question?', 'Old model answer.', now(), 17, 1, now(),
     'gemini', 'other-embedding-model', 768, null, null, null),
    ('84000000-0000-0000-0000-000000000008',
     (select workspace_id from retrieval_test_context where key = 'other'),
     '83000000-0000-0000-0000-000000000003', 'faq', 'Other tenant excluded', 'ready',
     'Other tenant question?', 'Other tenant answer.', now(), 20, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('84000000-0000-0000-0000-000000000009',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     '81000000-0000-0000-0000-000000000001', 'faq', 'Provider excluded', 'ready',
     'Old provider question?', 'Old provider answer.', now(), 20, 1, now(),
     'other-provider', 'gemini-embedding-2', 768, null, null, null);

insert into public.knowledge_chunks (
    id, source_id, workspace_id, chunk_index, content, content_sha256,
    char_count, locator, embedding
)
values
    ('85000000-0000-0000-0000-000000000001',
     '84000000-0000-0000-0000-000000000001',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Use the synthetic reset link.', repeat('a', 64), 29,
     '{"kind":"faq"}'::jsonb, pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000002',
     '84000000-0000-0000-0000-000000000002',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Use the synthetic recovery form.', repeat('b', 64), 32,
     '{"kind":"pdf","page_start":4,"page_end":5}'::jsonb,
     pg_temp.vector_json(0.8, 0.6)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000003',
     '84000000-0000-0000-0000-000000000003',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Pending content.', repeat('c', 64), 16, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000004',
     '84000000-0000-0000-0000-000000000004',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Failed content.', repeat('d', 64), 15, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000005',
     '84000000-0000-0000-0000-000000000005',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Processing content.', repeat('e', 64), 19, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000006',
     '84000000-0000-0000-0000-000000000006',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Null embedding content.', repeat('f', 64), 23, '{"kind":"faq"}'::jsonb, null),
    ('85000000-0000-0000-0000-000000000007',
     '84000000-0000-0000-0000-000000000007',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Old model content.', repeat('1', 64), 18, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000008',
     '84000000-0000-0000-0000-000000000008',
     (select workspace_id from retrieval_test_context where key = 'other'),
     0, 'Other tenant content.', repeat('2', 64), 21, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('85000000-0000-0000-0000-000000000009',
     '84000000-0000-0000-0000-000000000009',
     (select workspace_id from retrieval_test_context where key = 'primary'),
     0, 'Old provider content.', repeat('3', 64), 21, '{"kind":"faq"}'::jsonb,
     pg_temp.vector_json(1, 0)::text::extensions.vector);

set local role authenticated;
set local request.jwt.claim.sub = '83000000-0000-0000-0000-000000000003';
select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    '42501', 'Workspace membership is required for knowledge retrieval',
    'A non-member cannot retrieve another workspace'
);

set local request.jwt.claim.sub = '82000000-0000-0000-0000-000000000002';
select lives_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    'A workspace member can retrieve compatible knowledge'
);

select results_eq(
    $$ select count(*)::integer from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    $$ values (2) $$,
    'Only compatible ready non-null chunks participate'
);

select results_eq(
    $$ select source_id from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    $$ values
        ('84000000-0000-0000-0000-000000000001'::uuid),
        ('84000000-0000-0000-0000-000000000002'::uuid)
    $$,
    'Results are ordered by best cosine match first'
);

select results_eq(
    $$ select round(similarity::numeric, 2) from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    $$ values (1.00::numeric), (0.80::numeric) $$,
    'Similarity is one minus cosine distance'
);

select results_eq(
    $$ select locator from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
    ) where source_id = '84000000-0000-0000-0000-000000000002' $$,
    $$ values ('{"kind":"pdf","page_start":4,"page_end":5}'::jsonb) $$,
    'Citation locators are returned unchanged'
);

select unlike(
    pg_get_function_result(
        'public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer)'::regprocedure
    ),
    '%embedding%',
    'The retrieval result signature exposes no raw embeddings'
);

select results_eq(
    $$ select source_id from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 1
    ) $$,
    $$ values ('84000000-0000-0000-0000-000000000001'::uuid) $$,
    'A bounded top-one request returns only the best result'
);

select lives_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 12
    ) $$,
    'The maximum allowed result count is twelve'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 0
    ) $$,
    '22023', 'Match count must be between 1 and 12',
    'Match count cannot be below one'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 13
    ) $$,
    '22023', 'Match count must be between 1 and 12',
    'Match count cannot exceed twelve'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        '{}'::jsonb, 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    '22023', 'Query embedding must contain exactly 768 numeric values',
    'A non-array query embedding is rejected'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        '[1,2]'::jsonb, 'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    '22023', 'Query embedding must contain exactly 768 numeric values',
    'A wrong-length query embedding is rejected'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        (pg_temp.vector_json(1, 0) - 0) || '["not-numeric"]'::jsonb,
        'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    '22023', 'Query embedding must contain exactly 768 numeric values',
    'A non-numeric query embedding value is rejected'
);

select throws_ok(
    $$ select * from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 767, 8
    ) $$,
    '22023', 'Embedding compatibility metadata is invalid',
    'An incompatible query dimension is rejected'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id = '84000000-0000-0000-0000-000000000003'
    ),
    'Pending sources are excluded'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id = '84000000-0000-0000-0000-000000000004'
    ),
    'Failed sources are excluded'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id = '84000000-0000-0000-0000-000000000005'
    ),
    'Processing sources are excluded'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id = '84000000-0000-0000-0000-000000000006'
    ),
    'Null embeddings are excluded'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id in (
            '84000000-0000-0000-0000-000000000007',
            '84000000-0000-0000-0000-000000000009'
        )
    ),
    'Sources from an incompatible provider or model space are excluded'
);

select ok(
    not exists (
        select 1 from public.search_knowledge_chunks(
            (select workspace_id from retrieval_test_context where key = 'primary'),
            pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 8
        ) where source_id = '84000000-0000-0000-0000-000000000008'
    ),
    'Tenant filtering occurs inside semantic retrieval'
);

select results_eq(
    $$ select count(*)::integer from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'no-compatible-model', 768, 8
    ) $$,
    $$ values (0) $$,
    'No compatible ready sources returns successful empty evidence'
);

select results_eq(
    $$ select source_type, content, chunk_index from public.search_knowledge_chunks(
        (select workspace_id from retrieval_test_context where key = 'primary'),
        pg_temp.vector_json(1, 0), 'gemini', 'gemini-embedding-2', 768, 1
    ) $$,
    $$ values ('faq'::text, 'Use the synthetic reset link.'::text, 0) $$,
    'Retrieval returns only citation-ready evidence fields'
);

select * from finish();
rollback;
