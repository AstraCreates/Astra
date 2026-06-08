"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface TourStep {
  target: string | null;       // data-tour value, or null for a centered card
  title: string;
  description: string;
  icon: string;
  position?: "top" | "bottom" | "left" | "right";
  action?: { label: string; href: string };  // optional "Try it" CTA
}

const TOUR_STEPS: TourStep[] = [
  {
    target: null,
    title: "Welcome to your workspace",
    icon: "✦",
    description: "This is where your AI founding team lives. Let's walk through the key parts — takes about 30 seconds.",
    position: "bottom",
  },
  {
    target: "new-goal-btn",
    title: "Start a new run",
    icon: "＋",
    description: "Give Astra a goal in plain English. Your AI team — research, design, marketing, legal, finance — activates instantly and works in parallel.",
    position: "right",
    action: { label: "Try it →", href: "/?new=1" },
  },
  {
    target: "nav-dashboard",
    title: "Sessions dashboard",
    icon: "⬡",
    description: "Every run you launch lives here. See live status, what's running, what's done, and what needs your approval — all at a glance.",
    position: "right",
  },
  {
    target: "dash-new-run",
    title: "Launch from the dashboard too",
    icon: "↗",
    description: "You can also kick off a new run directly from the dashboard. Your company context from onboarding is automatically included — just describe the goal.",
    position: "bottom",
  },
  {
    target: "nav-outreach",
    title: "Outreach",
    icon: "✦",
    description: "Find qualified leads and run personalized cold email campaigns — automatically routed through your connected Gmail. No manual list-building.",
    position: "right",
  },
  {
    target: "nav-company-brain",
    title: "Company Brain",
    icon: "◈",
    description: "Everything Astra learns about your company lives here. Agents reference this context on every run — the more you build, the smarter they get.",
    position: "right",
  },
  {
    target: "nav-integrations",
    title: "Connect your tools",
    icon: "⌘",
    description: "Link GitHub, Gmail, Vercel, Stripe, Notion, and more. Agents use your connected tools to ship code, send emails, and take real actions on your behalf.",
    position: "right",
    action: { label: "Connect tools →", href: "/integrations" },
  },
  {
    target: "nav-payments",
    title: "Payments",
    icon: "$",
    description: "Once you connect Stripe, your revenue dashboard updates in real time. Track MRR, transactions, and active subscribers from here.",
    position: "right",
  },
];

interface SpotlightRect { top: number; left: number; width: number; height: number; }

function measureTarget(target: string | null): SpotlightRect | null {
  if (!target) return null;
  const el = document.querySelector(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

const PAD = 10;

function getTooltipPos(
  rect: SpotlightRect | null,
  position: TourStep["position"] = "right",
  TW = 320,
  TH = 200,
) {
  if (!rect) {
    // Centered
    return {
      top: window.innerHeight / 2 - TH / 2,
      left: window.innerWidth / 2 - TW / 2,
    };
  }
  const GAP = 18;
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
  // Clamp
  top = Math.max(12, Math.min(vh - TH - 12, top));
  left = Math.max(12, Math.min(vw - TW - 12, left));
  return { top, left };
}

export default function WorkspaceTour({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<SpotlightRect | null>(null);
  const [entering, setEntering] = useState(true);
  const step = TOUR_STEPS[idx];

  const measure = useCallback(() => {
    const r = measureTarget(step?.target ?? null);
    setRect(r);
  }, [step]);

  useEffect(() => {
    setEntering(true);
    const t = setTimeout(() => {
      measure();
      setEntering(false);
    }, 80);
    return () => clearTimeout(t);
  }, [measure, idx]);

  // Esc always closes the tour so it can never trap the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onDone(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  useEffect(() => {
    window.addEventListener("resize", measure, { passive: true });
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  function advance() {
    if (idx < TOUR_STEPS.length - 1) {
      setEntering(true);
      setTimeout(() => setIdx(i => i + 1), 50);
    } else {
      finish();
    }
  }

  function finish() {
    localStorage.setItem("astra_tour_done", "1");
    onDone();
  }

  const isLast = idx === TOUR_STEPS.length - 1;
  const spotlight = rect
    ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }
    : null;
  const tipPos = getTooltipPos(rect, step?.position);

  return (
    <>
      <style>{`
        @keyframes tour-fade-in {
          from { opacity: 0; transform: scale(0.97) translateY(6px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes tour-spotlight-pulse {
          0%, 100% { box-shadow: 0 0 0 2px rgba(0,46,255,0.7), 0 0 20px rgba(0,46,255,0.25); }
          50%       { box-shadow: 0 0 0 3px rgba(0,46,255,0.9), 0 0 32px rgba(0,46,255,0.4); }
        }
        @keyframes tour-dot-active {
          0%, 100% { transform: scaleX(1); }
          50%       { transform: scaleX(1.15); }
        }
        .tour-tip {
          animation: tour-fade-in 0.22s cubic-bezier(0.22,1,0.36,1) forwards;
        }
        .tour-spotlight-ring {
          animation: tour-spotlight-pulse 2s ease-in-out infinite;
          transition: top 0.35s cubic-bezier(0.22,1,0.36,1),
                      left 0.35s cubic-bezier(0.22,1,0.36,1),
                      width 0.35s cubic-bezier(0.22,1,0.36,1),
                      height 0.35s cubic-bezier(0.22,1,0.36,1);
        }
      `}</style>

      {/* Overlay — tap backdrop to dismiss (safety net for cramped mobile cards) */}
      <div
        style={{ position: "fixed", inset: 0, zIndex: 9000, pointerEvents: "auto", touchAction: "manipulation" }}
        onClick={onDone}
      >
        <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
          <defs>
            <mask id="tour-mask">
              <rect width="100%" height="100%" fill="white" />
              {spotlight && (
                <rect
                  x={spotlight.left} y={spotlight.top}
                  width={spotlight.width} height={spotlight.height}
                  rx={10} fill="black"
                  style={{ transition: "all 0.35s cubic-bezier(0.22,1,0.36,1)" }}
                />
              )}
            </mask>
          </defs>
          <rect width="100%" height="100%" fill="rgba(0,0,0,0.6)" mask="url(#tour-mask)" />
        </svg>

        {/* Spotlight ring */}
        {spotlight && (
          <div
            className="tour-spotlight-ring"
            style={{
              position: "absolute",
              top: spotlight.top, left: spotlight.left,
              width: spotlight.width, height: spotlight.height,
              borderRadius: 10,
              pointerEvents: "none",
            }}
          />
        )}
      </div>

      {/* Tooltip card */}
      {!entering && (
        <div
          key={idx}
          className="tour-tip"
          style={{
            position: "fixed",
            top: tipPos.top,
            left: tipPos.left,
            width: 320,
            zIndex: 9001,
            borderRadius: 16,
            background: "var(--surface)",
            border: "1px solid var(--bd)",
            boxShadow: "0 12px 40px rgba(0,0,0,0.28), 0 2px 8px rgba(0,0,0,0.12)",
            overflow: "hidden",
          }}
        >
          {/* Blue accent bar */}
          <div style={{ height: 3, background: "linear-gradient(90deg, var(--blue), var(--mint))" }} />

          <div style={{ padding: "16px 18px 18px", display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                  background: "rgba(0,46,255,0.1)",
                  border: "1px solid rgba(0,46,255,0.25)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 14, color: "var(--blue)",
                  fontFamily: "var(--font-chakra)", fontWeight: 700,
                }}>
                  {step.icon}
                </div>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>{step.title}</div>
                  <div style={{ fontSize: 9.5, color: "var(--fm)", marginTop: 1 }}>
                    {idx + 1} of {TOUR_STEPS.length}
                  </div>
                </div>
              </div>
              <button
                onClick={finish}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--fm)", fontSize: 18, lineHeight: 1, padding: "2px 4px", borderRadius: 4, flexShrink: 0 }}
              >×</button>
            </div>

            {/* Description */}
            <p style={{ fontSize: 12, color: "var(--fd)", lineHeight: 1.65, margin: 0 }}>
              {step.description}
            </p>

            {/* Progress dots */}
            <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
              {TOUR_STEPS.map((_, i) => (
                <div
                  key={i}
                  onClick={() => { setEntering(true); setTimeout(() => setIdx(i), 50); }}
                  style={{
                    height: 4, borderRadius: 999,
                    width: i === idx ? 20 : 6,
                    background: i === idx ? "var(--blue)" : i < idx ? "rgba(59,130,246,0.35)" : "var(--bd)",
                    transition: "width 0.25s, background 0.25s",
                    cursor: "pointer",
                    animation: i === idx ? "tour-dot-active 2s ease-in-out infinite" : "none",
                  }}
                />
              ))}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <button
                onClick={finish}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "var(--fm)", padding: 0 }}
              >
                Skip tour
              </button>
              <div style={{ display: "flex", gap: 7 }}>
                {step.action && (
                  <button
                    onClick={() => { finish(); router.push(step.action!.href); }}
                    style={{
                      padding: "7px 14px", borderRadius: 8, fontSize: 11, fontWeight: 600,
                      background: "rgba(0,46,255,0.1)",
                      border: "1px solid rgba(59,130,246,0.35)",
                      color: "var(--blue)", cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(59,130,246,0.18)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(0,46,255,0.1)")}
                  >
                    {step.action.label}
                  </button>
                )}
                <button
                  onClick={advance}
                  style={{
                    padding: "7px 16px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                    background: "var(--blue)", color: "#fff",
                    border: "none", cursor: "pointer",
                    transition: "opacity 0.15s",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.85")}
                  onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
                >
                  {isLast ? "Done ✓" : "Next →"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
