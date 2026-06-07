"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// ── Tour step definitions ─────────────────────────────────────────────────────

interface TourStep {
  target: string;       // data-tour attribute value
  title: string;
  description: string;
  position?: "top" | "bottom" | "left" | "right";
}

const TOUR_STEPS: TourStep[] = [
  {
    target: "new-goal-btn",
    title: "Start a new run",
    description: "Give Astra a goal in plain English — your AI founding team activates instantly across research, design, marketing, legal, and more.",
    position: "right",
  },
  {
    target: "nav-dashboard",
    title: "Your sessions",
    description: "Every run lives here. See what's in progress, what's done, and jump back into any session with a click.",
    position: "right",
  },
  {
    target: "nav-outreach",
    title: "Outreach",
    description: "Find leads and run personalized cold email campaigns routed through your connected Gmail — no manual list-building.",
    position: "right",
  },
  {
    target: "nav-company-brain",
    title: "Company Brain",
    description: "Everything Astra learns about your company lives here — goals, context, and artifacts your agents build on each run.",
    position: "right",
  },
  {
    target: "nav-integrations",
    title: "Connect your tools",
    description: "Link GitHub, Gmail, Vercel, Stripe, and more. Agents use your connected tools to ship code, send emails, and take real actions.",
    position: "right",
  },
  {
    target: "nav-payments",
    title: "Payments",
    description: "Connect Stripe to accept payments. Your revenue dashboard updates here in real time once you're live.",
    position: "right",
  },
];

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface TooltipPos {
  top: number;
  left: number;
  arrowSide: "top" | "bottom" | "left" | "right";
}

function computePosition(rect: DOMRect, position: TourStep["position"] = "bottom"): TooltipPos {
  const TW = 300; // tooltip width
  const TH = 140; // approx tooltip height
  const GAP = 14;

  switch (position) {
    case "right":
      return {
        top: rect.top + rect.height / 2 - TH / 2,
        left: rect.right + GAP,
        arrowSide: "left",
      };
    case "left":
      return {
        top: rect.top + rect.height / 2 - TH / 2,
        left: rect.left - TW - GAP,
        arrowSide: "right",
      };
    case "top":
      return {
        top: rect.top - TH - GAP,
        left: rect.left + rect.width / 2 - TW / 2,
        arrowSide: "bottom",
      };
    case "bottom":
    default:
      return {
        top: rect.bottom + GAP,
        left: rect.left + rect.width / 2 - TW / 2,
        arrowSide: "top",
      };
  }
}

// ── Main component ────────────────────────────────────────────────────────────

interface WorkspaceTourProps {
  onDone: () => void;
}

export default function WorkspaceTour({ onDone }: WorkspaceTourProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [visible, setVisible] = useState(false);
  const step = TOUR_STEPS[stepIndex];

  // Find the target element and get its rect
  const measureTarget = useCallback(() => {
    if (!step) return;
    const el = document.querySelector(`[data-tour="${step.target}"]`);
    if (el) {
      setTargetRect(el.getBoundingClientRect());
      setVisible(true);
    } else {
      // Target not in DOM — skip to next
      setTargetRect(null);
      setVisible(false);
    }
  }, [step]);

  useEffect(() => {
    // Small delay so DOM has settled
    const t = window.setTimeout(measureTarget, 120);
    return () => window.clearTimeout(t);
  }, [measureTarget]);

  // Re-measure on resize
  useEffect(() => {
    window.addEventListener("resize", measureTarget, { passive: true });
    return () => window.removeEventListener("resize", measureTarget);
  }, [measureTarget]);

  function handleNext() {
    if (stepIndex < TOUR_STEPS.length - 1) {
      setVisible(false);
      setStepIndex(i => i + 1);
    } else {
      handleDone();
    }
  }

  function handleDone() {
    localStorage.setItem("astra_tour_done", "1");
    onDone();
  }

  const isLast = stepIndex === TOUR_STEPS.length - 1;
  const tooltipPos = targetRect ? computePosition(targetRect, step?.position) : null;

  // Spotlight padding around the highlighted element
  const PAD = 8;
  const spotlight = targetRect
    ? {
        top: targetRect.top - PAD,
        left: targetRect.left - PAD,
        width: targetRect.width + PAD * 2,
        height: targetRect.height + PAD * 2,
      }
    : null;

  return (
    <>
      {/* Dark overlay with spotlight cutout */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 9998,
          pointerEvents: "auto",
        }}
        onClick={e => e.stopPropagation()}
      >
        <svg
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <mask id="tour-mask">
              <rect width="100%" height="100%" fill="white" />
              {spotlight && (
                <rect
                  x={spotlight.left}
                  y={spotlight.top}
                  width={spotlight.width}
                  height={spotlight.height}
                  rx={12}
                  fill="black"
                />
              )}
            </mask>
          </defs>
          <rect
            width="100%"
            height="100%"
            fill="rgba(0,0,0,0.55)"
            mask="url(#tour-mask)"
          />
        </svg>

        {/* Spotlight border glow */}
        {spotlight && (
          <div
            style={{
              position: "absolute",
              top: spotlight.top,
              left: spotlight.left,
              width: spotlight.width,
              height: spotlight.height,
              borderRadius: 12,
              boxShadow: "0 0 0 2px rgba(37,99,235,0.7), 0 0 20px rgba(37,99,235,0.3)",
              pointerEvents: "none",
              transition: "all 0.25s",
            }}
          />
        )}
      </div>

      {/* Tooltip */}
      {tooltipPos && visible && (
        <div
          style={{
            position: "fixed",
            top: Math.max(12, Math.min(window.innerHeight - 180, tooltipPos.top)),
            left: Math.max(12, Math.min(window.innerWidth - 320, tooltipPos.left)),
            width: 300,
            zIndex: 9999,
            borderRadius: 18,
            border: "1px solid rgba(0,0,0,0.12)",
            background: "var(--glass, rgba(255,255,255,0.92))",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
            padding: "18px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 12,
            transition: "top 0.25s, left 0.25s",
          }}
        >
          {/* Step counter */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute, #888)" }}>
              {stepIndex + 1} of {TOUR_STEPS.length}
            </span>
            <button
              onClick={handleDone}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16, color: "var(--fg-mute, #888)", lineHeight: 1, padding: 0 }}
              aria-label="Close tour"
            >
              ×
            </button>
          </div>

          {/* Content */}
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 5px", color: "var(--fg, #111)" }}>{step.title}</h3>
            <p style={{ fontSize: 12, color: "var(--fg-mute, #666)", margin: 0, lineHeight: 1.6 }}>{step.description}</p>
          </div>

          {/* Progress dots */}
          <div style={{ display: "flex", gap: 5, justifyContent: "center" }}>
            {TOUR_STEPS.map((_, i) => (
              <div
                key={i}
                style={{
                  width: i === stepIndex ? 16 : 6,
                  height: 6,
                  borderRadius: 999,
                  background: i === stepIndex ? "#2b45ff" : i < stepIndex ? "rgba(37,99,235,0.35)" : "rgba(0,0,0,0.15)",
                  transition: "width 0.2s, background 0.2s",
                }}
              />
            ))}
          </div>

          {/* Buttons */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <button
              onClick={handleDone}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--fg-mute, #888)", padding: 0 }}
            >
              Skip tour
            </button>
            <button
              onClick={handleNext}
              style={{
                padding: "8px 20px",
                borderRadius: 999,
                background: "#2b45ff",
                color: "#fff",
                border: "none",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {isLast ? "Done ✓" : "Next →"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
