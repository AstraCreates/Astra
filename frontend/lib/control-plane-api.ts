import { apiFetch } from "@/lib/api";
import type { RunStatus } from "@/lib/run-status";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Field-for-field mirrors of backend/control_plane/models.py Pydantic models,
// as serialized by `.model_dump(mode="json")` (backend/control_plane/projection.py).
// Optional[...] fields become `T | null` since pydantic emits `null`, not
// `undefined`, for unset optional fields in JSON mode.

// StepStatus is a type alias of RunStatus on the backend (`StepStatus = RunStatus`).
export type StepStatus = RunStatus;
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "skipped" | "consumed";
export type ArtifactVerificationStatus = "unverified" | "passed" | "weak" | "missing";
export type ReservationStatus = "reserved" | "committed" | "released" | "expired";

export type Run = {
  id: string;
  owner_id: string;
  org_id: string;
  company_id: string | null;
  workspace_id: string | null;
  chapter_id: string | null;
  parent_run_id: string | null;
  goal: string;
  stack_id: string | null;
  engine: string;
  workflow_version: string;
  status: RunStatus;
  next_event_sequence: number;
  budget_limit_usd: number | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancellation_requested_at: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
};

export type RunStep = {
  id: string;
  run_id: string;
  step_key: string;
  parent_step_id: string | null;
  kind: string;
  agent: string | null;
  phase: string | null;
  status: StepStatus;
  attempt_number: number;
  max_attempts: number;
  input_ref: string | null;
  output_ref: string | null;
  idempotency_key: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  completed_at: string | null;
  error: string | null;
};

export type ApprovalRequest = {
  id: string;
  run_id: string;
  step_id: string | null;
  action_id: string | null;
  gate_key: string;
  action_digest: string;
  required_role: string;
  policy_version: string;
  status: ApprovalStatus;
  expires_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
  decided_at: string | null;
  consumed_at: string | null;
  revision: number;
  created_at: string | null;
};

export type Artifact = {
  id: string;
  run_id: string;
  step_id: string | null;
  key: string;
  uri: string | null;
  content_hash: string | null;
  metadata: Record<string, unknown>;
  verification_status: ArtifactVerificationStatus;
  created_at: string | null;
};

export type BudgetReservation = {
  id: string;
  run_id: string;
  step_id: string | null;
  estimated_max_usd: number;
  actual_usd: number | null;
  status: ReservationStatus;
  expires_at: string;
  provider_request_id: string | null;
  reconciled_at: string | null;
  created_at: string | null;
};

export type RunSnapshot = {
  run: Run;
  steps: RunStep[];
  approvals: ApprovalRequest[];
  artifacts: Artifact[];
  budget: BudgetReservation[];
  engine: string;
};

// Mirrors backend/control_plane/models.py::RunEvent.
export type RunEvent = {
  run_id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string | null;
  published_at: string | null;
};

// Mirrors the literal dict returned by GET /runs/{run_id}/trace in
// backend/api/routes.py::get_run_trace — there is no OTel/Temporal UI URL
// wired up yet, just the raw identifiers pulled from session meta.
export type RunTrace = {
  run_id: string;
  engine: string;
  workflow_id: string;
  task_queue: string;
  trace_id: string;
  otel: { trace_id: string; span_id: string };
};

export async function getRunSnapshot(runId: string): Promise<RunSnapshot> {
  const res = await apiFetch(`${BASE}/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRunEvents(runId: string, afterSequence = 0): Promise<RunEvent[]> {
  const res = await apiFetch(
    `${BASE}/runs/${encodeURIComponent(runId)}/events?after=${encodeURIComponent(String(afterSequence))}`
  );
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return (data.events as RunEvent[]) ?? [];
}

export async function getRunTrace(runId: string): Promise<RunTrace> {
  const res = await apiFetch(`${BASE}/runs/${encodeURIComponent(runId)}/trace`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function decideApproval(
  runId: string,
  approvalId: string,
  decision: "approved" | "rejected" | "skipped",
  note?: string,
  expectedActionDigest?: string,
): Promise<void> {
  const res = await apiFetch(
    `${BASE}/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note, expected_action_digest: expectedActionDigest }),
    }
  );
  if (!res.ok) throw new Error(await res.text());
}
