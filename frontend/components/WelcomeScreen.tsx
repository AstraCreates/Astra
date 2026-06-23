"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import AstraGradient from "./AstraGradient";
import { desktopDownloadHref } from "@/lib/desktop-download";

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
        .ws-btn-secondary {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 12px 28px;
          font-size: 13px;
          font-weight: 600;
          letter-spacing: 0.01em;
          color: #ffffff;
          background: rgba(0,0,0,0.42);
          border: 1px solid rgba(255,255,255,0.22);
          border-radius: 100px;
          text-decoration: none;
          backdrop-filter: blur(18px);
          -webkit-backdrop-filter: blur(18px);
          box-shadow: 0 2px 12px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.08);
          transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
          font-family: var(--font-geist-sans), "Geist", sans-serif;
        }
        .ws-btn-secondary:hover {
          transform: translateY(-1px);
          background: rgba(0,0,0,0.58);
          border-color: rgba(255,255,255,0.35);
          box-shadow: 0 4px 20px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.1);
        }
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

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
            }}
          >
            <button className="ws-btn" onClick={() => router.push("/onboarding")}>
              Get Started
            </button>
            <a className="ws-btn-secondary" href={desktopDownloadHref}>
              <svg width="14" height="17" viewBox="0 0 14 17" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M13.014 12.53c-.29.636-.636 1.221-1.04 1.755-.546.72-1.003 1.22-1.365 1.498-.546.463-1.13.7-1.755.715-.45 0-.99-.128-1.617-.387-.628-.259-1.207-.387-1.737-.387-.556 0-1.151.128-1.789.387-.64.259-1.154.394-1.546.408-.6.025-1.199-.217-1.797-.729-.39-.303-.865-.82-1.424-1.554C.335 13.457-.11 12.3-.11 11.1c0-1.27.282-2.365.848-3.28A4.926 4.926 0 0 1 2.55 5.944a4.708 4.708 0 0 1 2.365-.672c.463 0 1.072.143 1.83.424.756.282 1.24.425 1.452.425.158 0 .695-.167 1.606-.5.86-.311 1.586-.44 2.181-.39 1.612.13 2.822.763 3.628 1.903-1.44.873-2.152 2.094-2.138 3.66.013 1.22.454 2.235 1.32 3.042.393.372.831.66 1.22.845l-.001-.151ZM9.856.76c0 .957-.349 1.85-1.045 2.677C8.1 4.33 7.11 4.79 6.036 4.707a3.364 3.364 0 0 1-.025-.415c0-.918.4-1.9 1.11-2.703.354-.407.806-.745 1.354-1.014C9.022.306 9.543.155 10.03.125c.017.145.025.29.025.435h-.199Z" fill="currentColor"/>
              </svg>
              Download for macOS
            </a>
          </div>
        </div>

        {/* White cover fades out to reveal preloaded gradient */}
        <AnimatePresence>
          {covered && (
            <motion.div
              key="cover"
              style={{ position: "absolute", inset: 0, background: "#F3F4F7", zIndex: 10 }}
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
