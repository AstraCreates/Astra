"use client";

import { useEffect, useRef, useCallback } from "react";
import { starPos } from "./starState";

// [scrollFraction 0–1, viewportX vw, viewportY vh]
const WAYPOINTS: [number, number, number][] = [
  [0,    76, 17],
  [0.05, 13, 35],
  [0.10, 20, 60],
  [0.16, 55, 30],
  [0.21, 16, 52],
  [0.26, 74, 42],
  [0.31, 42, 32],
  [0.36, 12, 52],
  [0.41, 78, 48],
  [0.47, 50, 25],
  [0.53, 10, 52],
  [0.59, 82, 45],
  [0.64, 48, 30],
  [0.70, 30, 52],
  [0.76, 70, 48],
  [0.83, 50, 38],
  [0.91, 48, 55],
  [1.00, 50, 75],
];

function smoothstep(t: number): number {
  t = Math.max(0, Math.min(1, t));
  return t * t * (3 - 2 * t);
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function getTarget(sf: number): { x: number; y: number } {
  const wp = WAYPOINTS;
  if (sf <= wp[0][0]) return { x: wp[0][1], y: wp[0][2] };
  for (let i = 0; i < wp.length - 1; i++) {
    const [s0, x0, y0] = wp[i];
    const [s1, x1, y1] = wp[i + 1];
    if (sf >= s0 && sf <= s1) {
      const t = smoothstep((sf - s0) / (s1 - s0));
      return { x: lerp(x0, x1, t), y: lerp(y0, y1, t) };
    }
  }
  const last = wp[wp.length - 1];
  return { x: last[1], y: last[2] };
}

// ─── SVG shapes ──────────────────────────────────────────────────────────────

// Full navigator reticle — main star only
function NavReticle({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} fill="none" color="var(--sg-color)">
      {/* Outer rotating dashed ring */}
      <circle
        cx="32" cy="32" r="26"
        stroke="currentColor" strokeWidth="0.9" fill="none"
        strokeDasharray="10 5"
        className="sg-ring"
      />
      {/* 4 diagonal ticks between the main spikes */}
      {([45, 135, 225, 315] as const).map(deg => (
        <line
          key={deg}
          x1="32" y1="7" x2="32" y2="15"
          stroke="currentColor" strokeWidth="1.2"
          strokeLinecap="round"
          opacity="0.5"
          transform={`rotate(${deg}, 32, 32)`}
        />
      ))}
      {/* 4 main elongated diamond spikes */}
      <path d="M32 2  L34.5 24 L32 27.5 L29.5 24  Z" fill="currentColor"/>
      <path d="M62 32 L40 29.5 L36.5 32 L40 34.5 Z" fill="currentColor"/>
      <path d="M32 62 L34.5 40 L32 36.5 L29.5 40  Z" fill="currentColor"/>
      <path d="M2  32 L24 29.5 L27.5 32 L24 34.5 Z" fill="currentColor"/>
      {/* Inner accent ring */}
      <circle cx="32" cy="32" r="7.5" stroke="currentColor" strokeWidth="0.85" fill="none" opacity="0.5"/>
      {/* Center dot */}
      <circle cx="32" cy="32" r="2.8" fill="currentColor"/>
    </svg>
  );
}

// Ghost copy — just spikes + center, no ring/ticks (stays crisp at small sizes)
function NavGhost({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} fill="none" color="var(--sg-color)">
      <path d="M32 2  L34.5 24 L32 27.5 L29.5 24  Z" fill="currentColor"/>
      <path d="M62 32 L40 29.5 L36.5 32 L40 34.5 Z" fill="currentColor"/>
      <path d="M32 62 L34.5 40 L32 36.5 L29.5 40  Z" fill="currentColor"/>
      <path d="M2  32 L24 29.5 L27.5 32 L24 34.5 Z" fill="currentColor"/>
      <circle cx="32" cy="32" r="2.2" fill="currentColor"/>
    </svg>
  );
}

// ─── component ───────────────────────────────────────────────────────────────

export default function StarGuide() {
  const mainRef = useRef<HTMLDivElement>(null);
  const g1Ref   = useRef<HTMLDivElement>(null);
  const g2Ref   = useRef<HTMLDivElement>(null);
  const cur     = useRef({ x: 76, y: 17 });
  const tgt     = useRef({ x: 76, y: 17 });
  const g1pos   = useRef({ x: 76, y: 17 });
  const g2pos   = useRef({ x: 76, y: 17 });
  const rafRef  = useRef<number>(0);

  const applyPos = useCallback((el: HTMLDivElement | null, x: number, y: number) => {
    if (el) el.style.transform = `translate(calc(${x}vw - 50%), calc(${y}vh - 50%))`;
  }, []);

  const tick = useCallback(() => {
    const c  = cur.current;
    const t  = tgt.current;
    const g1 = g1pos.current;
    const g2 = g2pos.current;

    c.x  += (t.x  - c.x)  * 0.052;
    c.y  += (t.y  - c.y)  * 0.052;
    g1.x += (c.x  - g1.x) * 0.036;
    g1.y += (c.y  - g1.y) * 0.036;
    g2.x += (g1.x - g2.x) * 0.024;
    g2.y += (g1.y - g2.y) * 0.024;

    applyPos(mainRef.current, c.x, c.y);
    applyPos(g1Ref.current,   g1.x, g1.y);
    applyPos(g2Ref.current,   g2.x, g2.y);

    // Publish screen position so SpaceEnv can draw a light bloom around us
    starPos.x = (c.x / 100) * window.innerWidth;
    starPos.y = (c.y / 100) * window.innerHeight;

    rafRef.current = requestAnimationFrame(tick);
  }, [applyPos]);

  useEffect(() => {
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const sf = max > 0 ? Math.max(0, Math.min(1, window.scrollY / max)) : 0;
      tgt.current = getTarget(sf);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(rafRef.current);
      starPos.x = -9999;
      starPos.y = -9999;
    };
  }, [tick]);

  return (
    <div aria-hidden="true" className="sg-root">
      <div ref={g2Ref} className="sg-node sg-g2"><NavGhost size={14} /></div>
      <div ref={g1Ref} className="sg-node sg-g1"><NavGhost size={22} /></div>
      <div ref={mainRef} className="sg-node sg-star"><NavReticle size={42} /></div>
    </div>
  );
}
