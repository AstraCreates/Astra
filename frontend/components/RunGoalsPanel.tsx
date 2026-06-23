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
  const done = session.status === "done";
  const failed = session.status === "error" || session.status === "killed";
  const faded = done || failed;

  const dot = running ? "#002EFF"
    : session.status === "stalled" ? "#d97706"
    : done    ? "#16a34a"
    : failed  ? "#dc2626"
    : "#a3a3a3";

  return (
    <div
      onClick={() => window.location.assign(`/s/${session.session_id}`)}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "8px 14px",
        borderBottom: last ? "none" : "1px solid var(--bd)",
        cursor: "pointer", opacity: faded ? 0.55 : 1,
        transition: "background 0.1s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(0,0,0,0.03)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      <span style={{
        marginTop: 5, width: 7, height: 7, borderRadius: "50%",
        flexShrink: 0, background: dot,
        ...(running ? { animation: "rg-pulse 1.5s ease-in-out infinite" } : {}),
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, fontWeight: 500, color: "var(--fg)", lineHeight: 1.4,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          textDecoration: faded ? "line-through" : "none",
        }}>
          {extractGoalTitle(session.goal || "Untitled run")}
        </div>
        <div style={{ fontSize: 10, color: "#a3a3a3", fontFamily: "var(--font-code), monospace", marginTop: 2 }}>
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

  const tops = sessions.filter(s => !s.parent_session_id);

  if (tops.length === 0) {
    return (
      <div style={{ border: "1px dashed var(--bd2)", borderRadius: 10, padding: "20px 14px", textAlign: "center", fontSize: 12, color: "var(--fm)" }}>
        No runs yet. Start a run to set your first goal.
      </div>
    );
  }

  const runningCount  = tops.filter(s => s.status === "running").length;
  const stalledCount  = tops.filter(s => s.status === "stalled").length;
  const doneCount     = tops.filter(s => s.status === "done").length;
  const failedCount   = tops.filter(s => s.status === "error" || s.status === "killed").length;
  const total         = tops.length;
  const hasActive     = runningCount + stalledCount > 0;

  // Arc ring math
  const r    = 30;
  const circ = 2 * Math.PI * r;
  const offset = total > 0 ? circ * (1 - doneCount / total) : circ;

  // Status label
  const statusLabel = runningCount > 0  ? "◈ Operating"
    : stalledCount > 0 ? "⚠ Needs attention"
    : doneCount === total ? "◎ All complete"
    : "◌ No active runs";

  const statusColor = runningCount > 0 ? "#002EFF"
    : stalledCount > 0 ? "#d97706"
    : "#16a34a";

  const rows = [
    ...tops.filter(s => s.status === "running" || s.status === "stalled"),
    ...tops.filter(s => s.status !== "running" && s.status !== "stalled").slice(0, 6),
  ];

  return (
    <div style={{ border: "1px solid var(--bd2)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <style>{`@keyframes rg-pulse { 0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.45;transform:scale(0.75);} }`}</style>

      {/* Header — text LEFT, ring RIGHT (same layout as original GoalPanel) */}
      <div style={{ padding: "14px 16px 12px", borderBottom: rows.length ? "1px solid var(--bd)" : "none" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>

          {/* LEFT: labels + stats */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* Status label */}
            <div style={{
              fontSize: 9, fontWeight: 700, letterSpacing: ".08em",
              textTransform: "uppercase",
              fontFamily: "var(--font-code), monospace",
              color: statusColor, marginBottom: 6,
            }}>
              {statusLabel}
            </div>

            {/* Title */}
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3, marginBottom: 8 }}>
              {doneCount === total
                ? "All goals complete"
                : doneCount === 0 && !hasActive
                ? "No runs completed yet"
                : hasActive
                ? `${runningCount + stalledCount} goal${runningCount + stalledCount > 1 ? "s" : ""} in progress`
                : `${doneCount} of ${total} complete`}
            </div>

            {/* Stat rows — code font, same style as GoalPanel */}
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {runningCount > 0 && (
                <div style={{ fontSize: 10, fontFamily: "var(--font-code), monospace", color: "#002EFF", fontWeight: 600 }}>
                  ● {runningCount} running
                </div>
              )}
              {stalledCount > 0 && (
                <div style={{ fontSize: 10, fontFamily: "var(--font-code), monospace", color: "#d97706", fontWeight: 600 }}>
                  ⚠ {stalledCount} stalled
                </div>
              )}
              {doneCount > 0 && (
                <div style={{ fontSize: 10, fontFamily: "var(--font-code), monospace", color: "#16a34a", fontWeight: 600 }}>
                  ✓ {doneCount} done
                </div>
              )}
              {failedCount > 0 && (
                <div style={{ fontSize: 10, fontFamily: "var(--font-code), monospace", color: "#dc2626", fontWeight: 600 }}>
                  ✗ {failedCount} failed
                </div>
              )}
              <div style={{ fontSize: 10, fontFamily: "var(--font-code), monospace", color: "#a3a3a3" }}>
                ◌ {total} total
              </div>
            </div>
          </div>

          {/* RIGHT: arc progress ring — exactly like original GoalPanel */}
          <div style={{ position: "relative", width: 76, height: 76, flexShrink: 0 }}>
            <svg width={76} height={76} viewBox="0 0 76 76" style={{ transform: "rotate(-90deg)" }}>
              <circle cx={38} cy={38} r={r} fill="none" stroke="var(--bd)" strokeWidth={5} />
              <circle
                cx={38} cy={38} r={r} fill="none"
                stroke="#002EFF"
                strokeWidth={5}
                strokeDasharray={circ}
                strokeDashoffset={offset}
                strokeLinecap="round"
                style={{ transition: "stroke-dashoffset .6s ease" }}
              />
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: "#002EFF", fontFamily: "var(--font-code), monospace", lineHeight: 1 }}>
                {doneCount}
              </div>
              <div style={{ fontSize: 9, color: "var(--fm)", letterSpacing: ".04em", fontFamily: "var(--font-code), monospace" }}>
                / {total}
              </div>
            </div>
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
