"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import SessionView from "@/components/SessionView";
import DashboardView from "@/components/DashboardView";
import NewGoalView from "@/components/NewGoalView";
import WelcomeScreen from "@/components/WelcomeScreen";
import PostOnboardingScreen from "@/components/PostOnboardingScreen";

export default function AppHome() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [onboarded, setOnboarded] = useState<boolean | null>(null);
  const [showWelcomeLS, setShowWelcomeLS] = useState(false);

  const sessionId = searchParams.get("session") ?? "";
  const forceNew = searchParams.get("new") === "1";
  const showWelcome = searchParams.get("welcome") === "1" || showWelcomeLS;
  const welcomeName = searchParams.get("name") ?? "";

  // Back-compat: old links used /?session=<id>(&founder=…). Redirect to the clean
  // shareable /s/<id> route (drops the founder param).
  useEffect(() => {
    if (sessionId) router.replace(`/s/${sessionId}`);
  }, [sessionId, router]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setOnboarded(!!localStorage.getItem("astra_onboarding_done"));
      if (localStorage.getItem("astra_show_welcome") === "1") {
        localStorage.removeItem("astra_show_welcome");
        setShowWelcomeLS(true);
      }
    }
  }, []);

  // Still checking localStorage — transparent cover so body gradient shows (no flash)
  if (onboarded === null) return (
    <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "transparent" }} />
  );

  // Not onboarded — show animated landing, not a redirect (avoids flash)
  if (!onboarded) {
    return <WelcomeScreen />;
  }

  const postName = welcomeName || (typeof window !== "undefined" ? localStorage.getItem("astra_onboarding_name") || "" : "");

  function handleWelcomeDone() {
    try { localStorage.setItem("astra_show_tour", "1"); } catch {}
    router.replace("/");
    setTimeout(() => window.dispatchEvent(new CustomEvent("astra:show-tour")), 200);
  }

  // Normal routing
  const view = forceNew ? "new" : sessionId ? "session" : "home";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden", background: "var(--bg)" }}>
      {view === "new" ? (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">New Run</div>
          </div>
          <NewGoalView />
        </>
      ) : view === "session" ? (
        <SessionView key={sessionId} sessionId={sessionId} />
      ) : (
        <DashboardView />
      )}
      {/* PostOnboarding overlay — fixed on top so DashboardView loads sessions in background */}
      {showWelcome && <PostOnboardingScreen name={postName} onComplete={handleWelcomeDone} />}
    </div>
  );
}
