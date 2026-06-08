"use client";

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
          color: #0437ff;
          background: #ffffff;
          border: 1px solid rgba(255,255,255,.74);
          cursor: pointer;
          transition: opacity 0.18s ease, transform 0.18s ease;
          font-family: var(--font-dm-sans), "DM Sans", sans-serif;
          box-shadow: 0 0 26px rgba(255,255,255,.22);
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
        .ws-orbits {
          position: absolute;
          inset: 0;
          z-index: 1;
          pointer-events: none;
          opacity: .86;
          background:
            radial-gradient(104% 62% at 99% 16%, transparent 44%, rgba(255,255,255,.9) 44.16% 44.42%, transparent 44.66%),
            radial-gradient(120% 78% at 92% 12%, transparent 39%, rgba(255,255,255,.82) 39.16% 39.42%, transparent 39.66%),
            radial-gradient(90% 66% at 72% 49%, transparent 46%, rgba(255,255,255,.74) 46.14% 46.42%, transparent 46.68%),
            radial-gradient(148% 44% at -4% 100%, transparent 57%, rgba(255,255,255,.78) 57.12% 57.34%, transparent 57.62%);
          filter: drop-shadow(0 0 9px rgba(255,255,255,.68));
        }
        .ws-logo-mark {
          position: relative;
          width: 80px;
          height: 80px;
          color: #fff;
          filter: drop-shadow(0 0 18px rgba(255,255,255,.8));
        }
        .ws-logo-mark::before,
        .ws-logo-mark::after {
          content: "";
          position: absolute;
          border: 5px solid currentColor;
        }
        .ws-logo-mark::before {
          inset: 8% 18% 26% 18%;
          border-bottom-color: transparent;
          border-left-color: transparent;
          transform: rotate(-45deg);
        }
        .ws-logo-mark::after {
          inset: 32% 14% 8% 14%;
          border-top-color: transparent;
          border-right-color: transparent;
          transform: rotate(45deg);
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        position: "relative", overflow: "hidden",
        background: "radial-gradient(ellipse at 86% 10%, rgba(255,255,255,.28), transparent 15%), radial-gradient(ellipse at 86% 80%, rgba(92,255,226,.38), transparent 30%), radial-gradient(ellipse at 16% 84%, rgba(255,71,231,.20), transparent 26%), linear-gradient(180deg, #02040c 0%, #0020f4 38%, #0b49ff 66%, #34edff 100%)",
      }}>
        <div className="ws-grain" />
        <div className="ws-orbits" />

        <div style={{ position: "relative", zIndex: 2, textAlign: "center", padding: "0 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 32 }}>
          <div className="ws-logo">
            <div className="ws-logo-mark" aria-label="Astra" />
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
