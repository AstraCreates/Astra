"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "@/components/AstraGradient";
import {
  getCompanyGoal,
  postponeCompanyTask,
  markCompanyTaskDone,
  runCompanyCycle,
  setCompanyGoalStatus,
  syncMissionNotion,
  type CompanyGoal,
  type CompanyGoalEntry,
  type CompanyTask,
} from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function currentGoalOf(goal: CompanyGoal | null): CompanyGoalEntry | null {
  if (!goal?.goals?.length) return null;
  return (
    goal.goals.find((g) => g.id === goal.current_goal_id) ||
    goal.goals.find((g) => g.status === "active") ||
    null
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

const STATUS_ICON: Record<string, string> = {
  done:              "✓",
  in_progress:       "◉",
  awaiting_approval: "▲",
  blocked:           "✕",
  postponed:         "◌",
  pending:           "○",
};

const STATUS_CLS: Record<string, string> = {
  done:              "green",
  in_progress:       "blue",
  awaiting_approval: "amber",
  blocked:           "red",
  postponed:         "amber",
};

const TASK_BG: Record<string, { bg: string; border: string }> = {
  done:              { bg: "var(--gdim)", border: "var(--gb)" },
  in_progress:       { bg: "var(--bdim)", border: "var(--bb)" },
  awaiting_approval: { bg: "var(--adim)", border: "var(--ab)" },
  blocked:           { bg: "var(--rdim)", border: "var(--rb)" },
  postponed:         { bg: "transparent", border: "var(--bd2)" },
  pending:           { bg: "transparent", border: "var(--bd)" },
};

function Badge({ label, kind }: { label: string; kind: string }) {
  const cls = STATUS_CLS[kind] ?? "";
  return <span className={`pill${cls ? " " + cls : ""}`}>{label}</span>;
}

function Btn({ label, onClick, primary, disabled, small }: {
  label: string; onClick: () => void; primary?: boolean; disabled?: boolean; small?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`btn${primary ? " pri" : ""}${small ? " sm" : ""}`}
    >
      {label}
    </button>
  );
}

const STATUS_DOT_COLOR: Record<string, string> = {
  done: "var(--green)",
  in_progress: "var(--blue)",
  awaiting_approval: "var(--amber)",
  blocked: "var(--red)",
  postponed: "var(--fm)",
  pending: "var(--fm)",
};

function TaskRow({
  t, busy, onPostpone, onMarkDone,
}: {
  t: CompanyTask;
  busy: string | null;
  onPostpone: () => void;
  onMarkDone: () => void;
}) {
  const kind = t.postponed ? "postponed" : t.status;
  const label =
    t.postponed ? "postponed"
    : t.status === "awaiting_approval" ? "needs approval"
    : t.status.replace(/_/g, " ");
  const owners = t.owner_agents ?? [];
  const doneAgents = t.done_agents ?? [];
  const dotColor = STATUS_DOT_COLOR[kind] ?? "var(--fm)";
  const isDone = t.status === "done";

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12, padding: "11px 16px",
      background: isDone ? "var(--gdim)" : kind === "in_progress" ? "var(--bdim)" : kind === "awaiting_approval" ? "var(--adim)" : "var(--surface)",
      border: `1px solid ${isDone ? "var(--gb)" : kind === "in_progress" ? "var(--bb)" : kind === "awaiting_approval" ? "var(--ab)" : "var(--bd)"}`,
      opacity: t.postponed ? 0.55 : 1,
      transition: "border-color .12s, background .12s",
    }}>
      <div style={{ marginTop: 3, width: 8, height: 8, flexShrink: 0, borderRadius: "50%", background: dotColor, boxShadow: kind === "in_progress" ? `0 0 0 3px rgba(0,46,255,0.18)` : "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: isDone ? "var(--fd)" : "var(--fg)",
            textDecoration: t.postponed || isDone ? "line-through" : "none",
          }}>
            {t.title}
          </span>
          <Badge label={label} kind={kind} />
          {owners.length > 0 && (
            <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>
              {owners.map((o) => (doneAgents.includes(o) ? `✓${o}` : o)).join(" · ")}
            </span>
          )}
        </div>
        {t.notes && (
          <div style={{
            fontSize: 11, color: "var(--fm)", marginTop: 5, lineHeight: 1.55,
            whiteSpace: "pre-wrap", fontFamily: "var(--font-code)",
          }}>
            {t.notes.slice(0, 200)}
          </div>
        )}
        {t.status !== "done" && (
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <Btn label={t.postponed ? "Resume" : "Postpone"} onClick={onPostpone} disabled={!!busy} small />
            {!t.postponed && (
              <Btn
                label={t.status === "awaiting_approval" ? "Approve ✓" : "Mark done"}
                onClick={onMarkDone}
                disabled={!!busy}
                primary
                small
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function MissionsPanel() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [operatingOpen, setOperatingOpen] = useState(true);

  const load = useCallback(async () => {
    if (!founderId) return;
    setError(null);
    try {
      setGoal(await getCompanyGoal(founderId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (!founderId) { setLoading(false); return; }
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [founderId, load]);

  const cg = currentGoalOf(goal);
  const tasks = cg?.tasks ?? [];
  const doneGoals = (goal?.goals ?? []).filter((g) => g.status === "done").reverse();
  const runs = (goal?.operating_sessions ?? []).slice().reverse().slice(0, 8);
  const paused = goal?.status === "paused";

  const postpone = async (t: CompanyTask) => {
    setBusy(t.id);
    try { await postponeCompanyTask(founderId, t.id, !t.postponed); await load(); }
    finally { setBusy(null); }
  };

  const markDone = async (t: CompanyTask) => {
    setBusy(t.id);
    try { await markCompanyTaskDone(founderId, t.id); await load(); }
    finally { setBusy(null); }
  };

  const runNow = async () => {
    setBusy("run");
    setActionErr(null);
    try {
      const r = await runCompanyCycle(founderId);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
      else await load();
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : String(e));
      setTimeout(() => setActionErr(null), 8000);
    } finally { setBusy(null); }
  };

  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused"); await load(); }
    finally { setBusy(null); }
  };

  // ── Render states ──

  const doneTasks = tasks.filter((t) => t.status === "done").length;
  const totalTasks = tasks.length;

  if (!founderId) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
        <GoalsHero goal={null} paused={false} cg={null} busy={null} runNow={() => {}} togglePause={() => {}} />
        <div className="empty" style={{ flex: 1 }}>
          <span style={{ fontSize: 22, fontFamily: "var(--font-code)", opacity: 0.25 }}>◎</span>
          <span className="empty-title">Sign in to track your launch progress.</span>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
        <GoalsHero goal={null} paused={false} cg={null} busy={null} runNow={() => {}} togglePause={() => {}} />
        <div className="empty" style={{ flex: 1 }}>
          <span style={{ fontSize: 11, fontFamily: "var(--font-code)", color: "var(--fm)" }}>Loading…</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`
        @keyframes goals-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .goal-row-enter { animation: goals-fade 0.24s cubic-bezier(0.22,1,0.36,1) both; }
        .run-row:hover { border-color: var(--bb) !important; background: var(--bdim) !important; }
        @media (prefers-reduced-motion: reduce) { .goal-row-enter { animation: none; opacity: 1; } }
      `}</style>

      {/* ── Blue hero header ── */}
      <div style={{
        position: "relative", overflow: "hidden", flexShrink: 0,
        background: "#001aff", minHeight: 148,
        borderBottom: "1px solid var(--bd)",
      }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2, padding: "28px 24px 22px" }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 26, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em", marginBottom: 6 }}>
                Company Goals
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {goal ? (
                  <>
                    <span style={{
                      padding: "3px 10px", fontSize: 10, fontWeight: 700, letterSpacing: ".06em",
                      textTransform: "uppercase", fontFamily: "var(--font-code)",
                      border: paused ? "1px solid rgba(255,180,50,0.45)" : "1px solid rgba(124,255,198,0.45)",
                      background: paused ? "rgba(255,180,50,0.14)" : "rgba(124,255,198,0.14)",
                      color: paused ? "#FFCB50" : "#7CFFC6",
                    }}>
                      {paused ? "paused" : "operating"}
                    </span>
                    {totalTasks > 0 && (
                      <span style={{ fontSize: 11, color: "rgba(255,255,255,0.72)", fontFamily: "var(--font-code)" }}>
                        {doneTasks}/{totalTasks} tasks done
                      </span>
                    )}
                    {runs.length > 0 && (
                      <span style={{ fontSize: 11, color: "rgba(255,255,255,0.55)" }}>
                        · {runs.length} operating run{runs.length !== 1 ? "s" : ""}
                      </span>
                    )}
                  </>
                ) : (
                  <span style={{ fontSize: 11, color: "rgba(255,255,255,0.55)" }}>No active goal</span>
                )}
              </div>
            </div>
            {goal && (
              <div style={{ display: "flex", gap: 9, flexShrink: 0 }}>
                <button
                  onClick={runNow}
                  disabled={paused || !cg || !!busy}
                  style={{
                    padding: "9px 20px", fontSize: 12, fontWeight: 600, color: "#002EFF",
                    background: "#fff", border: "none", cursor: "pointer",
                    letterSpacing: "0.01em", opacity: (paused || !cg || !!busy) ? 0.5 : 1,
                  }}
                >
                  {busy === "run" ? "Starting…" : "▶ Run now"}
                </button>
                <button
                  onClick={togglePause}
                  disabled={!!busy}
                  style={{
                    padding: "9px 16px", fontSize: 12, fontWeight: 500,
                    color: "rgba(255,255,255,0.88)", background: "rgba(255,255,255,0.13)",
                    border: "1px solid rgba(255,255,255,0.28)", cursor: "pointer",
                    opacity: !!busy ? 0.5 : 1,
                  }}
                >
                  {paused ? "Resume" : "Pause"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px 48px" }}>

        {error && (
          <div className="err-banner" style={{ marginBottom: 18 }}>
            {error}
            <button onClick={load} style={{ marginLeft: 8, textDecoration: "underline", background: "none", border: "none", color: "var(--red)", cursor: "pointer", fontFamily: "var(--font-code)", fontSize: 11 }}>
              Retry
            </button>
          </div>
        )}

        {actionErr && (
          <div className="err-banner" style={{ marginBottom: 18 }}>{actionErr}</div>
        )}

        {/* ── Empty state ── */}
        {!goal && !loading && (
          <div style={{ padding: "64px 24px", textAlign: "center", border: "1px dashed var(--bd2)" }}>
            <div style={{ fontSize: 28, marginBottom: 14, fontFamily: "var(--font-code)", color: "var(--fm)", opacity: 0.25 }}>◎</div>
            <div className="empty-title" style={{ marginBottom: 8 }}>No run started yet</div>
            <p style={{ fontSize: 12, color: "var(--fm)", maxWidth: 340, margin: "0 auto 20px", lineHeight: 1.65 }}>
              Start a run from the home screen — Astra auto-completes tasks as agents work.
            </p>
            <a href="/" className="btn pri" style={{ textDecoration: "none", display: "inline-block" }}>Start a run →</a>
          </div>
        )}

        {goal && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 820 }}>

            {/* ── North star ── */}
            {goal.north_star && (
              <div className="goal-row-enter" style={{ padding: "14px 18px", background: "var(--bdim)", border: "1px solid var(--bb)" }}>
                <div className="sec-label" style={{ color: "var(--blue)", marginBottom: 6 }}>North Star</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)", lineHeight: 1.6 }}>
                  {goal.north_star}
                </div>
                {goal.notion_url && (
                  <a href={goal.notion_url} target="_blank" rel="noreferrer"
                    style={{ fontSize: 11, color: "var(--blue)", marginTop: 8, display: "inline-block", fontFamily: "var(--font-code)" }}>
                    Open in Notion →
                  </a>
                )}
              </div>
            )}

            {/* ── Current goal + tasks ── */}
            {cg ? (
              <div className="goal-row-enter" style={{ border: "1px solid var(--bd2)", background: "var(--surface)" }}>
                <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <div className="sec-label" style={{ marginBottom: 5 }}>
                      Current goal{cg.kind === "launch" ? " · launch" : ""}
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", letterSpacing: "-0.01em" }}>
                      {cg.title}
                    </div>
                  </div>
                  {totalTasks > 0 && (
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ fontSize: 22, fontWeight: 700, color: doneTasks === totalTasks ? "var(--green)" : "var(--fg)", fontFamily: "var(--font-code)", lineHeight: 1 }}>{doneTasks}</div>
                      <div style={{ fontSize: 9, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".08em" }}>of {totalTasks} done</div>
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                  {tasks.map((t, i) => (
                    <div key={t.id} className="goal-row-enter" style={{ animationDelay: `${i * 30}ms`, borderBottom: i < tasks.length - 1 ? "1px solid var(--bd)" : "none" }}>
                      <TaskRow
                        t={t}
                        busy={busy}
                        onPostpone={() => postpone(t)}
                        onMarkDone={() => markDone(t)}
                      />
                    </div>
                  ))}
                  {tasks.length === 0 && (
                    <div style={{ padding: "16px 18px", fontSize: 12, color: "var(--fm)" }}>
                      No tasks on this goal yet.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ padding: "16px 18px", border: "1px solid var(--bd)", background: "var(--s2)", fontSize: 12, color: "var(--fm)" }}>
                No active goal — planner sets the next one when the current run finishes.
              </div>
            )}

            {/* ── Actions row ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                onClick={async () => {
                  setBusy("notion");
                  try { await syncMissionNotion(founderId); await load(); }
                  catch (e) { setActionErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setActionErr(null), 8000); }
                  finally { setBusy(null); }
                }}
                disabled={!!busy}
                className="btn"
              >
                {busy === "notion" ? "Syncing…" : "Sync Notion"}
              </button>
              <button onClick={load} disabled={!!busy} className="btn" style={{ color: "var(--fm)" }}>Refresh</button>
            </div>

            {/* ── Recent runs ── */}
            {runs.length > 0 && (
              <div className="goal-row-enter">
                <div className="sec-label" style={{ marginBottom: 10 }}>Recent runs · {runs.length}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {runs.map((r) => (
                    <a
                      key={r.session_id}
                      href={`/s/${r.session_id}`}
                      className="run-row"
                      style={{
                        display: "flex", alignItems: "center", gap: 12,
                        padding: "10px 14px",
                        border: "1px solid var(--bd)",
                        background: "var(--surface)",
                        textDecoration: "none",
                        transition: "border-color .12s, background .12s",
                      }}
                    >
                      <div style={{
                        width: 7, height: 7, flexShrink: 0,
                        borderRadius: "50%",
                        background: r.status === "done" ? "var(--green)" : r.status === "error" ? "var(--red)" : "var(--blue)",
                      }} />
                      <span style={{
                        flex: 1, minWidth: 0, fontSize: 12, fontWeight: 500, color: "var(--fg)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {r.summary || "Operating run"}
                      </span>
                      <Badge
                        label={r.status}
                        kind={r.status === "done" ? "done" : r.status === "error" ? "blocked" : "in_progress"}
                      />
                      <span style={{ fontSize: 10, color: "var(--fm)", whiteSpace: "nowrap", fontFamily: "var(--font-code)" }}>
                        {timeAgo(r.started_at)}
                      </span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* ── Completed goals ── */}
            {doneGoals.length > 0 && (
              <div className="goal-row-enter">
                <div className="sec-label" style={{ marginBottom: 10 }}>Completed goals · {doneGoals.length}</div>
                <div style={{ border: "1px solid var(--bd)", background: "var(--surface)" }}>
                  {doneGoals.map((g, i) => (
                    <div
                      key={g.id}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "9px 14px", fontSize: 12, color: "var(--fm)",
                        borderBottom: i < doneGoals.length - 1 ? "1px solid var(--bd)" : "none",
                      }}
                    >
                      <span style={{ color: "var(--green)", fontFamily: "var(--font-code)", fontSize: 11, flexShrink: 0 }}>✓</span>
                      <span style={{ textDecoration: "line-through", flex: 1, color: "var(--fd)" }}>{g.title}</span>
                      <span style={{ fontSize: 10, fontFamily: "var(--font-code)", flexShrink: 0 }}>{timeAgo(g.completed_at)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  );
}

// Tiny helper component used in loading/unauthenticated states
function GoalsHero({ goal, paused, cg, busy, runNow, togglePause }: {
  goal: CompanyGoal | null; paused: boolean;
  cg: CompanyGoalEntry | null; busy: string | null;
  runNow: () => void; togglePause: () => void;
}) {
  return (
    <div style={{ position: "relative", overflow: "hidden", flexShrink: 0, background: "#001aff", minHeight: 100, borderBottom: "1px solid var(--bd)" }}>
      <AstraGradient />
      <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
      <div style={{ position: "relative", zIndex: 2, padding: "24px 24px 20px" }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>Company Goals</div>
      </div>
    </div>
  );
}
