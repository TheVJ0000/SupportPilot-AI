-- Phase 6B: database-owned unresolved work, recovery, and deterministic email outbox.
create function app_private.escalate_insufficient_evidence()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into public.escalations (workspace_id, conversation_id, trigger_reason)
    values (new.workspace_id, new.conversation_id, 'insufficient_evidence')
    on conflict on constraint escalations_conversation_unique do nothing;
    return new;
end;
$$;
revoke all on function app_private.escalate_insufficient_evidence() from public, anon, authenticated, service_role;
create trigger messages_escalate_insufficient_evidence
after insert on public.messages for each row
when (new.role = 'assistant' and new.answer_status = 'insufficient_evidence')
execute function app_private.escalate_insufficient_evidence();

create function app_private.is_recoverable_escalation(escalation public.escalations)
returns boolean language sql stable set search_path = '' as $$
    select escalation.triage_attempts < 3 and escalation.status in ('open', 'in_progress')
      and exists (select 1 from public.conversations as conversation
        where conversation.id = escalation.conversation_id and conversation.workspace_id = escalation.workspace_id
          and ((escalation.trigger_reason = 'human_requested' and conversation.status = 'human_requested')
            or (escalation.trigger_reason = 'insufficient_evidence' and conversation.status in ('open', 'human_requested'))))
      and (escalation.triage_status = 'pending'
        or (escalation.triage_status = 'processing' and escalation.triage_started_at <= now() - interval '15 minutes')
        or (escalation.triage_status = 'failed' and escalation.updated_at <= now() - interval '15 minutes'
          and escalation.last_error_code in ('triage_not_configured', 'triage_rate_limited', 'triage_provider_unavailable', 'triage_failed')));
$$;
revoke all on function app_private.is_recoverable_escalation(public.escalations) from public, anon, authenticated, service_role;

create function public.list_recoverable_escalations(max_results integer)
returns setof uuid language plpgsql stable security definer set search_path = '' as $$
begin
    if max_results is null or max_results not between 1 and 20 then
        raise exception 'Recovery limit must be between 1 and 20' using errcode = '22023';
    end if;
    return query select escalation.id from public.escalations as escalation
    where app_private.is_recoverable_escalation(escalation)
    order by escalation.updated_at, escalation.id limit max_results;
end;
$$;

create or replace function public.begin_escalation_triage(target_escalation_id uuid)
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
    if escalation_record.status not in ('open', 'in_progress') or not exists (
        select 1 from public.conversations as conversation
        where conversation.id = escalation_record.conversation_id and conversation.workspace_id = escalation_record.workspace_id
          and ((escalation_record.trigger_reason = 'human_requested' and conversation.status = 'human_requested')
            or (escalation_record.trigger_reason = 'insufficient_evidence' and conversation.status in ('open', 'human_requested')))
    ) then
        raise exception 'Escalation is not eligible for triage' using errcode = '55000';
    end if;
    -- Recheck backoff/cap under the row lock: listing is never authority to claim work.
    if not app_private.is_recoverable_escalation(escalation_record) then
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

create table public.escalation_notifications (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    escalation_id uuid not null unique,
    status text not null default 'pending' check (status in ('pending', 'sending', 'sent', 'failed')),
    attempts integer not null default 0 check (attempts between 0 and 3),
    provider text,
    provider_message_id text,
    last_error_code text check (last_error_code in (
        'notification_auth_failed', 'notification_configuration_invalid', 'notification_rate_limited',
        'notification_provider_unavailable', 'notification_no_recipients', 'notification_delivery_unknown',
        'notification_failed', 'stale_notification_recovered')),
    delivery_started_at timestamptz,
    first_delivery_started_at timestamptz,
    sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (escalation_id, workspace_id) references public.escalations (id, workspace_id) on delete cascade,
    constraint notification_provider_valid check (
        provider is null or (provider = btrim(provider) and char_length(provider) between 1 and 100 and provider ~ '[^[:space:]]')),
    constraint notification_message_id_valid check (
        provider_message_id is null or (provider_message_id = btrim(provider_message_id)
          and char_length(provider_message_id) between 1 and 200 and provider_message_id ~ '[^[:space:]]')),
    constraint notification_state_consistent check (
        (status = 'pending' and attempts = 0 and delivery_started_at is null and first_delivery_started_at is null
          and sent_at is null and last_error_code is null and provider is null and provider_message_id is null)
        or (status = 'sending' and attempts > 0 and delivery_started_at is not null and first_delivery_started_at is not null
          and sent_at is null and last_error_code is null and provider is null and provider_message_id is null)
        or (status = 'sent' and attempts > 0 and delivery_started_at is null and first_delivery_started_at is not null
          and sent_at is not null and last_error_code is null and provider is not null and provider_message_id is not null)
        or (status = 'failed' and attempts > 0 and delivery_started_at is null and first_delivery_started_at is not null
          and sent_at is null and last_error_code is not null and provider is null and provider_message_id is null)
    )
);
create trigger escalation_notifications_set_updated_at before update on public.escalation_notifications
for each row execute function app_private.set_updated_at();
create index escalation_notifications_recovery_idx on public.escalation_notifications (status, updated_at, id);
create index escalations_recovery_idx on public.escalations (triage_status, updated_at, id);
alter table public.escalation_notifications enable row level security;
revoke all on table public.escalation_notifications from public, anon, authenticated, service_role;
grant select on table public.escalation_notifications to authenticated;
create policy escalation_notifications_select_for_members on public.escalation_notifications
for select to authenticated using ((select app_private.is_workspace_member(workspace_id)));

-- Runs inside the completion RPC transaction, after all classification constraints pass.
create function app_private.enqueue_escalation_notification()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into public.escalation_notifications (workspace_id, escalation_id)
    values (new.workspace_id, new.id) on conflict (escalation_id) do nothing;
    return new;
end;
$$;
revoke all on function app_private.enqueue_escalation_notification() from public, anon, authenticated, service_role;
create trigger escalations_enqueue_notification after insert or update on public.escalations
for each row when (new.triage_status = 'completed') execute function app_private.enqueue_escalation_notification();
insert into public.escalation_notifications (workspace_id, escalation_id)
select workspace_id, id from public.escalations where triage_status = 'completed' on conflict (escalation_id) do nothing;

create function app_private.is_recoverable_notification(notification public.escalation_notifications)
returns boolean language sql stable set search_path = '' as $$
    select notification.attempts < 3 and exists (
        select 1 from public.escalations as escalation where escalation.id = notification.escalation_id
          and escalation.workspace_id = notification.workspace_id and escalation.triage_status = 'completed')
      and (notification.status = 'pending'
        or (notification.status = 'sending' and notification.delivery_started_at <= now() - interval '15 minutes')
        or (notification.status = 'failed' and notification.updated_at <= now() - interval '15 minutes'
          and notification.last_error_code in ('notification_rate_limited', 'notification_provider_unavailable', 'notification_failed')));
$$;
revoke all on function app_private.is_recoverable_notification(public.escalation_notifications) from public, anon, authenticated, service_role;

create function public.list_recoverable_escalation_notifications(max_results integer)
returns setof uuid language plpgsql stable security definer set search_path = '' as $$
begin
    if max_results is null or max_results not between 1 and 20 then
        raise exception 'Recovery limit must be between 1 and 20' using errcode = '22023';
    end if;
    return query select notification.id from public.escalation_notifications as notification
    where app_private.is_recoverable_notification(notification)
    order by notification.updated_at, notification.id limit max_results;
end;
$$;

create function public.begin_escalation_notification(target_notification_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    notification_record public.escalation_notifications%rowtype;
    escalation_record public.escalations%rowtype;
    recipients jsonb;
    workspace_name text;
begin
    select notification.* into notification_record from public.escalation_notifications as notification
    where notification.id = target_notification_id for update;
    if not found then
        raise exception 'Notification is unavailable' using errcode = '55000';
    end if;
    if not app_private.is_recoverable_notification(notification_record) then
        return null;
    end if;
    -- Resend retains keys for 24h. Never replay a potentially accepted send outside
    -- a conservative 23h recovery window, even after a long process outage.
    if notification_record.first_delivery_started_at <= now() - interval '23 hours' then
        update public.escalation_notifications set status = 'failed', delivery_started_at = null,
            last_error_code = 'notification_delivery_unknown' where id = notification_record.id;
        return null;
    end if;
    select escalation.* into escalation_record from public.escalations as escalation
    where escalation.id = notification_record.escalation_id and escalation.workspace_id = notification_record.workspace_id
      and escalation.triage_status = 'completed';
    select workspace.name into workspace_name from public.workspaces as workspace where workspace.id = notification_record.workspace_id;
    select coalesce(jsonb_agg(address.email order by address.email), '[]'::jsonb) into recipients from (
        select distinct lower(btrim(account.email)) as email from public.workspace_members as member
        join auth.users as account on account.id = member.user_id
        where member.workspace_id = notification_record.workspace_id and member.role in ('owner', 'admin')
          and account.email_confirmed_at is not null and account.deleted_at is null
          and account.email is not null and char_length(btrim(account.email)) between 3 and 254
          and btrim(account.email) ~ '^[^[:space:]@<>]+@[^[:space:]@<>]+[.][^[:space:]@<>]+$'
        order by email limit 20
    ) as address;
    update public.escalation_notifications as notification set attempts = notification.attempts + 1,
        first_delivery_started_at = coalesce(notification.first_delivery_started_at, now()),
        status = case when jsonb_array_length(recipients) = 0 then 'failed' else 'sending' end,
        delivery_started_at = case when jsonb_array_length(recipients) = 0 then null else now() end,
        last_error_code = case when jsonb_array_length(recipients) = 0 then 'notification_no_recipients' else null end
    where notification.id = notification_record.id returning notification.* into notification_record;
    if jsonb_array_length(recipients) = 0 then return null; end if;
    return jsonb_build_object('notification_id', notification_record.id, 'workspace_name', workspace_name,
        'category', escalation_record.category, 'priority', escalation_record.priority,
        'recipient_emails', recipients, 'attempt_number', notification_record.attempts);
end;
$$;

create function public.complete_escalation_notification(target_notification_id uuid, expected_attempt_number integer,
    submitted_provider text, submitted_provider_message_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare notification_record public.escalation_notifications%rowtype;
begin
    if expected_attempt_number is null or expected_attempt_number not between 1 and 3
       or submitted_provider is null or char_length(submitted_provider) not between 1 and 100
       or submitted_provider <> btrim(submitted_provider) or submitted_provider !~ '[^[:space:]]'
       or submitted_provider_message_id is null or char_length(submitted_provider_message_id) not between 1 and 200
       or submitted_provider_message_id <> btrim(submitted_provider_message_id) or submitted_provider_message_id !~ '[^[:space:]]' then
        raise exception 'Notification completion is invalid' using errcode = '22023';
    end if;
    select notification.* into notification_record from public.escalation_notifications as notification
    where notification.id = target_notification_id for update;
    if not found then raise exception 'Notification is unavailable' using errcode = '55000'; end if;
    if notification_record.status = 'sent' and notification_record.attempts = expected_attempt_number
       and notification_record.provider = submitted_provider and notification_record.provider_message_id = submitted_provider_message_id then
        return true;
    end if;
    if notification_record.status <> 'sending' or notification_record.attempts <> expected_attempt_number
       or not exists (select 1 from public.escalations as escalation where escalation.id = notification_record.escalation_id
         and escalation.workspace_id = notification_record.workspace_id and escalation.triage_status = 'completed') then
        raise exception 'Notification is not the active attempt' using errcode = '55000';
    end if;
    update public.escalation_notifications set status = 'sent', provider = submitted_provider,
        provider_message_id = submitted_provider_message_id, delivery_started_at = null, sent_at = now(), last_error_code = null
    where id = notification_record.id;
    return true;
end;
$$;

create function public.fail_escalation_notification(target_notification_id uuid, expected_attempt_number integer, submitted_error_code text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare notification_record public.escalation_notifications%rowtype;
begin
    if expected_attempt_number is null or expected_attempt_number not between 1 and 3 or submitted_error_code is null
       or submitted_error_code not in ('notification_auth_failed', 'notification_configuration_invalid', 'notification_rate_limited',
         'notification_provider_unavailable', 'notification_no_recipients', 'notification_delivery_unknown', 'notification_failed', 'stale_notification_recovered') then
        raise exception 'Notification failure code is invalid' using errcode = '22023';
    end if;
    select notification.* into notification_record from public.escalation_notifications as notification
    where notification.id = target_notification_id for update;
    if not found or notification_record.status <> 'sending' or notification_record.attempts <> expected_attempt_number
       or not exists (select 1 from public.escalations as escalation where escalation.id = notification_record.escalation_id
         and escalation.workspace_id = notification_record.workspace_id and escalation.triage_status = 'completed') then
        raise exception 'Notification is not the active attempt' using errcode = '55000';
    end if;
    update public.escalation_notifications set status = 'failed', delivery_started_at = null, last_error_code = submitted_error_code
    where id = notification_record.id;
    return true;
end;
$$;

revoke all on function public.list_recoverable_escalations(integer) from public, anon, authenticated, service_role;
revoke all on function public.begin_escalation_triage(uuid) from public, anon, authenticated, service_role;
revoke all on function public.list_recoverable_escalation_notifications(integer) from public, anon, authenticated, service_role;
revoke all on function public.begin_escalation_notification(uuid) from public, anon, authenticated, service_role;
revoke all on function public.complete_escalation_notification(uuid, integer, text, text) from public, anon, authenticated, service_role;
revoke all on function public.fail_escalation_notification(uuid, integer, text) from public, anon, authenticated, service_role;
grant execute on function public.list_recoverable_escalations(integer) to service_role;
grant execute on function public.begin_escalation_triage(uuid) to service_role;
grant execute on function public.list_recoverable_escalation_notifications(integer) to service_role;
grant execute on function public.begin_escalation_notification(uuid) to service_role;
grant execute on function public.complete_escalation_notification(uuid, integer, text, text) to service_role;
grant execute on function public.fail_escalation_notification(uuid, integer, text) to service_role;
