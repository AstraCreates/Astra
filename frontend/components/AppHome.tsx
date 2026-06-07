"use client";

import { useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";
import { getSessionSnapshot, subscribeSessions } from "@/lib/history";
import SessionView from "@/components/SessionView";
import DashboardView from "@/components/DashboardView";
import NewGoalView from "@/components/NewGoalView";

import type { SessionRecord } from "@/lib/history";

const EMPTY_RECENT_SESSIONS: SessionRecord[] = [];

export default function AppHome() {
  const searchParams = useSearchParams();
  const recentSessions = useSyncExternalStore(subscribeSessions, getSessionSnapshot, () => EMPTY_RECENT_SESSIONS);

  const forceNewGoal = searchParams.get("new") === "1";
  const latestSession = recentSessions[0];
  const activeSessionId = forceNewGoal ? "" : searchParams.get("session") ?? latestSession?.sessionId ?? "";
  const view = forceNewGoal ? "new" : activeSessionId ? "session" : "dash";

  // Sidebar comes from the global AppChrome; here we only render the view.
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden", background: "var(--bg)" }}>
      {view === "session" ? (
        <SessionView key={activeSessionId} sessionId={activeSessionId} />
      ) : view === "new" ? (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}><div className="topbar-title">New goal</div></div>
          <NewGoalView />
        </>
      ) : (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}><div className="topbar-title">Dashboard</div></div>
          <DashboardView />
        </>
      )}
    </div>
  );
}
