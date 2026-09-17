-- Phase 8A: reuse the existing public chat identity; no table grants or customer RPC changes.
create function public.admin_get_widget_config(target_workspace_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare config jsonb;
begin
    if auth.uid() is null then
        raise exception 'Authentication required' using errcode = '28000';
    end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Owner or admin required' using errcode = '42501';
    end if;
    select jsonb_build_object('workspace_id', workspace.id, 'workspace_name', workspace.name,
        'public_id', chat.public_id, 'is_enabled', chat.is_enabled)
    into config from public.workspace_chat_configs as chat
    join public.workspaces as workspace on workspace.id = chat.workspace_id
    where chat.workspace_id = target_workspace_id;
    if not found then
        raise exception 'Widget configuration unavailable' using errcode = 'P0002';
    end if;
    return config;
end;
$$;

create function public.admin_set_widget_enabled(
    target_workspace_id uuid, expected_is_enabled boolean, new_is_enabled boolean
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare config public.workspace_chat_configs%rowtype;
begin
    if auth.uid() is null then
        raise exception 'Authentication required' using errcode = '28000';
    end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Owner or admin required' using errcode = '42501';
    end if;
    select chat.* into config from public.workspace_chat_configs as chat
    where chat.workspace_id = target_workspace_id for update;
    if not found then
        raise exception 'Widget configuration unavailable' using errcode = 'P0002';
    end if;
    if not app_private.can_view_support_operations(target_workspace_id) then
        raise exception 'Owner or admin required' using errcode = '42501';
    end if;
    if config.is_enabled is distinct from expected_is_enabled then
        raise exception 'Widget configuration changed' using errcode = '40001';
    end if;
    if new_is_enabled is null then
        raise exception 'Enabled state required' using errcode = '22023';
    end if;
    if config.is_enabled = new_is_enabled then
        raise exception 'Widget state unchanged' using errcode = '55000';
    end if;
    update public.workspace_chat_configs set is_enabled = new_is_enabled
    where workspace_id = target_workspace_id;
    -- public_id, sessions, conversation/escalation state and AI behavior are untouched.
    return public.admin_get_widget_config(target_workspace_id);
end;
$$;

revoke all on function public.admin_get_widget_config(uuid)
    from public, anon, authenticated, service_role;
revoke all on function public.admin_set_widget_enabled(uuid, boolean, boolean)
    from public, anon, authenticated, service_role;
grant execute on function public.admin_get_widget_config(uuid) to authenticated;
grant execute on function public.admin_set_widget_enabled(uuid, boolean, boolean) to authenticated;
