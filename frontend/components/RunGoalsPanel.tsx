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

  const runningCount = tops.filter(s => s.status === "running").length;
  const stalledCount = tops.filter(s => s.status === "stalled").length;
  const doneCount    = tops.filter(s => s.status === "done").length;
  const failedCount  = tops.filter(s => s.status === "error" || s.status === "killed").length;
  const total        = tops.length;
  const allDone      = doneCount === total;
  const hasActive    = runningCount + stalledCount > 0;

  // Arc ring — identical math to original GoalPanel
  const r      = 30;
  const circ   = 2 * Math.PI * r;
  const offset = circ * (1 - doneCount / total);

  const statusLabel = runningCount > 0 ? "◈ Operating"
    : stalledCount > 0                 ? "⚠ Needs attention"
    : allDone                          ? "◎ All complete"
    :                                    "◌ No active runs";

  const rows = [
    ...tops.filter(s => s.status === "running" || s.status === "stalled"),
    ...tops.filter(s => s.status !== "running" && s.status !== "stalled").slice(0, 6),
  ];

  return (
    <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", borderRadius: 10, overflow: "hidden" }}>
      <style>{`@keyframes rg-pulse { 0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.45;transform:scale(0.75);} }`}</style>

      {/* Header — copied exactly from original GoalPanel active-goal block */}
      <div style={{ padding: "14px 16px 12px", borderBottom: rows.length ? "1px solid var(--bd)" : "none" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>

          {/* Left: label + summary + counts */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: 9, fontWeight: 700, letterSpacing: ".08em",
              textTransform: "uppercase", fontFamily: "var(--font-code)",
              marginBottom: 6, color: "var(--blue)",
            }}>
              {statusLabel}
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>
              {allDone ? "All goals complete"
                : hasActive ? `${runningCount + stalledCount} in progress`
                : `${doneCount} of ${total} done`}
            </div>
            {/* Counts row — same style as GoalPanel task counts */}
            <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
              {runningCount > 0 && <span style={{ fontSize: 10, color: "var(--blue)", fontFamily: "var(--font-code)", fontWeight: 600 }}>● {runningCount} running</span>}
              {stalledCount > 0 && <span style={{ fontSize: 10, color: "var(--amber)", fontFamily: "var(--font-code)", fontWeight: 600 }}>⚠ {stalledCount} stalled</span>}
              {doneCount > 0    && <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "var(--font-code)", fontWeight: 600 }}>✓ {doneCount} done</span>}
              {failedCount > 0  && <span style={{ fontSize: 10, color: "var(--red)", fontFamily: "var(--font-code)", fontWeight: 600 }}>✗ {failedCount} failed</span>}
              {!hasActive && doneCount === 0 && <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>◌ {total} total</span>}
            </div>
          </div>

          {/* Right: arc progress ring — pixel-for-pixel match of original GoalPanel */}
          <div style={{ position: "relative", width: 76, height: 76, flexShrink: 0 }}>
            <svg width={76} height={76} viewBox="0 0 76 76" style={{ transform: "rotate(-90deg)" }}>
              <circle cx={38} cy={38} r={r} fill="none" stroke="var(--bd)" strokeWidth={5} />
              <circle
                cx={38} cy={38} r={r} fill="none"
                stroke={allDone ? "var(--green)" : "var(--blue)"}
                strokeWidth={5}
                strokeDasharray={circ}
                strokeDashoffset={offset}
                strokeLinecap="round"
                style={{ transition: "stroke-dashoffset .6s ease" }}
              />
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: allDone ? "var(--green)" : "var(--fg)", fontFamily: "var(--font-code)", lineHeight: 1 }}>
                {doneCount}
              </div>
              <div style={{ fontSize: 9, color: "var(--fm)", letterSpacing: ".04em" }}>/ {total}</div>
            </div>
          </div>

        </div>
      </div>

      {/* Goal rows */}
      {rows.map((s, i) => {
        const running = s.status === "running";
        const done    = s.status === "done";
        const failed  = s.status === "error" || s.status === "killed";
        const faded   = done || failed;
        const dot     = running         ? "var(--blue)"
          : s.status === "stalled"      ? "var(--amber)"
          : done                        ? "var(--green)"
          : failed                      ? "var(--red)"
          : "var(--fm)";

        return (
          <div
            key={s.session_id}
            onClick={() => window.location.assign(`/s/${s.session_id}`)}
            style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "8px 14px",
              borderBottom: i < rows.length - 1 ? "1px solid var(--bd)" : "none",
              cursor: "pointer", opacity: faded ? 0.6 : 1,
              transition: "background 0.1s",
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--s2, rgba(0,0,0,0.03))"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
          >
            <span style={{
              marginTop: 5, width: 7, height: 7, borderRadius: "50%",
              flexShrink: 0, background: dot,
              ...(running ? { animation: "rg-pulse 1.5s ease-in-out infinite" } : {}),
            }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 12, color: faded ? "var(--fd)" : "var(--fg)",
                lineHeight: 1.4, textDecoration: faded ? "line-through" : "none",
                overflow: "hidden", display: "-webkit-box",
                WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
              }}>
                {extractGoalTitle(s.goal || "Untitled run")}
              </div>
              <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 2, fontFamily: "var(--font-code)" }}>
                {ago(s.created_at)}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
