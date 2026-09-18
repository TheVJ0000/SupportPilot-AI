begin;
select no_plan();
-- Actual database time, epoch-aligned windows; synthetic neighboring windows.
-- No clock replacement, sleeps, real users, or assumption of UTC session time.
set local timezone = 'Pacific/Chatham';
create function pg_temp.boundary_checks(target_scope text, seconds integer, maximum integer)
returns setof text language plpgsql as $$
declare
    subject uuid := gen_random_uuid();
    active_window timestamptz;
    after_window timestamptz;
begin
    active_window := to_timestamp(floor(extract(epoch from clock_timestamp()) / seconds) * seconds);
    insert into public.customer_api_rate_limits(scope,subject_id,window_started_at,request_count,expires_at)
    select target_scope,subject,active_window + offset_seconds * interval '1 second',maximum,
        active_window + (offset_seconds + seconds) * interval '1 second'
    from (values (-seconds),(seconds)) adjacent(offset_seconds);
    perform app_private.consume_customer_rate_limit(target_scope,subject);
    after_window := to_timestamp(floor(extract(epoch from clock_timestamp()) / seconds) * seconds);
    return next is(after_window,active_window,target_scope || ': test stayed within measured DB-time window');
    return next is((select request_count from public.customer_api_rate_limits where scope=target_scope
        and subject_id=subject and window_started_at=active_window),1,target_scope || ': fresh current window receives exactly one claim');
    return next is((select request_count from public.customer_api_rate_limits where scope=target_scope
        and subject_id=subject and window_started_at=active_window - seconds * interval '1 second'),maximum,
        target_scope || ': exhausted previous window is unchanged and cannot block new window');
    return next is((select request_count from public.customer_api_rate_limits where scope=target_scope
        and subject_id=subject and window_started_at=active_window + seconds * interval '1 second'),maximum,
        target_scope || ': future window neither selected nor altered');
    return next is((select expires_at from public.customer_api_rate_limits where scope=target_scope
        and subject_id=subject and window_started_at=active_window),active_window + seconds * interval '1 second',
        target_scope || ': expiry is exact next boundary');
    return next ok(mod(extract(epoch from active_window)::bigint,seconds)=0,
        target_scope || ': epoch alignment is independent of connection timezone');
end;
$$;
select * from pg_temp.boundary_checks('session_minute',60,30);
select * from pg_temp.boundary_checks('session_hour',3600,300);
select * from pg_temp.boundary_checks('turn_minute',60,6);
select * from pg_temp.boundary_checks('turn_hour',3600,60);
select * from finish();
rollback;
