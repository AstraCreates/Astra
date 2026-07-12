-- Wave 1 control plane: durable, strictly-ordered run event log.
--
-- The ordering guarantee (System Invariant: "a database function locks the
-- run row, increments next_event_sequence, and inserts the event and
-- outbox record atomically -- application-side counters are forbidden")
-- lives entirely in astra_append_run_event() below. Application code must
-- always call this function to record an event; it must never read
-- next_event_sequence and compute the next value itself, since that would
-- reintroduce the exact race this function exists to close.

create table if not exists astra_run_events (
  run_id       text not null references astra_runs(id) on delete cascade,
  sequence     bigint not null,
  event_type   text not null,
  payload      jsonb not null default '{}',
  created_at   timestamptz not null default now(),
  published_at timestamptz,
  primary key (run_id, sequence)
);

create index if not exists astra_run_events_run_seq_idx on astra_run_events(run_id, sequence);

create or replace function astra_append_run_event(
  p_run_id text,
  p_event_type text,
  p_payload jsonb
) returns bigint
language plpgsql
as $$
declare
  v_sequence bigint;
begin
  -- Lock the run row BEFORE reading next_event_sequence. Locking after the
  -- read (or not at all) is exactly the bug this function exists to close:
  -- two concurrent callers could both read the same value and assign the
  -- same sequence to two different events.
  select next_event_sequence into v_sequence
    from astra_runs
    where id = p_run_id
    for update;

  if not found then
    raise exception 'astra_append_run_event: run % does not exist', p_run_id;
  end if;

  update astra_runs
    set next_event_sequence = v_sequence + 1
    where id = p_run_id;

  insert into astra_run_events (run_id, sequence, event_type, payload)
    values (p_run_id, v_sequence, p_event_type, p_payload);

  insert into astra_outbox (run_id, event_sequence, payload)
    values (p_run_id, v_sequence, jsonb_build_object(
      'run_id', p_run_id,
      'sequence', v_sequence,
      'event_type', p_event_type,
      'payload', p_payload
    ));

  return v_sequence;
end;
$$;
