alter table public.confirmed_schedules
  add column if not exists visibility text not null default 'self'
  check (visibility in ('self', 'all'));

create or replace function crewfit_private.crewfit_schedule_week(p_store bigint, p_week date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  caller uuid := auth.uid();
  is_owner boolean := crewfit_private.schedule_access(p_store, p_week);
  published_id bigint;
  published_visibility text := 'self';
begin
  select id, visibility into published_id, published_visibility
  from public.confirmed_schedules
  where store_id = p_store and week = p_week;

  return jsonb_build_object(
    'is_owner', is_owner,
    'published', published_id is not null,
    'visibility', published_visibility,
    'employees', coalesce((
      select jsonb_agg(jsonb_build_object(
        'user_id', e.user_id,
        'name', coalesce(nullif(p.user_name, ''), nullif(u.raw_user_meta_data->>'full_name', ''),
          nullif(u.raw_user_meta_data->>'name', ''), '직원 ' || left(e.user_id::text, 8)),
        'default_start', case when is_owner then to_char(e.default_start_time, 'HH24:MI') end,
        'available', case when is_owner or e.user_id = caller then s.available_day end,
        'unavailable', case when is_owner or e.user_id = caller then s.impossible_day end,
        'note', case when is_owner or e.user_id = caller then s.etc end,
        'submitted', case when is_owner or e.user_id = caller then s.id is not null end
      ) order by p.user_name nulls last, e.user_id)
      from public.employees e
      join public.profiles p on p.id = e.user_id and not p.is_deleted
      join auth.users u on u.id = e.user_id
      left join public.schedule_submissions s
        on s.user_id = e.user_id and s.store_id = e.store_id and s.week = p_week
      where e.store_id = p_store
        and (is_owner or e.user_id = caller or
          (published_id is not null and published_visibility = 'all'))
    ), '[]'::jsonb),
    'items', coalesce((
      select jsonb_object_agg(i.user_id::text, i.schedule_text order by i.id)
      from public.confirmed_schedule_items i
      where i.schedule_id = published_id and i.user_id is not null
        and (is_owner or i.user_id = caller or published_visibility = 'all')
    ), '{}'::jsonb)
  );
end;
$$;

drop function if exists public.crewfit_publish_schedule(bigint, date, jsonb);
drop function if exists crewfit_private.crewfit_publish_schedule(bigint, date, jsonb);

create function crewfit_private.crewfit_publish_schedule(
  p_store bigint, p_week date, p_items jsonb, p_visibility text
)
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
  if p_visibility is null or p_visibility not in ('self', 'all') then
    raise exception using errcode = '22023', message = 'invalid_visibility';
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

  insert into public.confirmed_schedules as s (store_id, week, created_by, visibility)
  values (p_store, p_week, auth.uid(), p_visibility)
  on conflict (store_id, week) do update
    set created_by = excluded.created_by, visibility = excluded.visibility
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

create function public.crewfit_publish_schedule(
  p_store bigint, p_week date, p_items jsonb, p_visibility text
)
returns void language sql security invoker set search_path = '' as $$
  select crewfit_private.crewfit_publish_schedule(p_store, p_week, p_items, p_visibility);
$$;

revoke all on function public.crewfit_publish_schedule(bigint,date,jsonb,text),
  crewfit_private.crewfit_publish_schedule(bigint,date,jsonb,text) from public, anon, authenticated;
grant execute on function public.crewfit_publish_schedule(bigint,date,jsonb,text),
  crewfit_private.crewfit_publish_schedule(bigint,date,jsonb,text) to authenticated;
