-- Wave 1 control plane: request-addressed approval ledger.
-- Mirrors the contract already enforced in backend/approval_workflows.py
-- (Wave 0, W0.1) at the durable-storage layer: approval_id + action_digest
-- required for a decision, revision on reopen, expiry not approval.

create table if not exists astra_approval_requests (
  id              text primary key,
  run_id          text not null references astra_runs(id) on delete cascade,
  step_id         text references astra_run_steps(id) on delete cascade,
  action_id       text references astra_actions(id) on delete cascade,
  gate_key        text not null,
  action_digest   text not null,
  required_role   text not null default 'owner',
  policy_version  text not null default 'v1',
  status          text not null default 'pending'
    check (status in ('pending','approved','rejected','expired','skipped','consumed')),
  expires_at      timestamptz,
  decided_by      text,
  decision_note   text,
  decided_at      timestamptz,
  consumed_at     timestamptz,
  revision        int not null default 1,
  created_at      timestamptz not null default now()
);

create index if not exists astra_approval_requests_run_idx on astra_approval_requests(run_id, status);
create index if not exists astra_approval_requests_gate_idx on astra_approval_requests(run_id, gate_key, revision desc);
