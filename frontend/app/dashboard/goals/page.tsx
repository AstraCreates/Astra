"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSessions, deleteSession, SessionRecord } from "@/lib/history";

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  const hrs = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hrs < 24) return `${hrs}h ago`;
  return `${days}d ago`;
}

const STATUS_META = {
  done: { label: "Complete", color: "#6DC98A", bg: "rgba(60,170,100,0.10)", border: "rgba(60,170,100,0.22)" },
  running: { label: "Running", color: "#ffffff", bg: "rgba(255,255,255,0.10)", border: "rgba(255,255,255,0.22)" },
  error: { label: "Error", color: "#C97070", bg: "rgba(180,60,60,0.10)", border: "rgba(180,60,60,0.22)" },
};

export default function GoalsPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [mounted, setMounted] = useState(false);
  const [filter, setFilter] = useState<"all" | "done" | "running" | "error">("all");

  useEffect(() => { setSessions(getSessions()); setMounted(true); }, []);

  function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    deleteSession(id);
    setSessions(getSessions());
  }

  const filtered = filter === "all" ? sessions : sessions.filter(s => s.status === filter);

  return (
    <div style={{ maxWidth: 1100, margin: 0, display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>All goals</h1>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>{sessions.length} total</p>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {(["all", "done", "running", "error"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} className={`site-btn ${filter === f ? "site-btn-primary" : "site-btn-ghost"}`} style={{ padding: "0 14px", fontSize: 12, minHeight: 34 }}>
              {f === "all" ? "All" : STATUS_META[f].label}
            </button>
          ))}
        </div>
      </div>

      {mounted && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.length === 0 && (
            <div style={{ padding: "40px 0", textAlign: "center", color: "rgba(255,255,255,0.2)", fontSize: 13 }}>No goals yet.</div>
          )}
          {filtered.map(s => {
            const meta = STATUS_META[s.status];
            return (
              <div key={s.sessionId}
                onClick={() => router.push(`/dashboard/goal/${s.sessionId}?instruction=${encodeURIComponent(s.instruction)}&founder=${encodeURIComponent(s.founderId)}&company=${encodeURIComponent(s.companyName)}`)}
                style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 20px", borderRadius: 28, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08)", transition: "background 0.12s" }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.07)"}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)"}
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: meta.color }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.companyName || s.instruction.slice(0, 60)}
                  </p>
                  {s.companyName && <p style={{ margin: "2px 0 0", fontSize: 11, color: "rgba(255,255,255,0.3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.instruction.slice(0, 80)}</p>}
                </div>
                <span style={{ fontSize: 10, padding: "2px 9px", borderRadius: 999, color: meta.color, background: meta.bg, border: `1px solid ${meta.border}`, fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                  {meta.label}
                </span>
                <span style={{ fontSize: 11, color: "rgba(255,255,255,0.25)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{timeAgo(s.startedAt)}</span>
                <button onClick={e => remove(e, s.sessionId)} style={{ background: "none", border: "none", color: "rgba(255,255,255,0.2)", cursor: "pointer", fontSize: 14, padding: "2px 4px", borderRadius: 4, transition: "color 0.12s" }}
                  onMouseEnter={e => (e.currentTarget.style.color = "#C97070")}
                  onMouseLeave={e => (e.currentTarget.style.color = "rgba(255,255,255,0.2)")}
                >✕</button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
