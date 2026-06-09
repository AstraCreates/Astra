"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

const WORDS = [
  "Hello",
  "Hola",
  "Bonjour",
  "こんにちは",
  "你好",
  "Ciao",
  "Hej",
  "مرحبا",
];

// First word lingers, rest cycle fast
const FIRST_HOLD = 900;
const REST_HOLD  = 320;

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
      }, 400);
      return () => clearTimeout(finish);
    }

    const hold = index === 0 ? FIRST_HOLD : REST_HOLD;
    const t = setTimeout(() => setIndex((p) => p + 1), hold);
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
                initial={{ opacity: 0, y: index === 0 ? 20 : 10, filter: "blur(8px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{
                  opacity: 0,
                  y: index === 0 ? -14 : -8,
                  filter: "blur(6px)",
                  transition: { duration: index === 0 ? 0.32 : 0.18, ease: [0.22, 1, 0.36, 1] },
                }}
                transition={{
                  duration: index === 0 ? 0.55 : 0.22,
                  ease: [0.22, 1, 0.36, 1],
                }}
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
