"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function PostOnboardingScreen({ name }: { name: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState(0);
  // 0 = hidden, 1 = greeting, 2 = name, 3 = sub + button

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 200);
    const t2 = setTimeout(() => setPhase(2), 800);
    const t3 = setTimeout(() => setPhase(3), 1500);
    // Auto-redirect after 3.5s
    const t4 = setTimeout(() => router.replace("/"), 3800);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); };
  }, [router]);

  const displayName = name.split(" ")[0] || name; // first name only

  return (
    <>
      <style>{`
        @keyframes pos-fade-up {
          from { opacity: 0; transform: translateY(20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pos-reveal {
          from { opacity: 0; transform: translateY(30px) scale(0.96); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes pos-shimmer {
          0%   { background-position: -200% center; }
          100% { background-position: 200% center; }
        }
        @keyframes pos-orb-float {
          0%, 100% { transform: translate(-50%, -50%) scale(1); }
          50%       { transform: translate(-50%, -52%) scale(1.08); }
        }
        @keyframes pos-progress {
          from { width: 0%; }
          to   { width: 100%; }
        }
      `}</style>

      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "linear-gradient(160deg, #020511 0%, #001040 42%, #000d35 65%, #020714 100%)",
        position: "relative", overflow: "hidden",
      }}>
        {/* Ambient glow */}
        <div style={{
          position: "absolute", width: 700, height: 700, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(0,46,255,0.13) 0%, transparent 65%)",
          top: "50%", left: "50%",
          animation: "pos-orb-float 7s ease-in-out infinite",
          pointerEvents: "none",
        }} />

        {/* Grid */}
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none",
          backgroundImage: "linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }} />

        <div style={{ position: "relative", zIndex: 1, textAlign: "center", padding: "0 24px" }}>
          {/* Greeting line */}
          <div style={{
            fontSize: 16, fontWeight: 500,
            color: "rgba(255,255,255,0.45)",
            letterSpacing: "0.02em",
            marginBottom: 12,
            opacity: phase >= 1 ? 1 : 0,
            animation: phase >= 1 ? "pos-fade-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            You&rsquo;re all set.
          </div>

          {/* Name headline */}
          <h1 style={{
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            fontSize: "clamp(48px, 9vw, 80px)",
            fontWeight: 700,
            lineHeight: 1.05,
            margin: "0 0 28px",
            opacity: phase >= 2 ? 1 : 0,
            animation: phase >= 2 ? "pos-reveal 0.8s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            <span style={{ color: "rgba(255,255,255,0.55)", fontSize: "0.55em", fontWeight: 400, display: "block", marginBottom: 6, letterSpacing: "0.01em" }}>
              Let&rsquo;s get started,
            </span>
            <span style={{
              background: "linear-gradient(90deg, #fff 0%, #7CFFC6 35%, #002EFF 55%, #7CFFC6 75%, #fff 100%)",
              backgroundSize: "200% auto",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
              animation: phase >= 2 ? "pos-shimmer 3s linear 0.3s infinite" : "none",
            }}>
              {displayName || "Founder"}
            </span>
          </h1>

          {/* Sub + actions */}
          <div style={{
            opacity: phase >= 3 ? 1 : 0,
            animation: phase >= 3 ? "pos-fade-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            <p style={{
              fontSize: 13, color: "rgba(255,255,255,0.35)", margin: "0 0 36px",
            }}>
              Astra is ready. Heading to your dashboard…
            </p>

            <button
              onClick={() => router.replace("/")}
              style={{
                padding: "12px 32px",
                fontSize: 13, fontWeight: 600,
                letterSpacing: "0.04em",
                color: "rgba(255,255,255,0.85)",
                background: "rgba(0,46,255,0.15)",
                border: "1.5px solid rgba(0,46,255,0.45)",
                borderRadius: 9,
                cursor: "pointer",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "rgba(0,46,255,0.28)";
                (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(0,46,255,0.85)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "rgba(0,46,255,0.15)";
                (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(0,46,255,0.45)";
              }}
            >
              Go to dashboard →
            </button>
          </div>
        </div>

        {/* Auto-progress bar */}
        {phase >= 3 && (
          <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0, height: 2,
            background: "rgba(255,255,255,0.06)",
          }}>
            <div style={{
              height: "100%",
              background: "linear-gradient(90deg, #002EFF, #7CFFC6)",
              animation: "pos-progress 2.3s linear forwards",
            }} />
          </div>
        )}
      </div>
    </>
  );
}
