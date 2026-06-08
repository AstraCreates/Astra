"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import {
  getCompanyGoal,
  approveCompanyTask,
  updateCompanyTask,
  runCompanyCycle,
  setCompanyGoalStatus,
  syncMissionNotion,
  type CompanyGoal,
  type CompanyTask,
} from "@/lib/api";

// ── Design tokens ────────────────────────────────────────────────────────────
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
  awaiting_approval: { background: c.amberTint, color: c.amberText },
  done: { background: c.greenTint, color: c.greenText },
  blocked: { background: "#FEF2F2", color: "#DC2626" },
};

function TaskBadge({ status }: { status: CompanyTask["status"] }) {
  const label = status === "awaiting_approval" ? "needs approval" : status.replace("_", " ");
  return <span style={{ ...(STATUS_STYLE[status] || STATUS_STYLE.pending), fontSize: 11, padding: "2px 8px", borderRadius: 99, fontWeight: 600, whiteSpace: "nowrap" }}>{label}</span>;
}

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
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

  useEffect(() => { if (founderId) load(); }, [founderId, load]);

  const tasks = goal?.tasks ?? [];
  const awaiting = tasks.filter((t) => t.status === "awaiting_approval");
  const open = tasks.filter((t) => ["pending", "in_progress", "blocked"].includes(t.status));
  const done = tasks.filter((t) => t.status === "done");
  const runs = (goal?.operating_sessions ?? []).slice().reverse();
  const paused = goal?.status === "paused";

  const decide = async (task: CompanyTask, approved: boolean) => {
    let note = "";
    if (!approved) { note = window.prompt("What needs changing? (sent back to the team)") || ""; }
    setBusy(task.id);
    try { await approveCompanyTask(founderId, task.id, approved, note); await load(); }
    catch (e) { alert(`Could not record decision: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(null); }
  };

  const approveAll = async () => {
    if (!awaiting.length || !confirm(`Approve all ${awaiting.length} milestone(s)?`)) return;
    setBusy("all");
    try { for (const t of awaiting) await approveCompanyTask(founderId, t.id, true, ""); await load(); }
    finally { setBusy(null); }
  };

  const toggleDone = async (task: CompanyTask, nextDone: boolean) => {
    setBusy(task.id);
    try { await updateCompanyTask(founderId, task.id, { status: nextDone ? "done" : "pending" }); await load(); }
    finally { setBusy(null); }
  };

  const runNow = async () => {
    setBusy("run");
    try { const r = await runCompanyCycle(founderId); if (r.session_id) window.location.assign(`/?session=${r.session_id}`); }
    catch (e) { alert(e instanceof Error ? e.message : String(e)); setBusy(null); }
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
        fontSize: 13, fontWeight: 600, cursor: busy ? "wait" : "pointer", whiteSpace: "nowrap", opacity: busy ? 0.7 : 1 }}>
      {label}
    </button>
  );

  const Section = ({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) => (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 }}>
        {title}{count != null ? ` · ${count}` : ""}
      </div>
      {children}
    </div>
  );

  const TaskRow = ({ task, withApproval }: { task: CompanyTask; withApproval?: boolean }) => (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "11px 14px",
      border: `1px solid ${withApproval ? c.amberText : c.border}`, borderRadius: 10,
      background: withApproval ? c.amberTint : c.surface }}>
      {!withApproval && (
        <input type="checkbox" checked={task.status === "done"} disabled={!!busy}
          onChange={(e) => toggleDone(task, e.currentTarget.checked)} style={{ marginTop: 3 }} />
      )}
      {withApproval && <span style={{ marginTop: 1 }}>🔔</span>}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: c.text }}>{task.title}</span>
          <TaskBadge status={task.status} />
        </div>
        {task.notes && <div style={{ fontSize: 12, color: c.textMuted, marginTop: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{task.notes}</div>}
        {withApproval && (
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button disabled={!!busy} onClick={() => decide(task, true)}
              style={{ fontSize: 11.5, fontWeight: 700, padding: "5px 12px", borderRadius: 8, border: "none", background: c.greenText, color: "#fff", cursor: "pointer" }}>✓ Approve</button>
            <button disabled={!!busy} onClick={() => decide(task, false)}
              style={{ fontSize: 11.5, fontWeight: 600, padding: "5px 12px", borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, cursor: "pointer" }}>Request changes</button>
          </div>
        )}
      </div>
    </div>
  );

  if (!founderId) return <div style={{ padding: 40, color: c.textMuted }}>Sign in to view your company goal.</div>;

  return (
    <div style={{ background: c.bg, minHeight: "100%", padding: "32px 36px", maxWidth: 820, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: c.text, margin: "0 0 6px", letterSpacing: "-0.02em" }}>Company Goal</h1>
          <p style={{ fontSize: 14, color: c.textMuted, margin: 0 }}>One goal. All agents working together, every cycle.</p>
        </div>
        {goal && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {btn(busy === "run" ? "Starting…" : "▶ Run cycle now", runNow, { primary: true, disabled: paused })}
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
          <p style={{ fontSize: 14, color: c.textMuted, maxWidth: 360, margin: "0 auto" }}>
            Launch a company from the home screen — when the build finishes, your north star and operating milestones appear here.
          </p>
        </div>
      ) : (
        <>
          {/* North star header */}
          <div style={{ marginBottom: 28, padding: "18px 20px", borderRadius: 12, border: `1px solid ${c.border}`, background: c.blueTint }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: c.blue, letterSpacing: "0.06em", textTransform: "uppercase" }}>North Star</span>
              <span style={{ ...STATUS_STYLE[paused ? "blocked" : "in_progress"], fontSize: 10.5, padding: "2px 8px", borderRadius: 99, fontWeight: 700, textTransform: "uppercase" }}>
                {paused ? "paused" : "operating"}
              </span>
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: c.text, lineHeight: 1.45, marginBottom: 6 }}>{goal.north_star}</div>
            <div style={{ fontSize: 13, color: c.textMuted, lineHeight: 1.5 }}>{goal.company_goal}</div>
            {!!goal.kpis?.length && (
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12 }}>
                {goal.kpis.map((k, i) => (
                  <div key={i} style={{ fontSize: 12, color: c.text }}>
                    <span style={{ color: c.textMuted }}>{k.label || k.key}:</span> <strong>{k.target}</strong>
                  </div>
                ))}
              </div>
            )}
            {goal.notion_url && <a href={goal.notion_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: c.blue, marginTop: 10, display: "inline-block" }}>Open operating mirror in Notion →</a>}
          </div>

          {/* Awaiting approval */}
          {awaiting.length > 0 && (
            <Section title="Awaiting your approval" count={awaiting.length}>
              <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
                {btn(busy === "all" ? "Approving…" : `✓ Approve all (${awaiting.length})`, approveAll)}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {awaiting.map((t) => <TaskRow key={t.id} task={t} withApproval />)}
              </div>
            </Section>
          )}

          {/* Open milestones */}
          <Section title="Open milestones" count={open.length}>
            {open.length === 0 ? (
              <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>No open milestones — the planner assigns the next ones on the next cycle.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {open.map((t) => <TaskRow key={t.id} task={t} />)}
              </div>
            )}
          </Section>

          {/* Operating runs */}
          {runs.length > 0 && (
            <Section title="Operating runs" count={runs.length}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {runs.map((r) => (
                  <a key={r.session_id} href={`/?session=${r.session_id}`}
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", border: `1px solid ${c.border}`, borderRadius: 10, background: c.surface, textDecoration: "none" }}>
                    <span style={{ ...STATUS_STYLE[r.status === "done" ? "done" : r.status === "error" ? "blocked" : "in_progress"], fontSize: 10.5, padding: "2px 8px", borderRadius: 99, fontWeight: 700 }}>{r.status}</span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: c.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.summary || "Operating cycle"}</span>
                    <span style={{ fontSize: 11, color: c.textMuted, whiteSpace: "nowrap" }}>{timeAgo(r.started_at)}</span>
                  </a>
                ))}
              </div>
            </Section>
          )}

          {/* Completed */}
          {done.length > 0 && (
            <Section title="Completed" count={done.length}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {done.map((t) => (
                  <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", fontSize: 13, color: c.textMuted }}>
                    <span style={{ color: c.greenText }}>✓</span> <span style={{ textDecoration: "line-through" }}>{t.title}</span>
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
