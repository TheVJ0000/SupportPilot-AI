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
insert into public.conversations(id,workspace_id,customer_session_id,status,human_requested_at,last_message_at,resolution_outcome,closed_at)
select ('b4000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case when position=5 then 'b2000000-0000-4000-8000-000000000002'::uuid else 'b2000000-0000-4000-8000-000000000001'::uuid end,
  ('b3000000-0000-4000-8000-'||lpad(position::text,12,'0'))::uuid,
  case position when 2 then 'human_requested' when 3 then 'closed' else 'open' end,
  case when position=2 then now() end,
  case when position in (4,5) then null else '2026-09-16T12:00:00Z'::timestamptz end,
  case when position=3 then 'closed_unresolved' else 'unresolved' end,
  case when position=3 then now() end
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


-- Extend populated fixtures with chunks and private storage objects for both tenants.
insert into public.knowledge_chunks(source_id,workspace_id,chunk_index,content,content_sha256,char_count,locator,embedding)
select id,workspace_id,0,'Synthetic chunk',repeat('a',64),15,'{"kind":"faq"}',
(select jsonb_agg(0.125) from generate_series(1,768))::text::extensions.vector
from public.knowledge_sources where id in ('b8000000-0000-4000-8000-000000000001','b8000000-0000-4000-8000-000000000005');
create temporary table matrix_files(workspace_id uuid,source_id uuid,storage_path text);
grant select,insert on matrix_files to authenticated;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000001';
insert into matrix_files select 'b2000000-0000-4000-8000-000000000001',source_id,storage_path
from public.begin_file_knowledge_source('b2000000-0000-4000-8000-000000000001','Matrix A','a.txt','text/plain',15);
reset role;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000004';
insert into matrix_files select 'b2000000-0000-4000-8000-000000000002',source_id,storage_path
from public.begin_file_knowledge_source('b2000000-0000-4000-8000-000000000002','Matrix B','b.txt','text/plain',15);
reset role;
insert into storage.objects(bucket_id,name) select 'knowledge-files',storage_path from matrix_files;

-- Every application table, not merely a prior phase's list.
select is((select array_agg(policyname::text order by policyname) from pg_policies
where schemaname='storage' and tablename='objects' and cmd in ('DELETE','ALL')
and roles && array['public','authenticated']::name[]),array['knowledge_files_delete_for_managers']::text[],
'No alternate permissive browser Storage DELETE/ALL policy can bypass tenant helper');
select ok(relrowsecurity,'Final table RLS: '||relname) from pg_class
where relnamespace='public'::regnamespace and relkind='r' order by relname;
select ok(not has_table_privilege('anon',oid,'SELECT,INSERT,UPDATE,DELETE'),'Anon table grants denied: '||relname)
from pg_class where relnamespace='public'::regnamespace and relkind='r' order by relname;
select ok(not exists(select 1 from pg_class where relnamespace='public'::regnamespace and relkind='r'
and (has_any_column_privilege('service_role',oid,'SELECT') or has_any_column_privilege('service_role',oid,'INSERT')
or has_any_column_privilege('service_role',oid,'UPDATE'))),'No inherited service-role column grants remain');
select ok(not has_table_privilege('service_role',oid,'SELECT,INSERT,UPDATE,DELETE'),'Server table grants RPC-only: '||relname)
from pg_class where relnamespace='public'::regnamespace and relkind='r' order by relname;
select ok(not has_table_privilege('authenticated',oid,'INSERT,UPDATE,DELETE'),'No broad browser mutations: '||relname)
from pg_class where relnamespace='public'::regnamespace and relkind='r' and relname not in ('profiles','workspaces') order by relname;
select ok(not has_column_privilege('authenticated','public.profiles','user_id','UPDATE'),'Profile identity immutable');
select ok(has_column_privilege('authenticated','public.profiles','display_name','UPDATE'),'Own profile display-name grant preserved');
select ok(not has_column_privilege('authenticated','public.workspaces','created_by','UPDATE'),'Workspace creator immutable');
select ok(not has_column_privilege('authenticated','public.knowledge_chunks','embedding','SELECT'),'Embedding column withheld');

-- Audit every final application SECURITY DEFINER, excluding extension/pgTAP functions.
select is((select array_agg(p.proname::text order by p.proname) from pg_proc p
where p.pronamespace='public'::regnamespace and not exists(select 1 from pg_depend d where d.objid=p.oid and d.deptype='e')
and has_function_privilege('service_role',p.oid,'EXECUTE')),
array['begin_customer_chat_turn','begin_escalation_notification','begin_escalation_triage','cleanup_customer_api_rate_limits',
'complete_customer_chat_turn','complete_escalation_notification','complete_escalation_triage','create_customer_chat_session',
'fail_customer_chat_turn','fail_escalation_notification','fail_escalation_triage','get_customer_chat_turn_result',
'get_customer_conversation','get_customer_conversation_history','list_recoverable_escalation_notifications',
'list_recoverable_escalations','request_customer_human_support','search_customer_chat_knowledge','set_customer_message_feedback']::text[],
'Exactly the nineteen necessary, narrow service-role RPCs remain');
select ok(p.proconfig @> array['search_path=""'],'Definer safe search_path: '||p.oid::regprocedure::text)
from pg_proc p where p.prosecdef and p.pronamespace in ('public'::regnamespace,'app_private'::regnamespace)
and not exists(select 1 from pg_depend d where d.objid=p.oid and d.deptype='e') order by p.oid::regprocedure::text;
select ok(not exists(select 1 from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE'),
'No PUBLIC execution: '||p.oid::regprocedure::text)
from pg_proc p where p.pronamespace in ('public'::regnamespace,'app_private'::regnamespace)
and not exists(select 1 from pg_depend d where d.objid=p.oid and d.deptype='e') order by p.oid::regprocedure::text;
select ok(pg_get_functiondef(p.oid) !~* '\yexecute\s','No dynamic application SQL: '||p.oid::regprocedure::text)
from pg_proc p where p.prosecdef and p.pronamespace in ('public'::regnamespace,'app_private'::regnamespace)
and not exists(select 1 from pg_depend d where d.objid=p.oid and d.deptype='e') order by p.oid::regprocedure::text;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000001';
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign workspaces invisible');
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000001'),1,'Actor 1: own workspaces expected access');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign workspace_members invisible');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 1: only own workspace_members row visible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign knowledge_sources invisible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000001'),5,'Actor 1: own knowledge_sources expected access');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign knowledge_chunks invisible');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 1: own knowledge_chunks expected access');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign workspace_chat_configs invisible');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 1: own workspace_chat_configs expected access');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign conversations invisible');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000001'),4,'Actor 1: own conversations expected access');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign conversation_turns invisible');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000001'),3,'Actor 1: own conversation_turns expected access');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign messages invisible');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000001'),6,'Actor 1: own messages expected access');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign message_citations invisible');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 1: own message_citations expected access');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign message_feedback invisible');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 1: own message_feedback expected access');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign escalations invisible');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 1: own escalations expected access');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign escalation_triage_runs invisible');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 1: own escalation_triage_runs expected access');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 1: foreign escalation_notifications invisible');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 1: own escalation_notifications expected access');
select is((select count(*)::integer from public.profiles where user_id='b1000000-0000-4000-8000-000000000004'),0,'Actor 1: other profile invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002')),0,'Actor 1: foreign storage invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000001')),1,'Actor 1: own knowledge storage readable');
select throws_ok('select * from public.customer_sessions','42501',null,'Actor 1: private customer_sessions unreadable');
select throws_ok('select * from public.customer_api_rate_limits','42501',null,'Actor 1: private customer_api_rate_limits unreadable');
select throws_ok($attack$select public.admin_get_conversation('b2000000-0000-4000-8000-000000000002','b4000000-0000-4000-8000-000000000005')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_get_escalation('b2000000-0000-4000-8000-000000000002','b5000000-0000-4000-8000-000000000002')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_conversation_resolution('b2000000-0000-4000-8000-000000000002','b4000000-0000-4000-8000-000000000005','open','unresolved','close_unresolved')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_escalation_status('b2000000-0000-4000-8000-000000000002','b5000000-0000-4000-8000-000000000002','open','closed')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_get_widget_config('b2000000-0000-4000-8000-000000000002')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_widget_enabled('b2000000-0000-4000-8000-000000000002',true,false)$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.begin_knowledge_extraction('b8000000-0000-4000-8000-000000000005')$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
select throws_ok($attack$select public.search_knowledge_chunks('b2000000-0000-4000-8000-000000000002',(select jsonb_agg(0.125) from generate_series(1,768)),'gemini','demo-model',768,8)$attack$,'42501',null,'Actor 1: cross-workspace RPC denied');
reset role;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000002';
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign workspaces invisible');
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000001'),1,'Actor 2: own workspaces expected access');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign workspace_members invisible');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 2: only own workspace_members row visible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign knowledge_sources invisible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000001'),5,'Actor 2: own knowledge_sources expected access');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign knowledge_chunks invisible');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 2: own knowledge_chunks expected access');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign workspace_chat_configs invisible');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 2: own workspace_chat_configs expected access');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign conversations invisible');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000001'),4,'Actor 2: own conversations expected access');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign conversation_turns invisible');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000001'),3,'Actor 2: own conversation_turns expected access');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign messages invisible');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000001'),6,'Actor 2: own messages expected access');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign message_citations invisible');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 2: own message_citations expected access');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign message_feedback invisible');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 2: own message_feedback expected access');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign escalations invisible');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 2: own escalations expected access');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign escalation_triage_runs invisible');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 2: own escalation_triage_runs expected access');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 2: foreign escalation_notifications invisible');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000001'),2,'Actor 2: own escalation_notifications expected access');
select is((select count(*)::integer from public.profiles where user_id='b1000000-0000-4000-8000-000000000004'),0,'Actor 2: other profile invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002')),0,'Actor 2: foreign storage invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000001')),1,'Actor 2: own knowledge storage readable');
select throws_ok('select * from public.customer_sessions','42501',null,'Actor 2: private customer_sessions unreadable');
select throws_ok('select * from public.customer_api_rate_limits','42501',null,'Actor 2: private customer_api_rate_limits unreadable');
select throws_ok($attack$select public.admin_get_conversation('b2000000-0000-4000-8000-000000000002','b4000000-0000-4000-8000-000000000005')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_get_escalation('b2000000-0000-4000-8000-000000000002','b5000000-0000-4000-8000-000000000002')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_conversation_resolution('b2000000-0000-4000-8000-000000000002','b4000000-0000-4000-8000-000000000005','open','unresolved','close_unresolved')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_escalation_status('b2000000-0000-4000-8000-000000000002','b5000000-0000-4000-8000-000000000002','open','closed')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_get_widget_config('b2000000-0000-4000-8000-000000000002')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.admin_set_widget_enabled('b2000000-0000-4000-8000-000000000002',true,false)$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.begin_knowledge_extraction('b8000000-0000-4000-8000-000000000005')$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
select throws_ok($attack$select public.search_knowledge_chunks('b2000000-0000-4000-8000-000000000002',(select jsonb_agg(0.125) from generate_series(1,768)),'gemini','demo-model',768,8)$attack$,'42501',null,'Actor 2: cross-workspace RPC denied');
reset role;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000003';
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign workspaces invisible');
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000001'),1,'Actor 3: own workspaces expected access');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign workspace_members invisible');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 3: only own workspace_members row visible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign knowledge_sources invisible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000001'),5,'Actor 3: own knowledge_sources expected access');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign knowledge_chunks invisible');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 3: own knowledge_chunks expected access');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign workspace_chat_configs invisible');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000001'),1,'Actor 3: own workspace_chat_configs expected access');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign conversations invisible');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own conversations expected access');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign conversation_turns invisible');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own conversation_turns expected access');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign messages invisible');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own messages expected access');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign message_citations invisible');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own message_citations expected access');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign message_feedback invisible');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own message_feedback expected access');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign escalations invisible');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own escalations expected access');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign escalation_triage_runs invisible');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own escalation_triage_runs expected access');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000002'),0,'Actor 3: foreign escalation_notifications invisible');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Actor 3: own escalation_notifications expected access');
select is((select count(*)::integer from public.profiles where user_id='b1000000-0000-4000-8000-000000000004'),0,'Actor 3: other profile invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002')),0,'Actor 3: foreign storage invisible');
select is((select count(*)::integer from storage.objects where name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000001')),1,'Actor 3: own knowledge storage readable');
select throws_ok('select * from public.customer_sessions','42501',null,'Actor 3: private customer_sessions unreadable');
select throws_ok('select * from public.customer_api_rate_limits','42501',null,'Actor 3: private customer_api_rate_limits unreadable');
reset role;
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000004';
select is((select count(id)::integer from public.workspaces where id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: workspaces invisible');
select is((select count(user_id)::integer from public.workspace_members where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: workspace_members invisible');
select is((select count(id)::integer from public.knowledge_sources where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: knowledge_sources invisible');
select is((select count(id)::integer from public.knowledge_chunks where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: knowledge_chunks invisible');
select is((select count(workspace_id)::integer from public.workspace_chat_configs where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: workspace_chat_configs invisible');
select is((select count(id)::integer from public.conversations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: conversations invisible');
select is((select count(id)::integer from public.conversation_turns where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: conversation_turns invisible');
select is((select count(id)::integer from public.messages where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: messages invisible');
select is((select count(id)::integer from public.message_citations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: message_citations invisible');
select is((select count(id)::integer from public.message_feedback where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: message_feedback invisible');
select is((select count(id)::integer from public.escalations where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: escalations invisible');
select is((select count(id)::integer from public.escalation_triage_runs where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: escalation_triage_runs invisible');
select is((select count(id)::integer from public.escalation_notifications where workspace_id='b2000000-0000-4000-8000-000000000001'),0,'Non-member: escalation_notifications invisible');
reset role;
set local role anon;
select throws_ok('select * from public.profiles','42501',null,'Anon profiles read denied');
select throws_ok('select * from public.workspaces','42501',null,'Anon workspaces read denied');
select throws_ok('select * from public.workspace_members','42501',null,'Anon workspace_members read denied');
select throws_ok('select * from public.knowledge_sources','42501',null,'Anon knowledge_sources read denied');
select throws_ok('select * from public.knowledge_chunks','42501',null,'Anon knowledge_chunks read denied');
select throws_ok('select * from public.workspace_chat_configs','42501',null,'Anon workspace_chat_configs read denied');
select throws_ok('select * from public.conversations','42501',null,'Anon conversations read denied');
select throws_ok('select * from public.conversation_turns','42501',null,'Anon conversation_turns read denied');
select throws_ok('select * from public.messages','42501',null,'Anon messages read denied');
select throws_ok('select * from public.message_citations','42501',null,'Anon message_citations read denied');
select throws_ok('select * from public.message_feedback','42501',null,'Anon message_feedback read denied');
select throws_ok('select * from public.escalations','42501',null,'Anon escalations read denied');
select throws_ok('select * from public.escalation_triage_runs','42501',null,'Anon escalation_triage_runs read denied');
select throws_ok('select * from public.escalation_notifications','42501',null,'Anon escalation_notifications read denied');
select throws_ok('select * from public.customer_sessions','42501',null,'Anon customer_sessions read denied');
select throws_ok('select * from public.customer_api_rate_limits','42501',null,'Anon customer_api_rate_limits read denied');
reset role;
set local role service_role;
select throws_ok($attack$select public.get_customer_conversation_history('b4000000-0000-4000-8000-000000000005',lpad('1',64,'0'))$attack$,'28000',null,'Customer A cannot operate on B');
select throws_ok($attack$select public.begin_customer_chat_turn('b4000000-0000-4000-8000-000000000005',lpad('1',64,'0'),gen_random_uuid(),'Synthetic attack')$attack$,'28000',null,'Customer A cannot operate on B');
select throws_ok($attack$select public.set_customer_message_feedback('b4000000-0000-4000-8000-000000000005',lpad('1',64,'0'),'b7000000-0000-4000-8000-000000000008','positive')$attack$,'28000',null,'Customer A cannot operate on B');
select throws_ok($attack$select public.request_customer_human_support('b4000000-0000-4000-8000-000000000005',lpad('1',64,'0'))$attack$,'28000',null,'Customer A cannot operate on B');
reset role;
select is((select count(*)::integer from public.customer_api_rate_limits where subject_id='b3000000-0000-4000-8000-000000000005'),0,'Rejected customer attacks cannot affect B limiter identity');
select is((select status from public.conversations where id='b4000000-0000-4000-8000-000000000005'),'open','B state preserved');
set local role authenticated; set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000001';
select is_empty($attack$update public.profiles set display_name='Synthetic attack'
where user_id='b1000000-0000-4000-8000-000000000004' returning user_id$attack$,'Owner A cannot update profile B');
select is_empty($attack$update public.workspaces set name='Synthetic attack'
where id='b2000000-0000-4000-8000-000000000002' returning id$attack$,'Owner A cannot update workspace B');
select is_empty($attack$delete from public.workspaces where id='b2000000-0000-4000-8000-000000000002'
returning id$attack$,'Owner A cannot delete workspace B');
select throws_ok($attack$insert into storage.objects(bucket_id,name) select 'knowledge-files',storage_path||'.attack'
from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002'$attack$,'42501',null,'Owner A cannot insert into B Storage namespace');
select throws_ok($attack$delete from storage.objects where bucket_id='knowledge-files'
and name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002') returning id$attack$,'42501',null,'Direct SQL Storage deletion denied without bypassing platform guard');
select ok(not app_private.can_delete_knowledge_object((select storage_path from matrix_files
where workspace_id='b2000000-0000-4000-8000-000000000002')),'Storage API deletion policy denies owner A for B');
select is_empty($attack$update storage.objects set name=name||'.attack' where bucket_id='knowledge-files'
and name=(select storage_path from matrix_files where workspace_id='b2000000-0000-4000-8000-000000000002') returning id$attack$,'Owner A cannot update B Storage object');
set local request.jwt.claim.sub='b1000000-0000-4000-8000-000000000002';
select ok(not app_private.can_delete_knowledge_object((select storage_path from matrix_files
where workspace_id='b2000000-0000-4000-8000-000000000002')),'Storage API deletion policy denies admin A for B');
reset role;
select ok(not has_function_privilege('service_role','app_private.consume_customer_rate_limit(text,uuid)','EXECUTE'),'No arbitrary server limiter scope/subject');
select * from finish();
rollback;
