begin;
select no_plan();

insert into auth.users (id, email, raw_user_meta_data) values
    ('91000000-0000-0000-0000-000000000001', 'triage-owner@example.test', '{}'),
    ('92000000-0000-0000-0000-000000000002', 'triage-outsider@example.test', '{}');
create temporary table triage_test_context (key text primary key, value uuid not null);
grant select, insert, update on triage_test_context to authenticated, service_role;
set local role authenticated;
set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
insert into triage_test_context select 'workspace', id from public.create_workspace('Triage Workspace');
set local request.jwt.claim.sub = '92000000-0000-0000-0000-000000000002';
insert into triage_test_context select 'other_workspace', id from public.create_workspace('Other Triage Workspace');
reset role;
insert into triage_test_context select 'public_id', public_id from public.workspace_chat_configs
where workspace_id = (select value from triage_test_context where key = 'workspace');
insert into triage_test_context select 'other_public_id', public_id from public.workspace_chat_configs
where workspace_id = (select value from triage_test_context where key = 'other_workspace');
set local role service_role;
with created as (select * from public.create_customer_chat_session(
    (select value from triage_test_context where key = 'public_id'), repeat('a',64), now() + interval '7 days'
)) insert into triage_test_context select 'conversation', conversation_id from created;
with created as (select * from public.create_customer_chat_session(
    (select value from triage_test_context where key = 'other_public_id'), repeat('b',64), now() + interval '7 days'
)) insert into triage_test_context select 'other_conversation', conversation_id from created;
insert into triage_test_context select 'turn', turn_id from public.begin_customer_chat_turn(
    (select value from triage_test_context where key = 'conversation'), repeat('a',64),
    '93000000-0000-4000-8000-000000000001', 'Cannot log in. Please help.'
);
select ok(public.complete_customer_chat_turn(
    (select value from triage_test_context where key = 'turn'), repeat('a',64),
    'insufficient_evidence', 'Insufficient verified information.', '[]'::jsonb
), 'Ordinary insufficient evidence is persisted without auto-escalation');
reset role;
select is((select count(*)::integer from public.escalations), 0, 'No automatic insufficient-evidence escalation in Phase 6A');

select ok((select relrowsecurity from pg_class where oid = 'public.escalations'::regclass), 'Escalations have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.escalation_triage_runs'::regclass), 'Audit runs have RLS');
select ok(not has_table_privilege('authenticated', 'public.escalations', 'INSERT,UPDATE,DELETE'), 'Browsers cannot write escalations');
select ok(not has_table_privilege('authenticated', 'public.escalation_triage_runs', 'INSERT,UPDATE,DELETE'), 'Browsers cannot write audit runs');
select ok(not has_table_privilege('anon', 'public.escalations', 'SELECT'), 'Anon cannot directly read escalations');
select ok(not has_table_privilege('anon', 'public.escalation_triage_runs', 'SELECT'), 'Anon cannot directly read audit runs');
select ok(not has_table_privilege('service_role', 'public.escalations', 'INSERT,UPDATE,DELETE'), 'Secret-key role is RPC-only too');
select ok(has_function_privilege('service_role', 'public.begin_escalation_triage(uuid)', 'EXECUTE'), 'Service role can begin triage');
select ok(has_function_privilege('service_role', 'public.complete_escalation_triage(uuid,uuid,text,text,text,text,text)', 'EXECUTE'), 'Service role can complete triage');
select ok(has_function_privilege('service_role', 'public.fail_escalation_triage(uuid,uuid,text)', 'EXECUTE'), 'Service role can fail triage');
select ok(not has_function_privilege('authenticated', 'public.begin_escalation_triage(uuid)', 'EXECUTE'), 'Browser cannot begin triage');
select ok(not has_function_privilege('authenticated', 'public.complete_escalation_triage(uuid,uuid,text,text,text,text,text)', 'EXECUTE'), 'Browser cannot complete triage');
select ok(not has_function_privilege('authenticated', 'public.fail_escalation_triage(uuid,uuid,text)', 'EXECUTE'), 'Browser cannot fail triage');
select ok(not has_function_privilege('anon', 'public.begin_escalation_triage(uuid)', 'EXECUTE'), 'Anon cannot begin triage');
select ok(not has_function_privilege('anon', 'public.complete_escalation_triage(uuid,uuid,text,text,text,text,text)', 'EXECUTE'), 'Anon cannot complete triage');
select ok(not has_function_privilege('anon', 'public.fail_escalation_triage(uuid,uuid,text)', 'EXECUTE'), 'Anon cannot fail triage');

set local role service_role;
insert into triage_test_context select 'escalation', escalation_id from public.request_customer_human_support(
    (select value from triage_test_context where key = 'conversation'), repeat('a',64)
);
insert into triage_test_context select 'other_escalation', escalation_id from public.request_customer_human_support(
    (select value from triage_test_context where key = 'other_conversation'), repeat('b',64)
);
select is((select escalation_id from public.request_customer_human_support(
    (select value from triage_test_context where key = 'conversation'), repeat('a',64)
)), (select value from triage_test_context where key = 'escalation'), 'Repeated human request reuses the escalation');
reset role;
select is((select status from public.conversations where id = (select value from triage_test_context where key = 'conversation')),
    'human_requested', 'Human request atomically pauses AI turns');
select ok((select human_requested_at is not null from public.conversations where id = (select value from triage_test_context where key = 'conversation')), 'Handoff timestamp preserved');
select is((select count(*)::integer from public.escalations where conversation_id = (select value from triage_test_context where key = 'conversation')), 1, 'One durable escalation per conversation');
select is((select triage_status from public.escalations where id = (select value from triage_test_context where key = 'escalation')), 'pending', 'Reliable placeholder starts pending without AI');
select throws_ok($$insert into public.escalations(workspace_id, conversation_id, trigger_reason)
select workspace_id, conversation_id, 'human_requested' from public.escalations limit 1$$,
    '23505', null, 'Duplicate conversation escalation rejected');
select throws_ok($$update public.escalations set workspace_id = (select value from triage_test_context where key = 'other_workspace')
where id = (select value from triage_test_context where key = 'escalation')$$,
    '23503', null, 'Conversation/workspace integrity enforced');

set local role authenticated;
set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
select is((select count(*)::integer from public.escalations), 1, 'Owner sees only own workspace escalation');
select is((select count(*)::integer from public.escalations where id = (select value from triage_test_context where key = 'other_escalation')), 0, 'Nonmember cannot read other workspace');
select throws_ok($$delete from public.escalations$$, '42501', null, 'Browser direct deletes rejected');
reset role;
set local role anon;
select throws_ok($$select * from public.escalations$$, '42501', null, 'Anonymous table reads rejected');
select throws_ok($$select * from public.escalation_triage_runs$$, '42501', null, 'Anonymous audit reads rejected');
reset role;

set local role service_role;
insert into triage_test_context select 'run1', (public.begin_escalation_triage(
    (select value from triage_test_context where key = 'escalation')) ->> 'triage_run_id')::uuid;
select is(public.begin_escalation_triage((select value from triage_test_context where key = 'escalation')) ->> 'should_run',
    'false', 'Recent processing does not duplicate attempt');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'),
    (select value from triage_test_context where key = 'other_escalation'), 'other', 'normal', 'Valid.', 'gemini', 'gemini-3.8-flash')$$,
    '55000', 'Triage run is not the active attempt', 'Wrong run relationship rejected');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run1'),
    'invented', 'normal', 'Valid.', 'gemini', 'gemini-3.8-flash')$$,
    '22023', 'Triage completion is invalid', 'Invalid category rejected');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run1'),
    'other', 'critical', 'Valid.', 'gemini', 'gemini-3.8-flash')$$,
    '22023', 'Triage completion is invalid', 'Invalid priority rejected');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run1'),
    'other', 'normal', '   ', 'gemini', 'gemini-3.8-flash')$$,
    '22023', 'Triage completion is invalid', 'Blank summary rejected');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run1'),
    'other', 'normal', repeat('x',1201), 'gemini', 'gemini-3.8-flash')$$,
    '22023', 'Triage completion is invalid', 'Oversize summary rejected');
select throws_ok($$select public.fail_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run1'), 'raw error text')$$,
    '22023', 'Triage failure code is invalid', 'Only safe error codes may be saved');
select ok(public.fail_escalation_triage((select value from triage_test_context where key = 'escalation'),
    (select value from triage_test_context where key = 'run1'), 'triage_not_configured'), 'AI failure is recorded without removing escalation');
insert into triage_test_context select 'run2', (public.begin_escalation_triage(
    (select value from triage_test_context where key = 'escalation')) ->> 'triage_run_id')::uuid;
reset role;
select is((select triage_attempts from public.escalations where id = (select value from triage_test_context where key = 'escalation')), 2, 'Failed retry increments attempts');
select is((select status from public.escalation_triage_runs where id = (select value from triage_test_context where key = 'run1')), 'failed', 'Failure is auditable');
select is((select status from public.escalation_triage_runs where id = (select value from triage_test_context where key = 'run2')), 'processing', 'Matching active audit run exists');
select throws_ok($$insert into public.escalation_triage_runs(workspace_id, escalation_id, attempt_number, status)
select workspace_id, escalation_id, attempt_number, 'processing' from public.escalation_triage_runs limit 1$$,
    '23505', null, 'Duplicate audit attempt rejected');
select throws_ok($$update public.escalation_triage_runs set workspace_id = (select value from triage_test_context where key = 'other_workspace')
where id = (select value from triage_test_context where key = 'run2')$$,
    '23503', null, 'Audit workspace relationship enforced');
select throws_ok($$update public.escalations set triage_started_at = null
where id = (select value from triage_test_context where key = 'escalation')$$,
    '23514', null, 'Processing state requires timestamp');
select throws_ok($$update public.escalation_triage_runs set status = 'completed', completed_at = now(), provider = 'gemini', model = 'gemini-3.8-flash'
where id = (select value from triage_test_context where key = 'run2')$$,
    '23514', null, 'Completed audit requires the known tool action');

-- Simulate a crashed process. Recovery must fence the old run out of completion.
update public.escalations set triage_started_at = now() - interval '16 minutes'
where id = (select value from triage_test_context where key = 'escalation');
update public.escalation_triage_runs set started_at = now() - interval '16 minutes'
where id = (select value from triage_test_context where key = 'run2');
set local role service_role;
insert into triage_test_context select 'run3', (public.begin_escalation_triage(
    (select value from triage_test_context where key = 'escalation')) ->> 'triage_run_id')::uuid;
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run2'),
    'other', 'normal', 'Valid.', 'gemini', 'gemini-3.8-flash')$$,
    '55000', 'Triage run is not the active attempt', 'Stale worker cannot complete newer attempt');
select ok(public.complete_escalation_triage((select value from triage_test_context where key = 'escalation'),
    (select value from triage_test_context where key = 'run3'), 'account_access', 'normal', 'Customer cannot log in.', 'gemini', 'gemini-3.8-flash'), 'Validated completion succeeds');
select is(public.begin_escalation_triage((select value from triage_test_context where key = 'escalation')) ->> 'should_run',
    'false', 'Completed triage never runs again');
select throws_ok($$select public.complete_escalation_triage(
    (select value from triage_test_context where key = 'escalation'), (select value from triage_test_context where key = 'run3'),
    'other', 'normal', 'Valid.', 'gemini', 'gemini-3.8-flash')$$,
    '55000', 'Escalation is not processing', 'Completed attempt cannot execute twice');
reset role;
select is((select triage_attempts from public.escalations where id = (select value from triage_test_context where key = 'escalation')), 3, 'Stale recovery increments attempts once');
select is((select safe_error_code from public.escalation_triage_runs where id = (select value from triage_test_context where key = 'run2')), 'stale_triage_recovered', 'Stale attempt is auditable');
select is((select triage_status from public.escalations where id = (select value from triage_test_context where key = 'escalation')), 'completed', 'Escalation details committed');
select is((select tool_name from public.escalation_triage_runs where id = (select value from triage_test_context where key = 'run3')), 'create_escalation', 'Only executed action is audited');
select ok((select triage_started_at is null and last_error_code is null and triaged_at is not null
    from public.escalations where id = (select value from triage_test_context where key = 'escalation')), 'Completed state clears processing/error fields');
set local role authenticated;
set local request.jwt.claim.sub = '91000000-0000-0000-0000-000000000001';
select is((select count(*)::integer from public.escalation_triage_runs), 3, 'Owner can read own audit rows');
set local request.jwt.claim.sub = '92000000-0000-0000-0000-000000000002';
select is((select count(*)::integer from public.escalation_triage_runs), 0, 'Nonmember cannot read audit rows');
reset role;
update public.conversations set status = 'closed'
where id = (select value from triage_test_context where key = 'other_conversation');
set local role service_role;
select throws_ok($$select public.begin_escalation_triage((select value from triage_test_context where key = 'other_escalation'))$$,
    '55000', 'Escalation is not eligible for human-request triage', 'Underlying conversation must still be human-requested');
reset role;
select * from finish();
rollback;
