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

  const sessionId = searchParams.get("session") ?? "";
  const forceNew = searchParams.get("new") === "1";
  const showWelcome = searchParams.get("welcome") === "1";
  const welcomeName = searchParams.get("name") ?? "";

  // Back-compat: old links used /?session=<id>(&founder=…). Redirect to the clean
  // shareable /s/<id> route (drops the founder param).
  useEffect(() => {
    if (sessionId) router.replace(`/s/${sessionId}`);
  }, [sessionId, router]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setOnboarded(!!localStorage.getItem("astra_onboarding_done"));
    }
  }, []);

  // Still checking localStorage — cover with blank screen matching preloader bg to avoid sidebar flash
  if (onboarded === null) return (
    <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "#F3F4F7" }} />
  );

  // Post-onboarding celebration screen
  if (showWelcome) {
    const name = welcomeName || (typeof window !== "undefined" ? localStorage.getItem("astra_onboarding_name") || "" : "");
    return <PostOnboardingScreen name={name} />;
  }

  // Not onboarded — show animated landing, not a redirect (avoids flash)
  if (!onboarded) {
    return <WelcomeScreen />;
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
    </div>
  );
}
