-- Hosted setup regression fixes. Preserve empty search paths and existing grants.

create or replace function public.search_knowledge_chunks(
    target_workspace_id uuid,
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
    query_vector extensions.vector(768);
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required for knowledge retrieval'
            using errcode = '28000';
    end if;
    if target_workspace_id is null
       or not (select app_private.is_workspace_member(target_workspace_id)) then
        raise exception 'Workspace membership is required for knowledge retrieval'
            using errcode = '42501';
    end if;
    if expected_provider is null
       or char_length(expected_provider) not between 1 and 50
       or expected_provider <> btrim(expected_provider)
       or expected_model is null
       or char_length(expected_model) not between 1 and 100
       or expected_model <> btrim(expected_model)
       or expected_dimension is distinct from 768 then
        raise exception 'Embedding compatibility metadata is invalid'
            using errcode = '22023';
    end if;
    if match_count is null or match_count not between 1 and 12 then
        raise exception 'Match count must be between 1 and 12'
            using errcode = '22023';
    end if;
    if jsonb_typeof(query_embedding) is distinct from 'array'
       or jsonb_array_length(query_embedding) <> 768
       or exists (
            select 1
            from jsonb_array_elements(query_embedding) as value
            where jsonb_typeof(value) <> 'number'
       ) then
        raise exception 'Query embedding must contain exactly 768 numeric values'
            using errcode = '22023';
    end if;

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
        (1.0::double precision - (chunk.embedding OPERATOR(extensions.<=>) query_vector))::double precision
    from public.knowledge_chunks as chunk
    join public.knowledge_sources as source
      on source.id = chunk.source_id
     and source.workspace_id = chunk.workspace_id
    where source.workspace_id = target_workspace_id
      and chunk.workspace_id = target_workspace_id
      and source.status = 'ready'
      and source.indexed_at is not null
      and source.embedding_provider = expected_provider
      and source.embedding_model = expected_model
      and source.embedding_dimension = expected_dimension
      and chunk.embedding is not null
    order by chunk.embedding OPERATOR(extensions.<=>) query_vector, source.id, chunk.chunk_index
    limit match_count;
end;
$$;

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

create or replace function public.search_customer_chat_knowledge(
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
        (1.0::double precision - (chunk.embedding OPERATOR(extensions.<=>) query_vector))::double precision
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
    order by chunk.embedding OPERATOR(extensions.<=>) query_vector, source.id, chunk.chunk_index
    limit match_count;
end;
$$;
