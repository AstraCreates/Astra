-- Wave 1 control plane: external-side-effect ledger.

create table if not exists astra_actions (
  id                  text primary key,
  run_id              text not null references astra_runs(id) on delete cascade,
  step_id             text references astra_run_steps(id) on delete cascade,
  tool                text not null,
  canonical_args_hash text not null,
  risk_level          text not null default 'low',
  approval_id         text,
  idempotency_key     text not null,
  status              text not null default 'pending'
    check (status in ('pending','approved','executing','succeeded','failed','blocked')),
  receipt             jsonb,
  created_at          timestamptz not null default now(),
  executed_at         timestamptz,
  unique (idempotency_key)
);

create index if not exists astra_actions_run_idx on astra_actions(run_id);
create index if not exists astra_actions_step_idx on astra_actions(step_id);
create index if not exists astra_actions_approval_idx on astra_actions(approval_id);
