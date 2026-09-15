-- SupportPilot AI Phase 3B: secure extraction lifecycle and citation-aware chunks.

alter table public.knowledge_sources
add column processing_started_at timestamptz,
add column processing_attempts integer not null default 0,
add column extracted_at timestamptz,
add column extracted_char_count integer,
add column chunk_count integer not null default 0,
add column last_error_code text,
add constraint knowledge_sources_processing_attempts_nonnegative
    check (processing_attempts >= 0),
add constraint knowledge_sources_extracted_char_count_valid
    check (extracted_char_count is null or extracted_char_count between 1 and 1000000),
add constraint knowledge_sources_chunk_count_valid
    check (chunk_count between 0 and 1000),
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
        'chunking_failed'
    )
),
add constraint knowledge_sources_id_workspace_unique unique (id, workspace_id);

grant select (
    processing_started_at,
    processing_attempts,
    extracted_at,
    extracted_char_count,
    chunk_count,
    last_error_code
) on table public.knowledge_sources to authenticated;

create table public.knowledge_chunks (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null,
    workspace_id uuid not null,
    chunk_index integer not null,
    content text not null,
    content_sha256 text not null,
    char_count integer not null,
    locator jsonb not null,
    created_at timestamptz not null default now(),
    constraint knowledge_chunks_source_workspace_fk
        foreign key (source_id, workspace_id)
        references public.knowledge_sources (id, workspace_id)
        on delete cascade,
    constraint knowledge_chunks_source_index_unique unique (source_id, chunk_index),
    constraint knowledge_chunks_index_nonnegative check (chunk_index >= 0),
    constraint knowledge_chunks_content_valid check (
        char_length(content) between 1 and 2200
        and btrim(content) <> ''
        and char_count = char_length(content)
    ),
    constraint knowledge_chunks_sha256_valid check (
        content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    constraint knowledge_chunks_locator_object check (jsonb_typeof(locator) = 'object')
);

create index knowledge_chunks_workspace_id_idx
    on public.knowledge_chunks (workspace_id);

alter table public.knowledge_chunks enable row level security;

revoke all on table public.knowledge_chunks from public, anon, authenticated;

grant select (
    id,
    source_id,
    workspace_id,
    chunk_index,
    content,
    content_sha256,
    char_count,
    locator,
    created_at
) on table public.knowledge_chunks to authenticated;

create policy knowledge_chunks_select_for_members
on public.knowledge_chunks
for select
to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create function public.begin_knowledge_extraction(target_source_id uuid)
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

    select source.*
    into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;

    if not found then
        raise exception 'Knowledge source was not found'
            using errcode = '22023';
    end if;

    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    if source_record.status = 'uploading' then
        raise exception 'Uploading sources must be recovered before processing'
            using errcode = '22023';
    end if;

    if source_record.status = 'ready' then
        raise exception 'Ready sources cannot be processed by the extraction stage'
            using errcode = '22023';
    end if;

    if source_record.status = 'processing'
       and source_record.processing_started_at is not null
       and source_record.processing_started_at >= now() - interval '15 minutes' then
        raise exception 'Knowledge extraction is already active'
            using errcode = '55000';
    end if;

    if source_record.status not in ('pending', 'failed', 'processing') then
        raise exception 'Knowledge source cannot begin extraction in its current state'
            using errcode = '22023';
    end if;

    update public.knowledge_sources as source
    set status = 'processing',
        processing_started_at = now(),
        processing_attempts = source.processing_attempts + 1,
        last_error_code = null
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

create function public.complete_knowledge_extraction(
    target_source_id uuid,
    chunk_payload jsonb,
    total_extracted_char_count integer
)
returns table (
    source_id uuid,
    status text,
    chunk_count integer,
    extracted_char_count integer
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
    chunk_record jsonb;
    locator_record jsonb;
    locator_kind text;
    payload_chunk_count integer;
    expected_index integer;
    submitted_index integer;
    submitted_content text;
    submitted_char_count integer;
    total_chunk_char_count integer := 0;
    maximum_chunk_char_count integer := 0;
    range_start integer;
    range_end integer;
    expected_locator_kind text;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to complete knowledge extraction'
            using errcode = '28000';
    end if;

    select source.*
    into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;

    if not found then
        raise exception 'Knowledge source was not found'
            using errcode = '22023';
    end if;

    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    if source_record.status <> 'processing' then
        raise exception 'Only a processing source can complete extraction'
            using errcode = '55000';
    end if;

    if jsonb_typeof(chunk_payload) is distinct from 'array' then
        raise exception 'Chunk payload must be a JSON array'
            using errcode = '22023';
    end if;

    payload_chunk_count := jsonb_array_length(chunk_payload);
    if payload_chunk_count < 1 or payload_chunk_count > 1000 then
        raise exception 'Chunk payload must contain between 1 and 1000 chunks'
            using errcode = '22023';
    end if;

    if total_extracted_char_count is null
       or total_extracted_char_count < 1
       or total_extracted_char_count > 1000000 then
        raise exception 'Extracted character count is outside the allowed range'
            using errcode = '22023';
    end if;

    expected_locator_kind := case
        when source_record.source_type = 'faq' then 'faq'
        when lower(source_record.original_filename) like '%.pdf' then 'pdf'
        when lower(source_record.original_filename) like '%.docx' then 'docx'
        when lower(source_record.original_filename) like '%.md' then 'markdown'
        else 'text'
    end;

    for chunk_record, expected_index in
        select element.value, (element.ordinality - 1)::integer
        from jsonb_array_elements(chunk_payload) with ordinality as element(value, ordinality)
        order by element.ordinality
    loop
        if jsonb_typeof(chunk_record) is distinct from 'object'
           or chunk_record - array[
               'chunk_index', 'content', 'content_sha256', 'char_count', 'locator'
           ]::text[] <> '{}'::jsonb
           or jsonb_typeof(chunk_record -> 'chunk_index') is distinct from 'number'
           or (chunk_record ->> 'chunk_index') !~ '^(0|[1-9][0-9]*)$'
           or jsonb_typeof(chunk_record -> 'content') is distinct from 'string'
           or jsonb_typeof(chunk_record -> 'content_sha256') is distinct from 'string'
           or jsonb_typeof(chunk_record -> 'char_count') is distinct from 'number'
           or (chunk_record ->> 'char_count') !~ '^[1-9][0-9]*$'
           or jsonb_typeof(chunk_record -> 'locator') is distinct from 'object' then
            raise exception 'Chunk payload contains malformed fields'
                using errcode = '22023';
        end if;

        submitted_index := (chunk_record ->> 'chunk_index')::integer;
        submitted_content := chunk_record ->> 'content';
        submitted_char_count := (chunk_record ->> 'char_count')::integer;
        locator_record := chunk_record -> 'locator';

        if submitted_index <> expected_index then
            raise exception 'Chunk indexes must be sequential and begin at zero'
                using errcode = '22023';
        end if;

        if char_length(submitted_content) < 1
           or char_length(submitted_content) > 2200
           or btrim(submitted_content) = ''
           or submitted_char_count <> char_length(submitted_content) then
            raise exception 'Chunk content or character count is invalid'
                using errcode = '22023';
        end if;

        if (chunk_record ->> 'content_sha256') !~ '^[0-9a-f]{64}$' then
            raise exception 'Chunk SHA-256 digest is invalid'
                using errcode = '22023';
        end if;

        locator_kind := locator_record ->> 'kind';
        if locator_kind is distinct from expected_locator_kind then
            raise exception 'Chunk locator kind does not match the source'
                using errcode = '22023';
        end if;

        if locator_kind = 'faq' then
            if locator_record <> '{"kind":"faq"}'::jsonb then
                raise exception 'FAQ locator is malformed' using errcode = '22023';
            end if;
        else
            if locator_kind = 'pdf' then
                if locator_record - array['kind', 'page_start', 'page_end']::text[]
                    <> '{}'::jsonb
                   or jsonb_typeof(locator_record -> 'page_start') is distinct from 'number'
                   or jsonb_typeof(locator_record -> 'page_end') is distinct from 'number'
                   or (locator_record ->> 'page_start') !~ '^[1-9][0-9]*$'
                   or (locator_record ->> 'page_end') !~ '^[1-9][0-9]*$' then
                    raise exception 'PDF locator is malformed' using errcode = '22023';
                end if;
                range_start := (locator_record ->> 'page_start')::integer;
                range_end := (locator_record ->> 'page_end')::integer;
                if range_end > 300 then
                    raise exception 'PDF locator exceeds the page limit'
                        using errcode = '22023';
                end if;
            elsif locator_kind = 'docx' then
                if locator_record - array['kind', 'block_start', 'block_end']::text[]
                    <> '{}'::jsonb
                   or jsonb_typeof(locator_record -> 'block_start') is distinct from 'number'
                   or jsonb_typeof(locator_record -> 'block_end') is distinct from 'number'
                   or (locator_record ->> 'block_start') !~ '^[1-9][0-9]*$'
                   or (locator_record ->> 'block_end') !~ '^[1-9][0-9]*$' then
                    raise exception 'DOCX locator is malformed' using errcode = '22023';
                end if;
                range_start := (locator_record ->> 'block_start')::integer;
                range_end := (locator_record ->> 'block_end')::integer;
            else
                if locator_record - array['kind', 'line_start', 'line_end']::text[]
                    <> '{}'::jsonb
                   or jsonb_typeof(locator_record -> 'line_start') is distinct from 'number'
                   or jsonb_typeof(locator_record -> 'line_end') is distinct from 'number'
                   or (locator_record ->> 'line_start') !~ '^[1-9][0-9]*$'
                   or (locator_record ->> 'line_end') !~ '^[1-9][0-9]*$' then
                    raise exception 'Text locator is malformed' using errcode = '22023';
                end if;
                range_start := (locator_record ->> 'line_start')::integer;
                range_end := (locator_record ->> 'line_end')::integer;
            end if;

            if range_start > range_end or range_end > 1000000 then
                raise exception 'Chunk locator range is invalid'
                    using errcode = '22023';
            end if;
        end if;

        total_chunk_char_count := total_chunk_char_count + submitted_char_count;
        maximum_chunk_char_count := greatest(maximum_chunk_char_count, submitted_char_count);
    end loop;

    if total_extracted_char_count > total_chunk_char_count + (2 * (payload_chunk_count - 1))
       or total_extracted_char_count < maximum_chunk_char_count then
        raise exception 'Extracted character count is inconsistent with the chunks'
            using errcode = '22023';
    end if;

    delete from public.knowledge_chunks as chunk
    where chunk.source_id = source_record.id;

    insert into public.knowledge_chunks (
        source_id,
        workspace_id,
        chunk_index,
        content,
        content_sha256,
        char_count,
        locator
    )
    select
        source_record.id,
        source_record.workspace_id,
        (element.value ->> 'chunk_index')::integer,
        element.value ->> 'content',
        element.value ->> 'content_sha256',
        (element.value ->> 'char_count')::integer,
        element.value -> 'locator'
    from jsonb_array_elements(chunk_payload) with ordinality as element(value, ordinality)
    order by element.ordinality;

    update public.knowledge_sources as source
    set status = 'pending',
        extracted_at = now(),
        extracted_char_count = total_extracted_char_count,
        chunk_count = payload_chunk_count,
        processing_started_at = null,
        last_error_code = null
    where source.id = source_record.id;

    source_id := source_record.id;
    status := 'pending';
    chunk_count := payload_chunk_count;
    extracted_char_count := total_extracted_char_count;
    return next;
end;
$$;

create function public.fail_knowledge_extraction(target_source_id uuid, error_code text)
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

    select source.*
    into source_record
    from public.knowledge_sources as source
    where source.id = target_source_id
    for update;

    if not found then
        raise exception 'Knowledge source was not found'
            using errcode = '22023';
    end if;

    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    if source_record.status <> 'processing' then
        raise exception 'Only a processing source can fail extraction'
            using errcode = '55000';
    end if;

    if error_code is null or error_code not in (
        'invalid_file_content',
        'unsupported_encoding',
        'encrypted_pdf',
        'too_many_pages',
        'document_too_large',
        'no_extractable_text',
        'malformed_document',
        'storage_download_failed',
        'extraction_failed',
        'chunking_failed'
    ) then
        raise exception 'Extraction error code is not allowed'
            using errcode = '22023';
    end if;

    update public.knowledge_sources as source
    set status = 'failed',
        processing_started_at = null,
        last_error_code = error_code
    where source.id = source_record.id;

    return true;
end;
$$;

revoke all on function public.begin_knowledge_extraction(uuid)
    from public, anon, authenticated;
revoke all on function public.complete_knowledge_extraction(uuid, jsonb, integer)
    from public, anon, authenticated;
revoke all on function public.fail_knowledge_extraction(uuid, text)
    from public, anon, authenticated;

grant execute on function public.begin_knowledge_extraction(uuid) to authenticated;
grant execute on function public.complete_knowledge_extraction(uuid, jsonb, integer)
    to authenticated;
grant execute on function public.fail_knowledge_extraction(uuid, text) to authenticated;
