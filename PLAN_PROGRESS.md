# Astra Durable Control Plane Migration — Progress Tracker

> Auto-generated status snapshot. Run `./scripts/monitor_plan_progress.sh` to refresh.

## Overall: ~15% Complete (Wave 0 done, Wave 1+ not started)

---

## Wave 0: Immediate Containment ✅

### W0.1 Approval Contract
- [x] Define final request-addressed approval contract
- [x] Require `approval_id` and `action_digest` for decisions
- [x] Resolve caller's actual role; never hardcode `owner`
- [x] Make timeout and missing decisions become `expired`
- [x] Consume decisions once and reject replay
- [x] Reopening rejected work creates new revision and pending request
- [x] Prevent multiple same-gate requests from collapsing into one state
- [x] Treat rejected and expired approvals as incomplete in completion audit
- [x] Reject ambiguous compatibility requests

### W0.2 Runtime and Token Safety
- [x] Move continuation vault context into run-local state
- [ ] Remove mutable per-run model config from singleton agents
- [x] Add atomic rerun ownership by (run_id, agent, operation)
- [x] Track all running task handles by attempt
- [x] Fence synchronous tools with persistent cancellation tokens and idempotency checks
- [ ] Serialize durable event persistence by sequence
- [ ] Persist parent-forwarded child events
- [ ] Sort and deduplicate restored events
- [x] Make terminal reducer states monotonic
- [x] Account compression summaries and malformed-response repair calls
- [x] Reserve tool-call attempts before parallel batches execute
- [x] Bound planner retry prompt growth
- [x] Reserve configured completion ceiling near session token limits
- [ ] Add completed-session in-memory eviction with durable replay fallback

### W0.3 Research Containment
- [x] Remove unconditional `deep_research` completion requirements
- [x] Use coverage readiness to decide escalation
- [x] Return structured per-query native-search answers and citations
- [x] Do not duplicate one shared result across every query
- [ ] Preserve two-round deep research when repaired arguments generate queries
- [x] Make deep-mode tool caps match advertised depth
- [x] Add source IDs and claim-level citation binding
- [ ] Replace blocking executor timeout behavior with cancellation-aware async I/O
- [x] Propagate cancellation through search, fetch, synthesis, and provider calls
- [x] Never mutate process-global provider environment variables

### W0.4 Frontend Integrity
- [x] Route goal submission and team APIs through authenticated `apiFetch`
- [x] Parse `GET /teams/me` as a collection
- [ ] Authenticate terminal WebSockets with short-lived tokens
- [x] Keep SSE connected if stop fails
- [ ] Preserve the original session if replacement submission fails
- [x] Display artifact content and files only from selected artifact or owner step
- [ ] Wire or remove the dashboard Pause control
- [x] Convert primary clickable divs into buttons or links with keyboard support

### W0.5 Operations and Health
- [x] Make TLS bootstrap work without existing certificate
- [x] Require HTTP 200 from readiness smoke checks
- [ ] Separate cheap metrics from expensive catalog/objective audits
- [ ] Protect detailed metrics with monitoring authentication or private networking
- [x] Add health checks for Headroom, CRW, backend, frontend, nginx
- [ ] Gate dependencies on health rather than container start
- [x] Add backend, Headroom, and nginx memory/PID/CPU limits
- [x] Reduce 128-thread executor and reserve capacity for interactive APIs
- [ ] Add executor backlog and cgroup pressure metrics

### W0.6 Tenancy and Compliance
- [x] Resolve company access by target workspace/company ID and verify ownership
- [x] Require signed preview access linked to owning session
- [x] Store PII retention receipts durably with expiry
- [ ] Make purge operate against shared durable storage
- [ ] Add distributed leases for auto-heal

---

## Wave 1: Contracts, Infrastructure, and Budget Foundation ❌

**Status:** Branch stubs exist (`control-plane-w1-1-schema`, `control-plane-w1-2-temporal`, `control-plane-w1-3-budget`, `control-plane-w1-4-flags`) but have 0 commits ahead of main.

### W1.1 Schema and Domain Contracts
- [ ] All canonical tables (astra_runs, astra_run_steps, astra_actions, astra_approval_requests, astra_run_events, astra_artifacts, astra_budget_reservations, astra_action_receipts, astra_outbox, astra_shadow_comparisons, astra_brain_records, astra_brain_acl, astra_brain_projection_jobs)
- [ ] Constraints, indexes, status checks, and database functions
- [ ] Pydantic models for run, step, action, approval, event, artifact, reservation, receipt
- [ ] Repository interfaces with local fake implementations for tests
- [ ] Backfill mapping existing session IDs into astra_runs
- [ ] RLS/service-role policy documentation
- [ ] Migration rollback scripts preserving legacy tables

### W1.2 Temporal Infrastructure
- [ ] Infrastructure Postgres with separate Temporal, visibility, and LiteLLM databases
- [ ] Temporal server, UI, schema initialization, and Python worker services
- [ ] Internal-only ports, TLS-ready settings, resource limits, backups, readiness checks
- [ ] Namespace `astra`, task queue `astra-runs-v1`, retention policy
- [ ] `temporalio` dependency and test-server fixture
- [ ] Workflow payload codec interface; workflow inputs remain ID-only

### W1.3 Transactional Budget Reservations
- [ ] `reserve`, `commit`, `release`, and `expire` service
- [ ] Atomic founder/org balance check and reservation creation
- [ ] Reservation TTL
- [ ] Orphan reaper: expired reservation with no active or terminal provider request released and audited
- [ ] Parent/child budget allocation from one shared account
- [ ] Repair, compression, and shadow work require reservations

### W1.4 Feature Assignment
- [x] Deterministic hash-based bucketing (SHA-256 of feature:founder_id)
- [x] `enabled()` function with percentage rollout support
- [ ] `ASTRA_CONTROL_PLANE_V2` flag
- [ ] `ASTRA_CONTROL_PLANE_V2_ROLLOUT_PERCENT` flag
- [ ] `ASTRA_TEMPORAL_SHADOW_PERCENT` flag
- [ ] `ASTRA_EVENT_STREAM_V2` flag
- [ ] `ASTRA_MODEL_GATEWAY_V2` flag
- [ ] `ASTRA_RESEARCH_ENGINE_V2` flag
- [ ] `ASTRA_BRAIN_V2` flag
- [ ] `ASTRA_LANGFUSE_ENABLED` flag
- [ ] Feature versions persisted on run creation

---

## Wave 2: Unified Commands and Ordered Events ❌

### W2.1 `StartRun` Application Service
- [ ] `POST /runs` endpoint
- [ ] `StartRun` application service class
- [ ] Authenticate actor and resolve org/company/workspace
- [ ] Validate goal and entitlements
- [ ] Reserve initial budget
- [ ] Create workspace/chapter if required
- [ ] Create durable run record
- [ ] Assign engine and feature versions
- [ ] Insert `run.created` in same transaction
- [ ] Dispatch to legacy or Temporal adapter after commit
- [ ] Return one canonical response

### W2.2 Submission Adapters
- [ ] HTTP routes delegate to `StartRun`
- [ ] MCP entrypoint delegates to `StartRun`
- [ ] Copilot dispatch delegates to `StartRun`
- [ ] Mission cycles delegate to `StartRun`
- [ ] Schedules delegate to `StartRun`

### W2.3 Durable Event Publisher
- [ ] Database-assigned per-run sequence using row lock or serializable function
- [ ] Atomic event and outbox insert
- [ ] Publisher writes Redis Streams `events:{org_id}:{run_id}` with stream ID `{sequence}-0`
- [ ] Retry and dead-letter handling for outbox publication
- [ ] Redis retention by length and age
- [ ] Supabase fallback when Redis unavailable
- [ ] Receipt-collision, sequence-gap, and outbox-lag alerts

### W2.4 SSE and Snapshot Projection
- [ ] Authorize before resolving stream keys
- [ ] Replay from Supabase to satisfy `Last-Event-ID`
- [ ] Use `XREAD` with independent cursor per connection
- [ ] Never use shared consuming queue for browser subscribers
- [ ] Materialize run snapshots from canonical rows and ordered events
- [ ] Preserve existing event payload compatibility

---

## Wave 3: Temporal Observation Shell ❌

### W3.1 Workflow Shell
- [ ] `AstraRunWorkflow` with workflow ID `astra-run/{run_id}`
- [ ] Signals: cancel, steer, approval decision, retry step
- [ ] Queries: workflow status, active step, waiting approval, cancellation state
- [ ] Initial legacy-orchestrator activity

### W3.2 Shadow Comparator
- [ ] Sample at most 5% of eligible runs
- [ ] Separate budget reservation and hard per-run ceiling
- [ ] No external effects
- [ ] Exact terminal-status comparison
- [ ] Required event ordering as ordered subset
- [ ] Deterministic artifact hashes
- [ ] Semantic artifact comparison
- [ ] Cost tolerance ±15%

### W3.3 Recovery Tests
- [ ] Worker death before and after activity dispatch
- [ ] Duplicate activity completion
- [ ] Signal during worker outage
- [ ] Cancellation during wait
- [ ] Server restart
- [ ] Workflow code version change
- [ ] No re-execution of legacy activity

---

## Wave 4: Durable Workflow Extraction ❌

### W4.1 Planner and Phase Workflows
- [ ] Planning activity
- [ ] Phase child workflows
- [ ] Dependency scheduling
- [ ] Continue-as-new thresholds
- [ ] Phase completion and verification transitions

### W4.2 Lane and Verification Activities
- [ ] One activity per bounded agent attempt
- [ ] Immutable run execution context
- [ ] Heartbeats for long tasks
- [ ] Explicit cancellation checkpoints
- [ ] Artifact verification as independent activity
- [ ] Step attempt records and outputs written transactionally

### W4.3 External Action Executor
- [ ] Normalize arguments
- [ ] Compute action digest and idempotency key
- [ ] Persist action before execution
- [ ] Require valid consumed approval when policy requires it
- [ ] Recheck cancellation immediately before effect
- [ ] Execute with provider idempotency key
- [ ] Persist receipt before returning success
- [ ] Treat receipt collision as critical alert

### W4.4 Durable Approval Waits
- [ ] Temporal waits on `approval_id`
- [ ] Approved decision must match request digest and policy version
- [ ] Timeout writes `expired`
- [ ] Late decisions rejected
- [ ] Duplicate decisions idempotent only when identical
- [ ] Decision consumed transactionally before action execution

### W4.5 Schedules and Cancellation
- [ ] Move recurring goals, auto-heal, and operating cycles to Temporal schedules
- [ ] Cancellation signals workflow
- [ ] Cancels pending children
- [ ] Activities heartbeat and observe cancellation
- [ ] Blocking tools use bounded subprocesses or cancellation-aware async clients

---

## Wave 5: Gateway, Research, Observability, and UI ❌

### W5.1 LiteLLM Gateway
- [ ] Deploy LiteLLM with per-org virtual keys and run_id/step_id metadata
- [ ] Astra reservation before gateway request
- [ ] Provider-normalized model aliases
- [ ] Fallback and rate-limit policy
- [ ] Actual token/cost reconciliation
- [ ] Cache-token pricing
- [ ] Request IDs linked to reservations and traces
- [ ] Direct provider paths disabled in production

### W5.2 OpenTelemetry and Langfuse
- [ ] Trace hierarchy: run → workflow → phase → step attempt → model/tool/action → artifact
- [ ] Required attributes: org, run, step, agent, model alias, provider, retry count, queue delay, tokens, cost, approval ID, action receipt, error class
- [ ] Redact goals, vault content, credentials, raw tool arguments, PII before export
- [ ] OpenTelemetry mandatory
- [ ] Langfuse hooks implemented but disabled

### W5.3 Research Engine V2
- [ ] Cheap native-search first pass retained
- [ ] Open Deep Research for deep escalation
- [ ] Canonical result format with query ID, claims, evidence IDs, source metadata
- [ ] Per-call clients; no global environment mutation
- [ ] Cancellation-aware network operations
- [ ] Deep research as cancellable Temporal child workflow
- [ ] Research agents write evidence artifacts incrementally

### W5.4 Frontend Control Plane
- [ ] Stable run identity across agent retries
- [ ] Agent start, goal, completion, research/technical summary, generated-image events
- [ ] Approval cards addressed by `approval_id`
- [ ] Accurate stop, retry, and restart progress
- [ ] Trace/status links for operators
- [ ] Explicit queued, cancelling, awaiting approval, degraded states
- [ ] Side panels use durable run/step/artifact data

---

## Wave 6: Company Brain V2 ❌ (~20% partial)

### W6.1 Canonical Record Ingestion
- [ ] Normalize connector content into `astra_brain_records`
- [ ] Identity: company_id + source + external_id + version
- [ ] Provenance, content hash, canonical status, supersession, tombstones
- [ ] ACL rows
- [ ] Idempotent ingest
- [ ] Outbox projection jobs

### W6.2 Graphiti/FalkorDB Projection
- [ ] One Graphiti group/namespace per company
- [ ] Upsert authorized episodes
- [ ] Apply corrections and supersession
- [ ] Propagate tombstones
- [ ] Full rebuild from Supabase

### W6.3 Retrieval Enforcement
- [ ] Authorize caller
- [ ] Query Graphiti for candidate record IDs
- [ ] Recheck every candidate against Supabase ACLs
- [ ] Fetch canonical source text from Supabase
- [ ] Rerank and return citations with temporal validity
- [ ] Fall back to canonical search if Graphiti unavailable

### W6.4 Shadow Benchmark
- [ ] Paraphrased facts, superseded facts, contradictions
- [ ] Deleted records, cross-company names
- [ ] Role-restricted records, connector outages
- [ ] Cutover requires zero tenant leaks

---

## Wave 7: Rollout and Legacy Retirement ❌

### Rollout Stages
- [ ] Internal fixture and chaos runs
- [ ] Ten internal live runs
- [ ] 1% → 5% → 25% → 50% → 100% beta
- [ ] Automatic halt conditions implemented
- [ ] Rollback procedures tested
- [ ] Legacy deletion after 100% rollout + 1000 runs or 30 clean days

---

## Legend
- `[x]` = Implemented and verified in code on `main`
- `[ ]` = Not yet implemented
- Branch stubs exist but have 0 commits ahead of main for Wave 1

## Last Updated
2026-07-12 — Based on codebase analysis and git branch inspection.
