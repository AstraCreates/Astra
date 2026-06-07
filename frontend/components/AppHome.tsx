"use client";

import { useSyncExternalStore } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import { useDevUser } from "@/lib/use-dev-user";
import { getSessionSnapshot, subscribeSessions } from "@/lib/history";
import SessionView from "@/components/SessionView";
import DashboardView from "@/components/DashboardView";
import NewGoalView from "@/components/NewGoalView";

import type { SessionRecord } from "@/lib/history";

const EMPTY_RECENT_SESSIONS: SessionRecord[] = [];

const NAV_LINKS: { href: string; ic: string; label: string }[] = [
  { href: "/", ic: "⬡", label: "Dashboard" },
  { href: "/outreach", ic: "✦", label: "Outreach" },
  { href: "/brain", ic: "◈", label: "Company Brain" },
  { href: "/integrations", ic: "⌘", label: "Integrations" },
  { href: "/payments", ic: "$", label: "Payments" },
];

function initials(id: string) { return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase(); }

export default function AppHome() {
  const searchParams = useSearchParams();
  const { userId, isSignedIn, user } = useDevUser();
  const recentSessions = useSyncExternalStore(subscribeSessions, getSessionSnapshot, () => EMPTY_RECENT_SESSIONS);

  const forceNewGoal = searchParams.get("new") === "1";
  const latestSession = recentSessions[0];
  const activeSessionId = forceNewGoal ? "" : searchParams.get("session") ?? latestSession?.sessionId ?? "";

  const view = forceNewGoal ? "new" : activeSessionId ? "session" : "dash";

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg)" }}>
      {/* ── Sidebar nav ── */}
      <nav style={{ width: 210, flexShrink: 0, display: "flex", flexDirection: "column", background: "var(--surface)", borderRight: "1px solid var(--bd)", height: "100vh", boxShadow: "2px 0 12px rgba(0,0,0,.04)" }}>
        <div style={{ padding: "20px 16px 16px", borderBottom: "1px solid var(--bd)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <div className="nav-hex"><span style={{ fontFamily: "var(--font-chakra)", fontSize: 12, fontWeight: 700, color: "#fff" }}>A</span></div>
            <div>
              <div className="nav-wordmark">Astra</div>
              <div style={{ fontSize: 9, color: "var(--blue)", letterSpacing: ".06em", textTransform: "uppercase" }}>ready</div>
            </div>
          </div>
          <Link href="/?new=1" className="btn" style={{ display: "flex", justifyContent: "center", gap: 7, width: "100%", textDecoration: "none" }}>＋ New goal</Link>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 1, padding: "10px 8px", flex: 1, overflowY: "auto" }}>
          {NAV_LINKS.map((l) => {
            const on = (l.href === "/" && view !== "new") || (l.href !== "/" && false);
            return (
              <Link key={l.href} href={l.href} className={`nl${on ? " on" : ""}`} style={{ textDecoration: "none" }}>
                <span style={{ width: 18, textAlign: "center" }}>{l.ic}</span>{l.label}
              </Link>
            );
          })}
        </div>

        <div style={{ height: 1, background: "var(--bd)", margin: "6px 8px" }} />
        <div style={{ padding: "0 8px 14px", display: "flex", flexDirection: "column", gap: 1 }}>
          <Link href="/settings" className="nl" style={{ textDecoration: "none" }}><span style={{ width: 18, textAlign: "center" }}>⚙</span>Settings</Link>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
            <div style={{ width: 24, height: 24, background: isSignedIn ? "var(--green)" : "var(--blue)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-chakra)", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{initials(userId)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 9, color: "var(--fm)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {isSignedIn ? (user.fullName || userId) : `${userId.replace(/^user_/, "").slice(0, 12)}…`}
              </div>
            </div>
            {isSignedIn
              ? <button onClick={() => signOut({ callbackUrl: "/" })} style={{ background: "none", border: "none", fontSize: 9, color: "var(--fm)", cursor: "pointer", fontFamily: "var(--font-ibm-mono)" }}>sign out</button>
              : <button onClick={() => signIn("google", { callbackUrl: "/" })} style={{ background: "none", border: "none", fontSize: 9, color: "var(--blue)", cursor: "pointer", fontFamily: "var(--font-ibm-mono)" }}>sign in</button>}
          </div>
        </div>
      </nav>

      {/* ── Main view ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {view === "session"
          ? <SessionView key={activeSessionId} sessionId={activeSessionId} />
          : view === "new"
          ? <>
              <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}><div className="topbar-title">New goal</div></div>
              <NewGoalView />
            </>
          : <>
              <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}><div className="topbar-title">Dashboard</div></div>
              <DashboardView />
            </>}
      </div>
    </div>
  );
}
