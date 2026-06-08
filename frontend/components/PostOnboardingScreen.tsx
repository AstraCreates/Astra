"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AstraGradient from "./AstraGradient";

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
      `}</style>

      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        position: "relative", overflow: "hidden",
        background: "#001aff",
      }}>
        <AstraGradient />

        <div style={{ position: "relative", zIndex: 2, textAlign: "center", padding: "0 32px" }}>
          <p style={{
            fontSize: 15, fontWeight: 400, color: "rgba(0,0,0,0.55)",
            marginBottom: 16, letterSpacing: "0.01em",
            opacity: phase >= 1 ? 1 : 0,
            animation: phase >= 1 ? "pos-up 0.6s cubic-bezier(0.22,1,0.36,1) forwards" : "none",
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
          }}>
            You&rsquo;re all set.
          </p>

          <h1 style={{
            fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
            fontSize: "clamp(48px, 9vw, 80px)",
            fontWeight: 700,
            color: "#0a0a0a",
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
                fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                color: "#ffffff", background: "#0a0a0a",
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
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 2, background: "rgba(0,0,0,0.1)", zIndex: 2 }}>
            <div style={{ height: "100%", background: "rgba(0,30,255,0.5)", animation: "pos-progress 2.3s linear forwards" }} />
          </div>
        )}
      </div>
    </>
  );
}
