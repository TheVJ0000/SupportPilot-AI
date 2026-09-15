-- SupportPilot AI Phase 5B.3: anonymous feedback and human handoff foundation.

alter table public.conversations
add column human_requested_at timestamptz;

update public.conversations
set human_requested_at = updated_at
where status = 'human_requested';

alter table public.conversations
add constraint conversations_human_request_state_consistent check (
    (status = 'open' and human_requested_at is null)
    or (status = 'human_requested' and human_requested_at is not null)
    or status = 'closed'
);

alter table public.messages
add constraint messages_id_workspace_conversation_unique
    unique (id, workspace_id, conversation_id);

create table public.message_feedback (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    conversation_id uuid not null,
    message_id uuid not null,
    rating text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint message_feedback_message_unique unique (message_id),
    constraint message_feedback_rating_allowed check (rating in ('positive', 'negative')),
    constraint message_feedback_message_scope_fk
        foreign key (message_id, workspace_id, conversation_id)
        references public.messages (id, workspace_id, conversation_id)
        on delete cascade,
    constraint message_feedback_conversation_scope_fk
        foreign key (conversation_id, workspace_id)
        references public.conversations (id, workspace_id)
        on delete cascade
);

create trigger message_feedback_set_updated_at
before update on public.message_feedback
for each row execute function app_private.set_updated_at();

create index message_feedback_workspace_conversation_idx
    on public.message_feedback (workspace_id, conversation_id, created_at, id);

alter table public.message_feedback enable row level security;
revoke all on table public.message_feedback from public, anon, authenticated, service_role;
grant select on table public.message_feedback to authenticated;

create policy message_feedback_select_for_members
on public.message_feedback
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create function public.set_customer_message_feedback(
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

create function public.request_customer_human_support(
    target_conversation_id uuid,
    session_token_hash text
)
returns table (
    conversation_id uuid,
    status text,
    human_requested_at timestamptz
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
    if target_conversation_id is null
       or session_token_hash is null or session_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Human support request is invalid' using errcode = '22023';
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

    if conversation_record.status = 'closed' then
        raise exception 'Conversation is closed' using errcode = '55000';
    end if;
    if conversation_record.status = 'open' then
        update public.conversations as conversation
        set status = 'human_requested',
            human_requested_at = request_timestamp
        where conversation.id = conversation_record.id
        returning conversation.human_requested_at
        into conversation_record.human_requested_at;
    end if;

    update public.customer_sessions as session
    set last_seen_at = request_timestamp
    where session.id = session_record.id;

    conversation_id := conversation_record.id;
    status := 'human_requested';
    human_requested_at := conversation_record.human_requested_at;
    return next;
end;
$$;

create or replace function public.get_customer_chat_turn_result(
    target_conversation_id uuid,
    session_token_hash text,
    target_client_message_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    turn_record public.conversation_turns%rowtype;
    assistant_record public.messages%rowtype;
begin
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
      and session.token_hash = session_token_hash;
    if not found or session_record.expires_at <= now() then
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
    select turn.* into turn_record
    from public.conversation_turns as turn
    where turn.conversation_id = conversation_record.id
      and turn.client_message_id = target_client_message_id
      and turn.status = 'completed';
    if not found then
        raise exception 'Completed customer turn was not found' using errcode = '55000';
    end if;
    select message.* into assistant_record
    from public.messages as message
    where message.id = turn_record.assistant_message_id
      and message.workspace_id = conversation_record.workspace_id
      and message.conversation_id = conversation_record.id
      and message.turn_id = turn_record.id
      and message.role = 'assistant';
    if not found then
        raise exception 'Completed customer turn is inconsistent' using errcode = '55000';
    end if;
    return jsonb_build_object(
        'turn_id', turn_record.id,
        'conversation_id', conversation_record.id,
        'message_id', assistant_record.id,
        'client_message_id', turn_record.client_message_id,
        'answer_status', assistant_record.answer_status,
        'answer', assistant_record.content,
        'citations', coalesce((
            select jsonb_agg(jsonb_build_object(
                'source_id', citation.source_id,
                'source_title', citation.source_title,
                'source_type', citation.source_type,
                'chunk_index', citation.chunk_index,
                'locator', citation.locator
            ) order by citation.ordinal)
            from public.message_citations as citation
            where citation.message_id = assistant_record.id
              and citation.workspace_id = assistant_record.workspace_id
        ), '[]'::jsonb)
    );
end;
$$;

create or replace function public.get_customer_conversation(
    target_conversation_id uuid,
    session_token_hash text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
begin
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
      and session.token_hash = session_token_hash;
    if not found or session_record.expires_at <= now() then
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
    return jsonb_build_object(
        'conversation_id', conversation_record.id,
        'status', conversation_record.status,
        'human_requested_at', conversation_record.human_requested_at,
        'messages', coalesce((
            select jsonb_agg(jsonb_build_object(
                'id', message.id,
                'role', message.role,
                'content', message.content,
                'answer_status', message.answer_status,
                'created_at', message.created_at,
                'feedback', (
                    select feedback.rating
                    from public.message_feedback as feedback
                    where feedback.message_id = message.id
                      and feedback.workspace_id = message.workspace_id
                      and feedback.conversation_id = message.conversation_id
                ),
                'citations', coalesce((
                    select jsonb_agg(jsonb_build_object(
                        'source_id', citation.source_id,
                        'source_title', citation.source_title,
                        'source_type', citation.source_type,
                        'chunk_index', citation.chunk_index,
                        'locator', citation.locator
                    ) order by citation.ordinal)
                    from public.message_citations as citation
                    where citation.message_id = message.id
                      and citation.workspace_id = message.workspace_id
                ), '[]'::jsonb)
            ) order by turn.created_at,
                       case message.role when 'customer' then 0 else 1 end,
                       message.created_at,
                       message.id)
            from public.messages as message
            join public.conversation_turns as turn
              on turn.id = message.turn_id
             and turn.workspace_id = message.workspace_id
             and turn.conversation_id = message.conversation_id
            where message.conversation_id = conversation_record.id
              and message.workspace_id = conversation_record.workspace_id
        ), '[]'::jsonb)
    );
end;
$$;

revoke all on function public.set_customer_message_feedback(uuid, text, uuid, text)
    from public, anon, authenticated, service_role;
revoke all on function public.request_customer_human_support(uuid, text)
    from public, anon, authenticated, service_role;

grant execute on function public.set_customer_message_feedback(uuid, text, uuid, text)
    to service_role;
grant execute on function public.request_customer_human_support(uuid, text)
    to service_role;
