"use client";

import Link from "next/link";
import { UserButton, useUser } from "@clerk/nextjs";
import ThemeToggle from "@/components/ThemeToggle";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, borderRadius: 28, overflow: "hidden", border: "1px solid var(--line)", background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", boxShadow: "var(--shadow-sm)" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ label, desc, action }: { label: string; desc?: string; action: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
      <div>
        <p style={{ margin: 0, fontSize: 13, color: "var(--fg)", fontWeight: 500 }}>{label}</p>
        {desc && <p style={{ margin: "2px 0 0", fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>{desc}</p>}
      </div>
      {action}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useUser();

  return (
    <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>
            ← Back
          </Link>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Settings</h1>
            <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>Manage your account and preferences</p>
          </div>
        </div>
        <ThemeToggle />
      </div>

      <Section title="Account">
        <Row label="Profile" desc={user?.primaryEmailAddress?.emailAddress ?? "Manage your Clerk account"} action={<UserButton />} />
        <Row label="Plan" desc="Developer — no usage limits during beta" action={<span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "var(--glass-hi)", color: "var(--fg-dim)", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>Beta</span>} />
      </Section>

      <Section title="Integrations">
        <Row label="GitHub · Vercel · Supabase · Composio" desc="Connect accounts for full agent capabilities" action={
          <Link href="/integrations" className="site-btn site-btn-ghost" style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}>
            Manage →
          </Link>
        } />
        <Row label="Stripe" desc="View revenue, balance, and transactions" action={
          <Link href="/payments" className="site-btn site-btn-ghost" style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}>
            Payments →
          </Link>
        } />
      </Section>

      <Section title="Notifications">
        <Row label="Browser notifications" desc="Get notified when a goal completes" action={
          <button
            onClick={() => Notification.requestPermission()}
            className="site-btn site-btn-primary"
            style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}
          >
            Enable
          </button>
        } />
      </Section>

      <Section title="Data">
        <Row label="Session history" desc="Stored locally in your browser" action={
          <button onClick={() => { if (confirm("Clear all session history?")) { localStorage.removeItem("astra_sessions"); window.location.reload(); } }}
            className="site-btn"
            style={{ fontSize: 12, padding: "0 14px", minHeight: 34, color: "#C97070", background: "rgba(180,60,60,0.10)", borderColor: "rgba(180,60,60,0.20)" }}
          >
            Clear history
          </button>
        } />
      </Section>
    </div>
  );
}
