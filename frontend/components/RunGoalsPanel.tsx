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

function GoalRow({ session, last }: { session: SessionIndexEntry; last: boolean }) {
  const running = session.status === "running";
  const stalled = session.status === "stalled";
  const done = session.status === "done";
  const failed = session.status === "error" || session.status === "killed";

  const dot = running ? "#002EFF"
    : stalled ? "#d97706"
    : done    ? "#16a34a"
    : failed  ? "#dc2626"
    : "#a3a3a3";

  const title = extractGoalTitle(session.goal || "Untitled run");
  const faded = done || failed;

  return (
    <div
      onClick={() => window.location.assign(`/s/${session.session_id}`)}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "10px 16px",
        borderBottom: last ? "none" : "1px solid var(--bd)",
        cursor: "pointer",
        opacity: faded ? 0.6 : 1,
        transition: "background 0.1s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--s2, rgba(0,0,0,0.035))"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      <span style={{
        marginTop: 5, width: 7, height: 7, borderRadius: "50%",
        flexShrink: 0, background: dot,
        ...(running ? { animation: "rg-pulse 1.5s ease-in-out infinite" } : {}),
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12.5, fontWeight: 500,
          color: "var(--fg)", lineHeight: 1.4,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          textDecoration: faded ? "line-through" : "none",
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
  const total = tops.length;
  const allDone = total > 0 && doneCount === total;
  const hasActive = active.length > 0;

  const r = 30;
  const circ = 2 * Math.PI * r;
  const offset = total > 0 ? circ * (1 - doneCount / total) : circ;
  const ringColor = hasActive ? "#002EFF" : "#16a34a";

  const rows = [...active, ...completed.slice(0, 6)];

  if (tops.length === 0) {
    return (
      <div style={{
        border: "1px dashed var(--bd2)", borderRadius: 10,
        padding: "20px 14px", textAlign: "center",
        fontSize: 12, color: "var(--fm)", lineHeight: 1.5,
      }}>
        No runs yet. Start a run to set your first goal.
      </div>
    );
  }

  const summaryText = allDone
    ? "All goals complete"
    : doneCount === 0
    ? "Getting started"
    : `${doneCount} of ${total} complete`;

  const subText = hasActive
    ? `${active.length} running`
    : allDone
    ? `${total} total`
    : `${total - doneCount} remaining`;

  return (
    <div style={{ border: "1px solid var(--bd2)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <style>{`@keyframes rg-pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:0.45; transform:scale(0.75); } }`}</style>

      {/* Header: ring + summary */}
      <div style={{ padding: "14px 16px 12px", display: "flex", alignItems: "center", gap: 14, borderBottom: rows.length ? "1px solid var(--bd)" : "none" }}>
        {/* Arc ring */}
        <div style={{ position: "relative", width: 68, height: 68, flexShrink: 0 }}>
          <svg width={68} height={68} viewBox="0 0 76 76" style={{ transform: "rotate(-90deg)" }}>
            <circle cx={38} cy={38} r={r} fill="none" stroke="var(--bd)" strokeWidth={5} />
            <circle
              cx={38} cy={38} r={r} fill="none"
              stroke={ringColor}
              strokeWidth={5}
              strokeDasharray={circ}
              strokeDashoffset={offset}
              strokeLinecap="round"
              style={{ transition: "stroke-dashoffset .6s ease, stroke .4s ease" }}
            />
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: ringColor, fontFamily: "var(--font-code)", lineHeight: 1 }}>{doneCount}</div>
            <div style={{ fontSize: 9, color: "var(--fm)", letterSpacing: ".04em" }}>/ {total}</div>
          </div>
        </div>

        {/* Summary text */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: ringColor, lineHeight: 1.3 }}>
            {summaryText}
          </div>
          <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 4 }}>
            {subText}
          </div>
        </div>
      </div>

      {/* Goal rows */}
      {rows.map((s, i) => (
        <GoalRow key={s.session_id} session={s} last={i === rows.length - 1} />
      ))}
    </div>
  );
}
