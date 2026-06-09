"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "@/components/AstraGradient";
import { CHECKLIST_CATEGORIES } from "@/lib/checklist-data";
import {
  getCompanyGoal, runCompanyCycle, setCompanyGoalStatus, syncMissionNotion,
  type CompanyGoal,
} from "@/lib/api";

// ── Storage ────────────────────────────────────────────────────────────────

const KEY_DONE = "astra_cl_done";
const KEY_CATS = "astra_cl_cats";       // string[] — selected cat ids; null = not set yet
const KEY_ACTIVE = "astra_cl_active";  // string — current active cat id

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

function loadActive(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem(KEY_ACTIVE); }
  catch { return null; }
}
function saveActive(id: string) { try { localStorage.setItem(KEY_ACTIVE, id); } catch {} }

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

  const toggle = (id: string) => setSel(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 100,
      background: "var(--bg, #fff)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{ position: "relative", overflow: "hidden", background: "#001aff", padding: "28px 28px 24px", flexShrink: 0 }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#fff", marginBottom: 6, letterSpacing: "-0.02em" }}>
            Build your launch plan
          </div>
          <div style={{ fontSize: 13, color: "rgba(255,255,255,0.75)", maxWidth: 480, lineHeight: 1.5 }}>
            Pick the areas relevant to your startup. You can change this anytime.
          </div>
        </div>
      </div>

      {/* Grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
          {CHECKLIST_CATEGORIES.map(cat => {
            const on = sel.has(cat.id);
            return (
              <button key={cat.id} type="button" onClick={() => toggle(cat.id)} style={{
                display: "flex", flexDirection: "column", gap: 6,
                padding: "14px 16px", textAlign: "left",
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

      {/* Footer */}
      <div style={{ padding: "16px 28px", borderTop: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <button
          type="button"
          disabled={sel.size === 0}
          onClick={() => onSave([...sel])}
          className="btn pri"
          style={{ opacity: sel.size === 0 ? 0.5 : 1 }}
        >
          Build checklist →
        </button>
        <span style={{ fontSize: 12, color: "var(--fm)" }}>
          {sel.size === 0 ? "Select at least one" : `${sel.size} area${sel.size > 1 ? "s" : ""} selected`}
        </span>
      </div>
    </div>
  );
}

// ── Check Item ─────────────────────────────────────────────────────────────

function CheckItem({ id, label, detail, autoAgent, done, onToggle }: {
  id: string; label: string; detail?: string; autoAgent?: string;
  done: boolean; onToggle: () => void;
}) {
  return (
    <label style={{
      display: "flex", alignItems: "flex-start", gap: 11,
      padding: "10px 16px", cursor: "pointer",
      borderBottom: "1px solid var(--bd)",
      opacity: done ? 0.55 : 1, transition: "opacity .15s",
    }}>
      <input type="checkbox" checked={done} onChange={onToggle}
        style={{ position: "absolute", opacity: 0, width: 0, height: 0 }} />
      <div style={{ marginTop: 2, flexShrink: 0, width: 16, height: 16,
        border: done ? "none" : "2px solid var(--bd2)",
        background: done ? "var(--green)" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all .1s",
      }}>
        {done && <span style={{ fontSize: 9, color: "#fff", fontWeight: 700 }}>✓</span>}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: done ? "var(--fm)" : "var(--fg)",
          textDecoration: done ? "line-through" : "none", lineHeight: 1.4 }}>
          {label}
        </div>
        {detail && !done && (
          <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 3, lineHeight: 1.5 }}>{detail}</div>
        )}
      </div>
      {autoAgent && !done && (
        <span style={{ flexShrink: 0, marginTop: 2, fontSize: 9, padding: "2px 6px",
          background: "var(--bdim)", border: "1px solid var(--bb)", color: "var(--blue)",
          fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em",
          fontFamily: "var(--font-code)", whiteSpace: "nowrap" }}>
          Agent
        </span>
      )}
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

  const [done, setDone] = useState<Set<string>>(new Set());
  const [selectedCats, setSelectedCats] = useState<string[] | null>(null); // null = not loaded yet
  const [activeCatId, setActiveCatId] = useState<string | null>(null);
  const [editingCats, setEditingCats] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    setDone(loadDone());
    const cats = loadCats();
    setSelectedCats(cats);
    if (cats) {
      const savedActive = loadActive();
      // If saved active is in selected cats, use it; else pick first incomplete
      if (savedActive && cats.includes(savedActive)) {
        setActiveCatId(savedActive);
      } else {
        const first = cats.find(id => {
          const cat = CHECKLIST_CATEGORIES.find(c => c.id === id);
          return cat && cat.items.some(it => !loadDone().has(it.id));
        }) ?? cats[0] ?? null;
        setActiveCatId(first);
      }
    }
    setMounted(true);
  }, []);

  const loadGoal = useCallback(async () => {
    if (!founderId) return;
    try { setGoal(await getCompanyGoal(founderId)); } catch {}
  }, [founderId]);

  useEffect(() => {
    if (!founderId) return;
    loadGoal();
    const t = setInterval(loadGoal, 20000);
    return () => clearInterval(t);
  }, [founderId, loadGoal]);

  const toggleItem = (itemId: string) => {
    setDone(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId); else next.add(itemId);
      saveDone(next);
      return next;
    });
  };

  const handleCatSave = (ids: string[]) => {
    saveCats(ids);
    setSelectedCats(ids);
    setEditingCats(false);
    const d = loadDone();
    const first = ids.find(id => {
      const cat = CHECKLIST_CATEGORIES.find(c => c.id === id);
      return cat && cat.items.some(it => !d.has(it.id));
    }) ?? ids[0] ?? null;
    setActiveCatId(first);
    if (first) saveActive(first);
  };

  const selectActive = (id: string) => {
    setActiveCatId(id);
    saveActive(id);
  };

  const paused = goal?.status === "paused";
  const runs = (goal?.operating_sessions ?? []).slice().reverse().slice(0, 6);

  const runNow = async () => {
    setBusy("run");
    setActionErr(null);
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

  // Wait for mount (avoid hydration mismatch)
  if (!mounted) return null;

  // First visit — show category picker
  if (!selectedCats || editingCats) {
    return <CategoryPicker initial={selectedCats ?? []} onSave={handleCatSave} />;
  }

  // Derive sections
  const activeCats = CHECKLIST_CATEGORIES.filter(c => selectedCats.includes(c.id));
  const catDoneMap = Object.fromEntries(
    activeCats.map(c => [c.id, c.items.every(it => done.has(it.id))])
  );
  const incompleteCats = activeCats.filter(c => !catDoneMap[c.id]);
  const doneCats = activeCats.filter(c => catDoneMap[c.id]);

  const activeCat = activeCats.find(c => c.id === activeCatId) ?? incompleteCats[0] ?? activeCats[0];
  const upNextCats = incompleteCats.filter(c => c.id !== activeCat?.id).slice(0, 4);

  const totalItems = activeCats.flatMap(c => c.items).length;
  const totalDone = activeCats.flatMap(c => c.items).filter(it => done.has(it.id)).length;
  const pct = totalItems > 0 ? Math.round((totalDone / totalItems) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`
        @keyframes cl-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        .cl-enter { animation: cl-fade 0.22s cubic-bezier(0.22,1,0.36,1) both; }
        .cl-upnext:hover { border-color: var(--bb) !important; background: var(--bdim) !important; cursor: pointer; }
        .run-row:hover { border-color: var(--bb) !important; background: var(--bdim) !important; }
        @media (prefers-reduced-motion: reduce) { .cl-enter { animation: none; } }
      `}</style>

      {/* ── Blue hero ── */}
      <div style={{ position: "relative", overflow: "hidden", flexShrink: 0, background: "#001aff", minHeight: 140, borderBottom: "1px solid var(--bd)" }}>
        <AstraGradient />
        <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.20)", pointerEvents: "none", zIndex: 1 }} />
        <div style={{ position: "relative", zIndex: 2, padding: "22px 24px 18px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em" }}>Launch Checklist</div>
              {goal && (
                <span style={{
                  padding: "2px 9px", fontSize: 9, fontWeight: 700, letterSpacing: ".07em",
                  textTransform: "uppercase", fontFamily: "var(--font-code)",
                  border: paused ? "1px solid rgba(255,180,50,0.5)" : "1px solid rgba(124,255,198,0.5)",
                  background: paused ? "rgba(255,180,50,0.14)" : "rgba(124,255,198,0.14)",
                  color: paused ? "#FFCB50" : "#7CFFC6",
                }}>{paused ? "paused" : "operating"}</span>
              )}
              <button type="button" onClick={() => setEditingCats(true)} style={{
                fontSize: 10, padding: "2px 8px", background: "rgba(255,255,255,0.12)",
                border: "1px solid rgba(255,255,255,0.25)", color: "rgba(255,255,255,0.75)",
                cursor: "pointer", fontFamily: "var(--font-code)",
              }}>Edit areas</button>
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

        {/* ── Now ── */}
        {activeCat && (
          <div className="cl-enter">
            <div className="sec-label" style={{ marginBottom: 10 }}>Working on now</div>
            <div style={{ border: "1px solid var(--bb)", background: "var(--bdim)", overflow: "hidden" }}>
              {/* Category header */}
              <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 20 }}>{activeCat.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "var(--fg)" }}>{activeCat.label}</div>
                  <div style={{ fontSize: 11, color: "var(--fm)", fontFamily: "var(--font-code)", marginTop: 1 }}>
                    {activeCat.items.filter(it => done.has(it.id)).length}/{activeCat.items.length} done
                  </div>
                </div>
                {/* Mini progress */}
                <div style={{ width: 80, height: 3, background: "var(--bd)", overflow: "hidden" }}>
                  <div style={{ height: "100%", background: "var(--blue)", transition: "width .4s",
                    width: `${Math.round(activeCat.items.filter(it => done.has(it.id)).length / activeCat.items.length * 100)}%` }} />
                </div>
              </div>
              {/* Items */}
              {activeCat.items.map((it, i) => (
                <CheckItem key={it.id} id={it.id} label={it.label} detail={it.detail}
                  autoAgent={it.autoAgent} done={done.has(it.id)}
                  onToggle={() => toggleItem(it.id)} />
              ))}
            </div>
          </div>
        )}

        {/* ── Up next ── */}
        {upNextCats.length > 0 && (
          <div className="cl-enter" style={{ animationDelay: "40ms" }}>
            <div className="sec-label" style={{ marginBottom: 10 }}>Up next</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8 }}>
              {upNextCats.map(cat => {
                const catDone = cat.items.filter(it => done.has(it.id)).length;
                return (
                  <button key={cat.id} type="button" onClick={() => selectActive(cat.id)}
                    className="cl-upnext"
                    style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 14px",
                      border: "1px solid var(--bd)", background: "var(--surface)",
                      textAlign: "left", transition: "border-color .1s, background .1s" }}>
                    <span style={{ fontSize: 18 }}>{cat.icon}</span>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--fg)", lineHeight: 1.3 }}>{cat.label}</div>
                    <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>
                      {catDone > 0 ? <span style={{ color: "var(--blue)" }}>{catDone}/</span> : "0/"}
                      {cat.items.length} done
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Done ── */}
        {doneCats.length > 0 && (
          <div className="cl-enter" style={{ animationDelay: "80ms" }}>
            <div className="sec-label" style={{ marginBottom: 10 }}>Done</div>
            <div style={{ border: "1px solid var(--bd)", background: "var(--surface)" }}>
              {doneCats.map((cat, i) => (
                <div key={cat.id} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                  borderBottom: i < doneCats.length - 1 ? "1px solid var(--bd)" : "none",
                  opacity: 0.7,
                }}>
                  <span style={{ fontSize: 16 }}>{cat.icon}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--fm)", textDecoration: "line-through" }}>{cat.label}</span>
                  <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "var(--font-code)", fontWeight: 700 }}>✓ {cat.items.length}/{cat.items.length}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Agent runs (collapsible) ── */}
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
