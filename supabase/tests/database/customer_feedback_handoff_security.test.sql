begin;

select no_plan();

insert into auth.users (id, email, raw_user_meta_data)
values
    ('81000000-0000-0000-0000-000000000001', 'feedback-owner@example.test', '{}'),
    ('82000000-0000-0000-0000-000000000002', 'feedback-outsider@example.test', '{}');

create temporary table feedback_test_context (
    key text primary key,
    value uuid not null
);
grant select, insert, update on table feedback_test_context to authenticated, service_role;

set local role authenticated;
set local request.jwt.claim.sub = '81000000-0000-0000-0000-000000000001';
insert into feedback_test_context (key, value)
select 'primary_workspace', id from public.create_workspace('Feedback Workspace');

set local request.jwt.claim.sub = '82000000-0000-0000-0000-000000000002';
insert into feedback_test_context (key, value)
select 'other_workspace', id from public.create_workspace('Other Feedback Workspace');
reset role;

insert into feedback_test_context (key, value)
select 'primary_public_id', public_id from public.workspace_chat_configs
where workspace_id = (select value from feedback_test_context where key = 'primary_workspace');
insert into feedback_test_context (key, value)
select 'other_public_id', public_id from public.workspace_chat_configs
where workspace_id = (select value from feedback_test_context where key = 'other_workspace');

set local role service_role;
with created as (
    select * from public.create_customer_chat_session(
        (select value from feedback_test_context where key = 'primary_public_id'),
        repeat('a', 64), now() + interval '7 days'
    )
)
insert into feedback_test_context (key, value)
select 'primary_session', customer_session_id from created
union all select 'primary_conversation', conversation_id from created;

with created as (
    select * from public.create_customer_chat_session(
        (select value from feedback_test_context where key = 'primary_public_id'),
        repeat('c', 64), now() + interval '7 days'
    )
)
insert into feedback_test_context (key, value)
select 'second_session', customer_session_id from created
union all select 'second_conversation', conversation_id from created;

with created as (
    select * from public.create_customer_chat_session(
        (select value from feedback_test_context where key = 'primary_public_id'),
        repeat('d', 64), now() + interval '7 days'
    )
)
insert into feedback_test_context (key, value)
select 'expired_session', customer_session_id from created
union all select 'expired_conversation', conversation_id from created;

with created as (
    select * from public.create_customer_chat_session(
        (select value from feedback_test_context where key = 'other_public_id'),
        repeat('b', 64), now() + interval '7 days'
    )
)
insert into feedback_test_context (key, value)
select 'other_session', customer_session_id from created
union all select 'other_conversation', conversation_id from created;

insert into feedback_test_context (key, value)
select 'primary_turn', turn_id from public.begin_customer_chat_turn(
    (select value from feedback_test_context where key = 'primary_conversation'),
    repeat('a', 64), '83000000-0000-4000-8000-000000000001', 'Primary question'
);
select ok(public.complete_customer_chat_turn(
    (select value from feedback_test_context where key = 'primary_turn'),
    repeat('a', 64), 'insufficient_evidence',
    'I do not have enough verified information to answer that.', '[]'::jsonb
), 'Primary assistant response is prepared for feedback tests');

insert into feedback_test_context (key, value)
select 'second_turn', turn_id from public.begin_customer_chat_turn(
    (select value from feedback_test_context where key = 'second_conversation'),
    repeat('c', 64), '83000000-0000-4000-8000-000000000002', 'Second question'
);
select ok(public.complete_customer_chat_turn(
    (select value from feedback_test_context where key = 'second_turn'),
    repeat('c', 64), 'insufficient_evidence',
    'I do not have enough verified information to answer that.', '[]'::jsonb
), 'Second same-workspace assistant response is prepared');

insert into feedback_test_context (key, value)
select 'other_turn', turn_id from public.begin_customer_chat_turn(
    (select value from feedback_test_context where key = 'other_conversation'),
    repeat('b', 64), '83000000-0000-4000-8000-000000000003', 'Other question'
);
select ok(public.complete_customer_chat_turn(
    (select value from feedback_test_context where key = 'other_turn'),
    repeat('b', 64), 'insufficient_evidence',
    'I do not have enough verified information to answer that.', '[]'::jsonb
), 'Other-workspace assistant response is prepared');
reset role;

insert into feedback_test_context (key, value)
select 'primary_customer_message', customer_message_id from public.conversation_turns
where id = (select value from feedback_test_context where key = 'primary_turn');
insert into feedback_test_context (key, value)
select 'primary_assistant_message', assistant_message_id from public.conversation_turns
where id = (select value from feedback_test_context where key = 'primary_turn');
insert into feedback_test_context (key, value)
select 'second_assistant_message', assistant_message_id from public.conversation_turns
where id = (select value from feedback_test_context where key = 'second_turn');
insert into feedback_test_context (key, value)
select 'other_assistant_message', assistant_message_id from public.conversation_turns
where id = (select value from feedback_test_context where key = 'other_turn');

insert into public.message_citations (
    workspace_id, message_id, ordinal, source_id, source_title,
    source_type, chunk_index, locator
)
values (
    (select value from feedback_test_context where key = 'primary_workspace'),
    (select value from feedback_test_context where key = 'primary_assistant_message'),
    1,
    '84000000-0000-4000-8000-000000000001',
    'Persisted support source',
    'faq',
    0,
    '{"kind":"faq"}'::jsonb
);

update public.customer_sessions
set created_at = now() - interval '2 days',
    last_seen_at = now() - interval '2 days',
    expires_at = now() - interval '1 day'
where id = (select value from feedback_test_context where key = 'expired_session');

select ok(
    (select relrowsecurity from pg_class where oid = 'public.message_feedback'::regclass),
    'Feedback has row-level security enabled'
);
select ok(
    not has_table_privilege('anon', 'public.message_feedback', 'SELECT')
    and not has_table_privilege('anon', 'public.message_feedback', 'INSERT')
    and not has_table_privilege('anon', 'public.message_feedback', 'UPDATE')
    and not has_table_privilege('anon', 'public.message_feedback', 'DELETE'),
    'Anonymous browser callers have no direct feedback access'
);
select ok(
    has_table_privilege('authenticated', 'public.message_feedback', 'SELECT')
    and not has_table_privilege('authenticated', 'public.message_feedback', 'INSERT')
    and not has_table_privilege('authenticated', 'public.message_feedback', 'UPDATE')
    and not has_table_privilege('authenticated', 'public.message_feedback', 'DELETE'),
    'Authenticated browser callers can read but cannot write feedback directly'
);
select ok(
    not has_table_privilege('service_role', 'public.message_feedback', 'SELECT')
    and not has_table_privilege('service_role', 'public.message_feedback', 'INSERT'),
    'The service role has no generic direct feedback-table access'
);
select ok(
    not has_function_privilege(
        'anon', 'public.set_customer_message_feedback(uuid,text,uuid,text)', 'EXECUTE'
    )
    and not has_function_privilege(
        'authenticated', 'public.set_customer_message_feedback(uuid,text,uuid,text)', 'EXECUTE'
    )
    and not has_function_privilege(
        'anon', 'public.request_customer_human_support(uuid,text)', 'EXECUTE'
    )
    and not has_function_privilege(
        'authenticated', 'public.request_customer_human_support(uuid,text)', 'EXECUTE'
    ),
    'Browser roles cannot execute feedback or human-request RPCs directly'
);
select ok(
    has_function_privilege(
        'service_role', 'public.set_customer_message_feedback(uuid,text,uuid,text)', 'EXECUTE'
    )
    and has_function_privilege(
        'service_role', 'public.request_customer_human_support(uuid,text)', 'EXECUTE'
    ),
    'Only the service role receives the new narrow RPC permissions'
);

set local role service_role;
select is(
    (select rating from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'positive'
    )),
    'positive',
    'A valid customer session can rate its assistant message'
);
reset role;

select is(
    (select count(*)::integer from public.message_feedback),
    1,
    'Valid feedback creates exactly one scoped row'
);
select ok(
    not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'message_feedback'
          and column_name like '%token%'
    ),
    'Feedback rows contain no token or token-hash column'
);

set local role service_role;
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('f', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'positive'
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'A wrong session cannot submit feedback'
);
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'expired_conversation'),
        repeat('d', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'positive'
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'An expired session cannot submit feedback'
);
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'second_assistant_message'),
        'positive'
    ) $$,
    '55000', 'Feedback target is unavailable',
    'A message from another conversation cannot be rated'
);
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'primary_customer_message'),
        'positive'
    ) $$,
    '55000', 'Feedback target is unavailable',
    'A customer message cannot receive assistant feedback'
);
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'other_assistant_message'),
        'positive'
    ) $$,
    '55000', 'Feedback target is unavailable',
    'A cross-workspace assistant message cannot be rated'
);
select throws_ok(
    $$ select * from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'neutral'
    ) $$,
    '22023', 'Customer feedback is invalid',
    'An invalid feedback rating is rejected'
);
select is(
    (select rating from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'positive'
    )),
    'positive',
    'Submitting the same feedback is idempotent'
);
reset role;
select is(
    (select count(*)::integer from public.message_feedback),
    1,
    'An idempotent feedback retry creates no duplicate row'
);
set local role service_role;
select is(
    (select rating from public.set_customer_message_feedback(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64),
        (select value from feedback_test_context where key = 'primary_assistant_message'),
        'negative'
    )),
    'negative',
    'A customer can change the existing rating'
);
reset role;

select is(
    (select count(*)::integer from public.message_feedback),
    1,
    'Changing feedback still retains one row per assistant message'
);

set local role authenticated;
set local request.jwt.claim.sub = '81000000-0000-0000-0000-000000000001';
select is(
    (select count(*)::integer from public.message_feedback),
    1,
    'A workspace member can read feedback for their conversation'
);
set local request.jwt.claim.sub = '82000000-0000-0000-0000-000000000002';
select is(
    (select count(*)::integer from public.message_feedback),
    0,
    'A nonmember cannot read another workspace feedback row'
);
reset role;

set local role service_role;
select is(
    (select status from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    )),
    'human_requested',
    'A valid session transitions an open conversation to human requested'
);
select ok(
    (select human_requested_at is not null from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    )),
    'The human-request timestamp is recorded'
);
select is(
    (select status from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    )),
    'human_requested',
    'A repeated human request returns the existing state safely'
);
select throws_ok(
    $$ select * from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'second_conversation'),
        repeat('f', 64)
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'A wrong token cannot request human support'
);
select throws_ok(
    $$ select * from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'expired_conversation'),
        repeat('d', 64)
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'An expired session cannot request human support'
);
select throws_ok(
    $$ select * from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'second_conversation'),
        repeat('b', 64)
    ) $$,
    '28000', 'Customer session is invalid or expired',
    'A token for another conversation cannot request human support'
);

reset role;
update public.conversations
set status = 'closed'
where id = (select value from feedback_test_context where key = 'second_conversation');
set local role service_role;
select throws_ok(
    $$ select * from public.request_customer_human_support(
        (select value from feedback_test_context where key = 'second_conversation'),
        repeat('c', 64)
    ) $$,
    '55000', 'Conversation is closed',
    'A closed conversation rejects a human request'
);
select throws_ok(
    $$ select * from public.begin_customer_chat_turn(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64), '83000000-0000-4000-8000-000000000099', 'Another AI turn'
    ) $$,
    '55000', 'Conversation is not open',
    'A human-requested conversation cannot begin another AI turn'
);
reset role;
select is(
    (select count(*)::integer from public.messages where conversation_id = (
        select value from feedback_test_context where key = 'primary_conversation'
    )),
    2,
    'Human request preserves existing customer and assistant messages'
);
select is(
    (select count(*)::integer from public.message_citations where message_id = (
        select value from feedback_test_context where key = 'primary_assistant_message'
    )),
    1,
    'Human request leaves the assistant citation set unchanged'
);
set local role service_role;
select is(
    (public.get_customer_conversation(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    ) ->> 'status'),
    'human_requested',
    'Conversation history restores human-requested state'
);
select is(
    (public.get_customer_conversation(
        (select value from feedback_test_context where key = 'primary_conversation'),
        repeat('a', 64)
    ) -> 'messages' -> 1 ->> 'feedback'),
    'negative',
    'Conversation history restores assistant feedback'
);
reset role;

select throws_ok(
    $$ update public.conversations
       set status = 'open', human_requested_at = now()
       where id = (select value from feedback_test_context where key = 'other_conversation') $$,
    '23514',
    'new row for relation "conversations" violates check constraint "conversations_human_request_state_consistent"',
    'Conversation state constraints reject an open conversation with a handoff timestamp'
);

update public.conversations
set status = 'closed'
where id = (select value from feedback_test_context where key = 'primary_conversation');
select ok(
    (select human_requested_at is not null from public.conversations where id = (
        select value from feedback_test_context where key = 'primary_conversation'
    )),
    'A closed conversation may retain its historical human-request timestamp'
);

select * from finish();
rollback;
