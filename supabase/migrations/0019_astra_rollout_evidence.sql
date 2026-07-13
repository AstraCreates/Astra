-- Wave 7: evidence ledger for rollout stages, halt probes, rollback drills, and archival snapshots.

create table if not exists astra_rollout_evidence (
  id          text primary key,
  campaign_id text not null references astra_rollout_campaigns(id) on delete cascade,
  run_id      text,
  kind        text not null
    check (kind in ('fixture','chaos','live_run','halt_probe','rollback_drill','archive_snapshot')),
  stage       text not null
    check (stage in ('internal_fixture','internal_live','pct_1','pct_5','pct_25','pct_50','pct_100')),
  passed      boolean not null default false,
  summary     text not null default '',
  metrics     jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

create index if not exists astra_rollout_evidence_campaign_idx
  on astra_rollout_evidence(campaign_id, created_at);
