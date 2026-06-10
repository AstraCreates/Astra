"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import PageHeader from "@/components/PageHeader";
import { CHECKLIST_CATEGORIES, type CLItem, type CLCategory } from "@/lib/checklist-data";
import {
  getCompanyGoal, approveNextGoal, runCompanyCycle, AGENT_LABELS,
  type CompanyTask, type CompanyGoal, type CompanyGoalEntry,
} from "@/lib/api";

// ── Storage ────────────────────────────────────────────────────────────────

const KEY_DONE = "astra_cl_done";

function loadDone(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try { const r = localStorage.getItem(KEY_DONE); return r ? new Set(JSON.parse(r) as string[]) : new Set(); }
  catch { return new Set(); }
}
function saveDone(s: Set<string>) { try { localStorage.setItem(KEY_DONE, JSON.stringify([...s])); } catch {} }

// ── Status helpers ─────────────────────────────────────────────────────────

function agentMatches(taskAgents: string[], autoAgent: string): boolean {
  return taskAgents.some(a =>
    a === autoAgent || a.startsWith(autoAgent + "_") || autoAgent.startsWith(a + "_")
  );
}

type ItemStatus = "active" | "awaiting" | "done" | "blocked" | "pending";

function getItemStatus(item: CLItem, tasks: CompanyTask[], doneSet: Set<string>): ItemStatus {
  if (doneSet.has(item.id)) return "done";
  if (!item.autoAgent) return "pending";
  const task = tasks.find(t => agentMatches(t.owner_agents ?? [], item.autoAgent!));
  if (!task) return "pending";
  if (task.status === "done") return "done";
  if (task.status === "in_progress") return "active";
  if (task.status === "awaiting_approval") return "awaiting";
  if (task.status === "blocked") return "blocked";
  return "pending";
}

function matchingTask(item: CLItem, tasks: CompanyTask[]): CompanyTask | null {
  if (!item.autoAgent) return null;
  return tasks.find(t => agentMatches(t.owner_agents ?? [], item.autoAgent!)) ?? null;
}

// ── Left sidebar item ──────────────────────────────────────────────────────

function SidebarRow({
  icon, label, done, total, hasActive, selected, onClick,
}: {
  icon: string; label: string; done: number; total: number;
  hasActive: boolean; selected: boolean; onClick: () => void;
}) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 9,
        padding: "7px 14px",
        background: selected ? "rgba(0,26,255,0.07)" : "transparent",
        borderLeft: `3px solid ${selected ? "#001AFF" : "transparent"}`,
        border: "none",
        cursor: "pointer",
        textAlign: "left",
        transition: "background 0.12s",
      }}
    >
      <span style={{ fontSize: 14, flexShrink: 0, width: 18, textAlign: "center" }}>{icon}</span>
      <span style={{
        flex: 1, fontSize: 12, fontWeight: selected ? 600 : 400,
        color: selected ? "#001AFF" : "var(--fg)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {label}
      </span>
      {hasActive && (
        <span style={{
          width: 6, height: 6, borderRadius: "50%", background: "#001AFF",
          flexShrink: 0, boxShadow: "0 0 5px rgba(0,26,255,0.5)",
        }} />
      )}
      <span style={{
        fontSize: 10, color: done === total && total > 0 ? "#16a34a" : "var(--fd)",
        fontFamily: "var(--font-code)", flexShrink: 0,
        fontWeight: 500,
      }}>
        {pct}%
      </span>
    </button>
  );
}

// ── Section wrapper ────────────────────────────────────────────────────────

function Section({
  title, count, accent, collapsible, collapsed, onToggle, empty, children,
}: {
  title: string; count: number; accent?: string;
  collapsible?: boolean; collapsed?: boolean; onToggle?: () => void;
  empty?: string; children?: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 32 }}>
      <div
        onClick={collapsible ? onToggle : undefined}
        style={{
          display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
          cursor: collapsible ? "pointer" : "default",
          userSelect: "none",
        }}
      >
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: ".1em",
          textTransform: "uppercase", color: accent ?? "var(--fd)",
          fontFamily: "var(--font-code)",
        }}>
          {title}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 600, color: accent ?? "var(--fd)",
          background: accent ? `${accent}18` : "var(--surface)",
          border: `1px solid ${accent ? `${accent}30` : "var(--bd)"}`,
          padding: "1px 7px", fontFamily: "var(--font-code)",
        }}>
          {count}
        </span>
        {collapsible && (
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--fd)" }}>
            {collapsed ? "▶ show" : "▼ hide"}
          </span>
        )}
      </div>
      {empty && count === 0 ? (
        <p style={{ fontSize: 12, color: "var(--fd)", margin: 0, padding: "10px 0" }}>{empty}</p>
      ) : (
        !collapsed && children
      )}
    </div>
  );
}

// ── Active card ────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  active:   { label: "Running",  color: "#001AFF", bg: "rgba(0,26,255,0.06)",  stripe: "#001AFF" },
  awaiting: { label: "Approval", color: "#D97706", bg: "rgba(217,119,6,0.06)", stripe: "#D97706" },
  blocked:  { label: "Blocked",  color: "#DC2626", bg: "rgba(220,38,38,0.06)", stripe: "#DC2626" },
};

function ActiveCard({ item, status, task }: { item: CLItem; status: "active" | "awaiting" | "blocked"; task?: CompanyTask | null }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <div style={{
      display: "flex", gap: 0, marginBottom: 8,
      background: cfg.bg,
      border: `1px solid ${cfg.color}30`,
      overflow: "hidden",
    }}>
      <div style={{ width: 3, flexShrink: 0, background: cfg.stripe }} />
      <div style={{ flex: 1, padding: "12px 14px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)", lineHeight: 1.35, flex: 1 }}>
            {item.label}
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase",
            color: cfg.color, background: `${cfg.color}18`,
            border: `1px solid ${cfg.color}40`,
            padding: "2px 8px", flexShrink: 0, fontFamily: "var(--font-code)",
          }}>
            {cfg.label}
          </span>
        </div>
        {item.detail && (
          <p style={{ fontSize: 11, color: "var(--fd)", margin: "5px 0 0", lineHeight: 1.5 }}>
            {item.detail}
          </p>
        )}
        {item.autoAgent && (
          <span style={{ fontSize: 10, color: cfg.color, marginTop: 6, display: "inline-block", fontFamily: "var(--font-code)" }}>
            {item.autoAgent}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Done row ───────────────────────────────────────────────────────────────

function DoneRow({ item, canUncheck, onUncheck }: { item: CLItem; canUncheck: boolean; onUncheck: () => void }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, padding: "7px 0",
      borderBottom: "1px solid var(--bd)",
    }}>
      <span style={{
        width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
        background: "#16a34a", display: "flex", alignItems: "center", justifyContent: "center",
        cursor: canUncheck ? "pointer" : "default",
      }} onClick={canUncheck ? onUncheck : undefined}>
        <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
          <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span style={{
        flex: 1, fontSize: 12, color: "var(--fd)",
        textDecoration: "line-through", lineHeight: 1.4,
      }}>
        {item.label}
      </span>
      {item.autoAgent && (
        <span style={{ fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-code)", flexShrink: 0 }}>
          {item.autoAgent}
        </span>
      )}
    </div>
  );
}

// ── Pending row ────────────────────────────────────────────────────────────

function PendingRow({ item, onCheck }: { item: CLItem; onCheck: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "7px 0",
        borderBottom: "1px solid var(--bd)",
        background: hovered ? "rgba(0,26,255,0.02)" : "transparent",
        transition: "background 0.1s",
      }}
    >
      <button
        onClick={onCheck}
        style={{
          width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
          border: "1.5px solid var(--bd)",
          background: hovered ? "rgba(0,26,255,0.08)" : "transparent",
          cursor: "pointer", padding: 0,
          transition: "border-color 0.12s, background 0.12s",
          borderColor: hovered ? "#001AFF" : undefined,
        }}
      />
      <span style={{ flex: 1, fontSize: 12, color: "var(--fg)", lineHeight: 1.4 }}>
        {item.label}
      </span>
      {item.autoAgent && (
        <span style={{
          fontSize: 9, color: "var(--fd)", fontFamily: "var(--font-code)", flexShrink: 0,
          background: "var(--surface)", border: "1px solid var(--bd)",
          padding: "1px 6px",
        }}>
          {item.autoAgent}
        </span>
      )}
    </div>
  );
}

// ── Category group (Up Next) ───────────────────────────────────────────────

function CategoryGroup({ cat, items, onCheck }: { cat: CLCategory; items: CLItem[]; onCheck: (id: string) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ marginBottom: 20 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: "flex", alignItems: "center", gap: 8, width: "100%",
          padding: "6px 0", border: "none", background: "transparent",
          cursor: "pointer", textAlign: "left",
        }}
      >
        <span style={{ fontSize: 13 }}>{cat.icon}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", flex: 1 }}>{cat.label}</span>
        <span style={{ fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-code)" }}>{items.length}</span>
        <span style={{ fontSize: 10, color: "var(--fd)", marginLeft: 4 }}>{open ? "▼" : "▶"}</span>
      </button>
      {open && items.map(item => (
        <PendingRow key={item.id} item={item} onCheck={() => onCheck(item.id)} />
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function ChecklistPage() {
  const { user } = useDevUser();
  const [tasks, setTasks] = useState<CompanyTask[]>([]);
  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [doneSet, setDoneSet] = useState<Set<string>>(new Set());
  const [selectedCat, setSelectedCat] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);

  useEffect(() => { setDoneSet(loadDone()); }, []);

  const load = useCallback(async () => {
    if (!user?.id) return;
    try {
      const g = await getCompanyGoal(user.id);
      setGoal(g);
      const entry = g?.goals?.find(x => x.id === g.current_goal_id) ?? null;
      setTasks(entry?.tasks ?? []);
    } catch {}
  }, [user?.id]);

  const currentGoal: CompanyGoalEntry | null = goal?.goals?.find(g => g.id === goal.current_goal_id) ?? null;
  const proposed = currentGoal?.status === "proposed";
  const doneGoals = (goal?.goals ?? []).filter(g => g.status === "done").reverse();
  const runs = (goal?.operating_sessions ?? []).slice().reverse().slice(0, 6);

  const decideGoal = async (approved: boolean) => {
    if (!user?.id) return;
    setBusy(approved ? "approve" : "reject");
    try {
      await approveNextGoal(user.id, approved);
      if (approved && goal?.root_session_id) window.location.assign(`/s/${goal.root_session_id}`);
      else await load();
    } catch {} finally { setBusy(null); }
  };

  const runNow = async () => {
    if (!user?.id) return;
    setBusy("run");
    try {
      const r = await runCompanyCycle(user.id);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
      else await load();
    } catch {} finally { setBusy(null); }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);

  const toggleDone = useCallback((id: string) => {
    setDoneSet(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      saveDone(next);
      return next;
    });
  }, []);

  const allItems = useMemo(() => CHECKLIST_CATEGORIES.flatMap(c => c.items), []);

  const visibleItems = useMemo(() =>
    selectedCat ? (CHECKLIST_CATEGORIES.find(c => c.id === selectedCat)?.items ?? []) : allItems,
    [selectedCat, allItems]
  );

  const { activeItems, doneItems, pendingItems } = useMemo(() => {
    const active: CLItem[] = [], done: CLItem[] = [], pending: CLItem[] = [];
    for (const item of visibleItems) {
      const s = getItemStatus(item, tasks, doneSet);
      if (s === "active" || s === "awaiting" || s === "blocked") active.push(item);
      else if (s === "done") done.push(item);
      else pending.push(item);
    }
    return { activeItems: active, doneItems: done, pendingItems: pending };
  }, [visibleItems, tasks, doneSet]);

  const pendingByCategory = useMemo(() => {
    const groups: { cat: CLCategory; items: CLItem[] }[] = [];
    for (const cat of CHECKLIST_CATEGORIES) {
      const items = pendingItems.filter(item => cat.items.some(ci => ci.id === item.id));
      if (items.length > 0) groups.push({ cat, items });
    }
    return groups;
  }, [pendingItems]);

  // Sidebar stats per category
  const catStats = useMemo(() => {
    const map: Record<string, { done: number; hasActive: boolean }> = {};
    for (const cat of CHECKLIST_CATEGORIES) {
      let done = 0, hasActive = false;
      for (const item of cat.items) {
        const s = getItemStatus(item, tasks, doneSet);
        if (s === "done") done++;
        if (s === "active" || s === "awaiting") hasActive = true;
      }
      map[cat.id] = { done, hasActive };
    }
    return map;
  }, [tasks, doneSet]);

  const totalDone = useMemo(() => allItems.filter(i => getItemStatus(i, tasks, doneSet) === "done").length, [allItems, tasks, doneSet]);
  const totalActive = useMemo(() => allItems.filter(i => { const s = getItemStatus(i, tasks, doneSet); return s === "active" || s === "awaiting"; }).length, [allItems, tasks, doneSet]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <PageHeader
        title="Checklist"
        badge={totalActive > 0 ? { label: `${totalActive} active`, color: "blue" } : { label: "ready", color: "green" }}
        stats={[
          { label: "Done",      value: String(totalDone) },
          { label: "Active",    value: String(totalActive) },
          { label: "Remaining", value: String(allItems.length - totalDone - totalActive) },
          { label: "Total",     value: String(allItems.length) },
        ]}
      />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Left sidebar ── */}
        <aside style={{
          width: 216, flexShrink: 0,
          borderRight: "1px solid var(--bd)",
          overflowY: "auto",
          background: "var(--surface)",
          padding: "10px 0 24px",
        }}>
          <SidebarRow
            icon="≡"
            label="All"
            done={totalDone}
            total={allItems.length}
            hasActive={totalActive > 0}
            selected={selectedCat === null}
            onClick={() => setSelectedCat(null)}
          />
          <div style={{ height: 1, background: "var(--bd)", margin: "8px 12px 6px" }} />
          {CHECKLIST_CATEGORIES.map(cat => (
            <SidebarRow
              key={cat.id}
              icon={cat.icon}
              label={cat.label}
              done={catStats[cat.id]?.done ?? 0}
              total={cat.items.length}
              hasActive={catStats[cat.id]?.hasActive ?? false}
              selected={selectedCat === cat.id}
              onClick={() => setSelectedCat(cat.id)}
            />
          ))}
        </aside>

        {/* ── Right content ── */}
        <main style={{ flex: 1, overflowY: "auto", padding: "24px 28px 48px" }}>

          {/* ── Company goals (current goal + approval + progression) ── */}
          {goal && (currentGoal || doneGoals.length > 0) && (() => {
            const cr = (n?: number) => `◈ ${(n ?? 0).toLocaleString()}`;
            const ago = (iso?: string | null) => {
              if (!iso) return "";
              const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
              return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
            };
            const ctasks = currentGoal?.tasks ?? [];
            const cdone = ctasks.filter(t => t.status === "done").length;
            return (
              <div style={{ marginBottom: 28, border: "1px solid var(--bd2)", background: "var(--surface)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "14px 16px", borderBottom: "1px solid var(--bd)", background: proposed ? "var(--adim)" : "transparent" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: proposed ? "var(--amber)" : "var(--fm)", marginBottom: 4 }}>
                      {proposed ? "▲ Next goal proposed · awaiting approval" : `Company goal${currentGoal?.kind === "launch" ? " · launch" : ""}`}
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)", lineHeight: 1.35 }}>{currentGoal?.title ?? "—"}</div>
                    <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 4, fontFamily: "var(--font-code)" }}>
                      {ctasks.length > 0 && `${cdone}/${ctasks.length} tasks · `}{cr(currentGoal?.credits_used)} credits
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    {proposed ? (
                      <>
                        <button onClick={() => decideGoal(true)} disabled={!!busy} style={{ padding: "8px 16px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#001AFF", border: "none", cursor: "pointer", opacity: busy ? 0.5 : 1 }}>{busy === "approve" ? "Starting…" : "✓ Approve & start"}</button>
                        <button onClick={() => decideGoal(false)} disabled={!!busy} style={{ padding: "8px 12px", fontSize: 12, color: "var(--fd)", background: "var(--surface)", border: "1px solid var(--bd2)", cursor: "pointer", opacity: busy ? 0.5 : 1 }}>{busy === "reject" ? "…" : "Reject"}</button>
                      </>
                    ) : currentGoal && currentGoal.status !== "done" ? (
                      <button onClick={runNow} disabled={!!busy} style={{ padding: "8px 16px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#001AFF", border: "none", cursor: "pointer", opacity: busy ? 0.5 : 1 }}>{busy === "run" ? "Starting…" : "▶ Run now"}</button>
                    ) : null}
                  </div>
                </div>
                {/* current goal tasks */}
                {currentGoal && currentGoal.status !== "done" && ctasks.map((t, i) => {
                  const tint = t.status === "done" ? "var(--green)" : t.status === "in_progress" ? "#001AFF" : t.status === "awaiting_approval" ? "var(--amber)" : "var(--fm)";
                  const owners = t.owner_agents ?? [], dn = t.done_agents ?? [];
                  return (
                    <div key={t.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 16px", borderTop: i === 0 ? "1px solid var(--bd)" : "1px solid var(--bd)" }}>
                      <span style={{ marginTop: 5, width: 7, height: 7, flexShrink: 0, borderRadius: "50%", background: tint }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, color: t.status === "done" ? "var(--fd)" : "var(--fg)", textDecoration: t.status === "done" ? "line-through" : "none", lineHeight: 1.4 }}>{t.title}</div>
                        {owners.length > 0 && <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 2, fontFamily: "var(--font-code)" }}>{owners.map(o => (dn.includes(o) ? `✓${AGENT_LABELS[o] ?? o}` : (AGENT_LABELS[o] ?? o))).join(" · ")}</div>}
                      </div>
                      <span style={{ flexShrink: 0, fontSize: 9, color: tint, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", fontFamily: "var(--font-code)" }}>{t.status === "awaiting_approval" ? "approval" : t.status.replace(/_/g, " ")}</span>
                    </div>
                  );
                })}
                {/* completed goals */}
                {doneGoals.length > 0 && (
                  <div style={{ borderTop: "1px solid var(--bd)" }}>
                    {doneGoals.map(g => (
                      <div key={g.id} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 16px", fontSize: 12, borderTop: "1px solid var(--bd)" }}>
                        <span style={{ color: "var(--green)", fontSize: 10, flexShrink: 0, fontFamily: "var(--font-code)" }}>✓</span>
                        <span style={{ flex: 1, color: "var(--fm)", textDecoration: "line-through", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.title}</span>
                        <span style={{ fontSize: 9, color: "var(--fm)", flexShrink: 0, fontFamily: "var(--font-code)" }}>{cr(g.credits_used)}</span>
                        <span style={{ fontSize: 9, color: "var(--fm)", flexShrink: 0, fontFamily: "var(--font-code)" }}>{ago(g.completed_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {/* recent sub-runs */}
                {runs.length > 0 && (
                  <div style={{ borderTop: "1px solid var(--bd)" }}>
                    {runs.map(r => (
                      <a key={r.session_id} href={`/s/${r.session_id}`} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 16px", fontSize: 11.5, borderTop: "1px solid var(--bd)", textDecoration: "none", color: "var(--fg)" }}>
                        <span style={{ width: 6, height: 6, flexShrink: 0, borderRadius: "50%", background: r.status === "done" ? "var(--green)" : r.status === "error" ? "var(--red)" : "#001AFF" }} />
                        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--fm)" }}>{r.summary || "Operating run"}</span>
                        <span style={{ fontSize: 9, color: "var(--fm)", flexShrink: 0, fontFamily: "var(--font-code)" }}>{cr(r.credits_used)}</span>
                        <span style={{ fontSize: 9, color: "var(--fm)", flexShrink: 0, fontFamily: "var(--font-code)" }}>{ago(r.started_at)}</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Active section */}
          <Section
            title="Active"
            count={activeItems.length}
            accent="#001AFF"
            empty="No items running right now — agents are idle."
          >
            {activeItems.map(item => {
              const s = getItemStatus(item, tasks, doneSet);
              const validStatus = (s === "active" || s === "awaiting" || s === "blocked") ? s : "active";
              return (
                <ActiveCard
                  key={item.id}
                  item={item}
                  status={validStatus}
                  task={matchingTask(item, tasks)}
                />
              );
            })}
          </Section>

          {/* Done section */}
          <Section
            title="Done"
            count={doneItems.length}
            collapsible
            collapsed={!showDone}
            onToggle={() => setShowDone(v => !v)}
          >
            {doneItems.map(item => (
              <DoneRow
                key={item.id}
                item={item}
                canUncheck={doneSet.has(item.id)}
                onUncheck={() => toggleDone(item.id)}
              />
            ))}
          </Section>

          {/* Up Next section */}
          <Section title="Up Next" count={pendingItems.length}>
            {pendingByCategory.map(({ cat, items }) => (
              <CategoryGroup
                key={cat.id}
                cat={cat}
                items={items}
                onCheck={toggleDone}
              />
            ))}
          </Section>

        </main>
      </div>
    </div>
  );
}
