create extension if not exists vector with schema extensions;

alter table public.knowledge_chunks
add column embedding extensions.vector(768);

alter table public.knowledge_sources
drop constraint knowledge_sources_last_error_code_allowed,
add column processing_stage text,
add column indexing_attempts integer not null default 0,
add column indexed_at timestamptz,
add column embedding_provider text,
add column embedding_model text,
add column embedding_dimension integer,
add column last_failure_stage text;

update public.knowledge_sources
set processing_stage = 'extraction'
where status = 'processing';

update public.knowledge_sources
set last_failure_stage = 'extraction'
where status = 'failed' and processing_attempts > 0;

alter table public.knowledge_sources
add constraint knowledge_sources_processing_stage_allowed
    check (processing_stage is null or processing_stage in ('extraction', 'indexing')),
add constraint knowledge_sources_processing_stage_consistent
    check ((status = 'processing') = (processing_stage is not null)),
add constraint knowledge_sources_indexing_attempts_nonnegative
    check (indexing_attempts >= 0),
add constraint knowledge_sources_last_failure_stage_allowed
    check (last_failure_stage is null or last_failure_stage in ('extraction', 'indexing')),
add constraint knowledge_sources_embedding_dimension_fixed
    check (embedding_dimension is null or embedding_dimension = 768),
add constraint knowledge_sources_embedding_provider_valid
    check (embedding_provider is null or (
        char_length(embedding_provider) between 1 and 50
        and embedding_provider = btrim(embedding_provider)
    )),
add constraint knowledge_sources_embedding_model_valid
    check (embedding_model is null or (
        char_length(embedding_model) between 1 and 100
        and embedding_model = btrim(embedding_model)
    )),
add constraint knowledge_sources_embedding_metadata_consistent check (
    (status = 'ready'
        and indexed_at is not null
        and embedding_provider is not null
        and embedding_model is not null
        and embedding_dimension = 768)
    or
    (status <> 'ready'
        and indexed_at is null
        and embedding_provider is null
        and embedding_model is null
        and embedding_dimension is null)
),
add constraint knowledge_sources_last_error_code_allowed check (
    last_error_code is null
    or last_error_code in (
        'invalid_file_content',
        'unsupported_encoding',
        'encrypted_pdf',
        'too_many_pages',
        'document_too_large',
        'no_extractable_text',
        'malformed_document',
        'storage_download_failed',
        'extraction_failed',
        'chunking_failed',
        'embedding_auth_failed',
        'embedding_rate_limited',
        'embedding_provider_unavailable',
        'embedding_invalid_response',
        'embedding_failed'
    )
);

grant select (
    processing_stage,
    indexing_attempts,
    indexed_at,
    embedding_provider,
    embedding_model,
    embedding_dimension,
    last_failure_stage
) on table public.knowledge_sources to authenticated;

create function app_private.enforce_knowledge_processing_transition()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.status = 'processing' and old.status is distinct from 'processing' then
        if new.processing_attempts > old.processing_attempts
           and new.indexing_attempts = old.indexing_attempts then
            new.processing_stage := 'extraction';
        elsif new.indexing_attempts > old.indexing_attempts
              and new.processing_attempts = old.processing_attempts then
            new.processing_stage := 'indexing';
        end if;
    end if;

    if old.status = 'processing' and new.status = 'pending' then
        if old.processing_stage <> 'extraction' then
            raise exception 'Only extraction can return a source to pending'
                using errcode = '55000';
        end if;
        new.processing_stage := null;
        new.last_failure_stage := null;
    elsif old.status = 'processing' and new.status = 'failed' then
        new.processing_stage := null;
        new.last_failure_stage := old.processing_stage;
    end if;

    return new;
end;
$$;

create trigger enforce_knowledge_processing_transition
before update on public.knowledge_sources
for each row execute function app_private.enforce_knowledge_processing_transition();

create or replace function public.begin_knowledge_extraction(target_source_id uuid)
returns table (
    source_id uuid,
    workspace_id uuid,
    source_type text,
    storage_path text,
    original_filename text,
    mime_type text,
    byte_size bigint,
    faq_question text,
    faq_answer text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to process a knowledge source'
            using errcode = '28000';
    end if;

    select source.* into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;

    if not found then
        raise exception 'Knowledge source was not found' using errcode = '22023';
    end if;
    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required' using errcode = '42501';
    end if;
    if source_record.status in ('uploading', 'ready') then
        raise exception 'Knowledge source cannot begin extraction in its current state'
            using errcode = '22023';
    end if;
    if source_record.status = 'failed'
       and source_record.last_failure_stage <> 'extraction' then
        raise exception 'An indexing failure must be retried through indexing'
            using errcode = '22023';
    end if;
    if source_record.status = 'processing' then
        if source_record.processing_stage <> 'extraction' then
            raise exception 'A different knowledge operation is active' using errcode = '55000';
        end if;
        if source_record.processing_started_at is not null
           and source_record.processing_started_at >= now() - interval '15 minutes' then
            raise exception 'Knowledge extraction is already active' using errcode = '55000';
        end if;
    end if;
    if source_record.status not in ('pending', 'failed', 'processing') then
        raise exception 'Knowledge source cannot begin extraction in its current state'
            using errcode = '22023';
    end if;

    update public.knowledge_sources as source
    set status = 'processing',
        processing_stage = 'extraction',
        processing_started_at = now(),
        processing_attempts = source.processing_attempts + 1,
        last_error_code = null,
        last_failure_stage = null
    where source.id = source_record.id
    returning source.* into source_record;

    source_id := source_record.id;
    workspace_id := source_record.workspace_id;
    source_type := source_record.source_type;
    storage_path := source_record.storage_path;
    original_filename := source_record.original_filename;
    mime_type := source_record.mime_type;
    byte_size := source_record.byte_size;
    faq_question := source_record.faq_question;
    faq_answer := source_record.faq_answer;
    return next;
end;
$$;

create or replace function public.fail_knowledge_extraction(
    target_source_id uuid,
    error_code text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to fail knowledge extraction'
            using errcode = '28000';
    end if;
    select source.* into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;
    if not found then
        raise exception 'Knowledge source was not found' using errcode = '22023';
    end if;
    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required' using errcode = '42501';
    end if;
    if source_record.status <> 'processing'
       or source_record.processing_stage <> 'extraction' then
        raise exception 'Only active extraction can be failed' using errcode = '55000';
    end if;
    if error_code is null or error_code not in (
        'invalid_file_content', 'unsupported_encoding', 'encrypted_pdf',
        'too_many_pages', 'document_too_large', 'no_extractable_text',
        'malformed_document', 'storage_download_failed', 'extraction_failed',
        'chunking_failed'
    ) then
        raise exception 'Extraction error code is not allowed' using errcode = '22023';
    end if;
    update public.knowledge_sources as source
    set status = 'failed',
        processing_stage = null,
        processing_started_at = null,
        last_failure_stage = 'extraction',
        last_error_code = error_code
    where source.id = source_record.id;
    return true;
end;
$$;

create function public.begin_knowledge_indexing(target_source_id uuid)
returns table (
    source_id uuid,
    workspace_id uuid,
    title text,
    chunk_id uuid,
    chunk_index integer,
    content text,
    content_sha256 text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
    actual_chunk_count integer;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to index a knowledge source'
            using errcode = '28000';
    end if;
    select source.* into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;
    if not found then
        raise exception 'Knowledge source was not found' using errcode = '22023';
    end if;
    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required' using errcode = '42501';
    end if;
    if source_record.extracted_at is null or source_record.chunk_count < 1 then
        raise exception 'Knowledge extraction must complete before indexing'
            using errcode = '22023';
    end if;
    select count(*)::integer into actual_chunk_count
    from public.knowledge_chunks as chunk
    where chunk.source_id = source_record.id;
    if actual_chunk_count <> source_record.chunk_count then
        raise exception 'Knowledge chunk metadata is inconsistent' using errcode = '55000';
    end if;
    if source_record.status in ('uploading', 'ready') then
        raise exception 'Knowledge source cannot begin indexing in its current state'
            using errcode = '22023';
    end if;
    if source_record.status = 'failed'
       and source_record.last_failure_stage <> 'indexing' then
        raise exception 'Extraction failures must be retried through extraction'
            using errcode = '22023';
    end if;
    if source_record.status = 'processing' then
        if source_record.processing_stage <> 'indexing' then
            raise exception 'A different knowledge operation is active' using errcode = '55000';
        end if;
        if source_record.processing_started_at is not null
           and source_record.processing_started_at >= now() - interval '15 minutes' then
            raise exception 'Knowledge indexing is already active' using errcode = '55000';
        end if;
    end if;
    if source_record.status not in ('pending', 'failed', 'processing') then
        raise exception 'Knowledge source cannot begin indexing in its current state'
            using errcode = '22023';
    end if;

    update public.knowledge_sources as source
    set status = 'processing',
        processing_stage = 'indexing',
        processing_started_at = now(),
        indexing_attempts = source.indexing_attempts + 1,
        last_error_code = null,
        last_failure_stage = null
    where source.id = source_record.id;

    return query
    select source_record.id, source_record.workspace_id, source_record.title,
           chunk.id, chunk.chunk_index, chunk.content, chunk.content_sha256
    from public.knowledge_chunks as chunk
    where chunk.source_id = source_record.id
    order by chunk.chunk_index;
end;
$$;

create function public.complete_knowledge_indexing(
    target_source_id uuid,
    provider_name text,
    model_name text,
    embedding_dimension integer,
    embedding_payload jsonb
)
returns table (
    source_id uuid,
    status text,
    chunk_count integer,
    embedding_provider text,
    embedding_model text,
    completed_embedding_dimension integer
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
    payload_record jsonb;
    persisted_chunk public.knowledge_chunks%rowtype;
    expected_index integer;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to complete knowledge indexing'
            using errcode = '28000';
    end if;
    select source.* into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;
    if not found then
        raise exception 'Knowledge source was not found' using errcode = '22023';
    end if;
    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required' using errcode = '42501';
    end if;
    if source_record.status <> 'processing'
       or source_record.processing_stage <> 'indexing' then
        raise exception 'Only active indexing can be completed' using errcode = '55000';
    end if;
    if provider_name is null or char_length(provider_name) not between 1 and 50
       or provider_name <> btrim(provider_name)
       or model_name is null or char_length(model_name) not between 1 and 100
       or model_name <> btrim(model_name)
       or embedding_dimension is distinct from 768 then
        raise exception 'Embedding metadata is invalid' using errcode = '22023';
    end if;
    if jsonb_typeof(embedding_payload) is distinct from 'array'
       or jsonb_array_length(embedding_payload) <> source_record.chunk_count then
        raise exception 'Embedding payload must cover every chunk' using errcode = '22023';
    end if;

    for payload_record, expected_index in
        select element.value, (element.ordinality - 1)::integer
        from jsonb_array_elements(embedding_payload) with ordinality as element(value, ordinality)
        order by element.ordinality
    loop
        if jsonb_typeof(payload_record) is distinct from 'object'
           or payload_record - array['chunk_index', 'content_sha256', 'embedding']::text[]
                <> '{}'::jsonb
           or jsonb_typeof(payload_record -> 'chunk_index') is distinct from 'number'
           or (payload_record ->> 'chunk_index') !~ '^(0|[1-9][0-9]*)$'
           or (payload_record ->> 'chunk_index')::integer <> expected_index
           or jsonb_typeof(payload_record -> 'content_sha256') is distinct from 'string'
           or jsonb_typeof(payload_record -> 'embedding') is distinct from 'array'
           or jsonb_array_length(payload_record -> 'embedding') <> 768
           or exists (
                select 1 from jsonb_array_elements(payload_record -> 'embedding') as value
                where jsonb_typeof(value) <> 'number'
           ) then
            raise exception 'Embedding payload contains malformed fields' using errcode = '22023';
        end if;

        select chunk.* into persisted_chunk
        from public.knowledge_chunks as chunk
        where chunk.source_id = source_record.id and chunk.chunk_index = expected_index
        for update;
        if not found
           or persisted_chunk.content_sha256 <> payload_record ->> 'content_sha256' then
            raise exception 'Knowledge chunk integrity check failed' using errcode = '55000';
        end if;

        update public.knowledge_chunks as chunk
        set embedding = ((payload_record -> 'embedding')::text)::extensions.vector
        where chunk.id = persisted_chunk.id;
    end loop;

    update public.knowledge_sources as source
    set status = 'ready',
        processing_stage = null,
        processing_started_at = null,
        indexed_at = now(),
        embedding_provider = provider_name,
        embedding_model = model_name,
        embedding_dimension = 768,
        last_error_code = null,
        last_failure_stage = null
    where source.id = source_record.id;

    source_id := source_record.id;
    status := 'ready';
    chunk_count := source_record.chunk_count;
    embedding_provider := provider_name;
    embedding_model := model_name;
    completed_embedding_dimension := 768;
    return next;
end;
$$;

create function public.fail_knowledge_indexing(target_source_id uuid, error_code text)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to fail knowledge indexing'
            using errcode = '28000';
    end if;
    select source.* into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;
    if not found then
        raise exception 'Knowledge source was not found' using errcode = '22023';
    end if;
    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required' using errcode = '42501';
    end if;
    if source_record.status <> 'processing'
       or source_record.processing_stage <> 'indexing' then
        raise exception 'Only active indexing can be failed' using errcode = '55000';
    end if;
    if error_code is null or error_code not in (
        'embedding_auth_failed', 'embedding_rate_limited',
        'embedding_provider_unavailable', 'embedding_invalid_response', 'embedding_failed'
    ) then
        raise exception 'Indexing error code is not allowed' using errcode = '22023';
    end if;
    update public.knowledge_sources as source
    set status = 'failed',
        processing_stage = null,
        processing_started_at = null,
        last_failure_stage = 'indexing',
        last_error_code = error_code
    where source.id = source_record.id;
    return true;
end;
$$;

create index knowledge_chunks_embedding_hnsw_idx
on public.knowledge_chunks
using hnsw (embedding extensions.vector_cosine_ops)
where embedding is not null;

revoke all on function app_private.enforce_knowledge_processing_transition() from public;
revoke all on function public.begin_knowledge_indexing(uuid) from public, anon, authenticated;
revoke all on function public.complete_knowledge_indexing(uuid, text, text, integer, jsonb)
    from public, anon, authenticated;
revoke all on function public.fail_knowledge_indexing(uuid, text)
    from public, anon, authenticated;

grant execute on function public.begin_knowledge_indexing(uuid) to authenticated;
grant execute on function public.complete_knowledge_indexing(uuid, text, text, integer, jsonb)
    to authenticated;
grant execute on function public.fail_knowledge_indexing(uuid, text) to authenticated;
