"use client";

import { useSearchParams } from "next/navigation";
import SessionView from "@/components/SessionView";
import NewGoalView from "@/components/NewGoalView";
import WorkspaceDashboard from "@/components/WorkspaceDashboard";
import WorkspaceView from "@/components/WorkspaceView";

export default function AppHome() {
  const searchParams = useSearchParams();

  const workspaceId = searchParams.get("workspace") ?? "";
  const chapterId = searchParams.get("chapter") ?? "";
  const sessionId = searchParams.get("session") ?? "";
  const forceNew = searchParams.get("new") === "1";

  // Routing priority: new > workspace > legacy session > dashboard home
  const view = forceNew ? "new"
    : workspaceId ? "workspace"
    : sessionId ? "session"
    : "home";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden", background: "var(--bg)" }}>
      {view === "workspace" ? (
        <WorkspaceView key={workspaceId} workspaceId={workspaceId} initialChapterId={chapterId || undefined} />
      ) : view === "session" ? (
        <SessionView key={sessionId} sessionId={sessionId} />
      ) : view === "new" ? (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">New Project</div>
          </div>
          <NewGoalView />
        </>
      ) : (
        <WorkspaceDashboard />
      )}
    </div>
  );
}
