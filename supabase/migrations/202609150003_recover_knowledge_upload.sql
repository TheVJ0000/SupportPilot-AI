-- SupportPilot AI Phase 3A correction: safely reconcile incomplete file uploads.

create function public.recover_file_knowledge_source(target_source_id uuid)
returns table (
    source_id uuid,
    recovery_action text,
    source_status text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
    source_record public.knowledge_sources%rowtype;
    expected_object_exists boolean;
begin
    if (select auth.uid()) is null then
        raise exception 'Authentication is required to recover a knowledge source'
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

    select exists (
        select 1
        from storage.objects as object
        where object.bucket_id = 'knowledge-files'
          and object.name = source_record.storage_path
    ) into expected_object_exists;

    -- A lost finalize response may leave the source already pending. Confirm it without mutation.
    if source_record.status = 'pending' and expected_object_exists then
        source_id := source_record.id;
        recovery_action := 'already_pending';
        source_status := 'pending';
        return next;
        return;
    end if;

    if source_record.status <> 'uploading' then
        raise exception 'Only an uploading source can be recovered'
            using errcode = '22023';
    end if;

    if expected_object_exists then
        update public.knowledge_sources
        set status = 'pending'
        where id = source_record.id;

        source_id := source_record.id;
        recovery_action := 'finalized';
        source_status := 'pending';
        return next;
        return;
    end if;

    delete from public.knowledge_sources where id = source_record.id;

    source_id := source_record.id;
    recovery_action := 'removed';
    source_status := null;
    return next;
end;
$$;

revoke all on function public.recover_file_knowledge_source(uuid)
    from public, anon, authenticated;

grant execute on function public.recover_file_knowledge_source(uuid) to authenticated;
