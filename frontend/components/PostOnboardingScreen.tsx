"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";

const TRANS = { duration: 0.65, ease: [0.22, 1, 0.36, 1] as const };

export default function PostOnboardingScreen({
  name,
  onComplete,
}: {
  name: string;
  onComplete: () => void;
}) {
  const [showName, setShowName] = useState(false);
  const [showTagline, setShowTagline] = useState(false);
  const [pullingUp, setPullingUp] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const displayName = (name.split(" ")[0] || name).trim() || "Founder";

  useEffect(() => {
    // "Welcome, [Name]" appears at 300ms
    const t1 = setTimeout(() => setShowName(true), 300);
    // "It's time to change the world." appears 4s after name
    const t2 = setTimeout(() => setShowTagline(true), 4300);
    // Pull up + navigate 2.2s after tagline appears
    const t3 = setTimeout(() => {
      setPullingUp(true);
      onCompleteRef.current();
    }, 6800);
    return () => [t1, t2, t3].forEach(clearTimeout);
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        background: "#000814",
        transform: pullingUp ? "translateY(-100%)" : "translateY(0)",
        transition: pullingUp
          ? "transform 0.9s cubic-bezier(0.76, 0, 0.24, 1)"
          : "none",
      }}
    >
      <AstraGradient />

      <div
        style={{
          position: "relative",
          zIndex: 2,
          textAlign: "center",
          padding: "0 40px",
          userSelect: "none",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 28,
        }}
      >
        {/* "Welcome, [Name]" */}
        <div style={{ position: "relative", minHeight: "clamp(56px, 10vw, 96px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <AnimatePresence>
            {showName && (
              <motion.h1
                key="name"
                initial={{ opacity: 0, y: 22, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={TRANS}
                style={{
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(48px, 9vw, 88px)",
                  fontWeight: 700,
                  color: "#ffffff",
                  lineHeight: 1,
                  letterSpacing: "-0.03em",
                  margin: 0,
                }}
              >
                Welcome, {displayName}
              </motion.h1>
            )}
          </AnimatePresence>
        </div>

        {/* "It's time to change the world." */}
        <div style={{ position: "relative", minHeight: "clamp(40px, 6vw, 64px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <AnimatePresence>
            {showTagline && (
              <motion.p
                key="tagline"
                initial={{ opacity: 0, y: 22, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={TRANS}
                style={{
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(32px, 5.5vw, 60px)",
                  fontWeight: 600,
                  color: "rgba(255,255,255,0.8)",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.1,
                  margin: 0,
                }}
              >
                It&rsquo;s time to change the world.
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
