"use client";

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

function ArcRing({ done, total }: { done: number; total: number }) {
  const r = 30;
  const circ = 2 * Math.PI * r;
  const pct = total > 0 ? done / total : 0;
  const offset = circ * (1 - pct);
  const allDone = total > 0 && done === total;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
      <div style={{ position: "relative", width: 76, height: 76, flexShrink: 0 }}>
        <svg width={76} height={76} viewBox="0 0 76 76" style={{ transform: "rotate(-90deg)" }}>
          <circle cx={38} cy={38} r={r} fill="none" stroke="var(--bd)" strokeWidth={5} />
          <circle
            cx={38} cy={38} r={r} fill="none"
            stroke={allDone ? "var(--green)" : "var(--blue)"}
            strokeWidth={5}
            strokeDasharray={circ}
            strokeDashoffset={total === 0 ? circ : offset}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset .6s ease" }}
          />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: allDone ? "var(--green)" : "var(--fg)", fontFamily: "var(--font-code)", lineHeight: 1 }}>{done}</div>
          <div style={{ fontSize: 9, color: "var(--fm)", letterSpacing: ".04em" }}>/ {total}</div>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", lineHeight: 1.3 }}>
          {allDone ? "All goals complete" : total === 0 ? "No goals yet" : done === 0 ? "Getting started" : `${done} of ${total} done`}
        </div>
        <div style={{ fontSize: 10.5, color: "var(--fm)", marginTop: 3 }}>
          {total - done > 0 ? `${total - done} in progress` : ""}
        </div>
      </div>
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
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "8px 14px", cursor: "pointer",
        opacity: (done || failed) ? 0.65 : 1,
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
          color: "var(--fg)", lineHeight: 1.4,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          textDecoration: (done || failed) ? "line-through" : "none",
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

  const tops = sessions.filter(s => !s.parent_session_id && s.stack_id !== "custom");
  const active = tops.filter(s => s.status === "running" || s.status === "stalled");
  const completed = tops.filter(s => s.status !== "running" && s.status !== "stalled");
  const doneCount = tops.filter(s => s.status === "done").length;

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

  // Ordered list: active first, then completed (most recent 6)
  const rows = [...active, ...completed.slice(0, 6)];

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <style>{`@keyframes rg-pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:0.45; transform:scale(0.75); } }`}</style>

      <ArcRing done={doneCount} total={tops.length} />

      <div style={{ border: "1px solid var(--bd2)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
        {rows.map((s, i) => (
          <div key={s.session_id} style={{ borderTop: i > 0 ? "1px solid var(--bd)" : "none" }}>
            <GoalRow session={s} />
          </div>
        ))}
      </div>
    </div>
  );
}
