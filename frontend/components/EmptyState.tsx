"use client";

import type { ReactNode } from "react";

export default function EmptyState({
  icon,
  title,
  hint,
  cta,
}: {
  icon?: ReactNode;
  title: string;
  hint: string;
  cta?: ReactNode;
}) {
  return (
    <div
      style={{
        padding: "40px 24px",
        border: "1px dashed var(--border)",
        borderRadius: 14,
        background: "var(--bg-surface)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        gap: 12,
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          border: "1px solid var(--border)",
          background: "var(--bg-sunken)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--accent)",
          fontSize: 20,
        }}
      >
        {icon || "◈"}
      </div>
      <div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{title}</div>
        <div style={{ fontSize: 13, color: "var(--text-3)", marginTop: 4, lineHeight: 1.6 }}>{hint}</div>
      </div>
      {cta}
    </div>
  );
}
