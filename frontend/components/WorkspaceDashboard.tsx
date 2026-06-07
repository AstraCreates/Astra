"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listWorkspaces, type Workspace } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

function ago(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 2) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function statusDot(ws: Workspace) {
  const running = ws.chapters?.some((c) => c.status === "running");
  if (running) return { color: "var(--blue)", label: "Running" };
  const done = ws.chapters?.some((c) => c.status === "done");
  if (done) return { color: "var(--green)", label: "Complete" };
  return { color: "var(--fm)", label: "Idle" };
}

function WorkspaceCard({ ws, onClick, onNewRun }: { ws: Workspace; onClick: () => void; onNewRun: (e: React.MouseEvent) => void }) {
  const dot = statusDot(ws);
  const chapterCount = ws.chapters?.length ?? 0;
  const latestChapter = ws.chapters?.[ws.chapters.length - 1];
  const artifactCount = ws.chapters?.reduce((s, c) => s + (c.artifact_count || 0), 0) ?? 0;

  return (
    <div
      onClick={onClick}
      style={{
        borderRadius: 14,
        border: "1.5px solid var(--bd)",
        background: "var(--surface)",
        padding: "20px 20px 16px",
        cursor: "pointer",
        transition: "border-color .15s, box-shadow .15s",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 160,
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--blue)";
        (e.currentTarget as HTMLDivElement).style.boxShadow = "0 0 0 3px rgba(59,130,246,.1)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--bd)";
        (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div>
          <div style={{ fontFamily: "var(--font-chakra)", fontSize: 14, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>
            {ws.company_name || ws.name}
          </div>
          {ws.company_name && ws.name !== ws.company_name && (
            <div style={{ fontSize: 9.5, color: "var(--fm)", marginTop: 2 }}>{ws.name}</div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0, marginTop: 2 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: dot.color, flexShrink: 0 }} />
          <span style={{ fontSize: 9, color: dot.color, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em" }}>{dot.label}</span>
        </div>
      </div>

      {/* Goal preview */}
      <div style={{ fontSize: 11, color: "var(--fd)", lineHeight: 1.55, flex: 1, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {ws.goal}
      </div>

      {/* Stats + actions */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, borderTop: "1px solid var(--bd)", paddingTop: 10, marginTop: 2 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", fontFamily: "var(--font-chakra)" }}>{chapterCount}</div>
          <div style={{ fontSize: 8, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".08em" }}>Chapter{chapterCount !== 1 ? "s" : ""}</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", fontFamily: "var(--font-chakra)" }}>{artifactCount}</div>
          <div style={{ fontSize: 8, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".08em" }}>Artifacts</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          <button
            className="btn"
            style={{ fontSize: 10, padding: "4px 10px", lineHeight: 1.4 }}
            onClick={onNewRun}
          >
            New Run →
          </button>
          {latestChapter && (
            <div style={{ fontSize: 9, color: "var(--fd)" }}>
              {latestChapter.status === "running" ? "⋯ in progress" : `✓ ${latestChapter.name}`}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NewProjectCard({ onClick }: { onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        borderRadius: 14,
        border: "1.5px dashed var(--bd)",
        background: "transparent",
        padding: "20px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        minHeight: 160,
        transition: "border-color .15s, background .15s",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--blue)";
        (e.currentTarget as HTMLDivElement).style.background = "rgba(59,130,246,.04)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--bd)";
        (e.currentTarget as HTMLDivElement).style.background = "transparent";
      }}
    >
      <div style={{ fontSize: 28, color: "var(--fm)" }}>+</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fm)" }}>New Project</div>
      <div style={{ fontSize: 10, color: "var(--fm)", textAlign: "center", lineHeight: 1.4 }}>Start a new workspace from a fresh goal</div>
    </div>
  );
}

export default function WorkspaceDashboard() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    const load = () => {
      listWorkspaces(userId)
        .then((ws) => { if (!cancelled) { setWorkspaces(ws); setErr(""); } })
        .catch(() => {
          // Server may still be starting — retry silently after 4s
          if (!cancelled) setTimeout(load, 4000);
        })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    return () => { cancelled = true; };
  }, [userId]);

  const openWorkspace = (ws: Workspace) => {
    const latestChapter = ws.chapters?.[ws.chapters.length - 1];
    const chapterParam = latestChapter ? `&chapter=${latestChapter.chapter_id}` : "";
    router.push(`/?workspace=${ws.workspace_id}${chapterParam}&founder=${encodeURIComponent(userId)}`);
  };

  const startNewRun = (ws: Workspace, e: React.MouseEvent) => {
    e.stopPropagation();
    router.push(`/?workspace=${ws.workspace_id}&run=1&founder=${encodeURIComponent(userId)}`);
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "28px 28px 60px" }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontFamily: "var(--font-chakra)", fontSize: 22, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
          Your Projects
        </div>
        <div style={{ fontSize: 11.5, color: "var(--fm)" }}>
          Each project is a persistent workspace that grows with every chapter you run.
        </div>
      </div>

      {loading && (
        <div style={{ color: "var(--fm)", fontSize: 11 }}>Loading projects…</div>
      )}

      {!loading && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 14,
        }}>
          {workspaces.map((ws) => (
            <WorkspaceCard key={ws.workspace_id} ws={ws} onClick={() => openWorkspace(ws)} onNewRun={(e) => startNewRun(ws, e)} />
          ))}
          <NewProjectCard onClick={() => router.push("/?new=1")} />
        </div>
      )}

      {!loading && workspaces.length === 0 && !err && (
        <div style={{ textAlign: "center", paddingTop: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🚀</div>
          <div style={{ fontFamily: "var(--font-chakra)", fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 6 }}>
            No projects yet
          </div>
          <div style={{ fontSize: 11.5, color: "var(--fm)", marginBottom: 20 }}>
            Launch your first project and Astra will build it across phases — each run a new chapter in your workspace.
          </div>
          <button
            className="btn pri"
            onClick={() => router.push("/?new=1")}
          >
            Start your first project →
          </button>
        </div>
      )}
    </div>
  );
}
