"use client";

import { useSearchParams } from "next/navigation";
import SessionView from "@/components/SessionView";
import DashboardView from "@/components/DashboardView";
import NewGoalView from "@/components/NewGoalView";

export default function AppHome() {
  const searchParams = useSearchParams();

  const sessionId = searchParams.get("session") ?? "";
  const forceNew = searchParams.get("new") === "1";

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
