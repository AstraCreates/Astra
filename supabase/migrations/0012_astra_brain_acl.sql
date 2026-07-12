-- Wave 1 control plane: per-record access control for Company Brain.
-- Retrieval enforcement (Wave 6, W6.3) rechecks every Graphiti candidate
-- against this table before returning canonical source text.

create table if not exists astra_brain_acl (
  id             text primary key,
  record_id      text not null references astra_brain_records(id) on delete cascade,
  principal_type text not null check (principal_type in ('company','user','role')),
  principal_id   text not null,
  access_level   text not null default 'read' check (access_level in ('read','write')),
  created_at     timestamptz not null default now(),
  unique (record_id, principal_type, principal_id)
);

create index if not exists astra_brain_acl_record_idx on astra_brain_acl(record_id);
create index if not exists astra_brain_acl_principal_idx on astra_brain_acl(principal_type, principal_id);
