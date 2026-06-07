"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listSessions, deleteSessionRemote, type SessionIndexEntry } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";

function ago(ts: string | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now"; if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
function pill(s: string) {
  if (s === "running") return <span className="pill blue">● Running</span>;
  if (s === "done") return <span className="pill green">✓ Done</span>;
  if (s === "error" || s === "killed") return <span className="pill red">✗ {s === "killed" ? "Stopped" : "Error"}</span>;
  if (s === "stalled") return <span className="pill amber">⚠ Stalled</span>;
  return <span className="pill">{s}</span>;
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [company, setCompany] = useState("");

  useEffect(() => {
    if (typeof window !== "undefined") {
      setCompany(localStorage.getItem("astra_onboarding_company") || "");
    }
  }, []);

  const del = useCallback(async (e: React.MouseEvent, s: SessionIndexEntry) => {
    e.stopPropagation();
    if (!confirm(`Delete this run permanently?\n\n${s.goal || s.session_id}`)) return;
    setDeleting((p) => new Set(p).add(s.session_id));
    const ok = await deleteSessionRemote(s.session_id);
    if (ok) { deleteLocalSession(s.session_id); setSessions((prev) => (prev || []).filter((x) => x.session_id !== s.session_id)); }
    else { alert("Could not delete this run — try again."); setDeleting((p) => { const n = new Set(p); n.delete(s.session_id); return n; }); }
  }, []);

  const load = useCallback(async () => {
    if (!userId) return;
    setError(""); setSessions(null);
    try { setSessions(await listSessions(userId)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setSessions([]); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const running = (sessions || []).filter((s) => s.status === "running").length;
  const sub = sessions === null ? "Loading sessions…"
    : error ? "Could not reach backend"
    : !sessions.length ? "No runs yet — start your first goal."
    : running ? `${running} run${running > 1 ? "s" : ""} active · ${sessions.length} total`
    : `${sessions.length} total run${sessions.length > 1 ? "s" : ""}`;

  const displayName = company;

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div style={{ padding: "28px 22px 0", borderBottom: "1px solid var(--bd)" }}>
        {company && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 20, border: "1px solid var(--bd)", background: "var(--surface)", fontSize: 10.5, color: "var(--fd)", marginBottom: 12 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)" }} />
            <span style={{ fontWeight: 600, color: "var(--fg)" }}>{displayName}</span>
          </div>
        )}
        <div className="dash-ht">Sessions</div>
        <div className="dash-sub">{sub}</div>
        <div style={{ display: "flex", gap: 9, paddingBottom: 22 }}>
          <button className="btn pri" onClick={() => router.push("/?new=1")}>＋ New run</button>
          <button className="btn" onClick={load}>Refresh</button>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 22px 0" }}>
        <div className="sec-label">Recent runs</div>
      </div>

      <div style={{ padding: "14px 22px 22px" }}>
        {sessions === null ? (
          <div style={{ display: "flex", alignItems: "center", gap: 9, padding: 22, color: "var(--fm)", fontSize: 11 }}>Loading sessions…</div>
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
            <div className="empty-sub" style={{ fontSize: 10.5, maxWidth: 280, lineHeight: 1.6 }}>Start your first goal and Astra will build your company step by step.</div>
            <button className="btn pri" style={{ marginTop: 12 }} onClick={() => router.push("/?new=1")}>Start first goal →</button>
          </div>
        ) : (
          <div className="sessions-grid">
            {sessions.map((s) => {
              const cls = s.status === "running" ? "running" : s.status === "done" ? "done" : (s.status === "error" || s.status === "killed") ? "error" : "";
              return (
                <div key={s.session_id} className={`sc ${cls}`} style={{ position: "relative" }} onClick={() => router.push(`/?session=${s.session_id}&founder=${encodeURIComponent(userId)}`)}>
                  <button
                    className="sc-del"
                    title="Delete run"
                    disabled={deleting.has(s.session_id)}
                    onClick={(e) => del(e, s)}
                    style={{ position: "absolute", top: 8, right: 8, width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", border: "1px solid var(--bd)", color: "var(--fm)", cursor: "pointer", fontSize: 12, lineHeight: 1, opacity: deleting.has(s.session_id) ? 0.4 : 1 }}
                  >{deleting.has(s.session_id) ? "…" : "✕"}</button>
                  <div className="sc-goal" style={{ paddingRight: 24 }}>{s.goal || "Untitled run"}</div>
                  <div className="sc-meta">
                    {pill(s.status)}
                    <span className="sc-time">{ago(s.created_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
