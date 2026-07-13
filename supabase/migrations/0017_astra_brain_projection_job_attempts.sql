-- Wave 6 hardening: projection-job retries and dead-letter tracking.

alter table if exists astra_brain_projection_jobs
  add column if not exists attempts int not null default 0,
  add column if not exists last_attempted_at timestamptz;
