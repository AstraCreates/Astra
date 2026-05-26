"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser, SignInButton } from "@clerk/nextjs";
import { submitGoal } from "@/lib/api";
import { saveSession } from "@/lib/history";

const EXAMPLES = [
  "Build a waitlist SaaS for creators — landing page, Next.js app, Supabase DB, Clerk auth, Vercel deploy.",
  "Launch a B2B invoice automation tool — repo, database, auth, landing page, three investor emails.",
  "Build a real-time co-founder matching platform with live URL, auth, and a pitch deck PDF.",
];

const STACK_OPTIONS = {
  frontend: ["Next.js", "React + Vite", "SvelteKit", "Remix"],
  backend: ["FastAPI", "Express / Node", "Django", "Serverless"],
  database: ["Supabase (Postgres)", "PlanetScale (MySQL)", "MongoDB", "SQLite"],
  auth: ["Clerk", "Supabase Auth", "NextAuth", "Custom JWT"],
};

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
    <div style={{ maxWidth: 680, margin: "0 auto", display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <h1 style={{ fontSize: "clamp(22px,2.5vw,32px)", lineHeight: 1.15, margin: "0 0 8px" }}>
          {isSignedIn && user?.firstName ? `What are you building, ${user.firstName}?` : "What are you building?"}
        </h1>
        <p style={{ fontSize: 14, color: "var(--fg-dim)", margin: 0, lineHeight: 1.6 }}>
          Describe your idea — eight agents build the rest in parallel.
        </p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
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
          <p className="site-label">Examples</p>
          {EXAMPLES.map((ex, i) => (
            <button key={i} type="button" onClick={() => setInstruction(ex)} disabled={loading}
              style={{ textAlign: "left", fontSize: 12, color: "var(--fg-mute)", background: "none", border: "none", padding: "1px 0", cursor: "pointer", lineHeight: 1.6 }}>
              · {ex}
            </button>
          ))}
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px" }}>
          <button type="button" onClick={() => setShowStack(v => !v)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
            <span className="site-label">Tech stack</span>
            <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>{showStack ? "▲" : "▼"}</span>
          </button>
          {showStack && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
              {(Object.entries(STACK_OPTIONS) as [string, string[]][]).map(([key, opts]) => (
                <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <label className="site-label">{key}</label>
                  <select value={stack[key as keyof typeof stack]} onChange={e => setStack(p => ({ ...p, [key]: e.target.value }))} disabled={loading} className="site-input" style={{ padding: "7px 10px", fontSize: 12, background: "rgba(10,18,32,0.8)" }}>
                    {opts.map(o => <option key={o} value={o} style={{ background: "#00000A" }}>{o}</option>)}
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

        {error && <p style={{ borderRadius: 8, border: "1px solid rgba(220,38,38,0.4)", background: "rgba(127,29,29,0.2)", padding: "10px 14px", fontSize: 13, color: "#fca5a5" }}>{error}</p>}
      </form>
    </div>
  );
}
