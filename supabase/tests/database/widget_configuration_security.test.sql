begin;
select no_plan();
-- Synthetic roles and workspaces; no passwords or permanent fixture records.
insert into auth.users(id,email,raw_user_meta_data) values
('e1000000-0000-4000-8000-000000000001','widget-owner@example.test','{}'),
('e1000000-0000-4000-8000-000000000002','widget-admin@example.test','{}'),
('e1000000-0000-4000-8000-000000000003','widget-member@example.test','{}'),
('e1000000-0000-4000-8000-000000000004','widget-outsider@example.test','{}');
insert into public.workspaces(id,name,created_by) values
('e2000000-0000-4000-8000-000000000001','Widget A','e1000000-0000-4000-8000-000000000001'),
('e2000000-0000-4000-8000-000000000002','Widget B','e1000000-0000-4000-8000-000000000004');
insert into public.workspace_members(workspace_id,user_id,role) values
('e2000000-0000-4000-8000-000000000001','e1000000-0000-4000-8000-000000000001','owner'),
('e2000000-0000-4000-8000-000000000001','e1000000-0000-4000-8000-000000000002','admin'),
('e2000000-0000-4000-8000-000000000001','e1000000-0000-4000-8000-000000000003','member'),
('e2000000-0000-4000-8000-000000000002','e1000000-0000-4000-8000-000000000004','owner');
create temporary table widget_fixture as select public_id from public.workspace_chat_configs
where workspace_id='e2000000-0000-4000-8000-000000000001';
grant select on widget_fixture to authenticated,service_role;
set local role authenticated;
set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000001';
select is(public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001'),
jsonb_build_object('workspace_id','e2000000-0000-4000-8000-000000000001','workspace_name','Widget A','public_id',(select public_id from widget_fixture),'is_enabled',true),'Owner gets only safe target-workspace config');
select is(public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,false)->>'is_enabled','false','Owner disables widget');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,true)$$,'40001',null,'Stale expected state rejected');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',false,false)$$,'55000',null,'Identical transition rejected');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',false,null)$$,'22023',null,'Null requested state rejected');
select is(public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')->>'public_id',(select public_id::text from widget_fixture),'Toggle never rotates public ID');
reset role; set local role service_role;
select throws_ok($$select public.create_customer_chat_session((select public_id from widget_fixture),repeat('a',64),now()+interval '1 day')$$,'22023',null,'Disabled widget cannot create customer sessions');
reset role; set local role authenticated;
set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000002';
select is(public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')->>'is_enabled','false','Admin gets configuration');
select is(public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',false,true)->>'is_enabled','true','Admin enables widget');
select is(public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')->>'public_id',(select public_id::text from widget_fixture),'Re-enable preserves public ID');
reset role; set local role service_role;
select lives_ok($$select public.create_customer_chat_session((select public_id from widget_fixture),repeat('b',64),now()+interval '1 day')$$,'Enabled chat creates sessions with unchanged server RPC');
reset role; set local role authenticated;
set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000003';
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')$$,'42501',null,'Member cannot read widget settings RPC');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,false)$$,'42501',null,'Member cannot manage widget');
set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000004';
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')$$,'42501',null,'Nonmember denied');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,false)$$,'42501',null,'Cross-workspace write denied');
set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000001';
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000002')$$,'42501',null,'Cross-workspace read denied');
set local request.jwt.claim.sub='';
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')$$,'28000',null,'Read requires auth.uid');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,false)$$,'28000',null,'Write requires auth.uid');
reset role; set local role anon;
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000001')$$,'42501',null,'Anon read execution denied');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000001',true,false)$$,'42501',null,'Anon write execution denied');
reset role;
select ok(not has_table_privilege('authenticated','public.workspace_chat_configs','UPDATE'),'No general browser UPDATE grant');
select ok(not has_table_privilege('anon','public.workspace_chat_configs','UPDATE'),'No anon UPDATE grant');
select ok(not has_function_privilege('service_role','public.admin_get_widget_config(uuid)','EXECUTE') and not has_function_privilege('service_role','public.admin_set_widget_enabled(uuid,boolean,boolean)','EXECUTE'),'Admin RPCs authenticate caller rather than service role');
set local role authenticated; set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000001';
reset role; delete from public.workspace_chat_configs where workspace_id='e2000000-0000-4000-8000-000000000002';
set local role authenticated; set local request.jwt.claim.sub='e1000000-0000-4000-8000-000000000004';
select throws_ok($$select public.admin_get_widget_config('e2000000-0000-4000-8000-000000000002')$$,'P0002',null,'Missing config safe unavailable');
select throws_ok($$select public.admin_set_widget_enabled('e2000000-0000-4000-8000-000000000002',true,false)$$,'P0002',null,'Missing mutation target unavailable');
select * from finish();
rollback;
