"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
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
  const { bg, border } = TASK_BG[kind] ?? TASK_BG.pending;
  const icon = STATUS_ICON[kind] ?? "○";

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 14px",
      border: `1px solid ${border}`, background: bg,
      opacity: t.postponed ? 0.55 : 1,
    }}>
      <span style={{ marginTop: 2, fontSize: 11, color: "var(--fm)", fontFamily: "var(--font-code)", flexShrink: 0 }}>
        {icon}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: "var(--fg)",
            textDecoration: t.postponed ? "line-through" : "none",
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
          <div style={{ display: "flex", gap: 6, marginTop: 7 }}>
            <Btn label={t.postponed ? "Resume" : "Postpone"} onClick={onPostpone} disabled={!!busy} small />
            {!t.postponed && (
              <Btn
                label={t.status === "awaiting_approval" ? "Approve ✓" : "Mark done"}
                onClick={onMarkDone}
                disabled={!!busy}
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

  if (!founderId) {
    return (
      <div className="empty" style={{ minHeight: 240 }}>
        <span style={{ fontSize: 22, fontFamily: "var(--font-code)", opacity: 0.25 }}>◎</span>
        <span className="empty-title">Sign in to track your launch progress.</span>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="empty" style={{ minHeight: 240 }}>
        <span style={{ fontSize: 11, fontFamily: "var(--font-code)", color: "var(--fm)" }}>Loading…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: "32px 36px", maxWidth: 860, margin: "0 auto" }}>
        <div className="err-banner">
          {error}{" "}
          <button
            onClick={load}
            style={{ marginLeft: 8, textDecoration: "underline", background: "none", border: "none", color: "var(--red)", cursor: "pointer", fontFamily: "var(--font-code)", fontSize: 11 }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100%", padding: "32px 36px", maxWidth: 860, margin: "0 auto" }}>

      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <h1 className="dash-ht" style={{ margin: "0 0 5px" }}>Company Goal</h1>
        <p className="dash-sub" style={{ margin: 0 }}>
          One goal at a time — tasks tick as agents finish, planner sets the next.
        </p>
      </div>

      {actionErr && (
        <div className="err-banner" style={{ marginBottom: 16 }}>{actionErr}</div>
      )}

      {/* Operating section */}
      {goal && (
        <div style={{ border: "1px solid var(--bd)", marginBottom: 24 }}>

          {/* Header row */}
          <button
            onClick={() => setOperatingOpen((o) => !o)}
            style={{
              width: "100%", display: "flex", alignItems: "center",
              justifyContent: "space-between", padding: "11px 16px",
              background: "none", border: "none", cursor: "pointer",
              borderBottom: operatingOpen ? "1px solid var(--bd)" : "none",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--fg)", letterSpacing: "0.03em" }}>
                What Astra is working on
              </span>
              <span className={`pill${paused ? " amber" : " blue"}`}>
                {paused ? "paused" : "operating"}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span onClick={(e) => e.stopPropagation()}>
                <Btn
                  label={busy === "run" ? "Starting…" : "▶ Run now"}
                  onClick={runNow}
                  primary
                  disabled={paused || !cg || !!busy}
                />
              </span>
              <span onClick={(e) => e.stopPropagation()}>
                <Btn
                  label={paused ? "Resume" : "Pause"}
                  onClick={togglePause}
                  disabled={!!busy}
                />
              </span>
              <span style={{ fontSize: 9, color: "var(--fm)", fontFamily: "var(--font-code)", marginLeft: 2, flexShrink: 0 }}>
                {operatingOpen ? "▲" : "▼"}
              </span>
            </div>
          </button>

          {operatingOpen && (
            <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 20 }}>

              {/* North star */}
              <div style={{ padding: "11px 14px", background: "var(--bdim)", border: "1px solid var(--bb)" }}>
                <div className="sec-label" style={{ color: "var(--blue)", marginBottom: 5 }}>North Star</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", lineHeight: 1.55 }}>
                  {goal.north_star}
                </div>
                {goal.notion_url && (
                  <a
                    href={goal.notion_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: 11, color: "var(--blue)", marginTop: 8, display: "inline-block", fontFamily: "var(--font-code)" }}
                  >
                    Open in Notion →
                  </a>
                )}
              </div>

              {/* Current goal + tasks */}
              {cg ? (
                <div>
                  <div className="sec-label" style={{ marginBottom: 9 }}>
                    Current goal{cg.kind === "launch" ? " · launch" : ""}
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", marginBottom: 12, letterSpacing: "-0.01em" }}>
                    {cg.title}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    {tasks.map((t) => (
                      <TaskRow
                        key={t.id}
                        t={t}
                        busy={busy}
                        onPostpone={() => postpone(t)}
                        onMarkDone={() => markDone(t)}
                      />
                    ))}
                    {tasks.length === 0 && (
                      <p style={{ fontSize: 12, color: "var(--fm)", margin: 0 }}>No tasks on this goal yet.</p>
                    )}
                  </div>
                </div>
              ) : (
                <p style={{ fontSize: 12, color: "var(--fm)", margin: 0 }}>
                  No active goal — planner sets the next one when the current run finishes.
                </p>
              )}

              {/* Sync Notion */}
              <div style={{ display: "flex" }}>
                <Btn
                  label={busy === "notion" ? "Syncing…" : "Sync Notion"}
                  onClick={async () => {
                    setBusy("notion");
                    try { await syncMissionNotion(founderId); await load(); }
                    catch (e) { setActionErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setActionErr(null), 8000); }
                    finally { setBusy(null); }
                  }}
                  disabled={!!busy}
                />
              </div>

              {/* Recent runs */}
              {runs.length > 0 && (
                <div>
                  <div className="sec-label" style={{ marginBottom: 8 }}>Recent runs · {runs.length}</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {runs.map((r) => (
                      <a
                        key={r.session_id}
                        href={`/s/${r.session_id}`}
                        style={{
                          display: "flex", alignItems: "center", gap: 10,
                          padding: "8px 12px", border: "1px solid var(--bd)",
                          background: "var(--surface)", textDecoration: "none",
                          transition: "border-color .12s, background .12s",
                        }}
                      >
                        <Badge
                          label={r.status}
                          kind={r.status === "done" ? "done" : r.status === "error" ? "blocked" : "in_progress"}
                        />
                        <span style={{
                          flex: 1, minWidth: 0, fontSize: 12, color: "var(--fg)",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {r.summary || "Operating run"}
                        </span>
                        <span style={{ fontSize: 10, color: "var(--fm)", whiteSpace: "nowrap", fontFamily: "var(--font-code)" }}>
                          {timeAgo(r.started_at)}
                        </span>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Completed goals */}
              {doneGoals.length > 0 && (
                <div>
                  <div className="sec-label" style={{ marginBottom: 8 }}>Completed goals · {doneGoals.length}</div>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {doneGoals.map((g) => (
                      <div
                        key={g.id}
                        style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "7px 0", fontSize: 12, color: "var(--fm)",
                          borderBottom: "1px solid var(--bd)",
                        }}
                      >
                        <span style={{ color: "var(--green)", fontFamily: "var(--font-code)", fontSize: 10 }}>✓</span>
                        <span style={{ textDecoration: "line-through", flex: 1 }}>{g.title}</span>
                        <span style={{ fontSize: 10, fontFamily: "var(--font-code)" }}>{timeAgo(g.completed_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!goal && !loading && (
        <div style={{ padding: "64px 24px", textAlign: "center", border: "1px dashed var(--bd2)" }}>
          <div style={{ fontSize: 22, marginBottom: 14, fontFamily: "var(--font-code)", color: "var(--fm)", opacity: 0.35 }}>◎</div>
          <div className="empty-title" style={{ marginBottom: 8 }}>No run started yet</div>
          <p style={{ fontSize: 12, color: "var(--fm)", maxWidth: 340, margin: "0 auto 20px", lineHeight: 1.65 }}>
            Start a run from the home screen — Astra auto-completes checklist items as it works.
          </p>
          <a href="/" className="btn pri" style={{ textDecoration: "none", display: "inline-block" }}>
            Start a run →
          </a>
        </div>
      )}

    </div>
  );
}
