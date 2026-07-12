-- Wave 1 control plane: canonical run ledger.
-- Additive only. Does not touch supabase/schema.sql (legacy tables).

create table if not exists astra_runs (
  id                        text primary key,
  owner_id                  text not null,
  org_id                    text not null,
  company_id                text,
  workspace_id              text,
  chapter_id                text,
  parent_run_id             text references astra_runs(id),
  goal                      text not null,
  stack_id                  text,
  engine                    text not null default 'legacy',
  workflow_version          text not null default 'v1',
  status                    text not null default 'queued'
    check (status in ('queued','running','awaiting_approval','cancelling','cancelled','succeeded','failed')),
  next_event_sequence       bigint not null default 0,
  budget_limit_usd          numeric(12,4),
  created_at                timestamptz not null default now(),
  started_at                timestamptz,
  completed_at              timestamptz,
  cancellation_requested_at timestamptz,
  error                     text,
  metadata                  jsonb not null default '{}'
);

create index if not exists astra_runs_org_idx on astra_runs(org_id, status);
create index if not exists astra_runs_owner_idx on astra_runs(owner_id, created_at desc);
create index if not exists astra_runs_parent_idx on astra_runs(parent_run_id);
