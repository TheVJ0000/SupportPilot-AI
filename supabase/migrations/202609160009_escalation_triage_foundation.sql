-- Phase 6A: durable human-request escalation + one bounded, audited triage action.
create table public.escalations (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    conversation_id uuid not null,
    trigger_reason text not null,
    status text not null default 'open',
    triage_status text not null default 'pending',
    triage_attempts integer not null default 0,
    category text,
    priority text,
    summary text,
    triage_provider text,
    triage_model text,
    triage_started_at timestamptz,
    triaged_at timestamptz,
    last_error_code text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint escalations_conversation_unique unique (conversation_id),
    constraint escalations_id_workspace_unique unique (id, workspace_id),
    constraint escalations_conversation_scope_fk foreign key (conversation_id, workspace_id)
        references public.conversations (id, workspace_id) on delete cascade,
    constraint escalations_trigger_allowed
        check (trigger_reason in ('human_requested', 'insufficient_evidence')),
    constraint escalations_status_allowed check (status in ('open', 'in_progress', 'resolved', 'closed')),
    constraint escalations_triage_status_allowed check (triage_status in ('pending', 'processing', 'completed', 'failed')),
    constraint escalations_attempts_valid check (triage_attempts >= 0),
    constraint escalations_category_allowed check (category is null or category in (
        'account_access', 'billing', 'technical', 'product', 'policy', 'cancellation_refund', 'other'
    )),
    constraint escalations_priority_allowed check (priority is null or priority in ('low', 'normal', 'high', 'urgent')),
    constraint escalations_summary_valid check (summary is null or (
        char_length(summary) between 1 and 1200 and summary = btrim(summary) and summary ~ '[^[:space:]]'
    )),
    constraint escalations_provider_valid check (triage_provider is null or (
        char_length(triage_provider) between 1 and 100 and triage_provider = btrim(triage_provider) and triage_provider <> ''
    )),
    constraint escalations_model_valid check (triage_model is null or (
        char_length(triage_model) between 1 and 100 and triage_model = btrim(triage_model) and triage_model <> ''
    )),
    constraint escalations_error_allowed check (last_error_code is null or last_error_code in (
        'triage_not_configured', 'triage_auth_failed', 'triage_rate_limited', 'triage_provider_unavailable',
        'triage_invalid_tool_call', 'triage_failed', 'stale_triage_recovered'
    )),
    constraint escalations_state_consistent check (
        (triage_status = 'completed' and category is not null and priority is not null and summary is not null
         and triage_provider is not null and triage_model is not null and triaged_at is not null
         and triage_started_at is null and last_error_code is null and triage_attempts > 0)
        or
        (triage_status <> 'completed' and category is null and priority is null and summary is null
         and triage_provider is null and triage_model is null and triaged_at is null and (
            (triage_status = 'pending' and triage_started_at is null and last_error_code is null)
            or (triage_status = 'processing' and triage_started_at is not null and last_error_code is null and triage_attempts > 0)
            or (triage_status = 'failed' and triage_started_at is null and last_error_code is not null and triage_attempts > 0)
         ))
    )
);

create table public.escalation_triage_runs (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    escalation_id uuid not null,
    attempt_number integer not null check (attempt_number > 0),
    status text not null check (status in ('processing', 'completed', 'failed')),
    provider text,
    model text,
    tool_name text,
    safe_error_code text,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint escalation_triage_runs_attempt_unique unique (escalation_id, attempt_number),
    constraint escalation_triage_runs_scope_fk foreign key (escalation_id, workspace_id)
        references public.escalations (id, workspace_id) on delete cascade,
    constraint escalation_triage_runs_tool_allowed check (tool_name is null or tool_name = 'create_escalation'),
    constraint escalation_triage_runs_provider_valid check (provider is null or (
        char_length(provider) between 1 and 100 and provider = btrim(provider) and provider <> ''
    )),
    constraint escalation_triage_runs_model_valid check (model is null or (
        char_length(model) between 1 and 100 and model = btrim(model) and model <> ''
    )),
    constraint escalation_triage_runs_error_allowed check (safe_error_code is null or safe_error_code in (
        'triage_not_configured', 'triage_auth_failed', 'triage_rate_limited', 'triage_provider_unavailable',
        'triage_invalid_tool_call', 'triage_failed', 'stale_triage_recovered'
    )),
    constraint escalation_triage_runs_state_consistent check (
        (status = 'processing' and completed_at is null and safe_error_code is null
         and tool_name is null and provider is null and model is null)
        or (status = 'completed' and completed_at is not null and completed_at >= started_at
            and safe_error_code is null and tool_name is not null and tool_name = 'create_escalation'
            and provider is not null and model is not null)
        or (status = 'failed' and completed_at is not null and completed_at >= started_at
            and safe_error_code is not null and tool_name is null and provider is null and model is null)
    )
);

create trigger escalations_set_updated_at before update on public.escalations
for each row execute function app_private.set_updated_at();
create index escalations_workspace_created_idx on public.escalations (workspace_id, created_at desc, id);
create index escalation_triage_runs_workspace_idx on public.escalation_triage_runs (workspace_id, escalation_id);

alter table public.escalations enable row level security;
alter table public.escalation_triage_runs enable row level security;
revoke all on table public.escalations, public.escalation_triage_runs from public, anon, authenticated, service_role;
grant select on table public.escalations, public.escalation_triage_runs to authenticated;
create policy escalations_select_for_members on public.escalations for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));
create policy escalation_triage_runs_select_for_members on public.escalation_triage_runs for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

-- Preserve historical handoffs too; AI is never needed to create the record.
insert into public.escalations (workspace_id, conversation_id, trigger_reason)
select workspace_id, id, 'human_requested' from public.conversations
where status = 'human_requested'
on conflict on constraint escalations_conversation_unique do nothing;

-- Return shape changes require drop/recreate, not editing an already-pushed migration.
drop function public.request_customer_human_support(uuid, text);
create function public.request_customer_human_support(target_conversation_id uuid, session_token_hash text)
returns table (conversation_id uuid, status text, human_requested_at timestamptz, escalation_id uuid, triage_status text)
language plpgsql security definer set search_path = '' as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    escalation_record public.escalations%rowtype;
    request_timestamp timestamptz := now();
begin
    if target_conversation_id is null or session_token_hash is null or session_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Human support request is invalid' using errcode = '22023';
    end if;
    select conversation.* into conversation_record from public.conversations as conversation
    where conversation.id = target_conversation_id for update;
    if not found then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;
    select session.* into session_record from public.customer_sessions as session
    where session.id = conversation_record.customer_session_id
      and session.workspace_id = conversation_record.workspace_id and session.token_hash = session_token_hash
    for update;
    if not found or session_record.expires_at <= request_timestamp then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;
    if not exists (select 1 from public.workspace_chat_configs as config
        where config.workspace_id = conversation_record.workspace_id and config.public_id = session_record.chat_public_id and config.is_enabled) then
        raise exception 'Customer chat is disabled' using errcode = '42501';
    end if;
    if conversation_record.status = 'closed' then
        raise exception 'Conversation is closed' using errcode = '55000';
    end if;
    if conversation_record.status = 'open' then
        update public.conversations as conversation set status = 'human_requested', human_requested_at = request_timestamp
        where conversation.id = conversation_record.id
        returning conversation.human_requested_at into conversation_record.human_requested_at;
    end if;
    insert into public.escalations (workspace_id, conversation_id, trigger_reason)
    values (conversation_record.workspace_id, conversation_record.id, 'human_requested')
    on conflict on constraint escalations_conversation_unique do nothing;
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.conversation_id = conversation_record.id and escalation.workspace_id = conversation_record.workspace_id;
    if not found then
        raise exception 'Escalation state is invalid' using errcode = '55000';
    end if;
    update public.customer_sessions as session set last_seen_at = request_timestamp where session.id = session_record.id;
    conversation_id := conversation_record.id;
    status := 'human_requested';
    human_requested_at := conversation_record.human_requested_at;
    escalation_id := escalation_record.id;
    triage_status := escalation_record.triage_status;
    return next;
end;
$$;

create function public.begin_escalation_triage(target_escalation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    escalation_record public.escalations%rowtype;
    run_id uuid;
    transcript jsonb;
    request_timestamp timestamptz := now();
begin
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.id = target_escalation_id for update;
    if not found then
        raise exception 'Escalation is unavailable' using errcode = '55000';
    end if;
    if escalation_record.trigger_reason <> 'human_requested' or escalation_record.status not in ('open', 'in_progress')
       or not exists (select 1 from public.conversations as conversation
           where conversation.id = escalation_record.conversation_id and conversation.workspace_id = escalation_record.workspace_id
             and conversation.status = 'human_requested') then
        raise exception 'Escalation is not eligible for human-request triage' using errcode = '55000';
    end if;
    if escalation_record.triage_status = 'completed' or (
        escalation_record.triage_status = 'processing'
        and escalation_record.triage_started_at > request_timestamp - interval '15 minutes'
    ) then
        return jsonb_build_object('escalation_id', escalation_record.id, 'workspace_id', escalation_record.workspace_id,
            'conversation_id', escalation_record.conversation_id, 'trigger_reason', escalation_record.trigger_reason,
            'triage_status', escalation_record.triage_status, 'should_run', false,
            'triage_run_id', null, 'attempt_number', escalation_record.triage_attempts, 'messages', '[]'::jsonb);
    end if;
    if escalation_record.triage_status = 'processing' then
        update public.escalation_triage_runs as run
        set status = 'failed', safe_error_code = 'stale_triage_recovered', completed_at = request_timestamp
        where run.escalation_id = escalation_record.id and run.workspace_id = escalation_record.workspace_id
          and run.attempt_number = escalation_record.triage_attempts and run.status = 'processing';
        if not found then
            raise exception 'Triage run state is invalid' using errcode = '55000';
        end if;
    end if;
    update public.escalations as escalation
    set triage_status = 'processing', triage_attempts = escalation.triage_attempts + 1,
        triage_started_at = request_timestamp, last_error_code = null
    where escalation.id = escalation_record.id returning escalation.* into escalation_record;
    insert into public.escalation_triage_runs (workspace_id, escalation_id, attempt_number, status, started_at)
    values (escalation_record.workspace_id, escalation_record.id, escalation_record.triage_attempts, 'processing', request_timestamp)
    returning id into run_id;
    -- Return only safe persisted message fields. Recent-first selection, chronological final order.
    select coalesce(jsonb_agg(jsonb_build_object('role', recent.role, 'content', recent.content,
        'answer_status', recent.answer_status) order by recent.turn_created_at, recent.role_order, recent.created_at, recent.id), '[]'::jsonb)
    into transcript from (
        select message.id, message.role, message.content, message.answer_status, message.created_at,
            turn.created_at as turn_created_at, case message.role when 'customer' then 0 else 1 end as role_order
        from public.messages as message join public.conversation_turns as turn
          on turn.id = message.turn_id and turn.workspace_id = message.workspace_id and turn.conversation_id = message.conversation_id
        where message.workspace_id = escalation_record.workspace_id and message.conversation_id = escalation_record.conversation_id
        order by turn.created_at desc, case message.role when 'customer' then 0 else 1 end desc, message.created_at desc, message.id desc
        limit 20
    ) as recent;
    return jsonb_build_object('escalation_id', escalation_record.id, 'workspace_id', escalation_record.workspace_id,
        'conversation_id', escalation_record.conversation_id, 'trigger_reason', escalation_record.trigger_reason,
        'triage_status', 'processing', 'should_run', true, 'triage_run_id', run_id,
        'attempt_number', escalation_record.triage_attempts, 'messages', transcript);
end;
$$;

create function public.complete_escalation_triage(
    target_escalation_id uuid, target_triage_run_id uuid, submitted_category text, submitted_priority text,
    submitted_summary text, submitted_provider text, submitted_model text
)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
    escalation_record public.escalations%rowtype;
    run_record public.escalation_triage_runs%rowtype;
    request_timestamp timestamptz := now();
begin
    if submitted_category is null or submitted_category not in ('account_access', 'billing', 'technical', 'product', 'policy', 'cancellation_refund', 'other')
       or submitted_priority is null or submitted_priority not in ('low', 'normal', 'high', 'urgent')
       or submitted_summary is null or char_length(submitted_summary) not between 1 and 1200
       or submitted_summary <> btrim(submitted_summary) or submitted_summary !~ '[^[:space:]]'
       or submitted_provider is null or char_length(submitted_provider) not between 1 and 100
       or submitted_provider <> btrim(submitted_provider) or submitted_provider !~ '[^[:space:]]'
       or submitted_model is null or char_length(submitted_model) not between 1 and 100
       or submitted_model <> btrim(submitted_model) or submitted_model !~ '[^[:space:]]' then
        raise exception 'Triage completion is invalid' using errcode = '22023';
    end if;
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.id = target_escalation_id for update;
    if not found or escalation_record.triage_status <> 'processing' then
        raise exception 'Escalation is not processing' using errcode = '55000';
    end if;
    select run.* into run_record from public.escalation_triage_runs as run
    where run.id = target_triage_run_id and run.escalation_id = escalation_record.id
      and run.workspace_id = escalation_record.workspace_id and run.attempt_number = escalation_record.triage_attempts
    for update;
    if not found or run_record.status <> 'processing' then
        raise exception 'Triage run is not the active attempt' using errcode = '55000';
    end if;
    update public.escalations as escalation set category = submitted_category, priority = submitted_priority,
        summary = submitted_summary, triage_provider = submitted_provider, triage_model = submitted_model,
        triage_status = 'completed', triage_started_at = null, last_error_code = null, triaged_at = request_timestamp
    where escalation.id = escalation_record.id;
    update public.escalation_triage_runs as run set status = 'completed', provider = submitted_provider,
        model = submitted_model, tool_name = 'create_escalation', completed_at = request_timestamp
    where run.id = run_record.id;
    return true;
end;
$$;

create function public.fail_escalation_triage(target_escalation_id uuid, target_triage_run_id uuid, submitted_error_code text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
    escalation_record public.escalations%rowtype;
    run_record public.escalation_triage_runs%rowtype;
    request_timestamp timestamptz := now();
begin
    if submitted_error_code is null or submitted_error_code not in (
        'triage_not_configured', 'triage_auth_failed', 'triage_rate_limited', 'triage_provider_unavailable',
        'triage_invalid_tool_call', 'triage_failed', 'stale_triage_recovered'
    ) then
        raise exception 'Triage failure code is invalid' using errcode = '22023';
    end if;
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.id = target_escalation_id for update;
    if not found or escalation_record.triage_status <> 'processing' then
        raise exception 'Escalation is not processing' using errcode = '55000';
    end if;
    select run.* into run_record from public.escalation_triage_runs as run
    where run.id = target_triage_run_id and run.escalation_id = escalation_record.id
      and run.workspace_id = escalation_record.workspace_id and run.attempt_number = escalation_record.triage_attempts
    for update;
    if not found or run_record.status <> 'processing' then
        raise exception 'Triage run is not the active attempt' using errcode = '55000';
    end if;
    update public.escalations as escalation set triage_status = 'failed', triage_started_at = null, last_error_code = submitted_error_code
    where escalation.id = escalation_record.id;
    update public.escalation_triage_runs as run set status = 'failed', safe_error_code = submitted_error_code, completed_at = request_timestamp
    where run.id = run_record.id;
    return true;
end;
$$;

revoke all on function public.request_customer_human_support(uuid, text) from public, anon, authenticated, service_role;
revoke all on function public.begin_escalation_triage(uuid) from public, anon, authenticated, service_role;
revoke all on function public.complete_escalation_triage(uuid, uuid, text, text, text, text, text) from public, anon, authenticated, service_role;
revoke all on function public.fail_escalation_triage(uuid, uuid, text) from public, anon, authenticated, service_role;
grant execute on function public.request_customer_human_support(uuid, text) to service_role;
grant execute on function public.begin_escalation_triage(uuid) to service_role;
grant execute on function public.complete_escalation_triage(uuid, uuid, text, text, text, text, text) to service_role;
grant execute on function public.fail_escalation_triage(uuid, uuid, text) to service_role;
