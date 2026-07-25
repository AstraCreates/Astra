"use client";

import { useState } from "react";
import { MeetingTimeline } from "@/components/CompanyHome";
import type { CompanyHomeSquad } from "@/lib/company-os";

const WORKBENCH_STATE: Record<string, string> = { planned: "que", active: "run", waiting: "que", complete: "done", blocked: "err" };
const WORKBENCH_LABEL: Record<string, string> = { planned: "Queued", active: "Working", waiting: "Waiting", complete: "Done", blocked: "Blocked" };

export default function SquadDetailPanel({ squad }: { squad: CompanyHomeSquad | null }) {
  // Meetings render open by default here -- the whole point of this page is
  // that meetings were previously buried behind SquadWorkbench's
  // collapsed-by-default toggle (meetingsOpen useState(false)). Same
  // component, same props, just not defaulted shut.
  const [meetingsOpen, setMeetingsOpen] = useState(true);

  if (!squad) {
    return (
      <div className="empty" style={{ minHeight: 280 }}>
        <div className="empty-title">Select a squad</div>
        <p style={{ margin: 0, fontSize: 12 }}>Click a node in the graph to see its roster, tasks, and meetings.</p>
      </div>
    );
  }

  return (
    <div style={{ border: "1px solid var(--bd)", borderRadius: "var(--radius-lg)", background: "var(--bg-surface)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "16px 20px", borderBottom: "1px solid var(--bd)" }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{squad.name}</h2>
        <span className={`dc-badge ${squad.lifecycle.toLowerCase() === "working" || squad.lifecycle.toLowerCase() === "active" ? "run" : squad.lifecycle.toLowerCase() === "done" || squad.lifecycle.toLowerCase() === "complete" ? "done" : "que"}`}>{squad.lifecycle}</span>
      </div>

      {(squad.charter || squad.roster.length > 0) && (
        <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--bd)", background: "var(--bg-sunken)", fontSize: 11.5, color: "var(--fm)" }}>
          {squad.charter && <div style={{ marginBottom: squad.roster.length ? 5 : 0 }}><b style={{ color: "var(--fg)" }}>Charter: </b>{squad.charter}</div>}
          {squad.roster.length > 0 && <div><b style={{ color: "var(--fg)" }}>Team: </b>{squad.roster.map(member => `${member.name} (${member.isLead ? "Lead, " : ""}${member.role} · ${member.status})`).join(" · ")}</div>}
        </div>
      )}

      <div style={{ padding: "14px 20px" }}>
        <div className="sec-label" style={{ marginBottom: 8 }}>Tasks · {squad.tasks.length}</div>
        {squad.tasks.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12, color: "var(--fm)" }}>This squad hasn&apos;t started work.</p>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {squad.tasks.map(task => (
              <div key={task.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "8px 10px", border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-sunken)" }}>
                <span style={{ fontSize: 12.5, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</span>
                <span className={`dc-badge ${WORKBENCH_STATE[task.status] ?? "que"}`} style={{ flexShrink: 0 }}>{WORKBENCH_LABEL[task.status] ?? task.status}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <MeetingTimeline meetings={squad.meetings} open={meetingsOpen} onToggle={() => setMeetingsOpen(!meetingsOpen)} />
    </div>
  );
}
