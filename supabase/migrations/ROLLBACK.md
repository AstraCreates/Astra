# Rollback

Run in reverse order (0013 → 0001). Preserves `supabase/schema.sql`'s legacy
tables untouched — nothing here overlaps with them.

```sql
-- 0013_astra_brain_projection_jobs.sql
drop table if exists astra_brain_projection_jobs;

-- 0012_astra_brain_acl.sql
drop table if exists astra_brain_acl;

-- 0011_astra_brain_records.sql
drop table if exists astra_brain_records;

-- 0010_astra_shadow_comparisons.sql
drop table if exists astra_shadow_comparisons;

-- 0009_astra_action_receipts.sql
drop table if exists astra_action_receipts;

-- 0014_astra_budget_reservation_ledgers.sql
drop table if exists astra_budget_reservation_ledgers;

-- 0008_astra_budget_reservations.sql
drop table if exists astra_budget_reservations;

-- 0007_astra_artifacts.sql
drop table if exists astra_artifacts;

-- 0006_astra_run_events.sql
drop function if exists astra_append_run_event(text, text, jsonb);
drop table if exists astra_run_events;

-- 0005_astra_outbox.sql
drop table if exists astra_outbox;

-- 0004_astra_approval_requests.sql
drop table if exists astra_approval_requests;

-- 0003_astra_actions.sql
drop table if exists astra_actions;

-- 0002_astra_run_steps.sql
drop table if exists astra_run_steps;

-- 0001_astra_runs.sql
drop table if exists astra_runs;
```
