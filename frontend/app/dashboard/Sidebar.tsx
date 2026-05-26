"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { UserButton } from "@clerk/nextjs";
import { getSessions, deleteSession, SessionRecord } from "@/lib/history";
import LiquidGlass from "@/components/LiquidGlass";
import ThemeToggle from "@/components/ThemeToggle";

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
  if (status === "done") return "#5a9e72";
  if (status === "error") return "#b05555";
  return "#ffffff";
}

const NAV = [
  { href: "/dashboard",             label: "Overview",     icon: "○" },
  { href: "/dashboard/goals",       label: "Goals",        icon: "◇" },
  { href: "/dashboard/artifacts",   label: "Artifacts",    icon: "□" },
  { href: "/dashboard/knowledge",   label: "Knowledge",    icon: "△" },
];

const BOTTOM_NAV = [
  { href: "/dashboard/integrations", label: "Integrations", icon: "+" },
  { href: "/dashboard/settings",     label: "Settings",     icon: "≡" },
];


export default function Sidebar() {
  const pathname = usePathname();
  const router   = useRouter();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [mounted,  setMounted]  = useState(false);

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
    <LiquidGlass
      style={{
        width: 232,
        flexShrink: 0,
        height: "100%",
        borderRight: "1px solid rgba(180,205,228,0.18)",
        boxShadow: "1px 0 0 rgba(0,0,0,0.04)",
        borderRadius: 0,
      }}
      contentStyle={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
      borderRadius={0}
      tint="rgba(180,205,228,0.07)"
      displacementScale={20}
    >

      {/* Brand */}
      <div style={{ padding: "20px 16px 16px", borderBottom: "1px solid rgba(180,205,228,0.14)" }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <span style={{
            width: 22, height: 22, borderRadius: 6, flexShrink: 0,
            background: "rgba(178,196,216,0.92)", color: "rgba(10,14,22,0.92)",
            display: "grid", placeItems: "center",
            fontSize: 13, fontWeight: 600, lineHeight: 1,
          }}>A</span>
          <span style={{ fontSize: 12, letterSpacing: "0.16em", textTransform: "uppercase", color: "#dce6f0", fontWeight: 500 }}>
            Astra
          </span>
        </Link>
      </div>

      {/* New goal */}
      <div style={{ padding: "12px 12px 8px" }}>
        <Link href="/dashboard" style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          padding: "9px 16px", borderRadius: 24, fontSize: 13, fontWeight: 500,
          background: "rgba(178,196,216,0.92)", color: "rgba(10,14,22,0.92)",
          textDecoration: "none", letterSpacing: "0.01em",
          border: "1px solid rgba(0,0,0,0.08)",
          transition: "opacity 0.18s ease",
        }}
          onMouseEnter={e => (e.currentTarget.style.opacity = "0.84")}
          onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
        >
          + New goal
        </Link>
      </div>

      {/* Primary nav */}
      <nav style={{ padding: "4px 8px 0" }}>
        {NAV.map(({ href, label, icon }) => {
          const active = href === "/dashboard"
            ? pathname === "/dashboard"
            : pathname.startsWith(href);
          return (
            <Link key={href} href={href} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
              borderRadius: 24, marginBottom: 1, textDecoration: "none",
              fontSize: 13, fontWeight: active ? 500 : 400,
              color: active ? "#ffffff" : "rgba(255,255,255,0.82)",
              background: active ? "rgba(180,205,228,0.12)" : "transparent",
              boxShadow: active ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
              border: active ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
              transition: "background 0.15s ease, color 0.15s ease",
            }}
              onMouseEnter={e => { if (!active) { (e.currentTarget as HTMLElement).style.background = "rgba(180,205,228,0.10)"; (e.currentTarget as HTMLElement).style.color = "#dce6f0"; } }}
              onMouseLeave={e => { if (!active) { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.82)"; } }}
            >
              <span style={{ fontSize: 11, opacity: active ? 0.7 : 0.4, width: 16, textAlign: "center", fontFamily: "monospace" }}>{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Divider */}
      <div style={{ margin: "10px 12px", height: 1, background: "rgba(180,205,228,0.14)" }} />

      {/* Recent runs */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px", marginBottom: 6 }}>
          <p style={{ fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.82)", margin: 0, fontFamily: "var(--font-jetbrains-mono)" }}>Recent</p>
          {mounted && recentSessions.length > 0 && (
            <button
              onClick={() => { localStorage.removeItem("astra_sessions"); setSessions([]); }}
              style={{ background: "none", border: "none", fontSize: 9, color: "rgba(255,255,255,0.82)", cursor: "pointer", padding: 0, letterSpacing: "0.06em", transition: "color 0.15s" }}
              onMouseEnter={e => ((e.currentTarget as HTMLElement).style.color = "#ffffff")}
              onMouseLeave={e => ((e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.82)")}
            >clear</button>
          )}
        </div>

        {!mounted || recentSessions.length === 0 ? (
          <p style={{ fontSize: 12, color: "rgba(255,255,255,0.82)", padding: "8px 10px", lineHeight: 1.5, margin: 0 }}>No runs yet.</p>
        ) : recentSessions.map(s => {
          const isActive = pathname.includes(s.sessionId);
          const label = s.companyName || s.instruction.slice(0, 28);
          return (
            <Link
              key={s.sessionId}
              href={`/dashboard/goal/${s.sessionId}?instruction=${encodeURIComponent(s.instruction)}&founder=${encodeURIComponent(s.founderId)}&company=${encodeURIComponent(s.companyName)}`}
              style={{
                display: "flex", alignItems: "center", gap: 8, borderRadius: 24,
                padding: "7px 10px", textDecoration: "none", marginBottom: 1,
                background: isActive ? "rgba(180,205,228,0.12)" : "transparent",
                border: isActive ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
                boxShadow: isActive ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
                transition: "background 0.15s ease",
              }}
              onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "rgba(180,205,228,0.10)"; }}
              onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <span style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0, background: statusColor(s.status) }} />
              <span style={{ flex: 1, fontSize: 12, color: isActive ? "#ffffff" : "rgba(255,255,255,0.82)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.3 }}>
                {label}
              </span>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.82)", flexShrink: 0, fontFamily: "var(--font-jetbrains-mono)" }}>
                {timeAgo(s.startedAt)}
              </span>
              <button
                onClick={e => remove(e, s.sessionId)}
                style={{ display: "none", background: "none", border: "none", padding: "0 2px", color: "rgba(255,255,255,0.82)", cursor: "pointer", fontSize: 11, lineHeight: 1 }}
                className="sidebar-delete-btn"
                aria-label="Delete"
              >✕</button>
            </Link>
          );
        })}
      </div>

      {/* Bottom nav + user */}
      <div style={{ borderTop: "1px solid rgba(180,205,228,0.14)", padding: "8px 8px 14px" }}>
        {BOTTOM_NAV.map(({ href, label, icon }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
              borderRadius: 24, marginBottom: 1, textDecoration: "none",
              fontSize: 13, fontWeight: active ? 500 : 400,
              color: active ? "#ffffff" : "rgba(255,255,255,0.82)",
              background: active ? "rgba(180,205,228,0.12)" : "transparent",
              border: active ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
              transition: "background 0.15s ease, color 0.15s ease",
            }}
              onMouseEnter={e => { if (!active) { (e.currentTarget as HTMLElement).style.background = "rgba(180,205,228,0.10)"; (e.currentTarget as HTMLElement).style.color = "#dce6f0"; } }}
              onMouseLeave={e => { if (!active) { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.82)"; } }}
            >
              <span style={{ fontSize: 11, opacity: active ? 0.7 : 0.4, width: 16, textAlign: "center", fontFamily: "monospace" }}>{icon}</span>
              {label}
            </Link>
          );
        })}

        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 10px 0", marginTop: 4, borderTop: "1px solid rgba(180,205,228,0.12)" }}>
          <UserButton appearance={{ elements: { avatarBox: "w-7 h-7 rounded-full" } }} />
          <p style={{ fontSize: 11, color: "rgba(255,255,255,0.82)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>My workspace</p>
          <ThemeToggle />
        </div>
      </div>
    </LiquidGlass>
  );
}
