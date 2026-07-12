-- Wave 1 control plane: per-attempt step ledger.
-- A retry is a NEW row sharing (run_id, step_key) with an incremented
-- attempt_number -- it never creates another run.

create table if not exists astra_run_steps (
  id             text primary key,
  run_id         text not null references astra_runs(id) on delete cascade,
  step_key       text not null,
  parent_step_id text references astra_run_steps(id),
  kind           text not null,
  agent          text,
  phase          text,
  status         text not null default 'queued'
    check (status in ('queued','running','awaiting_approval','cancelling','cancelled','succeeded','failed')),
  attempt_number int not null default 1,
  max_attempts   int not null default 1,
  input_ref      text,
  output_ref     text,
  idempotency_key text,
  started_at     timestamptz,
  heartbeat_at   timestamptz,
  completed_at   timestamptz,
  error          text,
  unique (run_id, step_key, attempt_number)
);

create index if not exists astra_run_steps_run_idx on astra_run_steps(run_id, status);
create index if not exists astra_run_steps_key_idx on astra_run_steps(run_id, step_key);
create index if not exists astra_run_steps_parent_idx on astra_run_steps(parent_step_id);
