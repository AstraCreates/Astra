"use client";

import { useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useUser, SignInButton } from "@clerk/nextjs";
import { submitGoal } from "@/lib/api";
import { getSessionSnapshot, saveSession, subscribeSessions } from "@/lib/history";
import LiquidGlass from "@/components/LiquidGlass";
import ThemeToggle from "@/components/ThemeToggle";

const EMPTY_RECENT_SESSIONS: readonly never[] = [];

const STACK_OPTIONS = {
  frontend: ["Next.js", "React + Vite", "SvelteKit", "Remix"],
  backend: ["FastAPI", "Express / Node", "Django", "Serverless"],
  database: ["Supabase (Postgres)", "PlanetScale (MySQL)", "MongoDB", "SQLite"],
  auth: ["Clerk", "Supabase Auth", "NextAuth", "Custom JWT"],
};

const STARTER_PROMPTS = [
  {
    title: "Waitlist SaaS",
    prompt: "Build a waitlist SaaS for creators — landing page, Next.js app, Supabase DB, Clerk auth, Vercel deploy.",
  },
  {
    title: "Invoice tool",
    prompt: "Launch a B2B invoice automation tool — repo, database, auth, landing page, three investor emails.",
  },
  {
    title: "Matching platform",
    prompt: "Build a real-time co-founder matching platform with live URL, auth, and a pitch deck PDF.",
  },
];

export default function DashboardHome() {
  const router = useRouter();
  const { user, isSignedIn } = useUser();
  const [companyName, setCompanyName] = useState("");
  const [domain, setDomain] = useState("");
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showStack, setShowStack] = useState(false);
  const [stack, setStack] = useState({ frontend: "Next.js", backend: "FastAPI", database: "Supabase (Postgres)", auth: "Clerk" });
  const recentSessions = useSyncExternalStore(
    subscribeSessions,
    getSessionSnapshot,
    () => EMPTY_RECENT_SESSIONS,
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    const parts = [
      companyName.trim() && `Company name: ${companyName.trim()}.`,
      domain.trim() && `Domain: ${domain.trim()}.`,
      showStack && `Tech stack: Frontend=${stack.frontend}, Backend=${stack.backend}, Database=${stack.database}, Auth=${stack.auth}.`,
    ].filter(Boolean);
    const full = parts.length ? `${parts.join(" ")}\n\n${instruction}` : instruction;
    const founderId = user?.id ?? "anon";
    try {
      const result = await submitGoal(founderId, full);
      saveSession({ sessionId: result.session_id, founderId, companyName: companyName.trim() || instruction.slice(0, 40), instruction, startedAt: Date.now(), status: "running", artifacts: [] });
      if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
      router.push(`/dashboard/goal/${result.session_id}?instruction=${encodeURIComponent(instruction)}&founder=${encodeURIComponent(founderId)}&company=${encodeURIComponent(companyName)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  return (
    <div style={{ width: "100%", maxWidth: 1320, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <LiquidGlass contentStyle={{ padding: "14px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <div style={{ width: 28, height: 28, borderRadius: 9, display: "grid", placeItems: "center", background: "rgba(168,172,178,0.92)", color: "rgba(10,14,22,0.92)", fontWeight: 600, fontSize: 14, flexShrink: 0 }}>A</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 12, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--fg)" }}>Astra dashboard</span>
            <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>Account, integrations, and active goals in one place</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Link href="/dashboard" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>Overview</Link>
          <Link href="/dashboard/settings" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>Settings</Link>
          <Link href="/dashboard/integrations" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>Integrations</Link>
          {recentSessions.length > 0 && (
            <button
              type="button"
              onClick={() => {
                if (confirm("Clear all session history?")) {
                  localStorage.removeItem("astra_sessions");
                  window.location.reload();
                }
              }}
              className="site-btn site-btn-ghost"
              style={{ padding: "0 14px", fontSize: 12, color: "#C97070" }}
            >
              Clear sessions
            </button>
          )}
          <ThemeToggle />
        </div>
      </LiquidGlass>

      <div>
        <h1 style={{ fontSize: "clamp(22px,2.5vw,32px)", lineHeight: 1.15, margin: "0 0 8px" }}>
          {isSignedIn && user?.firstName ? `What are you building, ${user.firstName}?` : "What are you building?"}
        </h1>
        <p style={{ fontSize: 14, color: "var(--fg-dim)", margin: 0, lineHeight: 1.6 }}>
          Describe your idea — eight agents build the rest in parallel.
        </p>
      </div>

      <LiquidGlass contentStyle={{ padding: "28px 30px" }}>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1.15fr 0.85fr", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <label className="site-label">Company</label>
              <input value={companyName} onChange={e => setCompanyName(e.target.value)} className="site-input" style={{ padding: "9px 12px", fontSize: 14 }} placeholder="Astra" disabled={loading} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <label className="site-label">Domain</label>
              <input value={domain} onChange={e => setDomain(e.target.value)} className="site-input" style={{ padding: "9px 12px", fontSize: 14 }} placeholder="astra.ai" disabled={loading} />
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <label className="site-label">Goal</label>
            <textarea value={instruction} onChange={e => setInstruction(e.target.value)}
              placeholder="Build a SaaS for indie hackers to track MRR — landing page, GitHub repo, Supabase backend, Clerk auth, Vercel deploy."
              rows={5} disabled={loading} className="site-textarea"
              style={{ padding: "12px 14px", fontSize: 14, lineHeight: 1.65, resize: "none" }} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <p className="site-label">Starter prompts</p>
            {STARTER_PROMPTS.map((item) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setInstruction(item.prompt)}
                disabled={loading}
                style={{ textAlign: "left", fontSize: 12, color: "var(--fg-mute)", background: "none", border: "none", padding: "1px 0", cursor: "pointer", lineHeight: 1.6 }}
              >
                · {item.title}
              </button>
            ))}
          </div>

          <div style={{ border: "1px solid var(--line)", borderRadius: 24, padding: "10px 12px" }}>
            <button type="button" onClick={() => setShowStack(v => !v)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <span className="site-label">Tech stack</span>
              <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>{showStack ? "▲" : "▼"}</span>
            </button>
            {showStack && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                {(Object.entries(STACK_OPTIONS) as [string, string[]][]).map(([key, opts]) => (
                  <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <label className="site-label">{key}</label>
                    <select value={stack[key as keyof typeof stack]} onChange={e => setStack(p => ({ ...p, [key]: e.target.value }))} disabled={loading} className="site-input" style={{ padding: "7px 10px", fontSize: 12, background: "linear-gradient(135deg, rgba(255,255,255,0.08), rgba(180,205,228,0.04)), var(--glass-hi)" }}>
                      {opts.map(o => <option key={o} value={o} style={{ background: "#0b0e14" }}>{o}</option>)}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 4 }}>
            {isSignedIn ? (
              <button type="submit" disabled={loading || !instruction.trim()} className="site-btn site-btn-primary" style={{ padding: "0 24px", fontSize: 14 }}>
                {loading ? "Launching…" : "Launch Astra →"}
              </button>
            ) : (
              <SignInButton mode="modal">
                <button type="button" className="site-btn site-btn-primary" style={{ padding: "0 24px", fontSize: 14 }}>Sign in to launch →</button>
              </SignInButton>
            )}
          </div>

          {error && <p style={{ borderRadius: 24, border: "1px solid rgba(220,38,38,0.4)", background: "rgba(127,29,29,0.2)", padding: "10px 14px", fontSize: 13, color: "#fca5a5" }}>{error}</p>}
        </form>
      </LiquidGlass>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, alignItems: "stretch" }}>
        <LiquidGlass contentStyle={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="site-label">Account</span>
            <h3 style={{ fontSize: 18 }}>Settings and profile</h3>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <div style={{ padding: "12px 13px", borderRadius: 22, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 13, color: "var(--fg)" }}>{user?.primaryEmailAddress?.emailAddress ?? "Signed in account"}</span>
              <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.6 }}>Manage name, password, and session history</span>
            </div>
            <Link href="/dashboard/settings" className="site-btn site-btn-primary" style={{ width: "fit-content", padding: "0 18px" }}>
              Open account settings →
            </Link>
          </div>
        </LiquidGlass>

        <LiquidGlass contentStyle={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="site-label">Integrations</span>
            <h3 style={{ fontSize: 18 }}>Connect services</h3>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <div style={{ padding: "12px 13px", borderRadius: 22, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 13, color: "var(--fg)" }}>GitHub, Vercel, Supabase, SendGrid</span>
              <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.6 }}>Control repo access, deploys, data, and email</span>
            </div>
            <Link href="/dashboard/integrations" className="site-btn site-btn-primary" style={{ width: "fit-content", padding: "0 18px" }}>
              Open integrations →
            </Link>
          </div>
        </LiquidGlass>

        <LiquidGlass contentStyle={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span className="site-label">Recent</span>
              <h3 style={{ fontSize: 18 }}>Open any saved run</h3>
            </div>
            <span style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)" }}>{recentSessions.length} saved</span>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            {recentSessions.slice(0, 4).length ? recentSessions.slice(0, 4).map((session) => (
              <button
                key={session.sessionId}
                type="button"
                onClick={() => router.push(`/dashboard/goal/${session.sessionId}`)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "10px 12px", borderRadius: 22, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", textAlign: "left" }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
                  <span style={{ fontSize: 13, color: "var(--fg)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{session.companyName}</span>
                  <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{session.status} · {session.artifacts.length} artifacts</span>
                </div>
                <span className="site-pill" style={{ padding: "6px 10px", fontSize: 11 }}>{session.sessionId.slice(0, 6)}</span>
              </button>
            )) : (
              <div style={{ padding: "14px 12px", borderRadius: 22, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", color: "var(--fg-mute)", fontSize: 13, lineHeight: 1.6 }}>
                Once you launch a goal, saved runs will appear here.
              </div>
            )}
          </div>
        </LiquidGlass>
      </div>

    </div>
  );
}
