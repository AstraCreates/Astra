"use client";

import { useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { getSessionSnapshot, subscribeSessions } from "@/lib/history";
import { GoalWorkspace } from "@/components/GoalWorkspace";

import type { SessionRecord } from "@/lib/history";

const EMPTY_RECENT_SESSIONS: SessionRecord[] = [];

export default function AppHome() {
  const searchParams = useSearchParams();
  const { userId } = useDevUser();
  const recentSessions = useSyncExternalStore(
    subscribeSessions,
    getSessionSnapshot,
    () => EMPTY_RECENT_SESSIONS,
  );

  const forceNewGoal = searchParams.get("new") === "1";
  const fromOnboarding = searchParams.get("from_onboarding") === "1";
  const latestSession = recentSessions[0];
  const activeSessionId = forceNewGoal ? "" : searchParams.get("session") ?? latestSession?.sessionId ?? "";
  const activeInstruction = forceNewGoal ? "" : searchParams.get("instruction") ?? latestSession?.instruction ?? "";
  const activeFounderId = forceNewGoal ? userId : searchParams.get("founder") ?? latestSession?.founderId ?? userId;
  const activeCompany = forceNewGoal ? "" : searchParams.get("company") ?? latestSession?.companyName ?? "";

  return (
    <div className="site-shell" style={{ paddingTop: 48, paddingBottom: 88, maxWidth: 1920 }}>
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
