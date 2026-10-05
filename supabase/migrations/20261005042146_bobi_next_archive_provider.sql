-- Independent Bobi Next namespace. Apply only to an explicitly selected dev
-- project first; this migration does not alter vouchers or legacy Bobi tables.
create table public.bobi_next_archive_installations (
  installation_id text primary key check (installation_id ~ '^[A-Za-z0-9._-]{1,128}$'),
  token_sha256 text not null unique check (token_sha256 ~ '^[a-f0-9]{64}$'),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.bobi_next_archive_objects (
  id uuid primary key default gen_random_uuid(),
  installation_id text not null references public.bobi_next_archive_installations(installation_id),
  external_id text not null check (external_id ~ '^bobi2_[a-f0-9]{48}$'),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  size_bytes integer not null check (size_bytes between 1 and 10485760),
  mime_type text not null check (mime_type in (
    'application/pdf', 'text/plain', 'text/csv', 'application/json',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic', 'image/heif',
    'audio/ogg', 'audio/opus', 'audio/mpeg', 'audio/mp4', 'audio/aac',
    'audio/wav', 'audio/x-wav', 'audio/webm'
  )),
  filename text not null check (char_length(filename) between 1 and 255),
  object_path text not null unique,
  state text not null default 'pending' check (state in ('pending', 'ready')),
  lease_owner uuid,
  lease_expires_at timestamptz,
  created_at timestamptz not null default now(),
  verified_at timestamptz,
  unique (installation_id, external_id, sha256),
  check (object_path = encode(sha256(convert_to(installation_id, 'UTF8')), 'hex')
    || '/' || external_id || '/' || sha256),
  check ((lease_owner is null) = (lease_expires_at is null)),
  check (state <> 'ready' or (lease_owner is null and verified_at is not null))
);

-- Bind every key, including a new key deduplicating an existing SHA. This
-- prevents a duplicate's key from later being reused for different bytes.
create table public.bobi_next_archive_requests (
  installation_id text not null references public.bobi_next_archive_installations(installation_id),
  external_id text not null check (external_id ~ '^bobi2_[a-f0-9]{48}$'),
  idempotency_key text not null check (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now(),
  primary key (installation_id, external_id, idempotency_key)
);

alter table public.bobi_next_archive_installations enable row level security;
alter table public.bobi_next_archive_objects enable row level security;
alter table public.bobi_next_archive_requests enable row level security;
revoke all on public.bobi_next_archive_installations,
  public.bobi_next_archive_objects, public.bobi_next_archive_requests
  from public, anon, authenticated;
grant select, insert, update on public.bobi_next_archive_installations,
  public.bobi_next_archive_objects, public.bobi_next_archive_requests to service_role;

create function public.bobi_next_archive_claim(
  p_installation text, p_subject text, p_sha256 text, p_size integer,
  p_mime text, p_filename text, p_key text, p_lease uuid
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_bound_sha text;
  v_object public.bobi_next_archive_objects%rowtype;
  v_status text;
begin
  if not exists (select 1 from public.bobi_next_archive_installations
      where installation_id = p_installation and enabled) then
    return jsonb_build_object('status', 'disabled');
  end if;
  if p_lease is null then raise exception 'lease_required'; end if;
  insert into public.bobi_next_archive_requests
    (installation_id, external_id, idempotency_key, sha256)
    values (p_installation, p_subject, p_key, p_sha256)
    on conflict (installation_id, external_id, idempotency_key) do nothing;
  select sha256 into v_bound_sha from public.bobi_next_archive_requests
    where installation_id = p_installation and external_id = p_subject and idempotency_key = p_key;
  if v_bound_sha <> p_sha256 then
    return jsonb_build_object('status', 'conflict');
  end if;
  insert into public.bobi_next_archive_objects
    (installation_id, external_id, sha256, size_bytes, mime_type, filename, object_path)
    values (p_installation, p_subject, p_sha256, p_size, p_mime, p_filename,
      encode(sha256(convert_to(p_installation, 'UTF8')), 'hex') || '/' || p_subject || '/' || p_sha256)
    on conflict (installation_id, external_id, sha256) do nothing;
  -- The lock ends with this RPC transaction; Storage I/O is outside it.
  select * into v_object from public.bobi_next_archive_objects
    where installation_id = p_installation and external_id = p_subject and sha256 = p_sha256
    for update;
  if v_object.size_bytes <> p_size then
    return jsonb_build_object('status', 'conflict');
  end if;
  if v_object.state = 'ready' then
    v_status := 'ready';
  elsif v_object.lease_expires_at > clock_timestamp() then
    return jsonb_build_object('status', 'busy');
  else
    update public.bobi_next_archive_objects
      set lease_owner = p_lease, lease_expires_at = clock_timestamp() + interval '5 minutes'
      where id = v_object.id;
    v_status := 'claimed';
  end if;
  return jsonb_build_object('status', v_status, 'media', jsonb_build_object(
    'id', v_object.id, 'object_path', v_object.object_path, 'sha256', v_object.sha256,
    'size_bytes', v_object.size_bytes, 'mime_type', v_object.mime_type, 'filename', v_object.filename
  ));
end;
$$;

create function public.bobi_next_archive_complete(
  p_installation text, p_subject text, p_id uuid, p_lease uuid
) returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  update public.bobi_next_archive_objects
    set state = 'ready', verified_at = clock_timestamp(), lease_owner = null, lease_expires_at = null
    where installation_id = p_installation and external_id = p_subject and id = p_id
      and state = 'pending' and lease_owner = p_lease and lease_expires_at > clock_timestamp()
      and exists (select 1 from public.bobi_next_archive_installations
        where installation_id = p_installation and enabled);
  return found;
end;
$$;

create function public.bobi_next_archive_release(
  p_installation text, p_subject text, p_id uuid, p_lease uuid
) returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  update public.bobi_next_archive_objects set lease_owner = null, lease_expires_at = null
    where installation_id = p_installation and external_id = p_subject and id = p_id
      and state = 'pending' and lease_owner = p_lease;
  return found;
end;
$$;

revoke all on function public.bobi_next_archive_claim(text, text, text, integer, text, text, text, uuid),
  public.bobi_next_archive_complete(text, text, uuid, uuid),
  public.bobi_next_archive_release(text, text, uuid, uuid) from public, anon, authenticated;
grant execute on function public.bobi_next_archive_claim(text, text, text, integer, text, text, text, uuid),
  public.bobi_next_archive_complete(text, text, uuid, uuid),
  public.bobi_next_archive_release(text, text, uuid, uuid) to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('bobi-next-archive', 'bobi-next-archive', false, 10485760, array[
    'application/pdf', 'text/plain', 'text/csv', 'application/json', 'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic', 'image/heif',
    'audio/ogg', 'audio/opus', 'audio/mpeg', 'audio/mp4', 'audio/aac',
    'audio/wav', 'audio/x-wav', 'audio/webm'
  ]) on conflict (id) do nothing;
do $$
begin
  if exists (select 1 from storage.buckets where id = 'bobi-next-archive'
      and (public is distinct from false or file_size_limit is distinct from 10485760)) then
    raise exception 'archive_bucket_configuration_conflict';
  end if;
end;
$$;

-- Defense against existing broad permissive Storage policies in a target
-- project. The service backend bypasses RLS; clients cannot access this bucket.
create policy bobi_next_archive_server_only on storage.objects
  as restrictive for all to anon, authenticated
  using (bucket_id <> 'bobi-next-archive')
  with check (bucket_id <> 'bobi-next-archive');
