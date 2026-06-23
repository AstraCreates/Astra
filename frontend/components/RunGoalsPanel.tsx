"use client";

// Dashboard left-panel: shows what each run is trying to accomplish.

import type { SessionIndexEntry } from "@/lib/api";

function extractGoalTitle(raw: string): string {
  return (
    raw
      .replace(/^FOLLOW-UP RUN for GOAL:\s*/i, "")
      .replace(/^GOAL:\s*/i, "")
      .replace(/\s*An earlier run already completed[\s\S]*$/i, "")
      .replace(/\s*Work together to complete these major tasks[\s\S]*$/i, "")
      .replace(/\s*Each agent: deliver[\s\S]*$/i, "")
      .replace(/\s*Finish ONLY the \d+[\s\S]*$/i, "")
      .trim() || raw
  );
}

function ago(ts: string | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

interface Props {
  sessions: SessionIndexEntry[] | null;
}

function SecLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 9, fontWeight: 700, letterSpacing: ".1em",
      textTransform: "uppercase", color: "var(--fd)",
      fontFamily: "var(--font-code)", marginBottom: 8,
    }}>
      {children}
    </div>
  );
}

function GoalRow({ session }: { session: SessionIndexEntry }) {
  const running = session.status === "running";
  const stalled = session.status === "stalled";
  const done = session.status === "done";
  const failed = session.status === "error" || session.status === "killed";

  const dot = running ? "var(--blue)"
    : stalled ? "var(--amber)"
    : done    ? "var(--green)"
    : failed  ? "var(--red)"
    : "var(--fm)";

  const title = extractGoalTitle(session.goal || "Untitled run");

  return (
    <div
      onClick={() => window.location.assign(`/s/${session.session_id}`)}
      style={{
        display: "flex", alignItems: "flex-start", gap: 9,
        padding: "8px 10px", borderRadius: 7, cursor: "pointer",
        transition: "background 0.1s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--s2, rgba(0,0,0,0.04))"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      <span style={{
        marginTop: 5, width: 7, height: 7, borderRadius: "50%",
        flexShrink: 0, background: dot,
        ...(running ? { animation: "rg-pulse 1.5s ease-in-out infinite" } : {}),
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, fontWeight: 500,
          color: done || failed ? "var(--fd)" : "var(--fg)",
          lineHeight: 1.4,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          textDecoration: done ? "line-through" : "none",
        }}>
          {title}
        </div>
        <div style={{ fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-code)", marginTop: 2 }}>
          {ago(session.created_at)}
        </div>
      </div>
    </div>
  );
}

export default function RunGoalsPanel({ sessions }: Props) {
  if (sessions === null) {
    return <div style={{ fontSize: 11, color: "var(--fm)", padding: "6px 2px" }}>Loading…</div>;
  }

  // Only show top-level sessions (no follow-up children)
  const tops = sessions.filter(s => !s.parent_session_id && s.stack_id !== "custom");

  const active = tops.filter(s => s.status === "running" || s.status === "stalled");
  const recent = tops.filter(s => s.status !== "running" && s.status !== "stalled").slice(0, 8);

  if (tops.length === 0) {
    return (
      <div style={{
        border: "1px dashed var(--bd2)", borderRadius: 8,
        padding: "20px 14px", textAlign: "center",
        fontSize: 12, color: "var(--fm)", lineHeight: 1.5,
      }}>
        No runs yet. Start a run to set your first goal.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <style>{`@keyframes rg-pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:0.45; transform:scale(0.75); } }`}</style>

      {active.length > 0 && (
        <div>
          <SecLabel>Active</SecLabel>
          <div style={{ border: "1px solid var(--bd)", borderRadius: 8, overflow: "hidden", background: "var(--surface)" }}>
            {active.map((s, i) => (
              <div key={s.session_id} style={{ borderTop: i > 0 ? "1px solid var(--bd)" : "none" }}>
                <GoalRow session={s} />
              </div>
            ))}
          </div>
        </div>
      )}

      {recent.length > 0 && (
        <div>
          <SecLabel>Recent</SecLabel>
          <div style={{ border: "1px solid var(--bd)", borderRadius: 8, overflow: "hidden", background: "var(--surface)" }}>
            {recent.map((s, i) => (
              <div key={s.session_id} style={{ borderTop: i > 0 ? "1px solid var(--bd)" : "none" }}>
                <GoalRow session={s} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
