"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { listSessions, deleteSessionRemote, killSession, getSessionDigest, AGENT_LABELS, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "./AstraGradient";
import GoalPanel from "./GoalPanel";

const GREETINGS = [
  "Welcome back",
  "Let's get to work",
  "Ready to build",
  "Good to see you",
  "Let's keep building",
];

function extractGoalTitle(raw: string): string {
  return raw
    .replace(/^FOLLOW-UP RUN for GOAL:\s*/i, "")
    .replace(/^GOAL:\s*/i, "")
    .replace(/\s*An earlier run already completed[\s\S]*$/i, "")
    .replace(/\s*Work together to complete these major tasks[\s\S]*$/i, "")
    .replace(/\s*Each agent: deliver[\s\S]*$/i, "")
    .replace(/\s*Finish ONLY the \d+[\s\S]*$/i, "")
    .trim() || raw;
}

function ago(ts: string | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now"; if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function StatusPill({ status }: { status: string }) {
  if (status === "running") return <span className="pill blue">● Running</span>;
  if (status === "done") return <span className="pill green">✓ Done</span>;
  if (status === "error") return <span className="pill red">✗ Error</span>;
  if (status === "killed") return <span className="pill red">✗ Stopped</span>;
  if (status === "stalled") return <span className="pill amber">⚠ Needs attention</span>;
  return <span className="pill">{status}</span>;
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [pendingDel, setPendingDel] = useState<Set<string>>(new Set());
  const [toastErr, setToastErr] = useState("");
  const showErr = (msg: string) => { setToastErr(msg); setTimeout(() => setToastErr(""), 6000); };
  const [firstName, setFirstName] = useState("");
  const [greeting, setGreeting] = useState("");
  const [digests, setDigests] = useState<Map<string, SessionDigest>>(new Map());
  const [showCompleted, setShowCompleted] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") {
      const fullName = localStorage.getItem("astra_onboarding_name") || "";
      setFirstName(fullName.split(" ")[0] || fullName);
    }
    setGreeting(GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
  }, []);

  const del = useCallback(async (e: React.MouseEvent, s: SessionIndexEntry) => {
    e.stopPropagation();
    e.preventDefault();
    if (!pendingDel.has(s.session_id)) {
      setPendingDel((p) => new Set(p).add(s.session_id));
      setTimeout(() => setPendingDel((p) => { const n = new Set(p); n.delete(s.session_id); return n; }), 3000);
      return;
    }
    setPendingDel((p) => { const n = new Set(p); n.delete(s.session_id); return n; });
    setDeleting((p) => new Set(p).add(s.session_id));
    // Optimistically drop from the UI immediately so it feels instant.
    deleteLocalSession(s.session_id);
    setSessions((prev) => (prev || []).filter((x) => x.session_id !== s.session_id));
    try {
      // Kill first — a live run would otherwise keep re-persisting itself to the
      // index and reappear on the next refresh.
      await killSession(s.session_id).catch(() => {});
      const ok = await deleteSessionRemote(s.session_id);
      if (!ok) { showErr("Could not delete this run on the server — it may reappear on refresh."); }
    } finally {
      setDeleting((p) => { const n = new Set(p); n.delete(s.session_id); return n; });
    }
  }, [pendingDel]);

  const load = useCallback(async () => {
    if (!userId) return;
    setError(""); setSessions(null);
    try { setSessions(await listSessions(userId, 50)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setSessions([]); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!sessions) return;
    const running = sessions.filter(s => s.status === "running");
    if (!running.length) return;
    const fetchAll = async () => {
      const results = await Promise.allSettled(
        running.map(s => getSessionDigest(s.session_id).then(d => [s.session_id, d] as [string, SessionDigest]))
      );
      setDigests(prev => {
        const next = new Map(prev);
        for (const r of results) {
          if (r.status === "fulfilled") next.set(r.value[0], r.value[1]);
        }
        return next;
      });
    };
    void fetchAll();
    const t = setInterval(fetchAll, 15_000);
    return () => clearInterval(t);
  }, [sessions]);

  const running = (sessions || []).filter((s) => s.status === "running").length;
  const stalled = (sessions || []).filter((s) => s.status === "stalled").length;

  const headline = greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "";

  return (
    <>
      <style>{`
        @keyframes dv-fade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes sc-shimmer { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
        @keyframes sc-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        .greeting-text { transition: opacity 0.3s ease; }
        .sc-row { cursor: pointer; padding: 14px 16px; border: 1px solid var(--bd); background: var(--surface); display: flex; align-items: flex-start; gap: 14; transition: border-color .15s, box-shadow .15s; position: relative; overflow: hidden; border-radius: 8px; }
        .sc-row::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--bd); transition: background .15s; border-radius: 8px 8px 0 0; }
        .sc-row:hover { border-color: var(--bb) !important; box-shadow: 0 4px 16px rgba(0,46,255,.07); }
        .sc-row:hover::before { background: linear-gradient(90deg, var(--blue), var(--mint)); }
        .sc-row.stalled { border-color: var(--ab) !important; background: var(--adim) !important; }
        .sc-row.stalled::before { background: var(--amber); }
        .sc-row.running { border-color: var(--bb) !important; }
        .sc-row.running::before { background: linear-gradient(90deg, var(--blue), var(--mint)); animation: sc-shimmer 2s ease-in-out infinite; }
        .sc-child { margin-left: 20px; border-left: 3px solid var(--bb) !important; border-radius: 0 8px 8px 0 !important; }
        .sc-child::before { border-radius: 0 8px 0 0 !important; }
        .sc-progress-track { height: 5px; background: var(--bd); border-radius: 3px; overflow: hidden; margin-top: 8px; }
        .sc-progress-fill { height: 100%; border-radius: 3px; transition: width 0.8s ease; }
        .sc-progress-indeterminate { height: 100%; width: 35%; border-radius: 3px; animation: sc-indeterminate 1.4s ease-in-out infinite; }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Header hero */}
        <div className="dv-hero" style={{ padding: "28px 24px 24px", borderBottom: "1px solid var(--bd)", position: "relative", overflow: "hidden", background: "var(--blue)", minHeight: 140 }}>
          <AstraGradient />
          {/* Scrim so text stays readable over the animated gradient */}
          <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.18)", pointerEvents: "none", zIndex: 1 }} />

          <div style={{ position: "relative", zIndex: 2 }}>
            <div className="greeting-text" style={{
              fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
              fontSize: 26, fontWeight: 700,
              letterSpacing: "-0.02em",
              color: "#fff", marginBottom: 4,
            }}>
              {headline}
            </div>

            {/* Stats row */}
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
              {sessions !== null && (
                <>
                  <span style={{ fontSize: 11, color: "rgba(255,255,255,0.85)" }}>
                    {sessions.length} run{sessions.length !== 1 ? "s" : ""}
                  </span>
                  {running > 0 && (
                    <span style={{ fontSize: 11, color: "#7cffe6", fontWeight: 600 }}>
                      ● {running} running
                    </span>
                  )}
                  {stalled > 0 && (
                    <span style={{ fontSize: 11, color: "rgba(255,210,80,1)", fontWeight: 600 }}>
                      ⚠ {stalled} need{stalled === 1 ? "s" : ""} attention
                    </span>
                  )}
                </>
              )}
            </div>

            <div style={{ display: "flex", gap: 9 }}>
              <button
                data-tour="dash-new-run"
                onClick={() => router.push("/?new=1")}
                style={{ padding: "9px 20px", fontSize: 12, fontWeight: 600, color: "#002EFF", background: "#fff", border: "none", cursor: "pointer", letterSpacing: "0.01em", borderRadius: 8, fontFamily: "var(--font-instrument), sans-serif" }}
              >+ New run</button>
              <button
                onClick={load}
                style={{ padding: "9px 16px", fontSize: 12, fontWeight: 500, color: "rgba(255,255,255,0.85)", background: "rgba(255,255,255,0.12)", border: "1px solid rgba(255,255,255,0.25)", cursor: "pointer", borderRadius: 8, fontFamily: "var(--font-instrument), sans-serif" }}
              >Refresh</button>
            </div>
          </div>
        </div>

        {toastErr && (
          <div style={{ background: "var(--rdim)", borderBottom: "1px solid var(--rb)", padding: "7px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "var(--red)", fontFamily: "var(--font-code)", animation: "astraSlideDown 0.22s var(--ease-out-quint, cubic-bezier(0.22,1,0.36,1)) both" }}>
            <span>✗</span>
            <span style={{ flex: 1 }}>{toastErr}</span>
            <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1 }}>✕</button>
          </div>
        )}
        <div style={{ padding: "20px 24px 40px", display: "flex", gap: 24, alignItems: "flex-start" }}>

          {/* ── Left: Goal panel ── */}
          <div style={{ width: 340, flexShrink: 0 }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--fd)", fontFamily: "var(--font-code)", marginBottom: 12 }}>
              Goals
            </div>
            <GoalPanel />
          </div>

          {/* ── Right: Sessions ── */}
          <div style={{ flex: 1, minWidth: 0 }}>
          {/* Attention banner */}
          {stalled > 0 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 14px",
              border: "1px solid rgba(245,158,11,0.35)",
              background: "rgba(245,158,11,0.07)",
              marginBottom: 18, fontSize: 12, color: "rgba(245,158,11,0.95)",
            }}>
              <span style={{ fontSize: 15 }}>⚠</span>
              <span>
                {stalled} session{stalled > 1 ? "s need" : " needs"} your attention — approval may be required.
                <button
                  style={{ marginLeft: 8, background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: 600, textDecoration: "underline", padding: 0, fontSize: 12 }}
                  onClick={() => {
                    const first = (sessions || []).find((s) => s.status === "stalled");
                    if (first) router.push(`/s/${first.session_id}`);
                  }}
                >
                  Review →
                </button>
              </span>
            </div>
          )}

          {sessions === null ? (
            <div style={{ color: "var(--fm)", fontSize: 11, padding: "12px 0" }}>Loading sessions…</div>
          ) : error ? (
            <div className="empty">
              <div style={{ fontSize: 34, opacity: .12 }}>⚙</div>
              <div className="empty-title">Backend not reachable</div>
              <div className="empty-sub" style={{ fontSize: 10.5, maxWidth: 280, lineHeight: 1.6 }}>{error}</div>
              <button className="btn pri" style={{ marginTop: 12 }} onClick={load}>Try again</button>
            </div>
          ) : !sessions.length ? (
            <div className="empty">
              <div style={{ fontSize: 34, opacity: .12 }}>◈</div>
              <div className="empty-title">No runs yet</div>
              <div className="empty-sub" style={{ fontSize: 10.5, maxWidth: 280, lineHeight: 1.6 }}>
                Start your first run and Astra will get to work.
              </div>
              <button className="btn pri" style={{ marginTop: 12 }} onClick={() => router.push("/?new=1")}>
                Start first run →
              </button>
            </div>
          ) : (
            <div data-tour="dash-sessions" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {(() => {
                const ids = new Set(sessions.map((x) => x.session_id));
                const kids: Record<string, SessionIndexEntry[]> = {};
                const roots: SessionIndexEntry[] = [];
                for (const s of sessions) {
                  const p = s.parent_session_id;
                  if (p && ids.has(p)) (kids[p] ||= []).push(s);
                  else roots.push(s);
                }

                const activeRoots = roots.filter(r => r.status !== "done");
                const completedRoots = roots.filter(r => r.status === "done");

                const toOrdered = (rootList: SessionIndexEntry[]) => {
                  const result: { s: SessionIndexEntry; child: boolean }[] = [];
                  for (const r of rootList) {
                    result.push({ s: r, child: false });
                    for (const k of kids[r.session_id] || []) result.push({ s: k, child: true });
                  }
                  return result;
                };

                const activeItems = toOrdered(activeRoots);
                const completedItems = toOrdered(completedRoots);

                const renderCard = ({ s, child }: { s: SessionIndexEntry; child: boolean }, idx: number) => {
                  const isStalled = s.status === "stalled";
                  const isRunning = s.status === "running";
                  const isDone = s.status === "done";
                  const digest = digests.get(s.session_id);
                  const totalAgents = digest?.counts.planned_agents ?? 0;
                  const doneAgents = digest?.counts.done_agents ?? 0;
                  const progressPct = isDone ? 100
                    : (isRunning && totalAgents > 0) ? Math.round((doneAgents / totalAgents) * 100)
                    : null;
                  const currentAgents = (digest?.running_agents ?? [])
                    .map(a => AGENT_LABELS[a as keyof typeof AGENT_LABELS] ?? a);
                  const cleanTitle = extractGoalTitle(s.goal || "Untitled run");
                  return (
                    <div
                      key={s.session_id}
                      className={`sc-row${isStalled ? " stalled" : isRunning ? " running" : ""}${child ? " sc-child" : ""}`}
                      onClick={() => router.push(`/s/${s.session_id}`)}
                      style={{ position: "relative", '--i': idx } as CSSProperties}
                    >
                      <button
                        title={pendingDel.has(s.session_id) ? "Click again to confirm delete" : "Delete run"}
                        aria-label={pendingDel.has(s.session_id) ? "Confirm delete" : "Delete run"}
                        disabled={deleting.has(s.session_id)}
                        onClick={(e) => del(e, s)}
                        onPointerDown={(e) => e.stopPropagation()}
                        onTouchStart={(e) => e.stopPropagation()}
                        style={{
                          position: "absolute", top: 8, right: 8,
                          width: pendingDel.has(s.session_id) ? "auto" : 28, height: 28,
                          padding: pendingDel.has(s.session_id) ? "0 8px" : 0,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          background: pendingDel.has(s.session_id) ? "var(--rdim)" : "transparent",
                          border: pendingDel.has(s.session_id) ? "1px solid var(--rb)" : "1px solid transparent",
                          color: pendingDel.has(s.session_id) ? "var(--red)" : "var(--fd)",
                          cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 9 : 12, borderRadius: 6,
                          opacity: deleting.has(s.session_id) ? 0.4 : 1,
                          transition: "opacity .15s, background .15s, border-color .15s, color .15s",
                          touchAction: "manipulation", WebkitTapHighlightColor: "transparent",
                          zIndex: 3, fontWeight: 700, letterSpacing: "0.04em", whiteSpace: "nowrap",
                        }}
                      >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DELETE?" : "✕"}</button>

                      <div style={{ flex: 1, paddingRight: 36 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                          {child && (
                            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", color: "var(--blue)", fontFamily: "var(--font-code)" }}>↳ sub-run</span>
                          )}
                          {s.stack_id && (
                            <span style={{ fontSize: 9, color: "var(--fm)", fontFamily: "var(--font-code)", padding: "2px 7px", background: "var(--s2, #f5f5f5)", border: "1px solid var(--bd)", borderRadius: 4 }}>
                              {s.stack_id}
                            </span>
                          )}
                          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                            <StatusPill status={s.status} />
                            <span style={{ fontSize: 10, color: "var(--fm)" }}>{ago(s.created_at)}</span>
                          </div>
                        </div>

                        <div style={{
                          fontSize: 13, fontWeight: 600, color: "var(--fg)",
                          lineHeight: 1.45, marginBottom: 10,
                          display: "-webkit-box", WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical", overflow: "hidden",
                        }}>
                          {cleanTitle}
                        </div>

                        {(isRunning || isDone) && (
                          <div>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                              <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)" }}>
                                {isDone ? "All agents done" : totalAgents > 0 ? `${doneAgents} / ${totalAgents} agents` : "Loading…"}
                              </span>
                              {progressPct !== null && (
                                <span style={{ fontSize: 10, color: isDone ? "var(--green)" : "var(--blue)", fontFamily: "var(--font-code)", fontWeight: 600 }}>
                                  {progressPct}%
                                </span>
                              )}
                            </div>
                            <div className="sc-progress-track">
                              {progressPct !== null ? (
                                <div className="sc-progress-fill" style={{ width: `${progressPct}%`, background: isDone ? "var(--green)" : "var(--blue)" }} />
                              ) : (
                                <div className="sc-progress-indeterminate" style={{ background: "var(--blue)" }} />
                              )}
                            </div>
                          </div>
                        )}

                        {isRunning && currentAgents.length > 0 && (
                          <div style={{ fontSize: 10, color: "var(--blue)", fontFamily: "var(--font-code)", marginTop: 7, display: "flex", alignItems: "center", gap: 5 }}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)", flexShrink: 0, animation: "sc-shimmer 1.5s ease-in-out infinite" }} />
                            {currentAgents.join(" · ")}
                          </div>
                        )}
                        {isRunning && currentAgents.length === 0 && totalAgents === 0 && (
                          <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)", marginTop: 7 }}>
                            Initializing agents…
                          </div>
                        )}
                      </div>
                    </div>
                  );
                };

                const completedRunCount = completedRoots.length;
                return (
                  <>
                    {activeItems.length === 0 && completedItems.length > 0 && (
                      <div style={{ fontSize: 12, color: "var(--fm)", padding: "4px 0 8px" }}>
                        No active runs. {completedRunCount} completed below.
                      </div>
                    )}
                    {activeItems.map((item, idx) => renderCard(item, idx))}

                    {completedRunCount > 0 && (
                      <div style={{ marginTop: activeItems.length ? 8 : 0 }}>
                        <button
                          onClick={() => setShowCompleted(v => !v)}
                          style={{
                            display: "flex", alignItems: "center", gap: 8, width: "100%",
                            padding: "10px 14px", background: "var(--surface)",
                            border: "1px solid var(--bd)", borderRadius: 8,
                            cursor: "pointer", textAlign: "left",
                            transition: "border-color .15s",
                          }}
                          onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--bb)")}
                          onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--bd)")}
                        >
                          <span style={{ fontSize: 10, color: "var(--fm)", transform: showCompleted ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block", transition: "transform .2s" }}>▶</span>
                          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>Completed runs</span>
                          <span style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)", marginLeft: 4 }}>{completedRunCount}</span>
                          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--fm)" }}>{showCompleted ? "Hide" : "Show"}</span>
                        </button>
                        {showCompleted && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                            {completedItems.map((item, idx) => renderCard(item, idx))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}
          </div>{/* end sessions col */}
        </div>
      </div>
    </>
  );
}
