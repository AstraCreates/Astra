-- Wave 1 control plane: external idempotency receipts.

create table if not exists astra_action_receipts (
  id                text primary key,
  action_id         text not null references astra_actions(id) on delete cascade,
  idempotency_key   text not null,
  provider_result   jsonb,
  collision_status  text not null default 'none'
    check (collision_status in ('none','detected','resolved')),
  created_at        timestamptz not null default now(),
  unique (idempotency_key)
);

create index if not exists astra_action_receipts_action_idx on astra_action_receipts(action_id);
