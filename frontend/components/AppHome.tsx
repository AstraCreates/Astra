"use client";

import { useEffect } from "react";
import { useSyncExternalStore } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { getSessionSnapshot, subscribeSessions } from "@/lib/history";
import { GoalWorkspace } from "@/components/GoalWorkspace";

import type { SessionRecord } from "@/lib/history";

const EMPTY_RECENT_SESSIONS: SessionRecord[] = [];

export default function AppHome() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoaded } = useUser();
  const recentSessions = useSyncExternalStore(
    subscribeSessions,
    getSessionSnapshot,
    () => EMPTY_RECENT_SESSIONS,
  );

  useEffect(() => {
    if (!isLoaded) return;
    if (user && !user.unsafeMetadata?.onboarding_done) {
      router.replace("/onboarding");
    }
  }, [isLoaded, user, router]);

  const forceNewGoal = searchParams.get("new") === "1";
  const fromOnboarding = searchParams.get("from_onboarding") === "1";
  const latestSession = recentSessions[0];
  const activeSessionId = forceNewGoal ? "" : searchParams.get("session") ?? latestSession?.sessionId ?? "";
  const activeInstruction = forceNewGoal ? "" : searchParams.get("instruction") ?? latestSession?.instruction ?? "";
  const activeFounderId = forceNewGoal ? user?.id ?? "founder_001" : searchParams.get("founder") ?? latestSession?.founderId ?? user?.id ?? "founder_001";
  const activeCompany = forceNewGoal ? "" : searchParams.get("company") ?? latestSession?.companyName ?? "";

  // Wait for Clerk to load; hold render if redirect is pending
  if (!isLoaded || (user && !user.unsafeMetadata?.onboarding_done)) return null;

  return (
    <div className="site-shell" style={{ paddingTop: 48, paddingBottom: 88 }}>
      <GoalWorkspace
        key={activeSessionId || "new"}
        sessionId={activeSessionId}
        instruction={activeInstruction}
        founderId={activeFounderId}
        company={activeCompany}
        startNew={!fromOnboarding && forceNewGoal}
      />
    </div>
  );
}
