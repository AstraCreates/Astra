"use client";

import { useEffect, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { MeetingTimeline } from "@/components/CompanyHome";
import type { CompanyHomeSquad, CompanyHomeArtifact } from "@/lib/company-os";

const WORKBENCH_STATE: Record<string, string> = { planned: "que", active: "run", waiting: "que", complete: "done", blocked: "err" };
const WORKBENCH_LABEL: Record<string, string> = { planned: "Queued", active: "Working", waiting: "Waiting", complete: "Done", blocked: "Blocked" };

export default function SquadDetailPanel({
  squad,
  artifacts = [],
  retryingTaskId = "",
  onRetryTask,
  onDeleteSquad,
}: {
  squad: CompanyHomeSquad | null;
  artifacts?: CompanyHomeArtifact[];
  // Owned by the parent (SquadsPage), not local state -- the parent already
  // resets this in a finally block regardless of success/failure. A local
  // copy here would only ever get SET, never cleared on a failed retry
  // (the task stays "blocked" and the button would be stuck reading
  // "Retrying..." forever with no way to try again).
  retryingTaskId?: string;
  onRetryTask?: (taskId: string) => void;
  onDeleteSquad?: () => void;
}) {
  // Meetings render open by default here -- the whole point of this page is
  // that meetings were previously buried behind SquadWorkbench's
  // collapsed-by-default toggle (meetingsOpen useState(false)). Same
  // component, same props, just not defaulted shut.
  const [meetingsOpen, setMeetingsOpen] = useState(true);
  const [pendingDeleteId, setPendingDeleteId] = useState("");

  useEffect(() => {
    if (!pendingDeleteId) return;
    const timer = window.setTimeout(() => setPendingDeleteId(""), 3000);
    return () => window.clearTimeout(timer);
  }, [pendingDeleteId]);

  if (!squad) {
    return (
      <div className="empty" style={{ minHeight: 280 }}>
        <div className="empty-title">Select a squad</div>
        <p style={{ margin: 0, fontSize: 12 }}>Click a node in the graph to see its roster, tasks, and meetings.</p>
      </div>
    );
  }

  const handleDelete = async () => {
    if (pendingDeleteId !== squad.id) {
      setPendingDeleteId(squad.id);
      return;
    }
    setPendingDeleteId("");
    onDeleteSquad?.();
  };

  return (
    <>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      <div style={{ border: "1px solid var(--bd)", borderRadius: "var(--radius-lg)", background: "var(--bg-surface)", overflow: "hidden", display: "flex", flexDirection: "column", minWidth: 0, width: "100%", maxWidth: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "16px 20px", borderBottom: "1px solid var(--bd)" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{squad.name}</h2>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span className={`dc-badge ${squad.lifecycle.toLowerCase() === "working" || squad.lifecycle.toLowerCase() === "active" ? "run" : squad.lifecycle.toLowerCase() === "done" || squad.lifecycle.toLowerCase() === "complete" ? "done" : "que"}`}>{squad.lifecycle}</span>
          <button
            type="button"
            onClick={() => void handleDelete()}
            title={pendingDeleteId === squad.id ? "Click again to confirm" : "Delete squad"}
            style={{
              flexShrink: 0,
              width: 28,
              height: 28,
              display: "grid",
              placeItems: "center",
              border: "1px solid var(--bd)",
              borderRadius: 6,
              background: "transparent",
              color: pendingDeleteId === squad.id ? "var(--red)" : "var(--fm)",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
              transition: "color .12s",
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {(squad.charter || squad.roster.length > 0) && (
        <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--bd)", background: "var(--bg-sunken)", fontSize: 11.5, color: "var(--fm)" }}>
          {squad.charter && <div style={{ marginBottom: squad.roster.length ? 5 : 0 }}><b style={{ color: "var(--fg)" }}>Charter: </b>{squad.charter}</div>}
          {squad.roster.length > 0 && <div><b style={{ color: "var(--fg)" }}>Team: </b>{squad.roster.map(member => `${member.name} (${member.isLead ? "Lead, " : ""}${member.role} · ${member.status})`).join(" · ")}</div>}
        </div>
      )}

      <div style={{ padding: "14px 20px", minWidth: 0 }}>
        <div className="sec-label" style={{ marginBottom: 8 }}>Tasks · {squad.tasks.length}</div>
        {squad.tasks.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12, color: "var(--fm)" }}>This squad hasn&apos;t started work.</p>
        ) : (
          <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
            {squad.tasks.map(task => (
              <div key={task.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "8px 10px", border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-sunken)", minWidth: 0 }}>
                <span style={{ fontSize: 12.5, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, flex: 1 }}>{task.title}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                  {task.status === "blocked" && onRetryTask && (
                    <button
                      type="button"
                      onClick={() => onRetryTask?.(task.id)}
                      disabled={retryingTaskId === task.id}
                      style={{
                        padding: "4px 8px",
                        fontSize: 11,
                        fontWeight: 600,
                        border: "1px solid var(--bd)",
                        borderRadius: 5,
                        background: "var(--bg-surface)",
                        color: retryingTaskId === task.id ? "var(--fm)" : "var(--fg)",
                        cursor: retryingTaskId === task.id ? "default" : "pointer",
                        opacity: retryingTaskId === task.id ? 0.6 : 1,
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        transition: "opacity .12s",
                      }}
                    >
                      {retryingTaskId === task.id && <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />}
                      {retryingTaskId === task.id ? "Retrying…" : "Retry"}
                    </button>
                  )}
                  <span className={`dc-badge ${WORKBENCH_STATE[task.status] ?? "que"}`}>{WORKBENCH_LABEL[task.status] ?? task.status}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {artifacts.length > 0 && (
        <div style={{ padding: "14px 20px", borderTop: "1px solid var(--bd)" }}>
          <div className="sec-label" style={{ marginBottom: 8 }}>Artifacts · {artifacts.length}</div>
          <div style={{ display: "grid", gap: 6 }}>
            {artifacts.map(artifact => (
              <div key={artifact.id} style={{ padding: "8px 10px", border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-sunken)" }}>
                <div style={{ fontSize: 12.5, color: "var(--fg)", fontWeight: 500, marginBottom: 2 }}>{artifact.title}</div>
                <div style={{ fontSize: 11, color: "var(--fm)", marginBottom: 4 }}>{artifact.source} · {artifact.updatedAt}</div>
                {artifact.url && (
                  <a
                    href={artifact.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: 11, color: "var(--accent)", textDecoration: "none", fontWeight: 500, display: "inline-block" }}
                  >
                    View link →
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <MeetingTimeline meetings={squad.meetings} open={meetingsOpen} onToggle={() => setMeetingsOpen(!meetingsOpen)} />
      </div>
    </>
  );
}
