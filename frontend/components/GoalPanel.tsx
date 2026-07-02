"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useCompany } from "@/lib/company-context";
import { useDevUser } from "@/lib/use-dev-user";
import {
  getCompanyGoal, runCompanyCycle, approveNextGoal, setCompanyGoalStatus,
  AGENT_LABELS,
  type CompanyGoal, type CompanyGoalEntry, type CompanyTask,
} from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const STATUS_DOT: Record<string, string> = {
  done:               "var(--green)",
  in_progress:        "var(--blue)",
  awaiting_approval:  "var(--amber)",
  blocked:            "var(--red)",
  pending:            "var(--fm)",
};

// ── Task row ───────────────────────────────────────────────────────────────

function TaskRow({ task, last }: { task: CompanyTask; last: boolean }) {
  const dot = STATUS_DOT[task.status] ?? "var(--fm)";
  const owners = task.owner_agents ?? [];
  const done = task.done_agents ?? [];
  const label = task.status === "awaiting_approval" ? "approval" : task.status.replace(/_/g, " ");
  const isDone = task.status === "done";
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 14px",
      borderBottom: last ? "none" : "1px solid var(--bd)",
    }}>
      <span style={{ marginTop: 5, width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: dot }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, color: isDone ? "var(--fd)" : "var(--fg)",
          textDecoration: isDone ? "line-through" : "none", lineHeight: 1.4,
        }}>
          {task.title}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
          {owners.length > 0 && (
            <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>
              {owners.map(o => (done.includes(o) ? `✓${AGENT_LABELS[o] ?? o}` : (AGENT_LABELS[o] ?? o))).join(" · ")}
            </span>
          )}
          {isDone && task.last_run_id && (
            <a
              href={`/library?session=${task.last_run_id}`}
              style={{ fontSize: 10, color: "#001AFF", textDecoration: "none", fontWeight: 500, opacity: 0.75 }}
              onMouseEnter={e => { e.currentTarget.style.opacity = "1"; e.currentTarget.style.textDecoration = "underline"; }}
              onMouseLeave={e => { e.currentTarget.style.opacity = "0.75"; e.currentTarget.style.textDecoration = "none"; }}
            >
              View deliverable →
            </a>
          )}
        </div>
      </div>
      <span style={{
        flexShrink: 0, fontSize: 9, color: dot, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: ".06em", fontFamily: "var(--font-code)",
      }}>
        {label}
      </span>
    </div>
  );
}

// ── Section label ──────────────────────────────────────────────────────────

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

// ── Main component ─────────────────────────────────────────────────────────

export default function GoalPanel({ defaultShowDone = false }: { defaultShowDone?: boolean }) {
  const { founderId, companyId, activeCompany, loading: companiesLoading } = useCompany();
  const { isSignedIn } = useDevUser();

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showDoneGoals, setShowDoneGoals] = useState(defaultShowDone);
  const loadRequest = useRef(0);

  const loadGoal = useCallback(async () => {
    if (!founderId) return;
    const requestId = ++loadRequest.current;
    setLoading(true);
    setErr(null);
    try {
      const nextGoal = await getCompanyGoal(founderId, companyId);
      if (loadRequest.current === requestId) setGoal(nextGoal);
    } catch (error) {
      if (loadRequest.current === requestId) {
        setGoal(null);
        setErr(error instanceof Error ? error.message : "Could not load goals.");
      }
    } finally {
      if (loadRequest.current === requestId) setLoading(false);
    }
  }, [companyId, founderId]);

  useEffect(() => {
    if (!founderId || companiesLoading) return;
    const initial = window.setTimeout(() => {
      setGoal(null);
      void loadGoal();
    }, 0);
    const t = window.setInterval(() => void loadGoal(), 15_000);
    return () => {
      loadRequest.current += 1;
      clearTimeout(initial);
      clearInterval(t);
    };
  }, [companiesLoading, founderId, loadGoal]);

  const paused = goal?.status === "paused";
  const currentEntry: CompanyGoalEntry | null = goal?.goals?.find(g => g.id === goal.current_goal_id) ?? null;
  const proposed = currentEntry?.status === "proposed";
  const hasActiveSession = goal?.has_active_session ?? false;
  const doneGoals = (goal?.goals ?? []).filter(g => g.status === "done").reverse();
  const tasks = currentEntry?.tasks ?? [];
  const tasksDone = tasks.filter(t => t.status === "done").length;
  const pct = tasks.length ? Math.round((tasksDone / tasks.length) * 100) : 0;

  const runNow = async () => {
    setBusy("run"); setErr(null);
    try {
      const r = await runCompanyCycle(founderId, companyId);
      const dest = r.session_id || r.parent_session_id;
      if (dest) window.location.assign(`/s/${dest}`);
      else await loadGoal();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setErr(null), 8000); }
    finally { setBusy(null); }
  };

  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused", companyId); await loadGoal(); }
    finally { setBusy(null); }
  };

  const decideGoal = async (approved: boolean) => {
    setBusy(approved ? "approve" : "reject"); setErr(null);
    try {
      const r = await approveNextGoal(founderId, approved, companyId);
      const dest = approved && (r?.session_id || goal?.root_session_id);
      if (dest) window.location.assign(`/s/${dest}`);
      else await loadGoal();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setErr(null), 8000); }
    finally { setBusy(null); }
  };

  // ── Empty / no goal ──────────────────────────────────────────────────────
  if (!goal || !currentEntry) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <SecLabel>Current goal</SecLabel>
        {err && (
          <div style={{ fontSize: 11, color: "var(--red)", padding: "8px 10px", background: "var(--rdim)", border: "1px solid var(--rb)", lineHeight: 1.5 }}>
            Could not load goals.
            <button onClick={() => void loadGoal()} style={{ marginLeft: 8, padding: 0, border: "none", background: "none", color: "inherit", font: "inherit", fontWeight: 700, cursor: "pointer", textDecoration: "underline" }}>
              Try again
            </button>
          </div>
        )}
        <div style={{
          border: "1px dashed var(--bd2)", padding: "18px 16px",
          fontSize: 12, color: "var(--fm)", lineHeight: 1.6, textAlign: "center",
        }}>
          {!isSignedIn
            ? "Sign in to see company goals."
            : companiesLoading || loading
            ? "Loading…"
            : !goal
              ? `${activeCompany?.name || "This company"} has no goals yet. Start a run to kick things off.`
              : "No active goal yet. Start a run to kick things off."}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {err && (
        <div style={{ fontSize: 11, color: "var(--red)", padding: "6px 10px", background: "var(--rdim)", border: "1px solid var(--rb)" }}>
          {err}
        </div>
      )}

      {/* ── Proposed goal ── */}
      {proposed && (
        <div>
          <SecLabel>▲ Proposed · awaiting your approval</SecLabel>
          <div style={{ border: "1px solid var(--ab)", background: "var(--adim)", overflow: "hidden" }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--ab)" }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)", lineHeight: 1.4 }}>
                {currentEntry.title}
              </div>
              <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 4, lineHeight: 1.5 }}>
                Planner proposed this after your last goal. Approve to start.
              </div>
            </div>
            {tasks.map((t, i) => (
              <div key={t.id} style={{ display: "flex", alignItems: "flex-start", gap: 9, padding: "7px 14px", borderTop: i > 0 ? "1px solid var(--bd)" : "none" }}>
                <span style={{ marginTop: 5, width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: "var(--amber)" }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11.5, color: "var(--fg)", lineHeight: 1.4 }}>{t.title}</div>
                  {(t.owner_agents?.length ?? 0) > 0 && (
                    <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 1, fontFamily: "var(--font-code)" }}>
                      {t.owner_agents!.map(a => AGENT_LABELS[a] ?? a).join(" · ")}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, padding: "10px 14px", borderTop: "1px solid var(--ab)" }}>
              <button onClick={() => decideGoal(true)} disabled={!!busy} style={{
                flex: 1, padding: "8px 12px", fontSize: 12, fontWeight: 600,
                color: "#fff", background: "var(--amber)",
                border: "none", cursor: busy ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}>
                {busy === "approve" ? "Starting…" : "✓ Approve & start"}
              </button>
              <button onClick={() => decideGoal(false)} disabled={!!busy} style={{
                padding: "8px 12px", fontSize: 12,
                color: "var(--fm)", background: "transparent",
                border: "1px solid var(--bd2)", cursor: busy ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}>
                {busy === "reject" ? "…" : "Reject"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Active goal — Option C: arc ring + pill chips ── */}
      {!proposed && (
        <div>
          <div style={{ border: `1px solid ${currentEntry.status === "done" ? "var(--bd)" : "var(--bd2)"}`, background: "var(--surface)", borderRadius: 10, overflow: "hidden" }}>
            {/* Header: status badge + arc ring */}
            <div style={{ padding: "14px 16px 12px", borderBottom: tasks.length ? "1px solid var(--bd)" : "none" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                {/* Left: label + title + credits */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", fontFamily: "var(--font-code)", marginBottom: 6,
                    color: currentEntry.status === "done" ? "var(--green)" : paused ? "var(--amber)" : !hasActiveSession ? "var(--fm)" : "var(--blue)" }}>
                    {currentEntry.status === "done"
                      ? "✓ Completed"
                      : paused ? "⏸ Paused"
                      : !hasActiveSession ? "◌ Idle — no run active"
                      : currentEntry.kind === "launch" ? "◎ Launch goal" : "◈ Operating"}
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>
                    {currentEntry.title}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 5, fontFamily: "var(--font-code)" }}>
                    ◈ {(currentEntry.credits_used ?? 0).toLocaleString()} credits used
                  </div>
                </div>
                {/* Right: arc progress ring */}
                {tasks.length > 0 && (() => {
                  const r = 30;
                  const circ = 2 * Math.PI * r;
                  const offset = circ * (1 - pct / 100);
                  const allDone = tasksDone === tasks.length || currentEntry.status === "done";
                  const ringColor = allDone ? "var(--green)" : !hasActiveSession ? "var(--fm)" : "var(--blue)";
                  return (
                    <div style={{ position: "relative", width: 76, height: 76, flexShrink: 0 }}>
                      <svg width={76} height={76} viewBox="0 0 76 76" style={{ transform: "rotate(-90deg)" }}>
                        <circle cx={38} cy={38} r={r} fill="none" stroke="var(--bd)" strokeWidth={5} />
                        <circle
                          cx={38} cy={38} r={r} fill="none"
                          stroke={ringColor}
                          strokeWidth={5}
                          strokeDasharray={circ}
                          strokeDashoffset={offset}
                          strokeLinecap="round"
                          style={{ transition: "stroke-dashoffset .6s ease" }}
                        />
                      </svg>
                      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                        <div style={{ fontSize: 22, fontWeight: 800, color: ringColor, fontFamily: "var(--font-code)", lineHeight: 1 }}>{tasksDone}</div>
                        <div style={{ fontSize: 9, color: "var(--fm)", letterSpacing: ".04em" }}>/ {tasks.length}</div>
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Task summary */}
            {tasks.length > 0 && (
              <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                {/* Active tasks only — as slim rows */}
                {tasks.filter(t => t.status === "in_progress" || t.status === "awaiting_approval").map(t => (
                  <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: t.status === "awaiting_approval" ? "var(--amber)" : "var(--blue)" }} />
                    <span style={{ fontSize: 11.5, color: "var(--fg)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</span>
                    {t.status === "awaiting_approval" && <span style={{ fontSize: 9, color: "var(--amber)", fontWeight: 700, fontFamily: "var(--font-code)", flexShrink: 0 }}>APPROVAL</span>}
                  </div>
                ))}
                {/* Compact counts row */}
                <div style={{ display: "flex", gap: 12, paddingTop: tasks.filter(t => t.status === "in_progress" || t.status === "awaiting_approval").length ? 4 : 0 }}>
                  {tasksDone > 0 && <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "var(--font-code)", fontWeight: 600 }}>✓ {tasksDone} done</span>}
                  {tasks.filter(t => t.status === "pending").length > 0 && <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>◌ {tasks.filter(t => t.status === "pending").length} queued</span>}
                  {tasks.filter(t => t.status === "blocked").length > 0 && <span style={{ fontSize: 10, color: "var(--red)", fontFamily: "var(--font-code)", fontWeight: 600 }}>✗ {tasks.filter(t => t.status === "blocked").length} blocked</span>}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Controls ── */}
      {!proposed && (
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={runNow} disabled={paused || !!busy} style={{
            flex: 1, padding: "9px 14px", fontSize: 12, fontWeight: 600,
            color: "#002EFF", background: "#fff", border: "1px solid #001AFF",
            borderRadius: 8, cursor: paused || busy ? "not-allowed" : "pointer",
            opacity: paused || busy ? 0.5 : 1,
            fontFamily: "var(--font-instrument), sans-serif",
          }}>
            {busy === "run" ? "Starting…" : "▶ Run now"}
          </button>
          <button onClick={togglePause} disabled={!!busy} style={{
            padding: "9px 14px", fontSize: 12,
            color: "var(--fm)", background: "transparent",
            border: "1px solid var(--bd2)", borderRadius: 8,
            cursor: busy ? "not-allowed" : "pointer",
            opacity: busy ? 0.5 : 1,
            fontFamily: "var(--font-instrument), sans-serif",
          }}>
            {busy === "pause" ? "…" : paused ? "Resume" : "Pause"}
          </button>
        </div>
      )}

      {/* ── Done goals ── */}
      {doneGoals.length > 0 && (
        <div>
          <button
            onClick={() => setShowDoneGoals(v => !v)}
            style={{
              display: "flex", alignItems: "center", gap: 7, width: "100%",
              border: "none", background: "transparent", cursor: "pointer",
              padding: "0 0 8px", textAlign: "left",
            }}
          >
            <SecLabel>Completed goals ({doneGoals.length})</SecLabel>
            <span style={{ fontSize: 10, color: "var(--fd)", marginLeft: "auto" }}>
              {showDoneGoals ? "▼" : "▶"}
            </span>
          </button>
          {showDoneGoals && (
            <div style={{ border: "1px solid var(--bd)", overflow: "hidden" }}>
              {doneGoals.map((g, i) => (
                <div key={g.id} style={{
                  display: "flex", alignItems: "center", gap: 9,
                  padding: "7px 12px", fontSize: 12,
                  borderBottom: i < doneGoals.length - 1 ? "1px solid var(--bd)" : "none",
                }}>
                  <span style={{ color: "var(--green)", fontFamily: "var(--font-code)", fontSize: 10, flexShrink: 0 }}>✓</span>
                  <span style={{ flex: 1, color: "var(--fm)", textDecoration: "line-through", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {g.title}
                  </span>
                  <span style={{ fontSize: 9, fontFamily: "var(--font-code)", color: "var(--fd)", flexShrink: 0 }}>
                    {timeAgo(g.completed_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
