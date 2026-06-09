"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "@/components/AstraGradient";
import { CHECKLIST_CATEGORIES, type CLItem, type CLCategory } from "@/lib/checklist-data";
import {
  getCompanyGoal, runCompanyCycle, setCompanyGoalStatus, syncMissionNotion,
  AGENT_LABELS,
  type CompanyGoal, type CompanyTask,
} from "@/lib/api";

// ── Storage ────────────────────────────────────────────────────────────────

const KEY_DONE   = "astra_cl_done";
const KEY_CATS   = "astra_cl_cats";

function loadDone(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try { const r = localStorage.getItem(KEY_DONE); return r ? new Set(JSON.parse(r) as string[]) : new Set(); }
  catch { return new Set(); }
}
function saveDone(s: Set<string>) { try { localStorage.setItem(KEY_DONE, JSON.stringify([...s])); } catch {} }

function loadCats(): string[] | null {
  if (typeof window === "undefined") return null;
  try { const r = localStorage.getItem(KEY_CATS); return r ? JSON.parse(r) : null; }
  catch { return null; }
}
function saveCats(ids: string[]) { try { localStorage.setItem(KEY_CATS, JSON.stringify(ids)); } catch {} }

// ── Agent matching ─────────────────────────────────────────────────────────

function agentMatches(taskAgents: string[], autoAgent: string): boolean {
  return taskAgents.some(a =>
    a === autoAgent ||
    a.startsWith(autoAgent + "_") ||
    autoAgent.startsWith(a + "_")
  );
}

function findTask(autoAgent: string | undefined, tasks: CompanyTask[]): CompanyTask | null {
  if (!autoAgent) return null;
  return tasks.find(t => agentMatches(t.owner_agents ?? [], autoAgent)) ?? null;
}

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

// ── Category Picker ────────────────────────────────────────────────────────

function CategoryPicker({ initial, onSave }: { initial: string[]; onSave: (ids: string[]) => void }) {
  const [sel, setSel] = useState<Set<string>>(new Set(initial));
  const toggle = (id: string) => setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "var(--bg, #fff)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ position: "relative", overflow: "hidden", background: "#001aff", padding: "28px 28px 24px", flexShrink: 0 }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#fff", marginBottom: 6, letterSpacing: "-0.02em" }}>Build your launch plan</div>
          <div style={{ fontSize: 13, color: "rgba(255,255,255,0.75)", maxWidth: 480, lineHeight: 1.5 }}>
            Pick the areas relevant to your startup. You can change this anytime.
          </div>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(175px, 1fr))", gap: 10 }}>
          {CHECKLIST_CATEGORIES.map(cat => {
            const on = sel.has(cat.id);
            return (
              <button key={cat.id} type="button" onClick={() => toggle(cat.id)} style={{
                display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px", textAlign: "left",
                border: `2px solid ${on ? "var(--blue)" : "var(--bd)"}`,
                background: on ? "var(--bdim)" : "var(--surface)",
                cursor: "pointer", transition: "border-color .1s, background .1s",
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 22 }}>{cat.icon}</span>
                  {on && <span style={{ fontSize: 11, color: "var(--blue)", fontWeight: 700 }}>✓</span>}
                </div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>{cat.label}</div>
                <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>{cat.items.length} items</div>
              </button>
            );
          })}
        </div>
      </div>
      <div style={{ padding: "16px 28px", borderTop: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <button type="button" disabled={sel.size === 0} onClick={() => onSave([...sel])} className="btn pri" style={{ opacity: sel.size === 0 ? 0.5 : 1 }}>
          Build checklist →
        </button>
        <span style={{ fontSize: 12, color: "var(--fm)" }}>
          {sel.size === 0 ? "Select at least one" : `${sel.size} area${sel.size > 1 ? "s" : ""} selected`}
        </span>
      </div>
    </div>
  );
}

// ── Active item card ───────────────────────────────────────────────────────

function ActiveItemCard({ item, cat, task }: { item: CLItem; cat: CLCategory; task: CompanyTask }) {
  const needsApproval = task.status === "awaiting_approval";
  const agentLabel = AGENT_LABELS[item.autoAgent ?? ""] ?? item.autoAgent ?? "";

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 16px",
      border: `1px solid ${needsApproval ? "var(--ab)" : "var(--bb)"}`,
      background: needsApproval ? "var(--adim)" : "var(--bdim)",
    }}>
      <div style={{ marginTop: 3, flexShrink: 0 }}>
        <span style={{
          display: "block", width: 8, height: 8, borderRadius: "50%",
          background: needsApproval ? "var(--amber)" : "var(--blue)",
          animation: needsApproval ? "none" : "cl-pulse 1.5s ease-in-out infinite",
        }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", lineHeight: 1.4 }}>{item.label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: "var(--fm)" }}>{cat.icon} {cat.label}</span>
          <span style={{ fontSize: 11, color: needsApproval ? "var(--amber)" : "var(--blue)", fontWeight: 600 }}>
            via {agentLabel}
          </span>
        </div>
      </div>
      <span style={{
        flexShrink: 0, fontSize: 9, padding: "2px 8px",
        border: `1px solid ${needsApproval ? "var(--ab)" : "var(--bb)"}`,
        color: needsApproval ? "var(--amber)" : "var(--blue)",
        fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em",
        fontFamily: "var(--font-code)",
      }}>
        {needsApproval ? "Needs approval" : "Running"}
      </span>
    </div>
  );
}

// ── Pending item row ───────────────────────────────────────────────────────

function PendingRow({ item, cat, onCheck }: { item: CLItem; cat: CLCategory; onCheck: () => void }) {
  const hasAgent = !!item.autoAgent;
  return (
    <label style={{
      display: "flex", alignItems: "flex-start", gap: 11, padding: "10px 14px",
      cursor: "pointer", borderBottom: "1px solid var(--bd)",
      background: "var(--surface)",
    }}>
      <input type="checkbox" onChange={onCheck} style={{ position: "absolute", opacity: 0, width: 0, height: 0 }} />
      <div style={{ marginTop: 3, flexShrink: 0, width: 15, height: 15,
        border: "2px solid var(--bd2)", background: "transparent",
        display: "flex", alignItems: "center", justifyContent: "center" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)", lineHeight: 1.4 }}>{item.label}</div>
        {item.detail && (
          <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 2, lineHeight: 1.45 }}>{item.detail}</div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0, marginTop: 2 }}>
        <span style={{ fontSize: 10, color: "var(--fm)" }}>{cat.icon}</span>
        {hasAgent ? (
          <span style={{ fontSize: 9, padding: "2px 6px", background: "var(--bdim)", border: "1px solid var(--bb)",
            color: "var(--blue)", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em",
            fontFamily: "var(--font-code)", whiteSpace: "nowrap" }}>
            Agent
          </span>
        ) : (
          <span style={{ fontSize: 9, padding: "2px 6px", background: "transparent", border: "1px solid var(--bd2)",
            color: "var(--fm)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em",
            fontFamily: "var(--font-code)", whiteSpace: "nowrap" }}>
            Manual
          </span>
        )}
      </div>
    </label>
  );
}

// ── Done item row ──────────────────────────────────────────────────────────

function DoneRow({ item, cat, onUncheck }: { item: CLItem; cat: CLCategory; onUncheck: () => void }) {
  return (
    <label style={{
      display: "flex", alignItems: "center", gap: 10, padding: "8px 14px",
      cursor: "pointer", borderBottom: "1px solid var(--bd)", opacity: 0.55,
    }}>
      <input type="checkbox" checked onChange={onUncheck} style={{ position: "absolute", opacity: 0, width: 0, height: 0 }} />
      <div style={{ flexShrink: 0, width: 15, height: 15, background: "var(--green)",
        display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontSize: 9, color: "#fff", fontWeight: 700 }}>✓</span>
      </div>
      <span style={{ flex: 1, fontSize: 12, fontWeight: 500, color: "var(--fm)", textDecoration: "line-through", lineHeight: 1.3 }}>
        {item.label}
      </span>
      <span style={{ fontSize: 10, color: "var(--fm)", flexShrink: 0 }}>{cat.icon}</span>
    </label>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function MissionsPanel() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [runsOpen, setRunsOpen] = useState(false);
  const [doneOpen, setDoneOpen] = useState(false);

  const [done, setDone] = useState<Set<string>>(new Set());
  const [selectedCats, setSelectedCats] = useState<string[] | null>(null);
  const [editingCats, setEditingCats] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setDone(loadDone());
    setSelectedCats(loadCats());
    setMounted(true);
  }, []);

  const loadGoal = useCallback(async () => {
    if (!founderId) return;
    try { setGoal(await getCompanyGoal(founderId)); } catch {}
  }, [founderId]);

  useEffect(() => {
    if (!founderId) return;
    loadGoal();
    const t = setInterval(loadGoal, 15000);
    return () => clearInterval(t);
  }, [founderId, loadGoal]);

  // Auto-sync agent-completed tasks → done set
  useEffect(() => {
    if (!goal || !selectedCats) return;
    const currentGoal = goal.goals?.find(g => g.id === goal.current_goal_id);
    if (!currentGoal) return;
    setDone(prev => {
      let changed = false;
      const next = new Set(prev);
      for (const cat of CHECKLIST_CATEGORIES.filter(c => selectedCats.includes(c.id))) {
        for (const item of cat.items) {
          if (prev.has(item.id) || !item.autoAgent) continue;
          const task = findTask(item.autoAgent, currentGoal.tasks);
          if (task?.status === "done") { next.add(item.id); changed = true; }
        }
      }
      if (changed) saveDone(next);
      return changed ? next : prev;
    });
  }, [goal, selectedCats]);

  const toggleItem = (itemId: string) => {
    setDone(prev => {
      const next = new Set(prev);
      next.has(itemId) ? next.delete(itemId) : next.add(itemId);
      saveDone(next);
      return next;
    });
  };

  const handleCatSave = (ids: string[]) => {
    saveCats(ids);
    setSelectedCats(ids);
    setEditingCats(false);
  };

  const paused = goal?.status === "paused";
  const runs = (goal?.operating_sessions ?? []).slice().reverse().slice(0, 6);
  const currentGoalTasks = goal?.goals?.find(g => g.id === goal.current_goal_id)?.tasks ?? [];

  const runNow = async () => {
    setBusy("run"); setActionErr(null);
    try {
      const r = await runCompanyCycle(founderId);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
      else await loadGoal();
    } catch (e) { setActionErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setActionErr(null), 8000); }
    finally { setBusy(null); }
  };

  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused"); await loadGoal(); }
    finally { setBusy(null); }
  };

  if (!mounted) return null;
  if (!selectedCats || editingCats) return <CategoryPicker initial={selectedCats ?? []} onSave={handleCatSave} />;

  // ── Derive item lists ──────────────────────────────────────────────────

  type ItemWithMeta = { item: CLItem; cat: CLCategory };

  const activeCats = CHECKLIST_CATEGORIES.filter(c => selectedCats.includes(c.id));
  const allSelected: ItemWithMeta[] = activeCats.flatMap(cat => cat.items.map(item => ({ item, cat })));

  // "Working on now": items whose agent has an in_progress or awaiting_approval task
  const activeSet = new Set<string>();
  const workingOn: Array<ItemWithMeta & { task: CompanyTask }> = [];
  for (const { item, cat } of allSelected) {
    if (done.has(item.id) || !item.autoAgent) continue;
    const task = findTask(item.autoAgent, currentGoalTasks);
    if (task && (task.status === "in_progress" || task.status === "awaiting_approval")) {
      // Only show first incomplete item per running agent (avoid duplicates per agent)
      if (!activeSet.has(item.autoAgent!)) {
        workingOn.push({ item, cat, task });
        activeSet.add(item.autoAgent!);
      }
    }
  }

  // "Up next": incomplete, not active, not done — flat mixed list
  const upNext: ItemWithMeta[] = allSelected
    .filter(({ item }) => !done.has(item.id) && !workingOn.find(w => w.item.id === item.id))
    .slice(0, 12);

  // "Done"
  const doneItems: ItemWithMeta[] = allSelected.filter(({ item }) => done.has(item.id));

  const totalItems = allSelected.length;
  const totalDone = doneItems.length;
  const pct = totalItems > 0 ? Math.round((totalDone / totalItems) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`
        @keyframes cl-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        @keyframes cl-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(0,46,255,0.5); } 50% { box-shadow: 0 0 0 5px rgba(0,46,255,0); } }
        .cl-enter { animation: cl-fade 0.22s cubic-bezier(0.22,1,0.36,1) both; }
        .run-row:hover { border-color: var(--bb) !important; background: var(--bdim) !important; }
        @media (prefers-reduced-motion: reduce) { .cl-enter { animation: none; } @keyframes cl-pulse {} }
      `}</style>

      {/* ── Blue hero ── */}
      <div style={{ position: "relative", overflow: "hidden", flexShrink: 0, background: "#001aff", minHeight: 140, borderBottom: "1px solid var(--bd)" }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2, padding: "22px 24px 18px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>Launch Checklist</div>
              {goal && (
                <span style={{ padding: "2px 9px", fontSize: 9, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", fontFamily: "var(--font-code)",
                  border: paused ? "1px solid rgba(255,180,50,0.5)" : "1px solid rgba(124,255,198,0.5)",
                  background: paused ? "rgba(255,180,50,0.14)" : "rgba(124,255,198,0.14)",
                  color: paused ? "#FFCB50" : "#7CFFC6" }}>
                  {paused ? "paused" : "operating"}
                </span>
              )}
              <button type="button" onClick={() => setEditingCats(true)} style={{
                fontSize: 10, padding: "2px 8px", background: "rgba(255,255,255,0.12)",
                border: "1px solid rgba(255,255,255,0.25)", color: "rgba(255,255,255,0.75)", cursor: "pointer" }}>
                Edit areas
              </button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ flex: 1, maxWidth: 300, height: 5, background: "rgba(255,255,255,0.2)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${pct}%`, background: pct === 100 ? "#7CFFC6" : "#fff", borderRadius: 3, transition: "width .5s" }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 600, color: pct === 100 ? "#7CFFC6" : "rgba(255,255,255,0.85)", fontFamily: "var(--font-code)" }}>
                {totalDone}/{totalItems}
              </span>
            </div>
          </div>
          {goal && (
            <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
              <button onClick={runNow} disabled={paused || !!busy}
                style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#002EFF", background: "#fff", border: "none", cursor: "pointer", opacity: (paused || !!busy) ? 0.5 : 1 }}>
                {busy === "run" ? "Starting…" : "▶ Run now"}
              </button>
              <button onClick={togglePause} disabled={!!busy}
                style={{ padding: "8px 14px", fontSize: 12, color: "rgba(255,255,255,0.88)", background: "rgba(255,255,255,0.13)", border: "1px solid rgba(255,255,255,0.28)", cursor: "pointer", opacity: !!busy ? 0.5 : 1 }}>
                {paused ? "Resume" : "Pause"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Scrollable ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px 48px", display: "flex", flexDirection: "column", gap: 24 }}>

        {actionErr && <div className="err-banner">{actionErr}</div>}

        {/* ── Working on now ── */}
        <div className="cl-enter">
          <div className="sec-label" style={{ marginBottom: 10 }}>Working on now</div>
          {workingOn.length === 0 ? (
            <div style={{ padding: "14px 16px", border: "1px dashed var(--bd2)", fontSize: 12, color: "var(--fm)", lineHeight: 1.55 }}>
              No agents running.{" "}
              {goal
                ? <button onClick={runNow} disabled={!!busy} style={{ color: "var(--blue)", background: "none", border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, padding: 0, textDecoration: "underline" }}>Start a run</button>
                : <a href="/" style={{ color: "var(--blue)" }}>Start a run</a>
              }{" "}
              to kick things off.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {workingOn.map(({ item, cat, task }) => (
                <ActiveItemCard key={item.id} item={item} cat={cat} task={task} />
              ))}
            </div>
          )}
        </div>

        {/* ── Up next ── */}
        {upNext.length > 0 && (
          <div className="cl-enter" style={{ animationDelay: "40ms" }}>
            <div className="sec-label" style={{ marginBottom: 10 }}>Up next</div>
            <div style={{ border: "1px solid var(--bd)", overflow: "hidden" }}>
              {upNext.map(({ item, cat }, i) => (
                <PendingRow
                  key={item.id}
                  item={item}
                  cat={cat}
                  onCheck={() => toggleItem(item.id)}
                />
              ))}
            </div>
          </div>
        )}

        {/* ── Done ── */}
        {doneItems.length > 0 && (
          <div className="cl-enter" style={{ animationDelay: "70ms" }}>
            <button type="button" onClick={() => setDoneOpen(p => !p)}
              style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", cursor: "pointer", padding: "0 0 10px" }}>
              <span className="sec-label" style={{ marginBottom: 0 }}>Done</span>
              <span style={{ fontSize: 11, color: "var(--green)", fontFamily: "var(--font-code)", fontWeight: 700 }}>{doneItems.length}</span>
              <span style={{ fontSize: 10, color: "var(--fm)", transform: doneOpen ? "rotate(180deg)" : "none", transition: "transform .15s", display: "inline-block" }}>▾</span>
            </button>
            {doneOpen && (
              <div style={{ border: "1px solid var(--bd)", overflow: "hidden" }}>
                {doneItems.map(({ item, cat }) => (
                  <DoneRow key={item.id} item={item} cat={cat} onUncheck={() => toggleItem(item.id)} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Agent runs ── */}
        {runs.length > 0 && (
          <div className="cl-enter" style={{ animationDelay: "100ms" }}>
            <button type="button" onClick={() => setRunsOpen(p => !p)}
              style={{ display: "flex", alignItems: "center", gap: 7, background: "none", border: "none", cursor: "pointer", padding: "0 0 8px" }}>
              <span className="sec-label" style={{ marginBottom: 0 }}>Agent runs</span>
              <span style={{ fontSize: 10, color: "var(--fm)", transform: runsOpen ? "rotate(180deg)" : "none", transition: "transform .15s", display: "inline-block" }}>▾</span>
            </button>
            {runsOpen && (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {runs.map(r => (
                  <a key={r.session_id} href={`/s/${r.session_id}`} className="run-row"
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid var(--bd)", background: "var(--surface)", textDecoration: "none", transition: "border-color .12s, background .12s" }}>
                    <div style={{ width: 7, height: 7, flexShrink: 0, borderRadius: "50%", background: r.status === "done" ? "var(--green)" : r.status === "error" ? "var(--red)" : "var(--blue)" }} />
                    <span style={{ flex: 1, fontSize: 12, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.summary || "Operating run"}</span>
                    <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>{timeAgo(r.started_at)}</span>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Util */}
        {goal && (
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={async () => {
              setBusy("notion");
              try { await syncMissionNotion(founderId); await loadGoal(); }
              catch (e) { setActionErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setActionErr(null), 8000); }
              finally { setBusy(null); }
            }} disabled={!!busy} className="btn" style={{ fontSize: 11 }}>
              {busy === "notion" ? "Syncing…" : "Sync Notion"}
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
