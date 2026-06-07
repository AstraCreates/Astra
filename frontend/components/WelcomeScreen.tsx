"use client";

import { useRouter } from "next/navigation";

export default function WelcomeScreen() {
  const router = useRouter();

  return (
    <>
      <style>{`
        @keyframes ws-up {
          from { opacity: 0; transform: translateY(22px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes ws-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes ws-glow {
          0%, 100% { text-shadow: 0 0 40px rgba(59,130,246,0.45), 0 0 80px rgba(59,130,246,0.18); }
          50%       { text-shadow: 0 0 70px rgba(59,130,246,0.75), 0 0 140px rgba(59,130,246,0.3); }
        }
        @keyframes ws-float {
          0%, 100% { transform: translateY(0px); }
          50%       { transform: translateY(-22px); }
        }
        @keyframes ws-float-r {
          0%, 100% { transform: translateY(0px); }
          50%       { transform: translateY(22px); }
        }
        @keyframes ws-pulse-ring {
          0%   { box-shadow: 0 0 0 0 rgba(59,130,246,0.45); }
          70%  { box-shadow: 0 0 0 10px rgba(59,130,246,0); }
          100% { box-shadow: 0 0 0 0 rgba(59,130,246,0); }
        }
        .ws-mark {
          opacity: 0;
          animation: ws-in 0.7s cubic-bezier(0.22,1,0.36,1) 0.1s forwards;
          will-change: opacity;
        }
        .ws-h1 {
          opacity: 0;
          animation:
            ws-up 0.75s cubic-bezier(0.22,1,0.36,1) 0.4s forwards,
            ws-glow 4s ease-in-out 1.8s infinite;
          will-change: opacity, transform;
        }
        .ws-sub {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 0.75s forwards;
          will-change: opacity, transform;
        }
        .ws-cta {
          opacity: 0;
          animation: ws-up 0.7s cubic-bezier(0.22,1,0.36,1) 1.1s forwards;
          will-change: opacity, transform;
        }
        .ws-footer {
          opacity: 0;
          animation: ws-in 1s ease 1.6s forwards;
          will-change: opacity;
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
          animation: ws-pulse-ring 2.4s ease-out 2s infinite;
        }
        .ws-btn:hover {
          background: rgba(59,130,246,0.22);
          border-color: rgba(59,130,246,0.85);
          color: #fff;
        }
        .ws-orb1 {
          animation: ws-float 9s ease-in-out infinite;
          will-change: transform;
        }
        .ws-orb2 {
          animation: ws-float-r 12s ease-in-out infinite;
          will-change: transform;
        }
      `}</style>

      <div style={{
        minHeight: "100vh",
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "#05070f",
        position: "relative", overflow: "hidden",
      }}>
        {/* Orbs — positioned statically, animated with transform only */}
        <div className="ws-orb1" style={{
          position: "absolute",
          width: 640, height: 640, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(59,130,246,0.11) 0%, transparent 68%)",
          top: "50%", left: "50%",
          marginTop: -320, marginLeft: -320,
          pointerEvents: "none",
        }} />
        <div className="ws-orb2" style={{
          position: "absolute",
          width: 380, height: 380, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(139,92,246,0.07) 0%, transparent 70%)",
          bottom: "8%", right: "12%",
          pointerEvents: "none",
        }} />

        {/* Grid */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px), " +
            "linear-gradient(90deg, rgba(255,255,255,0.022) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }} />

        {/* Content — single static element, all animation via CSS */}
        <div style={{ position: "relative", zIndex: 1, textAlign: "center", padding: "0 24px", maxWidth: 560 }}>
          <div className="ws-mark" style={{ marginBottom: 36 }}>
            <div style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: 50, height: 50, borderRadius: 13,
              border: "1.5px solid rgba(59,130,246,0.38)",
              background: "rgba(59,130,246,0.07)",
              fontSize: 20, color: "rgba(59,130,246,0.9)",
            }}>
              ✦
            </div>
          </div>

          <h1 className="ws-h1" style={{
            fontFamily: "'Chakra Petch', sans-serif",
            fontSize: "clamp(44px, 8vw, 74px)",
            fontWeight: 700,
            color: "#ffffff",
            letterSpacing: "-0.02em",
            lineHeight: 1.06,
            margin: "0 0 18px",
          }}>
            Welcome to<br />
            <span style={{ color: "rgba(59,130,246,1)" }}>Astra</span>
          </h1>

          <p className="ws-sub" style={{
            fontSize: 15,
            color: "rgba(255,255,255,0.42)",
            lineHeight: 1.7,
            margin: "0 0 48px",
          }}>
            Your AI founding team, ready to build.<br />
            From zero to revenue — one goal at a time.
          </p>

          <div className="ws-cta">
            <button className="ws-btn" onClick={() => router.push("/onboarding")}>
              Get Started →
            </button>
          </div>
        </div>

        <div className="ws-footer" style={{
          position: "absolute", bottom: 26, left: "50%", transform: "translateX(-50%)",
          fontSize: 9.5, color: "rgba(255,255,255,0.16)",
          letterSpacing: "0.14em", textTransform: "uppercase",
          fontFamily: "'Chakra Petch', sans-serif",
          whiteSpace: "nowrap",
        }}>
          Astra · AI Founding Team
        </div>
      </div>
    </>
  );
}
