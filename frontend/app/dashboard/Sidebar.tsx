"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { UserButton } from "@clerk/nextjs";
import { getSessions, deleteSession, SessionRecord } from "@/lib/history";

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  const hrs = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (hrs < 24) return `${hrs}h`;
  return `${days}d`;
}

function statusColor(status: SessionRecord["status"]) {
  if (status === "done") return "#6DC98A";
  if (status === "error") return "#C97070";
  return "#1E6AFF";
}

const NAV = [
  { href: "/dashboard", label: "Overview", icon: "⊞" },
  { href: "/dashboard/goals", label: "Goals", icon: "◎" },
  { href: "/dashboard/artifacts", label: "Artifacts", icon: "⬡" },
  { href: "/dashboard/knowledge", label: "Knowledge", icon: "◈" },
];

const BOTTOM_NAV = [
  { href: "/dashboard/integrations", label: "Integrations", icon: "⚡" },
  { href: "/dashboard/settings", label: "Settings", icon: "⊙" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setSessions(getSessions());
    setMounted(true);
    const id = setInterval(() => setSessions(getSessions()), 3000);
    return () => clearInterval(id);
  }, []);

  function remove(e: React.MouseEvent, id: string) {
    e.preventDefault();
    e.stopPropagation();
    deleteSession(id);
    setSessions(getSessions());
    if (pathname.includes(id)) router.push("/dashboard");
  }

  const recentSessions = sessions.slice(0, 8);

  return (
    <aside style={{
      width: 240,
      flexShrink: 0,
      display: "flex",
      flexDirection: "column",
      height: "100%",
      overflow: "hidden",
      borderRight: "1px solid rgba(255,255,255,0.07)",
      background: "rgba(255,255,255,0.04)",
      backdropFilter: "blur(28px) saturate(180%)",
      WebkitBackdropFilter: "blur(28px) saturate(180%)",
    }}>

      {/* Brand */}
      <div style={{ padding: "20px 18px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 9, textDecoration: "none" }}>
          <span style={{
            width: 24, height: 24, borderRadius: "50%", flexShrink: 0,
            background: "radial-gradient(circle, #fff 0%, #1E6AFF 55%, transparent 75%)",
            boxShadow: "0 0 14px rgba(30,106,255,0.6)",
          }} />
          <span style={{ fontSize: 12, letterSpacing: "0.22em", textTransform: "uppercase", color: "var(--fg)", fontFamily: "var(--font-geist-sans)", fontWeight: 500 }}>
            Astra
          </span>
        </Link>
      </div>

      {/* New goal */}
      <div style={{ padding: "12px 12px 8px" }}>
        <Link href="/dashboard" style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          padding: "8px 0", borderRadius: 10, fontSize: 13, fontWeight: 500,
          background: "var(--fg)", color: "var(--ink)", textDecoration: "none",
          transition: "opacity 0.15s",
        }}
          onMouseEnter={e => (e.currentTarget.style.opacity = "0.88")}
          onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
        >
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> New goal
        </Link>
      </div>

      {/* Primary nav */}
      <nav style={{ padding: "4px 8px 0" }}>
        {NAV.map(({ href, label, icon }) => {
          const active = href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
          return (
            <Link key={href} href={href} style={{
              display: "flex", alignItems: "center", gap: 9, padding: "7px 10px",
              borderRadius: 8, marginBottom: 1, textDecoration: "none",
              fontSize: 13, color: active ? "var(--fg)" : "var(--fg-dim)",
              background: active ? "rgba(255,255,255,0.08)" : "transparent",
              fontWeight: active ? 500 : 400,
              transition: "background 0.12s, color 0.12s",
            }}
              onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)"; }}
              onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <span style={{ fontSize: 14, opacity: active ? 1 : 0.5, width: 18, textAlign: "center" }}>{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Divider */}
      <div style={{ margin: "10px 12px", height: 1, background: "rgba(255,255,255,0.06)" }} />

      {/* Recent runs */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
        <p style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: "rgba(255,255,255,0.25)", padding: "0 10px", marginBottom: 4, fontFamily: "var(--font-mono)" }}>
          Recent
        </p>
        {!mounted || recentSessions.length === 0 ? (
          <p style={{ fontSize: 12, color: "rgba(255,255,255,0.2)", padding: "8px 10px", lineHeight: 1.5 }}>No runs yet.</p>
        ) : recentSessions.map(s => {
          const isActive = pathname.includes(s.sessionId);
          const label = s.companyName || s.instruction.slice(0, 28);
          return (
            <Link
              key={s.sessionId}
              href={`/dashboard/goal/${s.sessionId}?instruction=${encodeURIComponent(s.instruction)}&founder=${encodeURIComponent(s.founderId)}&company=${encodeURIComponent(s.companyName)}`}
              style={{
                display: "flex", alignItems: "center", gap: 8, borderRadius: 8,
                padding: "6px 10px", textDecoration: "none", marginBottom: 1,
                background: isActive ? "rgba(255,255,255,0.08)" : "transparent",
                transition: "background 0.12s",
              }}
              onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)"; }}
              onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0, background: statusColor(s.status) }} />
              <span style={{ flex: 1, fontSize: 12, color: isActive ? "var(--fg)" : "var(--fg-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.3 }}>
                {label}
              </span>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.2)", flexShrink: 0, fontFamily: "var(--font-mono)" }}>
                {timeAgo(s.startedAt)}
              </span>
              <button
                onClick={e => remove(e, s.sessionId)}
                style={{ display: "none", background: "none", border: "none", padding: "0 2px", color: "rgba(255,255,255,0.3)", cursor: "pointer", fontSize: 11, lineHeight: 1 }}
                className="sidebar-delete-btn"
                aria-label="Delete"
              >✕</button>
            </Link>
          );
        })}
      </div>

      {/* Bottom nav + user */}
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: "8px 8px 12px" }}>
        {BOTTOM_NAV.map(({ href, label, icon }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href} style={{
              display: "flex", alignItems: "center", gap: 9, padding: "7px 10px",
              borderRadius: 8, marginBottom: 1, textDecoration: "none",
              fontSize: 13, color: active ? "var(--fg)" : "var(--fg-dim)",
              background: active ? "rgba(255,255,255,0.08)" : "transparent",
              transition: "background 0.12s, color 0.12s",
            }}
              onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.04)"; }}
              onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <span style={{ fontSize: 13, opacity: active ? 1 : 0.45, width: 18, textAlign: "center" }}>{icon}</span>
              {label}
            </Link>
          );
        })}

        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px 0", marginTop: 4 }}>
          <UserButton appearance={{ elements: { avatarBox: "w-7 h-7 rounded-full" } }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ fontSize: 11, color: "var(--fg-dim)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>My workspace</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
