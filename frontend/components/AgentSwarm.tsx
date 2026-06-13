"use client";

/* AgentSwarm — live founding-team constellation.
   Core = company. Each agent = orbital node.
   running → bright, ping ring, data packet flowing to core
   done    → solid mint, settled
   error   → red
   waiting → hollow dim ring

   Uses SVG-native <animateMotion> (not CSS offset-path) and SVG <animate>
   for ping rings — both have near-universal support and work on SVG elements. */

import { useMemo, useState } from "react";

export type SwarmAgent = {
  key: string;
  label: string;
  status: string;
  currentTool?: string | null;
};

interface Props {
  agents: SwarmAgent[];
  coreLabel: string;
  coreSub?: string;
  /** Ignored — kept for backwards compat; height is now auto from aspect ratio. */
  height?: number;
}

// Wide-aspect viewBox so the SVG fills container width without letterboxing.
// paddingBottom = VB_H/VB_W as a % makes container auto-height.
const VB_W  = 700;
const VB_H  = 440;  // extra vertical room so bottom-ring labels don't clip
const CX    = VB_W / 2;  // 350
const CY    = VB_H / 2;  // 220
const R_IN  = 110;
const R_OUT = 158;

function short(label: string, max = 13): string {
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

type Placed = SwarmAgent & { x: number; y: number; lx: number; ly: number; anchor: "start" | "middle" | "end"; ring: number; idx: number };

function placeAgents(agents: SwarmAgent[]): Placed[] {
  const n = agents.length;
  if (!n) return [];
  const twoRings = n > 7;
  const innerCount = twoRings ? Math.ceil(n / 2) : n;
  return agents.map((a, i) => {
    const ring = i < innerCount ? 0 : 1;
    const inRing = ring === 0 ? innerCount : n - innerCount;
    const iInRing = ring === 0 ? i : i - innerCount;
    const orbitR = ring === 0 ? R_IN : R_OUT;
    // offset outer ring by half-step so nodes don't stack directly behind inner
    const phase = ring === 1 ? Math.PI / inRing : 0;
    const ang = (iInRing / inRing) * Math.PI * 2 - Math.PI / 2 + phase;
    const x = CX + Math.cos(ang) * orbitR;
    const y = CY + Math.sin(ang) * orbitR;
    // label sits 26px further out along same radial
    const labelR = orbitR + 30;
    const lx = CX + Math.cos(ang) * labelR;
    const ly = CY + Math.sin(ang) * labelR;
    // text-anchor by x position
    const anchor = (lx < CX - 12 ? "end" : lx > CX + 12 ? "start" : "middle") as "end" | "start" | "middle";
    return { ...a, x, y, lx, ly, anchor, ring, idx: i };
  });
}

export default function AgentSwarm({ agents, coreLabel, coreSub }: Props) {
  const [hover, setHover] = useState<string | null>(null);
  const placed = useMemo(() => placeAgents(agents), [agents]);
  const runCount  = agents.filter(a => a.status === "running").length;
  const doneCount = agents.filter(a => a.status === "done").length;

  const uid = "sw";

  return (
    // Padding-bottom trick: height = VB_H/VB_W of actual width → no letterboxing.
    <div style={{
      position: "relative",
      width: "100%",
      paddingBottom: `${(VB_H / VB_W) * 100}%`,
      background: "var(--s2)",
      borderRadius: 12,
      border: "1px solid var(--bd)",
      overflow: "hidden",
    }}>
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} width="100%" height="100%"
        style={{ position: "absolute", inset: 0, display: "block" }}>
        <defs>
          {/* subtle glow filter — applied only to active nodes, not everything */}
          <filter id={`${uid}-glow`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="1.8" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* beam paths for animateMotion — defined once, referenced by mpath */}
          {placed.filter(a => a.status === "running").map(a => (
            <path key={`path-${a.key}`} id={`${uid}-p-${a.key}`}
              d={`M ${a.x.toFixed(1)} ${a.y.toFixed(1)} L ${CX} ${CY}`}
            />
          ))}
        </defs>

        {/* static orbital tracks — no rotation, just clean geometry */}
        {placed.some(a => a.ring === 0) && (
          <circle cx={CX} cy={CY} r={R_IN}
            fill="none" stroke="var(--bd)" strokeWidth={0.75}
          />
        )}
        {placed.some(a => a.ring === 1) && (
          <circle cx={CX} cy={CY} r={R_OUT}
            fill="none" stroke="var(--bd)" strokeWidth={0.75}
          />
        )}

        {/* data beams — thin, static, low opacity lines for all active connections */}
        {placed.map(a => {
          if (a.status === "waiting") return null;
          const opacity = a.status === "running" ? 0.22 : 0.10;
          const stroke  = a.status === "error" ? "var(--red)" : "var(--blue)";
          return (
            <line key={`beam-${a.key}`}
              x1={a.x} y1={a.y} x2={CX} y2={CY}
              stroke={stroke} strokeWidth={0.8} strokeOpacity={opacity}
            />
          );
        })}

        {/* data packets — SVG-native animateMotion, staggered */}
        {placed.filter(a => a.status === "running").map((a, ri) => (
          <circle key={`pkt-${a.key}`} r={2.2} fill="var(--mint)">
            <animate attributeName="opacity"
              values="0;0;1;1;0" keyTimes="0;0.05;0.12;0.88;1"
              dur="1.8s" repeatCount="indefinite"
              begin={`${ri * 0.32}s`}
            />
            <animateMotion
              dur="1.8s" repeatCount="indefinite"
              begin={`${ri * 0.32}s`}
            >
              <mpath href={`#${uid}-p-${a.key}`} />
            </animateMotion>
          </circle>
        ))}

        {/* core — expanding breath ring + solid disc */}
        <circle cx={CX} cy={CY} r={24} fill="none" stroke="var(--blue)" strokeWidth={1} strokeOpacity={0.25}>
          <animate attributeName="r" values="24;38" dur="3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.45;0" dur="3s" repeatCount="indefinite" />
        </circle>
        <circle cx={CX} cy={CY} r={24} fill="var(--blue)" />

        {/* agent nodes */}
        {placed.map(a => {
          const isRun  = a.status === "running";
          const isDone = a.status === "done";
          const isErr  = a.status === "error";
          const isWait = !isRun && !isDone && !isErr;

          const nodeFill   = isWait ? "var(--s2)" : isRun ? "var(--blue)" : isDone ? "var(--mint)" : "var(--red)";
          const nodeStroke = isWait ? "var(--fm)" : isRun ? "var(--blue)" : isDone ? "var(--mint)" : "var(--red)";
          const nodeR      = isRun ? 8 : 7;
          const labelColor = isWait ? "var(--fm)" : isRun ? "var(--blue)" : isDone ? "var(--mint)" : "var(--red)";
          const isHovered  = hover === a.key;

          return (
            <g key={a.key}
              onMouseEnter={() => setHover(a.key)}
              onMouseLeave={() => setHover(h => h === a.key ? null : h)}
              style={{ cursor: "default" }}
            >
              {/* ping ring — running only, SVG animate */}
              {isRun && (
                <circle cx={a.x} cy={a.y} r={nodeR} fill="none" stroke="var(--blue)" strokeWidth={1.2}>
                  <animate attributeName="r" values={`${nodeR};${nodeR + 10}`} dur="1.6s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.6;0" dur="1.6s" repeatCount="indefinite" />
                </circle>
              )}

              {/* node disc */}
              <circle
                cx={a.x} cy={a.y} r={nodeR}
                fill={nodeFill}
                stroke={nodeStroke}
                strokeWidth={isWait ? 1.2 : 0}
                filter={isRun ? `url(#${uid}-glow)` : undefined}
                opacity={isWait ? 0.6 : 1}
              />

              {/* hover enlarge ring */}
              {isHovered && (
                <circle cx={a.x} cy={a.y} r={nodeR + 4}
                  fill="none" stroke={nodeStroke} strokeWidth={1} strokeOpacity={0.5}
                />
              )}

              {/* permanent label — short, radially placed */}
              <text
                x={a.lx} y={a.ly}
                textAnchor={a.anchor}
                dominantBaseline="middle"
                fontSize={isHovered ? 9 : 8.5}
                fill={isHovered ? "var(--fg)" : labelColor}
                fontFamily="var(--font-geist-sans), system-ui, sans-serif"
                fontWeight={isRun || isHovered ? 600 : 400}
                opacity={isWait ? 0.55 : 0.9}
                style={{ userSelect: "none", transition: "font-size .1s" }}
              >
                {short(a.label)}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Core label — HTML for subpixel-crisp text, centered over SVG */}
      <div style={{
        position: "absolute",
        top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        textAlign: "center",
        pointerEvents: "none",
        maxWidth: 100,
        lineHeight: 1.25,
      }}>
        <div style={{
          fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "-0.02em",
          color: "#fff",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: 92,
          textShadow: "0 1px 4px rgba(0,0,0,.5)",
        }}>
          {coreLabel.length > 10 ? coreLabel.slice(0, 9) + "…" : coreLabel}
        </div>
        {coreSub && (
          <div style={{
            fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
            fontSize: 8,
            color: "rgba(255,255,255,.72)",
            marginTop: 2,
            textTransform: "uppercase",
            letterSpacing: ".08em",
            textShadow: "0 1px 3px rgba(0,0,0,.4)",
          }}>
            {coreSub}
          </div>
        )}
      </div>

      {/* Status line — bottom-left */}
      <div style={{
        position: "absolute", bottom: 10, left: 13,
        display: "flex", alignItems: "center", gap: 10,
        fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
        fontSize: 9.5, color: "var(--fm)",
      }}>
        {runCount > 0 && (
          <span style={{ color: "var(--blue)", fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{
              width: 5, height: 5, borderRadius: "50%",
              background: "var(--blue)", display: "inline-block",
              animation: "sw-blink 1.2s ease-in-out infinite",
            }} />
            {runCount} working
          </span>
        )}
        {doneCount > 0 && (
          <span style={{ color: "var(--mint)", fontWeight: 500 }}>
            {doneCount} done
          </span>
        )}
        <span>{agents.length} agents</span>
      </div>

      {/* hover tooltip — shown above the status line */}
      {hover && (() => {
        const a = placed.find(p => p.key === hover);
        if (!a) return null;
        const leftPct = (a.x / VB_W) * 100;
        const topPct  = (a.y / VB_H) * 100;
        return (
          <div style={{
            position: "absolute",
            left: `${leftPct}%`, top: `${topPct}%`,
            transform: "translate(-50%, calc(-100% - 14px))",
            background: "var(--fg)", color: "var(--bg)",
            padding: "5px 10px", borderRadius: 6,
            fontSize: 10, whiteSpace: "nowrap",
            pointerEvents: "none", zIndex: 10,
            boxShadow: "0 4px 16px rgba(0,0,0,.2)",
            fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
          }}>
            <div style={{ fontWeight: 700 }}>{a.label}</div>
            <div style={{ opacity: 0.7, fontSize: 9, marginTop: 2 }}>
              {a.status === "running"
                ? (a.currentTool ? `↳ ${a.currentTool}` : "working…")
                : a.status === "done"  ? "completed"
                : a.status === "error" ? "error"
                : "queued"}
            </div>
          </div>
        );
      })()}

      <style>{`@keyframes sw-blink { 0%,100%{opacity:.4} 50%{opacity:1} }`}</style>
    </div>
  );
}
