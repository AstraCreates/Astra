"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function PostOnboardingScreen({ name }: { name: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 200);
    const t2 = setTimeout(() => setPhase(2), 800);
    const t3 = setTimeout(() => setPhase(3), 1500);
    const t4 = setTimeout(() => router.replace("/"), 3800);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); };
  }, [router]);

  const displayName = name.split(" ")[0] || name;

  return (
    <>
      <style>{`
        @keyframes pos-up {
          from { opacity: 0; transform: translateY(20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pos-progress {
          from { width: 0%; }
          to   { width: 100%; }
        }
        @keyframes pos-grain {
          0%   { transform: translate(0px,   0px)  scale(1.05); }
          10%  { transform: translate(-6px, -4px)  scale(1.05); }
          20%  { transform: translate(4px,   7px)  scale(1.05); }
          30%  { transform: translate(-3px,  3px)  scale(1.05); }
          40%  { transform: translate(6px,  -6px)  scale(1.05); }
          50%  { transform: translate(-5px,  5px)  scale(1.05); }
          60%  { transform: translate(7px,  -3px)  scale(1.05); }
          70%  { transform: translate(-4px,  6px)  scale(1.05); }
          80%  { transform: translate(3px,  -7px)  scale(1.05); }
          90%  { transform: translate(-6px,  2px)  scale(1.05); }
          100% { transform: translate(0px,   0px)  scale(1.05); }
        }
      `}</style>

      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        position: "relative", overflow: "hidden",
        background: "linear-gradient(145deg, #002EFF 0%, #0040FF 25%, #1a6aff 55%, #5DFFB8 85%, #7CFFC6 100%)",
      }}>
        {/* Animated pixelated grain */}
        <div style={{
          position: "absolute", top: "-10%", left: "-10%", width: "120%", height: "120%",
          pointerEvents: "none", zIndex: 1,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 80 80' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.55' numOctaves='1' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "180px 180px",
          imageRendering: "pixelated",
          opacity: 0.42,
          mixBlendMode: "overlay",
          animation: "pos-grain 0.65s steps(10) infinite",
        } as React.CSSProperties} />

        <div style={{ position: "relative", zIndex: 2, textAlign: "center", padding: "0 32px" }}>
          <p style={{
            fontSize: 15, fontWeight: 400, color: "rgba(255,255,255,0.7)",
            marginBottom: 16, letterSpacing: "0.01em",
            opacity: phase >= 1 ? 1 : 0,
            animation: phase >= 1 ? "pos-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
          }}>
            You&rsquo;re all set.
          </p>

          <h1 style={{
            fontFamily: "var(--font-fraunces), 'Fraunces', serif",
            fontSize: "clamp(52px, 10vw, 88px)",
            fontWeight: 400,
            color: "#ffffff",
            lineHeight: 1.05,
            letterSpacing: "-0.02em",
            margin: "0 0 36px",
            opacity: phase >= 2 ? 1 : 0,
            animation: phase >= 2 ? "pos-up 0.8s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            Let&rsquo;s build,<br />{displayName || "Founder"}.
          </h1>

          <div style={{
            opacity: phase >= 3 ? 1 : 0,
            animation: phase >= 3 ? "pos-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
          }}>
            <button
              onClick={() => router.replace("/")}
              style={{
                padding: "12px 36px", fontSize: 13, fontWeight: 500,
                fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                color: "#002EFF", background: "#ffffff",
                border: "none", borderRadius: 100, cursor: "pointer",
                transition: "opacity 0.18s",
              }}
              onMouseEnter={e => (e.currentTarget.style.opacity = "0.85")}
              onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
            >
              Go to dashboard
            </button>
          </div>
        </div>

        {phase >= 3 && (
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 2, background: "rgba(255,255,255,0.15)", zIndex: 2 }}>
            <div style={{ height: "100%", background: "rgba(255,255,255,0.6)", animation: "pos-progress 2.3s linear forwards" }} />
          </div>
        )}
      </div>
    </>
  );
}
