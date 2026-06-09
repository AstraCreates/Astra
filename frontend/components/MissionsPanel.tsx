"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "@/components/AstraGradient";
import { CHECKLIST_CATEGORIES } from "@/lib/checklist-data";
import {
  getCompanyGoal,
  runCompanyCycle,
  setCompanyGoalStatus,
  syncMissionNotion,
  type CompanyGoal,
} from "@/lib/api";

// ── localStorage persistence ───────────────────────────────────────────────

const CL_KEY = "astra_cl_done";

function loadDone(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(CL_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch { return new Set(); }
}

function saveDone(done: Set<string>) {
  try { localStorage.setItem(CL_KEY, JSON.stringify([...done])); } catch {}
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

// ── Checklist item row ─────────────────────────────────────────────────────

function CheckItem({
  id, label, detail, autoAgent, done, onToggle,
}: {
  id: string; label: string; detail?: string; autoAgent?: string;
  done: boolean; onToggle: () => void;
}) {
  return (
    <label style={{
      display: "flex", alignItems: "flex-start", gap: 12,
      padding: "9px 18px 9px 52px", cursor: "pointer",
      borderBottom: "1px solid var(--bd)",
      background: done ? "transparent" : "var(--surface)",
      transition: "background .1s",
    }}>
      <div style={{ marginTop: 2, flexShrink: 0, width: 16, height: 16, position: "relative" }}>
        <input
          type="checkbox"
          checked={done}
          onChange={onToggle}
          style={{ position: "absolute", opacity: 0, width: 0, height: 0 }}
        />
        <div style={{
          width: 16, height: 16,
          border: done ? "none" : "2px solid var(--bd2)",
          background: done ? "var(--green)" : "transparent",
          display: "flex", alignItems: "center", justifyContent: "center",
          transition: "background .1s, border .1s",
        }}>
          {done && <span style={{ fontSize: 10, color: "#fff", fontWeight: 700, lineHeight: 1 }}>✓</span>}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, fontWeight: 500,
          color: done ? "var(--fm)" : "var(--fg)",
          textDecoration: done ? "line-through" : "none",
          lineHeight: 1.4,
        }}>
          {label}
        </div>
        {detail && !done && (
          <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 3, lineHeight: 1.5 }}>
            {detail}
          </div>
        )}
      </div>
      {autoAgent && !done && (
        <div style={{
          flexShrink: 0, marginTop: 1,
          fontSize: 9, padding: "2px 6px",
          background: "var(--bdim)", border: "1px solid var(--bb)",
          color: "var(--blue)", fontWeight: 700,
          textTransform: "uppercase", letterSpacing: ".06em",
          fontFamily: "var(--font-code)", whiteSpace: "nowrap",
        }}>
          Agent
        </div>
      )}
    </label>
  );
}

// ── Category accordion row ─────────────────────────────────────────────────

function CategoryRow({
  id, label, icon, items, done, open, onToggle, onItemToggle,
}: {
  id: string; label: string; icon: string;
  items: { id: string; label: string; detail?: string; autoAgent?: string }[];
  done: Set<string>; open: boolean;
  onToggle: () => void;
  onItemToggle: (itemId: string) => void;
}) {
  const doneCount = items.filter(it => done.has(it.id)).length;
  const total = items.length;
  const allDone = doneCount === total;

  return (
    <div style={{ borderBottom: "1px solid var(--bd)" }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 12,
          padding: "12px 18px", background: "none", border: "none",
          cursor: "pointer", textAlign: "left",
          transition: "background .1s",
        }}
        className="cl-cat-row"
      >
        <span style={{ fontSize: 18, flexShrink: 0, width: 26, textAlign: "center" }}>{icon}</span>
        <span style={{
          flex: 1, fontSize: 13, fontWeight: 700,
          color: allDone ? "var(--fm)" : "var(--fg)",
          textDecoration: allDone ? "line-through" : "none",
        }}>
          {label}
        </span>
        <span style={{
          fontSize: 11, fontFamily: "var(--font-code)", fontWeight: 700,
          color: allDone ? "var(--green)" : doneCount > 0 ? "var(--blue)" : "var(--fm)",
          flexShrink: 0, marginRight: 8,
        }}>
          {doneCount}/{total}
        </span>
        {allDone ? (
          <span style={{ fontSize: 12, color: "var(--green)", flexShrink: 0 }}>✓</span>
        ) : (
          <span style={{
            fontSize: 10, color: "var(--fm)", flexShrink: 0,
            transform: open ? "rotate(180deg)" : "none",
            display: "inline-block", transition: "transform .15s",
          }}>▾</span>
        )}
      </button>

      {open && !allDone && (
        <div>
          {items.map((it, i) => (
            <CheckItem
              key={it.id}
              id={it.id}
              label={it.label}
              detail={it.detail}
              autoAgent={it.autoAgent}
              done={done.has(it.id)}
              onToggle={() => onItemToggle(it.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function MissionsPanel() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;

  const [goal, setGoal] = useState<CompanyGoal | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [runsOpen, setRunsOpen] = useState(false);

  const [done, setDone] = useState<Set<string>>(new Set());
  const [openCats, setOpenCats] = useState<Set<string>>(new Set());

  // Load done state from localStorage
  useEffect(() => {
    const d = loadDone();
    setDone(d);
    // Auto-open first category that has incomplete items
    const firstIncomplete = CHECKLIST_CATEGORIES.find(cat =>
      cat.items.some(it => !d.has(it.id))
    );
    if (firstIncomplete) setOpenCats(new Set([firstIncomplete.id]));
  }, []);

  const loadGoal = useCallback(async () => {
    if (!founderId) return;
    try { setGoal(await getCompanyGoal(founderId)); }
    catch { /* silent */ }
    finally { setLoading(false); }
  }, [founderId]);

  useEffect(() => {
    if (!founderId) { setLoading(false); return; }
    loadGoal();
    const t = setInterval(loadGoal, 20000);
    return () => clearInterval(t);
  }, [founderId, loadGoal]);

  const toggleItem = (itemId: string) => {
    setDone(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      saveDone(next);
      return next;
    });
  };

  const toggleCat = (catId: string) => {
    setOpenCats(prev => {
      const next = new Set(prev);
      if (next.has(catId)) next.delete(catId);
      else next.add(catId);
      return next;
    });
  };

  const paused = goal?.status === "paused";
  const runs = (goal?.operating_sessions ?? []).slice().reverse().slice(0, 6);

  // Overall progress
  const allItems = CHECKLIST_CATEGORIES.flatMap(c => c.items);
  const totalDone = allItems.filter(it => done.has(it.id)).length;
  const totalItems = allItems.length;
  const pct = totalItems > 0 ? Math.round((totalDone / totalItems) * 100) : 0;

  const runNow = async () => {
    setBusy("run");
    setActionErr(null);
    try {
      const r = await runCompanyCycle(founderId);
      if (r.parent_session_id) window.location.assign(`/s/${r.parent_session_id}`);
      else await loadGoal();
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : String(e));
      setTimeout(() => setActionErr(null), 8000);
    } finally { setBusy(null); }
  };

  const togglePause = async () => {
    setBusy("pause");
    try { await setCompanyGoalStatus(founderId, paused ? "operating" : "paused"); await loadGoal(); }
    finally { setBusy(null); }
  };

  if (!founderId) {
    return (
      <div className="empty" style={{ minHeight: 240 }}>
        <span style={{ fontSize: 22, fontFamily: "var(--font-code)", opacity: 0.25 }}>◎</span>
        <span className="empty-title">Sign in to track your launch progress.</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`
        @keyframes goals-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .gr-enter { animation: goals-fade 0.22s cubic-bezier(0.22,1,0.36,1) both; }
        .cl-cat-row:hover { background: rgba(0,0,0,0.025) !important; }
        .run-row:hover { border-color: var(--bb) !important; background: var(--bdim) !important; }
        [data-theme="dark"] .cl-cat-row:hover { background: rgba(255,255,255,0.03) !important; }
        @media (prefers-reduced-motion: reduce) { .gr-enter { animation: none; } }
      `}</style>

      {/* ── Blue hero ── */}
      <div style={{ position: "relative", overflow: "hidden", flexShrink: 0, background: "#001aff", minHeight: 148, borderBottom: "1px solid var(--bd)" }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2, padding: "24px 24px 20px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>Launch Checklist</div>
              {goal && (
                <span style={{
                  padding: "3px 10px", fontSize: 9, fontWeight: 700, letterSpacing: ".07em",
                  textTransform: "uppercase", fontFamily: "var(--font-code)",
                  border: paused ? "1px solid rgba(255,180,50,0.5)" : "1px solid rgba(124,255,198,0.5)",
                  background: paused ? "rgba(255,180,50,0.14)" : "rgba(124,255,198,0.14)",
                  color: paused ? "#FFCB50" : "#7CFFC6",
                }}>
                  {paused ? "paused" : "operating"}
                </span>
              )}
            </div>
            {/* Progress bar */}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ flex: 1, maxWidth: 340, height: 5, background: "rgba(255,255,255,0.2)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{
                  height: "100%", width: `${pct}%`,
                  background: pct === 100 ? "#7CFFC6" : "#fff",
                  borderRadius: 3, transition: "width .5s ease",
                }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 600, color: pct === 100 ? "#7CFFC6" : "rgba(255,255,255,0.85)", fontFamily: "var(--font-code)" }}>
                {totalDone}/{totalItems}
              </span>
              {pct === 100 && <span style={{ fontSize: 12, color: "#7CFFC6" }}>🎉 All done!</span>}
            </div>
          </div>
          {goal && (
            <div style={{ display: "flex", gap: 9, flexShrink: 0, alignItems: "flex-start" }}>
              <button onClick={runNow} disabled={paused || !!busy}
                style={{ padding: "9px 20px", fontSize: 12, fontWeight: 600, color: "#002EFF", background: "#fff", border: "none", cursor: "pointer", opacity: (paused || !!busy) ? 0.5 : 1 }}>
                {busy === "run" ? "Starting…" : "▶ Run now"}
              </button>
              <button onClick={togglePause} disabled={!!busy}
                style={{ padding: "9px 16px", fontSize: 12, fontWeight: 500, color: "rgba(255,255,255,0.88)", background: "rgba(255,255,255,0.13)", border: "1px solid rgba(255,255,255,0.28)", cursor: "pointer", opacity: !!busy ? 0.5 : 1 }}>
                {paused ? "Resume" : "Pause"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div style={{ flex: 1, overflowY: "auto" }}>

        {actionErr && (
          <div className="err-banner" style={{ margin: "14px 20px 0" }}>{actionErr}</div>
        )}

        {/* ── Checklist accordion ── */}
        <div className="gr-enter" style={{ borderBottom: "1px solid var(--bd)" }}>
          {CHECKLIST_CATEGORIES.map((cat) => (
            <CategoryRow
              key={cat.id}
              id={cat.id}
              label={cat.label}
              icon={cat.icon}
              items={cat.items}
              done={done}
              open={openCats.has(cat.id)}
              onToggle={() => toggleCat(cat.id)}
              onItemToggle={toggleItem}
            />
          ))}
        </div>

        {/* ── Agent activity (collapsible) ── */}
        <div style={{ padding: "16px 20px 48px", display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Agent runs */}
          {runs.length > 0 && (
            <div className="gr-enter">
              <button
                type="button"
                onClick={() => setRunsOpen(p => !p)}
                style={{ display: "flex", alignItems: "center", gap: 7, background: "none", border: "none", cursor: "pointer", padding: "0 0 8px 0" }}
              >
                <span className="sec-label" style={{ marginBottom: 0 }}>Agent runs</span>
                <span style={{
                  fontSize: 10, color: "var(--fm)",
                  transform: runsOpen ? "rotate(180deg)" : "none",
                  transition: "transform .15s", display: "inline-block",
                }}>▾</span>
              </button>
              {runsOpen && (
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {runs.map((r) => (
                    <a key={r.session_id} href={`/s/${r.session_id}`} className="run-row"
                      style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid var(--bd)", background: "var(--surface)", textDecoration: "none", transition: "border-color .12s, background .12s" }}>
                      <div style={{ width: 7, height: 7, flexShrink: 0, borderRadius: "50%", background: r.status === "done" ? "var(--green)" : r.status === "error" ? "var(--red)" : "var(--blue)" }} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {r.summary || "Operating run"}
                      </span>
                      <span style={{ fontSize: 10, color: "var(--fm)", whiteSpace: "nowrap", fontFamily: "var(--font-code)" }}>{timeAgo(r.started_at)}</span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Utility actions */}
          {goal && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button onClick={async () => {
                setBusy("notion");
                try { await syncMissionNotion(founderId); await loadGoal(); }
                catch (e) { setActionErr(e instanceof Error ? e.message : String(e)); setTimeout(() => setActionErr(null), 8000); }
                finally { setBusy(null); }
              }} disabled={!!busy} className="btn" style={{ fontSize: 11 }}>
                {busy === "notion" ? "Syncing…" : "Sync Notion"}
              </button>
              {done.size > 0 && (
                <button onClick={() => {
                  if (confirm("Clear all checked items?")) {
                    const empty = new Set<string>();
                    saveDone(empty);
                    setDone(empty);
                  }
                }} className="btn" style={{ fontSize: 11, color: "var(--fm)" }}>
                  Reset checklist
                </button>
              )}
            </div>
          )}

          {!goal && !loading && (
            <div style={{ padding: "48px 20px", textAlign: "center", border: "1px dashed var(--bd2)", marginTop: 8 }}>
              <div style={{ fontSize: 28, marginBottom: 14, fontFamily: "var(--font-code)", color: "var(--fm)", opacity: 0.25 }}>◎</div>
              <div className="empty-title" style={{ marginBottom: 8 }}>No agent run started yet</div>
              <p style={{ fontSize: 12, color: "var(--fm)", maxWidth: 320, margin: "0 auto 20px", lineHeight: 1.65 }}>
                Start a run from the home screen — Astra auto-completes tasks as agents work.
              </p>
              <a href="/" className="btn pri" style={{ textDecoration: "none", display: "inline-block" }}>Start a run →</a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
