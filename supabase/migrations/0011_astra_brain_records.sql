-- Wave 1 control plane: canonical Company Brain source records
-- (used from Wave 6 on -- Graphiti/FalkorDB is a rebuildable derived index,
-- this table is the authoritative source).

create table if not exists astra_brain_records (
  id            text primary key,
  company_id    text not null,
  source        text not null,
  external_id   text not null,
  version       int not null default 1,
  content_hash  text,
  provenance    jsonb not null default '{}',
  is_canonical  boolean not null default true,
  tombstoned_at timestamptz,
  created_at    timestamptz not null default now(),
  unique (company_id, source, external_id, version)
);

create index if not exists astra_brain_records_company_idx on astra_brain_records(company_id, is_canonical);
create index if not exists astra_brain_records_lookup_idx on astra_brain_records(company_id, source, external_id);
