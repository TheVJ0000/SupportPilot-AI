begin;
set local timezone='UTC';
select no_plan();
insert into auth.users(id,email,raw_user_meta_data) values
('d1000000-0000-4000-8000-000000000001','lifecycle-1@example.test','{}'),
('d1000000-0000-4000-8000-000000000002','lifecycle-2@example.test','{}'),
('d1000000-0000-4000-8000-000000000003','lifecycle-3@example.test','{}'),
('d1000000-0000-4000-8000-000000000004','lifecycle-4@example.test','{}');
insert into public.workspaces(id,name,created_by) values
('d2000000-0000-4000-8000-000000000001','Lifecycle A','d1000000-0000-4000-8000-000000000001'),('d2000000-0000-4000-8000-000000000002','Lifecycle B','d1000000-0000-4000-8000-000000000004');
insert into public.workspace_members(workspace_id,user_id,role) values
('d2000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000001','owner'),('d2000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000002','admin'),('d2000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000003','member'),('d2000000-0000-4000-8000-000000000002','d1000000-0000-4000-8000-000000000004','owner');
insert into public.customer_sessions(id,workspace_id,chat_public_id,token_hash,expires_at)
select ('d3000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
config.workspace_id,config.public_id,lpad(position::text,64,'0'),now()+interval '1 day'
from generate_series(1,5) series(position) join public.workspace_chat_configs config
on config.workspace_id=case when position=4 then 'd2000000-0000-4000-8000-000000000002'::uuid else 'd2000000-0000-4000-8000-000000000001'::uuid end;
insert into public.conversations(id,workspace_id,customer_session_id,status,human_requested_at,resolution_outcome,closed_at)
select ('d4000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
case when position=4 then 'd2000000-0000-4000-8000-000000000002'::uuid else 'd2000000-0000-4000-8000-000000000001'::uuid end,
('d3000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
case when position=2 then 'human_requested' when position=5 then 'closed' else 'open' end,
case when position=2 then now() end,
case when position=5 then 'closed_unresolved' else 'unresolved' end,
case when position=5 then now() end
from generate_series(1,5) series(position);
insert into public.escalations(id,workspace_id,conversation_id,trigger_reason) values
('d5000000-0000-4000-8000-000000000001','d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','insufficient_evidence'),
('d5000000-0000-4000-8000-000000000002','d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000002','human_requested'),
('d5000000-0000-4000-8000-000000000004','d2000000-0000-4000-8000-000000000002','d4000000-0000-4000-8000-000000000004','insufficient_evidence');
insert into public.conversation_turns(id,workspace_id,conversation_id,client_message_id,status)
values ('d6000000-0000-4000-8000-000000000003','d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000003',gen_random_uuid(),'processing');
insert into public.messages(id,workspace_id,conversation_id,turn_id,role,content,answer_status)
values ('d7000000-0000-4000-8000-000000000003','d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000003','d6000000-0000-4000-8000-000000000003','assistant','Synthetic grounded answer.','answered');
set local role authenticated;
set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','open','unresolved','resolve')->'conversation'->>'resolution_outcome','resolved','Owner explicitly resolves an open conversation');
reset role; set local role service_role;
select throws_ok($$select public.begin_customer_chat_turn('d4000000-0000-4000-8000-000000000001',lpad('1',64,'0'),gen_random_uuid(),'Synthetic next question.')$$,'55000',null,'Closed conversations reject new customer turns');
reset role; set local role authenticated; set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select ok((select status='closed' and resolved_at=closed_at and resolved_at is not null from public.conversations where id='d4000000-0000-4000-8000-000000000001'),'Resolved closure has consistent timestamps');
select is((select status from public.escalations where id='d5000000-0000-4000-8000-000000000001'),'open','Conversation resolution does not rewrite escalation');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','closed','resolved','reopen')->'conversation'->>'status','open','Ordinary resolved conversation reopens to open');
reset role; set local role service_role;
select lives_ok($$select public.begin_customer_chat_turn('d4000000-0000-4000-8000-000000000001',lpad('1',64,'0'),gen_random_uuid(),'Synthetic reopened question.')$$,'Reopened ordinary conversations accept customer turns with the existing session');
reset role; set local role authenticated; set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select ok((select resolution_outcome='unresolved' and resolved_at is null and closed_at is null from public.conversations where id='d4000000-0000-4000-8000-000000000001'),'Reopen clears outcome timestamps');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','open','unresolved','close_unresolved')->'conversation'->>'resolution_outcome','closed_unresolved','Close unresolved is not successful resolution');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','closed','closed_unresolved','reopen')->'conversation'->>'status','open','Closed unresolved can reopen');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000002','human_requested','unresolved','resolve')->'conversation'->>'status','closed','Human-requested conversation can resolve');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000002','closed','resolved','reopen')->'conversation'->>'status','human_requested','Human history restores paused AI operational state');
reset role; set local role service_role;
select throws_ok($$select public.begin_customer_chat_turn('d4000000-0000-4000-8000-000000000002',lpad('2',64,'0'),gen_random_uuid(),'Synthetic paused question.')$$,'55000',null,'Reopened human history still rejects AI customer turns');
reset role; set local role authenticated; set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000002','human_requested','unresolved','close_unresolved')->'conversation'->>'resolution_outcome','closed_unresolved','Human-requested conversations can close without resolution');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000002','closed','closed_unresolved','reopen')->'conversation'->>'status','human_requested','Unresolved closure also preserves human history when reopened');
select ok((select human_requested_at is not null and resolved_at is null and closed_at is null from public.conversations where id='d4000000-0000-4000-8000-000000000002'),'Reopen retains the historical human request');
set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000002';
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000002','open','in_progress')->'escalation'->>'status','in_progress','Admin may manage escalations');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000002','in_progress','open')->'escalation'->>'status','open','Admin may return escalation to queue');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','open','unresolved','resolve')->'conversation'->>'resolution_outcome','resolved','Admin may resolve');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','closed','resolved','reopen')->'conversation'->>'status','open','Admin may reopen');
set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''closed'',''resolved'',''reopen'')','40001',null,'Stale conversation status rejected');
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''resolved'',''resolve'')','40001',null,'Stale conversation outcome rejected');
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''reopen'')','55000',null,'Invalid reopen transition rejected');
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''delete'')','55000',null,'Arbitrary action rejected');
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000004'',''open'',''unresolved'',''resolve'')','P0002',null,'Cross-workspace conversation hidden');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000004'',''open'',''resolved'')','P0002',null,'Cross-workspace escalation hidden');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','in_progress')->'escalation'->>'status','in_progress','Escalation open to in_progress');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','in_progress','open')->'escalation'->>'status','open','Escalation in_progress to open');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','resolved')->'escalation'->>'status','resolved','Escalation open to resolved');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','resolved','open')->'escalation'->>'status','open','Escalation resolved to open');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','in_progress')->'escalation'->>'status','in_progress','Escalation open to in_progress');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','in_progress','resolved')->'escalation'->>'status','resolved','Escalation in_progress to resolved');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','resolved','closed')->'escalation'->>'status','closed','Escalation resolved to closed');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','closed','open')->'escalation'->>'status','open','Escalation closed to open');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','closed')->'escalation'->>'status','closed','Escalation open to closed');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','closed','open')->'escalation'->>'status','open','Escalation closed to open');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','in_progress')->'escalation'->>'status','in_progress','Escalation open to in_progress');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','in_progress','closed')->'escalation'->>'status','closed','Escalation in_progress to closed');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','closed','open')->'escalation'->>'status','open','Escalation closed to open');
select ok((select status='open' and resolution_outcome='unresolved' from public.conversations where id='d4000000-0000-4000-8000-000000000001'),'Escalation actions never rewrite conversation');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''open'')','55000',null,'Identical escalation transition rejected');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''paused'')','55000',null,'Arbitrary escalation status rejected');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''in_progress'',''resolved'')','40001',null,'Stale escalation status rejected');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','open','closed')->'escalation'->>'status','closed','Prepare terminal escalation');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''closed'',''resolved'')','55000',null,'Closed to resolved is illegal');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''closed'',''in_progress'')','55000',null,'Closed to in_progress is illegal');
select is(public.admin_set_escalation_status('d2000000-0000-4000-8000-000000000001','d5000000-0000-4000-8000-000000000001','closed','open')->'escalation'->>'status','open','Reopen terminal escalation');
set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000003';
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''resolve'')','42501',null,'Member cannot resolve');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''in_progress'')','42501',null,'Member cannot manage escalation');
set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000004';
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''resolve'')','42501',null,'Nonmember cannot resolve');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''in_progress'')','42501',null,'Nonmember cannot manage escalation');
set local request.jwt.claim.sub='';
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''resolve'')','28000',null,'Conversation mutation requires auth.uid');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''in_progress'')','28000',null,'Escalation mutation requires auth.uid');
reset role; set local role anon;
select throws_ok('select public.admin_set_conversation_resolution(''d2000000-0000-4000-8000-000000000001'',''d4000000-0000-4000-8000-000000000001'',''open'',''unresolved'',''resolve'')','42501',null,'Anonymous execute revoked');
select throws_ok('select public.admin_set_escalation_status(''d2000000-0000-4000-8000-000000000001'',''d5000000-0000-4000-8000-000000000001'',''open'',''in_progress'')','42501',null,'Anonymous escalation execute revoked');
reset role;
select ok(not has_table_privilege('authenticated','public.conversations','UPDATE'),'conversations has no general browser UPDATE grant');
select ok(not has_table_privilege('authenticated','public.escalations','UPDATE'),'escalations has no general browser UPDATE grant');
select ok(not has_function_privilege('service_role','public.admin_set_conversation_resolution(uuid,uuid,text,text,text)','EXECUTE') and not has_function_privilege('service_role','public.admin_set_escalation_status(uuid,uuid,text,text)','EXECUTE'),'Admin writes do not grant service-role execution');
select throws_ok('update public.conversations set status=''open'',resolution_outcome=''resolved'',resolved_at=now(),closed_at=now() where id=''d4000000-0000-4000-8000-000000000001''','23514',null,'Impossible conversation state rejected');
select throws_ok('update public.conversations set status=''closed'',resolution_outcome=''unresolved'' where id=''d4000000-0000-4000-8000-000000000001''','23514',null,'Impossible conversation state rejected');
select throws_ok('update public.conversations set status=''closed'',resolution_outcome=''resolved'',resolved_at=null,closed_at=now() where id=''d4000000-0000-4000-8000-000000000001''','23514',null,'Impossible conversation state rejected');
select throws_ok('update public.conversations set status=''closed'',resolution_outcome=''closed_unresolved'',resolved_at=now(),closed_at=now() where id=''d4000000-0000-4000-8000-000000000001''','23514',null,'Impossible conversation state rejected');
select throws_ok('update public.conversations set status=''human_requested'',resolution_outcome=''unresolved'',closed_at=now() where id=''d4000000-0000-4000-8000-000000000001''','23514',null,'Impossible conversation state rejected');
set local role authenticated; set local request.jwt.claim.sub='d1000000-0000-4000-8000-000000000001';
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'total_conversations','4','Exact workspace conversation total');
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'resolved_conversations','0','AI answered without admin resolution is not resolved');
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'closed_unresolved_conversations','1','Exact closed-unresolved count');
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'ai_answered_conversations','1','AI answer coverage remains distinct');
select is(public.admin_set_conversation_resolution('d2000000-0000-4000-8000-000000000001','d4000000-0000-4000-8000-000000000001','open','unresolved','resolve')->'conversation'->>'resolution_outcome','resolved','Resolve previously unanswered conversation');
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'resolved_conversations','1','Explicit resolution increments exact metric');
select is(public.admin_dashboard_snapshot('d2000000-0000-4000-8000-000000000001')->'metrics'->>'ai_answered_conversations','1','Explicit resolution does not invent an AI answer');
select * from finish();
rollback;
