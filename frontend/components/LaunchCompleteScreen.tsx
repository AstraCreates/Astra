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

export function consumePreviewSignal(): boolean {
  try {
    if (!localStorage.getItem(SIGNAL_KEY)) return false;
    localStorage.removeItem(SIGNAL_KEY);
    return true;
  } catch { return false; }
}

const FADE = { duration: 0.7, ease: [0.22, 1, 0.36, 1] as const };
const CONFETTI_COLORS = [
  "#002eff", "#5df5e0", "#4ade80", "#fbbf24", "#f472b6",
  "#a78bfa", "#38bdf8", "#fb923c", "#ffffff",
];

function randomBetween(a: number, b: number) {
  return a + Math.random() * (b - a);
}

interface Particle {
  id: number;
  x: number;
  color: string;
  delay: number;
  duration: number;
  size: number;
  rotation: number;
  shape: "rect" | "circle";
}

function Confetti() {
  const [particles] = useState<Particle[]>(() =>
    Array.from({ length: 80 }, (_, i) => ({
      id: i,
      x: randomBetween(2, 98),
      color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
      delay: randomBetween(0, 1.2),
      duration: randomBetween(2.2, 4.0),
      size: randomBetween(6, 14),
      rotation: randomBetween(-180, 180),
      shape: Math.random() > 0.4 ? "rect" : "circle",
    }))
  );

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 5 }}>
      {particles.map(p => (
        <motion.div
          key={p.id}
          initial={{ y: -20, opacity: 1, rotate: 0 }}
          animate={{ y: "110vh", opacity: [1, 1, 0.8, 0], rotate: p.rotation * 3 }}
          transition={{ duration: p.duration, delay: p.delay, ease: "easeIn", repeat: Infinity, repeatDelay: randomBetween(0, 2) }}
          style={{
            position: "absolute",
            left: `${p.x}%`,
            top: 0,
            width: p.shape === "rect" ? p.size : p.size,
            height: p.shape === "rect" ? p.size * 0.45 : p.size,
            borderRadius: p.shape === "circle" ? "50%" : 2,
            background: p.color,
            opacity: 0.9,
          }}
        />
      ))}
    </div>
  );
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div style={{ textAlign: "center", padding: "0 20px" }}>
      <div style={{
        fontSize: "clamp(28px, 5vw, 48px)", fontWeight: 700,
        color: "#002eff", letterSpacing: "-0.03em", lineHeight: 1,
        fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
      }}>{value}</div>
      <div style={{ fontSize: 12, color: "#5566aa", marginTop: 5, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500 }}>{label}</div>
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
  const [phase, setPhase] = useState<"congrats" | "launch" | "out">("congrats");
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    markLaunchCompleteShown();
  }, []);

  // Auto-advance congrats → launch after 2.8s
  useEffect(() => {
    if (phase !== "congrats") return;
    const t = setTimeout(() => setPhase("launch"), 2800);
    return () => clearTimeout(t);
  }, [phase]);

  function dismiss() {
    setPhase("out");
    setTimeout(() => {
      setVisible(false);
      onCompleteRef.current();
    }, 550);
  }

  if (!visible) return null;

  const displayName = (companyName || "Your company").trim();

  const isOut = phase === "out";

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      overflow: "hidden",
      opacity: isOut ? 0 : 1,
      transform: isOut ? "scale(1.04)" : "scale(1)",
      transition: isOut ? "opacity 0.5s ease, transform 0.5s ease" : "none",
    }}>
      {/* Congrats phase */}
      <AnimatePresence>
        {phase === "congrats" && (
          <motion.div
            key="congrats"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 1.06 }}
            transition={{ duration: 0.5 }}
            style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "#fff",
              flexDirection: "column",
            }}
          >
            <Confetti />

            {/* Logo */}
            <div style={{ position: "absolute", top: 24, left: 28, display: "flex", alignItems: "center", gap: 8, zIndex: 10 }}>
              <div style={{
                width: 26, height: 26, flexShrink: 0,
                background: "#002eff",
                WebkitMask: "url('/logo.png') center/contain no-repeat",
                mask: "url('/logo.png') center/contain no-repeat",
              }} />
              <span style={{ fontSize: 12, letterSpacing: "0.2em", textTransform: "uppercase", color: "#002eff", fontWeight: 700, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>Astra</span>
            </div>

            <div style={{ position: "relative", zIndex: 10, textAlign: "center", padding: "0 32px" }}>
              {/* Trophy / celebration emoji */}
              <motion.div
                initial={{ scale: 0, rotate: -20 }}
                animate={{ scale: 1, rotate: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 18, delay: 0.1 }}
                style={{ fontSize: "clamp(56px, 10vw, 96px)", marginBottom: 24, lineHeight: 1 }}
              >
                🎉
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...FADE, delay: 0.25 }}
                style={{
                  fontSize: "clamp(32px, 6vw, 72px)",
                  fontWeight: 800,
                  color: "#002eff",
                  margin: 0,
                  lineHeight: 1.05,
                  letterSpacing: "-0.035em",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                }}
              >
                Congratulations,
                <br />
                <span style={{ color: "#111" }}>{displayName}!</span>
              </motion.h1>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ ...FADE, delay: 0.55 }}
                style={{
                  marginTop: 18, fontSize: 16,
                  color: "#6677bb",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                }}
              >
                Your launch is complete.
              </motion.p>
            </div>

            {/* Click to continue */}
            <motion.button
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.9 }}
              onClick={() => setPhase("launch")}
              style={{
                position: "absolute", bottom: 32,
                background: "transparent", border: "none",
                fontSize: 13, color: "#aab", cursor: "pointer",
                fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                letterSpacing: "0.04em",
              }}
            >
              tap to continue →
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Launch details phase */}
      <AnimatePresence>
        {phase === "launch" && (
          <motion.div
            key="launch"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "linear-gradient(135deg, #002eff 0%, #1a45ff 25%, #5df5e0 65%, #fefff6 100%)",
            }}
          >
            <AstraGradient />

            {/* Skip */}
            <button
              onClick={dismiss}
              style={{
                position: "absolute", top: 22, right: 24,
                background: "rgba(0,0,0,0.12)", border: "1px solid rgba(0,0,0,0.15)",
                borderRadius: 20, padding: "5px 14px", cursor: "pointer",
                fontSize: 12, color: "#002eff", fontWeight: 500, zIndex: 10,
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
                background: "#002eff",
                WebkitMask: "url('/logo.png') center/contain no-repeat",
                mask: "url('/logo.png') center/contain no-repeat",
              }} />
              <span style={{ fontSize: 12, letterSpacing: "0.2em", textTransform: "uppercase", color: "#002eff", fontWeight: 700, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>Astra</span>
            </div>

            {/* Main content */}
            <div style={{ position: "relative", zIndex: 2, width: "100%", maxWidth: 700, padding: "0 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>

              {/* Headline block */}
              <motion.div
                initial={{ opacity: 0, y: 32, filter: "blur(12px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ ...FADE, delay: 0.1 }}
                style={{ textAlign: "center" }}
              >
                {/* Badge */}
                <motion.div
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ ...FADE, delay: 0.05 }}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 7,
                    background: "rgba(0,0,0,0.08)", border: "1px solid rgba(0,0,0,0.12)",
                    borderRadius: 20, padding: "5px 14px", marginBottom: 28,
                    backdropFilter: "blur(8px)",
                  }}
                >
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#16a34a", boxShadow: "0 0 8px #16a34a", flexShrink: 0 }} />
                  <span style={{ fontSize: 11, color: "#002eff", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>
                    Launch complete
                  </span>
                </motion.div>

                <h1 style={{
                  fontSize: "clamp(38px, 7vw, 80px)",
                  fontWeight: 800,
                  color: "#002eff",
                  margin: 0,
                  lineHeight: 1.0,
                  letterSpacing: "-0.035em",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                }}>
                  {displayName}
                  <br />
                  <span style={{ color: "#111" }}>is live.</span>
                </h1>

                {stackName && (
                  <p style={{
                    marginTop: 18, fontSize: 15, color: "#3344aa", lineHeight: 1.6,
                    fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  }}>
                    Launched with the <strong style={{ color: "#002eff" }}>{stackName}</strong> stack
                  </p>
                )}
              </motion.div>

              {/* Stats row */}
              {(agentsRan > 0 || artifactsCreated > 0) && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...FADE, delay: 0.3 }}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: "rgba(255,255,255,0.65)", border: "1px solid rgba(255,255,255,0.9)",
                    borderRadius: 18, padding: "20px 8px", backdropFilter: "blur(12px)",
                    width: "100%",
                  }}
                >
                  {agentsRan > 0 && <Stat value={agentsRan} label="Agents ran" />}
                  {agentsRan > 0 && artifactsCreated > 0 && (
                    <div style={{ width: 1, height: 40, background: "rgba(0,46,255,0.15)" }} />
                  )}
                  {artifactsCreated > 0 && <Stat value={artifactsCreated} label="Deliverables" />}
                  {agentsRan > 0 && (
                    <>
                      <div style={{ width: 1, height: 40, background: "rgba(0,46,255,0.15)" }} />
                      <Stat value="Live" label="Status" />
                    </>
                  )}
                </motion.div>
              )}

              {/* CTA */}
              <motion.button
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...FADE, delay: 0.45 }}
                onClick={dismiss}
                style={{
                  background: "#002eff", color: "#fff",
                  border: "none", borderRadius: 14,
                  padding: "16px 48px", fontSize: 16, fontWeight: 700,
                  cursor: "pointer", letterSpacing: "-0.01em",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  boxShadow: "0 8px 32px rgba(0,46,255,0.35)",
                  transition: "transform 0.15s ease, box-shadow 0.15s ease",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 12px 40px rgba(0,46,255,0.5)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = ""; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 32px rgba(0,46,255,0.35)"; }}
              >
                Open workspace →
              </motion.button>

              {/* Fine print */}
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ ...FADE, delay: 0.65 }}
                style={{ fontSize: 12, color: "#6677bb", margin: 0, textAlign: "center", fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}
              >
                Your agents are continuing to work in the background
              </motion.p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
