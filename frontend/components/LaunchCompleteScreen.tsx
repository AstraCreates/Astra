"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";

const LS_KEY = "astra_launch_complete_shown";

const SIGNAL_KEY = "astra_launch_complete_preview";

export function markLaunchCompleteShown() {
  try { localStorage.setItem(LS_KEY, "1"); } catch {}
}

export function clearLaunchCompleteShown() {
  try {
    localStorage.removeItem(LS_KEY);
    localStorage.setItem(SIGNAL_KEY, "1");
  } catch {}
}

export function shouldShowLaunchComplete(): boolean {
  try { return !localStorage.getItem(LS_KEY); } catch { return false; }
}

/** Returns true (and consumes the signal) if settings triggered a preview. */
export function consumePreviewSignal(): boolean {
  try {
    if (!localStorage.getItem(SIGNAL_KEY)) return false;
    localStorage.removeItem(SIGNAL_KEY);
    return true;
  } catch { return false; }
}

const FADE = { duration: 0.7, ease: [0.22, 1, 0.36, 1] as const };
const STAGGER = 0.12;

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div style={{ textAlign: "center", padding: "0 20px" }}>
      <div style={{
        fontSize: "clamp(28px, 5vw, 48px)", fontWeight: 700,
        color: "#fff", letterSpacing: "-0.03em", lineHeight: 1,
        fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
      }}>{value}</div>
      <div style={{ fontSize: 12, color: "rgba(255,255,255,0.55)", marginTop: 5, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500 }}>{label}</div>
    </div>
  );
}

export default function LaunchCompleteScreen({
  companyName,
  agentsRan = 0,
  artifactsCreated = 0,
  stackName,
  onComplete,
}: {
  companyName: string;
  agentsRan?: number;
  artifactsCreated?: number;
  stackName?: string;
  onComplete: () => void;
}) {
  const [visible, setVisible] = useState(true);
  const [phase, setPhase] = useState<"in" | "out">("in");
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    markLaunchCompleteShown();
  }, []);

  function dismiss() {
    setPhase("out");
    setTimeout(() => {
      setVisible(false);
      onCompleteRef.current();
    }, 600);
  }

  if (!visible) return null;

  const displayName = (companyName || "Your company").trim();

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
      overflow: "hidden",
      background: "linear-gradient(135deg, #002eff 0%, #1a45ff 25%, #5df5e0 65%, #fefff6 100%)",
      opacity: phase === "out" ? 0 : 1,
      transform: phase === "out" ? "scale(1.04)" : "scale(1)",
      transition: phase === "out" ? "opacity 0.55s ease, transform 0.55s ease" : "none",
    }}>
      <AstraGradient />

      {/* Skip */}
      <button
        onClick={dismiss}
        style={{
          position: "absolute", top: 22, right: 24,
          background: "rgba(255,255,255,0.14)", border: "1px solid rgba(255,255,255,0.22)",
          borderRadius: 20, padding: "5px 14px", cursor: "pointer",
          fontSize: 12, color: "rgba(255,255,255,0.7)", fontWeight: 500, zIndex: 10,
          fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
          backdropFilter: "blur(8px)",
        }}
      >
        Skip
      </button>

      {/* Logo */}
      <div style={{ position: "absolute", top: 24, left: 28, display: "flex", alignItems: "center", gap: 8, zIndex: 10 }}>
        <div style={{
          width: 26, height: 26, flexShrink: 0,
          background: "#fff",
          WebkitMask: "url('/logo.png') center/contain no-repeat",
          mask: "url('/logo.png') center/contain no-repeat",
        }} />
        <span style={{ fontSize: 12, letterSpacing: "0.2em", textTransform: "uppercase", color: "rgba(255,255,255,0.8)", fontWeight: 700, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>Astra</span>
      </div>

      {/* Main content */}
      <div style={{ position: "relative", zIndex: 2, width: "100%", maxWidth: 700, padding: "0 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>

        {/* Headline block */}
        <AnimatePresence>
          <motion.div
            key="headline"
            initial={{ opacity: 0, y: 32, filter: "blur(12px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ ...FADE, delay: 0.15 }}
            style={{ textAlign: "center" }}
          >
            {/* Badge */}
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ ...FADE, delay: 0.05 }}
              style={{
                display: "inline-flex", alignItems: "center", gap: 7,
                background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.28)",
                borderRadius: 20, padding: "5px 14px", marginBottom: 28,
                backdropFilter: "blur(8px)",
              }}
            >
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#4ade80", boxShadow: "0 0 8px #4ade80", flexShrink: 0 }} />
              <span style={{ fontSize: 11, color: "rgba(255,255,255,0.9)", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>
                Launch complete
              </span>
            </motion.div>

            <h1 style={{
              fontSize: "clamp(38px, 7vw, 80px)",
              fontWeight: 800,
              color: "#fff",
              margin: 0,
              lineHeight: 1.0,
              letterSpacing: "-0.035em",
              fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            }}>
              {displayName}
              <br />
              <span style={{ color: "rgba(255,255,255,0.55)" }}>is live.</span>
            </h1>

            {stackName && (
              <p style={{
                marginTop: 18, fontSize: 15, color: "rgba(255,255,255,0.6)", lineHeight: 1.6,
                fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
              }}>
                Launched with the <strong style={{ color: "rgba(255,255,255,0.85)" }}>{stackName}</strong> stack
              </p>
            )}
          </motion.div>
        </AnimatePresence>

        {/* Stats row */}
        {(agentsRan > 0 || artifactsCreated > 0) && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...FADE, delay: 0.35 }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "rgba(255,255,255,0.1)", border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: 18, padding: "20px 8px", backdropFilter: "blur(12px)",
              width: "100%",
            }}
          >
            {agentsRan > 0 && <Stat value={agentsRan} label="Agents ran" />}
            {agentsRan > 0 && artifactsCreated > 0 && (
              <div style={{ width: 1, height: 40, background: "rgba(255,255,255,0.2)" }} />
            )}
            {artifactsCreated > 0 && <Stat value={artifactsCreated} label="Deliverables" />}
            {agentsRan > 0 && (
              <>
                <div style={{ width: 1, height: 40, background: "rgba(255,255,255,0.2)" }} />
                <Stat value="Live" label="Status" />
              </>
            )}
          </motion.div>
        )}

        {/* CTA */}
        <motion.button
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...FADE, delay: 0.5 + STAGGER }}
          onClick={dismiss}
          style={{
            background: "#fff", color: "#002eff",
            border: "none", borderRadius: 14,
            padding: "16px 48px", fontSize: 16, fontWeight: 700,
            cursor: "pointer", letterSpacing: "-0.01em",
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            boxShadow: "0 8px 32px rgba(0,46,255,0.25)",
            transition: "transform 0.15s ease, box-shadow 0.15s ease",
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 12px 40px rgba(0,46,255,0.35)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = ""; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 32px rgba(0,46,255,0.25)"; }}
        >
          Open workspace →
        </motion.button>

        {/* Fine print */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ ...FADE, delay: 0.7 }}
          style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", margin: 0, textAlign: "center", fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}
        >
          Your agents are continuing to work in the background
        </motion.p>
      </div>
    </div>
  );
}
