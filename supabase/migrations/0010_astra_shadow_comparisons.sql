-- Wave 1 control plane: legacy/Temporal parity metrics (used from Wave 3 on).

create table if not exists astra_shadow_comparisons (
  id               text primary key,
  run_id           text not null references astra_runs(id) on delete cascade,
  comparison_type  text not null,
  discrepancies    jsonb not null default '[]',
  passed           boolean not null default false,
  created_at       timestamptz not null default now()
);

create index if not exists astra_shadow_comparisons_run_idx on astra_shadow_comparisons(run_id);
