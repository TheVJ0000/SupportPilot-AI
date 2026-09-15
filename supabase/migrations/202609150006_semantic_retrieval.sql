create function public.search_knowledge_chunks(
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
        (1.0::double precision - (chunk.embedding <=> query_vector))::double precision
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
    order by chunk.embedding <=> query_vector, source.id, chunk.chunk_index
    limit match_count;
end;
$$;

revoke all on function public.search_knowledge_chunks(
    uuid, jsonb, text, text, integer, integer
) from public, anon, authenticated;

grant execute on function public.search_knowledge_chunks(
    uuid, jsonb, text, text, integer, integer
) to authenticated;
