# RLS intent (documentation only — no policies applied yet)

None of these tables have RLS enabled yet. The backend talks to Supabase
exclusively via the service-role key (`backend/db/client.py::get_supabase()`),
which bypasses RLS entirely — so nothing here is a live gap today. This
documents intent for whenever an authenticated-client (non-service-role) read
path is added for any of these tables, per the plan's own rollout sequencing
(RLS is not part of Wave 1's bar).

- **astra_runs**: service-role bypasses RLS for all backend writes. A future
  client read path would filter `owner_id = auth.uid()` OR org membership
  (`org_id` in the caller's orgs, joined through whatever org-membership table
  exists at that time).
- **astra_run_steps**, **astra_actions**, **astra_approval_requests**,
  **astra_run_events**, **astra_artifacts**, **astra_budget_reservations**:
  all scoped by `run_id` — a client read policy would join back to
  `astra_runs` and apply the same owner/org check as above rather than
  duplicating ownership columns on every child table.
- **astra_outbox**: never client-readable. Internal publisher-only table.
- **astra_action_receipts**: never client-readable directly — sensitive
  provider results. Any UI surface should go through a backend endpoint that
  redacts before returning, not direct table access.
- **astra_shadow_comparisons**: internal/operator-only. A policy (once
  built) should restrict to platform admins, not regular founders.
- **astra_brain_records**: canonical source records. A policy MUST recheck
  every candidate against `astra_brain_acl` (Wave 6, W6.3's own retrieval
  flow already does this at the application layer — RLS would be a second,
  redundant enforcement layer, valuable specifically because it fails closed
  even if application code has a bug).
- **astra_brain_acl**: readable only by the record's own access-check path;
  never broadly listable by a client (would leak who-has-access-to-what).
- **astra_brain_projection_jobs**: internal/operator-only, same posture as
  `astra_shadow_comparisons`.
