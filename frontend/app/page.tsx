"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser, SignInButton, SignUpButton } from "@clerk/nextjs";
import { submitGoal } from "@/lib/api";
import { saveSession } from "@/lib/history";

const STACK_OPTIONS = {
  frontend: ["Next.js", "React + Vite", "SvelteKit", "Remix"],
  backend: ["FastAPI", "Express / Node", "Django", "Serverless"],
  database: ["Supabase (Postgres)", "PlanetScale (MySQL)", "MongoDB", "SQLite"],
  auth: ["Clerk", "Supabase Auth", "NextAuth", "Custom JWT"],
};

const EXAMPLES = [
  "Build a waitlist SaaS for creators — landing page, Next.js app, Supabase DB, Clerk auth, Vercel deploy.",
  "Launch a B2B invoice automation tool — repo, database, auth, landing page, three investor emails.",
  "Build a real-time co-founder matching platform with live URL, auth, and a pitch deck PDF.",
];

export default function Home() {
  const router = useRouter();
  const { user, isSignedIn } = useUser();
  const [companyName, setCompanyName] = useState("");
  const [domain, setDomain] = useState("");
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showStack, setShowStack] = useState(false);
  const [stack, setStack] = useState<Record<string, string>>({
    frontend: "Next.js",
    backend: "FastAPI",
    database: "Supabase (Postgres)",
    auth: "Clerk",
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);

    const parts = [
      companyName.trim() && `Company name: ${companyName.trim()}.`,
      domain.trim() && `Domain: ${domain.trim()}.`,
      showStack &&
        `Tech stack preferences: Frontend=${stack.frontend}, Backend=${stack.backend}, Database=${stack.database}, Auth=${stack.auth}.`,
    ].filter(Boolean);

    const full = parts.length ? `${parts.join(" ")}\n\n${instruction}` : instruction;
    const founderId = user?.id ?? "anon";

    try {
      const result = await submitGoal(founderId, full);
      saveSession({
        sessionId: result.session_id,
        founderId,
        companyName: companyName.trim() || instruction.slice(0, 40),
        instruction,
        startedAt: Date.now(),
        status: "running",
        artifacts: [],
      });
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission();
      }
      router.push(
        `/dashboard/goal/${result.session_id}?instruction=${encodeURIComponent(instruction)}&founder=${encodeURIComponent(founderId)}&company=${encodeURIComponent(companyName)}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  return (
    <div className="site-shell" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: 32 }}>

      {/* Header text */}
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <div className="eyebrow" style={{ justifyContent: "center", marginBottom: 20 }}>Astra · AI founding team</div>
        <h1 style={{ fontSize: "clamp(32px, 4vw, 52px)", lineHeight: 1.1, marginBottom: 16 }}>
          What are you<br />
          <em className="display-italic">building?</em>
        </h1>
        <p className="lede" style={{ margin: "0 auto", textAlign: "center", fontSize: "clamp(14px, 1.2vw, 16px)" }}>
          Describe the idea. Eight agents run in parallel — GitHub repo, landing page, legal docs,
          market research, investor outreach.
        </p>
      </div>

      {/* Form or sign-in prompt */}
      {isSignedIn ? (
        <div className="site-card" style={{ width: "100%", maxWidth: 580, padding: "28px 32px" }}>
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Company + domain */}
            <div style={{ display: "grid", gap: 12, gridTemplateColumns: "1fr 1fr" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label className="site-label">Company name</label>
                <input
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="site-input"
                  style={{ padding: "10px 14px", fontSize: 14 }}
                  placeholder="Astra"
                  disabled={loading}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label className="site-label">Domain (optional)</label>
                <input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  className="site-input"
                  style={{ padding: "10px 14px", fontSize: 14 }}
                  placeholder="astra.ai"
                  disabled={loading}
                />
              </div>
            </div>

            {/* Goal */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label className="site-label">Goal</label>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Build a SaaS for indie hackers to track MRR — landing page, GitHub repo, Supabase backend, Clerk auth, Vercel deploy."
                rows={5}
                className="site-textarea"
                style={{ padding: "14px", fontSize: 14, lineHeight: 1.6, resize: "none" }}
                disabled={loading}
              />
            </div>

            {/* Examples */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <p className="site-label">Examples</p>
              {EXAMPLES.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setInstruction(ex)}
                  disabled={loading}
                  style={{
                    textAlign: "left", fontSize: 12, color: "var(--fg-mute)",
                    cursor: "pointer", background: "none", border: "none",
                    padding: "2px 0", lineHeight: 1.5, transition: "color 0.2s",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "var(--fg-dim)")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "var(--fg-mute)")}
                >
                  · {ex}
                </button>
              ))}
            </div>

            {/* Stack preferences */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: "12px 16px", background: "rgba(0,0,0,0.02)" }}>
              <button
                type="button"
                onClick={() => setShowStack((v) => !v)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer" }}
              >
                <span className="site-label">Tech stack preferences</span>
                <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{showStack ? "▲ hide" : "▼ show"}</span>
              </button>
              {showStack && (
                <div style={{ display: "grid", gap: 10, gridTemplateColumns: "1fr 1fr", marginTop: 12 }}>
                  {(Object.entries(STACK_OPTIONS) as [string, string[]][]).map(([key, opts]) => (
                    <div key={key} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      <label className="site-label">{key}</label>
                      <select
                        value={stack[key]}
                        onChange={(e) => setStack((p) => ({ ...p, [key]: e.target.value }))}
                        disabled={loading}
                        className="site-input"
                        style={{ padding: "8px 12px", fontSize: 13, color: "var(--fg)", background: "#FFFFFF" }}
                      >
                        {opts.map((o) => (
                          <option key={o} value={o}>{o}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="submit"
                disabled={loading || !instruction.trim()}
                className="site-btn site-btn-primary"
                style={{ padding: "0 24px" }}
              >
                {loading ? "Launching…" : "Launch Astra"}{" "}
                <span aria-hidden="true">→</span>
              </button>
            </div>

            {error && (
              <p style={{ borderRadius: 10, border: "1px solid rgba(200,50,50,0.4)", background: "rgba(180,20,20,0.15)", padding: "10px 14px", fontSize: 13, color: "#f87171", margin: 0 }}>
                {error}
              </p>
            )}
          </form>
        </div>
      ) : (
        <div className="site-card" style={{ width: "100%", maxWidth: 420, padding: "36px 40px", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 24 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <p style={{ margin: 0, fontSize: 16, color: "var(--fg)" }}>Sign in to launch your company</p>
            <p className="site-muted" style={{ margin: 0, fontSize: 13, lineHeight: 1.6 }}>
              Eight agents, one prompt. GitHub, Vercel, legal, outreach — all automated.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <SignInButton mode="modal">
              <button className="site-btn site-btn-ghost" style={{ padding: "0 20px" }}>Sign in</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="site-btn site-btn-primary" style={{ padding: "0 20px" }}>
                Get started <span aria-hidden="true">→</span>
              </button>
            </SignUpButton>
          </div>
          <a
            href="https://astracreates.com"
            style={{ fontSize: 12, color: "var(--fg-mute)", transition: "color 0.2s" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--fg-dim)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--fg-mute)")}
          >
            Learn more at astracreates.com →
          </a>
        </div>
      )}
    </div>
  );
}
