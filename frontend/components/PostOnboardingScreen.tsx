"use client";

import { useEffect, useRef, useState } from "react";
import AstraGradient from "./AstraGradient";

export default function PostOnboardingScreen({
  name,
  onComplete,
}: {
  name: string;
  onComplete: () => void;
}) {
  const [phase, setPhase] = useState(0);
  const [pullingUp, setPullingUp] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const displayName = (name.split(" ")[0] || name).trim() || "Founder";

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 300);   // "Welcome, [Name]"
    const t2 = setTimeout(() => setPhase(2), 1400);  // tagline
    const t3 = setTimeout(() => {
      setPullingUp(true);
      onCompleteRef.current();
    }, 3200);
    return () => [t1, t2, t3].forEach(clearTimeout);
  }, []);

  return (
    <>
      <style>{`
        @keyframes pos-fade-up {
          from { opacity: 0; transform: translateY(22px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

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
          }}
        >
          {/* "Welcome, [Name]" — single line, appear together */}
          <h1
            style={{
              fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
              fontSize: "clamp(48px, 9vw, 88px)",
              fontWeight: 700,
              color: "#ffffff",
              lineHeight: 1,
              letterSpacing: "-0.03em",
              margin: "0 0 28px",
              opacity: phase >= 1 ? 1 : 0,
              animation: phase >= 1 ? "pos-fade-up 0.8s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
            }}
          >
            Welcome, {displayName}
          </h1>

          {/* Tagline */}
          <p
            style={{
              fontSize: "clamp(16px, 2.5vw, 22px)",
              fontWeight: 400,
              color: "rgba(255,255,255,0.65)",
              margin: 0,
              letterSpacing: "-0.01em",
              fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
              opacity: phase >= 2 ? 1 : 0,
              animation: phase >= 2 ? "pos-fade-up 0.65s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
            }}
          >
            It&rsquo;s time to change the world.
          </p>
        </div>
      </div>
    </>
  );
}
