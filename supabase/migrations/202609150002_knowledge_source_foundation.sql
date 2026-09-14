-- SupportPilot AI Phase 3A: secure knowledge source storage and management.

create table public.knowledge_sources (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    created_by uuid not null references auth.users (id) on delete restrict,
    source_type text not null,
    title text not null,
    status text not null,
    original_filename text,
    storage_path text unique,
    mime_type text,
    byte_size bigint,
    faq_question text,
    faq_answer text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint knowledge_sources_type_allowed
        check (source_type in ('file', 'faq')),
    constraint knowledge_sources_status_allowed
        check (status in ('uploading', 'pending', 'processing', 'ready', 'failed')),
    constraint knowledge_sources_title_format check (
        title = btrim(title)
        and char_length(title) between 2 and 200
    ),
    constraint knowledge_sources_payload_matches_type check (
        (
            source_type = 'file'
            and original_filename is not null
            and original_filename = btrim(original_filename)
            and char_length(original_filename) between 1 and 255
            and strpos(original_filename, '/') = 0
            and strpos(original_filename, chr(92)) = 0
            and strpos(original_filename, '..') = 0
            and lower(substring(original_filename from '[.]([^.]+)$'))
                in ('pdf', 'docx', 'txt', 'md')
            and storage_path is not null
            and storage_path = workspace_id::text || '/' || id::text || '/' || id::text
                || '.' || lower(substring(original_filename from '[.]([^.]+)$'))
            and mime_type is not null
            and (
                (
                    lower(substring(original_filename from '[.]([^.]+)$')) = 'pdf'
                    and mime_type = 'application/pdf'
                )
                or (
                    lower(substring(original_filename from '[.]([^.]+)$')) = 'docx'
                    and mime_type =
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                )
                or (
                    lower(substring(original_filename from '[.]([^.]+)$')) = 'txt'
                    and mime_type = 'text/plain'
                )
                or (
                    lower(substring(original_filename from '[.]([^.]+)$')) = 'md'
                    and mime_type in ('text/markdown', 'text/plain')
                )
            )
            and byte_size between 1 and 10485760
            and faq_question is null
            and faq_answer is null
        )
        or (
            source_type = 'faq'
            and status <> 'uploading'
            and original_filename is null
            and storage_path is null
            and mime_type is null
            and byte_size is null
            and faq_question is not null
            and faq_question = btrim(faq_question)
            and char_length(faq_question) between 5 and 1000
            and faq_answer is not null
            and faq_answer = btrim(faq_answer)
            and char_length(faq_answer) between 1 and 20000
        )
    )
);

create index knowledge_sources_workspace_id_idx
    on public.knowledge_sources (workspace_id);

create index knowledge_sources_workspace_status_idx
    on public.knowledge_sources (workspace_id, status);

create index knowledge_sources_workspace_created_at_idx
    on public.knowledge_sources (workspace_id, created_at desc, id);

create trigger knowledge_sources_set_updated_at
before update on public.knowledge_sources
for each row execute function app_private.set_updated_at();

create function app_private.can_manage_knowledge(target_workspace_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.workspace_members as membership
        where membership.workspace_id = target_workspace_id
          and membership.user_id = (select auth.uid())
          and membership.role in ('owner', 'admin')
    );
$$;

create function app_private.can_read_knowledge_object(object_name text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.knowledge_sources as source
        where source.source_type = 'file'
          and source.storage_path = object_name
          and source.storage_path =
              source.workspace_id::text || '/' || source.id::text || '/'
              || source.id::text || '.'
              || lower(substring(source.original_filename from '[.]([^.]+)$'))
          and (select app_private.is_workspace_member(source.workspace_id))
    );
$$;

create function app_private.can_upload_knowledge_object(object_name text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.knowledge_sources as source
        where source.source_type = 'file'
          and source.status = 'uploading'
          and source.storage_path = object_name
          and source.storage_path =
              source.workspace_id::text || '/' || source.id::text || '/'
              || source.id::text || '.'
              || lower(substring(source.original_filename from '[.]([^.]+)$'))
          and (select app_private.can_manage_knowledge(source.workspace_id))
    );
$$;

create function app_private.can_delete_knowledge_object(object_name text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.knowledge_sources as source
        where source.source_type = 'file'
          and source.storage_path = object_name
          and source.storage_path =
              source.workspace_id::text || '/' || source.id::text || '/'
              || source.id::text || '.'
              || lower(substring(source.original_filename from '[.]([^.]+)$'))
          and (select app_private.can_manage_knowledge(source.workspace_id))
    );
$$;

create function public.begin_file_knowledge_source(
    target_workspace_id uuid,
    source_title text,
    file_original_filename text,
    file_mime_type text,
    file_byte_size bigint
)
returns table (
    source_id uuid,
    storage_path text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_user_id uuid := (select auth.uid());
    normalized_title text;
    normalized_filename text;
    normalized_mime_type text;
    file_extension text;
    generated_source_id uuid := gen_random_uuid();
    generated_storage_path text;
begin
    if caller_user_id is null then
        raise exception 'Authentication is required to create a knowledge source'
            using errcode = '28000';
    end if;

    if not (select app_private.can_manage_knowledge(target_workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    normalized_title := regexp_replace(btrim(coalesce(source_title, '')), '\s+', ' ', 'g');
    normalized_filename := btrim(coalesce(file_original_filename, ''));
    normalized_mime_type := lower(btrim(coalesce(file_mime_type, '')));

    if char_length(normalized_title) < 2 or char_length(normalized_title) > 200 then
        raise exception 'Source title must contain between 2 and 200 characters'
            using errcode = '22023';
    end if;

    if char_length(normalized_filename) < 1
        or char_length(normalized_filename) > 255
        or strpos(normalized_filename, '/') > 0
        or strpos(normalized_filename, chr(92)) > 0
        or strpos(normalized_filename, '..') > 0 then
        raise exception 'Original filename is invalid'
            using errcode = '22023';
    end if;

    file_extension := lower(substring(normalized_filename from '[.]([^.]+)$'));

    if file_extension not in ('pdf', 'docx', 'txt', 'md') then
        raise exception 'File extension is not supported'
            using errcode = '22023';
    end if;

    if not (
        (file_extension = 'pdf' and normalized_mime_type = 'application/pdf')
        or (
            file_extension = 'docx'
            and normalized_mime_type =
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        or (file_extension = 'txt' and normalized_mime_type = 'text/plain')
        or (
            file_extension = 'md'
            and normalized_mime_type in ('text/markdown', 'text/plain')
        )
    ) then
        raise exception 'File extension and MIME type do not match a supported document type'
            using errcode = '22023';
    end if;

    if file_byte_size is null or file_byte_size < 1 or file_byte_size > 10485760 then
        raise exception 'File size must be between 1 byte and 10 MB'
            using errcode = '22023';
    end if;

    generated_storage_path := target_workspace_id::text || '/' || generated_source_id::text
        || '/' || generated_source_id::text || '.' || file_extension;

    insert into public.knowledge_sources (
        id,
        workspace_id,
        created_by,
        source_type,
        title,
        status,
        original_filename,
        storage_path,
        mime_type,
        byte_size
    )
    values (
        generated_source_id,
        target_workspace_id,
        caller_user_id,
        'file',
        normalized_title,
        'uploading',
        normalized_filename,
        generated_storage_path,
        normalized_mime_type,
        file_byte_size
    );

    source_id := generated_source_id;
    storage_path := generated_storage_path;
    return next;
end;
$$;

create function public.finalize_file_knowledge_source(target_source_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to finalize a knowledge source'
            using errcode = '28000';
    end if;

    select *
    into source_record
    from public.knowledge_sources
    where id = target_source_id
      and source_type = 'file'
    for update;

    if not found then
        raise exception 'File knowledge source was not found'
            using errcode = '22023';
    end if;

    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    if source_record.status <> 'uploading' then
        raise exception 'Only an uploading source can be finalized'
            using errcode = '22023';
    end if;

    if not exists (
        select 1
        from storage.objects as object
        where object.bucket_id = 'knowledge-files'
          and object.name = source_record.storage_path
    ) then
        raise exception 'The expected private Storage object does not exist'
            using errcode = '22023';
    end if;

    update public.knowledge_sources
    set status = 'pending'
    where id = source_record.id;

    return true;
end;
$$;

create function public.cancel_file_knowledge_source(target_source_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to cancel a knowledge source'
            using errcode = '28000';
    end if;

    select *
    into source_record
    from public.knowledge_sources
    where id = target_source_id
      and source_type = 'file'
    for update;

    if not found then
        raise exception 'File knowledge source was not found'
            using errcode = '22023';
    end if;

    if not (select app_private.can_manage_knowledge(source_record.workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    if source_record.status <> 'uploading' then
        raise exception 'Only an uploading source can be canceled'
            using errcode = '22023';
    end if;

    if exists (
        select 1
        from storage.objects as object
        where object.bucket_id = 'knowledge-files'
          and object.name = source_record.storage_path
    ) then
        raise exception 'Remove the private Storage object through the Storage API first'
            using errcode = '22023';
    end if;

    delete from public.knowledge_sources where id = source_record.id;
    return true;
end;
$$;

create function public.create_faq_knowledge_source(
    target_workspace_id uuid,
    source_title text,
    question text,
    answer text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_user_id uuid := (select auth.uid());
    normalized_title text;
    normalized_question text := btrim(coalesce(question, ''));
    normalized_answer text := btrim(coalesce(answer, ''));
    generated_source_id uuid;
begin
    if caller_user_id is null then
        raise exception 'Authentication is required to create a knowledge source'
            using errcode = '28000';
    end if;

    if not (select app_private.can_manage_knowledge(target_workspace_id)) then
        raise exception 'Knowledge management permission is required'
            using errcode = '42501';
    end if;

    normalized_title := regexp_replace(btrim(coalesce(source_title, '')), '\s+', ' ', 'g');

    if char_length(normalized_title) < 2 or char_length(normalized_title) > 200 then
        raise exception 'Source title must contain between 2 and 200 characters'
            using errcode = '22023';
    end if;

    if char_length(normalized_question) < 5 or char_length(normalized_question) > 1000 then
        raise exception 'FAQ question must contain between 5 and 1000 characters'
            using errcode = '22023';
    end if;

    if char_length(normalized_answer) < 1 or char_length(normalized_answer) > 20000 then
        raise exception 'FAQ answer must contain between 1 and 20000 characters'
            using errcode = '22023';
    end if;

    insert into public.knowledge_sources (
        workspace_id,
        created_by,
        source_type,
        title,
        status,
        faq_question,
        faq_answer
    )
    values (
        target_workspace_id,
        caller_user_id,
        'faq',
        normalized_title,
        'pending',
        normalized_question,
        normalized_answer
    )
    returning id into generated_source_id;

    return generated_source_id;
end;
$$;

alter table public.knowledge_sources enable row level security;

revoke all on table public.knowledge_sources from public, anon, authenticated;

grant select (
    id,
    workspace_id,
    source_type,
    title,
    status,
    original_filename,
    mime_type,
    byte_size,
    created_at,
    updated_at
) on table public.knowledge_sources to authenticated;

create policy knowledge_sources_select_for_members
on public.knowledge_sources
for select
to authenticated
using ((select app_private.is_workspace_member(workspace_id)));

create policy knowledge_sources_direct_insert_denied
on public.knowledge_sources
for insert
to authenticated
with check (false);

create policy knowledge_sources_direct_update_denied
on public.knowledge_sources
for update
to authenticated
using (false)
with check (false);

create policy knowledge_sources_direct_delete_denied
on public.knowledge_sources
for delete
to authenticated
using (false);

-- Direct mutation grants are intentionally absent. Security-definer RPCs perform scoped changes.

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'knowledge-files',
    'knowledge-files',
    false,
    10485760,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'text/markdown'
    ]::text[]
)
on conflict (id) do update
set name = excluded.name,
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy knowledge_files_select_for_members
on storage.objects
for select
to authenticated
using (
    bucket_id = 'knowledge-files'
    and (select app_private.can_read_knowledge_object(name))
);

create policy knowledge_files_insert_for_managers
on storage.objects
for insert
to authenticated
with check (
    bucket_id = 'knowledge-files'
    and (select app_private.can_upload_knowledge_object(name))
);

create policy knowledge_files_delete_for_managers
on storage.objects
for delete
to authenticated
using (
    bucket_id = 'knowledge-files'
    and (select app_private.can_delete_knowledge_object(name))
);

-- No UPDATE policy is created: browser uploads use upsert=false and cannot overwrite objects.

revoke all on function app_private.can_manage_knowledge(uuid)
    from public, anon, authenticated;
revoke all on function app_private.can_read_knowledge_object(text)
    from public, anon, authenticated;
revoke all on function app_private.can_upload_knowledge_object(text)
    from public, anon, authenticated;
revoke all on function app_private.can_delete_knowledge_object(text)
    from public, anon, authenticated;
revoke all on function public.begin_file_knowledge_source(uuid, text, text, text, bigint)
    from public, anon, authenticated;
revoke all on function public.finalize_file_knowledge_source(uuid)
    from public, anon, authenticated;
revoke all on function public.cancel_file_knowledge_source(uuid)
    from public, anon, authenticated;
revoke all on function public.create_faq_knowledge_source(uuid, text, text, text)
    from public, anon, authenticated;

grant execute on function app_private.can_manage_knowledge(uuid) to authenticated;
grant execute on function app_private.can_read_knowledge_object(text) to authenticated;
grant execute on function app_private.can_upload_knowledge_object(text) to authenticated;
grant execute on function app_private.can_delete_knowledge_object(text) to authenticated;
grant execute on function public.begin_file_knowledge_source(uuid, text, text, text, bigint)
    to authenticated;
grant execute on function public.finalize_file_knowledge_source(uuid) to authenticated;
grant execute on function public.cancel_file_knowledge_source(uuid) to authenticated;
grant execute on function public.create_faq_knowledge_source(uuid, text, text, text)
    to authenticated;
