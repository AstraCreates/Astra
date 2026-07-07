"use client";

type StatusTone = "running" | "done" | "error" | "stalled" | "awaiting" | "active" | "paused" | "draft" | "neutral";

const TONE_META: Record<StatusTone, { label: string; fg: string; bg: string; border: string }> = {
  running: { label: "Running", fg: "var(--accent)", bg: "color-mix(in srgb, var(--accent) 12%, transparent)", border: "color-mix(in srgb, var(--accent) 28%, transparent)" },
  done: { label: "Done", fg: "var(--green)", bg: "color-mix(in srgb, var(--green) 12%, transparent)", border: "color-mix(in srgb, var(--green) 28%, transparent)" },
  error: { label: "Error", fg: "var(--red)", bg: "color-mix(in srgb, var(--red) 12%, transparent)", border: "color-mix(in srgb, var(--red) 28%, transparent)" },
  stalled: { label: "Needs attention", fg: "var(--amber)", bg: "color-mix(in srgb, var(--amber) 12%, transparent)", border: "color-mix(in srgb, var(--amber) 28%, transparent)" },
  awaiting: { label: "Approve", fg: "var(--amber)", bg: "color-mix(in srgb, var(--amber) 12%, transparent)", border: "color-mix(in srgb, var(--amber) 28%, transparent)" },
  active: { label: "Active", fg: "var(--accent)", bg: "color-mix(in srgb, var(--accent) 12%, transparent)", border: "color-mix(in srgb, var(--accent) 28%, transparent)" },
  paused: { label: "Paused", fg: "var(--amber)", bg: "color-mix(in srgb, var(--amber) 12%, transparent)", border: "color-mix(in srgb, var(--amber) 28%, transparent)" },
  draft: { label: "Draft", fg: "var(--text-3)", bg: "var(--bg-sunken)", border: "var(--border)" },
  neutral: { label: "Status", fg: "var(--text-3)", bg: "var(--bg-sunken)", border: "var(--border)" },
};

export default function StatusChip({
  tone,
  label,
}: {
  tone: StatusTone;
  label?: string;
}) {
  const meta = TONE_META[tone] ?? TONE_META.neutral;
  return (
    <span
      style={{
        padding: "3px 9px",
        borderRadius: 999,
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: ".04em",
        textTransform: "uppercase",
        color: meta.fg,
        background: meta.bg,
        border: `1px solid ${meta.border}`,
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {label || meta.label}
    </span>
  );
}
