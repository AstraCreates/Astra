"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

// Correct punctuation per language
const WORDS = [
  "Hello!",       // English
  "¡Hola!",       // Spanish
  "Bonjour !",    // French (space before !)
  "Ciao!",        // Italian
  "Olá!",         // Portuguese
  "Hallo!",       // German
  "こんにちは！",   // Japanese (full-width)
  "你好！",        // Chinese (full-width)
  "안녕하세요!",   // Korean
  "Привет!",      // Russian — fast
  "مرحباً!",      // Arabic — fast
];

// Geometric progression ~×0.84 per step: 1200 → 220ms, no plateau
const HOLDS = [1200, 1000, 850, 720, 610, 510, 430, 360, 300, 255, 220];

interface Props {
  children: React.ReactNode;
  onExitStart?: () => void;
}

export default function WordsPreloader({ children, onExitStart }: Props) {
  const [index, setIndex] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    document.body.style.overflow = "hidden";

    if (index >= WORDS.length - 1) {
      const finish = setTimeout(() => {
        onExitStart?.();
        setDone(true);
        setTimeout(() => { document.body.style.overflow = ""; }, 900);
      }, 300);
      return () => clearTimeout(finish);
    }

    const t = setTimeout(() => setIndex((p) => p + 1), HOLDS[index] ?? 200);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  // Animate duration also shrinks as index grows
  const progress = index / (WORDS.length - 1);
  const enterDur = 0.48 - progress * 0.34; // 0.48 → 0.14
  const exitDur  = 0.28 - progress * 0.18; // 0.28 → 0.10

  return (
    <>
      {children}

      <AnimatePresence>
        {!done && (
          <motion.div
            key="preloader"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 9999,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "#FEFFF6",
            }}
            exit={{
              clipPath: "inset(0 0 100% 0)",
              transition: { duration: 0.85, ease: [0.76, 0, 0.24, 1] },
            }}
          >
            <motion.div
              style={{
                position: "absolute",
                bottom: "10%",
                left: "50%",
                transform: "translateX(-50%)",
                width: 5,
                height: 5,
                background: "#002EFF",
                borderRadius: "50%",
              }}
              animate={{ opacity: [0.25, 1, 0.25], scale: [0.8, 1.2, 0.8] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            />

            <AnimatePresence mode="wait">
              <motion.span
                key={index}
                initial={{ opacity: 0, y: 16, filter: "blur(8px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -14, filter: "blur(6px)" }}
                transition={{ duration: enterDur, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  position: "absolute",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(2.6rem, 5vw, 4.5rem)",
                  fontWeight: 500,
                  letterSpacing: "-0.04em",
                  color: "#111018",
                  userSelect: "none",
                  lineHeight: 1,
                }}
              >
                {WORDS[index]}
              </motion.span>
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
