-- Wave 2 control plane: durable outbox retry and dead-letter metadata.
--
-- The publisher now distinguishes "pending retry" from "terminally dead-lettered"
-- rows so operators can observe outbox failures without silently retrying
-- forever or losing the error cause.

alter table if exists astra_outbox
  add column if not exists dead_lettered_at timestamptz,
  add column if not exists last_error text;

create index if not exists astra_outbox_dead_letter_idx
  on astra_outbox(dead_lettered_at)
  where dead_lettered_at is not null;
