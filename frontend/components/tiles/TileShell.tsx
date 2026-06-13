"use client";
import { useEffect, useState } from "react";
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
  /** Position in the canvas — drives the staggered "power-on" build order. */
  index?: number;
  /** Skip the build animation (e.g. tiles that arrive after the initial boot). */
  instant?: boolean;
}

// Build phases: 0 = wireframe shell, 1 = skeleton fill, 2 = live content.
export default function TileShell({ element, children, onRemove, isRefreshing, index = 0, instant = false }: Props) {
  const [hovered, setHovered] = useState(false);
  const [phase, setPhase] = useState<0 | 1 | 2>(instant ? 2 : 0);
  const cols = SIZE_COLS[element.size] ?? 6;
  const rows = SIZE_ROWS[element.size] ?? 1;

  useEffect(() => {
    if (instant) return;
    const start = Math.min(index, 12) * 90; // stagger, capped so late tiles don't lag forever
    const t1 = setTimeout(() => setPhase(1), start);
    const t2 = setTimeout(() => setPhase(2), start + 340);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [index, instant]);

  const building = phase < 2;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        gridColumn: `span ${cols}`,
        gridRow: `span ${rows}`,
        border: `1px solid ${building ? "var(--bb)" : "var(--bd)"}`,
        background: "var(--surface)",
        borderRadius: 10,
        boxShadow: phase === 0
          ? "0 0 0 1px var(--bb), 0 0 18px rgba(0,46,255,0.10)"
          : hovered ? "0 2px 10px rgba(0,0,0,0.10)" : "0 1px 3px rgba(0,0,0,0.06)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "relative",
        opacity: phase === 0 ? 0.55 : 1,
        transform: phase === 0 ? "scale(0.965)" : "scale(1)",
        transition: "box-shadow 0.2s, border-color 0.3s, opacity 0.3s, transform 0.35s cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      <style>{`
        @keyframes ts-skel { 0% { background-position: -180% 0; } 100% { background-position: 180% 0; } }
        @keyframes ts-sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(220%); } }
        @keyframes ts-content-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .ts-skel-bar {
          border-radius: 5px;
          background: linear-gradient(90deg, var(--s2) 25%, var(--bd) 37%, var(--s2) 63%);
          background-size: 220% 100%;
          animation: ts-skel 1.1s linear infinite;
        }
      `}</style>

      {/* power-on scanline sweep while building */}
      {building && (
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 4 }}>
          <div style={{
            position: "absolute", top: 0, bottom: 0, width: "45%",
            background: "linear-gradient(90deg, transparent, rgba(0,46,255,0.10), transparent)",
            animation: "ts-sweep 0.9s ease-in-out infinite",
          }} />
        </div>
      )}

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
        {phase === 0 ? (
          <div className="ts-skel-bar" style={{ height: 8, width: "46%" }} />
        ) : (
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
              animation: phase === 1 ? "none" : undefined,
            }}
          >
            {element.title}
          </div>
        )}
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
          {onRemove && hovered && !building && (
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
      <div style={{ flex: 1, padding: "8px 14px 12px", minHeight: 0, position: "relative" }}>
        {phase < 2 ? (
          // Skeleton bars approximating content layout while the tile "assembles"
          <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 4 }}>
            <div className="ts-skel-bar" style={{ height: 22, width: "62%" }} />
            <div className="ts-skel-bar" style={{ height: 8, width: "90%" }} />
            <div className="ts-skel-bar" style={{ height: 8, width: "78%" }} />
            {(element.size === "big" || element.size === "xl") && (
              <div className="ts-skel-bar" style={{ height: 8, width: "84%" }} />
            )}
          </div>
        ) : (
          <div style={{ animation: "ts-content-in 0.4s cubic-bezier(0.22,1,0.36,1) both" }}>
            {children}
          </div>
        )}
      </div>

      {/* Agent badge */}
      {element.agent && hovered && !building && (
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
