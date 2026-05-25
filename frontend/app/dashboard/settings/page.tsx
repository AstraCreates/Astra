"use client";

import Link from "next/link";
import { UserButton, useUser } from "@clerk/nextjs";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, borderRadius: 14, overflow: "hidden", border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.04)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10)" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "rgba(255,255,255,0.3)", fontFamily: "var(--font-mono)" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ label, desc, action }: { label: string; desc?: string; action: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
      <div>
        <p style={{ margin: 0, fontSize: 13, color: "var(--fg)", fontWeight: 500 }}>{label}</p>
        {desc && <p style={{ margin: "2px 0 0", fontSize: 11, color: "rgba(255,255,255,0.3)", lineHeight: 1.4 }}>{desc}</p>}
      </div>
      {action}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useUser();

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Settings</h1>
        <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>Manage your account and preferences</p>
      </div>

      <Section title="Account">
        <Row label="Profile" desc={user?.primaryEmailAddress?.emailAddress ?? "Manage your Clerk account"} action={<UserButton />} />
        <Row label="Plan" desc="Developer — no usage limits during beta" action={<span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "rgba(30,106,255,0.12)", color: "#8BA8C8", border: "1px solid rgba(30,106,255,0.22)", fontFamily: "var(--font-mono)" }}>Beta</span>} />
      </Section>

      <Section title="Integrations">
        <Row label="GitHub · Vercel · Supabase · Composio" desc="Connect accounts for full agent capabilities" action={
          <Link href="/dashboard/integrations" style={{ fontSize: 12, padding: "6px 14px", borderRadius: 8, background: "rgba(255,255,255,0.08)", color: "var(--fg)", border: "1px solid rgba(255,255,255,0.10)", textDecoration: "none", transition: "all 0.12s" }}
            onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,0.14)")}
            onMouseLeave={e => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
          >
            Manage →
          </Link>
        } />
      </Section>

      <Section title="Notifications">
        <Row label="Browser notifications" desc="Get notified when a goal completes" action={
          <button
            onClick={() => Notification.requestPermission()}
            style={{ fontSize: 12, padding: "6px 14px", borderRadius: 8, background: "rgba(255,255,255,0.06)", color: "var(--fg-dim)", border: "1px solid rgba(255,255,255,0.08)", cursor: "pointer", transition: "all 0.12s" }}
            onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,0.10)")}
            onMouseLeave={e => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
          >
            Enable
          </button>
        } />
      </Section>

      <Section title="Data">
        <Row label="Session history" desc="Stored locally in your browser" action={
          <button onClick={() => { if (confirm("Clear all session history?")) { localStorage.removeItem("astra_sessions"); window.location.reload(); } }}
            style={{ fontSize: 12, padding: "6px 14px", borderRadius: 8, background: "rgba(180,60,60,0.08)", color: "#C97070", border: "1px solid rgba(180,60,60,0.18)", cursor: "pointer", transition: "all 0.12s" }}
            onMouseEnter={e => (e.currentTarget.style.background = "rgba(180,60,60,0.15)")}
            onMouseLeave={e => (e.currentTarget.style.background = "rgba(180,60,60,0.08)")}
          >
            Clear history
          </button>
        } />
      </Section>
    </div>
  );
}
