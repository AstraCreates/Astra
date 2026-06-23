"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { useCompany } from "@/lib/company-context";
import PageHeader from "@/components/PageHeader";
import { CHECKLIST_CATEGORIES, itemOwner, type CLItem, type CLCategory, type CLOwner } from "@/lib/checklist-data";
import { getCompanyGoal, AGENT_LABELS, type CompanyTask } from "@/lib/api";

// ── Status model ─────────────────────────────────────────────────────────────
// Status is derived ENTIRELY from agent task state — the founder cannot check
// anything off by hand. Owner decides how a finished agent task reads:
//   agent  → "done" when the agent delivers
//   assist → "ready" when the agent finishes its prep (founder still acts)
//   founder→ always "founder" (informational; no agent works it)

type RowState = "active" | "awaiting" | "blocked" | "done" | "ready" | "pending" | "founder";

function agentMatches(taskAgents: string[], autoAgent: string): boolean {
  return taskAgents.some(a =>
    a === autoAgent || a.startsWith(autoAgent + "_") || autoAgent.startsWith(a + "_")
  );
}

function matchingTask(item: CLItem, tasks: CompanyTask[]): CompanyTask | null {
  if (!item.autoAgent) return null;
  const candidates = tasks.filter(t => agentMatches(t.owner_agents ?? [], item.autoAgent!));
  if (candidates.length === 0) return null;
  // Prefer done tasks (across all goals) over in-progress over pending.
  return (
    candidates.find(t => t.status === "done") ??
    candidates.find(t => t.status === "in_progress") ??
    candidates[0]
  );
}

function getRowState(item: CLItem, tasks: CompanyTask[]): RowState {
  const owner = itemOwner(item);
  if (owner === "founder") return "founder";
  const task = matchingTask(item, tasks);
  if (!task) return "pending";
  if (task.status === "in_progress") return "active";
  if (task.status === "awaiting_approval") return "awaiting";
  if (task.status === "blocked") return "blocked";
  if (task.status === "done") return owner === "assist" ? "ready" : "done";
  return "pending";
}

// "Settled" = nothing more the system is actively doing on it.
const SETTLED: RowState[] = ["done"];
// "Needs you" = a handoff is waiting on the founder.
const NEEDS_YOU: RowState[] = ["awaiting", "ready"];
const IN_PROGRESS: RowState[] = ["active", "blocked"];

// ── Visual config ────────────────────────────────────────────────────────────

const STATE_META: Record<RowState, { label: string; color: string }> = {
  active:   { label: "Running",   color: "#001AFF" },
  awaiting: { label: "Approve",   color: "#D97706" },
  ready:    { label: "Your turn", color: "#D97706" },
  blocked:  { label: "Blocked",   color: "#DC2626" },
  done:     { label: "Done",      color: "#16A34A" },
  pending:  { label: "Up next",   color: "var(--fd)" },
  founder:  { label: "Your task", color: "var(--fm)" },
};

const OWNER_META: Record<CLOwner, { label: string; color: string; bg: string }> = {
  agent:   { label: "Astra",       color: "#001AFF", bg: "rgba(0,26,255,0.07)" },
  assist:  { label: "Astra + You", color: "#D97706", bg: "rgba(217,119,6,0.09)" },
  founder: { label: "You",         color: "var(--fm)", bg: "var(--s2, rgba(0,0,0,0.04))" },
};

// ── Status glyph ─────────────────────────────────────────────────────────────

function Glyph({ state }: { state: RowState }) {
  const c = STATE_META[state].color;
  if (state === "done") {
    return (
      <span style={{ width: 18, height: 18, borderRadius: "50%", flexShrink: 0, background: "#16A34A", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width="10" height="8" viewBox="0 0 9 7" fill="none"><path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
    );
  }
  if (state === "active") {
    return <span style={{ width: 18, height: 18, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ width: 9, height: 9, borderRadius: "50%", background: c, animation: "cl-pulse 1.5s ease-in-out infinite" }} />
    </span>;
  }
  if (state === "awaiting" || state === "ready") {
    return <span style={{ width: 18, height: 18, borderRadius: "50%", flexShrink: 0, border: `2px solid ${c}`, background: `${c}1a`, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: c }} />
    </span>;
  }
  if (state === "blocked") {
    return <span style={{ width: 18, height: 18, borderRadius: "50%", flexShrink: 0, background: c, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 11, fontWeight: 700 }}>!</span>;
  }
  // pending / founder — hollow ring
  return <span style={{ width: 18, height: 18, borderRadius: "50%", flexShrink: 0, border: `1.5px solid var(--bd)`, background: "transparent" }} />;
}

// ── Owner badge ──────────────────────────────────────────────────────────────

function OwnerBadge({ owner }: { owner: CLOwner }) {
  const m = OWNER_META[owner];
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 600, color: m.color, background: m.bg,
      padding: "2px 8px", borderRadius: 100, flexShrink: 0, whiteSpace: "nowrap",
      letterSpacing: ".01em",
    }}>
      {m.label}
    </span>
  );
}

// ── Task row ─────────────────────────────────────────────────────────────────

function TaskRow({ item, state }: { item: CLItem; state: RowState }) {
  const owner = itemOwner(item);
  const meta = STATE_META[state];
  const settled = state === "done";
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 14px",
      borderRadius: 10,
      background: NEEDS_YOU.includes(state) ? "rgba(217,119,6,0.04)"
                : state === "active" ? "rgba(0,26,255,0.03)"
                : "transparent",
      opacity: settled ? 0.62 : 1,
      transition: "background 0.15s",
    }}>
      <div style={{ marginTop: 1 }}><Glyph state={state} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 13, fontWeight: 500, color: settled ? "var(--fd)" : "var(--fg)",
            textDecoration: settled ? "line-through" : "none", lineHeight: 1.4,
          }}>
            {item.label}
          </span>
        </div>
        {item.detail && !settled && (
          <p style={{ fontSize: 11.5, color: "var(--fd)", margin: "3px 0 0", lineHeight: 1.5 }}>
            {item.detail}
          </p>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 7 }}>
          <OwnerBadge owner={owner} />
          {item.autoAgent && owner !== "founder" && (
            <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>
              {AGENT_LABELS[item.autoAgent] ?? item.autoAgent}
            </span>
          )}
        </div>
      </div>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase",
        color: meta.color, flexShrink: 0, fontFamily: "var(--font-code)", marginTop: 3,
        whiteSpace: "nowrap",
      }}>
        {meta.label}
      </span>
    </div>
  );
}

// ── Category menu row ────────────────────────────────────────────────────────

function MenuRow({
  icon, label, pct, hasActive, selected, onClick,
}: {
  icon: string; label: string; pct: number;
  hasActive: boolean; selected: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 10, width: "100%",
        padding: "8px 10px",
        background: selected ? "rgba(0,26,255,0.06)" : "transparent",
        border: "none", borderRadius: 7, cursor: "pointer", textAlign: "left",
        transition: "background 0.12s",
      }}
      onMouseEnter={e => { if (!selected) e.currentTarget.style.background = "var(--s2, rgba(0,0,0,0.03))"; }}
      onMouseLeave={e => { if (!selected) e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ fontSize: 14, flexShrink: 0, width: 18, textAlign: "center" }}>{icon}</span>
      <span style={{
        flex: 1, fontSize: 12.5, fontWeight: selected ? 600 : 400,
        color: selected ? "#001AFF" : "var(--fg)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>{label}</span>
      {hasActive && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#001AFF", flexShrink: 0, boxShadow: "0 0 5px rgba(0,26,255,0.5)" }} />}
      <span style={{ fontSize: 10, color: pct === 100 ? "#16a34a" : "var(--fd)", fontFamily: "var(--font-code)", flexShrink: 0, fontWeight: 500 }}>{pct}%</span>
    </button>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function ChecklistPage() {
  const { userId } = useDevUser();
  const { companyId, activeCompany } = useCompany();
  const founderId = userId;
  const [tasks, setTasks] = useState<CompanyTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCat, setSelectedCat] = useState<string | null>(null);
  type TabKey = "needsYou" | "inProgress" | "upNext" | "done";
  const [tab, setTab] = useState<TabKey>("needsYou");
  const [userPickedTab, setUserPickedTab] = useState(false);
  const [catMenuOpen, setCatMenuOpen] = useState(false);

  const load = useCallback(async () => {
    if (!founderId) return;
    try {
      const g = await getCompanyGoal(founderId, companyId);
      // Aggregate tasks across ALL goals so completed work from prior goals
      // is reflected in the checklist (not just the current active goal).
      const allTasks = (g?.goals ?? []).flatMap(goal => goal.tasks ?? []);
      setTasks(allTasks);
    } catch {} finally {
      setLoading(false);
    }
  }, [companyId, founderId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);

  const allItems = useMemo(() => CHECKLIST_CATEGORIES.flatMap(c => c.items), []);
  const visibleItems = useMemo(() =>
    selectedCat ? (CHECKLIST_CATEGORIES.find(c => c.id === selectedCat)?.items ?? []) : allItems,
    [selectedCat, allItems]
  );

  // Bucket visible items by resolved state.
  const buckets = useMemo(() => {
    const needsYou: { item: CLItem; state: RowState }[] = [];
    const inProgress: { item: CLItem; state: RowState }[] = [];
    const upNext: { item: CLItem; state: RowState }[] = [];
    const done: { item: CLItem; state: RowState }[] = [];
    for (const item of visibleItems) {
      const state = getRowState(item, tasks);
      if (NEEDS_YOU.includes(state)) needsYou.push({ item, state });
      else if (IN_PROGRESS.includes(state)) inProgress.push({ item, state });
      else if (SETTLED.includes(state)) done.push({ item, state });
      else upNext.push({ item, state }); // pending + founder
    }
    return { needsYou, inProgress, upNext, done };
  }, [visibleItems, tasks]);

  // On initial load, jump to the first tab that has something.
  // Skip once the user has explicitly clicked a tab.
  useEffect(() => {
    if (userPickedTab) return;
    const order: TabKey[] = ["needsYou", "inProgress", "upNext", "done"];
    if (buckets[tab].length === 0) {
      const next = order.find(k => buckets[k].length > 0);
      if (next && next !== tab) setTab(next);
    }
  }, [buckets, tab, userPickedTab]);

  // Header + sidebar stats (across ALL items, regardless of filter).
  const stats = useMemo(() => {
    let done = 0, active = 0, needsYou = 0;
    for (const item of allItems) {
      const s = getRowState(item, tasks);
      if (s === "done") done++;
      else if (s === "active" || s === "blocked") active++;
      else if (NEEDS_YOU.includes(s)) needsYou++;
    }
    return { done, active, needsYou };
  }, [allItems, tasks]);

  const catStats = useMemo(() => {
    const map: Record<string, { done: number; hasActive: boolean }> = {};
    for (const cat of CHECKLIST_CATEGORIES) {
      let done = 0, hasActive = false;
      for (const item of cat.items) {
        const s = getRowState(item, tasks);
        if (s === "done") done++;
        if (s === "active" || NEEDS_YOU.includes(s)) hasActive = true;
      }
      map[cat.id] = { done, hasActive };
    }
    return map;
  }, [tasks]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`@keyframes cl-pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.82); } }`}</style>

      <PageHeader
        title={`${activeCompany?.name || "Company"} Checklist`}
        badge={stats.needsYou > 0 ? { label: `${stats.needsYou} needs you`, color: "amber" }
             : stats.active > 0 ? { label: `${stats.active} active`, color: "blue" }
             : { label: "all clear", color: "green" }}
        stats={[
          { label: "Done",      value: String(stats.done) },
          { label: "Active",    value: String(stats.active) },
          { label: "Needs you", value: String(stats.needsYou) },
          { label: "Total",     value: String(allItems.length) },
        ]}
      />

      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Tab bar + category filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "0 24px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
          {([
            { key: "needsYou",   label: "Needs you",   accent: "#D97706", count: buckets.needsYou.length },
            { key: "inProgress", label: "In progress", accent: "#001AFF", count: buckets.inProgress.length },
            { key: "upNext",     label: "Up next",     accent: "var(--fg)", count: buckets.upNext.length },
            { key: "done",       label: "Done",        accent: "#16A34A", count: buckets.done.length },
          ] as { key: TabKey; label: string; accent: string; count: number }[]).map(t => {
            const on = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => { setTab(t.key); setUserPickedTab(true); }}
                style={{
                  display: "flex", alignItems: "center", gap: 7,
                  padding: "13px 14px 12px", border: "none", background: "transparent",
                  cursor: "pointer", position: "relative",
                  borderBottom: `2px solid ${on ? t.accent : "transparent"}`,
                  marginBottom: -1,
                }}
              >
                <span style={{ fontSize: 13, fontWeight: on ? 700 : 500, color: on ? (t.accent === "var(--fg)" ? "var(--fg)" : t.accent) : "var(--fm)", letterSpacing: "-0.01em" }}>
                  {t.label}
                </span>
                {t.count > 0 && (
                  <span style={{
                    fontSize: 10.5, fontWeight: 600, fontFamily: "var(--font-code)",
                    color: on ? (t.accent === "var(--fg)" ? "var(--fg)" : t.accent) : "var(--fd)",
                    background: on && t.accent !== "var(--fg)" ? `${t.accent}14` : "var(--s2, rgba(0,0,0,0.04))",
                    padding: "1px 7px", borderRadius: 100,
                  }}>{t.count}</span>
                )}
              </button>
            );
          })}

          {/* Category filter dropdown — replaces the old left rail */}
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <button
              onClick={() => setCatMenuOpen(v => !v)}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "7px 12px", borderRadius: 8,
                border: "1px solid var(--bd)", background: "var(--surface)",
                cursor: "pointer", fontSize: 12, fontWeight: 500, color: "var(--fg)",
              }}
            >
              <span style={{ fontSize: 13 }}>{selectedCat ? CHECKLIST_CATEGORIES.find(c => c.id === selectedCat)?.icon : "≡"}</span>
              <span style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {selectedCat ? CHECKLIST_CATEGORIES.find(c => c.id === selectedCat)?.label : "All categories"}
              </span>
              <span style={{ fontSize: 9, color: "var(--fm)" }}>▾</span>
            </button>
            {catMenuOpen && (
              <>
                <div onClick={() => setCatMenuOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
                <div style={{
                  position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 41,
                  width: 248, maxHeight: 380, overflowY: "auto",
                  background: "var(--surface)", border: "1px solid var(--bd)",
                  borderRadius: 10, boxShadow: "0 8px 32px rgba(0,0,0,0.12)", padding: 6,
                }}>
                  <MenuRow icon="≡" label="All categories" pct={allItems.length ? Math.round((stats.done / allItems.length) * 100) : 0} hasActive={stats.active > 0} selected={selectedCat === null} onClick={() => { setSelectedCat(null); setCatMenuOpen(false); }} />
                  <div style={{ height: 1, background: "var(--bd)", margin: "5px 6px" }} />
                  {CHECKLIST_CATEGORIES.map(cat => {
                    const cs = catStats[cat.id];
                    const pct = cat.items.length ? Math.round(((cs?.done ?? 0) / cat.items.length) * 100) : 0;
                    return (
                      <MenuRow key={cat.id} icon={cat.icon} label={cat.label} pct={pct} hasActive={cs?.hasActive ?? false} selected={selectedCat === cat.id} onClick={() => { setSelectedCat(cat.id); setCatMenuOpen(false); }} />
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Active tab body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px 56px" }}>
          {loading ? (
            <p style={{ fontSize: 13, color: "var(--fd)", padding: "20px 0" }}>Loading…</p>
          ) : (
            <>
              {tab === "needsYou" && buckets.needsYou.length > 0 && (
                <p style={{ fontSize: 12, color: "var(--fd)", margin: "0 0 16px", lineHeight: 1.5 }}>
                  Agents finished their part — these are waiting on you to act.
                </p>
              )}
              {buckets[tab].length === 0 ? (
                <p style={{ fontSize: 13, color: "var(--fd)", padding: "20px 0" }}>
                  {tab === "needsYou" ? "Nothing waiting on you right now."
                   : tab === "inProgress" ? "No agents are working on this list right now."
                   : tab === "upNext" ? "Nothing queued."
                   : "Nothing completed yet."}
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {buckets[tab].map(({ item, state }) => <TaskRow key={item.id} item={item} state={state} />)}
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
