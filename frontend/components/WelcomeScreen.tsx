"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import AstraGradient from "./AstraGradient";
import WordsPreloader from "./WordsPreloader";

export default function WelcomeScreen() {
  const router = useRouter();
  const [animate, setAnimate] = useState(false);

  return (
    <WordsPreloader onExitStart={() => setAnimate(true)}>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(28px); filter: blur(6px); }
          to   { opacity: 1; transform: translateY(0);    filter: blur(0px); }
        }
        .ws-logo {
          opacity: 0;
        }
        .ws-logo.go {
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.05s forwards;
        }
        .ws-h1 {
          opacity: 0;
        }
        .ws-h1.go {
          animation: ws-up 0.8s cubic-bezier(0.22,1,0.36,1) 0.18s forwards;
        }
        .ws-cta {
          opacity: 0;
        }
        .ws-cta.go {
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.34s forwards;
        }
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
        .ws-btn:hover {
          opacity: 0.88;
          transform: translateY(-1px);
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
        overflow: "hidden",
        background: "#001aff",
      }}>
        <AstraGradient />

        <div style={{
          position: "relative",
          zIndex: 2,
          textAlign: "center",
          padding: "0 32px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 32,
        }}>
          <div className={`ws-logo${animate ? " go" : ""}`}>
            <Image
              src="/logo.png"
              alt="Astra"
              width={72}
              height={72}
              style={{ filter: "brightness(0)", objectFit: "contain" }}
            />
          </div>

          <h1
            className={`ws-h1${animate ? " go" : ""}`}
            style={{
              fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
              fontSize: "clamp(48px, 9vw, 80px)",
              fontWeight: 700,
              color: "#0a0a0a",
              letterSpacing: "-0.02em",
              lineHeight: 1.05,
              margin: 0,
            }}
          >
            Welcome to Astra
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
