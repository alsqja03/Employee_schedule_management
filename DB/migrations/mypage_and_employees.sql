create or replace function crewfit_private.crewfit_my_profile()
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('name',p.user_name,'telephone',p.telephone,'birth',p.birth,'deleted',p.is_deleted)
  from public.profiles p where p.id = (select auth.uid());
$$;

create or replace function crewfit_private.crewfit_save_profile(p_name text, p_phone text, p_birth date)
returns void language plpgsql security definer set search_path = '' as $$
declare
  caller uuid := auth.uid();
  clean_name text := btrim(p_name);
begin
  if caller is null then
    raise exception using errcode = '42501', message = 'login_required';
  end if;
  if clean_name is null or char_length(clean_name) not between 1 and 80
     or char_length(coalesce(p_phone,'')) > 24
     or (p_birth is not null and (p_birth < date '1900-01-01' or p_birth > (now() at time zone 'Asia/Seoul')::date)) then
    raise exception using errcode = '22023', message = 'invalid_profile';
  end if;

  insert into public.profiles as p(id,user_name,telephone,birth)
  values(caller,clean_name,nullif(btrim(p_phone),''),p_birth)
  on conflict (id) do update set user_name = excluded.user_name,
    telephone = excluded.telephone, birth = excluded.birth
  where not p.is_deleted;
  if not found then
    raise exception using errcode = '42501', message = 'inactive_profile';
  end if;
end;
$$;

create or replace function crewfit_private.crewfit_withdraw()
returns void language plpgsql security definer set search_path = '' as $$
declare
  caller uuid := auth.uid();
begin
  if caller is null then
    raise exception using errcode = '42501', message = 'login_required';
  end if;

  insert into public.profiles as p(id,is_deleted,deleted_at)
  values(caller,true,now())
  on conflict (id) do update set is_deleted = true, deleted_at = now(),
    user_name = null, telephone = null, birth = null
  where not p.is_deleted;
end;
$$;

create or replace function crewfit_private.crewfit_store_employees(p_store bigint)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not exists (
    select 1 from public.stores s join public.profiles p on p.id = s.user_id
    where s.id = p_store and s.user_id = (select auth.uid()) and not s.is_deleted and not p.is_deleted
  ) then
    raise exception using errcode = '42501', message = 'owner_only';
  end if;

  return coalesce((
    select jsonb_agg(jsonb_build_object(
      'id',e.user_id,'name',coalesce(nullif(p.user_name,''),nullif(u.raw_user_meta_data->>'full_name',''),
        nullif(u.raw_user_meta_data->>'name',''),'직원 ' || left(e.user_id::text,8)),
      'start',to_char(e.default_start_time,'HH24:MI'),'position',e.position,
      'telephone',p.telephone,'birth',p.birth
    ) order by p.user_name nulls last,e.user_id)
    from public.employees e
    join public.profiles p on p.id = e.user_id and not p.is_deleted
    join auth.users u on u.id = e.user_id
    where e.store_id = p_store
  ),'[]'::jsonb);
end;
$$;

create or replace function public.crewfit_my_profile()
returns jsonb language sql stable security invoker set search_path = '' as $$
  select crewfit_private.crewfit_my_profile();
$$;
revoke all on function public.crewfit_my_profile(), crewfit_private.crewfit_my_profile() from public, anon, authenticated;
grant execute on function public.crewfit_my_profile(), crewfit_private.crewfit_my_profile() to authenticated;

create or replace function public.crewfit_save_profile(p_name text, p_phone text, p_birth date)
returns void language sql volatile security invoker set search_path = '' as $$
  select crewfit_private.crewfit_save_profile(p_name,p_phone,p_birth);
$$;
revoke all on function public.crewfit_save_profile(text,text,date), crewfit_private.crewfit_save_profile(text,text,date) from public, anon, authenticated;
grant execute on function public.crewfit_save_profile(text,text,date), crewfit_private.crewfit_save_profile(text,text,date) to authenticated;

create or replace function public.crewfit_withdraw()
returns void language sql volatile security invoker set search_path = '' as $$
  select crewfit_private.crewfit_withdraw();
$$;
revoke all on function public.crewfit_withdraw(), crewfit_private.crewfit_withdraw() from public, anon, authenticated;
grant execute on function public.crewfit_withdraw(), crewfit_private.crewfit_withdraw() to authenticated;

create or replace function public.crewfit_store_employees(p_store bigint)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select crewfit_private.crewfit_store_employees(p_store);
$$;
revoke all on function public.crewfit_store_employees(bigint), crewfit_private.crewfit_store_employees(bigint) from public, anon, authenticated;
grant execute on function public.crewfit_store_employees(bigint), crewfit_private.crewfit_store_employees(bigint) to authenticated;
