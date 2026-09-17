-- Phase 7B: explicit admin decisions, independent of AI answers and escalation state.
alter table public.conversations
    add column resolution_outcome text not null default 'unresolved',
    add column resolved_at timestamptz,
    add column closed_at timestamptz;

-- Historical closure is not evidence of successful resolution.
update public.conversations
set resolution_outcome='closed_unresolved', closed_at=coalesce(updated_at,created_at,now())
where status='closed';

alter table public.conversations
    add constraint conversations_resolution_outcome_allowed
        check (resolution_outcome in ('unresolved','resolved','closed_unresolved')),
    add constraint conversations_resolution_state_consistent check (
        (status in ('open','human_requested') and resolution_outcome='unresolved'
            and resolved_at is null and closed_at is null)
        or (status='closed' and resolution_outcome='resolved'
            and resolved_at is not null and closed_at is not null and resolved_at=closed_at
            and isfinite(resolved_at) and isfinite(closed_at))
        or (status='closed' and resolution_outcome='closed_unresolved'
            and resolved_at is null and closed_at is not null and isfinite(closed_at))
    );

create or replace function app_private.admin_conversation_item(conversation public.conversations)
returns jsonb language sql stable set search_path = '' as $$
    select jsonb_build_object('id',conversation.id,'status',conversation.status,'resolution_outcome',conversation.resolution_outcome,
        'created_at',conversation.created_at,'updated_at',conversation.updated_at,'last_message_at',conversation.last_message_at,
        'message_count',(select count(*) from public.messages as message where message.workspace_id=conversation.workspace_id and message.conversation_id=conversation.id),
        'assistant_message_count',(select count(*) from public.messages as message where message.workspace_id=conversation.workspace_id and message.conversation_id=conversation.id and message.role='assistant'),
        'feedback_positive_count',(select count(*) from public.message_feedback as feedback where feedback.workspace_id=conversation.workspace_id and feedback.conversation_id=conversation.id and feedback.rating='positive'),
        'feedback_negative_count',(select count(*) from public.message_feedback as feedback where feedback.workspace_id=conversation.workspace_id and feedback.conversation_id=conversation.id and feedback.rating='negative'),
        'has_escalation',exists(select 1 from public.escalations as escalation where escalation.workspace_id=conversation.workspace_id and escalation.conversation_id=conversation.id),
        'escalation_priority',(select escalation.priority from public.escalations as escalation where escalation.workspace_id=conversation.workspace_id and escalation.conversation_id=conversation.id));
$$;

create function public.admin_set_conversation_resolution(
    target_workspace_id uuid, target_conversation_id uuid, expected_status text,
    expected_resolution_outcome text, requested_action text
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.conversations%rowtype; action_timestamp timestamptz := now();
begin
    if auth.uid() is null then
        raise exception 'Authentication required' using errcode='28000';
    end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select conversation.* into record from public.conversations as conversation
    where conversation.workspace_id=target_workspace_id and conversation.id=target_conversation_id
    for update;
    if not found then raise exception 'Support record not found' using errcode='P0002'; end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    if record.status is distinct from expected_status
        or record.resolution_outcome is distinct from expected_resolution_outcome then
        raise exception 'Support record changed' using errcode='40001';
    end if;
    if requested_action in ('resolve','close_unresolved') and record.status in ('open','human_requested')
        and record.resolution_outcome='unresolved' then
        update public.conversations set status='closed',
            resolution_outcome=case requested_action when 'resolve' then 'resolved' else 'closed_unresolved' end,
            resolved_at=case when requested_action='resolve' then action_timestamp end,
            closed_at=action_timestamp
        where workspace_id=target_workspace_id and id=target_conversation_id;
    elsif requested_action='reopen' and record.status='closed'
        and record.resolution_outcome in ('resolved','closed_unresolved') then
        update public.conversations
        set status=case when record.human_requested_at is not null then 'human_requested' else 'open' end,
            resolution_outcome='unresolved', resolved_at=null, closed_at=null
        where workspace_id=target_workspace_id and id=target_conversation_id;
    else
        raise exception 'Conversation transition conflicts' using errcode='55000';
    end if;
    -- No escalation mutation; return only the existing minimized read contract.
    return public.admin_get_conversation(target_workspace_id,target_conversation_id);
end;
$$;

create function public.admin_set_escalation_status(
    target_workspace_id uuid, target_escalation_id uuid, expected_current_status text, new_status text
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.escalations%rowtype;
begin
    if auth.uid() is null then
        raise exception 'Authentication required' using errcode='28000';
    end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select escalation.* into record from public.escalations as escalation
    where escalation.workspace_id=target_workspace_id and escalation.id=target_escalation_id
    for update;
    if not found then raise exception 'Support record not found' using errcode='P0002'; end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    if record.status is distinct from expected_current_status then
        raise exception 'Support record changed' using errcode='40001';
    end if;
    if new_status is null or not (
        (record.status='open' and new_status in ('in_progress','resolved','closed'))
        or (record.status='in_progress' and new_status in ('open','resolved','closed'))
        or (record.status='resolved' and new_status in ('open','closed'))
        or (record.status='closed' and new_status='open')
    ) then
        raise exception 'Escalation transition conflicts' using errcode='55000';
    end if;
    update public.escalations set status=new_status
    where workspace_id=target_workspace_id and id=target_escalation_id;
    -- Conversation outcome, triage fields, and recovery policy stay independent.
    return public.admin_get_escalation(target_workspace_id,target_escalation_id);
end;
$$;

revoke all on function public.admin_set_conversation_resolution(uuid,uuid,text,text,text)
    from public,anon,authenticated,service_role;
revoke all on function public.admin_set_escalation_status(uuid,uuid,text,text)
    from public,anon,authenticated,service_role;
grant execute on function public.admin_set_conversation_resolution(uuid,uuid,text,text,text) to authenticated;
grant execute on function public.admin_set_escalation_status(uuid,uuid,text,text) to authenticated;

create or replace function public.admin_get_conversation(target_workspace_id uuid,target_conversation_id uuid)
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
        'id',conversation_record.id,'status',conversation_record.status,
        'resolution_outcome',conversation_record.resolution_outcome,'resolved_at',conversation_record.resolved_at,'closed_at',conversation_record.closed_at,'created_at',conversation_record.created_at,
        'updated_at',conversation_record.updated_at,'last_message_at',conversation_record.last_message_at,'human_requested_at',conversation_record.human_requested_at),
        'messages',transcript,'escalation',escalation);
end;
$$;

create or replace function public.admin_dashboard_snapshot(target_workspace_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare metrics jsonb; conversations jsonb; escalations jsonb;
begin
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Support operations access denied' using errcode='42501';
    end if;
    select jsonb_build_object(
        'resolved_conversations',(select count(*) from public.conversations where workspace_id=target_workspace_id and resolution_outcome='resolved'),
        'closed_unresolved_conversations',(select count(*) from public.conversations where workspace_id=target_workspace_id and resolution_outcome='closed_unresolved'),
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
