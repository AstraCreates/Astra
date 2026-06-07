"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listSessions, deleteSessionRemote, killSession, type SessionIndexEntry } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";

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
    if (!confirm(`Delete this run permanently?\n\n${s.goal || s.session_id}`)) return;
    setDeleting((p) => new Set(p).add(s.session_id));
    // Optimistically drop from the UI immediately so it feels instant.
    deleteLocalSession(s.session_id);
    setSessions((prev) => (prev || []).filter((x) => x.session_id !== s.session_id));
    try {
      // Kill first — a live run would otherwise keep re-persisting itself to the
      // index and reappear on the next refresh.
      await killSession(s.session_id).catch(() => {});
      const ok = await deleteSessionRemote(s.session_id);
      if (!ok) { alert("Could not delete this run on the server — it may reappear on refresh."); }
    } finally {
      setDeleting((p) => { const n = new Set(p); n.delete(s.session_id); return n; });
    }
  }, []);

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
        .sc-row { cursor: pointer; padding: 14px 16px; border-radius: 10px; border: 1.5px solid var(--bd); background: var(--surface); display: flex; align-items: flex-start; gap: 14; transition: border-color .15s, box-shadow .15s; }
        .sc-row:hover { border-color: var(--blue) !important; box-shadow: 0 0 0 3px rgba(59,130,246,.08); }
        .sc-row.stalled { border-color: rgba(245,158,11,0.4) !important; background: rgba(245,158,11,0.04) !important; }
        .sc-row.running { border-color: rgba(59,130,246,0.3) !important; }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Header */}
        <div style={{ padding: "28px 24px 20px", borderBottom: "1px solid var(--bd)" }}>
          {company && (
            <div style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 20, border: "1px solid var(--bd)", background: "var(--surface)", fontSize: 10.5, color: "var(--fd)", marginBottom: 14 }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)" }} />
              <span style={{ fontWeight: 600, color: "var(--fg)" }}>{company}</span>
            </div>
          )}

          <div
            className="greeting-text"
            style={{
              fontFamily: "var(--font-chakra)", fontSize: 22, fontWeight: 700,
              color: "var(--fg)", marginBottom: 4,
            }}
          >
            {headline || "Sessions"}
          </div>

          {/* Stats row */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
            {sessions !== null && (
              <>
                <span style={{ fontSize: 11, color: "var(--fm)" }}>
                  {sessions.length} session{sessions.length !== 1 ? "s" : ""}
                </span>
                {running > 0 && (
                  <span style={{ fontSize: 11, color: "var(--blue)", fontWeight: 600 }}>
                    ● {running} running
                  </span>
                )}
                {stalled > 0 && (
                  <span style={{ fontSize: 11, color: "rgba(245,158,11,1)", fontWeight: 600 }}>
                    ⚠ {stalled} need{stalled === 1 ? "s" : ""} attention
                  </span>
                )}
              </>
            )}
          </div>

          <div style={{ display: "flex", gap: 9 }}>
            <button className="btn pri" onClick={() => router.push("/?new=1")}>＋ New run</button>
            <button className="btn" onClick={load}>Refresh</button>
          </div>
        </div>

        <div style={{ padding: "20px 24px 40px" }}>
          {/* Attention banner */}
          {stalled > 0 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 14px", borderRadius: 9,
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
                    if (first) router.push(`/?session=${first.session_id}&founder=${encodeURIComponent(userId)}`);
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
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {sessions.map((s) => {
                const isStalled = s.status === "stalled";
                const isRunning = s.status === "running";
                return (
                  <div
                    key={s.session_id}
                    className={`sc-row${isStalled ? " stalled" : isRunning ? " running" : ""}`}
                    onClick={() => router.push(`/?session=${s.session_id}&founder=${encodeURIComponent(userId)}`)}
                    style={{ position: "relative" }}
                  >
                    {/* Delete */}
                    <button
                      title="Delete run"
                      disabled={deleting.has(s.session_id)}
                      onClick={(e) => del(e, s)}
                      style={{
                        position: "absolute", top: 10, right: 10,
                        width: 22, height: 22,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: "var(--surface)", border: "1px solid var(--bd)",
                        color: "var(--fm)", cursor: "pointer", fontSize: 11, borderRadius: 5,
                        opacity: deleting.has(s.session_id) ? 0.4 : 0.6,
                        transition: "opacity .15s",
                      }}
                    >{deleting.has(s.session_id) ? "…" : "✕"}</button>

                    <div style={{ flex: 1, paddingRight: 28 }}>
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
                              background: "rgba(59,130,246,0.25)",
                              position: "relative", overflow: "hidden",
                            }}>
                              <div style={{
                                position: "absolute", inset: 0,
                                background: "rgba(59,130,246,0.7)",
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
                          <span style={{ fontSize: 9, color: "var(--fm)", fontFamily: "var(--font-ibm-mono)", marginLeft: "auto" }}>
                            {s.stack_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
