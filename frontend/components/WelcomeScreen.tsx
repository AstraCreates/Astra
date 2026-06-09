"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";

const PHRASES = [
  "Welcome to Astra!",
  "¡Bienvenido a Astra!",
  "Bienvenue chez Astra !",
  "Astraへようこそ！",
  "欢迎来到Astra！",
  "Добро пожаловать в Astra!",
];

const HOLD = 3000;

export default function WelcomeScreen() {
  const router = useRouter();
  const [covered, setCovered] = useState(true);
  const [idx, setIdx] = useState(0);

  // Let shader preload behind overlay, then fade it away
  useEffect(() => {
    const t = setTimeout(() => setCovered(false), 800);
    return () => clearTimeout(t);
  }, []);

  // Cycle phrases once revealed
  useEffect(() => {
    if (covered) return;
    const t = setTimeout(() => setIdx((i) => (i + 1) % PHRASES.length), HOLD);
    return () => clearTimeout(t);
  }, [covered, idx]);

  const content = (
    <>
      <style>{`
        .ws-btn {
          padding: 12px 36px;
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

      {/* Renders on document.body via portal — root stacking context, above everything */}
      <div style={{ position: "fixed", inset: 0, zIndex: 9999 }}>

        {/* Gradient preloads behind the cover */}
        <div style={{ position: "absolute", inset: 0 }}>
          <AstraGradient />
        </div>

        {/* Content */}
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
          gap: 20,
        }}>
          <Image
            src="/logo.png"
            alt="Astra"
            width={60}
            height={60}
            style={{ objectFit: "contain", filter: "brightness(0)" }}
          />

          {/* Fixed-height container so button doesn't shift */}
          <div style={{
            position: "relative",
            width: "100%",
            maxWidth: 860,
            height: "clamp(50px, 8vw, 90px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <AnimatePresence>
              <motion.h1
                key={idx}
                initial={{ opacity: 0, y: 22, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -18, filter: "blur(6px)" }}
                transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  position: "absolute",
                  width: "100%",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(32px, 5.5vw, 62px)",
                  fontWeight: 700,
                  color: "#0a0a0a",
                  letterSpacing: "-0.02em",
                  lineHeight: 1.05,
                  margin: 0,
                }}
              >
                {PHRASES[idx]}
              </motion.h1>
            </AnimatePresence>
          </div>

          <button className="ws-btn" onClick={() => router.push("/onboarding")}>
            Get Started
          </button>
        </div>

        {/* White cover fades out to reveal preloaded gradient */}
        <AnimatePresence>
          {covered && (
            <motion.div
              key="cover"
              style={{ position: "absolute", inset: 0, background: "#FEFFF6", zIndex: 10 }}
              exit={{ opacity: 0, transition: { duration: 0.7, ease: "easeInOut" } }}
            />
          )}
        </AnimatePresence>
      </div>
    </>
  );

  // Portal to document.body bypasses all stacking context issues.
  // Return null on SSR — Suspense fallback in page.tsx covers that case.
  if (typeof document === "undefined") return null;
  return createPortal(content, document.body);
}
