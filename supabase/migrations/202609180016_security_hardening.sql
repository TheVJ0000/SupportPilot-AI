-- Phase 9A: remove inherited default service-role access unused by application flows.
-- Business gateways use publishable key + verified caller JWT. Privileged customer/
-- triage/notification operations retain their explicitly granted narrow RPCs.
-- SECURITY DEFINER owners retain table access; auth/config/outbox triggers remain intact.
revoke all on table public.profiles, public.workspaces, public.workspace_members,
    public.knowledge_sources, public.knowledge_chunks from service_role;

revoke execute on function public.create_workspace(text) from service_role;
revoke execute on function public.begin_file_knowledge_source(uuid,text,text,text,bigint) from service_role;
revoke execute on function public.finalize_file_knowledge_source(uuid) from service_role;
revoke execute on function public.cancel_file_knowledge_source(uuid) from service_role;
revoke execute on function public.create_faq_knowledge_source(uuid,text,text,text) from service_role;
revoke execute on function public.recover_file_knowledge_source(uuid) from service_role;
revoke execute on function public.begin_knowledge_extraction(uuid) from service_role;
revoke execute on function public.complete_knowledge_extraction(uuid,jsonb,integer) from service_role;
revoke execute on function public.fail_knowledge_extraction(uuid,text) from service_role;
revoke execute on function public.begin_knowledge_indexing(uuid) from service_role;
revoke execute on function public.complete_knowledge_indexing(uuid,text,text,integer,jsonb) from service_role;
revoke execute on function public.fail_knowledge_indexing(uuid,text) from service_role;
revoke execute on function public.search_knowledge_chunks(uuid,jsonb,text,text,integer,integer) from service_role;
