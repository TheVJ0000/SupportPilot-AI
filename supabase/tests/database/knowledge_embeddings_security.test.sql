begin;

select plan(36);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('71000000-0000-0000-0000-000000000001', 'index-owner@example.test', '{}'),
    ('72000000-0000-0000-0000-000000000002', 'index-admin@example.test', '{}'),
    ('73000000-0000-0000-0000-000000000003', 'index-member@example.test', '{}'),
    ('74000000-0000-0000-0000-000000000004', 'index-outsider@example.test', '{}');

create temporary table indexing_test_context (
    key text primary key,
    workspace_id uuid,
    source_id uuid
);
grant select, insert, update on table indexing_test_context to authenticated;

create function pg_temp.embedding_payload(hash_value text, dimensions integer default 768)
returns jsonb
language sql
immutable
as $$
    select jsonb_build_array(jsonb_build_object(
        'chunk_index', 0,
        'content_sha256', hash_value,
        'embedding', (select jsonb_agg(0.125) from generate_series(1, dimensions))
    ));
$$;

select ok(
    exists (select 1 from pg_extension where extname = 'vector'),
    'The vector extension exists'
);

select matches(
    (select pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
     from pg_attribute as attribute
     where attribute.attrelid = 'public.knowledge_chunks'::regclass
       and attribute.attname = 'embedding'),
    '^vector\(768\)$',
    'Knowledge chunk embeddings have exactly 768 dimensions'
);

select ok(
    to_regclass('public.knowledge_chunks_embedding_hnsw_idx') is not null,
    'The knowledge embedding HNSW index exists'
);

select matches(
    pg_get_indexdef('public.knowledge_chunks_embedding_hnsw_idx'::regclass),
    'USING hnsw.*vector_cosine_ops.*WHERE.*embedding IS NOT NULL',
    'The single ANN index uses cosine HNSW for non-null embeddings'
);

select ok(
    not has_table_privilege('authenticated', 'public.knowledge_chunks', 'UPDATE'),
    'Authenticated browser callers cannot directly update embeddings'
);

select ok(
    not has_column_privilege(
        'authenticated', 'public.knowledge_chunks', 'embedding', 'SELECT'
    ),
    'Raw embeddings are not exposed through browser column grants'
);

select ok(
    not has_function_privilege('anon', 'public.begin_knowledge_indexing(uuid)', 'EXECUTE'),
    'Anonymous callers cannot begin indexing'
);

select ok(
    not has_function_privilege(
        'anon', 'public.complete_knowledge_indexing(uuid,text,text,integer,jsonb)', 'EXECUTE'
    ),
    'Anonymous callers cannot complete indexing'
);

select ok(
    not has_function_privilege('anon', 'public.fail_knowledge_indexing(uuid,text)', 'EXECUTE'),
    'Anonymous callers cannot fail indexing'
);

set local role authenticated;
set local request.jwt.claim.sub = '71000000-0000-0000-0000-000000000001';

insert into indexing_test_context (key, workspace_id)
select 'workspace', id from public.create_workspace('Embedding Security Test');

reset role;
insert into public.workspace_members (workspace_id, user_id, role)
values
    ((select workspace_id from indexing_test_context where key = 'workspace'),
     '72000000-0000-0000-0000-000000000002', 'admin'),
    ((select workspace_id from indexing_test_context where key = 'workspace'),
     '73000000-0000-0000-0000-000000000003', 'member');

set local role authenticated;
set local request.jwt.claim.sub = '71000000-0000-0000-0000-000000000001';

insert into indexing_test_context (key, workspace_id, source_id)
select 'owner-source', workspace_id,
       public.create_faq_knowledge_source(
           workspace_id, 'Index owner source', 'What is synthetic support?',
           'Synthetic support is available for this database test.'
       )
from indexing_test_context where key = 'workspace';

select * from public.begin_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'owner-source')
);
select results_eq(
    $$ select status, processing_stage from public.knowledge_sources
       where id = (select source_id from indexing_test_context where key = 'owner-source') $$,
    $$ values ('processing'::text, 'extraction'::text) $$,
    'Beginning extraction records the extraction processing stage'
);
select * from public.complete_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'owner-source'),
    '[{"chunk_index":0,"content":"Synthetic indexed chunk","content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","char_count":23,"locator":{"kind":"faq"}}]'::jsonb,
    23
);
select results_eq(
    $$ select status, processing_stage from public.knowledge_sources
       where id = (select source_id from indexing_test_context where key = 'owner-source') $$,
    $$ values ('pending'::text, null::text) $$,
    'Completing extraction clears the processing stage'
);

select lives_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source')
    ) $$,
    'An owner can begin indexing trusted extracted chunks'
);

select results_eq(
    $$ select status, processing_stage, indexing_attempts
       from public.knowledge_sources
       where id = (select source_id from indexing_test_context where key = 'owner-source') $$,
    $$ values ('processing'::text, 'indexing'::text, 1) $$,
    'Beginning indexing records the explicit stage and attempt'
);

select throws_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source')
    ) $$,
    '55000', 'Knowledge indexing is already active',
    'An active indexing attempt cannot be started twice'
);

set local request.jwt.claim.sub = '73000000-0000-0000-0000-000000000003';
select throws_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source')
    ) $$,
    '42501', 'Knowledge management permission is required',
    'An ordinary member cannot begin indexing'
);

set local request.jwt.claim.sub = '74000000-0000-0000-0000-000000000004';
select throws_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source')
    ) $$,
    '42501', 'Knowledge management permission is required',
    'A non-member cannot index another workspace source'
);

set local request.jwt.claim.sub = '71000000-0000-0000-0000-000000000001';
select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768, '[]'::jsonb
    ) $$,
    '22023', 'Embedding payload must cover every chunk',
    'Completion rejects a payload missing a chunk'
);

select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768,
        pg_temp.embedding_payload(repeat('a', 64)) || pg_temp.embedding_payload(repeat('a', 64))
    ) $$,
    '22023', 'Embedding payload must cover every chunk',
    'Completion rejects an extra vector'
);

select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768,
        '[{"chunk_index":0,"content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]'::jsonb
    ) $$,
    '22023', 'Embedding payload contains malformed fields',
    'Completion rejects a missing vector'
);

select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 767,
        pg_temp.embedding_payload(repeat('a', 64), 767)
    ) $$,
    '22023', 'Embedding metadata is invalid',
    'Completion rejects the wrong embedding dimension'
);

select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768,
        pg_temp.embedding_payload(repeat('b', 64))
    ) $$,
    '55000', 'Knowledge chunk integrity check failed',
    'Completion rejects a stale or incorrect content hash'
);

reset role;
-- Inspect raw vectors only as the test owner, never grant browser access.
select results_eq(
    $$ select count(*)::integer from public.knowledge_chunks
       where source_id = (select source_id from indexing_test_context where key = 'owner-source')
         and embedding is not null $$,
    $$ values (0) $$,
    'Rejected completion attempts commit no partial embeddings'
);

set local role authenticated;
select lives_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768,
        pg_temp.embedding_payload(repeat('a', 64))
    ) $$,
    'A complete valid payload atomically finishes indexing'
);

select results_eq(
    $$ select status, processing_stage, embedding_provider, embedding_model,
              embedding_dimension, indexed_at is not null
       from public.knowledge_sources
       where id = (select source_id from indexing_test_context where key = 'owner-source') $$,
    $$ values ('ready'::text, null::text, 'gemini'::text,
               'gemini-embedding-2'::text, 768, true) $$,
    'Successful completion records ready state and safe embedding metadata'
);

reset role;
select results_eq(
    $$ select vector_dims(embedding) from public.knowledge_chunks
       where source_id = (select source_id from indexing_test_context where key = 'owner-source') $$,
    $$ values (768) $$,
    'The committed chunk vector retains exactly 768 values'
);

set local role authenticated;
select throws_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source')
    ) $$,
    '22023', 'Knowledge source cannot begin indexing in its current state',
    'A ready source cannot be indexed again in this phase'
);

select throws_ok(
    $$ select * from public.complete_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'owner-source'),
        'gemini', 'gemini-embedding-2', 768,
        pg_temp.embedding_payload(repeat('a', 64))
    ) $$,
    '55000', 'Only active indexing can be completed',
    'Completion requires the indexing processing stage'
);

insert into indexing_test_context (key, workspace_id, source_id)
select 'admin-source', workspace_id,
       public.create_faq_knowledge_source(
           workspace_id, 'Index admin source', 'Can an admin index?',
           'Yes, this synthetic source verifies the admin lifecycle.'
       )
from indexing_test_context where key = 'workspace';
select * from public.begin_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'admin-source')
);
select * from public.complete_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'admin-source'),
    '[{"chunk_index":0,"content":"Admin synthetic chunk","content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","char_count":21,"locator":{"kind":"faq"}}]'::jsonb,
    21
);

set local request.jwt.claim.sub = '72000000-0000-0000-0000-000000000002';
select lives_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'admin-source')
    ) $$,
    'A workspace admin can begin indexing'
);

select throws_ok(
    $$ select public.fail_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'admin-source'),
        'raw-provider-message'
    ) $$,
    '22023', 'Indexing error code is not allowed',
    'Indexing failure accepts only approved machine-readable codes'
);

select lives_ok(
    $$ select public.fail_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'admin-source'),
        'embedding_rate_limited'
    ) $$,
    'An approved provider failure safely ends active indexing'
);

select results_eq(
    $$ select status, last_failure_stage, chunk_count,
              (select count(*)::integer from public.knowledge_chunks as chunk
               where chunk.source_id = source.id)
       from public.knowledge_sources as source
       where id = (select source_id from indexing_test_context where key = 'admin-source') $$,
    $$ values ('failed'::text, 'indexing'::text, 1, 1) $$,
    'An indexing failure retains the complete extracted chunk set'
);

select lives_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'admin-source')
    ) $$,
    'An indexing-failed source can retry without re-extraction'
);

select public.fail_knowledge_indexing(
    (select source_id from indexing_test_context where key = 'admin-source'),
    'embedding_failed'
);
select throws_ok(
    $$ select * from public.begin_knowledge_extraction(
        (select source_id from indexing_test_context where key = 'admin-source')
    ) $$,
    '22023', 'An indexing failure must be retried through indexing',
    'An indexing failure cannot accidentally enter extraction'
);

set local request.jwt.claim.sub = '71000000-0000-0000-0000-000000000001';
insert into indexing_test_context (key, workspace_id, source_id)
select 'extraction-failed', workspace_id,
       public.create_faq_knowledge_source(
           workspace_id, 'Failed extraction', 'Will extraction fail?', 'Synthetic answer.'
       )
from indexing_test_context where key = 'workspace';
select * from public.begin_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'extraction-failed')
);
select public.fail_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'extraction-failed'),
    'extraction_failed'
);
select results_eq(
    $$ select status, processing_stage, last_failure_stage
       from public.knowledge_sources
       where id = (select source_id from indexing_test_context where key = 'extraction-failed') $$,
    $$ values ('failed'::text, null::text, 'extraction'::text) $$,
    'Extraction failure records its distinct failure stage'
);
select throws_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'extraction-failed')
    ) $$,
    '22023', 'Knowledge extraction must complete before indexing',
    'An extraction-failed source cannot bypass extraction'
);

insert into indexing_test_context (key, workspace_id, source_id)
select 'stale-source', workspace_id,
       public.create_faq_knowledge_source(
           workspace_id, 'Stale indexing', 'Can stale work recover?', 'Yes, after the timeout.'
       )
from indexing_test_context where key = 'workspace';
select * from public.begin_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'stale-source')
);
select * from public.complete_knowledge_extraction(
    (select source_id from indexing_test_context where key = 'stale-source'),
    '[{"chunk_index":0,"content":"Stale synthetic chunk","content_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","char_count":21,"locator":{"kind":"faq"}}]'::jsonb,
    21
);
select * from public.begin_knowledge_indexing(
    (select source_id from indexing_test_context where key = 'stale-source')
);
reset role;
update public.knowledge_sources
set processing_started_at = now() - interval '16 minutes'
where id = (select source_id from indexing_test_context where key = 'stale-source');
set local role authenticated;
set local request.jwt.claim.sub = '71000000-0000-0000-0000-000000000001';
select lives_ok(
    $$ select * from public.begin_knowledge_indexing(
        (select source_id from indexing_test_context where key = 'stale-source')
    ) $$,
    'A stale indexing attempt can be recovered after the conservative timeout'
);

select * from finish();
rollback;
