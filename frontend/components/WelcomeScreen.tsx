"use client";

import { useRouter } from "next/navigation";

function AstraTriquetra({ size = 56 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="50" cy="50" rx="3.5" ry="44" stroke="white" strokeWidth="8.5"/>
      <ellipse cx="50" cy="50" rx="3.5" ry="44" transform="rotate(120 50 50)" stroke="white" strokeWidth="8.5"/>
      <ellipse cx="50" cy="50" rx="3.5" ry="44" transform="rotate(240 50 50)" stroke="white" strokeWidth="8.5"/>
    </svg>
  );
}

export default function WelcomeScreen() {
  const router = useRouter();

  return (
    <>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(22px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .ws-logo {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.1s forwards;
          will-change: opacity, transform;
        }
        .ws-h1 {
          opacity: 0;
          animation: ws-up 0.8s cubic-bezier(0.22,1,0.36,1) 0.28s forwards;
          will-change: opacity, transform;
        }
        .ws-cta {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.62s forwards;
          will-change: opacity, transform;
        }
        .ws-btn {
          padding: 13px 38px;
          font-size: 13px;
          font-weight: 600;
          letter-spacing: 0.04em;
          color: rgba(255,255,255,0.90);
          background: rgba(0,46,255,0.15);
          border: 1.5px solid rgba(0,46,255,0.55);
          border-radius: 10px;
          cursor: pointer;
          transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
        }
        .ws-btn:hover {
          background: rgba(0,46,255,0.28);
          border-color: rgba(0,46,255,0.9);
          color: #fff;
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "linear-gradient(160deg, #020511 0%, #001040 42%, #000d35 65%, #020714 100%)",
      }}>
        <div style={{ textAlign: "center", padding: "0 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 28 }}>
          <div className="ws-logo">
            <AstraTriquetra size={64} />
          </div>

          <h1 className="ws-h1" style={{
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            fontSize: "clamp(42px, 8vw, 72px)",
            fontWeight: 700,
            color: "#ffffff",
            letterSpacing: "-0.02em",
            lineHeight: 1.06,
            margin: 0,
          }}>
            Welcome to<br />
            <span style={{ color: "#002EFF" }}>Astra</span>
          </h1>

          <div className="ws-cta">
            <button className="ws-btn" onClick={() => router.push("/onboarding")}>
              Get Started →
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
