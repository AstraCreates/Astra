"use client";

import { useEffect, useRef, useState, useMemo } from "react";

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
}

const VBW = 500, VBH = 500;
const CX = VBW / 2, CY = VBH / 2;
const SUN_R = 26;
const PLANET_R = 7;
const MOON_R = 3;
const MOON_ORBIT_R = 14;

// Max radius: CY(250) - label(20) - margin(18) = 212
const ORBIT_R = [62, 85, 107, 127, 147, 164, 180, 195];
const ORBIT_T = [12, 17, 22, 28, 34, 41, 48, 56];
const MOON_T_BASE = 3.2;

function clip(s: string, n = 14) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

type Group = { dept: string; planet: SwarmAgent; moons: SwarmAgent[] };
function groupByDept(agents: SwarmAgent[]): Group[] {
  const buckets = new Map<string, SwarmAgent[]>();
  for (const a of agents) {
    const dept = a.key.includes("_") ? a.key.split("_")[0] : a.key;
    if (!buckets.has(dept)) buckets.set(dept, []);
    buckets.get(dept)!.push(a);
  }
  return Array.from(buckets.entries()).map(([dept, members]) => {
    const exact  = members.find(m => m.key === dept);
    const others = members.filter(m => m.key !== dept);
    const planet = exact ?? others[0];
    const moons  = exact ? others : others.slice(1);
    return { dept, planet, moons };
  });
}

function nodeColor(status: string) {
  if (status === "running") return "var(--blue)";
  if (status === "done")    return "var(--mint, #34d399)";
  if (status === "error")   return "var(--red, #ef4444)";
  return "var(--fm)";
}

export default function AgentSwarm({ agents, coreLabel, coreSub }: Props) {
  const pAngles = useRef<Record<string, number>>({});
  const mAngles = useRef<Record<string, number[]>>({});
  const lastTs  = useRef(0);
  const rafId   = useRef<number>(0);

  const [frame, setFrame] = useState(0);

  const active = useMemo(
    () => agents.filter(a => a.status === "running" || a.status === "done" || a.status === "error"),
    [agents],
  );
  const groups = useMemo(() => groupByDept(active), [active]);

  useEffect(() => {
    groups.forEach(({ dept, moons }, i) => {
      if (!(dept in pAngles.current)) {
        pAngles.current[dept] =
          (i / Math.max(groups.length, 1)) * Math.PI * 2 - Math.PI / 2;
      }
      if (!(dept in mAngles.current)) {
        mAngles.current[dept] = moons.map((_, si) =>
          (si / Math.max(moons.length, 1)) * Math.PI * 2,
        );
      }
    });
  }, [groups]);

  useEffect(() => {
    if (!groups.length) return;
    const tick = (ts: number) => {
      const dt = lastTs.current ? Math.min((ts - lastTs.current) / 1000, 0.05) : 0;
      lastTs.current = ts;

      groups.forEach(({ dept, moons }, i) => {
        const T = ORBIT_T[Math.min(i, ORBIT_T.length - 1)];
        pAngles.current[dept] = (pAngles.current[dept] ?? 0) + (2 * Math.PI / T) * dt;

        const ma = mAngles.current[dept] ?? [];
        moons.forEach((_, si) => {
          const mT = MOON_T_BASE + si * 1.4;
          ma[si] = (ma[si] ?? 0) + (2 * Math.PI / mT) * dt;
        });
        mAngles.current[dept] = ma;
      });

      setFrame(f => f + 1);
      rafId.current = requestAnimationFrame(tick);
    };
    rafId.current = requestAnimationFrame(tick);
    return () => { if (rafId.current) cancelAnimationFrame(rafId.current); };
  }, [groups]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const positions = useMemo(() => groups.map(({ dept, planet, moons }, i) => {
    const angle  = pAngles.current[dept] ?? 0;
    const orbitR = ORBIT_R[Math.min(i, ORBIT_R.length - 1)];
    const px = CX + Math.cos(angle) * orbitR;
    const py = CY + Math.sin(angle) * orbitR;

    const labelR = orbitR + PLANET_R + 13;
    const lx     = CX + Math.cos(angle) * labelR;
    const ly     = CY + Math.sin(angle) * labelR;
    const anchor: "end" | "start" | "middle" = lx < CX - 8 ? "end" : lx > CX + 8 ? "start" : "middle";

    const moonPos = (mAngles.current[dept] ?? []).map((ma, si) => {
      const m = moons[si]; if (!m) return null;
      return {
        key: m.key, status: m.status,
        x: px + Math.cos(ma) * MOON_ORBIT_R,
        y: py + Math.sin(ma) * MOON_ORBIT_R,
      };
    }).filter(Boolean) as { key: string; status: string; x: number; y: number }[];

    return { dept, planet, moons: moonPos, px, py, lx, ly, anchor, orbitR };
  }), [groups, frame]); // frame forces recompute every RAF tick

  const runCount  = groups.filter(g => g.planet.status === "running").length;
  const doneCount = groups.filter(g => g.planet.status === "done").length;

  return (
    <div style={{
      position: "relative", width: "100%", maxWidth: 440,
      aspectRatio: "1 / 1",
      background: "var(--s2, #f8f9fa)", borderRadius: 12,
      border: "1px solid var(--bd)", overflow: "hidden",
    }}>
      <svg
        viewBox={`0 0 ${VBW} ${VBH}`} width="100%" height="100%"
        style={{ position: "absolute", inset: 0, display: "block" }}
      >
        <defs>
          <filter id="sw-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="2.5" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Orbit tracks */}
        {ORBIT_R.slice(0, groups.length).map((r, i) => (
          <circle key={`track-${i}`} cx={CX} cy={CY} r={r}
            fill="none" stroke="var(--bd)" strokeWidth={0.7} strokeOpacity={0.5} />
        ))}

        {/* Moon orbit tracks — follow planet each frame */}
        {positions.filter(p => p.moons.length > 0).map(p => (
          <circle key={`mtrack-${p.dept}`}
            cx={p.px} cy={p.py} r={MOON_ORBIT_R}
            fill="none" stroke="var(--bd)" strokeWidth={0.5} strokeOpacity={0.4} />
        ))}

        {/* Planets + moons */}
        {positions.map(p => {
          const c         = nodeColor(p.planet.status);
          const isRunning = p.planet.status === "running";
          const isDone    = p.planet.status === "done";

          return (
            <g key={p.dept}>
              {/* Pulse ring — running planets only */}
              {isRunning && (
                <circle cx={p.px} cy={p.py} r={PLANET_R + 5}
                  fill="none" stroke={c} strokeWidth={1.5}>
                  <animate attributeName="r"
                    values={`${PLANET_R + 5};${PLANET_R + 16}`}
                    dur="2.2s" repeatCount="indefinite" />
                  <animate attributeName="opacity"
                    values="0.6;0" dur="2.2s" repeatCount="indefinite" />
                </circle>
              )}

              {/* Planet — spring pop-in */}
              <circle cx={p.px} cy={p.py} r={PLANET_R}
                fill={c} opacity={isRunning ? 0.95 : 0.85}
                filter={isRunning ? "url(#sw-glow)" : undefined}
              >
                <animate attributeName="r"
                  values={`0;${PLANET_R * 1.35};${PLANET_R}`}
                  keyTimes="0;0.65;1"
                  dur="0.42s" fill="freeze" />
              </circle>

              {/* Label */}
              <text
                x={p.lx} y={p.ly}
                textAnchor={p.anchor} dominantBaseline="middle"
                fontSize={8.5}
                fill={isRunning ? "var(--blue)" : isDone ? "var(--mint, #34d399)" : "var(--fd)"}
                fontFamily="var(--font-geist-sans), system-ui, sans-serif"
                fontWeight={isRunning ? 600 : 400}
                opacity={0.9}
              >
                <animate attributeName="opacity" from="0" to="0.9" dur="0.5s" fill="freeze" />
                {clip(p.planet.label)}
              </text>

              {/* Moons */}
              {p.moons.map(m => (
                <circle key={m.key} cx={m.x} cy={m.y} r={MOON_R}
                  fill={nodeColor(m.status)} opacity={0.75}
                >
                  <animate attributeName="r"
                    values={`0;${MOON_R * 1.4};${MOON_R}`}
                    keyTimes="0;0.65;1"
                    dur="0.35s" fill="freeze" />
                </circle>
              ))}
            </g>
          );
        })}

        {/* Sun breath ring */}
        <circle cx={CX} cy={CY} r={SUN_R + 3}
          fill="none" stroke="var(--blue)" strokeWidth={1.5} strokeOpacity={0.18}>
          <animate attributeName="r"
            values={`${SUN_R + 3};${SUN_R + 20}`}
            dur="3.6s" repeatCount="indefinite" />
          <animate attributeName="opacity"
            values="0.5;0" dur="3.6s" repeatCount="indefinite" />
        </circle>

        {/* Sun */}
        <circle cx={CX} cy={CY} r={SUN_R} fill="var(--blue)" />
      </svg>

      {/* Sun label */}
      <div style={{
        position: "absolute", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        textAlign: "center", pointerEvents: "none", maxWidth: 72,
      }}>
        <div style={{
          fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
          fontSize: 11, fontWeight: 700, color: "#fff",
          letterSpacing: "-0.02em", textShadow: "0 1px 4px rgba(0,0,0,.5)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {coreLabel.length > 8 ? coreLabel.slice(0, 7) + "…" : coreLabel}
        </div>
        {coreSub && (
          <div style={{
            fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
            fontSize: 7.5, color: "rgba(255,255,255,.7)", marginTop: 2,
            textTransform: "uppercase", letterSpacing: ".09em",
            textShadow: "0 1px 3px rgba(0,0,0,.4)",
          }}>
            {coreSub}
          </div>
        )}
      </div>

      {/* Status line */}
      <div style={{
        position: "absolute", bottom: 10, left: 14,
        display: "flex", alignItems: "center", gap: 10,
        fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
        fontSize: 9.5, color: "var(--fm)",
      }}>
        {runCount > 0 && (
          <span style={{ color: "var(--blue)", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{
              width: 5, height: 5, borderRadius: "50%",
              background: "var(--blue)", display: "inline-block",
              animation: "sw-blink 1.2s ease-in-out infinite",
            }} />
            {runCount} working
          </span>
        )}
        {doneCount > 0 && (
          <span style={{ color: "var(--mint, #34d399)", fontWeight: 500 }}>{doneCount} done</span>
        )}
        <span>{groups.length} agents</span>
      </div>

      <style>{`
        @keyframes sw-blink { 0%,100%{ opacity:.35 } 50%{ opacity:1 } }
      `}</style>
    </div>
  );
}
