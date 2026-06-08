"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";

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
        .ws-grain {
          position: absolute;
          inset: 0;
          pointer-events: none;
          z-index: 1;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 80 80' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.55' numOctaves='1' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          background-repeat: repeat;
          background-size: 180px 180px;
          image-rendering: pixelated;
          opacity: 0.42;
          mix-blend-mode: overlay;
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        position: "relative", overflow: "hidden",
        background: "linear-gradient(145deg, #002EFF 0%, #0040FF 25%, #1a6aff 55%, #5DFFB8 85%, #7CFFC6 100%)",
      }}>
        <div className="ws-grain" />

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
