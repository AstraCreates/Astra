"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

const WORDS = [
  "Hello",
  "Bonjour",
  "Hola",
  "Ciao",
  "Olá",
  "Hallo",
  "Hej",
  "こんにちは",
  "안녕하세요",
  "你好",
  "ਸਤ ਸ੍ਰੀ ਅਕਾਲ",
];

export default function WordsPreloader({ children }: { children: React.ReactNode }) {
  const [index, setIndex] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    document.body.style.overflow = "hidden";

    if (index >= WORDS.length - 1) {
      const finish = setTimeout(() => {
        setDone(true);
        setTimeout(() => { document.body.style.overflow = ""; }, 900);
      }, 700);
      return () => clearTimeout(finish);
    }

    const t = setTimeout(() => setIndex((p) => p + 1), 850);
    return () => clearTimeout(t);
  }, [index]);

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
              background: "var(--bg, #FEFFF6)",
            }}
            initial={{ opacity: 1 }}
            exit={{
              clipPath: "inset(0 0 100% 0)",
              transition: { duration: 0.9, ease: [0.76, 0, 0.24, 1] },
            }}
          >
            {/* Subtle blue accent dot — Astra brand */}
            <motion.div
              style={{
                position: "absolute",
                bottom: "10%",
                left: "50%",
                transform: "translateX(-50%)",
                width: 4,
                height: 4,
                background: "var(--blue, #002EFF)",
                borderRadius: "50%",
              }}
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            />

            <AnimatePresence mode="wait">
              <motion.span
                key={index}
                initial={{ opacity: 0, y: 18, filter: "blur(8px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -18, filter: "blur(8px)" }}
                transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
                style={{
                  position: "absolute",
                  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                  fontSize: "clamp(2.6rem, 5vw, 4.5rem)",
                  fontWeight: 500,
                  letterSpacing: "-0.04em",
                  color: "var(--astra-ink, #111018)",
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
