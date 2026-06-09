"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { motion } from "framer-motion";
import AstraGradient from "./AstraGradient";
import WordsPreloader from "./WordsPreloader";

const CSS_GRADIENT = "radial-gradient(ellipse at 30% 40%, #002EFF 0%, #004FCC 40%, #7CFFC6 75%, #FEFFF6 100%)";

export default function WelcomeScreen() {
  const router = useRouter();
  const [animate, setAnimate] = useState(false);

  return (
    <WordsPreloader onExitStart={() => setAnimate(true)}>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(24px); filter: blur(6px); }
          to   { opacity: 1; transform: translateY(0);    filter: blur(0px); }
        }
        .ws-logo { opacity: 0; }
        .ws-logo.go { animation: ws-up 0.65s cubic-bezier(0.22,1,0.36,1) 0.55s forwards; }
        .ws-h1  { opacity: 0; }
        .ws-h1.go  { animation: ws-up 0.75s cubic-bezier(0.22,1,0.36,1) 0.7s forwards; }
        .ws-cta { opacity: 0; }
        .ws-cta.go { animation: ws-up 0.65s cubic-bezier(0.22,1,0.36,1) 0.88s forwards; }
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

      {/*
        Outer div: always covers full viewport (no clip-path) — blocks sidebar bleed-through.
        Shows CSS gradient as fallback while shader boots.
      */}
      <div style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: CSS_GRADIENT,
        overflow: "hidden",
      }}>
        {/* Shader gradient: expands from center via clip-path on this inner layer */}
        <motion.div
          style={{
            position: "absolute",
            inset: 0,
            clipPath: "circle(0% at 50% 50%)",
          }}
          animate={animate ? { clipPath: "circle(150% at 50% 50%)" } : {}}
          transition={{ duration: 1.05, ease: [0.65, 0, 0.35, 1], delay: 0.2 }}
        >
          <AstraGradient />
        </motion.div>

        {/* Content always on top */}
        <div style={{
          position: "relative",
          zIndex: 2,
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: "0 32px",
          gap: 32,
        }}>
          <div className={`ws-logo${animate ? " go" : ""}`}>
            <Image src="/logo.png" alt="Astra" width={72} height={72} style={{ filter: "brightness(0)", objectFit: "contain" }} />
          </div>

          <h1 className={`ws-h1${animate ? " go" : ""}`} style={{
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            fontSize: "clamp(48px, 9vw, 80px)",
            fontWeight: 700,
            color: "#0a0a0a",
            letterSpacing: "-0.02em",
            lineHeight: 1.05,
            margin: 0,
          }}>
            Welcome to Astra!
          </h1>

          <div className={`ws-cta${animate ? " go" : ""}`}>
            <button className="ws-btn" onClick={() => router.push("/onboarding")}>
              Get Started
            </button>
          </div>
        </div>
      </div>
    </WordsPreloader>
  );
}
