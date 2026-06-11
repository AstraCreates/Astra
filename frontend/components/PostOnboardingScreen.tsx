"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";

const ENTER = { opacity: 1, y: 0, filter: "blur(0px)" } as const;
const EXIT  = { opacity: 0, y: -18, filter: "blur(6px)" } as const;
const INIT  = { opacity: 0, y: 22,  filter: "blur(10px)" } as const;
const TRANS = { duration: 0.6, ease: [0.22, 1, 0.36, 1] as const };

const TEXT_STYLE = {
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  fontSize: "clamp(36px, 6vw, 72px)",
  fontWeight: 700,
  color: "#0a0a0a",
  lineHeight: 1.05,
  letterSpacing: "-0.025em",
  margin: 0,
  position: "absolute" as const,
  width: "100%",
  textAlign: "center" as const,
};

export default function PostOnboardingScreen({
  name,
  onComplete,
}: {
  name: string;
  onComplete: () => void;
}) {
  const [phrase, setPhrase] = useState<"welcome" | "tagline" | null>(null);
  const [pullingUp, setPullingUp] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const displayName = (name.split(" ")[0] || name).trim() || "Founder";

  useEffect(() => {
    const t1 = setTimeout(() => setPhrase("welcome"), 300);
    // Swap to tagline 2.5s after welcome appears
    const t2 = setTimeout(() => setPhrase("tagline"), 2800);
    // Start pull-up 4.2s after tagline appears (tagline stays for ~4s)
    const t3 = setTimeout(() => setPullingUp(true), 7000);
    // Navigate AFTER pull-up animation finishes (0.9s)
    const t4 = setTimeout(() => onCompleteRef.current(), 7900);
    return () => [t1, t2, t3, t4].forEach(clearTimeout);
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        /* Static gradient shows instantly; shader overlays once loaded */
        background: "linear-gradient(135deg, #002eff 0%, #1a45ff 25%, #5df5e0 65%, #fefff6 100%)",
        transform: pullingUp ? "translateY(-100%)" : "translateY(0)",
        transition: pullingUp
          ? "transform 0.9s cubic-bezier(0.76, 0, 0.24, 1)"
          : "none",
      }}
    >
      <AstraGradient />

      {/* Fixed-height container so layout doesn't shift on swap */}
      <div
        style={{
          position: "relative",
          zIndex: 2,
          width: "100%",
          maxWidth: 900,
          height: "clamp(60px, 10vw, 100px)",
          padding: "0 40px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          userSelect: "none",
        }}
      >
        <AnimatePresence mode="wait">
          {phrase === "welcome" && (
            <motion.h1
              key="welcome"
              style={TEXT_STYLE}
              initial={INIT}
              animate={ENTER}
              exit={EXIT}
              transition={TRANS}
            >
              Welcome, {displayName}
            </motion.h1>
          )}
          {phrase === "tagline" && (
            <motion.h1
              key="tagline"
              style={TEXT_STYLE}
              initial={INIT}
              animate={ENTER}
              exit={EXIT}
              transition={TRANS}
            >
              It&rsquo;s time to change the world.
            </motion.h1>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
