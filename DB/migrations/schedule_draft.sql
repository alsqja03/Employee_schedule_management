alter table public.employees
  add column if not exists default_start_time time(0) without time zone;

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
        'default_start', case when is_owner then to_char(e.default_start_time, 'HH24:MI') end,
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

create or replace function crewfit_private.crewfit_save_default_starts(p_store bigint, p_times jsonb)
returns void language plpgsql security definer set search_path = '' as $$
begin
  perform id from public.stores where id = p_store for update;
  if not exists (
    select 1 from public.stores s join public.profiles p on p.id = s.user_id
    where s.id = p_store and s.user_id = (select auth.uid()) and not s.is_deleted and not p.is_deleted
  ) then
    raise exception using errcode = '42501', message = 'owner_only';
  end if;
  if jsonb_typeof(p_times) is distinct from 'object' then
    raise exception using errcode = '22023', message = 'invalid_default_starts';
  end if;
  if exists (
    select 1 from jsonb_each_text(p_times) i
    where (i.value is not null and i.value !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
       or not exists (
         select 1 from public.employees e
         join public.profiles p on p.id = e.user_id and not p.is_deleted
         where e.store_id = p_store and e.user_id::text = i.key
       )
  ) then
    raise exception using errcode = '22023', message = 'invalid_default_starts';
  end if;

  update public.employees e
  set default_start_time = i.value::time
  from jsonb_each_text(p_times) i
  where e.store_id = p_store and e.user_id::text = i.key;
end;
$$;

create or replace function public.crewfit_save_default_starts(p_store bigint, p_times jsonb)
returns void language sql security invoker set search_path = '' as $$
  select crewfit_private.crewfit_save_default_starts(p_store, p_times);
$$;

revoke all on function public.crewfit_save_default_starts(bigint,jsonb),
  crewfit_private.crewfit_save_default_starts(bigint,jsonb) from public, anon, authenticated;
grant execute on function public.crewfit_save_default_starts(bigint,jsonb),
  crewfit_private.crewfit_save_default_starts(bigint,jsonb) to authenticated;
