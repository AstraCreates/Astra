"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import SessionView from "@/components/SessionView";
import DashboardView from "@/components/DashboardView";
import NewGoalView from "@/components/NewGoalView";
import WelcomeScreen from "@/components/WelcomeScreen";
import PostOnboardingScreen from "@/components/PostOnboardingScreen";
import { listSessions } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

export default function AppHome() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId } = useDevUser();
  const [onboarded, setOnboarded] = useState<boolean | null>(null);
  const [showWelcomeLS, setShowWelcomeLS] = useState(false);
  const [onboardingCheckError, setOnboardingCheckError] = useState<string | null>(null);

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
    if (typeof window === "undefined" || !userId) return;

    if (localStorage.getItem("astra_show_welcome") === "1") {
      localStorage.removeItem("astra_show_welcome");
      setShowWelcomeLS(true);
    }

    // Fast path: localStorage already set
    if (localStorage.getItem("astra_onboarding_done")) {
      setOnboarded(true);
      return;
    }

    // Slow path: localStorage missing (new device/browser). Check backend —
    // if the user already has sessions, they've been onboarded before.
    listSessions(userId, 1).then((sessions) => {
      if (sessions.length > 0) {
        localStorage.setItem("astra_onboarding_done", "1");
        setOnboarded(true);
      } else {
        setOnboarded(false);
      }
    }).catch(() => {
      // If the backend is temporarily unreachable, avoid trapping existing users
      // behind onboarding just because this browser has no local marker yet.
      setOnboardingCheckError("Couldn't verify onboarding right now. Showing your dashboard instead.");
      setOnboarded(true);
    });
  }, [userId]);

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
    router.replace("/dashboard");
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
        <>
          {onboardingCheckError && (
            <div style={{ padding: "10px 14px", background: "rgba(255,184,77,0.12)", color: "var(--text)", borderBottom: "1px solid var(--bd)", fontSize: 12 }}>
              {onboardingCheckError}
            </div>
          )}
          <DashboardView />
        </>
      )}
      {/* PostOnboarding overlay — fixed on top so DashboardView loads sessions in background */}
      {showWelcome && <PostOnboardingScreen name={postName} onComplete={handleWelcomeDone} />}
    </div>
  );
}
