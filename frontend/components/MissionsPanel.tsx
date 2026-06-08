"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import {
  createMission,
  deleteMission,
  getCompanyGoal,
  getMissions,
  runMission,
  syncMissionNotion,
  updateMission,
  updateMissionTask,
  approveMissionTask,
  type CompanyGoal,
  type Mission,
  type MissionTask,
} from "@/lib/api";

// ── Design tokens ──────────────────────────────────────────────────────────────
const c = {
  bg: "#FFFFFF",
  surface: "#F9FAFB",
  border: "#E5E7EB",
  text: "#111827",
  textMuted: "#6B7280",
  blue: "#2b45ff",
  blueHover: "#1f36e0",
  blueTint: "#EFF6FF",
  greenTint: "#F0FDF4",
  greenText: "#22C55E",
  radius: 12,
};

// ── Department config ──────────────────────────────────────────────────────────
const DEPARTMENTS = [
  "research",
  "marketing",
  "sales",
  "technical",
  "legal",
  "ops",
  "finance",
] as const;

type Department = (typeof DEPARTMENTS)[number];

const DEPT_ICON: Record<Department, string> = {
  research: "🔍",
  marketing: "📢",
  sales: "💰",
  technical: "⚙️",
  legal: "⚖️",
  ops: "🧭",
  finance: "📊",
};

const DEPT_LABEL: Record<Department, string> = {
  research: "Research",
  marketing: "Marketing",
  sales: "Sales",
  technical: "Technical",
  legal: "Legal",
  ops: "Ops",
  finance: "Finance",
};

// ── Status badge ───────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: Mission["status"] }) {
  const styles: Record<Mission["status"], React.CSSProperties> = {
    active: { background: c.blueTint, color: c.blue },
    paused: { background: c.surface, color: c.textMuted },
    completed: { background: c.greenTint, color: c.greenText },
  };
  return (
    <span
      style={{
        ...styles[status],
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        padding: "3px 9px",
        borderRadius: 99,
        display: "inline-block",
      }}
    >
      {status}
    </span>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffH = Math.floor(diffMins / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function TaskBadge({ status }: { status: MissionTask["status"] }) {
  const styles: Record<string, React.CSSProperties> = {
    pending: { background: c.surface, color: c.textMuted },
    in_progress: { background: c.blueTint, color: c.blue },
    running: { background: c.blueTint, color: c.blue },
    awaiting_approval: { background: "#FFF7E6", color: "#B45309" },
    done: { background: c.greenTint, color: c.greenText },
    blocked: { background: "#FEF2F2", color: "#DC2626" },
  };
  const label = status === "awaiting_approval" ? "needs approval" : status.replace("_", " ");
  return <span style={{ ...(styles[status] || styles.pending), fontSize: 11, padding: "2px 8px", borderRadius: 99, fontWeight: 600, whiteSpace: "nowrap" }}>{label}</span>;
}

function MissionTaskTree({ mission, onRefresh }: { mission: Mission; onRefresh: () => void }) {
  const { userId } = useDevUser();
  const [savingId, setSavingId] = useState<string | null>(null);
  const tasks = mission.tasks ?? [];
  const roots = tasks.filter((task) => !task.parent_id);
  const childrenByParent = tasks.reduce<Record<string, MissionTask[]>>((acc, task) => {
    if (task.parent_id) (acc[task.parent_id] ??= []).push(task);
    return acc;
  }, {});

  const toggleDone = async (task: MissionTask, nextDone: boolean) => {
    setSavingId(task.id);
    try {
      await updateMissionTask(mission.id, task.id, { status: nextDone ? "done" : "pending" });
      onRefresh();
    } finally {
      setSavingId(null);
    }
  };

  const decide = async (task: MissionTask, approved: boolean) => {
    let note = "";
    if (!approved) { note = window.prompt("What needs changing? (sent back to the agent)") || ""; }
    setSavingId(task.id);
    try {
      await approveMissionTask(mission.id, task.id, userId, approved, note);
      onRefresh();
    } catch (e) {
      alert(`Could not record decision: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingId(null);
    }
  };

  const renderTask = (task: MissionTask, depth = 0) => {
    const awaiting = task.status === "awaiting_approval";
    return (
    <div key={task.id} style={{ display: "flex", flexDirection: "column", gap: 8, marginLeft: depth * 18 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 12px", border: `1px solid ${awaiting ? c.blue : c.border}`, borderRadius: 10, background: awaiting ? "rgba(0,46,255,0.04)" : c.surface }}>
        {!awaiting && (
          <input
            type="checkbox"
            checked={task.status === "done"}
            disabled={savingId === task.id}
            onChange={(e) => toggleDone(task, e.currentTarget.checked)}
            style={{ marginTop: 2 }}
          />
        )}
        {awaiting && <span style={{ marginTop: 1, fontSize: 13 }}>🔔</span>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>{task.title}</span>
            <TaskBadge status={task.status} />
            <span style={{ fontSize: 11, color: c.textMuted }}>{task.owner_agent}</span>
          </div>
          {task.notes && <div style={{ fontSize: 12, color: c.textMuted, marginTop: 4, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{task.notes}</div>}
          {awaiting && (
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button disabled={savingId === task.id} onClick={() => decide(task, true)}
                style={{ fontSize: 11, fontWeight: 700, padding: "5px 12px", borderRadius: 8, border: "none", background: "#16a34a", color: "#fff", cursor: "pointer" }}>
                ✓ Approve milestone
              </button>
              <button disabled={savingId === task.id} onClick={() => decide(task, false)}
                style={{ fontSize: 11, fontWeight: 600, padding: "5px 12px", borderRadius: 8, border: `1px solid ${c.border}`, background: c.surface, color: c.text, cursor: "pointer" }}>
                Request changes
              </button>
            </div>
          )}
          {task.notion_page_url && (
            <a href={task.notion_page_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: c.blue, marginTop: 6, display: "inline-block" }}>
              Open in Notion
            </a>
          )}
        </div>
      </div>
      {(childrenByParent[task.id] || []).map((child) => renderTask(child, depth + 1))}
    </div>
    );
  };

  if (!roots.length) return <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>No operating tasks yet.</p>;
  return <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{roots.map((task) => renderTask(task))}</div>;
}

// ── MissionCard ────────────────────────────────────────────────────────────────
interface MissionCardProps {
  mission: Mission;
  onRefresh: () => void;
}

function MissionCard({ mission, onRefresh }: MissionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [running, setRunning] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [runFeedback, setRunFeedback] = useState<string | null>(null);

  const handleRun = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (running || mission.status !== "active") return;
      setRunning(true);
      setRunFeedback(null);
      try {
        const result = await runMission(mission.id);
        setRunFeedback(result.ok ? "Run started" : "Failed to start");
        onRefresh();
      } catch {
        setRunFeedback("Error");
      } finally {
        setRunning(false);
        setTimeout(() => setRunFeedback(null), 3000);
      }
    },
    [running, mission.id, mission.status, onRefresh]
  );

  const handleToggle = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (toggling) return;
      setToggling(true);
      try {
        const nextStatus = mission.status === "active" ? "paused" : "active";
        await updateMission(mission.id, { status: nextStatus });
        onRefresh();
      } catch {
        // silent
      } finally {
        setToggling(false);
      }
    },
    [toggling, mission.id, mission.status, onRefresh]
  );

  const handleDelete = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!confirm(`Delete mission "${mission.name}"?`)) return;
      setDeleting(true);
      try {
        await deleteMission(mission.id);
        onRefresh();
      } catch {
        setDeleting(false);
      }
    },
    [mission.id, mission.name, onRefresh]
  );

  const recentNotes = mission.progress_notes.slice(-5).reverse();

  return (
    <div
      onClick={() => setExpanded((v) => !v)}
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: c.radius,
        padding: "20px 24px",
        cursor: "pointer",
        transition: "box-shadow 0.15s",
      }}
      onMouseEnter={(e) =>
        ((e.currentTarget as HTMLDivElement).style.boxShadow =
          "0 2px 12px rgba(0,0,0,0.07)")
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLDivElement).style.boxShadow = "none")
      }
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <span style={{ fontSize: 22, lineHeight: 1, flexShrink: 0, marginTop: 2 }}>
          {DEPT_ICON[mission.department as Department] ?? "🤖"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: c.text,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 280,
              }}
            >
              {mission.name}
            </span>
            <StatusBadge status={mission.status} />
          </div>
          <div
            style={{
              fontSize: 12,
              color: c.textMuted,
              marginTop: 3,
              display: "flex",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <span>
              {DEPT_LABEL[mission.department as Department] ?? mission.department}
            </span>
            <span>Metric: {mission.primary_metric}</span>
            <span>Runs: {mission.run_count}</span>
            <span>Last: {formatDate(mission.last_run_at)}</span>
            <span>Cost: ${mission.total_cost_usd.toFixed(2)}</span>
          </div>
        </div>

        {/* Actions */}
        <div
          onClick={(e) => e.stopPropagation()}
          style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}
        >
          {runFeedback && (
            <span style={{ fontSize: 12, color: c.textMuted }}>{runFeedback}</span>
          )}
          <button
            onClick={handleRun}
            disabled={running || mission.status !== "active"}
            style={{
              padding: "6px 14px",
              borderRadius: 99,
              border: "none",
              background:
                mission.status !== "active" ? c.border : c.blue,
              color: mission.status !== "active" ? c.textMuted : "#fff",
              fontSize: 12,
              fontWeight: 600,
              cursor: mission.status !== "active" ? "not-allowed" : "pointer",
              opacity: running ? 0.6 : 1,
            }}
          >
            {running ? "Running…" : "Run now"}
          </button>
          <button
            onClick={handleToggle}
            disabled={toggling || mission.status === "completed"}
            style={{
              padding: "6px 14px",
              borderRadius: 99,
              border: `1px solid ${c.border}`,
              background: c.bg,
              color: c.text,
              fontSize: 12,
              fontWeight: 500,
              cursor: mission.status === "completed" ? "not-allowed" : "pointer",
              opacity: toggling ? 0.6 : 1,
            }}
          >
            {mission.status === "active" ? "Pause" : "Resume"}
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            style={{
              padding: "6px 10px",
              borderRadius: 8,
              border: `1px solid ${c.border}`,
              background: c.bg,
              color: "#DC2626",
              fontSize: 12,
              cursor: "pointer",
              opacity: deleting ? 0.5 : 1,
            }}
            title="Delete mission"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          style={{
            marginTop: 20,
            borderTop: `1px solid ${c.border}`,
            paddingTop: 20,
            display: "flex",
            gap: 32,
            flexWrap: "wrap",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Goal + Objectives */}
          <div style={{ flex: "1 1 260px", minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>
              Goal
            </div>
            <p style={{ fontSize: 13, color: c.text, lineHeight: 1.6, margin: 0 }}>
              {mission.goal}
            </p>

            {mission.objectives.length > 0 && (
              <>
                <div style={{ fontSize: 11, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginTop: 16, marginBottom: 8 }}>
                  Objectives
                </div>
                <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 4 }}>
                  {mission.objectives.map((obj, i) => (
                    <li key={i} style={{ fontSize: 13, color: c.text, lineHeight: 1.5 }}>
                      {obj}
                    </li>
                  ))}
                </ul>
              </>
            )}

            <div style={{ marginTop: 16, display: "flex", gap: 24 }}>
              <div>
                <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 2 }}>Max runs/day</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: c.text }}>
                  {mission.budget.max_runs_per_day}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 2 }}>Max $/run</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: c.text }}>
                  ${mission.budget.max_cost_usd_per_run.toFixed(2)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 2 }}>Approval</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: c.text }}>
                  {mission.approval_policy === "auto" ? "Automatic" : "Requires approval"}
                </div>
              </div>
            </div>
          </div>

          {/* Progress notes */}
          <div style={{ flex: "1 1 240px", minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
              Recent progress
            </div>
            {recentNotes.length === 0 ? (
              <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>No progress notes yet.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {recentNotes.map((note, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "10px 14px",
                      background: c.surface,
                      borderRadius: 8,
                      border: `1px solid ${c.border}`,
                    }}
                  >
                    <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 4 }}>
                      {formatDate(note.timestamp)}
                    </div>
                    <p style={{ fontSize: 13, color: c.text, margin: 0, lineHeight: 1.55 }}>
                      {note.note}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div style={{ flex: "1 1 320px", minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: c.textMuted, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
              Operating tasks
            </div>
            <MissionTaskTree mission={mission} onRefresh={onRefresh} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── CreateMissionModal ─────────────────────────────────────────────────────────
interface CreateMissionModalProps {
  founderId: string;
  onClose: () => void;
  onCreated: () => void;
}

function CreateMissionModal({ founderId, onClose, onCreated }: CreateMissionModalProps) {
  const [department, setDepartment] = useState<Department>("research");
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [metric, setMetric] = useState("");
  const [objectives, setObjectives] = useState<string[]>([""]);
  const [maxRuns, setMaxRuns] = useState(3);
  const [maxCost, setMaxCost] = useState(0.5);
  const [approvalPolicy, setApprovalPolicy] = useState<"auto" | "require_approval">("auto");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  const addObjective = () => setObjectives((prev) => [...prev, ""]);
  const removeObjective = (i: number) =>
    setObjectives((prev) => prev.filter((_, idx) => idx !== i));
  const updateObjective = (i: number, val: string) =>
    setObjectives((prev) => prev.map((o, idx) => (idx === i ? val : o)));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !goal.trim() || !metric.trim()) {
      setError("Name, goal, and metric are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createMission({
        founder_id: founderId,
        department,
        name: name.trim(),
        goal: goal.trim(),
        primary_metric: metric.trim(),
        objectives: objectives.map((o) => o.trim()).filter(Boolean),
        budget: { max_runs_per_day: maxRuns, max_cost_usd_per_run: maxCost },
        approval_policy: approvalPolicy,
        status: "active",
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create mission");
      setSaving(false);
    }
  };

  // Close on overlay click
  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "9px 12px",
    borderRadius: 8,
    border: `1px solid ${c.border}`,
    background: c.bg,
    color: c.text,
    fontSize: 14,
    outline: "none",
    boxSizing: "border-box",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 600,
    color: c.textMuted,
    display: "block",
    marginBottom: 6,
    letterSpacing: "0.03em",
  };

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        style={{
          background: c.bg,
          borderRadius: 16,
          width: "100%",
          maxWidth: 560,
          maxHeight: "90vh",
          overflowY: "auto",
          boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
        }}
      >
        {/* Modal header */}
        <div
          style={{
            padding: "22px 28px 18px",
            borderBottom: `1px solid ${c.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 700, color: c.text }}>
            New Mission
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: c.textMuted,
              fontSize: 18,
              cursor: "pointer",
              lineHeight: 1,
              padding: 4,
            }}
          >
            ✕
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ padding: "24px 28px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Department selector */}
          <div>
            <label style={labelStyle}>Department</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {DEPARTMENTS.map((dept) => (
                <button
                  key={dept}
                  type="button"
                  onClick={() => setDepartment(dept)}
                  style={{
                    padding: "7px 14px",
                    borderRadius: 99,
                    border: `1px solid ${department === dept ? c.blue : c.border}`,
                    background: department === dept ? c.blueTint : c.bg,
                    color: department === dept ? c.blue : c.text,
                    fontSize: 13,
                    fontWeight: department === dept ? 600 : 400,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <span>{DEPT_ICON[dept]}</span>
                  {DEPT_LABEL[dept]}
                </button>
              ))}
            </div>
          </div>

          {/* Name */}
          <div>
            <label style={labelStyle}>Mission name</label>
            <input
              style={inputStyle}
              placeholder="e.g. Weekly competitor monitoring"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          {/* Goal */}
          <div>
            <label style={labelStyle}>Goal</label>
            <textarea
              style={{ ...inputStyle, minHeight: 80, resize: "vertical", fontFamily: "inherit" }}
              placeholder="Describe what this mission should accomplish…"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              required
            />
          </div>

          {/* Primary metric */}
          <div>
            <label style={labelStyle}>Primary metric</label>
            <input
              style={inputStyle}
              placeholder="e.g. # qualified leads per week"
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              required
            />
          </div>

          {/* Objectives */}
          <div>
            <label style={labelStyle}>Objectives</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {objectives.map((obj, i) => (
                <div key={i} style={{ display: "flex", gap: 8 }}>
                  <input
                    style={{ ...inputStyle }}
                    placeholder={`Objective ${i + 1}`}
                    value={obj}
                    onChange={(e) => updateObjective(i, e.target.value)}
                  />
                  {objectives.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeObjective(i)}
                      style={{
                        flexShrink: 0,
                        padding: "0 10px",
                        border: `1px solid ${c.border}`,
                        borderRadius: 8,
                        background: c.bg,
                        color: "#DC2626",
                        cursor: "pointer",
                        fontSize: 14,
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={addObjective}
                style={{
                  alignSelf: "flex-start",
                  padding: "6px 14px",
                  borderRadius: 99,
                  border: `1px solid ${c.border}`,
                  background: c.bg,
                  color: c.blue,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                + Add objective
              </button>
            </div>
          </div>

          {/* Budget sliders */}
          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>
                Max runs/day — <strong style={{ color: c.text }}>{maxRuns}</strong>
              </label>
              <input
                type="range"
                min={1}
                max={24}
                step={1}
                value={maxRuns}
                onChange={(e) => setMaxRuns(Number(e.target.value))}
                style={{ width: "100%", accentColor: c.blue }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>
                Max $/run — <strong style={{ color: c.text }}>${maxCost.toFixed(2)}</strong>
              </label>
              <input
                type="range"
                min={0.1}
                max={10}
                step={0.1}
                value={maxCost}
                onChange={(e) => setMaxCost(Number(e.target.value))}
                style={{ width: "100%", accentColor: c.blue }}
              />
            </div>
          </div>

          {/* Approval policy toggle */}
          <div>
            <label style={labelStyle}>Approval policy</label>
            <div
              style={{
                display: "inline-flex",
                border: `1px solid ${c.border}`,
                borderRadius: 99,
                overflow: "hidden",
              }}
            >
              {(["auto", "require_approval"] as const).map((policy) => (
                <button
                  key={policy}
                  type="button"
                  onClick={() => setApprovalPolicy(policy)}
                  style={{
                    padding: "7px 18px",
                    border: "none",
                    background: approvalPolicy === policy ? c.blue : c.bg,
                    color: approvalPolicy === policy ? "#fff" : c.text,
                    fontSize: 13,
                    fontWeight: approvalPolicy === policy ? 600 : 400,
                    cursor: "pointer",
                  }}
                >
                  {policy === "auto" ? "Automatic" : "Require approval"}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p style={{ margin: 0, fontSize: 13, color: "#DC2626" }}>{error}</p>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", paddingTop: 4 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: "9px 20px",
                borderRadius: 99,
                border: `1px solid ${c.border}`,
                background: c.bg,
                color: c.text,
                fontSize: 14,
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              style={{
                padding: "9px 24px",
                borderRadius: 99,
                border: "none",
                background: saving ? "#93C5FD" : c.blue,
                color: "#fff",
                fontSize: 14,
                fontWeight: 600,
                cursor: saving ? "not-allowed" : "pointer",
              }}
            >
              {saving ? "Creating…" : "Create Mission"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── MissionsPanel ──────────────────────────────────────────────────────────────
export default function MissionsPanel() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;

  const [missions, setMissions] = useState<Mission[]>([]);
  const [companyGoal, setCompanyGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [syncingNotion, setSyncingNotion] = useState(false);

  const load = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    setError(null);
    try {
      const [data, goal] = await Promise.all([getMissions(founderId), getCompanyGoal(founderId)]);
      setMissions(data);
      setCompanyGoal(goal);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load missions");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (founderId) {
      load();
    }
  }, [founderId, load]);

  const handleCreated = useCallback(() => {
    setShowCreate(false);
    load();
  }, [load]);

  // Group missions by department
  const grouped = DEPARTMENTS.reduce<Record<string, Mission[]>>((acc, dept) => {
    const deptMissions = missions.filter((m) => m.department === dept);
    if (deptMissions.length > 0) acc[dept] = deptMissions;
    return acc;
  }, {});

  // Summary stats
  const activeMissions = missions.filter((m) => m.status === "active").length;
  const totalCost = missions.reduce((s, m) => s + m.total_cost_usd, 0);
  const totalRuns = missions.reduce((s, m) => s + m.run_count, 0);

  return (
    <div
      style={{
        background: c.bg,
        minHeight: "100%",
        padding: "32px 36px",
        maxWidth: 900,
        margin: "0 auto",
      }}
    >
      {/* Page header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 32,
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: c.text,
              margin: "0 0 6px",
              letterSpacing: "-0.02em",
            }}
          >
            Missions
          </h1>
          <p style={{ fontSize: 14, color: c.textMuted, margin: 0 }}>
            Standing autonomous operators for your departments
          </p>
        </div>

        <button
          onClick={() => setShowCreate(true)}
          style={{
            padding: "10px 22px",
            borderRadius: 99,
            border: "none",
            background: c.blue,
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = c.blueHover)
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLButtonElement).style.background = c.blue)
          }
        >
          + New Mission
        </button>
        <button
          onClick={async () => {
            if (!founderId || syncingNotion) return;
            setSyncingNotion(true);
            try {
              await syncMissionNotion(founderId);
              await load();
            } finally {
              setSyncingNotion(false);
            }
          }}
          style={{
            padding: "10px 18px",
            borderRadius: 99,
            border: `1px solid ${c.border}`,
            background: c.bg,
            color: c.text,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {syncingNotion ? "Syncing…" : "Sync Notion"}
        </button>
      </div>

      {companyGoal && (
        <div style={{ marginBottom: 24, padding: "16px 18px", borderRadius: 12, border: `1px solid ${c.border}`, background: c.blueTint }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: c.blue, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>
            Company Goal
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: c.text, marginBottom: 6 }}>{companyGoal.company_goal}</div>
          <div style={{ fontSize: 13, color: c.textMuted, lineHeight: 1.5 }}>North star: {companyGoal.north_star}</div>
          {companyGoal.notion_url && (
            <a href={companyGoal.notion_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: c.blue, marginTop: 8, display: "inline-block" }}>
              Open operating mirror in Notion
            </a>
          )}
        </div>
      )}

      {/* Summary row */}
      {missions.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 16,
            marginBottom: 32,
            flexWrap: "wrap",
          }}
        >
          {[
            { label: "Total missions", value: missions.length },
            { label: "Active", value: activeMissions },
            { label: "Total runs", value: totalRuns },
            { label: "Total cost", value: `$${totalCost.toFixed(2)}` },
            { label: "Open tasks", value: missions.reduce((sum, mission) => sum + mission.tasks.filter((task) => task.status !== "done").length, 0) },
          ].map((stat) => (
            <div
              key={stat.label}
              style={{
                flex: "1 1 100px",
                background: c.surface,
                border: `1px solid ${c.border}`,
                borderRadius: 10,
                padding: "14px 18px",
              }}
            >
              <div style={{ fontSize: 11, color: c.textMuted, marginBottom: 4, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>
                {stat.label}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: c.text }}>
                {stat.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Loading / error states */}
      {loading ? (
        <div
          style={{
            padding: "60px 0",
            textAlign: "center",
            color: c.textMuted,
            fontSize: 14,
          }}
        >
          Loading missions…
        </div>
      ) : error ? (
        <div
          style={{
            padding: "40px 24px",
            textAlign: "center",
            background: "#FEF2F2",
            borderRadius: c.radius,
            border: "1px solid #FECACA",
            color: "#DC2626",
            fontSize: 14,
          }}
        >
          <div style={{ marginBottom: 12 }}>{error}</div>
          <button
            onClick={load}
            style={{
              padding: "7px 18px",
              borderRadius: 99,
              border: "1px solid #FECACA",
              background: c.bg,
              color: "#DC2626",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      ) : missions.length === 0 ? (
        // Empty state
        <div
          style={{
            padding: "72px 24px",
            textAlign: "center",
            border: `1px dashed ${c.border}`,
            borderRadius: 16,
          }}
        >
          <div style={{ fontSize: 36, marginBottom: 16 }}>🤖</div>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: c.text,
              marginBottom: 8,
            }}
          >
            No missions yet
          </div>
          <p style={{ fontSize: 14, color: c.textMuted, margin: "0 0 24px", maxWidth: 360, marginInline: "auto" }}>
            Create a mission to deploy a standing autonomous operator for any department.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            style={{
              padding: "10px 24px",
              borderRadius: 99,
              border: "none",
              background: c.blue,
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            + New Mission
          </button>
        </div>
      ) : (
        // Grouped list
        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          {Object.entries(grouped).map(([dept, deptMissions]) => (
            <div key={dept}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 14,
                }}
              >
                <span style={{ fontSize: 16 }}>
                  {DEPT_ICON[dept as Department] ?? "🤖"}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: c.textMuted,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                  }}
                >
                  {DEPT_LABEL[dept as Department] ?? dept}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: c.textMuted,
                    background: c.surface,
                    border: `1px solid ${c.border}`,
                    borderRadius: 99,
                    padding: "1px 8px",
                    marginLeft: 4,
                  }}
                >
                  {deptMissions.length}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {deptMissions.map((m) => (
                  <MissionCard key={m.id} mission={m} onRefresh={load} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateMissionModal
          founderId={founderId}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
