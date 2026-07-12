-- Wave 1 control plane: transactional outbox for Redis Streams publication.
-- Rows are inserted by the same atomic function that assigns event
-- sequences (0006_astra_run_events.sql) -- never by application code
-- directly, so an event can never exist without a matching outbox row.

create table if not exists astra_outbox (
  id             bigint generated always as identity primary key,
  run_id         text not null references astra_runs(id) on delete cascade,
  event_sequence bigint not null,
  payload        jsonb not null,
  published_at   timestamptz,
  attempts       int not null default 0,
  created_at     timestamptz not null default now()
);

-- Partial index over unpublished rows only -- this is what the outbox
-- publisher polls, and it should stay small regardless of table growth.
create index if not exists astra_outbox_pending_idx on astra_outbox(created_at)
  where published_at is null;
