begin;
create schema if not exists crewfit_private;
revoke all on schema crewfit_private from public, anon, authenticated;
grant usage on schema crewfit_private to authenticated;
alter table public.stores add column if not exists invite_code text;
create unique index if not exists stores_invite_code_key
  on public.stores (invite_code) where invite_code is not null;

create or replace function crewfit_private.crewfit_create_store(p_name text)
returns void language plpgsql security definer set search_path = ''
as $$
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

  insert into public.profiles (id) values (caller) on conflict (id) do nothing;
  if not exists (select 1 from public.profiles where id = caller and not is_deleted) then
    raise exception using errcode = '42501', message = 'inactive_profile';
  end if;

  insert into public.stores (user_id, store_name, invite_code)
  values (caller, clean_name, upper(replace(gen_random_uuid()::text, '-', '')));
end;
$$;

create or replace function crewfit_private.crewfit_issue_invite(p_store_id bigint)
returns text language sql security definer set search_path = ''
as $$
  update public.stores s
     set invite_code = coalesce(s.invite_code, upper(replace(gen_random_uuid()::text, '-', '')))
   where s.id = p_store_id and s.user_id = (select auth.uid()) and not s.is_deleted
     and exists (select 1 from public.profiles p where p.id = s.user_id and not p.is_deleted)
  returning s.invite_code;
$$;

create or replace function crewfit_private.crewfit_join_store(p_code text)
returns text language plpgsql security definer set search_path = ''
as $$
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

  insert into public.profiles (id) values (caller) on conflict (id) do nothing;
  if not exists (select 1 from public.profiles where id = caller and not is_deleted) then
    raise exception using errcode = '42501', message = 'inactive_profile';
  end if;

  insert into public.employees (user_id, store_id, position)
  values (caller, target.id, '직원')
  on conflict (user_id, store_id) do nothing;
  return target.store_name;
end;
$$;

create or replace function crewfit_private.crewfit_my_stores()
returns table (store_id bigint, store_name text, is_owner boolean, invite_code text)
language sql stable security definer set search_path = ''
as $$
  select s.id, s.store_name, s.user_id = caller.id,
         case when s.user_id = caller.id then s.invite_code end
    from public.profiles caller
    join public.stores s on not s.is_deleted
   where caller.id = (select auth.uid()) and not caller.is_deleted
     and exists (select 1 from public.profiles owner where owner.id = s.user_id and not owner.is_deleted)
     and (s.user_id = caller.id or exists (
       select 1 from public.employees e where e.user_id = caller.id and e.store_id = s.id
     ))
   order by s.store_name, s.id;
$$;

create or replace function public.crewfit_create_store(p_name text) returns void
language sql  security invoker set search_path = '' as $$
  select crewfit_private.crewfit_create_store(p_name);
$$;
revoke all on function public.crewfit_create_store(text), crewfit_private.crewfit_create_store(text) from public, anon, authenticated;
grant execute on function public.crewfit_create_store(text), crewfit_private.crewfit_create_store(text) to authenticated;
create or replace function public.crewfit_issue_invite(p_store_id bigint) returns text
language sql  security invoker set search_path = '' as $$
  select crewfit_private.crewfit_issue_invite(p_store_id);
$$;
revoke all on function public.crewfit_issue_invite(bigint), crewfit_private.crewfit_issue_invite(bigint) from public, anon, authenticated;
grant execute on function public.crewfit_issue_invite(bigint), crewfit_private.crewfit_issue_invite(bigint) to authenticated;
create or replace function public.crewfit_join_store(p_code text) returns text
language sql  security invoker set search_path = '' as $$
  select crewfit_private.crewfit_join_store(p_code);
$$;
revoke all on function public.crewfit_join_store(text), crewfit_private.crewfit_join_store(text) from public, anon, authenticated;
grant execute on function public.crewfit_join_store(text), crewfit_private.crewfit_join_store(text) to authenticated;
create or replace function public.crewfit_my_stores() returns table (store_id bigint, store_name text, is_owner boolean, invite_code text)
language sql stable security invoker set search_path = '' as $$
  select * from crewfit_private.crewfit_my_stores();
$$;
revoke all on function public.crewfit_my_stores(), crewfit_private.crewfit_my_stores() from public, anon, authenticated;
grant execute on function public.crewfit_my_stores(), crewfit_private.crewfit_my_stores() to authenticated;

commit;
