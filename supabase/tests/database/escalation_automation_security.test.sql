begin;
select no_plan();

insert into auth.users (id, email, email_confirmed_at, raw_user_meta_data) values
    ('a1000000-0000-4000-8000-000000000001', 'automation-owner@example.test', now(), '{}'),
    ('a1000000-0000-4000-8000-000000000002', 'automation-admin@example.test', now(), '{}'),
    ('a1000000-0000-4000-8000-000000000003', 'automation-member@example.test', now(), '{}'),
    ('a1000000-0000-4000-8000-000000000004', 'automation-outsider@example.test', now(), '{}'),
    ('a1000000-0000-4000-8000-000000000005', 'unverified@example.test', null, '{}');
create temporary table automation_context (key text primary key, value uuid not null);
grant select, insert on automation_context to authenticated, service_role;
set local role authenticated;
set local request.jwt.claim.sub = 'a1000000-0000-4000-8000-000000000001';
insert into automation_context select 'workspace', id from public.create_workspace('Automation Demo');
set local request.jwt.claim.sub = 'a1000000-0000-4000-8000-000000000004';
insert into automation_context select 'other_workspace', id from public.create_workspace('Other Automation Demo');
reset role;
insert into public.workspace_members (workspace_id,user_id,role)
select value, 'a1000000-0000-4000-8000-000000000002', 'admin' from automation_context where key='workspace';
insert into public.workspace_members (workspace_id,user_id,role)
select value, 'a1000000-0000-4000-8000-000000000003', 'member' from automation_context where key='workspace';
insert into public.workspace_members (workspace_id,user_id,role)
select value, 'a1000000-0000-4000-8000-000000000005', 'admin' from automation_context where key='workspace';
insert into automation_context select 'public_id', public_id from public.workspace_chat_configs
where workspace_id=(select value from automation_context where key='workspace');
set local role service_role;
insert into automation_context select 'conversation', conversation_id from public.create_customer_chat_session(
    (select value from automation_context where key='public_id'), repeat('c',64), now()+interval '7 days');
insert into automation_context select 'turn', turn_id from public.begin_customer_chat_turn(
    (select value from automation_context where key='conversation'), repeat('c',64), gen_random_uuid(), 'Synthetic unresolved issue');
select ok(public.complete_customer_chat_turn((select value from automation_context where key='turn'),
    repeat('c',64),'insufficient_evidence','Insufficient verified information.','[]'), 'Completion atomically escalates unresolved work');
reset role;
insert into automation_context select 'escalation', id from public.escalations
where conversation_id=(select value from automation_context where key='conversation');
select is((select status from public.conversations where id=(select value from automation_context where key='conversation')),
    'open', 'Automatic escalation never claims a human request');
select is((select trigger_reason from public.escalations where id=(select value from automation_context where key='escalation')),
    'insufficient_evidence', 'Correct automatic trigger');
-- A second persisted assistant answer for another turn exercises duplicate trigger handling.
insert into public.conversation_turns(id,workspace_id,conversation_id,client_message_id,status)
select 'a2000000-0000-4000-8000-000000000001',value,
    (select value from automation_context where key='conversation'),gen_random_uuid(),'processing'
from automation_context where key='workspace';
insert into public.messages(workspace_id,conversation_id,turn_id,role,content,answer_status)
select value,(select value from automation_context where key='conversation'),
    'a2000000-0000-4000-8000-000000000001','assistant','Still insufficient.','insufficient_evidence'
from automation_context where key='workspace';
select is((select count(*)::integer from public.escalations where conversation_id=(select value from automation_context where key='conversation')),
    1, 'Repeated insufficient answers reuse the escalation');
-- An answered message on an independent conversation creates no escalation.
set local role service_role;
insert into automation_context select 'answered_conversation',conversation_id from public.create_customer_chat_session(
    (select value from automation_context where key='public_id'),repeat('d',64),now()+interval '7 days');
reset role;
insert into public.conversation_turns(id,workspace_id,conversation_id,client_message_id,status)
select 'a2000000-0000-4000-8000-000000000002',value,
    (select value from automation_context where key='answered_conversation'),gen_random_uuid(),'processing'
from automation_context where key='workspace';
insert into public.messages(workspace_id,conversation_id,turn_id,role,content,answer_status)
select value,(select value from automation_context where key='answered_conversation'),
    'a2000000-0000-4000-8000-000000000002','assistant','Synthetic grounded answer.','answered'
from automation_context where key='workspace';
select is((select count(*)::integer from public.escalations where conversation_id=(select value from automation_context where key='answered_conversation')),
    0,'Answered messages do not auto-escalate');

set local role service_role;
select ok((select value from automation_context where key='escalation') in (select public.list_recoverable_escalations(10)), 'Pending automatic work recoverable');
select throws_ok($$select public.list_recoverable_escalations(21)$$,'22023',null,'Recovery limit bounded');
insert into automation_context select 'run1',(public.begin_escalation_triage((select value from automation_context where key='escalation'))->>'triage_run_id')::uuid;
select is(public.begin_escalation_triage((select value from automation_context where key='escalation'))->>'should_run','false','Duplicate claim suppressed');
select ok(public.complete_escalation_triage((select value from automation_context where key='escalation'),
    (select value from automation_context where key='run1'),'billing','high','Synthetic summary not emailed.','gemini','gemini-3.8-flash'), 'Open unresolved conversation triages');
select is((select escalation_id from public.request_customer_human_support((select value from automation_context where key='conversation'),repeat('c',64))),
    (select value from automation_context where key='escalation'), 'Later human request reuses completed automatic escalation');
reset role;
select is((select count(*)::integer from public.escalation_triage_runs where escalation_id=(select value from automation_context where key='escalation')),1,'Human request preserves prior audit');
insert into automation_context select 'notification',id from public.escalation_notifications
where escalation_id=(select value from automation_context where key='escalation');
select is((select status from public.escalation_notifications where id=(select value from automation_context where key='notification')),'pending','Triage completion atomically enqueues notification');
update public.escalations set status='in_progress' where id=(select value from automation_context where key='escalation');
select is((select count(*)::integer from public.escalation_notifications),1,'Completed row updates cannot duplicate outbox');
select ok(not exists(select 1 from information_schema.columns where table_schema='public' and table_name='escalation_notifications'
    and column_name in ('recipient_emails','summary','transcript','session_token','customer_email')), 'Outbox stores no transcript or email snapshots');
select throws_ok($$update public.escalation_notifications set workspace_id=(select value from automation_context where key='other_workspace')$$,
    '23503',null,'Notification workspace must match escalation');
select throws_ok($$update public.escalation_notifications set status='sent'$$,'23514',null,'Inconsistent delivery state rejected');
select ok((select relrowsecurity from pg_class where oid='public.escalation_notifications'::regclass),'Outbox RLS enabled');
select ok(not has_table_privilege('authenticated','public.escalation_notifications','INSERT,UPDATE,DELETE'),'Browser outbox writes denied');
select ok(not has_table_privilege('service_role','public.escalation_notifications','INSERT,UPDATE,DELETE'),'Privileged writes RPC-only');
select ok(not has_table_privilege('anon','public.escalation_notifications','SELECT'),'Anonymous outbox reads denied');
select ok(not has_function_privilege('authenticated','public.list_recoverable_escalations(integer)','EXECUTE'),'Browser triage listing denied');
select ok(not has_function_privilege('anon','public.list_recoverable_escalations(integer)','EXECUTE'),'Anonymous triage listing denied');
select ok(bool_and(has_function_privilege('service_role',signature,'EXECUTE')
    and not has_function_privilege('authenticated',signature,'EXECUTE') and not has_function_privilege('anon',signature,'EXECUTE')),
    'All notification RPCs server-only') from unnest(array[
    'public.list_recoverable_escalation_notifications(integer)','public.begin_escalation_notification(uuid)',
    'public.complete_escalation_notification(uuid,integer,text,text)','public.fail_escalation_notification(uuid,integer,text)']) as signatures(signature);
set local role authenticated;
set local request.jwt.claim.sub='a1000000-0000-4000-8000-000000000003';
select is((select count(*)::integer from public.escalation_notifications),1,'Workspace members may read delivery state');
set local request.jwt.claim.sub='a1000000-0000-4000-8000-000000000004';
select is((select count(*)::integer from public.escalation_notifications),0,'Nonmembers cannot read another workspace outbox');
reset role;

create temporary table notification_claim (context jsonb);
grant select,insert on notification_claim to service_role;
set local role service_role;
insert into notification_claim select public.begin_escalation_notification((select value from automation_context where key='notification'));
select is((select context->'recipient_emails' from notification_claim),
    '["automation-admin@example.test","automation-owner@example.test"]'::jsonb,'Only verified workspace owner/admin recipients');
select ok((select context-array['notification_id','workspace_name','category','priority','recipient_emails','attempt_number'] from notification_claim)='{}'::jsonb,
    'Delivery context contains only minimal trusted fields');
select is(public.begin_escalation_notification((select value from automation_context where key='notification')),null::jsonb,'Active sending cannot be claimed twice');
select throws_ok($$select public.complete_escalation_notification((select value from automation_context where key='notification'),1,'resend',repeat('x',201))$$,
    '22023',null,'Provider message ID bounded');
select ok(public.fail_escalation_notification((select value from automation_context where key='notification'),1,'notification_rate_limited'),'Safe transient delivery failure');
select is(public.begin_escalation_notification((select value from automation_context where key='notification')),null::jsonb,'Failure backoff enforced at claim');
reset role;
alter table public.escalation_notifications disable trigger escalation_notifications_set_updated_at;
update public.escalation_notifications set updated_at=now()-interval '16 minutes';
alter table public.escalation_notifications enable trigger escalation_notifications_set_updated_at;
set local role service_role;
select is(public.begin_escalation_notification((select value from automation_context where key='notification'))->>'attempt_number','2','Transient notification retries after durable backoff');
reset role;
update public.escalation_notifications set delivery_started_at=now()-interval '16 minutes';
set local role service_role;
select is(public.begin_escalation_notification((select value from automation_context where key='notification'))->>'attempt_number','3','Stale send recoverable once within provider window');
select throws_ok($$select public.complete_escalation_notification((select value from automation_context where key='notification'),2,'resend','message-old')$$,
    '55000',null,'Stale worker completion fenced');
select throws_ok($$select public.fail_escalation_notification((select value from automation_context where key='notification'),2,'notification_failed')$$,
    '55000',null,'Stale worker failure fenced');
select ok(public.complete_escalation_notification((select value from automation_context where key='notification'),3,'resend','message-3'),'Delivery completion records bounded ID');
select ok(public.complete_escalation_notification((select value from automation_context where key='notification'),3,'resend','message-3'),'Lost completion response can be replayed idempotently');
select is(public.begin_escalation_notification((select value from automation_context where key='notification')),null::jsonb,'Sent final and never resent');
select is((select count(*)::integer from public.list_recoverable_escalation_notifications(10)),0,'Sent omitted from recovery');
reset role;

-- Independent fixtures for retry exclusions/caps and recipient failure, without AI.
insert into public.escalations(workspace_id,conversation_id,trigger_reason)
select value,(select value from automation_context where key='answered_conversation'),'insufficient_evidence'
from automation_context where key='workspace';
insert into automation_context select 'retry_escalation',id from public.escalations
where conversation_id=(select value from automation_context where key='answered_conversation');
set local role service_role;
insert into automation_context select 'retry_run',(public.begin_escalation_triage((select value from automation_context where key='retry_escalation'))->>'triage_run_id')::uuid;
select ok(public.fail_escalation_triage((select value from automation_context where key='retry_escalation'),
    (select value from automation_context where key='retry_run'),'triage_invalid_tool_call'),'Invalid tool fails safely');
reset role;
alter table public.escalations disable trigger escalations_set_updated_at;
update public.escalations set updated_at=now()-interval '16 minutes' where id=(select value from automation_context where key='retry_escalation');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalations(10)),0,'Invalid tool never loops automatically');
select is(public.begin_escalation_triage((select value from automation_context where key='retry_escalation'))->>'should_run','false','Claim also enforces invalid-tool exclusion');
reset role;
update public.escalations set last_error_code='triage_auth_failed' where id=(select value from automation_context where key='retry_escalation');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalations(10)),0,'Auth failure excluded');
reset role;
update public.escalations set last_error_code='triage_not_configured',triage_attempts=3 where id=(select value from automation_context where key='retry_escalation');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalations(10)),0,'Triage cap enforced');
select is(public.begin_escalation_triage((select value from automation_context where key='retry_escalation'))->>'should_run','false','Claim cannot bypass cap');
reset role;
update public.escalations set triage_attempts=1 where id=(select value from automation_context where key='retry_escalation');
alter table public.escalations enable trigger escalations_set_updated_at;
set local role service_role;
insert into automation_context select 'retry_run2',(public.begin_escalation_triage((select value from automation_context where key='retry_escalation'))->>'triage_run_id')::uuid;
select ok(public.complete_escalation_triage((select value from automation_context where key='retry_escalation'),
    (select value from automation_context where key='retry_run2'),'other','normal','Synthetic summary.','gemini','gemini-3.8-flash'),'Configured retry completes');
reset role;
insert into automation_context select 'retry_notification',id from public.escalation_notifications where escalation_id=(select value from automation_context where key='retry_escalation');
update auth.users set email_confirmed_at=null where id in ('a1000000-0000-4000-8000-000000000001','a1000000-0000-4000-8000-000000000002');
set local role service_role;
select is(public.begin_escalation_notification((select value from automation_context where key='retry_notification')),null::jsonb,'No verified recipients fails safely without sending');
reset role;
select is((select last_error_code from public.escalation_notifications where id=(select value from automation_context where key='retry_notification')),
    'notification_no_recipients','No-recipient safe error persisted');
-- Exercise exclusions and expired provider keys with a controlled state fixture.
alter table public.escalation_notifications disable trigger escalation_notifications_set_updated_at;
update public.escalation_notifications set updated_at=now()-interval '16 minutes',last_error_code='notification_delivery_unknown'
where id=(select value from automation_context where key='retry_notification');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalation_notifications(10)),0,'Unknown delivery never auto-retried');
reset role;
update public.escalation_notifications set last_error_code='notification_auth_failed' where id=(select value from automation_context where key='retry_notification');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalation_notifications(10)),0,'Notification auth failure excluded');
reset role;
update public.escalation_notifications set last_error_code='notification_configuration_invalid' where id=(select value from automation_context where key='retry_notification');
set local role service_role;
select is((select count(*)::integer from public.list_recoverable_escalation_notifications(10)),0,'Notification configuration failure excluded');
reset role;
update public.escalation_notifications set last_error_code='notification_rate_limited',first_delivery_started_at=now()-interval '25 hours'
where id=(select value from automation_context where key='retry_notification');
alter table public.escalation_notifications enable trigger escalation_notifications_set_updated_at;
set local role service_role;
select is(public.begin_escalation_notification((select value from automation_context where key='retry_notification')),null::jsonb,'Expired provider idempotency window never replayed');
reset role;
select is((select last_error_code from public.escalation_notifications where id=(select value from automation_context where key='retry_notification')),
    'notification_delivery_unknown','Expired replay retained for later manual review');
select is((select triage_status from public.escalations where id=(select value from automation_context where key='retry_escalation')),'completed','Notification failure never reverts triage');
select * from finish();
rollback;
