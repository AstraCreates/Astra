"use client";

import { useRouter } from "next/navigation";

export default function WelcomeScreen() {
  const router = useRouter();

  return (
    <>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .ws-h1 {
          opacity: 0;
          animation: ws-up 0.8s cubic-bezier(0.22,1,0.36,1) 0.2s forwards;
          will-change: opacity, transform;
        }
        .ws-cta {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.6s forwards;
          will-change: opacity, transform;
        }
        .ws-btn {
          padding: 14px 40px;
          font-size: 14px;
          font-weight: 600;
          font-family: 'Chakra Petch', sans-serif;
          letter-spacing: 0.05em;
          color: rgba(255,255,255,0.88);
          background: rgba(59,130,246,0.1);
          border: 1.5px solid rgba(59,130,246,0.5);
          border-radius: 10px;
          cursor: pointer;
          transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
        }
        .ws-btn:hover {
          background: rgba(59,130,246,0.22);
          border-color: rgba(59,130,246,0.85);
          color: #fff;
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "#05070f",
      }}>
        <div style={{ textAlign: "center", padding: "0 24px" }}>
          <h1 className="ws-h1" style={{
            fontFamily: "'Chakra Petch', sans-serif",
            fontSize: "clamp(44px, 8vw, 74px)",
            fontWeight: 700,
            color: "#ffffff",
            letterSpacing: "-0.02em",
            lineHeight: 1.06,
            margin: "0 0 40px",
          }}>
            Welcome to<br />
            <span style={{ color: "rgba(59,130,246,1)" }}>Astra</span>
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
