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

// ── Design tokens ──────────────────────────────────────────────────────────────
const c = {
  bg: "#FFFFFF",
  surface: "#F9FAFB",
  border: "#E5E7EB",
  text: "#111827",
  textMuted: "#6B7280",
  blue: "#002EFF",
  blueHover: "#1f36e0",
  blueTint: "#EFF6FF",
  greenTint: "#F0FDF4",
  greenText: "#16A34A",
  amberTint: "#FFF7E6",
  amberText: "#B45309",
  radius: 12,
};

const STATUS_STYLE: Record<string, React.CSSProperties> = {
  pending: { background: c.surface, color: c.textMuted },
  in_progress: { background: c.blueTint, color: c.blue },
  done: { background: c.greenTint, color: c.greenText },
  blocked: { background: "#FEF2F2", color: "#DC2626" },
  postponed: { background: c.amberTint, color: c.amberText },
};

function Badge({ label, kind }: { label: string; kind: string }) {
  return <span style={{ ...(STATUS_STYLE[kind] || STATUS_STYLE.pending), fontSize: 11, padding: "2px 8px", borderRadius: 99, fontWeight: 600, whiteSpace: "nowrap" }}>{label}</span>;
}

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

export default function MissionsPanel() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

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
    if (!founderId) return;
    load();
    const t = setInterval(load, 15000); // live-ish: tasks tick as agents finish
    return () => clearInterval(t);
  }, [founderId, load]);

  const cg = currentGoalOf(goal);
  const tasks = cg?.tasks ?? [];
  const doneGoals = (goal?.goals ?? []).filter((g) => g.status === "done").reverse();
  const runs = (goal?.operating_sessions ?? []).slice().reverse();
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
    try { const r = await runCompanyCycle(founderId); if (r.parent_session_id) window.location.assign(`/?session=${r.parent_session_id}`); else await load(); }
    catch (e) { alert(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused"); await load(); }
    finally { setBusy(null); }
  };

  const btn = (label: string, onClick: () => void, opts: { primary?: boolean; disabled?: boolean } = {}) => (
    <button onClick={onClick} disabled={opts.disabled || !!busy}
      style={{ padding: "8px 16px", borderRadius: 99, border: opts.primary ? "none" : `1px solid ${c.border}`,
        background: opts.primary ? c.blue : c.bg, color: opts.primary ? "#fff" : c.text,
        fontSize: 13, fontWeight: 600, cursor: busy ? "wait" : "pointer", whiteSpace: "nowrap", opacity: busy ? 0.7 : 1 }}>{label}</button>
  );

  const TaskRow = ({ t }: { t: CompanyTask }) => {
    const owners = t.owner_agents || [];
    const doneAgents = t.done_agents || [];
    const kind = t.postponed ? "postponed" : t.status;
    const label = t.postponed ? "postponed" : t.status.replace("_", " ");
    return (
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "11px 14px",
        border: `1px solid ${c.border}`, borderRadius: 10, background: t.status === "done" ? c.greenTint : c.surface, opacity: t.postponed ? 0.6 : 1 }}>
        <span style={{ marginTop: 1, fontSize: 14 }}>{t.status === "done" ? "✅" : t.postponed ? "⏸️" : "○"}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13.5, fontWeight: 600, color: c.text, textDecoration: t.postponed ? "line-through" : "none" }}>{t.title}</span>
            <Badge label={label} kind={kind} />
            {owners.length > 0 && (
              <span style={{ fontSize: 11, color: c.textMuted }}>
                {owners.map((o) => (doneAgents.includes(o) ? `✓${o}` : o)).join(" · ")}
              </span>
            )}
          </div>
          {t.notes && <div style={{ fontSize: 12, color: c.textMuted, marginTop: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{t.notes}</div>}
          {t.status !== "done" && (
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button disabled={!!busy} onClick={() => postpone(t)}
                style={{ fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, cursor: "pointer" }}>
                {t.postponed ? "Resume task" : "Postpone"}
              </button>
              {!t.postponed && (
                <button disabled={!!busy} onClick={() => markDone(t)}
                  style={{ fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.greenText, cursor: "pointer" }}>
                  Mark done
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  const Section = ({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) => (
    <div style={{ marginBottom: 26 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 }}>
        {title}{count != null ? ` · ${count}` : ""}
      </div>
      {children}
    </div>
  );

  if (!founderId) return <div style={{ padding: 40, color: c.textMuted }}>Sign in to view your company goal.</div>;

  return (
    <div style={{ background: c.bg, minHeight: "100%", padding: "32px 36px", maxWidth: 820, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: c.text, margin: "0 0 6px", letterSpacing: "-0.02em" }}>Company Goal</h1>
          <p style={{ fontSize: 14, color: c.textMuted, margin: 0 }}>One goal at a time. Tasks tick as agents finish; the planner sets the next goal.</p>
        </div>
        {goal && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {btn(busy === "run" ? "Starting…" : "▶ Run goal now", runNow, { primary: true, disabled: paused || !cg })}
            {btn(paused ? "Resume" : "Pause", togglePause)}
            {btn("Sync Notion", async () => { setBusy("notion"); try { await syncMissionNotion(founderId); await load(); } finally { setBusy(null); } })}
          </div>
        )}
      </div>

      {loading ? (
        <div style={{ padding: "60px 0", textAlign: "center", color: c.textMuted }}>Loading…</div>
      ) : error ? (
        <div style={{ padding: 24, background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: c.radius, color: "#DC2626" }}>
          {error} <button onClick={load} style={{ marginLeft: 8, textDecoration: "underline", background: "none", border: "none", color: "#DC2626", cursor: "pointer" }}>Retry</button>
        </div>
      ) : !goal ? (
        <div style={{ padding: "72px 24px", textAlign: "center", border: `1px dashed ${c.border}`, borderRadius: 16 }}>
          <div style={{ fontSize: 34, marginBottom: 14 }}>◎</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: c.text, marginBottom: 8 }}>No company goal yet</div>
          <p style={{ fontSize: 14, color: c.textMuted, maxWidth: 380, margin: "0 auto" }}>
            Start a run from the home screen — your launch goal and its tasks appear here the moment the agents start.
          </p>
        </div>
      ) : (
        <>
          {/* North star */}
          <div style={{ marginBottom: 24, padding: "18px 20px", borderRadius: 12, border: `1px solid ${c.border}`, background: c.blueTint }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: c.blue, letterSpacing: "0.06em", textTransform: "uppercase" }}>North Star</span>
              <Badge label={paused ? "paused" : "operating"} kind={paused ? "blocked" : "in_progress"} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: c.text, lineHeight: 1.45, marginBottom: 6 }}>{goal.north_star}</div>
            <div style={{ fontSize: 13, color: c.textMuted, lineHeight: 1.5 }}>{goal.company_goal}</div>
            {goal.notion_url && <a href={goal.notion_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: c.blue, marginTop: 10, display: "inline-block" }}>Open operating mirror in Notion →</a>}
          </div>

          {/* Current goal + tasks */}
          {cg ? (
            <Section title={`Current goal${cg.kind === "launch" ? " · launch" : ""}`}>
              <div style={{ fontSize: 17, fontWeight: 700, color: c.text, marginBottom: 12 }}>{cg.title}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {tasks.map((t) => <TaskRow key={t.id} t={t} />)}
              </div>
              {tasks.length === 0 && <p style={{ fontSize: 13, color: c.textMuted }}>No tasks on this goal.</p>}
            </Section>
          ) : (
            <Section title="Current goal">
              <p style={{ fontSize: 13, color: c.textMuted }}>No active goal — the planner sets the next one when the current run finishes.</p>
            </Section>
          )}

          {/* Operating runs */}
          {runs.length > 0 && (
            <Section title="Runs" count={runs.length}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {runs.map((r) => (
                  <a key={r.session_id} href={`/?session=${r.session_id}`}
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", border: `1px solid ${c.border}`, borderRadius: 10, background: c.surface, textDecoration: "none" }}>
                    <Badge label={r.status} kind={r.status === "done" ? "done" : r.status === "error" ? "blocked" : "in_progress"} />
                    <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: c.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.summary || "Operating run"}</span>
                    <span style={{ fontSize: 11, color: c.textMuted, whiteSpace: "nowrap" }}>{timeAgo(r.started_at)}</span>
                  </a>
                ))}
              </div>
            </Section>
          )}

          {/* Completed goals */}
          {doneGoals.length > 0 && (
            <Section title="Completed goals" count={doneGoals.length}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {doneGoals.map((g) => (
                  <div key={g.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", fontSize: 13, color: c.textMuted }}>
                    <span style={{ color: c.greenText }}>✓</span> <span style={{ textDecoration: "line-through" }}>{g.title}</span>
                    <span style={{ marginLeft: "auto", fontSize: 11 }}>{timeAgo(g.completed_at)}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  );
}
