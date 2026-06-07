"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function WelcomeScreen() {
  const router = useRouter();
  const [phase, setPhase] = useState(0);
  // 0 = logo, 1 = headline, 2 = sub, 3 = button

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 300);
    const t2 = setTimeout(() => setPhase(2), 900);
    const t3 = setTimeout(() => setPhase(3), 1500);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, []);

  return (
    <>
      <style>{`
        @keyframes ws-fade-up {
          from { opacity: 0; transform: translateY(18px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes ws-fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes ws-glow-pulse {
          0%, 100% { text-shadow: 0 0 40px rgba(59,130,246,0.5), 0 0 80px rgba(59,130,246,0.2); }
          50%       { text-shadow: 0 0 60px rgba(59,130,246,0.8), 0 0 120px rgba(59,130,246,0.35); }
        }
        @keyframes ws-btn-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(59,130,246,0.4); }
          50%       { box-shadow: 0 0 0 8px rgba(59,130,246,0); }
        }
        @keyframes ws-bg-drift {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes ws-orb-float {
          0%, 100% { transform: translateY(0px) scale(1); }
          50%       { transform: translateY(-30px) scale(1.05); }
        }
        .ws-btn:hover {
          background: rgba(59,130,246,0.2) !important;
          border-color: rgba(59,130,246,0.8) !important;
          color: #fff !important;
        }
      `}</style>

      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "#05070f",
        position: "relative", overflow: "hidden",
      }}>
        {/* Ambient orbs */}
        <div style={{
          position: "absolute", width: 600, height: 600, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(59,130,246,0.12) 0%, transparent 70%)",
          top: "50%", left: "50%", transform: "translate(-50%, -60%)",
          animation: "ws-orb-float 8s ease-in-out infinite",
          pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", width: 400, height: 400, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(139,92,246,0.08) 0%, transparent 70%)",
          bottom: "10%", right: "15%",
          animation: "ws-orb-float 11s ease-in-out infinite reverse",
          pointerEvents: "none",
        }} />

        {/* Grid overlay */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          backgroundImage: "linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }} />

        {/* Content */}
        <div style={{ position: "relative", zIndex: 1, textAlign: "center", padding: "0 24px", maxWidth: 560 }}>
          {/* Mark */}
          <div style={{
            opacity: phase >= 0 ? 1 : 0,
            animation: phase >= 0 ? "ws-fade-in 0.8s ease forwards" : "none",
            marginBottom: 40,
          }}>
            <div style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: 52, height: 52, borderRadius: 14,
              border: "1.5px solid rgba(59,130,246,0.4)",
              background: "rgba(59,130,246,0.08)",
              fontSize: 22,
              animation: "ws-orb-float 6s ease-in-out infinite",
            }}>
              ✦
            </div>
          </div>

          {/* Headline */}
          <h1 style={{
            fontFamily: "'Chakra Petch', sans-serif",
            fontSize: "clamp(42px, 8vw, 72px)",
            fontWeight: 700,
            color: "#ffffff",
            letterSpacing: "-0.02em",
            lineHeight: 1.05,
            margin: "0 0 16px",
            opacity: phase >= 1 ? 1 : 0,
            animation: phase >= 1 ? "ws-fade-up 0.7s cubic-bezier(0.22,1,0.36,1) forwards, ws-glow-pulse 4s ease-in-out 1.5s infinite" : "none",
          }}>
            Welcome to<br />
            <span style={{ color: "rgba(59,130,246,1)" }}>Astra</span>
          </h1>

          {/* Subtitle */}
          <p style={{
            fontSize: 15, color: "rgba(255,255,255,0.45)", lineHeight: 1.65,
            margin: "0 0 48px",
            opacity: phase >= 2 ? 1 : 0,
            animation: phase >= 2 ? "ws-fade-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            Your AI founding team, ready to build.<br />
            From zero to revenue — one goal at a time.
          </p>

          {/* CTA */}
          <div style={{
            opacity: phase >= 3 ? 1 : 0,
            animation: phase >= 3 ? "ws-fade-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            <button
              className="ws-btn"
              onClick={() => router.push("/onboarding")}
              style={{
                padding: "14px 36px",
                fontSize: 14, fontWeight: 600,
                fontFamily: "'Chakra Petch', sans-serif",
                letterSpacing: "0.04em",
                color: "rgba(255,255,255,0.9)",
                background: "rgba(59,130,246,0.1)",
                border: "1.5px solid rgba(59,130,246,0.5)",
                borderRadius: 10,
                cursor: "pointer",
                transition: "all 0.2s ease",
                animation: "ws-btn-glow 2.5s ease-in-out 2s infinite",
              }}
            >
              Get Started →
            </button>
          </div>
        </div>

        {/* Bottom badge */}
        <div style={{
          position: "absolute", bottom: 28, left: "50%", transform: "translateX(-50%)",
          fontSize: 10, color: "rgba(255,255,255,0.18)", letterSpacing: "0.12em",
          textTransform: "uppercase", fontFamily: "'Chakra Petch', sans-serif",
          opacity: phase >= 3 ? 1 : 0,
          animation: phase >= 3 ? "ws-fade-in 1s ease 0.5s forwards" : "none",
        }}>
          Astra · AI Founding Team
        </div>
      </div>
    </>
  );
}
