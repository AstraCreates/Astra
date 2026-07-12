-- Wave 1 control plane: Graphiti/FalkorDB projection job tracking.

create table if not exists astra_brain_projection_jobs (
  id           text primary key,
  record_id    text not null references astra_brain_records(id) on delete cascade,
  job_type     text not null check (job_type in ('upsert','tombstone','rebuild')),
  status       text not null default 'pending'
    check (status in ('pending','running','succeeded','failed','dead_letter')),
  error        text,
  created_at   timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists astra_brain_projection_jobs_record_idx on astra_brain_projection_jobs(record_id);
create index if not exists astra_brain_projection_jobs_pending_idx on astra_brain_projection_jobs(created_at)
  where status in ('pending','failed');
