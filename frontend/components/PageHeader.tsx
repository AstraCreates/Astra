"use client";

import type { ReactNode } from "react";

interface Stat { label: string; value: string; }
interface BadgeProp { label: string; color: "green" | "blue" | "amber" | "red"; }

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  badge?: BadgeProp;
  stats?: Stat[];
  actions?: ReactNode;
}

const BADGE_STYLE: Record<string, { border: string; bg: string; color: string }> = {
  green: { border: "color-mix(in srgb, var(--green) 30%, transparent)", bg: "color-mix(in srgb, var(--green) 12%, transparent)", color: "var(--green)" },
  blue:  { border: "color-mix(in srgb, var(--accent) 30%, transparent)", bg: "color-mix(in srgb, var(--accent) 12%, transparent)", color: "var(--accent)" },
  amber: { border: "color-mix(in srgb, var(--amber) 30%, transparent)", bg: "color-mix(in srgb, var(--amber) 12%, transparent)", color: "var(--amber)" },
  red:   { border: "color-mix(in srgb, var(--red) 30%, transparent)", bg: "color-mix(in srgb, var(--red) 12%, transparent)", color: "var(--red)" },
};

export default function PageHeader({ title, subtitle, badge, stats, actions }: PageHeaderProps) {
  const bs = badge ? BADGE_STYLE[badge.color] : null;

  return (
    <div style={{
      background: "var(--bg-surface)",
      borderBottom: "1px solid var(--border)",
      padding: "22px 24px 18px",
      flexShrink: 0,
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 16,
      flexWrap: "wrap",
      position: "sticky",
      top: 0,
      zIndex: 10,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Title row */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: stats?.length ? 10 : subtitle ? 5 : 0, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--text)", letterSpacing: "-0.02em", margin: 0, lineHeight: 1.15 }}>
            {title}
          </h1>
          {badge && bs && (
            <span style={{
              padding: "2px 9px", fontSize: 9, fontWeight: 700, letterSpacing: ".07em",
              textTransform: "uppercase", fontFamily: "var(--font-code)",
              border: `1px solid ${bs.border}`,
              background: bs.bg,
              color: bs.color,
            }}>
              {badge.label}
            </span>
          )}
        </div>

        {/* Subtitle */}
        {subtitle && !stats?.length && (
          <div style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.5, maxWidth: 520 }}>
            {subtitle}
          </div>
        )}

        {/* Stats row */}
        {stats && stats.length > 0 && (
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {stats.map(s => (
              <div key={s.label} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text)", fontFamily: "var(--font-code)", lineHeight: 1 }}>
                  {s.value}
                </span>
                <span style={{ fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".08em" }}>
                  {s.label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      {actions && (
        <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "flex-start" }}>
          {actions}
        </div>
      )}
    </div>
  );
}

// ── Shared button styles for PageHeader actions ────────────────────────────

export function HeaderPrimaryBtn({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} className="m-tap" style={{
      padding: "8px 18px", fontSize: 12, fontWeight: 600,
      color: "white", background: "var(--accent)", border: "none",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
    }}>
      {label}
    </button>
  );
}

export function HeaderSecondaryBtn({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} className="m-tap" style={{
      padding: "8px 14px", fontSize: 12,
      color: "var(--text-2)",
      background: "var(--bg-sunken)",
      border: "1px solid var(--border)",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
    }}>
      {label}
    </button>
  );
}
