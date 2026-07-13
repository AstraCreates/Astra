-- Wave 2 control plane: transactional run creation + initial run.created event.
--
-- This closes the gap where application code previously created astra_runs and
-- then appended run.created in a second call. New callers can create the run
-- row and initial ordered event in one database transaction.

create or replace function astra_create_run_with_event(
  p_run jsonb,
  p_event_type text,
  p_event_payload jsonb
) returns bigint
language plpgsql
as $$
declare
  v_run_id text;
begin
  v_run_id := p_run->>'id';
  if v_run_id is null or v_run_id = '' then
    raise exception 'astra_create_run_with_event: run id is required';
  end if;

  insert into astra_runs (
    id,
    owner_id,
    org_id,
    company_id,
    workspace_id,
    chapter_id,
    parent_run_id,
    goal,
    stack_id,
    engine,
    workflow_version,
    status,
    next_event_sequence,
    budget_limit_usd,
    created_at,
    started_at,
    completed_at,
    cancellation_requested_at,
    error,
    metadata
  ) values (
    v_run_id,
    p_run->>'owner_id',
    p_run->>'org_id',
    p_run->>'company_id',
    p_run->>'workspace_id',
    p_run->>'chapter_id',
    p_run->>'parent_run_id',
    p_run->>'goal',
    p_run->>'stack_id',
    coalesce(p_run->>'engine', 'legacy'),
    coalesce(p_run->>'workflow_version', 'v1'),
    coalesce(p_run->>'status', 'queued'),
    coalesce((p_run->>'next_event_sequence')::bigint, 0),
    nullif(p_run->>'budget_limit_usd', '')::numeric,
    coalesce((p_run->>'created_at')::timestamptz, now()),
    nullif(p_run->>'started_at', '')::timestamptz,
    nullif(p_run->>'completed_at', '')::timestamptz,
    nullif(p_run->>'cancellation_requested_at', '')::timestamptz,
    p_run->>'error',
    coalesce(p_run->'metadata', '{}'::jsonb)
  )
  on conflict (id) do update
    set owner_id = excluded.owner_id,
        org_id = excluded.org_id,
        company_id = excluded.company_id,
        workspace_id = excluded.workspace_id,
        chapter_id = excluded.chapter_id,
        parent_run_id = excluded.parent_run_id,
        goal = excluded.goal,
        stack_id = excluded.stack_id,
        engine = excluded.engine,
        workflow_version = excluded.workflow_version,
        status = excluded.status,
        next_event_sequence = excluded.next_event_sequence,
        budget_limit_usd = excluded.budget_limit_usd,
        created_at = excluded.created_at,
        started_at = excluded.started_at,
        completed_at = excluded.completed_at,
        cancellation_requested_at = excluded.cancellation_requested_at,
        error = excluded.error,
        metadata = excluded.metadata;

  return astra_append_run_event(v_run_id, p_event_type, p_event_payload);
end;
$$;
