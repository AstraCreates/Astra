"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { listSessions, deleteSessionRemote, killSession, type SessionIndexEntry } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import AstraGradient from "./AstraGradient";

const GREETINGS = [
  "Welcome back",
  "Let's get to work",
  "Ready to build",
  "Good to see you",
  "Let's keep building",
];

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
  const [company, setCompany] = useState("");
  const [firstName, setFirstName] = useState("");
  const [greeting, setGreeting] = useState("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setCompany(localStorage.getItem("astra_onboarding_company") || "");
      const fullName = localStorage.getItem("astra_onboarding_name") || "";
      setFirstName(fullName.split(" ")[0] || fullName);
    }
    // Pick one greeting randomly for this session — never changes until next load
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
    try { setSessions(await listSessions(userId)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setSessions([]); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const running = (sessions || []).filter((s) => s.status === "running").length;
  const stalled = (sessions || []).filter((s) => s.status === "stalled").length;

  const headlineName = firstName || (company ? `the ${company} team` : null);
  const headline = greeting && headlineName ? `${greeting}, ${headlineName}.` : greeting ? `${greeting}.` : "";

  return (
    <>
      <style>{`
        @keyframes dv-fade { from { opacity: 0; } to { opacity: 1; } }
        .greeting-text { transition: opacity 0.3s ease; }
        .sc-row { cursor: pointer; padding: 14px 16px; border: 1px solid var(--bd); background: var(--surface); display: flex; align-items: flex-start; gap: 14; transition: border-color .15s, box-shadow .15s; position: relative; overflow: hidden; }
        .sc-row::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--bd); transition: background .15s; }
        .sc-row:hover { border-color: var(--bb) !important; box-shadow: 0 4px 16px rgba(0,46,255,.07); }
        .sc-row:hover::before { background: linear-gradient(90deg, var(--blue), var(--mint)); }
        .sc-row.stalled { border-color: var(--ab) !important; background: var(--adim) !important; }
        .sc-row.stalled::before { background: var(--amber); }
        .sc-row.running { border-color: var(--bb) !important; }
        .sc-row.running::before { background: linear-gradient(90deg, var(--blue), var(--mint)); animation: sc-shimmer 2s ease-in-out infinite; }
        @keyframes sc-shimmer { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Header hero */}
        <div className="dv-hero" style={{ padding: "28px 24px 24px", borderBottom: "1px solid var(--bd)", position: "relative", overflow: "hidden", background: "#001aff", minHeight: 140 }}>
          <AstraGradient />
          {/* Scrim so text stays readable over the animated gradient */}
          <div style={{ position: "absolute", inset: 0, background: "rgba(0,10,60,0.18)", pointerEvents: "none", zIndex: 1 }} />

          <div style={{ position: "relative", zIndex: 2 }}>
            {company && (
              <div style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", border: "1px solid rgba(255,255,255,0.25)", background: "rgba(255,255,255,0.12)", fontSize: 10.5, color: "rgba(255,255,255,0.8)", marginBottom: 14 }}>
                <div style={{ width: 6, height: 6, background: "#7cffe6" }} />
                <span style={{ fontWeight: 600, color: "#fff" }}>{company}</span>
              </div>
            )}

            <div
              className="greeting-text"
              style={{
                fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                fontSize: 26, fontWeight: 700,
                letterSpacing: "-0.02em",
                color: "#fff", marginBottom: 4,
              }}
            >
              {headline || "Sessions"}
            </div>

            {/* Stats row */}
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
              {sessions !== null && (
                <>
                  <span style={{ fontSize: 11, color: "rgba(255,255,255,0.85)" }}>
                    {sessions.length} session{sessions.length !== 1 ? "s" : ""}
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
                style={{ padding: "9px 20px", fontSize: 12, fontWeight: 600, color: "#002EFF", background: "#fff", border: "none", cursor: "pointer", letterSpacing: "0.01em" }}
              >+ New run</button>
              <button
                onClick={load}
                style={{ padding: "9px 16px", fontSize: 12, fontWeight: 500, color: "rgba(255,255,255,0.85)", background: "rgba(255,255,255,0.12)", border: "1px solid rgba(255,255,255,0.25)", cursor: "pointer" }}
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
        <div style={{ padding: "20px 24px 40px" }}>
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
                // Nest operating/continuation runs UNDER their launch session, indented,
                // to show the hierarchy (parent run → the goals it spawned).
                const ids = new Set(sessions.map((x) => x.session_id));
                const kids: Record<string, SessionIndexEntry[]> = {};
                const roots: SessionIndexEntry[] = [];
                for (const s of sessions) {
                  const p = s.parent_session_id;
                  if (p && ids.has(p)) (kids[p] ||= []).push(s);
                  else roots.push(s);
                }
                const ordered: { s: SessionIndexEntry; child: boolean }[] = [];
                for (const r of roots) {
                  ordered.push({ s: r, child: false });
                  for (const k of kids[r.session_id] || []) ordered.push({ s: k, child: true });
                }
                return ordered.map(({ s, child }, idx) => {
                const isStalled = s.status === "stalled";
                const isRunning = s.status === "running";
                return (
                  <div
                    key={s.session_id}
                    className={`sc-row${isStalled ? " stalled" : isRunning ? " running" : ""}`}
                    onClick={() => router.push(`/s/${s.session_id}`)}
                    style={{ position: "relative", '--i': idx } as CSSProperties}
                  >
                    {/* Delete */}
                    <button
                      title={pendingDel.has(s.session_id) ? "Click again to confirm delete" : "Delete run"}
                      aria-label={pendingDel.has(s.session_id) ? "Confirm delete" : "Delete run"}
                      disabled={deleting.has(s.session_id)}
                      onClick={(e) => del(e, s)}
                      onPointerDown={(e) => e.stopPropagation()}
                      onTouchStart={(e) => e.stopPropagation()}
                      style={{
                        position: "absolute", top: 6, right: 6,
                        width: pendingDel.has(s.session_id) ? "auto" : 36, height: 36,
                        padding: pendingDel.has(s.session_id) ? "0 10px" : 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: pendingDel.has(s.session_id) ? "var(--rdim)" : "var(--surface)",
                        border: pendingDel.has(s.session_id) ? "1px solid var(--rb)" : "1px solid var(--bd)",
                        color: pendingDel.has(s.session_id) ? "var(--red)" : "var(--fm)",
                        cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 9 : 14, borderRadius: 8,
                        opacity: deleting.has(s.session_id) ? 0.4 : 1,
                        transition: "opacity .15s, background .15s, border-color .15s, color .15s",
                        touchAction: "manipulation", WebkitTapHighlightColor: "transparent",
                        zIndex: 3, fontWeight: 700, letterSpacing: "0.04em", whiteSpace: "nowrap",
                      }}
                    >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DELETE?" : "✕"}</button>

                    <div style={{ flex: 1, paddingRight: 44 }}>
                      {/* Sub-run indicator */}
                      {child && (
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                          <span style={{ width: 14, height: 1, background: "var(--bb)", display: "inline-block", flexShrink: 0 }} />
                          <span style={{ fontSize: 9, color: "var(--blue)", fontFamily: "var(--font-code)", letterSpacing: ".06em", fontWeight: 700, textTransform: "uppercase" }}>sub-run</span>
                        </div>
                      )}
                      {/* Goal */}
                      <div style={{
                        fontSize: 12.5, fontWeight: 600, color: "var(--fg)",
                        lineHeight: 1.45, marginBottom: 7,
                        display: "-webkit-box", WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical", overflow: "hidden",
                      }}>
                        {s.goal || "Untitled run"}
                      </div>

                      {/* Running progress dots */}
                      {isRunning && (
                        <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 7 }}>
                          {["diagnose", "design", "deploy", "govern", "operate"].map((ph) => (
                            <div key={ph} style={{
                              width: 28, height: 3, borderRadius: 2,
                              background: "rgba(0,46,255,0.25)",
                              position: "relative", overflow: "hidden",
                            }}>
                              <div style={{
                                position: "absolute", inset: 0,
                                background: "rgba(0,46,255,0.7)",
                                animation: "dv-fade 1.5s ease-in-out infinite alternate",
                              }} />
                            </div>
                          ))}
                          <span style={{ fontSize: 9, color: "var(--blue)", marginLeft: 4, fontWeight: 600 }}>IN PROGRESS</span>
                        </div>
                      )}

                      {/* Meta row */}
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <StatusPill status={s.status} />
                        <span style={{ fontSize: 10, color: "var(--fm)" }}>{ago(s.created_at)}</span>
                        {s.stack_id && (
                          <span style={{ fontSize: 9, color: "var(--fm)", fontFamily: "var(--font-code)", marginLeft: "auto" }}>
                            {s.stack_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
                });
              })()}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
