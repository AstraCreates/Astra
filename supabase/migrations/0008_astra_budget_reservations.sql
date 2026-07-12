-- Wave 1 control plane: transactional budget reservations (W1.3 builds the
-- service on top of this table; this migration only lays down the schema).

create table if not exists astra_budget_reservations (
  id                  text primary key,
  run_id              text not null references astra_runs(id) on delete cascade,
  step_id             text references astra_run_steps(id) on delete cascade,
  estimated_max_usd   numeric(12,6) not null,
  actual_usd          numeric(12,6),
  status              text not null default 'reserved'
    check (status in ('reserved','committed','released','expired')),
  expires_at          timestamptz not null,
  provider_request_id text,
  reconciled_at       timestamptz,
  created_at          timestamptz not null default now()
);

create index if not exists astra_budget_reservations_run_idx on astra_budget_reservations(run_id, status);
-- Orphan reaper sweep: expired reservations still marked 'reserved'.
create index if not exists astra_budget_reservations_expiry_idx on astra_budget_reservations(expires_at)
  where status = 'reserved';
