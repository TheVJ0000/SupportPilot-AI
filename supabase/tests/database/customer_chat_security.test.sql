begin;

select plan(48);

insert into auth.users (id, email, raw_user_meta_data)
values
    ('91000000-0000-0000-0000-000000000001', 'chat-owner@example.test', '{}'),
    ('92000000-0000-0000-0000-000000000002', 'chat-outsider@example.test', '{}');

create temporary table customer_chat_test_context (
    key text primary key,
    value uuid not null
);
grant select, insert, update on table customer_chat_test_context
    to authenticated, service_role;

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

set local role authenticated;
set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
insert into customer_chat_test_context (key, value)
select 'primary_workspace', id from public.create_workspace('Customer Chat Workspace');

set local request.jwt.claim.sub = '92000000-0000-0000-0000-000000000002';
insert into customer_chat_test_context (key, value)
select 'other_workspace', id from public.create_workspace('Other Chat Workspace');

reset role;

select is(
    (select count(*)::integer from public.workspace_chat_configs),
    2,
    'A chat configuration is automatically created for every workspace'
);

select is(
    (select count(distinct public_id)::integer from public.workspace_chat_configs),
    2,
    'Every workspace receives a distinct public chat identifier'
);

select ok(
    not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'customer_sessions'
          and column_name in ('token', 'session_token', 'raw_token')
    ),
    'The customer session table has no raw-token column'
);

select ok(
    position('[0-9a-f]{64}' in pg_get_constraintdef(
        (select oid from pg_constraint
         where conname = 'customer_sessions_token_hash_format')
    )) > 0,
    'The database validates lowercase 64-character SHA-256 token hashes'
);

select ok(
    position('7 days' in pg_get_constraintdef(
        (select oid from pg_constraint
         where conname = 'customer_sessions_expiry_bounded')
    )) > 0,
    'The database enforces the maximum seven-day session lifetime'
);

select ok(
    not has_table_privilege('anon', 'public.customer_sessions', 'INSERT'),
    'Anonymous browser callers cannot directly create customer sessions'
);

select ok(
    not has_table_privilege('authenticated', 'public.conversation_turns', 'INSERT')
    and not has_table_privilege('authenticated', 'public.messages', 'INSERT'),
    'Authenticated browser callers cannot directly insert turns or messages'
);

select ok(
    position('(customer_session_id, workspace_id)' in pg_get_constraintdef(
        (select oid from pg_constraint
         where conname = 'conversations_session_workspace_fk')
    )) > 0,
    'Conversation foreign keys enforce matching session and workspace ownership'
);

select unalike(
    pg_get_function_arguments(
        'public.search_customer_chat_knowledge(uuid,text,jsonb,text,text,integer,integer)'::regprocedure
    ),
    '%workspace%',
    'Customer retrieval accepts no caller-supplied workspace identifier'
);

set local role authenticated;
set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
select is(
    (select count(*)::integer from public.workspace_chat_configs),
    1,
    'A member can read only their workspace chat configuration'
);

set local request.jwt.claim.sub = '92000000-0000-0000-0000-000000000002';
select is(
    (select count(*)::integer from public.workspace_chat_configs
     where workspace_id = (
        select value from customer_chat_test_context where key = 'primary_workspace'
     )),
    0,
    'An outsider cannot discover another workspace chat configuration'
);
reset role;

insert into customer_chat_test_context (key, value)
select 'primary_public_id', public_id from public.workspace_chat_configs
where workspace_id = (
    select value from customer_chat_test_context where key = 'primary_workspace'
);
insert into customer_chat_test_context (key, value)
select 'other_public_id', public_id from public.workspace_chat_configs
where workspace_id = (
    select value from customer_chat_test_context where key = 'other_workspace'
);

select ok(
    not has_table_privilege('anon', 'public.customer_sessions', 'SELECT'),
    'Anonymous callers have no direct customer-session read access'
);

select ok(
    not has_table_privilege('authenticated', 'public.customer_sessions', 'SELECT'),
    'Authenticated browser callers cannot read customer token hashes'
);

select ok(
    not has_table_privilege('service_role', 'public.messages', 'SELECT')
    and not has_table_privilege('service_role', 'public.messages', 'INSERT'),
    'The service role has no generic direct message-table access'
);

select ok(
    not has_function_privilege('anon', 'public.create_customer_chat_session(uuid,text,timestamptz)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.begin_customer_chat_turn(uuid,text,uuid,text)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.search_customer_chat_knowledge(uuid,text,jsonb,text,text,integer,integer)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.complete_customer_chat_turn(uuid,text,text,text,jsonb)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.fail_customer_chat_turn(uuid,text,text)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.get_customer_chat_turn_result(uuid,text,uuid)', 'EXECUTE')
    and not has_function_privilege('anon', 'public.get_customer_conversation(uuid,text)', 'EXECUTE'),
    'Anonymous callers cannot execute any customer-chat RPC directly'
);

select ok(
    not has_function_privilege('authenticated', 'public.create_customer_chat_session(uuid,text,timestamptz)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.begin_customer_chat_turn(uuid,text,uuid,text)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.search_customer_chat_knowledge(uuid,text,jsonb,text,text,integer,integer)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.complete_customer_chat_turn(uuid,text,text,text,jsonb)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.fail_customer_chat_turn(uuid,text,text)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.get_customer_chat_turn_result(uuid,text,uuid)', 'EXECUTE')
    and not has_function_privilege('authenticated', 'public.get_customer_conversation(uuid,text)', 'EXECUTE'),
    'Authenticated callers cannot execute any customer-chat RPC directly'
);

select ok(
    has_function_privilege('service_role', 'public.create_customer_chat_session(uuid,text,timestamptz)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.begin_customer_chat_turn(uuid,text,uuid,text)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.search_customer_chat_knowledge(uuid,text,jsonb,text,text,integer,integer)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.complete_customer_chat_turn(uuid,text,text,text,jsonb)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.fail_customer_chat_turn(uuid,text,text)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.get_customer_chat_turn_result(uuid,text,uuid)', 'EXECUTE')
    and has_function_privilege('service_role', 'public.get_customer_conversation(uuid,text)', 'EXECUTE'),
    'Only the service role receives the complete narrow customer-chat RPC surface'
);

select ok(
    has_function_privilege(
        'authenticated',
        'public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer)',
        'EXECUTE'
    ),
    'The existing authenticated business retrieval RPC remains available'
);

select ok(
    not has_function_privilege(
        'anon',
        'public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer)',
        'EXECUTE'
    ),
    'The existing business retrieval RPC remains unavailable to anonymous callers'
);

set local role service_role;
select throws_ok(
    $$ select * from public.create_customer_chat_session(
        '99999999-0000-4000-8000-000000000001', repeat('a', 64), now() + interval '7 days'
    ) $$,
    '22023', 'Customer chat is unavailable',
    'An unknown public chat identifier cannot create a session'
);

with created as (
    select * from public.create_customer_chat_session(
        (select value from customer_chat_test_context where key = 'primary_public_id'),
        repeat('a', 64),
        now() + interval '7 days'
    )
)
insert into customer_chat_test_context (key, value)
select 'primary_session', customer_session_id from created
union all
select 'primary_conversation', conversation_id from created;
reset role;

select is(
    (select token_hash from public.customer_sessions where id = (
        select value from customer_chat_test_context where key = 'primary_session'
    )),
    repeat('a', 64),
    'Session creation persists only the supplied SHA-256 hash'
);

select ok(
    (select expires_at <= created_at + interval '7 days'
       and expires_at > created_at
     from public.customer_sessions where id = (
        select value from customer_chat_test_context where key = 'primary_session'
     )),
    'Session expiry is future-dated and bounded to seven days'
);

set local role service_role;
select throws_ok(
    $$ select * from public.begin_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('b', 64),
        '93000000-0000-4000-8000-000000000001',
        'How do I reset my password?'
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'A wrong opaque session credential cannot start a turn'
);

with created as (
    select * from public.create_customer_chat_session(
        (select value from customer_chat_test_context where key = 'other_public_id'),
        repeat('b', 64),
        now() + interval '7 days'
    )
)
insert into customer_chat_test_context (key, value)
select 'other_session', customer_session_id from created
union all
select 'other_conversation', conversation_id from created;

select throws_ok(
    $$ select * from public.begin_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('b', 64),
        '93000000-0000-4000-8000-000000000002',
        'Cross-tenant attempt'
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'A valid token from another workspace cannot cross tenant boundaries'
);

insert into customer_chat_test_context (key, value)
select 'primary_turn', turn_id
from public.begin_customer_chat_turn(
    (select value from customer_chat_test_context where key = 'primary_conversation'),
    repeat('a', 64),
    '93000000-0000-4000-8000-000000000003',
    '  How   do I reset my password?  '
);

select is(
    (select turn_status from public.begin_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        '93000000-0000-4000-8000-000000000003',
        'How do I reset my password?'
    )),
    'processing',
    'A same-content idempotent retry returns the existing processing turn'
);

reset role;
select is(
    (select count(*)::integer from public.messages where conversation_id = (
        select value from customer_chat_test_context where key = 'primary_conversation'
    ) and role = 'customer'),
    1,
    'An idempotent retry does not duplicate the customer message'
);

insert into public.knowledge_sources (
    id, workspace_id, created_by, source_type, title, status, faq_question, faq_answer,
    extracted_at, extracted_char_count, chunk_count, indexed_at,
    embedding_provider, embedding_model, embedding_dimension,
    last_failure_stage, processing_stage, processing_started_at
)
values
    ('94000000-0000-4000-8000-000000000001',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     '91000000-0000-0000-0000-000000000001', 'faq', 'Password Help', 'ready',
     'How do I reset my password?', 'Use the account reset form.', now(), 27, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('94000000-0000-4000-8000-000000000002',
     (select value from customer_chat_test_context where key = 'other_workspace'),
     '92000000-0000-0000-0000-000000000002', 'faq', 'Private Other Tenant', 'ready',
     'Private question?', 'Private answer.', now(), 15, 1, now(),
     'gemini', 'gemini-embedding-2', 768, null, null, null),
    ('94000000-0000-4000-8000-000000000003',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     '91000000-0000-0000-0000-000000000001', 'faq', 'Pending Excluded', 'pending',
     'Pending question?', 'Pending answer.', now(), 16, 1, null,
     null, null, null, null, null, null),
    ('94000000-0000-4000-8000-000000000004',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     '91000000-0000-0000-0000-000000000001', 'faq', 'Wrong Model Excluded', 'ready',
     'Wrong model question?', 'Wrong model answer.', now(), 20, 1, now(),
     'gemini', 'other-model', 768, null, null, null);

insert into public.knowledge_chunks (
    id, source_id, workspace_id, chunk_index, content, content_sha256,
    char_count, locator, embedding
)
values
    ('95000000-0000-4000-8000-000000000001',
     '94000000-0000-4000-8000-000000000001',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     0, 'Use the account reset form.', repeat('c', 64), char_length('Use the account reset form.'),
     '{"kind":"faq"}'::jsonb, pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('95000000-0000-4000-8000-000000000002',
     '94000000-0000-4000-8000-000000000002',
     (select value from customer_chat_test_context where key = 'other_workspace'),
     0, 'Other tenant secret answer.', repeat('d', 64), 27,
     '{"kind":"faq"}'::jsonb, pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('95000000-0000-4000-8000-000000000003',
     '94000000-0000-4000-8000-000000000003',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     0, 'Pending content.', repeat('e', 64), 16,
     '{"kind":"faq"}'::jsonb, pg_temp.vector_json(1, 0)::text::extensions.vector),
    ('95000000-0000-4000-8000-000000000004',
     '94000000-0000-4000-8000-000000000004',
     (select value from customer_chat_test_context where key = 'primary_workspace'),
     0, 'Wrong model content.', repeat('f', 64), 20,
     '{"kind":"faq"}'::jsonb, pg_temp.vector_json(1, 0)::text::extensions.vector);

set local role service_role;
select results_eq(
    $$ select source_id from public.search_customer_chat_knowledge(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64), pg_temp.vector_json(1, 0),
        'gemini', 'gemini-embedding-2', 768, 8
    ) $$,
    $$ values ('94000000-0000-4000-8000-000000000001'::uuid) $$,
    'Customer retrieval derives workspace and returns only compatible ready knowledge'
);

select unalike(
    pg_get_function_result(
        'public.search_customer_chat_knowledge(uuid,text,jsonb,text,text,integer,integer)'::regprocedure
    ),
    '%embedding%',
    'Customer retrieval never returns raw vectors'
);

select throws_ok(
    $$ select public.complete_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_turn'),
        repeat('a', 64), 'answered', 'Too many citations.',
        (select jsonb_agg(jsonb_build_object(
            'source_id', '94000000-0000-4000-8000-000000000001',
            'source_title', 'Password Help',
            'source_type', 'faq',
            'chunk_index', 0,
            'locator', jsonb_build_object('kind', 'faq')
        )) from generate_series(1, 9))
    ) $$,
    '22023', 'Citation count does not match answer status',
    'Completion enforces at most eight citation snapshots'
);

select throws_ok(
    $$ select public.complete_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_turn'),
        repeat('a', 64), 'answered', 'Unsafe answer.',
        '[{"source_id":"94000000-0000-4000-8000-000000000002","source_title":"Private Other Tenant","source_type":"faq","chunk_index":0,"locator":{"kind":"faq"}}]'::jsonb
    ) $$,
    '22023', 'Citation does not match trusted workspace knowledge',
    'Completion rejects a citation from another workspace atomically'
);

reset role;
select is(
    (select count(*)::integer from public.messages where turn_id = (
        select value from customer_chat_test_context where key = 'primary_turn'
    ) and role = 'assistant'),
    0,
    'Rejected completion leaves no half-written assistant message'
);

set local role service_role;
select ok(
    public.complete_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_turn'),
        repeat('a', 64), 'answered', 'Use the account reset form.',
        '[{"source_id":"94000000-0000-4000-8000-000000000001","source_title":"Password Help","source_type":"faq","chunk_index":0,"locator":{"kind":"faq"}}]'::jsonb
    ),
    'A processing turn can atomically persist a grounded answer'
);
reset role;

select is(
    (select count(*)::integer from public.message_citations where workspace_id = (
        select value from customer_chat_test_context where key = 'primary_workspace'
    )),
    1,
    'Completion persists the exact trusted citation snapshot'
);

set local role service_role;
select throws_ok(
    $$ select public.complete_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_turn'),
        repeat('a', 64), 'answered', 'Duplicate answer.',
        '[{"source_id":"94000000-0000-4000-8000-000000000001","source_title":"Password Help","source_type":"faq","chunk_index":0,"locator":{"kind":"faq"}}]'::jsonb
    ) $$,
    '55000', 'Only a processing turn can be completed',
    'A completed turn cannot create a duplicate assistant message'
);

select is(
    (public.get_customer_chat_turn_result(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64), '93000000-0000-4000-8000-000000000003'
    ) ->> 'answer_status'),
    'answered',
    'A completed idempotent turn result can be safely replayed'
);

select is(
    jsonb_array_length(public.get_customer_conversation(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    ) -> 'messages'),
    2,
    'Conversation history returns the ordered customer and assistant messages'
);

select is(
    (public.get_customer_conversation(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    ) -> 'messages' -> 0 ->> 'role'),
    'customer',
    'Conversation history keeps the customer message before its assistant answer'
);
reset role;

set local role authenticated;
set local request.jwt.claim.sub = '92000000-0000-0000-0000-000000000002';
select is(
    (select count(*)::integer from public.conversations where id = (
        select value from customer_chat_test_context where key = 'primary_conversation'
    )),
    0,
    'An authenticated outsider cannot read another workspace conversation'
);

set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
select is(
    (select count(*)::integer from public.messages where conversation_id = (
        select value from customer_chat_test_context where key = 'primary_conversation'
    )),
    2,
    'A workspace owner can read their persisted conversation messages'
);
reset role;

update public.workspace_chat_configs
set is_enabled = false
where workspace_id = (select value from customer_chat_test_context where key = 'primary_workspace');
set local role service_role;
select throws_ok(
    $$ select public.get_customer_conversation(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    ) $$,
    '42501', 'Customer chat is disabled',
    'A disabled hosted chat rejects customer history access'
);
reset role;
update public.workspace_chat_configs
set is_enabled = true
where workspace_id = (select value from customer_chat_test_context where key = 'primary_workspace');

update public.customer_sessions
set created_at = now() - interval '2 days',
    last_seen_at = now() - interval '2 days',
    expires_at = now() - interval '1 day'
where id = (select value from customer_chat_test_context where key = 'other_session');
set local role service_role;
select throws_ok(
    $$ select public.get_customer_conversation(
        (select value from customer_chat_test_context where key = 'other_conversation'),
        repeat('b', 64)
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'An expired customer session cannot restore history'
);
reset role;

update public.conversation_turns
set created_at = now() - interval '2 seconds', updated_at = now() - interval '2 seconds'
where id = (select value from customer_chat_test_context where key = 'primary_turn');

set local role service_role;
insert into customer_chat_test_context (key, value)
select 'retry_turn', turn_id
from public.begin_customer_chat_turn(
    (select value from customer_chat_test_context where key = 'primary_conversation'),
    repeat('a', 64),
    '93000000-0000-4000-8000-000000000004',
    'I still need help.'
);

select throws_ok(
    $$ select * from public.begin_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        '93000000-0000-4000-8000-000000000005',
        'An accidental immediate duplicate.'
    ) $$,
    '55000', 'A customer turn was created too recently',
    'A recent processing turn prevents an immediate second new turn'
);

select throws_ok(
    $$ select public.fail_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'retry_turn'),
        repeat('a', 64), 'Gemini said private provider details'
    ) $$,
    '22023', 'Customer turn error code is invalid',
    'Provider exception text cannot be persisted as a failure code'
);

select ok(
    public.fail_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'retry_turn'),
        repeat('a', 64), 'generation_failed'
    ),
    'An allow-listed safe failure code marks the turn failed'
);

select is(
    (select turn_status from public.begin_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        '93000000-0000-4000-8000-000000000004',
        'I still need help.'
    )),
    'processing',
    'A failed turn can retry with the same client message ID'
);

select ok(
    public.complete_customer_chat_turn(
        (select value from customer_chat_test_context where key = 'retry_turn'),
        repeat('a', 64), 'insufficient_evidence',
        'I do not have enough verified information to answer that from the available support knowledge.',
        '[]'::jsonb
    ),
    'An insufficient-evidence answer completes atomically with zero citations'
);
reset role;

select is(
    (select count(*)::integer from public.messages where turn_id = (
        select value from customer_chat_test_context where key = 'retry_turn'
    ) and role = 'customer'),
    1,
    'Retrying a failed turn preserves one customer message without duplication'
);

select is(
    (select count(*)::integer
     from public.message_citations as citation
     join public.messages as message on message.id = citation.message_id
     where message.turn_id = (
        select value from customer_chat_test_context where key = 'retry_turn'
     )),
    0,
    'The persisted insufficient-evidence assistant message has no citations'
);

select * from finish();
rollback;
