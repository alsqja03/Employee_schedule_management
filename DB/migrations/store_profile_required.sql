CREATE OR REPLACE FUNCTION crewfit_private.crewfit_create_store(p_name text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  caller uuid := auth.uid();
  clean_name text := btrim(p_name);
begin
  if caller is null then
    raise exception using errcode = '42501', message = 'login_required';
  end if;
  if clean_name is null or char_length(clean_name) not between 1 and 100 then
    raise exception using errcode = '22023', message = 'invalid_store_name';
  end if;

  if not exists (
    select 1 from public.profiles
    where id = caller and not is_deleted and nullif(btrim(telephone),'') is not null and birth is not null
  ) then
    raise exception using errcode = '42501', message = 'profile_required';
  end if;

  insert into public.stores (user_id, store_name, invite_code)
  values (caller, clean_name, upper(replace(gen_random_uuid()::text, '-', '')));
end;
$function$;

CREATE OR REPLACE FUNCTION crewfit_private.crewfit_join_store(p_code text)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  caller uuid := auth.uid();
  invite text := upper(btrim(p_code));
  target public.stores%rowtype;
begin
  if caller is null then
    raise exception using errcode = '42501', message = 'login_required';
  end if;
  if invite is null or invite !~ '^[0-9A-F]{32}$' then
    return null;
  end if;

  select s.* into target from public.stores s
   where s.invite_code = invite and not s.is_deleted
     and exists (select 1 from public.profiles p where p.id = s.user_id and not p.is_deleted)
   for share of s;
  if not found then
    return null;
  end if;
  if target.user_id = caller then
    raise exception using errcode = '22023', message = 'already_owner';
  end if;

  if not exists (
    select 1 from public.profiles
    where id = caller and not is_deleted and nullif(btrim(telephone),'') is not null and birth is not null
  ) then
    raise exception using errcode = '42501', message = 'profile_required';
  end if;

  insert into public.employees (user_id, store_id, position)
  values (caller, target.id, '직원')
  on conflict (user_id, store_id) do nothing;
  return target.store_name;
end;
$function$;

CREATE OR REPLACE FUNCTION crewfit_private.crewfit_save_profile(p_name text, p_phone text, p_birth date)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  caller uuid := auth.uid();
  clean_name text := btrim(p_name);
begin
  if caller is null then
    raise exception using errcode = '42501', message = 'login_required';
  end if;
  if clean_name is null or char_length(clean_name) not between 1 and 80
     or coalesce(btrim(p_phone),'') = '' or char_length(p_phone) > 24
     or p_birth is null
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
$function$;
