#!/usr/bin/env bash
# monitor_plan_progress.sh — Scan codebase for Durable Control Plane Migration markers
# Run: ./scripts/monitor_plan_progress.sh
# Outputs a status report for each wave/section.

set -euo pipefail
cd "$(dirname "$0")/.."

PASS="✅"
PARTIAL="⚠️"
MISS="❌"
TOTAL_PASS=0
TOTAL_PARTIAL=0
TOTAL_MISS=0

check() {
  local label="$1"
  shift
  if eval "$@" >/dev/null 2>&1; then
    echo "  $PASS $label"
    TOTAL_PASS=$((TOTAL_PASS + 1))
  else
    echo "  $MISS $label"
    TOTAL_MISS=$((TOTAL_MISS + 1))
  fi
}

check_count() {
  local label="$1"
  local count="$2"
  local total="$3"
  if [ "$count" -eq 0 ]; then
    echo "  $MISS $label ($count/$total)"
    TOTAL_MISS=$((TOTAL_MISS + 1))
  elif [ "$count" -lt "$total" ]; then
    echo "  $PARTIAL $label ($count/$total)"
    TOTAL_PARTIAL=$((TOTAL_PARTIAL + 1))
  else
    echo "  $PASS $label ($count/$total)"
    TOTAL_PASS=$((TOTAL_PASS + 1))
  fi
}

echo "=============================================="
echo " Astra Durable Control Plane — Progress Scan"
echo " $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "=============================================="
echo ""

# ── Wave 0 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 0: Immediate Containment ━━"

check "W0.1 Approval contract (action_digest, revision, expired)" \
  'grep -rq "action_digest" backend/approval_workflows.py && grep -rq "revision" backend/approval_workflows.py && grep -rq "expired" backend/approval_workflows.py'

check "W0.2 Cancellation fences" \
  'grep -rq "cancellation_fence" backend/core/cancellation.py'

check "W0.2 Atomic rerun ownership" \
  'grep -rq "claim_attempt" backend/core/cancellation.py'

check "W0.2 RunBudget (iteration/tool/cost accounting)" \
  'test -f backend/runtime/budget.py && grep -rq "consume_iteration" backend/runtime/budget.py'

check "W0.3 Research containment (coverage readiness)" \
  'grep -rq "coverage.*readiness\|readiness.*coverage" backend/ -l 2>/dev/null | head -1 | grep -q .'

check "W0.3 Citation binding" \
  'grep -rq "source_ids\|citation_urls\|evidence_ids" backend/tools/ 2>/dev/null'

check "W0.4 apiFetch (authenticated frontend)" \
  'grep -rq "apiFetch" frontend/lib/api.ts'

check "W0.4 Team API as collection" \
  'grep -rq "teams/me" frontend/components/SettingsPage.tsx'

check "W0.5 Health checks (docker-compose)" \
  'grep -q "healthcheck" docker-compose.yml'

check "W0.5 Resource limits (docker-compose)" \
  'grep -q "mem_limit" docker-compose.yml'

check "W0.6 Signed preview access" \
  'grep -rq "preview_token\|signed.*preview" backend/api/preview_proxy.py'

check "W0.6 PII vault with expiry" \
  'test -f backend/core/pii_vault.py && grep -rq "purge_expired\|record_ssn_receipt" backend/core/pii_vault.py'

echo ""

# ── Wave 1 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 1: Contracts, Infrastructure, Budget ━━"

# W1.1 Canonical tables
for table in astra_runs astra_run_steps astra_actions astra_approval_requests astra_run_events astra_artifacts astra_budget_reservations astra_action_receipts astra_outbox astra_shadow_comparisons astra_brain_records astra_brain_acl astra_brain_projection_jobs; do
  check "Table: $table" "grep -rq 'CREATE TABLE.*$table' supabase/ 2>/dev/null || grep -rq 'class ${table//-/_}' backend/ 2>/dev/null"
done

check "Pydantic models (run, step, action, approval, event)" \
  'grep -rq "class.*Run.*BaseModel\|class.*Step.*BaseModel\|class.*Action.*BaseModel\|class.*Approval.*BaseModel\|class.*Event.*BaseModel" backend/ 2>/dev/null'

check "Versioned Supabase migrations dir" \
  'test -d supabase/migrations || test -d migrations'

# W1.2 Temporal
check "temporalio dependency" \
  'grep -rq "temporalio" requirements.txt pyproject.toml 2>/dev/null'

check "Temporal workflow definition" \
  'grep -rq "Workflow\|@workflow.defn\|activity.defn" backend/ 2>/dev/null'

check "Temporal Docker service" \
  'grep -q "temporal" docker-compose.yml'

check "Temporal worker process" \
  'grep -rq "temporalio.worker\|TemporalWorker" backend/ 2>/dev/null'

# W1.3 Budget reservations
check "Reservation service (reserve/commit/release/expire)" \
  'grep -rq "def reserve\|def commit_reservation\|def release_reservation\|def expire_reservation" backend/ 2>/dev/null'

check "Atomic balance check" \
  'grep -rq "balance.*check\|check.*balance\|atomic.*reservation" backend/ 2>/dev/null'

check "Orphan reaper" \
  'grep -rq "orphan.*reap\|reap.*orphan\|expired.*reservation.*release" backend/ 2>/dev/null'

# W1.4 Feature flags
check "ASTRA_CONTROL_PLANE_V2 flag" \
  'grep -rq "ASTRA_CONTROL_PLANE_V2\|control_plane_v2" backend/ 2>/dev/null'

check "ASTRA_TEMPORAL_SHADOW_PERCENT flag" \
  'grep -rq "ASTRA_TEMPORAL_SHADOW_PERCENT\|temporal_shadow_percent" backend/ 2>/dev/null'

check "ASTRA_EVENT_STREAM_V2 flag" \
  'grep -rq "ASTRA_EVENT_STREAM_V2\|event_stream_v2" backend/ 2>/dev/null'

echo ""

# ── Wave 2 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 2: Unified Commands and Ordered Events ━━"

check "POST /runs endpoint" \
  'grep -rq "post.*\"/runs\"\|@router.post.*runs" backend/api/ 2>/dev/null'

check "StartRun application service" \
  'grep -rq "class StartRun\|def start_run\|StartRun" backend/ 2>/dev/null'

check "Every submission surface delegates to StartRun" \
  'grep -rq "start_run\|StartRun" backend/api/routes.py backend/copilot.py backend/missions/ 2>/dev/null'

# Redis Streams
check "Redis Streams (XADD/XREAD)" \
  'grep -rq "xadd\|xread\|XADD\|XREAD\|redis.*stream" backend/ 2>/dev/null'

check "Durable event sequence (DB-assigned)" \
  'grep -rq "next_event_sequence\|event_sequence\|db.*sequence" backend/ 2>/dev/null'

check "Outbox pattern" \
  'grep -rq "outbox\|astra_outbox" backend/ 2>/dev/null'

check "SSE from Supabase replay (Last-Event-ID)" \
  'grep -rq "Last-Event-ID\|last.event.id\|supabase.*replay" backend/ 2>/dev/null'

echo ""

# ── Wave 3 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 3: Temporal Observation Shell ━━"

check "AstraRunWorkflow class" \
  'grep -rq "class AstraRunWorkflow\|AstraRunWorkflow" backend/ 2>/dev/null'

check "Shadow comparator (5% sampling)" \
  'grep -rq "shadow.*compar\|shadow.*percent\|shadow_percent" backend/ 2>/dev/null'

check "Temporal recovery tests" \
  'grep -rq "temporal.*recovery\|test.*worker.*restart\|test.*temporal" tests/ 2>/dev/null'

echo ""

# ── Wave 4 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 4: Durable Workflow Extraction ━━"

check "Planner workflow/activity" \
  'grep -rq "planner.*activity\|planner.*workflow\|PlanningActivity" backend/ 2>/dev/null'

check "External action executor with idempotency" \
  'grep -rq "idempotency_key\|action_executor\|ExternalActionExecutor" backend/ 2>/dev/null'

check "Durable approval waits (Temporal)" \
  'grep -rq "approval.*temporal\|temporal.*approval\|wait_for_approval" backend/ 2>/dev/null'

echo ""

# ── Wave 5 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 5: Gateway, Research, Observability ━━"

check "LiteLLM gateway deployment" \
  'grep -q "litellm" docker-compose.yml 2>/dev/null || grep -rq "litellm" backend/ 2>/dev/null'

check "LiteLLM virtual keys" \
  'grep -rq "virtual_key\|litellm.*key" backend/ 2>/dev/null'

check "OpenTelemetry integration" \
  'grep -rq "from opentelemetry\|import opentelemetry\|otel\|OTEL_" backend/ 2>/dev/null || grep -q "opentelemetry" requirements.txt pyproject.toml 2>/dev/null'

check "Langfuse hooks" \
  'grep -rq "langfuse" backend/ 2>/dev/null'

check "Open Deep Research integration" \
  'grep -rq "open_deep_research\|deep.*research.*v2" backend/ 2>/dev/null'

echo ""

# ── Wave 6 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 6: Company Brain V2 ━━"

check "Company Brain records store" \
  'test -f backend/tools/company_brain.py'

check "Graphiti integration" \
  'grep -rq "graphiti" backend/ 2>/dev/null'

check "FalkorDB deployment" \
  'grep -q "falkordb\|falkor" docker-compose.yml 2>/dev/null || grep -rq "falkordb\|falkor" backend/ 2>/dev/null'

check "Brain ACL table/enforcement" \
  'grep -rq "astra_brain_acl\|brain.*acl\|acl.*brain" backend/ supabase/ 2>/dev/null'

check "Graph RAG (existing partial)" \
  'test -f backend/tools/graph_rag_v2.py'

echo ""

# ── Wave 7 ──────────────────────────────────────────────────────────────────
echo "━━ WAVE 7: Rollout and Legacy Retirement ━━"

check "Strangler rollout / engine assignment" \
  'grep -rq "engine.*assignment\|strangler\|legacy.*engine\|temporal.*engine" backend/ 2>/dev/null'

check "Dual writes" \
  'grep -rq "dual.*write\|shadow.*write\|write.*legacy\|write.*temporal" backend/ 2>/dev/null'

check "Rollback procedures" \
  'grep -rq "rollback\|roll.*back" backend/ docs/ 2>/dev/null'

echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo "=============================================="
TOTAL=$((TOTAL_PASS + TOTAL_PARTIAL + TOTAL_MISS))
echo " RESULTS: $TOTAL_PASS pass / $TOTAL_PARTIAL partial / $TOTAL_MISS missing  ($TOTAL checks)"
if [ "$TOTAL" -gt 0 ]; then
  PCT=$(( (TOTAL_PASS * 100) / TOTAL ))
  echo " COMPLETION: ~${PCT}%"
fi
echo "=============================================="

# ── Git branch status ───────────────────────────────────────────────────────
echo ""
echo "━━ Git Branch Status ━━"
echo "Branches with control-plane/wave/temporal in name:"
git branch -a 2>/dev/null | grep -i 'control\|wave\|temporal\|durable\|migration\|start-run' | head -20 || echo "  (none found)"
echo ""
echo "Recent plan-related commits (last 10):"
git log --oneline -10 --grep='temporal\|durable\|astra_runs\|wave\|migration\|control.plane' -i 2>/dev/null || echo "  (none found)"
