// Pure status helpers for the Wave 5.4 control-plane UI. No React here —
// keep this importable from both server and client code.

// Verbatim mirror of backend/control_plane/models.py::RunStatus (a Literal).
// Keep in lockstep with that file; StepStatus is a type alias of the same
// Literal on the backend, so RunStep.status also uses this type.
export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "cancelling"
  | "cancelled"
  | "succeeded"
  | "failed";

const LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_approval: "Awaiting Approval",
  cancelling: "Cancelling",
  cancelled: "Cancelled",
  succeeded: "Succeeded",
  failed: "Failed",
};

export function runStatusLabel(status: RunStatus): string {
  return LABELS[status] ?? status;
}

const TERMINAL: ReadonlySet<RunStatus> = new Set(["cancelled", "succeeded", "failed"]);

export function runStatusIsTerminal(status: RunStatus): boolean {
  return TERMINAL.has(status);
}

/**
 * "Degraded" is not a raw backend RunStatus — it's a UI-derived state layered
 * on top of "running": the run hasn't failed or stopped, but at least one
 * step already recorded a non-empty `error`, so the operator should look
 * closer even though the run is technically still in progress.
 */
export function runStatusIsDegraded(status: RunStatus, hasErrors: boolean): boolean {
  return status === "running" && hasErrors;
}
