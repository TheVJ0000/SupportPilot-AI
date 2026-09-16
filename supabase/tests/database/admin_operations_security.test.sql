begin;
set local timezone='UTC';
select no_plan();

-- Only synthetic records; transaction rollback keeps these out of the application.
insert into auth.users (id,email,raw_user_meta_data) values
('b1000000-0000-4000-8000-000000000001','operations-owner@example.test','{}'),
('b1000000-0000-4000-8000-000000000002','operations-admin@example.test','{}'),
('b1000000-0000-4000-8000-000000000003','operations-member@example.test','{}'),
('b1000000-0000-4000-8000-000000000004','operations-outsider@example.test','{}');
insert into public.workspaces(id,name,created_by) values
('b2000000-0000-4000-8000-000000000001','Operations A','b1000000-0000-4000-8000-000000000001'),
('b2000000-0000-4000-8000-000000000002','Operations B','b1000000-0000-4000-8000-000000000004');
insert into public.workspace_members(workspace_id,user_id,role) values
('b2000000-0000-4000-8000-000000000001','b1000000-0000-4000-8000-000000000001','owner'),
('b2000000-0000-4000-8000-000000000001','b1000000-0000-4000-8000-000000000002','admin'),
('b2000000-0000-4000-8000-000000000001','b1000000-0000-4000-8000-000000000003','member'),
('b2000000-0000-4000-8000-000000000002','b1000000-0000-4000-8000-000000000004','owner');
insert into public.customer_sessions(id,workspace_id,chat_public_id,token_hash,expires_at)
select ('b3000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case when position=5 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end,
  config.public_id,lpad(position::text,64,'0'),now()+interval '1 day'
from generate_series(1,5) as series(position) join public.workspace_chat_configs as config
on config.workspace_id=case when position=5 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end;
insert into public.conversations(id,workspace_id,customer_session_id,status,human_requested_at,last_message_at)
select ('b4000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case when position=5 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end,
  ('b3000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case position when 2 then 'human_requested' when 3 then 'closed' else 'open' end,
  case when position=2 then now() end,
  case when position in (4,5) then null else '2026-09-16T12:00:00Z'::timestamptz end
from generate_series(1,5) as series(position);
insert into public.conversation_turns(id,workspace_id,conversation_id,client_message_id,status,created_at)
select ('b6000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case when position=4 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end,
  case when position in (1,2) then 'b4000000-0000-4000-8000-000000000001'::uuid when position=3 then 'b4000000-0000-4000-8000-000000000002'::uuid else 'b4000000-0000-4000-8000-000000000005'::uuid end,
  gen_random_uuid(),'processing','2026-09-16T10:00:00Z'::timestamptz+position*interval '1 minute'
from generate_series(1,4) as series(position);
insert into public.messages(id,workspace_id,conversation_id,turn_id,role,content,answer_status,created_at)
select ('b7000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  turn.workspace_id,turn.conversation_id,turn.id,
  case when position%2=1 then 'customer' else 'assistant' end,
  case when position%2=1 then 'Synthetic question.' else 'Synthetic evidence response.' end,
  case when position%2=1 then null when position<=4 then 'answered' else 'insufficient_evidence' end,
  -- Deliberately reversed message timestamps within a turn: turn/role order is authoritative.
  turn.created_at+case when position%2=1 then interval '2 seconds' else interval '1 second' end
from generate_series(1,8) as series(position) join public.conversation_turns as turn
on turn.id=('b6000000-0000-4000-8000-'||lpad(((position+1)/2)::text,12,'0'))::uuid;
insert into public.message_feedback(workspace_id,conversation_id,message_id,rating) values
('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000001','b7000000-0000-4000-8000-000000000002','positive'),
('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000001','b7000000-0000-4000-8000-000000000004','negative'),
('b2000000-0000-4000-8000-000000000002','b4000000-0000-4000-8000-000000000005','b7000000-0000-4000-8000-000000000008','negative');
insert into public.message_citations(workspace_id,message_id,ordinal,source_id,source_title,source_type,chunk_index,locator) values
('b2000000-0000-4000-8000-000000000001','b7000000-0000-4000-8000-000000000002',1,'b8000000-0000-4000-8000-000000000001','Synthetic FAQ','faq',0,'{"kind":"faq"}'),
('b2000000-0000-4000-8000-000000000002','b7000000-0000-4000-8000-000000000008',1,'b8000000-0000-4000-8000-000000000002','Other private title','file',0,'{"kind":"pdf","page_start":1,"page_end":2}');
-- The insufficient-evidence trigger creates these rows before classification.
update public.escalations set id='b5000000-0000-4000-8000-000000000001',triage_status='completed',triage_attempts=2,
category='billing',priority='high',summary='Synthetic high-priority summary.',triage_provider='gemini',triage_model='demo-model',triaged_at=now()
where conversation_id='b4000000-0000-4000-8000-000000000002';
update public.escalations set id='b5000000-0000-4000-8000-000000000002',triage_status='completed',triage_attempts=1,
category='other',priority='low',summary='Other workspace summary.',triage_provider='gemini',triage_model='demo-model',triaged_at=now()
where conversation_id='b4000000-0000-4000-8000-000000000005';
insert into public.escalations(id,workspace_id,conversation_id,trigger_reason,status,triage_status,triage_attempts,category,priority,summary,triage_provider,triage_model,triaged_at) values
('b5000000-0000-4000-8000-000000000003','b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000003','human_requested','in_progress','completed',1,'technical','urgent','Synthetic urgent summary.','gemini','demo-model',now());
insert into public.escalation_triage_runs(workspace_id,escalation_id,attempt_number,status,provider,model,tool_name,safe_error_code,started_at,completed_at) values
('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000001',1,'failed',null,null,null,'triage_rate_limited',now(),now()),
('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000001',2,'completed','gemini','demo-model','create_escalation',null,now(),now()),
('b2000000-0000-4000-8000-000000000002','b5000000-0000-4000-8000-000000000002',1,'completed','gemini','other-model','create_escalation',null,now(),now());
insert into public.knowledge_sources(id,workspace_id,created_by,source_type,title,status,faq_question,faq_answer,processing_stage,indexed_at,embedding_provider,embedding_model,embedding_dimension)
select ('b8000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
case when position=5 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end,
'b1000000-0000-4000-8000-000000000001','faq','Synthetic knowledge',
case position when 1 then 'ready' when 2 then 'processing' when 3 then 'failed' when 4 then 'pending' else 'ready' end,
'Synthetic question?','Synthetic answer.',case when position=2 then 'indexing' end,
case when position in (1,5) then now() end,case when position in (1,5) then 'gemini' end,
case when position in (1,5) then 'demo-model' end,case when position in (1,5) then 768 end
from generate_series(1,5) as series(position);

create function pg_temp.operations_calls(workspace uuid) returns table(query text) language sql as $$
select format('select public.admin_dashboard_snapshot(%L)',workspace) union all
select format('select public.admin_list_conversations(%L)',workspace) union all
select format('select public.admin_get_conversation(%L,%L)',workspace,'b4000000-0000-4000-8000-000000000001') union all
select format('select public.admin_list_escalations(%L)',workspace) union all
select format('select public.admin_get_escalation(%L,%L)',workspace,'b5000000-0000-4000-8000-000000000001');
$$;
set local role authenticated;
set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000001';
select lives_ok(query,'Owner allowed: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000001');
select throws_ok(query,'42501',null,'Cross-workspace request denied: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000002');
select is(public.admin_dashboard_snapshot('b2000000-0000-4000-8000-000000000001')->'metrics',
'{"total_conversations":4,"ai_answered_conversations":1,"insufficient_evidence_conversations":1,"escalated_conversations":2,"human_requested_conversations":1,"positive_feedback_count":1,"negative_feedback_count":1,"open_escalations":1,"high_priority_escalations":1,"urgent_escalations":1,"knowledge_ready":1,"knowledge_processing":1,"knowledge_failed":1}'::jsonb,'Exact tenant-scoped metrics; repeated AI answers count once; open excludes in_progress; pending knowledge excluded');
select is(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',1)->'items'->0->>'id','b4000000-0000-4000-8000-000000000003','Timestamp ties ordered by descending UUID');
select is(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',1)->'next_cursor',
'{"time":"2026-09-16T12:00:00+00:00","id":"b4000000-0000-4000-8000-000000000003"}'::jsonb,'Cursor points at last returned record');
select is(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',1,'all','2026-09-16T12:00:00Z','b4000000-0000-4000-8000-000000000003')->'items'->0->>'id','b4000000-0000-4000-8000-000000000002','Second keyset page does not duplicate');
select is(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',1,'all','2026-09-16T12:00:00Z','b4000000-0000-4000-8000-000000000001')->'items'->0->>'id','b4000000-0000-4000-8000-000000000004','Null activity appears after all non-null activity');
select is(jsonb_array_length(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',25,'all',null,'b4000000-0000-4000-8000-000000000004')->'items'),0,'Null bucket cursor terminates');
select is(jsonb_array_length(public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',25,'human_requested')->'items'),1,'Conversation status filter');
select is(public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000001')->'messages'->0->>'role','customer','Customer first despite reversed timestamps');
select is(public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000001')->'messages'->1->>'feedback','positive','Feedback belongs to the assistant message');
select is(public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000001')->'messages'->1->'citations',
'[{"source_id":"b8000000-0000-4000-8000-000000000001","source_title":"Synthetic FAQ","source_type":"faq","chunk_index":0,"locator":{"kind":"faq"}}]'::jsonb,'Safe exact citation snapshot');
select is(public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000002')->'escalation'->>'id','b5000000-0000-4000-8000-000000000001','Correct escalation association');
select is(public.admin_get_escalation('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000001')->'audit_runs'->0->>'attempt_number','2','Newest audit attempt first');
select is(jsonb_array_length(public.admin_get_escalation('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000001')->'audit_runs'),2,'No other workspace audit records');
select is(public.admin_get_escalation('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000001')->'notification',
(select jsonb_build_object('status',status,'attempts',attempts,'provider',provider,'last_error_code',last_error_code,'sent_at',sent_at,'created_at',created_at,'updated_at',updated_at) from public.escalation_notifications where escalation_id='b5000000-0000-4000-8000-000000000001'),'Exact notification shape excludes provider_message_id and recipients');
select is(public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',25,'open','completed','high','insufficient_evidence')->'items'->0->>'id','b5000000-0000-4000-8000-000000000001','All escalation enum filters applied');
select is(public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',1)->'items'->0->>'id','b5000000-0000-4000-8000-000000000003','Escalation ties use descending UUID');
select is(public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',1,'all','all','all','all',
  (public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',1)->'next_cursor'->>'time')::timestamptz,
  (public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',1)->'next_cursor'->>'id')::uuid)->'items'->0->>'id','b5000000-0000-4000-8000-000000000001','Escalation second page');
select throws_ok($$select public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','b4000000-0000-4000-8000-000000000005')$$,'P0002',null,'Foreign conversation is indistinguishable from absent record');
select throws_ok($$select public.admin_get_escalation('b2000000-0000-4000-8000-000000000001','b5000000-0000-4000-8000-000000000002')$$,'P0002',null,'Foreign escalation is indistinguishable from absent record');
select throws_ok($$select public.admin_get_conversation('b2000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000000')$$,'P0002',null,'Absent conversation response matches foreign record');
select throws_ok($$select public.admin_get_escalation('b2000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000000')$$,'P0002',null,'Absent escalation response matches foreign record');
select throws_ok(query,'22023',null,'Bounded parameters rejected') from unnest(array[
$$select public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',0)$$,
$$select public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',51)$$,
$$select public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',25,'SQL')$$,
$$select public.admin_list_conversations('b2000000-0000-4000-8000-000000000001',25,'all',now(),null)$$,
$$select public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',51)$$,
$$select public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',25,'all','all','SQL')$$,
$$select public.admin_list_escalations('b2000000-0000-4000-8000-000000000001',25,'all','all','all','all',null,gen_random_uuid())$$
]) as queries(query);
select is((select count(*)::integer from public.messages),6,'Owner RLS excludes tenant B messages');
select is((select count(*)::integer from public.conversations),4,'Owner conversation RLS');
select is((select count(*)::integer from public.conversation_turns),3,'Owner turn RLS');
select is((select count(*)::integer from public.message_citations),1,'Owner citation RLS');
select is((select count(*)::integer from public.message_feedback),2,'Owner feedback RLS');
select is((select count(*)::integer from public.escalations),2,'Owner escalation RLS');
select is((select count(*)::integer from public.escalation_triage_runs),2,'Owner audit RLS');
select is((select count(*)::integer from public.escalation_notifications),2,'Owner reads workspace notification records');
set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000002';
select lives_ok(query,'Admin allowed: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000001');
select is((select count(*)::integer from public.messages),6,'Admin RLS includes own workspace messages');
select is((select count(*)::integer from public.conversations),4,'Admin conversation RLS');
select is((select count(*)::integer from public.conversation_turns),3,'Admin turn RLS');
select is((select count(*)::integer from public.message_citations),1,'Admin citation RLS');
select is((select count(*)::integer from public.message_feedback),2,'Admin feedback RLS');
select is((select count(*)::integer from public.escalations),2,'Admin escalation RLS');
select is((select count(*)::integer from public.escalation_triage_runs),2,'Admin audit RLS');
select is((select count(*)::integer from public.escalation_notifications),2,'Admin notification RLS');
set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000003';
select throws_ok(query,'42501',null,'Ordinary member denied: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000001');
select is((select count(*)::integer from public.conversations),0,'Member conversations denied');
select is((select count(*)::integer from public.conversation_turns),0,'Member turns denied');
select is((select count(*)::integer from public.messages),0,'Member messages denied');
select is((select count(*)::integer from public.message_citations),0,'Member citations denied');
select is((select count(*)::integer from public.message_feedback),0,'Member feedback denied');
select is((select count(*)::integer from public.escalations),0,'Member escalations denied');
select is((select count(*)::integer from public.escalation_triage_runs),0,'Member audits denied');
select is((select count(*)::integer from public.escalation_notifications),0,'Member notifications denied');
select is((select count(*)::integer from public.knowledge_sources),4,'Member Knowledge Base reads preserved');
set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000004';
select throws_ok(query,'42501',null,'Nonmember denied: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000001');
reset role;
set local role anon;
select throws_ok(query,'42501',null,'Anonymous role denied: '||query) from pg_temp.operations_calls('b2000000-0000-4000-8000-000000000001');
reset role;
select ok(bool_and(prosecdef and proconfig @> array['search_path=""']), 'Every public admin read is security-definer with empty search_path')
from pg_proc where pronamespace='public'::regnamespace and proname in ('admin_dashboard_snapshot','admin_list_conversations','admin_get_conversation','admin_list_escalations','admin_get_escalation');
select ok(bool_and(has_function_privilege('authenticated',oid,'EXECUTE') and not has_function_privilege('anon',oid,'EXECUTE') and not has_function_privilege('service_role',oid,'EXECUTE')),'Admin RPCs granted only to authenticated')
from pg_proc where pronamespace='public'::regnamespace and proname in ('admin_dashboard_snapshot','admin_list_conversations','admin_get_conversation','admin_list_escalations','admin_get_escalation');
select ok(not has_function_privilege('authenticated','app_private.admin_escalation_item(public.escalations)','EXECUTE'),'Shape builder is private');
select * from finish();
rollback;
