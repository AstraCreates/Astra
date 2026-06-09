"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

const WORDS = [
  "Hello",
  "Hola",
  "こんにちは",
  "Bonjour",
  "你好",
];

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
      }, 650);
      return () => clearTimeout(finish);
    }

    const t = setTimeout(() => setIndex((p) => p + 1), 800);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
              background: "#FEFFF6",
            }}
            initial={{ clipPath: "inset(0 0 0% 0)" }}
            exit={{
              clipPath: "inset(0 0 100% 0)",
              transition: { duration: 0.85, ease: [0.76, 0, 0.24, 1] },
            }}
          >
            {/* Blue pulse dot */}
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
                initial={{ opacity: 0, y: 16, filter: "blur(10px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -16, filter: "blur(10px)" }}
                transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
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
