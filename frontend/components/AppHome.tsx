"use client";

import { useSearchParams } from "next/navigation";
import SessionView from "@/components/SessionView";
import WorkspaceDashboard from "@/components/WorkspaceDashboard";
import WorkspaceView from "@/components/WorkspaceView";
import NewProjectView from "@/components/NewProjectView";
import NewRunView from "@/components/NewRunView";

export default function AppHome() {
  const searchParams = useSearchParams();

  const workspaceId = searchParams.get("workspace") ?? "";
  const chapterId = searchParams.get("chapter") ?? "";
  const sessionId = searchParams.get("session") ?? "";
  const forceNew = searchParams.get("new") === "1";
  const forceRun = searchParams.get("run") === "1";

  // Routing priority: run (within workspace) > new project > workspace > legacy session > dashboard
  const view = (forceRun && workspaceId) ? "run"
    : forceNew ? "new"
    : workspaceId ? "workspace"
    : sessionId ? "session"
    : "home";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden", background: "var(--bg)" }}>
      {view === "run" ? (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">New Run</div>
          </div>
          <NewRunView workspaceId={workspaceId} />
        </>
      ) : view === "new" ? (
        <>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">New Project</div>
          </div>
          <NewProjectView />
        </>
      ) : view === "workspace" ? (
        <WorkspaceView key={workspaceId} workspaceId={workspaceId} initialChapterId={chapterId || undefined} />
      ) : view === "session" ? (
        <SessionView key={sessionId} sessionId={sessionId} />
      ) : (
        <WorkspaceDashboard />
      )}
    </div>
  );
}
