"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";

const CSS_GRADIENT =
  "radial-gradient(ellipse at 30% 40%, #002EFF 0%, #004FCC 40%, #7CFFC6 75%, #FEFFF6 100%)";

// Foreign langs first — settle on English
const PHRASES = [
  "Bienvenido a Astra",
  "Bienvenue chez Astra",
  "Astraへようこそ",
  "欢迎来到Astra",
  "Добро пожаловать в Astra",
  "Welcome to Astra",
];

// Hold per phrase before advancing (last phrase stays — 0 unused)
const HOLDS = [600, 480, 380, 300, 240, 0];

export default function WelcomeScreen() {
  const router = useRouter();
  const [phase, setPhase] = useState<"blank" | "reveal" | "cycle" | "done">("blank");
  const [idx, setIdx] = useState(0);
  const [showCta, setShowCta] = useState(false);

  // blank → reveal (350ms) → cycle starts after gradient finishes (350+850ms)
  useEffect(() => {
    const t1 = setTimeout(() => setPhase("reveal"), 350);
    const t2 = setTimeout(() => setPhase("cycle"), 1200);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  // Advance phrase index during cycle
  useEffect(() => {
    if (phase !== "cycle") return;
    if (idx >= PHRASES.length - 1) {
      setPhase("done");
      const t = setTimeout(() => setShowCta(true), 550);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setIdx((i) => i + 1), HOLDS[idx]);
    return () => clearTimeout(t);
  }, [phase, idx]);

  const isLast = idx === PHRASES.length - 1;
  // Enter animation: fast for foreign, slow + expressive for final English
  const enterDur = isLast ? 0.7 : Math.max(0.18, 0.32 - (idx / (PHRASES.length - 2)) * 0.14);

  return (
    <>
      <style>{`
        .ws-btn {
          padding: 13px 40px;
          font-size: 13px;
          font-weight: 600;
          letter-spacing: 0.02em;
          color: #ffffff;
          background: #0a0a0a;
          border: none;
          border-radius: 100px;
          cursor: pointer;
          transition: opacity 0.18s ease, transform 0.18s ease;
          font-family: var(--font-geist-sans), "Geist", sans-serif;
        }
        .ws-btn:hover { opacity: 0.88; transform: translateY(-1px); }
      `}</style>

      {/* Base: always covers full viewport */}
      <div style={{ position: "fixed", inset: 0, zIndex: 200, background: "#FEFFF6" }}>

        {/* Gradient wipes up from bottom */}
        <motion.div
          style={{
            position: "absolute",
            inset: 0,
            clipPath: "inset(100% 0 0 0)",
            background: CSS_GRADIENT,
          }}
          animate={phase !== "blank" ? { clipPath: "inset(0% 0 0 0)" } : {}}
          transition={{ duration: 0.85, ease: [0.76, 0, 0.24, 1] }}
        >
          <AstraGradient />
        </motion.div>

        {/* Content */}
        <div
          style={{
            position: "relative",
            zIndex: 2,
            height: "100%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            padding: "0 32px",
            gap: 36,
          }}
        >
          <AnimatePresence>
            {(phase === "cycle" || phase === "done") && (
              <motion.h1
                key={idx}
                initial={{ opacity: 0, y: 22, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -16, filter: "blur(6px)", transition: { duration: 0.2 } }}
                transition={{ duration: enterDur, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(36px, 6vw, 68px)",
                  fontWeight: 700,
                  color: "#0a0a0a",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.05,
                  margin: 0,
                }}
              >
                {PHRASES[idx]}
              </motion.h1>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {showCta && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
              >
                <button className="ws-btn" onClick={() => router.push("/onboarding")}>
                  Get Started
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </>
  );
}
