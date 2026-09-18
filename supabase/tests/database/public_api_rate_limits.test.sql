begin;
select no_plan();
-- All fixture users, sessions, messages and counters are synthetic and rolled back.
insert into auth.users(id,email,raw_user_meta_data) values
('f1000000-0000-4000-8000-000000000001','hardening-owner@example.test','{}'),
('f1000000-0000-4000-8000-000000000002','hardening-other@example.test','{}');
insert into public.workspaces(id,name,created_by) values
('f2000000-0000-4000-8000-000000000001','Hardening A','f1000000-0000-4000-8000-000000000001'),
('f2000000-0000-4000-8000-000000000002','Hardening B','f1000000-0000-4000-8000-000000000002');
insert into public.workspace_members(workspace_id,user_id,role) values
('f2000000-0000-4000-8000-000000000001','f1000000-0000-4000-8000-000000000001','owner'),
('f2000000-0000-4000-8000-000000000002','f1000000-0000-4000-8000-000000000002','owner');
create temporary table rate_fixture as
select 'A'::text as label, session.* from public.create_customer_chat_session(
(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('a',64),now()+interval '1 day') as session
union all
select 'B', session.* from public.create_customer_chat_session(
(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000002'),repeat('b',64),now()+interval '1 day') as session
union all
select 'C', session.* from public.create_customer_chat_session(
(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('c',64),now()+interval '1 day') as session;
-- Owner-only fixture seeding at the current DB window. Never exposed by the application.
create function pg_temp.seed_rate(target_scope text, target_subject uuid, amount integer)
returns void language sql as $$
insert into public.customer_api_rate_limits(scope,subject_id,window_started_at,request_count,expires_at)
values(target_scope,target_subject,date_trunc(case when target_scope like '%_hour' then 'hour' else 'minute' end,clock_timestamp()),amount,
date_trunc(case when target_scope like '%_hour' then 'hour' else 'minute' end,clock_timestamp())+
case when target_scope like '%_hour' then interval '1 hour' else interval '1 minute' end)
on conflict(scope,subject_id,window_started_at) do update set request_count=excluded.request_count;
$$;
select ok((select relrowsecurity from pg_class where oid='public.customer_api_rate_limits'::regclass),'Rate table RLS is enabled');
select is((select array_agg(column_name::text order by ordinal_position) from information_schema.columns where table_schema='public' and table_name='customer_api_rate_limits'),
array['scope','subject_id','window_started_at','request_count','expires_at']::text[],'Only infrastructure counters; no IP, hash, device or request content columns');
select ok(not has_table_privilege('anon','public.customer_api_rate_limits','SELECT,INSERT,UPDATE,DELETE'),'Anon has no direct counter privileges');
select ok(not has_table_privilege('authenticated','public.customer_api_rate_limits','SELECT,INSERT,UPDATE,DELETE'),'Authenticated has no direct counter privileges');
select ok(not has_table_privilege('service_role','public.customer_api_rate_limits','SELECT,INSERT,UPDATE,DELETE'),'Service RPC only, not direct table privileges');
select ok(not has_function_privilege('anon','app_private.consume_customer_rate_limit(text,uuid)','EXECUTE'),'Anon cannot execute private limiter');
select ok(not has_function_privilege('authenticated','app_private.consume_customer_rate_limit(text,uuid)','EXECUTE'),'Authenticated cannot execute private limiter');
select ok(not has_function_privilege('service_role','app_private.consume_customer_rate_limit(text,uuid)','EXECUTE'),'No service-role arbitrary subject/scope helper execution');
select ok(not has_function_privilege('authenticated','public.get_customer_conversation_history(uuid,text)','EXECUTE'),'History RPC is server-only');
select throws_ok($$insert into public.customer_api_rate_limits values('evil',gen_random_uuid(),now(),1,now()+interval '1 minute')$$,'23514',null,'Unknown scope rejected');
select throws_ok($$select app_private.consume_customer_rate_limit('evil',gen_random_uuid())$$,'22023',null,'Unknown helper scope rejected');

-- Session minute: fill the remaining slots using the unchanged server-created identity path.
select pg_temp.seed_rate('session_minute',(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),29);
select lives_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('d',64),now()+interval '1 day')$$,'Final minute session slot succeeds');
select throws_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('e',64),now()+interval '1 day')$$,'PT429','Too many requests','Session minute exhausted');
select is((select count(*) from public.customer_sessions where workspace_id='f2000000-0000-4000-8000-000000000001'),3::bigint,'Rejected creation leaves no session');
select lives_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000002'),repeat('f',64),now()+interval '1 day')$$,'Separate widget public ID has separate quota');
delete from public.customer_api_rate_limits where scope='session_minute' and subject_id=(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001');
select pg_temp.seed_rate('session_hour',(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),300);
select throws_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('1',64),now()+interval '1 day')$$,'PT429','Too many requests','Session hourly quota enforced independently');
select is((select count(*) from public.customer_api_rate_limits where scope='session_minute' and subject_id=(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001')),0::bigint,'Hourly rejection atomically rolls back minute claim');
delete from public.customer_api_rate_limits where subject_id=(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001');
insert into public.customer_api_rate_limits values('session_minute',(select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),date_trunc('minute',clock_timestamp())-interval '2 minutes',30,date_trunc('minute',clock_timestamp())-interval '1 minute');
select lives_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('2',64),now()+interval '1 day')$$,'Expired window does not block new creation');
update public.workspace_chat_configs set is_enabled=false where workspace_id='f2000000-0000-4000-8000-000000000001';
select throws_ok($$select public.create_customer_chat_session((select public_id from public.workspace_chat_configs where workspace_id='f2000000-0000-4000-8000-000000000001'),repeat('3',64),now()+interval '1 day')$$,'22023',null,'Disabled widget retains unavailable validation');
update public.workspace_chat_configs set is_enabled=true where workspace_id='f2000000-0000-4000-8000-000000000001';

select pg_temp.seed_rate('turn_minute',(select customer_session_id from rate_fixture where label='A'),5);
select pg_temp.seed_rate('turn_hour',(select customer_session_id from rate_fixture where label='A'),59);
create temporary table rate_turn as select * from public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='A'),repeat('a',64),'f5000000-0000-4000-8000-000000000001','Synthetic question');
select is((select turn_status from rate_turn),'processing','Final allowed turn begins');
select is((select request_count from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='A')),6,'Minute processing counter consumed exactly once');
select is((select request_count from public.customer_api_rate_limits where scope='turn_hour' and subject_id=(select customer_session_id from rate_fixture where label='A')),60,'Hourly processing counter consumed exactly once');
select is((select is_replay from public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='A'),repeat('a',64),'f5000000-0000-4000-8000-000000000001','Synthetic question')),true,'Processing duplicate preserves replay/conflict path despite exhausted quota');
select is((select request_count from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='A')),6,'Processing duplicate consumes no new unit');
select lives_ok($$select public.complete_customer_chat_turn((select turn_id from rate_turn),repeat('a',64),'insufficient_evidence','I do not have enough demo evidence.','[]'::jsonb)$$,'Complete synthetic result normally');
select is((select turn_status from public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='A'),repeat('a',64),'f5000000-0000-4000-8000-000000000001','Synthetic question')),'completed','Completed replay bypasses quota');
select is((select request_count from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='A')),6,'Completed replay consumes no processing quota');
update public.conversation_turns set created_at=now()-interval '2 seconds' where id=(select turn_id from rate_turn);
select throws_ok($$select public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='A'),repeat('a',64),'f5000000-0000-4000-8000-000000000002','Another synthetic question')$$,'PT429','Too many requests','New turn rejects exhausted minute quota');
select is((select count(*) from public.messages where conversation_id=(select conversation_id from rate_fixture where label='A')),2::bigint,'Rejected turn leaves no new customer message');
delete from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='A');
select throws_ok($$select public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='A'),repeat('a',64),'f5000000-0000-4000-8000-000000000002','Another synthetic question')$$,'PT429','Too many requests','Turn hourly quota independently enforced');
select is((select count(*) from public.conversation_turns where conversation_id=(select conversation_id from rate_fixture where label='A')),1::bigint,'Hourly rejection leaves no turn');
select is((select count(*) from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='A')),0::bigint,'Turn hourly rejection atomically rolls back minute claim');
select lives_ok($$select public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='B'),repeat('b',64),'f5000000-0000-4000-8000-000000000003','Separate session question')$$,'Separate session turn quota isolated');
create temporary table retry_turn as select * from public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='C'),repeat('c',64),'f5000000-0000-4000-8000-000000000004','Retry question');
select lives_ok($$select public.fail_customer_chat_turn((select turn_id from retry_turn),repeat('c',64),'generation_failed')$$,'Synthetic attempt fails safely');
select is((select is_replay from public.begin_customer_chat_turn((select conversation_id from rate_fixture where label='C'),repeat('c',64),'f5000000-0000-4000-8000-000000000004','Retry question')),false,'Failed retry starts a new attempt with same ID');
select is((select request_count from public.customer_api_rate_limits where scope='turn_minute' and subject_id=(select customer_session_id from rate_fixture where label='C')),2,'Failed retry consumes one new attempt');

select pg_temp.seed_rate('history_minute',(select customer_session_id from rate_fixture where label='A'),59);
select lives_ok($$select public.get_customer_conversation_history((select conversation_id from rate_fixture where label='A'),repeat('a',64))$$,'Last public history slot succeeds');
select throws_ok($$select public.get_customer_conversation_history((select conversation_id from rate_fixture where label='A'),repeat('a',64))$$,'PT429','Too many requests','Public history quota enforced');
select lives_ok($$select public.get_customer_conversation((select conversation_id from rate_fixture where label='A'),repeat('a',64))$$,'Internal context read does not double-consume browser history quota');
select throws_ok($$select public.get_customer_conversation_history((select conversation_id from rate_fixture where label='A'),repeat('b',64))$$,'28000',null,'Wrong token/cross-workspace history rejected before quota');
select lives_ok($$select public.get_customer_conversation_history((select conversation_id from rate_fixture where label='B'),repeat('b',64))$$,'Separate session history isolated');

select pg_temp.seed_rate('feedback_minute',(select customer_session_id from rate_fixture where label='A'),19);
select lives_ok($$select public.set_customer_message_feedback((select conversation_id from rate_fixture where label='A'),repeat('a',64),(select id from public.messages where turn_id=(select turn_id from rate_turn) and role='assistant'),'positive')$$,'Last feedback slot succeeds');
select throws_ok($$select public.set_customer_message_feedback((select conversation_id from rate_fixture where label='A'),repeat('a',64),(select id from public.messages where turn_id=(select turn_id from rate_turn) and role='assistant'),'negative')$$,'PT429','Too many requests','Repeated feedback toggling bounded');
select is((select rating from public.message_feedback where conversation_id=(select conversation_id from rate_fixture where label='A')),'positive','Rejected feedback leaves saved rating intact');
select throws_ok($$select public.set_customer_message_feedback((select conversation_id from rate_fixture where label='A'),repeat('b',64),(select id from public.messages where turn_id=(select turn_id from rate_turn) and role='assistant'),'positive')$$,'28000',null,'Cross-session feedback denied');
select pg_temp.seed_rate('human_minute',(select customer_session_id from rate_fixture where label='B'),9);
select is((select is_new_request from public.request_customer_human_support((select conversation_id from rate_fixture where label='B'),repeat('b',64))),true,'Last human request slot records first request');
select throws_ok($$select public.request_customer_human_support((select conversation_id from rate_fixture where label='B'),repeat('b',64))$$,'PT429','Too many requests','Human request minute quota enforced');
select is((select status from public.conversations where id=(select conversation_id from rate_fixture where label='B')),'human_requested','Throttle cannot undo recorded human request');
select is((select count(*) from public.escalations where conversation_id=(select conversation_id from rate_fixture where label='B')),1::bigint,'One escalation remains after throttle');
select is((select is_new_request from public.request_customer_human_support((select conversation_id from rate_fixture where label='C'),repeat('c',64))),true,'Separate session human request isolated');
select is((select is_new_request from public.request_customer_human_support((select conversation_id from rate_fixture where label='C'),repeat('c',64))),false,'Repeated recorded human request signals no new immediate triage');
select is((select count(*) from public.escalations where conversation_id=(select conversation_id from rate_fixture where label='C')),1::bigint,'Repeated human request retains one escalation');
select throws_ok($$select public.request_customer_human_support((select conversation_id from rate_fixture where label='C'),repeat('a',64))$$,'28000',null,'Wrong human-request token rejected');

-- Deterministic retry metadata and transactionally bounded maintenance.
-- Refresh the exact DB-time window: a long hosted run can cross a minute.
select pg_temp.seed_rate('history_minute',(select customer_session_id from rate_fixture where label='A'),60);
do $$
declare details text; seconds integer;
begin
    begin
        perform public.get_customer_conversation_history((select conversation_id from rate_fixture where label='A'),repeat('a',64));
        raise exception 'Expected rate limit';
    exception when sqlstate 'PT429' then
        get stacked diagnostics details = pg_exception_detail;
        seconds := (details::jsonb->>'retry_after_seconds')::integer;
        if seconds not between 1 and 60 or details::jsonb - 'retry_after_seconds' <> '{}'::jsonb then
            raise exception 'Unsafe retry metadata';
        end if;
    end;
end;
$$;
select pass('Rate failure contains only bounded retry-after seconds');
select is(public.cleanup_customer_api_rate_limits(1),1,'Expired-row cleanup honors bounded batch');
select throws_ok($$select public.cleanup_customer_api_rate_limits(501)$$,'22023',null,'Oversized cleanup batch denied');
select lives_ok($$select public.get_customer_conversation((select conversation_id from rate_fixture where label='A'),repeat('a',64))$$,'Cleanup leaves active customer state unchanged');
set local role anon;
select throws_ok($$select * from public.customer_api_rate_limits$$,'42501',null,'Anon cannot read infrastructure counters');
select throws_ok($$select public.cleanup_customer_api_rate_limits(1)$$,'42501',null,'Anon cannot run maintenance');
reset role;
set local role authenticated;
select throws_ok($$select * from public.customer_api_rate_limits$$,'42501',null,'Authenticated cannot read counters');
select throws_ok($$insert into public.customer_api_rate_limits values('history_minute',gen_random_uuid(),now(),1,now()+interval '1 minute')$$,'42501',null,'Authenticated cannot write counters');
reset role;
select * from finish();
rollback;
