"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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

  useEffect(() => {
    const t = setTimeout(() => setCovered(false), 700);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (covered) return;
    const t = setTimeout(() => setIdx((i) => (i + 1) % PHRASES.length), HOLD);
    return () => clearTimeout(t);
  }, [covered, idx]);

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

      <div style={{ position: "fixed", inset: 0, zIndex: 200 }}>
        <div style={{ position: "absolute", inset: 0 }}>
          <AstraGradient />
        </div>

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
            gap: 48,
          }}
        >
          {/* Fixed-height title container so button doesn't move */}
          <div
            style={{
              position: "relative",
              width: "100%",
              maxWidth: 860,
              height: "clamp(60px, 9vw, 110px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AnimatePresence>
              <motion.h1
                key={idx}
                initial={{ opacity: 0, y: 24, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -20, filter: "blur(6px)" }}
                transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  position: "absolute",
                  width: "100%",
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
            </AnimatePresence>
          </div>

          <button className="ws-btn" onClick={() => router.push("/onboarding")}>
            Get Started
          </button>
        </div>

        <AnimatePresence>
          {covered && (
            <motion.div
              style={{ position: "absolute", inset: 0, background: "#FEFFF6", zIndex: 10 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.65, ease: "easeInOut" }}
            />
          )}
        </AnimatePresence>
      </div>
    </>
  );
}
