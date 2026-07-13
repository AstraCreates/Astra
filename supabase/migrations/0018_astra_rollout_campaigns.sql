-- Wave 7: rollout campaign state for staged Temporal/control-plane rollout.

create table if not exists astra_rollout_campaigns (
  id                         text primary key,
  feature                    text not null,
  stage                      text not null
    check (stage in ('internal_fixture','internal_live','pct_1','pct_5','pct_25','pct_50','pct_100')),
  status                     text not null
    check (status in ('draft','active','halted','rolled_back','completed')),
  started_at                 timestamptz,
  last_stage_changed_at      timestamptz,
  required_sample_size       int not null default 0,
  observed_sample_size       int not null default 0,
  required_observation_hours int not null default 24,
  metadata                   jsonb not null default '{}',
  created_at                 timestamptz not null default now(),
  completed_at               timestamptz
);

create index if not exists astra_rollout_campaigns_feature_status_idx
  on astra_rollout_campaigns(feature, status, created_at desc);
