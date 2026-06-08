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
  return goal.goals.find((g) => g.id === goal.current_goal_id) || goal.goals.find((g) => g.status === "active") || null;
}


// ── Design tokens ──────────────────────────────────────────────────────────────
const C = {
  bg: "#FFFFFF",
  surface: "#F9FAFB",
  surfaceHover: "#F3F4F6",
  border: "#E5E7EB",
  borderStrong: "#D1D5DB",
  text: "#111827",
  textMuted: "#6B7280",
  textFaint: "#9CA3AF",
  blue: "#002EFF",
  blueHover: "#1f36e0",
  blueTint: "#EFF6FF",
  green: "#16A34A",
  greenTint: "#F0FDF4",
  amber: "#B45309",
  amberTint: "#FFF7E6",
  red: "#DC2626",
  redTint: "#FEF2F2",
};

const TASK_STYLE: Record<string, { bg: string; color: string }> = {
  pending:           { bg: C.surface,   color: C.textMuted },
  in_progress:       { bg: C.blueTint,  color: C.blue },
  awaiting_approval: { bg: C.amberTint, color: C.amber },
  done:              { bg: C.greenTint, color: C.green },
  blocked:           { bg: C.redTint,   color: C.red },
  postponed:         { bg: C.amberTint, color: C.amber },
};

function Badge({ label, kind }: { label: string; kind: string }) {
  const s = TASK_STYLE[kind] ?? TASK_STYLE.pending;
  return (
    <span style={{ ...s, fontSize: 11, padding: "2px 8px", borderRadius: 99, fontWeight: 600, whiteSpace: "nowrap" }}>
      {label}
    </span>
  );
}

// ── Mini-button helper ─────────────────────────────────────────────────────────
function Btn({ label, onClick, primary, disabled, small }: {
  label: string; onClick: () => void; primary?: boolean; disabled?: boolean; small?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: small ? "4px 10px" : "8px 16px",
        borderRadius: 99,
        border: primary ? "none" : `1px solid ${C.border}`,
        background: primary ? C.blue : C.bg,
        color: primary ? "#fff" : C.text,
        fontSize: small ? 11 : 13,
        fontWeight: 600,
        cursor: disabled ? "wait" : "pointer",
        whiteSpace: "nowrap",
        opacity: disabled ? 0.65 : 1,
      }}
    >
      {label}
    </button>
  );
}

// ── Task row (for the "what Astra is working on" section) ──────────────────────

function TaskRow({
  t, busy, onPostpone, onMarkDone,
}: {
  t: CompanyTask;
  busy: string | null;
  onPostpone: () => void;
  onMarkDone: () => void;
}) {
  const kind = t.postponed ? "postponed" : t.status;
  const label = t.postponed ? "postponed" : t.status === "awaiting_approval" ? "needs approval" : t.status.replace(/_/g, " ");
  const owners = t.owner_agents ?? [];
  const doneAgents = t.done_agents ?? [];
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 14px",
      border: `1px solid ${C.border}`, borderRadius: 10,
      background: t.status === "done" ? C.greenTint : C.surface,
      opacity: t.postponed ? 0.6 : 1,
    }}>
      <span style={{ marginTop: 1, fontSize: 13 }}>
        {t.status === "done" ? "✅" : t.postponed ? "⏸" : t.status === "awaiting_approval" ? "🔔" : "○"}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text, textDecoration: t.postponed ? "line-through" : "none" }}>{t.title}</span>
          <Badge label={label} kind={kind} />
          {owners.length > 0 && (
            <span style={{ fontSize: 11, color: C.textFaint }}>
              {owners.map((o) => (doneAgents.includes(o) ? `✓${o}` : o)).join(" · ")}
            </span>
          )}
        </div>
        {t.notes && <div style={{ fontSize: 11.5, color: C.textMuted, marginTop: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{t.notes.slice(0, 200)}</div>}
        {t.status !== "done" && (
          <div style={{ display: "flex", gap: 7, marginTop: 7 }}>
            <Btn
              label={t.postponed ? "Resume" : "Postpone"}
              onClick={onPostpone}
              disabled={!!busy}
              small
            />
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
    try {
      const r = await runCompanyCycle(founderId);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
      else await load();
    } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused"); await load(); }
    finally { setBusy(null); }
  };

  if (!founderId) {
    return (
      <div style={{ padding: 40, color: C.textMuted, textAlign: "center" }}>
        Sign in to track your launch progress.
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ padding: "60px 0", textAlign: "center", color: C.textMuted }}>Loading…</div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24, background: C.redTint, border: `1px solid #FECACA`, borderRadius: 12, color: C.red, margin: "32px 36px" }}>
        {error}{" "}
        <button onClick={load} style={{ marginLeft: 8, textDecoration: "underline", background: "none", border: "none", color: C.red, cursor: "pointer" }}>Retry</button>
      </div>
    );
  }

  return (
    <div style={{ background: C.bg, minHeight: "100%", padding: "32px 36px", maxWidth: 860, margin: "0 auto" }}>

      {/* ── Page header ── */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: "0 0 6px", letterSpacing: "-0.025em" }}>
          Company Goal
        </h1>
        <p style={{ fontSize: 14, color: C.textMuted, margin: 0 }}>
          One goal at a time. Tasks tick as agents finish; the planner sets the next goal.
        </p>
      </div>

      {/* ── What Astra is doing ── */}
      {goal && (
        <div style={{ borderRadius: 14, border: `1px solid ${C.border}`, overflow: "hidden", marginBottom: 24 }}>
          {/* Section header */}
          <button
            onClick={() => setOperatingOpen((o) => !o)}
            style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", background: "none", border: "none", cursor: "pointer" }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>What Astra is working on</span>
              <span style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 99, fontWeight: 600,
                background: paused ? C.amberTint : C.blueTint,
                color: paused ? C.amber : C.blue,
              }}>
                {paused ? "paused" : "operating"}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {goal && (
                <>
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
                </>
              )}
              <span style={{ fontSize: 10, color: C.textFaint }}>{operatingOpen ? "▲" : "▼"}</span>
            </div>
          </button>

          {operatingOpen && (
            <div style={{ borderTop: `1px solid ${C.border}`, padding: "16px 20px" }}>
              {/* North star */}
              <div style={{ marginBottom: 18, padding: "12px 16px", borderRadius: 10, background: C.blueTint, border: `1px solid rgba(0,46,255,0.1)` }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: C.blue, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 5 }}>North Star</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: C.text, lineHeight: 1.5 }}>{goal.north_star}</div>
                {goal.notion_url && (
                  <a href={goal.notion_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: C.blue, marginTop: 8, display: "inline-block" }}>
                    Open in Notion →
                  </a>
                )}
              </div>

              {/* Current goal */}
              {cg ? (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
                    Current goal{cg.kind === "launch" ? " · launch" : ""}
                  </div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 12 }}>{cg.title}</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {tasks.map((t) => (
                      <TaskRow key={t.id} t={t} busy={busy} onPostpone={() => postpone(t)} onMarkDone={() => markDone(t)} />
                    ))}
                    {tasks.length === 0 && <p style={{ fontSize: 13, color: C.textMuted }}>No tasks on this goal yet.</p>}
                  </div>
                </div>
              ) : (
                <p style={{ fontSize: 13, color: C.textMuted, marginBottom: 18 }}>
                  No active goal — the planner will set the next one when the current run finishes.
                </p>
              )}

              {/* Sync Notion */}
              <div style={{ marginTop: 4 }}>
                <Btn
                  label="Sync Notion"
                  onClick={async () => { setBusy("notion"); try { await syncMissionNotion(founderId); await load(); } finally { setBusy(null); } }}
                  disabled={!!busy}
                />
              </div>

              {/* Runs */}
              {runs.length > 0 && (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                    Recent runs · {runs.length}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {runs.map((r) => (
                      <a key={r.session_id} href={`/s/${r.session_id}`}
                        style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: `1px solid ${C.border}`, borderRadius: 9, background: C.surface, textDecoration: "none" }}>
                        <Badge label={r.status} kind={r.status === "done" ? "done" : r.status === "error" ? "blocked" : "in_progress"} />
                        <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.summary || "Operating run"}</span>
                        <span style={{ fontSize: 11, color: C.textFaint, whiteSpace: "nowrap" }}>{timeAgo(r.started_at)}</span>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Completed goals */}
              {doneGoals.length > 0 && (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                    Completed goals · {doneGoals.length}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {doneGoals.map((g) => (
                      <div key={g.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", fontSize: 13, color: C.textMuted }}>
                        <span style={{ color: C.green }}>✓</span>
                        <span style={{ textDecoration: "line-through" }}>{g.title}</span>
                        <span style={{ marginLeft: "auto", fontSize: 11 }}>{timeAgo(g.completed_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Empty state (no goal yet) ── */}
      {!goal && !loading && (
        <div style={{ padding: "48px 24px", textAlign: "center", border: `1px dashed ${C.border}`, borderRadius: 16, marginTop: 8 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>◎</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: C.text, marginBottom: 8 }}>No run started yet</div>
          <p style={{ fontSize: 13, color: C.textMuted, maxWidth: 360, margin: "0 auto 16px" }}>
            Start a run from the home screen — Astra will auto-complete checklist items as it works.
          </p>
          <a href="/" style={{ display: "inline-block", padding: "9px 20px", borderRadius: 99, background: C.blue, color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none" }}>
            Start a run →
          </a>
        </div>
      )}
    </div>
  );
}
