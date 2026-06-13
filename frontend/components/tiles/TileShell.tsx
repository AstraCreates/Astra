"use client";
import { useState } from "react";
import type { DashboardElement } from "@/lib/dashboard-api";

const SIZE_COLS: Record<string, number> = {
  small: 3,
  medium: 6,
  big: 6,
  xl: 12,
};
const SIZE_ROWS: Record<string, number> = {
  small: 1,
  medium: 1,
  big: 2,
  xl: 2,
};

interface Props {
  element: DashboardElement;
  children: React.ReactNode;
  onRemove?: (id: string) => void;
  isRefreshing?: boolean;
}

export default function TileShell({ element, children, onRemove, isRefreshing }: Props) {
  const [hovered, setHovered] = useState(false);
  const cols = SIZE_COLS[element.size] ?? 6;
  const rows = SIZE_ROWS[element.size] ?? 1;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        gridColumn: `span ${cols}`,
        gridRow: `span ${rows}`,
        border: "1px solid var(--bd)",
        background: "var(--surface)",
        borderRadius: 10,
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "relative",
        transition: "box-shadow 0.15s",
        ...(hovered ? { boxShadow: "0 2px 10px rgba(0,0,0,0.10)" } : {}),
      }}
    >
      {/* Title bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px 0",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--fm)",
            letterSpacing: "0.03em",
            textTransform: "uppercase",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {element.title}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {isRefreshing && (
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--blue)",
                opacity: 0.7,
                animation: "dc-pulse 1.2s ease-in-out infinite",
              }}
            />
          )}
          {onRemove && hovered && (
            <button
              onClick={() => onRemove(element.id)}
              style={{
                width: 18,
                height: 18,
                border: "none",
                borderRadius: 4,
                background: "var(--bd)",
                color: "var(--fm)",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                lineHeight: 1,
                padding: 0,
              }}
              title="Remove tile"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, padding: "8px 14px 12px", minHeight: 0 }}>
        {children}
      </div>

      {/* Agent badge */}
      {element.agent && hovered && (
        <div
          style={{
            position: "absolute",
            bottom: 6,
            right: 10,
            fontSize: 9,
            color: "var(--fm)",
            opacity: 0.55,
          }}
        >
          {element.agent}
        </div>
      )}
    </div>
  );
}
