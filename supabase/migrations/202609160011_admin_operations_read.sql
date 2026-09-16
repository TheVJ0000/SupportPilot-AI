-- Phase 7A: read-only support operations, authorized by the caller's JWT identity.
create function app_private.can_view_support_operations(target_workspace_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select auth.uid() is not null and exists (
        select 1 from public.workspace_members as member
        where member.workspace_id = target_workspace_id and member.user_id = auth.uid()
          and member.role in ('owner', 'admin'));
$$;
revoke all on function app_private.can_view_support_operations(uuid) from public, anon, authenticated, service_role;
-- PostgreSQL checks EXECUTE when RLS invokes this helper as the browser role.
-- app_private is not exposed through PostgREST; this returns only a caller-bound boolean.
grant execute on function app_private.can_view_support_operations(uuid) to authenticated;

drop policy conversations_select_for_members on public.conversations;
drop policy conversation_turns_select_for_members on public.conversation_turns;
drop policy messages_select_for_members on public.messages;
drop policy message_citations_select_for_members on public.message_citations;
drop policy message_feedback_select_for_members on public.message_feedback;
drop policy escalations_select_for_members on public.escalations;
drop policy escalation_triage_runs_select_for_members on public.escalation_triage_runs;
drop policy escalation_notifications_select_for_members on public.escalation_notifications;
create policy conversations_select_for_managers on public.conversations for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy conversation_turns_select_for_managers on public.conversation_turns for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy messages_select_for_managers on public.messages for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy message_citations_select_for_managers on public.message_citations for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy message_feedback_select_for_managers on public.message_feedback for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy escalations_select_for_managers on public.escalations for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy escalation_triage_runs_select_for_managers on public.escalation_triage_runs for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));
create policy escalation_notifications_select_for_managers on public.escalation_notifications for select to authenticated
using ((select app_private.can_view_support_operations(workspace_id)));

create index conversations_admin_activity_idx on public.conversations (workspace_id, last_message_at desc nulls last, id desc);
create index escalations_admin_created_idx on public.escalations (workspace_id, created_at desc, id desc);

create function app_private.admin_conversation_item(conversation public.conversations)
returns jsonb language sql stable set search_path = '' as $$
    select jsonb_build_object('id',conversation.id,'status',conversation.status,
        'created_at',conversation.created_at,'updated_at',conversation.updated_at,'last_message_at',conversation.last_message_at,
        'message_count',(select count(*) from public.messages as message where message.workspace_id=conversation.workspace_id and message.conversation_id=conversation.id),
        'assistant_message_count',(select count(*) from public.messages as message where message.workspace_id=conversation.workspace_id and message.conversation_id=conversation.id and message.role='assistant'),
        'feedback_positive_count',(select count(*) from public.message_feedback as feedback where feedback.workspace_id=conversation.workspace_id and feedback.conversation_id=conversation.id and feedback.rating='positive'),
        'feedback_negative_count',(select count(*) from public.message_feedback as feedback where feedback.workspace_id=conversation.workspace_id and feedback.conversation_id=conversation.id and feedback.rating='negative'),
        'has_escalation',exists(select 1 from public.escalations as escalation where escalation.workspace_id=conversation.workspace_id and escalation.conversation_id=conversation.id),
        'escalation_priority',(select escalation.priority from public.escalations as escalation where escalation.workspace_id=conversation.workspace_id and escalation.conversation_id=conversation.id));
$$;
create function app_private.admin_escalation_item(escalation public.escalations)
returns jsonb language sql stable set search_path = '' as $$
    select jsonb_build_object('id',escalation.id,'conversation_id',escalation.conversation_id,
        'trigger_reason',escalation.trigger_reason,'status',escalation.status,'triage_status',escalation.triage_status,
        'category',escalation.category,'priority',escalation.priority,'summary',escalation.summary,
        'triage_attempts',escalation.triage_attempts,'created_at',escalation.created_at,'updated_at',escalation.updated_at,
        'triaged_at',escalation.triaged_at,'last_error_code',escalation.last_error_code,
        'notification_status',(select notification.status from public.escalation_notifications as notification
            where notification.workspace_id=escalation.workspace_id and notification.escalation_id=escalation.id));
$$;
revoke all on function app_private.admin_conversation_item(public.conversations) from public, anon, authenticated, service_role;
revoke all on function app_private.admin_escalation_item(public.escalations) from public, anon, authenticated, service_role;

create function public.admin_list_conversations(target_workspace_id uuid, page_limit integer default 25,
    status_filter text default 'all', cursor_time timestamptz default null, cursor_id uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare records jsonb; next_cursor jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    if page_limit is null or page_limit not between 1 and 50 or status_filter is null
       or status_filter not in ('all','open','human_requested','closed') or (cursor_time is not null and cursor_id is null)
       or (cursor_time is not null and not isfinite(cursor_time)) then
        raise exception 'Conversation query is invalid' using errcode='22023';
    end if;
    -- NULL activity is always last, sorted by UUID. cursor_id without time enters that bucket.
    select coalesce(jsonb_agg(app_private.admin_conversation_item(recent) order by recent.last_message_at desc nulls last,recent.id desc),'[]')
    into records from (select conversation.* from public.conversations as conversation
        where conversation.workspace_id=target_workspace_id and (status_filter='all' or conversation.status=status_filter)
          and (cursor_id is null or (cursor_time is null and conversation.last_message_at is null and conversation.id<cursor_id)
            or (cursor_time is not null and ((conversation.last_message_at,conversation.id)<(cursor_time,cursor_id) or conversation.last_message_at is null)))
        order by conversation.last_message_at desc nulls last,conversation.id desc limit page_limit+1) as recent;
    if jsonb_array_length(records)>page_limit then
        next_cursor:=jsonb_build_object('time',records->(page_limit-1)->'last_message_at','id',records->(page_limit-1)->'id');
        records:=records-(jsonb_array_length(records)-1);
    end if;
    return jsonb_build_object('workspace_id',target_workspace_id,'items',records,'next_cursor',next_cursor);
end;
$$;

create function public.admin_list_escalations(target_workspace_id uuid, page_limit integer default 25,
    status_filter text default 'all', triage_status_filter text default 'all', priority_filter text default 'all',
    trigger_reason_filter text default 'all', cursor_time timestamptz default null, cursor_id uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare records jsonb; next_cursor jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    if page_limit is null or page_limit not between 1 and 50
       or status_filter is null or status_filter not in ('all','open','in_progress','resolved','closed')
       or triage_status_filter is null or triage_status_filter not in ('all','pending','processing','completed','failed')
       or priority_filter is null or priority_filter not in ('all','low','normal','high','urgent')
       or trigger_reason_filter is null or trigger_reason_filter not in ('all','human_requested','insufficient_evidence')
       or ((cursor_time is null)<>(cursor_id is null)) or (cursor_time is not null and not isfinite(cursor_time)) then
        raise exception 'Escalation query is invalid' using errcode='22023';
    end if;
    select coalesce(jsonb_agg(app_private.admin_escalation_item(recent) order by recent.created_at desc,recent.id desc),'[]')
    into records from (select escalation.* from public.escalations as escalation where escalation.workspace_id=target_workspace_id
        and (status_filter='all' or escalation.status=status_filter) and (triage_status_filter='all' or escalation.triage_status=triage_status_filter)
        and (priority_filter='all' or escalation.priority=priority_filter) and (trigger_reason_filter='all' or escalation.trigger_reason=trigger_reason_filter)
        and (cursor_id is null or (escalation.created_at,escalation.id)<(cursor_time,cursor_id))
        order by escalation.created_at desc,escalation.id desc limit page_limit+1) as recent;
    if jsonb_array_length(records)>page_limit then
        next_cursor:=jsonb_build_object('time',records->(page_limit-1)->'created_at','id',records->(page_limit-1)->'id');
        records:=records-(jsonb_array_length(records)-1);
    end if;
    return jsonb_build_object('workspace_id',target_workspace_id,'items',records,'next_cursor',next_cursor);
end;
$$;

create function public.admin_dashboard_snapshot(target_workspace_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare metrics jsonb; conversations jsonb; escalations jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select jsonb_build_object(
        'total_conversations',(select count(*) from public.conversations where workspace_id=target_workspace_id),
        'ai_answered_conversations',(select count(distinct conversation_id) from public.messages where workspace_id=target_workspace_id and role='assistant' and answer_status='answered'),
        'insufficient_evidence_conversations',(select count(distinct conversation_id) from public.messages where workspace_id=target_workspace_id and role='assistant' and answer_status='insufficient_evidence'),
        'escalated_conversations',(select count(distinct conversation_id) from public.escalations where workspace_id=target_workspace_id),
        'human_requested_conversations',(select count(*) from public.conversations where workspace_id=target_workspace_id and status='human_requested'),
        'positive_feedback_count',(select count(*) from public.message_feedback where workspace_id=target_workspace_id and rating='positive'),
        'negative_feedback_count',(select count(*) from public.message_feedback where workspace_id=target_workspace_id and rating='negative'),
        'open_escalations',(select count(*) from public.escalations where workspace_id=target_workspace_id and status='open'),
        'high_priority_escalations',(select count(*) from public.escalations where workspace_id=target_workspace_id and triage_status='completed' and priority='high'),
        'urgent_escalations',(select count(*) from public.escalations where workspace_id=target_workspace_id and triage_status='completed' and priority='urgent'),
        'knowledge_ready',(select count(*) from public.knowledge_sources where workspace_id=target_workspace_id and status='ready'),
        'knowledge_processing',(select count(*) from public.knowledge_sources where workspace_id=target_workspace_id and status='processing'),
        'knowledge_failed',(select count(*) from public.knowledge_sources where workspace_id=target_workspace_id and status='failed')) into metrics;
    conversations:=public.admin_list_conversations(target_workspace_id,5)->'items';
    select coalesce(jsonb_agg(item.value-array['summary','updated_at','triage_attempts','last_error_code','notification_status'] order by item.ordinality),'[]')
    into escalations from jsonb_array_elements(public.admin_list_escalations(target_workspace_id,5)->'items') with ordinality as item(value,ordinality);
    return jsonb_build_object('workspace_id',target_workspace_id,'metrics',metrics,'recent_conversations',conversations,'recent_escalations',escalations);
end;
$$;

create function public.admin_get_conversation(target_workspace_id uuid,target_conversation_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare conversation_record public.conversations%rowtype; transcript jsonb; escalation jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select conversation.* into conversation_record from public.conversations as conversation
    where conversation.workspace_id=target_workspace_id and conversation.id=target_conversation_id;
    if not found then raise exception 'Support record not found' using errcode='P0002'; end if;
    select coalesce(jsonb_agg(jsonb_build_object('id',recent.id,'role',recent.role,'content',recent.content,
        'answer_status',recent.answer_status,'created_at',recent.created_at,
        'feedback',(select feedback.rating from public.message_feedback as feedback
            where feedback.workspace_id=target_workspace_id and feedback.conversation_id=target_conversation_id and feedback.message_id=recent.id),
        'citations',coalesce((select jsonb_agg(jsonb_build_object('source_id',citation.source_id,'source_title',citation.source_title,
            'source_type',citation.source_type,'chunk_index',citation.chunk_index,'locator',citation.locator) order by citation.ordinal)
            from public.message_citations as citation where citation.workspace_id=target_workspace_id and citation.message_id=recent.id),'[]'))
        order by recent.turn_created_at,recent.role_order,recent.created_at,recent.id),'[]') into transcript from (
        select message.*,turn.created_at as turn_created_at,case message.role when 'customer' then 0 else 1 end as role_order
        from public.messages as message join public.conversation_turns as turn on turn.id=message.turn_id
          and turn.workspace_id=message.workspace_id and turn.conversation_id=message.conversation_id
        where message.workspace_id=target_workspace_id and message.conversation_id=target_conversation_id
        order by turn.created_at,case message.role when 'customer' then 0 else 1 end,message.created_at,message.id limit 200) as recent;
    select app_private.admin_escalation_item(record) into escalation from public.escalations as record
    where record.workspace_id=target_workspace_id and record.conversation_id=target_conversation_id;
    return jsonb_build_object('workspace_id',target_workspace_id,'conversation',jsonb_build_object(
        'id',conversation_record.id,'status',conversation_record.status,'created_at',conversation_record.created_at,
        'updated_at',conversation_record.updated_at,'last_message_at',conversation_record.last_message_at,'human_requested_at',conversation_record.human_requested_at),
        'messages',transcript,'escalation',escalation);
end;
$$;

create function public.admin_get_escalation(target_workspace_id uuid,target_escalation_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare escalation_record public.escalations%rowtype; audit jsonb; notification jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.workspace_id=target_workspace_id and escalation.id=target_escalation_id;
    if not found then raise exception 'Support record not found' using errcode='P0002'; end if;
    select coalesce(jsonb_agg(jsonb_build_object('attempt_number',run.attempt_number,'status',run.status,
        'provider',run.provider,'model',run.model,'tool_name',run.tool_name,'safe_error_code',run.safe_error_code,
        'started_at',run.started_at,'completed_at',run.completed_at) order by run.attempt_number desc),'[]') into audit
    from (select record.* from public.escalation_triage_runs as record
        where record.workspace_id=target_workspace_id and record.escalation_id=target_escalation_id
        order by record.attempt_number desc limit 50) as run;
    select jsonb_build_object('status',record.status,'attempts',record.attempts,'provider',record.provider,
        'last_error_code',record.last_error_code,'sent_at',record.sent_at,'created_at',record.created_at,'updated_at',record.updated_at)
    into notification from public.escalation_notifications as record
    where record.workspace_id=target_workspace_id and record.escalation_id=target_escalation_id;
    return jsonb_build_object('workspace_id',target_workspace_id,'escalation',app_private.admin_escalation_item(escalation_record),
        'audit_runs',audit,'notification',notification);
end;
$$;

revoke all on function public.admin_dashboard_snapshot(uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_list_conversations(uuid,integer,text,timestamptz,uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_get_conversation(uuid,uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_list_escalations(uuid,integer,text,text,text,text,timestamptz,uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_get_escalation(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_dashboard_snapshot(uuid) to authenticated;
grant execute on function public.admin_list_conversations(uuid,integer,text,timestamptz,uuid) to authenticated;
grant execute on function public.admin_get_conversation(uuid,uuid) to authenticated;
grant execute on function public.admin_list_escalations(uuid,integer,text,text,text,text,timestamptz,uuid) to authenticated;
grant execute on function public.admin_get_escalation(uuid,uuid) to authenticated;
