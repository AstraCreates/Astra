-- Wave 1 control plane: founder-level reservation ledger metadata.
-- The reservation contract intentionally keeps founder/accounting metadata
-- out of astra_budget_reservations itself; this side table persists the
-- founder-scoped reservation bookkeeping that W1.3 needs for atomic balance
-- checks and later reconciliation.

create table if not exists astra_budget_reservation_ledgers (
  reservation_id         text primary key references astra_budget_reservations(id) on delete cascade,
  founder_id             text not null,
  reserved_credits       bigint not null default 0,
  markup                 numeric(12,6) not null default 10.0,
  billed_credits         bigint not null default 0,
  overspend_usd          numeric(12,6) not null default 0,
  unreconciled_credits   bigint not null default 0,
  reconciliation_error   text,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index if not exists astra_budget_reservation_ledgers_founder_idx
  on astra_budget_reservation_ledgers(founder_id);
