-- Wave 1 control plane: artifact identity and verification status.

create table if not exists astra_artifacts (
  id                  text primary key,
  run_id              text not null references astra_runs(id) on delete cascade,
  step_id             text references astra_run_steps(id) on delete cascade,
  key                 text not null,
  uri                 text,
  content_hash        text,
  metadata            jsonb not null default '{}',
  verification_status text not null default 'unverified'
    check (verification_status in ('unverified','passed','weak','missing')),
  created_at          timestamptz not null default now()
);

create index if not exists astra_artifacts_run_idx on astra_artifacts(run_id, key);
