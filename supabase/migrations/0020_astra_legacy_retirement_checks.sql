-- Wave 7: legacy-retirement readiness checks.

create table if not exists astra_legacy_retirement_checks (
  id                          text primary key,
  feature                     text not null unique,
  status                      text not null
    check (status in ('pending','ready','blocked','completed')),
  temporal_run_count          int not null default 0,
  clean_days                  int not null default 0,
  restart_chaos_passed        boolean not null default false,
  parity_discrepancies_open   int not null default 0,
  rollback_drill_passed       boolean not null default false,
  archival_snapshots_exported boolean not null default false,
  metadata                    jsonb not null default '{}',
  created_at                  timestamptz not null default now(),
  completed_at                timestamptz
);

create index if not exists astra_legacy_retirement_checks_status_idx
  on astra_legacy_retirement_checks(feature, status);
