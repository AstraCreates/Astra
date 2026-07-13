import { runStatusLabel, type RunStatus } from "@/lib/run-status";

// Reuses the existing `.pill` badge system (see app/astra-redesign.css and the
// StatusPill/statusPill helpers in DashboardView.tsx / SessionView.tsx) rather
// than introducing a new styling approach. Only blue/green/amber/red variants
// exist, so queued/cancelling/awaiting_approval/degraded are told apart by
// icon + label, not by inventing new colors.
const VARIANTS: Record<RunStatus, { cls: string; icon: string }> = {
  queued: { cls: "", icon: "○" },
  running: { cls: "blue", icon: "●" },
  awaiting_approval: { cls: "amber", icon: "⏸" },
  cancelling: { cls: "amber", icon: "◐" },
  cancelled: { cls: "red", icon: "■" },
  succeeded: { cls: "green", icon: "✓" },
  failed: { cls: "red", icon: "✗" },
};

export default function RunStatusBadge({
  status,
  degraded = false,
}: {
  status: RunStatus;
  degraded?: boolean;
}) {
  if (degraded) {
    return (
      <span className="pill amber" title="Running, but at least one step reported an error">
        ⚠ Degraded
      </span>
    );
  }

  const variant = VARIANTS[status] ?? { cls: "", icon: "" };
  return (
    <span className={`pill ${variant.cls}`.trim()}>
      {variant.icon ? `${variant.icon} ` : ""}
      {runStatusLabel(status)}
    </span>
  );
}
