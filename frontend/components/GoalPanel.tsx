"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useCompany } from "@/lib/company-context";
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
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 14px",
      borderBottom: last ? "none" : "1px solid var(--bd)",
    }}>
      <span style={{ marginTop: 5, width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: dot }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, color: task.status === "done" ? "var(--fd)" : "var(--fg)",
          textDecoration: task.status === "done" ? "line-through" : "none", lineHeight: 1.4,
        }}>
          {task.title}
        </div>
        {owners.length > 0 && (
          <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 2, fontFamily: "var(--font-code)" }}>
            {owners.map(o => (done.includes(o) ? `✓${AGENT_LABELS[o] ?? o}` : (AGENT_LABELS[o] ?? o))).join(" · ")}
          </div>
        )}
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

export default function GoalPanel() {
  const { founderId, companyId, activeCompany, loading: companiesLoading } = useCompany();

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showDoneGoals, setShowDoneGoals] = useState(false);
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
  const doneGoals = (goal?.goals ?? []).filter(g => g.status === "done").reverse();
  const tasks = currentEntry?.tasks ?? [];
  const tasksDone = tasks.filter(t => t.status === "done").length;
  const pct = tasks.length ? Math.round((tasksDone / tasks.length) * 100) : 0;

  const runNow = async () => {
    setBusy("run"); setErr(null);
    try {
      const r = await runCompanyCycle(founderId, companyId);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
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
      await approveNextGoal(founderId, approved, companyId);
      if (approved && goal?.root_session_id) window.location.assign(`/s/${goal.root_session_id}`);
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
          {companiesLoading || loading
            ? "Loading…"
            : !goal
              ? `${activeCompany?.name || "This company"} has no goals yet. Start a run to kick things off.`
              : "No active goal yet. Start a run to kick things off."}
        </div>
        {!loading && !err && !currentEntry && (
          <button onClick={runNow} disabled={!!busy} style={{
            padding: "9px 18px", fontSize: 12, fontWeight: 600,
            color: "#002EFF", background: "#fff",
            border: "1px solid #001AFF", cursor: "pointer",
          }}>
            {busy === "run" ? "Starting…" : "+ Start first run"}
          </button>
        )}
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

      {/* ── Active goal ── */}
      {!proposed && (
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <SecLabel>Current goal {currentEntry.kind === "launch" ? "· launch" : ""}</SecLabel>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase",
              color: paused ? "var(--amber)" : "var(--blue)",
              fontFamily: "var(--font-code)",
            }}>
              {paused ? "paused" : "operating"}
            </span>
          </div>

          <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", overflow: "hidden" }}>
            {/* Title + progress */}
            <div style={{ padding: "10px 14px", borderBottom: tasks.length ? "1px solid var(--bd)" : "none" }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)", lineHeight: 1.35, flex: 1 }}>
                  {currentEntry.title}
                </div>
                {tasks.length > 0 && (
                  <div style={{ textAlign: "right", flexShrink: 0 }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: tasksDone === tasks.length ? "var(--green)" : "var(--blue)", fontFamily: "var(--font-code)", lineHeight: 1 }}>
                      {tasksDone}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                      of {tasks.length}
                    </div>
                  </div>
                )}
              </div>
              {tasks.length > 0 && (
                <div style={{ height: 3, background: "var(--bd)", overflow: "hidden", marginTop: 8 }}>
                  <div style={{ height: "100%", width: `${pct}%`, background: tasksDone === tasks.length ? "var(--green)" : "var(--blue)", transition: "width .4s" }} />
                </div>
              )}
              <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 5, fontFamily: "var(--font-code)" }}>
                ◈ {(currentEntry.credits_used ?? 0).toLocaleString()} credits
              </div>
            </div>

            {/* Tasks */}
            {tasks.map((t, i) => (
              <TaskRow key={t.id} task={t} last={i === tasks.length - 1} />
            ))}
          </div>
        </div>
      )}

      {/* ── Controls ── */}
      {!proposed && (
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={runNow} disabled={paused || !!busy} style={{
            flex: 1, padding: "8px 12px", fontSize: 12, fontWeight: 600,
            color: "#002EFF", background: "#fff", border: "1px solid #001AFF",
            cursor: paused || busy ? "not-allowed" : "pointer",
            opacity: paused || busy ? 0.5 : 1,
          }}>
            {busy === "run" ? "Starting…" : "▶ Run now"}
          </button>
          <button onClick={togglePause} disabled={!!busy} style={{
            padding: "8px 12px", fontSize: 12,
            color: "var(--fm)", background: "transparent",
            border: "1px solid var(--bd2)", cursor: busy ? "not-allowed" : "pointer",
            opacity: busy ? 0.5 : 1,
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
