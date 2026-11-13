create or replace function crewfit_private.schedule_access(p_store bigint, p_week date)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  caller uuid := auth.uid();
  owner_id uuid;
begin
  if p_week is null or not isfinite(p_week) or extract(isodow from p_week) <> 1 then
    raise exception using errcode = '22023', message = 'invalid_week';
  end if;

  select s.user_id into owner_id
  from public.stores s join public.profiles p on p.id = s.user_id
  where s.id = p_store and not s.is_deleted and not p.is_deleted;

  if owner_id is null or not exists (
    select 1 from public.profiles p where p.id = caller and not p.is_deleted
  ) then
    raise exception using errcode = '42501', message = 'store_access_denied';
  end if;
  if owner_id = caller then
    return true;
  end if;
  if not exists (
    select 1 from public.employees e where e.store_id = p_store and e.user_id = caller
  ) then
    raise exception using errcode = '42501', message = 'store_access_denied';
  end if;
  return false;
end;
$$;
revoke all on function crewfit_private.schedule_access(bigint,date) from public, anon, authenticated;

create or replace function crewfit_private.crewfit_schedule_week(p_store bigint, p_week date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  caller uuid := auth.uid();
  is_owner boolean := crewfit_private.schedule_access(p_store, p_week);
  published_id bigint;
begin
  select id into published_id from public.confirmed_schedules
  where store_id = p_store and week = p_week;

  return jsonb_build_object(
    'is_owner', is_owner,
    'published', published_id is not null,
    'employees', coalesce((
      select jsonb_agg(jsonb_build_object(
        'user_id', e.user_id,
        'name', coalesce(nullif(p.user_name, ''), nullif(u.raw_user_meta_data->>'full_name', ''),
          nullif(u.raw_user_meta_data->>'name', ''), '직원 ' || left(e.user_id::text, 8)),
        'available', s.available_day,
        'unavailable', s.impossible_day,
        'note', s.etc,
        'submitted', s.id is not null
      ) order by p.user_name nulls last, e.user_id)
      from public.employees e
      join public.profiles p on p.id = e.user_id and not p.is_deleted
      join auth.users u on u.id = e.user_id
      left join public.schedule_submissions s
        on s.user_id = e.user_id and s.store_id = e.store_id and s.week = p_week
      where e.store_id = p_store and (is_owner or e.user_id = caller)
    ), '[]'::jsonb),
    'items', coalesce((
      select jsonb_object_agg(i.user_id::text, i.schedule_text order by i.id)
      from public.confirmed_schedule_items i
      where i.schedule_id = published_id and i.user_id is not null
        and (is_owner or i.user_id = caller)
    ), '{}'::jsonb)
  );
end;
$$;

create or replace function crewfit_private.crewfit_submit_schedule(
  p_store bigint, p_week date, p_available text[], p_unavailable text[], p_note text
) returns void language plpgsql security definer set search_path = '' as $$
declare
  days constant text[] := array['월','화','수','목','금','토','일'];
begin
  perform id from public.stores where id = p_store for update;
  if crewfit_private.schedule_access(p_store, p_week) then
    raise exception using errcode = '42501', message = 'employees_only';
  end if;
  if exists (select 1 from public.confirmed_schedules where store_id = p_store and week = p_week) then
    raise exception using errcode = '22023', message = 'week_published';
  end if;
  if p_available is null or p_unavailable is null
    or not (p_available <@ days and p_unavailable <@ days)
    or p_available && p_unavailable
    or cardinality(p_available) <> (select count(distinct d) from unnest(p_available) as d)
    or cardinality(p_unavailable) <> (select count(distinct d) from unnest(p_unavailable) as d)
    or cardinality(p_available) + cardinality(p_unavailable) = 0
    or char_length(coalesce(p_note,'')) > 500 then
    raise exception using errcode = '22023', message = 'invalid_availability';
  end if;

  insert into public.schedule_submissions (user_id, store_id, week, available_day, impossible_day, etc)
  values (auth.uid(), p_store, p_week, p_available, p_unavailable, nullif(btrim(p_note),''))
  on conflict (user_id, store_id, week) do update
  set available_day = excluded.available_day, impossible_day = excluded.impossible_day, etc = excluded.etc;
end;
$$;

create or replace function crewfit_private.crewfit_publish_schedule(p_store bigint, p_week date, p_items jsonb)
returns void language plpgsql security definer set search_path = '' as $$
declare
  published_id bigint;
begin
  perform id from public.stores where id = p_store for update;
  if not crewfit_private.schedule_access(p_store, p_week) then
    raise exception using errcode = '42501', message = 'owner_only';
  end if;
  if jsonb_typeof(p_items) is distinct from 'object' or p_items = '{}'::jsonb then
    raise exception using errcode = '22023', message = 'invalid_assignments';
  end if;
  if exists (
    select 1 from jsonb_each(p_items) i
    where jsonb_typeof(i.value) <> 'string'
      or char_length(btrim(i.value #>> '{}')) not between 1 and 500
      or not exists (
        select 1 from public.employees e
        join public.profiles p on p.id = e.user_id and not p.is_deleted
        where e.store_id = p_store and e.user_id::text = i.key
      )
  ) then
    raise exception using errcode = '22023', message = 'invalid_assignments';
  end if;

  insert into public.confirmed_schedules as s (store_id, week, created_by)
  values (p_store, p_week, auth.uid())
  on conflict (store_id, week) do update set created_by = excluded.created_by
  returning s.id into published_id;

  delete from public.confirmed_schedule_items i
  using public.employees e, public.profiles p
  where i.schedule_id = published_id and e.store_id = p_store
    and i.user_id = e.user_id and p.id = e.user_id and not p.is_deleted;

  insert into public.confirmed_schedule_items (schedule_id, user_id, schedule_text)
  select published_id, i.key::uuid, btrim(i.value)
  from jsonb_each_text(p_items) i;
end;
$$;

create or replace function public.crewfit_schedule_week(p_store bigint, p_week date)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select crewfit_private.crewfit_schedule_week(p_store, p_week);
$$;
revoke all on function public.crewfit_schedule_week(bigint,date), crewfit_private.crewfit_schedule_week(bigint,date) from public, anon, authenticated;
grant execute on function public.crewfit_schedule_week(bigint,date), crewfit_private.crewfit_schedule_week(bigint,date) to authenticated;

create or replace function public.crewfit_submit_schedule(p_store bigint, p_week date, p_available text[], p_unavailable text[], p_note text)
returns void language sql volatile security invoker set search_path = '' as $$
  select crewfit_private.crewfit_submit_schedule(p_store, p_week, p_available, p_unavailable, p_note);
$$;
revoke all on function public.crewfit_submit_schedule(bigint,date,text[],text[],text), crewfit_private.crewfit_submit_schedule(bigint,date,text[],text[],text) from public, anon, authenticated;
grant execute on function public.crewfit_submit_schedule(bigint,date,text[],text[],text), crewfit_private.crewfit_submit_schedule(bigint,date,text[],text[],text) to authenticated;

create or replace function public.crewfit_publish_schedule(p_store bigint, p_week date, p_items jsonb)
returns void language sql volatile security invoker set search_path = '' as $$
  select crewfit_private.crewfit_publish_schedule(p_store, p_week, p_items);
$$;
revoke all on function public.crewfit_publish_schedule(bigint,date,jsonb), crewfit_private.crewfit_publish_schedule(bigint,date,jsonb) from public, anon, authenticated;
grant execute on function public.crewfit_publish_schedule(bigint,date,jsonb), crewfit_private.crewfit_publish_schedule(bigint,date,jsonb) to authenticated;
