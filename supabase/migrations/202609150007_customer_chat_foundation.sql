-- SupportPilot AI Phase 5A: secure anonymous customer sessions and conversation persistence.

create table public.workspace_chat_configs (
    workspace_id uuid primary key references public.workspaces (id) on delete cascade,
    public_id uuid not null default gen_random_uuid(),
    is_enabled boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint workspace_chat_configs_public_id_unique unique (public_id),
    constraint workspace_chat_configs_public_workspace_unique unique (public_id, workspace_id)
);

create trigger workspace_chat_configs_set_updated_at
before update on public.workspace_chat_configs
for each row execute function app_private.set_updated_at();

insert into public.workspace_chat_configs (workspace_id)
select workspace.id
from public.workspaces as workspace
on conflict (workspace_id) do nothing;

create function app_private.create_workspace_chat_config()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.workspace_chat_configs (workspace_id)
    values (new.id)
    on conflict (workspace_id) do nothing;
    return new;
end;
$$;

create trigger create_workspace_chat_config_after_workspace
after insert on public.workspaces
for each row execute function app_private.create_workspace_chat_config();

create table public.customer_sessions (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    chat_public_id uuid not null,
    token_hash text not null,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at timestamptz not null,
    constraint customer_sessions_id_workspace_unique unique (id, workspace_id),
    constraint customer_sessions_token_hash_unique unique (token_hash),
    constraint customer_sessions_token_hash_format
        check (token_hash ~ '^[0-9a-f]{64}$'),
    constraint customer_sessions_expiry_bounded check (
        expires_at > created_at
        and expires_at <= created_at + interval '7 days'
    ),
    constraint customer_sessions_last_seen_valid check (last_seen_at >= created_at),
    constraint customer_sessions_chat_config_fk
        foreign key (chat_public_id, workspace_id)
        references public.workspace_chat_configs (public_id, workspace_id)
        on delete restrict
);

create index customer_sessions_workspace_id_idx
    on public.customer_sessions (workspace_id);
create index customer_sessions_expires_at_idx
    on public.customer_sessions (expires_at);

create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    customer_session_id uuid not null,
    status text not null default 'open',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    last_message_at timestamptz,
    constraint conversations_id_workspace_unique unique (id, workspace_id),
    constraint conversations_id_workspace_session_unique
        unique (id, workspace_id, customer_session_id),
    constraint conversations_status_allowed
        check (status in ('open', 'human_requested', 'closed')),
    constraint conversations_session_workspace_fk
        foreign key (customer_session_id, workspace_id)
        references public.customer_sessions (id, workspace_id)
        on delete cascade
);

create trigger conversations_set_updated_at
before update on public.conversations
for each row execute function app_private.set_updated_at();

create index conversations_workspace_last_message_idx
    on public.conversations (workspace_id, last_message_at desc, id);
create index conversations_session_id_idx
    on public.conversations (customer_session_id);

create table public.conversation_turns (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    conversation_id uuid not null,
    client_message_id uuid not null,
    status text not null,
    customer_message_id uuid,
    assistant_message_id uuid,
    safe_error_code text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint conversation_turns_id_scope_unique
        unique (id, workspace_id, conversation_id),
    constraint conversation_turns_client_message_unique
        unique (conversation_id, client_message_id),
    constraint conversation_turns_status_allowed
        check (status in ('processing', 'completed', 'failed')),
    constraint conversation_turns_error_code_allowed check (
        safe_error_code is null
        or safe_error_code in ('retrieval_failed', 'generation_failed', 'temporarily_unavailable')
    ),
    constraint conversation_turns_state_consistent check (
        (
            status = 'processing'
            and assistant_message_id is null
            and safe_error_code is null
        )
        or (
            status = 'completed'
            and customer_message_id is not null
            and assistant_message_id is not null
            and safe_error_code is null
        )
        or (
            status = 'failed'
            and customer_message_id is not null
            and assistant_message_id is null
            and safe_error_code is not null
        )
    ),
    constraint conversation_turns_conversation_workspace_fk
        foreign key (conversation_id, workspace_id)
        references public.conversations (id, workspace_id)
        on delete cascade
);

create trigger conversation_turns_set_updated_at
before update on public.conversation_turns
for each row execute function app_private.set_updated_at();

create index conversation_turns_workspace_conversation_idx
    on public.conversation_turns (workspace_id, conversation_id, created_at, id);

create table public.messages (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    conversation_id uuid not null,
    turn_id uuid not null,
    role text not null,
    content text not null,
    answer_status text,
    created_at timestamptz not null default now(),
    constraint messages_id_scope_unique
        unique (id, workspace_id, conversation_id, turn_id),
    constraint messages_turn_role_unique unique (turn_id, role),
    constraint messages_role_allowed check (role in ('customer', 'assistant')),
    constraint messages_content_matches_role check (
        (
            role = 'customer'
            and char_length(content) between 1 and 2000
            and btrim(content) <> ''
            and answer_status is null
        )
        or (
            role = 'assistant'
            and char_length(content) between 1 and 4000
            and btrim(content) <> ''
            and answer_status in ('answered', 'insufficient_evidence')
        )
    ),
    constraint messages_turn_scope_fk
        foreign key (turn_id, workspace_id, conversation_id)
        references public.conversation_turns (id, workspace_id, conversation_id)
        on delete cascade
);

alter table public.conversation_turns
add constraint conversation_turns_customer_message_fk
    foreign key (customer_message_id, workspace_id, conversation_id, id)
    references public.messages (id, workspace_id, conversation_id, turn_id)
    deferrable initially deferred,
add constraint conversation_turns_assistant_message_fk
    foreign key (assistant_message_id, workspace_id, conversation_id, id)
    references public.messages (id, workspace_id, conversation_id, turn_id)
    deferrable initially deferred;

create index messages_conversation_chronological_idx
    on public.messages (conversation_id, created_at, id);

create function app_private.is_valid_customer_citation_locator(
    locator jsonb,
    citation_source_type text
)
returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
    locator_kind text;
    range_start integer;
    range_end integer;
begin
    if jsonb_typeof(locator) is distinct from 'object'
       or jsonb_typeof(locator -> 'kind') is distinct from 'string' then
        return false;
    end if;
    locator_kind := locator ->> 'kind';
    if citation_source_type = 'faq' then
        return locator = '{"kind":"faq"}'::jsonb;
    end if;
    if citation_source_type <> 'file' or locator_kind = 'faq' then
        return false;
    end if;
    if locator_kind = 'pdf' then
        if locator - array['kind', 'page_start', 'page_end']::text[] <> '{}'::jsonb
           or not (locator ?& array['kind', 'page_start', 'page_end'])
           or jsonb_typeof(locator -> 'page_start') is distinct from 'number'
           or jsonb_typeof(locator -> 'page_end') is distinct from 'number'
           or (locator ->> 'page_start') !~ '^[1-9][0-9]*$'
           or (locator ->> 'page_end') !~ '^[1-9][0-9]*$' then
            return false;
        end if;
        range_start := (locator ->> 'page_start')::integer;
        range_end := (locator ->> 'page_end')::integer;
        return range_start <= range_end and range_end <= 300;
    end if;
    if locator_kind = 'docx' then
        if locator - array['kind', 'block_start', 'block_end']::text[] <> '{}'::jsonb
           or not (locator ?& array['kind', 'block_start', 'block_end'])
           or jsonb_typeof(locator -> 'block_start') is distinct from 'number'
           or jsonb_typeof(locator -> 'block_end') is distinct from 'number'
           or (locator ->> 'block_start') !~ '^[1-9][0-9]*$'
           or (locator ->> 'block_end') !~ '^[1-9][0-9]*$' then
            return false;
        end if;
        range_start := (locator ->> 'block_start')::integer;
        range_end := (locator ->> 'block_end')::integer;
        return range_start <= range_end and range_end <= 1000000;
    end if;
    if locator_kind in ('text', 'markdown') then
        if locator - array['kind', 'line_start', 'line_end']::text[] <> '{}'::jsonb
           or not (locator ?& array['kind', 'line_start', 'line_end'])
           or jsonb_typeof(locator -> 'line_start') is distinct from 'number'
           or jsonb_typeof(locator -> 'line_end') is distinct from 'number'
           or (locator ->> 'line_start') !~ '^[1-9][0-9]*$'
           or (locator ->> 'line_end') !~ '^[1-9][0-9]*$' then
            return false;
        end if;
        range_start := (locator ->> 'line_start')::integer;
        range_end := (locator ->> 'line_end')::integer;
        return range_start <= range_end and range_end <= 1000000;
    end if;
    return false;
end;
$$;

alter table public.messages
add constraint messages_id_workspace_unique unique (id, workspace_id);

create table public.message_citations (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    message_id uuid not null,
    ordinal integer not null,
    source_id uuid not null,
    source_title text not null,
    source_type text not null,
    chunk_index integer not null,
    locator jsonb not null,
    created_at timestamptz not null default now(),
    constraint message_citations_message_ordinal_unique unique (message_id, ordinal),
    constraint message_citations_ordinal_bounded check (ordinal between 1 and 8),
    constraint message_citations_source_title_valid check (
        source_title = btrim(source_title)
        and char_length(source_title) between 1 and 200
    ),
    constraint message_citations_source_type_allowed check (source_type in ('file', 'faq')),
    constraint message_citations_chunk_index_nonnegative check (chunk_index >= 0),
    constraint message_citations_locator_valid check (
        app_private.is_valid_customer_citation_locator(locator, source_type)
    ),
    constraint message_citations_message_workspace_fk
        foreign key (message_id, workspace_id)
        references public.messages (id, workspace_id)
        on delete cascade
);

create index message_citations_workspace_message_idx
    on public.message_citations (workspace_id, message_id, ordinal);

alter table public.workspace_chat_configs enable row level security;
alter table public.customer_sessions enable row level security;
alter table public.conversations enable row level security;
alter table public.conversation_turns enable row level security;
alter table public.messages enable row level security;
alter table public.message_citations enable row level security;

revoke all on table public.workspace_chat_configs from public, anon, authenticated, service_role;
revoke all on table public.customer_sessions from public, anon, authenticated, service_role;
revoke all on table public.conversations from public, anon, authenticated, service_role;
revoke all on table public.conversation_turns from public, anon, authenticated, service_role;
revoke all on table public.messages from public, anon, authenticated, service_role;
revoke all on table public.message_citations from public, anon, authenticated, service_role;

grant select on table public.workspace_chat_configs to authenticated;
grant select on table public.conversations to authenticated;
grant select on table public.conversation_turns to authenticated;
grant select on table public.messages to authenticated;
grant select on table public.message_citations to authenticated;

create policy workspace_chat_configs_select_for_members
on public.workspace_chat_configs
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create policy conversations_select_for_members
on public.conversations
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create policy conversation_turns_select_for_members
on public.conversation_turns
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create policy messages_select_for_members
on public.messages
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create policy message_citations_select_for_members
on public.message_citations
for select to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create function public.create_customer_chat_session(
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
    config_record public.workspace_chat_configs%rowtype;
    generated_session_id uuid := gen_random_uuid();
    generated_conversation_id uuid := gen_random_uuid();
    selected_workspace_name text;
    created_timestamp timestamptz := now();
begin
    select config, workspace.name
    into config_record, selected_workspace_name
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
    workspace_name := selected_workspace_name;
    expires_at := session_expires_at;
    return next;
end;
$$;

create function public.begin_customer_chat_turn(
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

create function public.search_customer_chat_knowledge(
    target_conversation_id uuid,
    session_token_hash text,
    query_embedding jsonb,
    expected_provider text,
    expected_model text,
    expected_dimension integer,
    match_count integer default 8
)
returns table (
    chunk_id uuid,
    source_id uuid,
    source_title text,
    source_type text,
    chunk_index integer,
    content text,
    locator jsonb,
    similarity double precision
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    derived_workspace_id uuid;
    query_vector extensions.vector(768);
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
    if expected_provider is null
       or char_length(expected_provider) not between 1 and 50
       or expected_provider <> btrim(expected_provider)
       or expected_model is null
       or char_length(expected_model) not between 1 and 100
       or expected_model <> btrim(expected_model)
       or expected_dimension is distinct from 768 then
        raise exception 'Embedding compatibility metadata is invalid' using errcode = '22023';
    end if;
    if match_count is null or match_count not between 1 and 12 then
        raise exception 'Match count must be between 1 and 12' using errcode = '22023';
    end if;
    if jsonb_typeof(query_embedding) is distinct from 'array'
       or jsonb_array_length(query_embedding) <> 768
       or exists (
            select 1 from jsonb_array_elements(query_embedding) as value
            where jsonb_typeof(value) <> 'number'
       ) then
        raise exception 'Query embedding must contain exactly 768 numeric values'
            using errcode = '22023';
    end if;

    derived_workspace_id := conversation_record.workspace_id;
    query_vector := (query_embedding::text)::extensions.vector(768);
    return query
    select
        chunk.id,
        source.id,
        source.title,
        source.source_type,
        chunk.chunk_index,
        chunk.content,
        chunk.locator,
        (1.0::double precision - (chunk.embedding <=> query_vector))::double precision
    from public.knowledge_chunks as chunk
    join public.knowledge_sources as source
      on source.id = chunk.source_id
     and source.workspace_id = chunk.workspace_id
    where source.workspace_id = derived_workspace_id
      and chunk.workspace_id = derived_workspace_id
      and source.status = 'ready'
      and source.indexed_at is not null
      and source.embedding_provider = expected_provider
      and source.embedding_model = expected_model
      and source.embedding_dimension = expected_dimension
      and chunk.embedding is not null
    order by chunk.embedding <=> query_vector, source.id, chunk.chunk_index
    limit match_count;
end;
$$;

create function public.complete_customer_chat_turn(
    target_turn_id uuid,
    session_token_hash text,
    submitted_answer_status text,
    answer_content text,
    citation_payload jsonb
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    turn_record public.conversation_turns%rowtype;
    conversation_record public.conversations%rowtype;
    session_record public.customer_sessions%rowtype;
    citation_record jsonb;
    citation_count integer;
    citation_index integer;
    generated_assistant_message_id uuid := gen_random_uuid();
    completion_timestamp timestamptz := now();
begin
    select turn.* into turn_record
    from public.conversation_turns as turn
    where turn.id = target_turn_id
    for update;
    if not found then
        raise exception 'Customer turn was not found' using errcode = '22023';
    end if;
    select conversation.* into conversation_record
    from public.conversations as conversation
    where conversation.id = turn_record.conversation_id
      and conversation.workspace_id = turn_record.workspace_id;
    if not found then
        raise exception 'Conversation scope is invalid' using errcode = '55000';
    end if;
    select session.* into session_record
    from public.customer_sessions as session
    where session.id = conversation_record.customer_session_id
      and session.workspace_id = conversation_record.workspace_id
      and session.token_hash = session_token_hash
    for update;
    if not found or session_record.expires_at <= completion_timestamp then
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
    if turn_record.status <> 'processing' then
        raise exception 'Only a processing turn can be completed' using errcode = '55000';
    end if;
    if submitted_answer_status not in ('answered', 'insufficient_evidence')
       or answer_content is null
       or char_length(answer_content) not between 1 and 4000
       or btrim(answer_content) = '' then
        raise exception 'Assistant answer is invalid' using errcode = '22023';
    end if;
    if jsonb_typeof(citation_payload) is distinct from 'array' then
        raise exception 'Citation payload must be an array' using errcode = '22023';
    end if;
    citation_count := jsonb_array_length(citation_payload);
    if citation_count > 8
       or (submitted_answer_status = 'answered' and citation_count < 1)
       or (submitted_answer_status = 'insufficient_evidence' and citation_count <> 0) then
        raise exception 'Citation count does not match answer status' using errcode = '22023';
    end if;

    for citation_record, citation_index in
        select element.value, element.ordinality::integer
        from jsonb_array_elements(citation_payload) with ordinality
            as element(value, ordinality)
        order by element.ordinality
    loop
        if jsonb_typeof(citation_record) is distinct from 'object'
           or citation_record - array[
               'source_id', 'source_title', 'source_type', 'chunk_index', 'locator'
           ]::text[] <> '{}'::jsonb
           or not (citation_record ?& array[
               'source_id', 'source_title', 'source_type', 'chunk_index', 'locator'
           ])
           or jsonb_typeof(citation_record -> 'source_id') is distinct from 'string'
           or (citation_record ->> 'source_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
           or jsonb_typeof(citation_record -> 'source_title') is distinct from 'string'
           or char_length(citation_record ->> 'source_title') not between 1 and 200
           or (citation_record ->> 'source_title') <> btrim(citation_record ->> 'source_title')
           or jsonb_typeof(citation_record -> 'source_type') is distinct from 'string'
           or (citation_record ->> 'source_type') not in ('file', 'faq')
           or jsonb_typeof(citation_record -> 'chunk_index') is distinct from 'number'
           or (citation_record ->> 'chunk_index') !~ '^(0|[1-9][0-9]*)$'
           or jsonb_typeof(citation_record -> 'locator') is distinct from 'object'
           or not app_private.is_valid_customer_citation_locator(
               citation_record -> 'locator', citation_record ->> 'source_type'
           ) then
            raise exception 'Citation payload contains malformed fields' using errcode = '22023';
        end if;
        if not exists (
            select 1
            from public.knowledge_sources as source
            join public.knowledge_chunks as chunk
              on chunk.source_id = source.id
             and chunk.workspace_id = source.workspace_id
            where source.id = (citation_record ->> 'source_id')::uuid
              and source.workspace_id = conversation_record.workspace_id
              and source.title = citation_record ->> 'source_title'
              and source.source_type = citation_record ->> 'source_type'
              and chunk.chunk_index = (citation_record ->> 'chunk_index')::integer
              and chunk.locator = citation_record -> 'locator'
        ) then
            raise exception 'Citation does not match trusted workspace knowledge'
                using errcode = '22023';
        end if;
    end loop;

    insert into public.messages (
        id, workspace_id, conversation_id, turn_id, role,
        content, answer_status, created_at
    ) values (
        generated_assistant_message_id,
        conversation_record.workspace_id,
        conversation_record.id,
        turn_record.id,
        'assistant',
        answer_content,
        submitted_answer_status,
        completion_timestamp
    );
    insert into public.message_citations (
        workspace_id, message_id, ordinal, source_id,
        source_title, source_type, chunk_index, locator, created_at
    )
    select
        conversation_record.workspace_id,
        generated_assistant_message_id,
        element.ordinality::integer,
        (element.value ->> 'source_id')::uuid,
        element.value ->> 'source_title',
        element.value ->> 'source_type',
        (element.value ->> 'chunk_index')::integer,
        element.value -> 'locator',
        completion_timestamp
    from jsonb_array_elements(citation_payload) with ordinality
        as element(value, ordinality)
    order by element.ordinality;
    update public.conversation_turns as turn
    set status = 'completed',
        assistant_message_id = generated_assistant_message_id,
        safe_error_code = null
    where turn.id = turn_record.id;
    update public.conversations as conversation
    set last_message_at = completion_timestamp
    where conversation.id = conversation_record.id;
    update public.customer_sessions as session
    set last_seen_at = completion_timestamp
    where session.id = session_record.id;
    return true;
end;
$$;

create function public.fail_customer_chat_turn(
    target_turn_id uuid,
    session_token_hash text,
    submitted_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    turn_record public.conversation_turns%rowtype;
    conversation_record public.conversations%rowtype;
begin
    if submitted_error_code is null or submitted_error_code not in (
        'retrieval_failed', 'generation_failed', 'temporarily_unavailable'
    ) then
        raise exception 'Customer turn error code is invalid' using errcode = '22023';
    end if;
    select turn.* into turn_record
    from public.conversation_turns as turn
    where turn.id = target_turn_id
    for update;
    if not found then
        raise exception 'Customer turn was not found' using errcode = '22023';
    end if;
    select conversation.* into conversation_record
    from public.conversations as conversation
    join public.customer_sessions as session
      on session.id = conversation.customer_session_id
     and session.workspace_id = conversation.workspace_id
    where conversation.id = turn_record.conversation_id
      and conversation.workspace_id = turn_record.workspace_id
      and session.token_hash = session_token_hash;
    if not found then
        raise exception 'Customer session is invalid' using errcode = '28000';
    end if;
    if turn_record.status = 'failed'
       and turn_record.safe_error_code = submitted_error_code then
        return true;
    end if;
    if turn_record.status <> 'processing' then
        raise exception 'Only a processing turn can be failed' using errcode = '55000';
    end if;
    update public.conversation_turns as turn
    set status = 'failed', safe_error_code = submitted_error_code
    where turn.id = turn_record.id;
    return true;
end;
$$;

create function public.get_customer_chat_turn_result(
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

create function public.get_customer_conversation(
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
        'messages', coalesce((
            select jsonb_agg(jsonb_build_object(
                'id', message.id,
                'role', message.role,
                'content', message.content,
                'answer_status', message.answer_status,
                'created_at', message.created_at,
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

revoke all on function app_private.create_workspace_chat_config()
    from public, anon, authenticated, service_role;
revoke all on function app_private.is_valid_customer_citation_locator(jsonb, text)
    from public, anon, authenticated, service_role;
revoke all on function public.create_customer_chat_session(uuid, text, timestamptz)
    from public, anon, authenticated, service_role;
revoke all on function public.begin_customer_chat_turn(uuid, text, uuid, text)
    from public, anon, authenticated, service_role;
revoke all on function public.search_customer_chat_knowledge(
    uuid, text, jsonb, text, text, integer, integer
) from public, anon, authenticated, service_role;
revoke all on function public.complete_customer_chat_turn(uuid, text, text, text, jsonb)
    from public, anon, authenticated, service_role;
revoke all on function public.fail_customer_chat_turn(uuid, text, text)
    from public, anon, authenticated, service_role;
revoke all on function public.get_customer_chat_turn_result(uuid, text, uuid)
    from public, anon, authenticated, service_role;
revoke all on function public.get_customer_conversation(uuid, text)
    from public, anon, authenticated, service_role;

grant execute on function public.create_customer_chat_session(uuid, text, timestamptz)
    to service_role;
grant execute on function public.begin_customer_chat_turn(uuid, text, uuid, text)
    to service_role;
grant execute on function public.search_customer_chat_knowledge(
    uuid, text, jsonb, text, text, integer, integer
) to service_role;
grant execute on function public.complete_customer_chat_turn(uuid, text, text, text, jsonb)
    to service_role;
grant execute on function public.fail_customer_chat_turn(uuid, text, text)
    to service_role;
grant execute on function public.get_customer_chat_turn_result(uuid, text, uuid)
    to service_role;
grant execute on function public.get_customer_conversation(uuid, text)
    to service_role;
