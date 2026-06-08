"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import AstraGradient from "./AstraGradient";

export default function WelcomeScreen() {
  const router = useRouter();

  return (
    <>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(24px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .ws-logo {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.1s forwards;
        }
        .ws-h1 {
          opacity: 0;
          animation: ws-up 0.8s cubic-bezier(0.22,1,0.36,1) 0.3s forwards;
        }
        .ws-cta {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.58s forwards;
        }
        .ws-btn {
          padding: 13px 40px;
          font-size: 13px;
          font-weight: 500;
          letter-spacing: 0.02em;
          color: #002EFF;
          background: #ffffff;
          border: none;
          border-radius: 100px;
          cursor: pointer;
          transition: opacity 0.18s ease, transform 0.18s ease;
          font-family: var(--font-dm-sans), "DM Sans", sans-serif;
        }
        .ws-btn:hover {
          opacity: 0.88;
          transform: translateY(-1px);
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        position: "relative", overflow: "hidden",
        background: "#001aff",
      }}>
        <AstraGradient />

        <div style={{ position: "relative", zIndex: 2, textAlign: "center", padding: "0 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 32 }}>
          <div className="ws-logo">
            <Image src="/logo.png" alt="Astra" width={72} height={72} style={{ filter: "brightness(0) invert(1)", objectFit: "contain" }} />
          </div>

          <h1 className="ws-h1" style={{
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            fontSize: "clamp(48px, 9vw, 80px)",
            fontWeight: 700,
            color: "#ffffff",
            letterSpacing: "-0.02em",
            lineHeight: 1.05,
            margin: 0,
          }}>
            Welcome to Astra
          </h1>

          <div className="ws-cta">
            <button className="ws-btn" onClick={() => router.push("/onboarding")}>
              Get Started
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
