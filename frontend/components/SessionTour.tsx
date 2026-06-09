"use client";

import { useCallback, useEffect, useState } from "react";

interface TourStep {
  target: string | null;
  title: string;
  icon: string;
  description: string;
  hint?: string;           // small italic action hint shown below description
  position?: "top" | "bottom" | "left" | "right" | "center";
}

const STEPS: TourStep[] = [
  {
    target: null,
    title: "Your run is live",
    icon: "◈",
    description: "Astra's agents are working in parallel right now. Here's a quick walkthrough of everything you can see and do.",
    position: "center",
  },
  {
    target: "session-phasebar",
    title: "Phase progress",
    icon: "→",
    description: "Your build moves through five phases: Diagnose → Design → Deploy → Govern → Operate. Each phase unlocks after you approve the previous one.",
    hint: "The active phase is highlighted in blue.",
    position: "bottom",
  },
  {
    target: "session-depts",
    title: "Your agent teams",
    icon: "⬡",
    description: "Each card is a department of AI agents — Research, Design, Marketing, Legal, Finance, and more. They work in parallel, not in sequence.",
    hint: "Click any card to see exactly what that team is building.",
    position: "top",
  },
  {
    target: "session-vault",
    title: "Deliverables vault",
    icon: "◈",
    description: "Every artifact your agents produce lands here — strategy docs, code, market analysis, pitch decks. Items appear as 'Ready' once an agent finishes.",
    hint: "Click any deliverable to read the full output.",
    position: "right",
  },
  {
    target: "session-detail",
    title: "Live updates & logs",
    icon: "≡",
    description: "After clicking a department card, you'll see three tabs here: Updates (plain-English progress), Technical logs (raw agent output), and Sources (URLs the agents researched).",
    hint: "Click a department card above, then switch between the tabs.",
    position: "left",
  },
  {
    target: "session-steerbar",
    title: "Steer your agents",
    icon: "↑",
    description: "Send real-time instructions to redirect the entire team mid-run. You don't have to wait for a phase to complete.",
    hint: 'Try: "focus on enterprise customers" · "skip the legal section" · "make it more aggressive"',
    position: "top",
  },
];

const PAD = 10;
const TW = 340;
const TH = 240;

interface Rect { top: number; left: number; width: number; height: number }

function measure(target: string | null): Rect | null {
  if (!target) return null;
  const el = document.querySelector(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function tooltipPos(rect: Rect | null, position: TourStep["position"] = "right") {
  if (!rect || position === "center") {
    return {
      top: Math.max(12, window.innerHeight / 2 - TH / 2),
      left: Math.max(12, window.innerWidth / 2 - TW / 2),
    };
  }
  const GAP = 16;
  const vw = window.innerWidth, vh = window.innerHeight;
  let top = 0, left = 0;
  switch (position) {
    case "right":
      top = rect.top + rect.height / 2 - TH / 2;
      left = rect.left + rect.width + PAD + GAP;
      break;
    case "left":
      top = rect.top + rect.height / 2 - TH / 2;
      left = rect.left - TW - PAD - GAP;
      break;
    case "top":
      top = rect.top - PAD - TH - GAP;
      left = rect.left + rect.width / 2 - TW / 2;
      break;
    case "bottom":
    default:
      top = rect.top + rect.height + PAD + GAP;
      left = rect.left + rect.width / 2 - TW / 2;
  }
  return {
    top: Math.max(12, Math.min(vh - TH - 12, top)),
    left: Math.max(12, Math.min(vw - TW - 12, left)),
  };
}

export default function SessionTour({ onDone }: { onDone: () => void }) {
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [ready, setReady] = useState(false);

  const step = STEPS[idx];

  const remeasure = useCallback(() => {
    setRect(measure(step?.target ?? null));
  }, [step]);

  useEffect(() => {
    setReady(false);
    const t = setTimeout(() => { remeasure(); setReady(true); }, 80);
    return () => clearTimeout(t);
  }, [remeasure, idx]);

  useEffect(() => {
    window.addEventListener("resize", remeasure, { passive: true });
    return () => window.removeEventListener("resize", remeasure);
  }, [remeasure]);

  // Esc always closes the tour so it can never trap the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onDone(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  function next() {
    if (idx < STEPS.length - 1) {
      setReady(false);
      setTimeout(() => setIdx(i => i + 1), 60);
    } else {
      onDone();
    }
  }

  const isLast = idx === STEPS.length - 1;
  const spotlight = rect
    ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }
    : null;
  const tip = tooltipPos(rect, step?.position);

  return (
    <>
      <style>{`
        @keyframes st-in {
          from { opacity: 0; transform: translateY(8px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes st-ring {
          0%, 100% { box-shadow: 0 0 0 2px rgba(0,46,255,.75), 0 0 18px rgba(0,46,255,.22); }
          50%       { box-shadow: 0 0 0 3px rgba(0,46,255,.95), 0 0 30px rgba(0,46,255,.38); }
        }
        .st-card { animation: st-in 0.2s cubic-bezier(0.22,1,0.36,1) forwards; }
        .st-ring { animation: st-ring 2s ease-in-out infinite; transition: top .32s cubic-bezier(0.22,1,0.36,1), left .32s cubic-bezier(0.22,1,0.36,1), width .32s cubic-bezier(0.22,1,0.36,1), height .32s cubic-bezier(0.22,1,0.36,1); }
      `}</style>

      {/* Overlay — tapping the dark backdrop dismisses the tour (safety net so it
          can always be closed, e.g. on mobile where the card buttons may be cramped). */}
      <div style={{ position: "fixed", inset: 0, zIndex: 9000, pointerEvents: "auto", touchAction: "manipulation" }} onClick={onDone}>
        <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
          <defs>
            <mask id="st-mask">
              <rect width="100%" height="100%" fill="white" />
              {spotlight && (
                <rect x={spotlight.left} y={spotlight.top} width={spotlight.width} height={spotlight.height} rx={10} fill="black" />
              )}
            </mask>
          </defs>
          <rect width="100%" height="100%" fill="rgba(0,0,0,0.58)" mask="url(#st-mask)" />
        </svg>

        {spotlight && (
          <div className="st-ring" style={{
            position: "absolute",
            top: spotlight.top, left: spotlight.left,
            width: spotlight.width, height: spotlight.height,
            borderRadius: 10, pointerEvents: "none",
          }} />
        )}
      </div>

      {/* Tooltip */}
      {ready && (
        <div key={idx} className="st-card" style={{
          position: "fixed", top: tip.top, left: tip.left, width: TW,
          zIndex: 9001, borderRadius: 16,
          background: "var(--surface)", border: "1px solid var(--bd)",
          boxShadow: "0 16px 48px rgba(0,0,0,0.32), 0 2px 8px rgba(0,0,0,0.1)",
          overflow: "hidden",
        }}>
          {/* Top accent */}
          <div style={{ height: 3, background: "linear-gradient(90deg, var(--blue), var(--mint))" }} />

          <div style={{ padding: "16px 18px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            {/* Header row */}
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                  background: "rgba(0,46,255,.1)", border: "1px solid rgba(59,130,246,.25)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, color: "var(--blue)", fontFamily: "var(--font-chakra)", fontWeight: 700,
                }}>{step.icon}</div>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>{step.title}</div>
                  <div style={{ fontSize: 9.5, color: "var(--fm)", marginTop: 1 }}>{idx + 1} of {STEPS.length}</div>
                </div>
              </div>
              <button onClick={onDone} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--fm)", fontSize: 18, lineHeight: 1, padding: "2px 4px", borderRadius: 4 }}>×</button>
            </div>

            {/* Description */}
            <p style={{ fontSize: 12, color: "var(--fd)", lineHeight: 1.7, margin: 0 }}>{step.description}</p>

            {/* Hint */}
            {step.hint && (
              <p style={{
                fontSize: 10.5, color: "var(--blue)", lineHeight: 1.55, margin: 0,
                background: "rgba(59,130,246,.07)", border: "1px solid rgba(0,46,255,.18)",
                borderRadius: 7, padding: "7px 10px", fontStyle: "italic",
              }}>
                {step.hint}
              </p>
            )}

            {/* Progress dots */}
            <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
              {STEPS.map((_, i) => (
                <div
                  key={i}
                  onClick={() => { setReady(false); setTimeout(() => setIdx(i), 60); }}
                  style={{
                    height: 4, borderRadius: 999, cursor: "pointer",
                    width: 20,
                    background: i === idx ? "var(--blue)" : i < idx ? "rgba(0,46,255,.35)" : "var(--bd)",
                    clipPath: `inset(0 ${i === idx ? 0 : 70}% 0 0 round 999px)`,
                    transition: "clip-path 0.22s cubic-bezier(0.22,1,0.36,1), background 0.22s",
                  }}
                />
              ))}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <button onClick={onDone} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "var(--fm)", padding: 0 }}>
                Skip tour
              </button>
              <button
                onClick={next}
                style={{
                  padding: "7px 18px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                  background: "var(--blue)", color: "#fff", border: "none", cursor: "pointer",
                  transition: "opacity .15s",
                }}
                onMouseEnter={e => (e.currentTarget.style.opacity = "0.85")}
                onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
              >
                {isLast ? "Got it ✓" : "Next →"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
