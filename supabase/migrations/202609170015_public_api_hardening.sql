-- Phase 8B: database-owned fixed-window quotas; no customer PII or request contents.
create table public.customer_api_rate_limits (
    scope text not null check (scope in (
        'session_minute','session_hour','turn_minute','turn_hour',
        'history_minute','feedback_minute','human_minute')),
    subject_id uuid not null,
    window_started_at timestamptz not null,
    request_count integer not null check (request_count between 1 and 300),
    expires_at timestamptz not null check (expires_at > window_started_at),
    primary key (scope, subject_id, window_started_at)
);
create index customer_api_rate_limits_expiry_idx on public.customer_api_rate_limits(expires_at);
alter table public.customer_api_rate_limits enable row level security;
revoke all on public.customer_api_rate_limits from public, anon, authenticated, service_role;

-- The only source of V1 quota constants. No public caller chooses scope, subject or limits.
create function app_private.consume_customer_rate_limit(target_scope text, target_subject uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare
    max_requests integer;
    window_seconds integer;
    db_timestamp timestamptz := clock_timestamp();
    window_start timestamptz;
    retry_seconds integer;
begin
    case target_scope
        when 'session_minute' then max_requests := 30; window_seconds := 60;
        when 'session_hour' then max_requests := 300; window_seconds := 3600;
        when 'turn_minute' then max_requests := 6; window_seconds := 60;
        when 'turn_hour' then max_requests := 60; window_seconds := 3600;
        when 'history_minute' then max_requests := 60; window_seconds := 60;
        when 'feedback_minute' then max_requests := 20; window_seconds := 60;
        when 'human_minute' then max_requests := 10; window_seconds := 60;
        else raise exception 'Invalid rate-limit scope' using errcode = '22023';
    end case;
    if target_subject is null then
        raise exception 'Invalid rate-limit subject' using errcode = '22023';
    end if;
    window_start := to_timestamp(floor(extract(epoch from db_timestamp) / window_seconds) * window_seconds);
    insert into public.customer_api_rate_limits as counter
        (scope, subject_id, window_started_at, request_count, expires_at)
    values (target_scope, target_subject, window_start, 1,
        window_start + make_interval(secs => window_seconds))
    on conflict (scope, subject_id, window_started_at) do update
    set request_count = counter.request_count + 1
    where counter.request_count < max_requests;
    if not found then
        retry_seconds := greatest(1, least(window_seconds,
            ceil(extract(epoch from window_start + make_interval(secs => window_seconds)
                - clock_timestamp()))::integer));
        -- PT429 is PostgREST's custom HTTP status; FastAPI emits only its own allow-listed envelope.
        raise exception 'Too many requests' using errcode = 'PT429',
            detail = jsonb_build_object('retry_after_seconds', retry_seconds)::text;
    end if;
end;
$$;
revoke all on function app_private.consume_customer_rate_limit(text,uuid)
    from public, anon, authenticated, service_role;

-- Low-frequency worker cleanup. Indexed bounded selection, not an unbounded per-request delete.
create function public.cleanup_customer_api_rate_limits(max_results integer default 500)
returns integer language plpgsql security definer set search_path = '' as $$
declare
    removed integer;
    cleanup_timestamp timestamptz := clock_timestamp();
begin
    if max_results is null or max_results not between 1 and 500 then
        raise exception 'Invalid cleanup batch' using errcode = '22023';
    end if;
    with expired as (
        select counter.scope, counter.subject_id, counter.window_started_at
        from public.customer_api_rate_limits as counter
        where counter.expires_at <= cleanup_timestamp
        order by counter.expires_at, counter.scope, counter.subject_id
        limit max_results for update skip locked
    ), deleted as (
        delete from public.customer_api_rate_limits as counter using expired
        where counter.scope=expired.scope and counter.subject_id=expired.subject_id
          and counter.window_started_at=expired.window_started_at
        returning 1
    ) select count(*)::integer into removed from deleted;
    return removed;
end;
$$;
revoke all on function public.cleanup_customer_api_rate_limits(integer) from public,anon,authenticated,service_role;
grant execute on function public.cleanup_customer_api_rate_limits(integer) to service_role;


create or replace function public.create_customer_chat_session(
    target_public_id uuid,
    session_token_hash text,
    session_expires_at timestamptz
)
returns table (
    customer_session_id uuid,
    conversation_id uuid,
    workspace_id uuid,
    workspace_name text,
    expires_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    config_record record;
    generated_session_id uuid := gen_random_uuid();
    generated_conversation_id uuid := gen_random_uuid();
    created_timestamp timestamptz := now();
begin
    select config.workspace_id, config.public_id, workspace.name as workspace_name
    into config_record
    from public.workspace_chat_configs as config
    join public.workspaces as workspace on workspace.id = config.workspace_id
    where config.public_id = target_public_id
      and config.is_enabled;
    if not found then
        raise exception 'Customer chat is unavailable' using errcode = '22023';
    end if;
    if session_token_hash is null or session_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Customer session hash is invalid' using errcode = '22023';
    end if;
    if session_expires_at is null
       or session_expires_at <= created_timestamp
       or session_expires_at > created_timestamp + interval '7 days' then
        raise exception 'Customer session expiry is invalid' using errcode = '22023';
    end if;

    perform app_private.consume_customer_rate_limit('session_minute', config_record.public_id);
    perform app_private.consume_customer_rate_limit('session_hour', config_record.public_id);

    insert into public.customer_sessions (
        id, workspace_id, chat_public_id, token_hash, created_at, last_seen_at, expires_at
    ) values (
        generated_session_id,
        config_record.workspace_id,
        config_record.public_id,
        session_token_hash,
        created_timestamp,
        created_timestamp,
        session_expires_at
    );
    insert into public.conversations (
        id, workspace_id, customer_session_id, status, created_at, updated_at
    ) values (
        generated_conversation_id,
        config_record.workspace_id,
        generated_session_id,
        'open',
        created_timestamp,
        created_timestamp
    );

    customer_session_id := generated_session_id;
    conversation_id := generated_conversation_id;
    workspace_id := config_record.workspace_id;
    workspace_name := config_record.workspace_name;
    expires_at := session_expires_at;
    return next;
end;
$$;

create or replace function public.begin_customer_chat_turn(
    target_conversation_id uuid,
    session_token_hash text,
    target_client_message_id uuid,
    message_content text
)
returns table (
    turn_id uuid,
    workspace_id uuid,
    conversation_id uuid,
    turn_status text,
    is_replay boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    existing_turn public.conversation_turns%rowtype;
    generated_turn_id uuid := gen_random_uuid();
    generated_customer_message_id uuid := gen_random_uuid();
    normalized_content text;
    persisted_content text;
    existing_turn_count integer;
    request_timestamp timestamptz := now();
begin
    if target_conversation_id is null or target_client_message_id is null
       or session_token_hash is null or session_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Customer turn identity is invalid' using errcode = '22023';
    end if;
    normalized_content := regexp_replace(
        btrim(coalesce(message_content, '')),
        '[[:space:]]+',
        ' ',
        'g'
    );
    if char_length(normalized_content) not between 1 and 2000 then
        raise exception 'Customer message length is invalid' using errcode = '22023';
    end if;

    select conversation.* into conversation_record
    from public.conversations as conversation
    where conversation.id = target_conversation_id
    for update;
    if not found then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;
    select session.* into session_record
    from public.customer_sessions as session
    where session.id = conversation_record.customer_session_id
      and session.workspace_id = conversation_record.workspace_id
      and session.token_hash = session_token_hash
    for update;
    if not found or session_record.expires_at <= request_timestamp then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;
    if not exists (
        select 1 from public.workspace_chat_configs as config
        where config.workspace_id = conversation_record.workspace_id
          and config.public_id = session_record.chat_public_id
          and config.is_enabled
    ) then
        raise exception 'Customer chat is disabled' using errcode = '42501';
    end if;
    if conversation_record.status <> 'open' then
        raise exception 'Conversation is not open' using errcode = '55000';
    end if;

    select turn.* into existing_turn
    from public.conversation_turns as turn
    where turn.conversation_id = conversation_record.id
      and turn.client_message_id = target_client_message_id
    for update;
    if found then
        select message.content into persisted_content
        from public.messages as message
        where message.id = existing_turn.customer_message_id
          and message.turn_id = existing_turn.id
          and message.role = 'customer';
        if not found or persisted_content is distinct from normalized_content then
            raise exception 'Client message ID cannot be reused for different content'
                using errcode = '22023';
        end if;
        if existing_turn.status = 'failed' then
            perform app_private.consume_customer_rate_limit('turn_minute', session_record.id);
            perform app_private.consume_customer_rate_limit('turn_hour', session_record.id);
            update public.conversation_turns as turn
            set status = 'processing', safe_error_code = null
            where turn.id = existing_turn.id;
            update public.customer_sessions as session
            set last_seen_at = request_timestamp
            where session.id = session_record.id;
            turn_id := existing_turn.id;
            workspace_id := existing_turn.workspace_id;
            conversation_id := existing_turn.conversation_id;
            turn_status := 'processing';
            is_replay := false;
            return next;
            return;
        end if;
        turn_id := existing_turn.id;
        workspace_id := existing_turn.workspace_id;
        conversation_id := existing_turn.conversation_id;
        turn_status := existing_turn.status;
        is_replay := true;
        return next;
        return;
    end if;

    select count(*)::integer into existing_turn_count
    from public.conversation_turns as turn
    where turn.conversation_id = conversation_record.id;
    if existing_turn_count >= 100 then
        raise exception 'Conversation customer turn limit reached' using errcode = '54000';
    end if;
    if exists (
        select 1 from public.conversation_turns as turn
        where turn.conversation_id = conversation_record.id
          and turn.created_at > request_timestamp - interval '1 second'
    ) then
        raise exception 'A customer turn was created too recently' using errcode = '55000';
    end if;

    perform app_private.consume_customer_rate_limit('turn_minute', session_record.id);
    perform app_private.consume_customer_rate_limit('turn_hour', session_record.id);

    insert into public.conversation_turns (
        id, workspace_id, conversation_id, client_message_id, status,
        created_at, updated_at
    ) values (
        generated_turn_id,
        conversation_record.workspace_id,
        conversation_record.id,
        target_client_message_id,
        'processing',
        request_timestamp,
        request_timestamp
    );
    insert into public.messages (
        id, workspace_id, conversation_id, turn_id, role, content, created_at
    ) values (
        generated_customer_message_id,
        conversation_record.workspace_id,
        conversation_record.id,
        generated_turn_id,
        'customer',
        normalized_content,
        request_timestamp
    );
    update public.conversation_turns as turn
    set customer_message_id = generated_customer_message_id
    where turn.id = generated_turn_id;
    update public.conversations as conversation
    set last_message_at = request_timestamp
    where conversation.id = conversation_record.id;
    update public.customer_sessions as session
    set last_seen_at = request_timestamp
    where session.id = session_record.id;

    turn_id := generated_turn_id;
    workspace_id := conversation_record.workspace_id;
    conversation_id := conversation_record.id;
    turn_status := 'processing';
    is_replay := false;
    return next;
end;
$$;

create or replace function public.set_customer_message_feedback(
    target_conversation_id uuid,
    session_token_hash text,
    target_message_id uuid,
    submitted_rating text
)
returns table (
    message_id uuid,
    rating text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    request_timestamp timestamptz := now();
begin
    if target_conversation_id is null or target_message_id is null
       or session_token_hash is null or session_token_hash !~ '^[0-9a-f]{64}$'
       or submitted_rating is null
       or submitted_rating not in ('positive', 'negative') then
        raise exception 'Customer feedback is invalid' using errcode = '22023';
    end if;

    select conversation.* into conversation_record
    from public.conversations as conversation
    where conversation.id = target_conversation_id;
    if not found then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;

    select session.* into session_record
    from public.customer_sessions as session
    where session.id = conversation_record.customer_session_id
      and session.workspace_id = conversation_record.workspace_id
      and session.token_hash = session_token_hash
    for update;
    if not found or session_record.expires_at <= request_timestamp then
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;

    if not exists (
        select 1 from public.workspace_chat_configs as config
        where config.workspace_id = conversation_record.workspace_id
          and config.public_id = session_record.chat_public_id
          and config.is_enabled
    ) then
        raise exception 'Customer chat is disabled' using errcode = '42501';
    end if;

    if not exists (
        select 1 from public.messages as message
        where message.id = target_message_id
          and message.workspace_id = conversation_record.workspace_id
          and message.conversation_id = conversation_record.id
          and message.role = 'assistant'
    ) then
        raise exception 'Feedback target is unavailable' using errcode = '55000';
    end if;

    perform app_private.consume_customer_rate_limit('feedback_minute', session_record.id);

    insert into public.message_feedback (
        workspace_id,
        conversation_id,
        message_id,
        rating,
        created_at,
        updated_at
    ) values (
        conversation_record.workspace_id,
        conversation_record.id,
        target_message_id,
        submitted_rating,
        request_timestamp,
        request_timestamp
    )
    on conflict on constraint message_feedback_message_unique do update
    set rating = excluded.rating,
        updated_at = excluded.updated_at;

    update public.customer_sessions as session
    set last_seen_at = request_timestamp
    where session.id = session_record.id;

    message_id := target_message_id;
    rating := submitted_rating;
    return next;
end;
$$;

drop function public.request_customer_human_support(uuid,text);
create function public.request_customer_human_support(target_conversation_id uuid, session_token_hash text)
returns table (conversation_id uuid, status text, human_requested_at timestamptz, escalation_id uuid, triage_status text, is_new_request boolean)
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
    perform app_private.consume_customer_rate_limit('human_minute', session_record.id);
    is_new_request := conversation_record.status = 'open';
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

-- Existing get_customer_conversation remains a trusted internal context read (no browser quota).
create function public.get_customer_conversation_history(target_conversation_id uuid, session_token_hash text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    session_id uuid;
begin
    select session.id into session_id
    from public.conversations as conversation
    join public.customer_sessions as session
      on session.id=conversation.customer_session_id and session.workspace_id=conversation.workspace_id
    join public.workspace_chat_configs as config
      on config.workspace_id=conversation.workspace_id and config.public_id=session.chat_public_id
    where conversation.id=target_conversation_id and session.token_hash=session_token_hash
      and session.expires_at > now() and config.is_enabled;
    if not found then
        -- Preserve the existing validator's disabled/invalid-session behavior without consuming quota.
        perform public.get_customer_conversation(target_conversation_id, session_token_hash);
        raise exception 'Customer session is invalid or expired' using errcode = '28000';
    end if;
    perform app_private.consume_customer_rate_limit('history_minute', session_id);
    return public.get_customer_conversation(target_conversation_id, session_token_hash);
end;
$$;
revoke all on function public.get_customer_conversation_history(uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.get_customer_conversation_history(uuid,text) to service_role;
revoke all on function public.request_customer_human_support(uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.request_customer_human_support(uuid,text) to service_role;
-- CREATE OR REPLACE preserves the existing server-only grants on session/turn/feedback RPCs.
