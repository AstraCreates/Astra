"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser, SignInButton, SignUpButton } from "@clerk/nextjs";
import { submitGoal } from "@/lib/api";
import { saveSession } from "@/lib/history";
import LiquidGlass from "@/components/LiquidGlass";

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

const STARTER_TEMPLATES = [
  {
    title: "Launch a waitlist",
    desc: "Good for validating demand with a landing page, capture form, and repo scaffold.",
    prompt: EXAMPLES[0],
  },
  {
    title: "Ship an ops tool",
    desc: "Best for internal SaaS, invoicing, support workflows, and basic auth.",
    prompt: EXAMPLES[1],
  },
  {
    title: "Build a network product",
    desc: "Useful when you need matchmaking, messaging, and an investor-ready surface.",
    prompt: EXAMPLES[2],
  },
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
    <div className="site-shell" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 32, alignItems: "start", minHeight: "100vh", paddingTop: 48, paddingBottom: 72 }}>

      <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 520, paddingTop: 14 }}>
        <div className="eyebrow">Astra · AI founding team</div>
        <h1 style={{ fontSize: "clamp(36px, 4vw, 58px)", lineHeight: 1.02, margin: 0 }}>
          What are you
          <br />
          <em className="display-italic">building?</em>
        </h1>
        <p className="lede" style={{ fontSize: "clamp(15px, 1.2vw, 17px)", maxWidth: 42 + "ch" }}>
          Describe the idea. Eight agents run in parallel to produce the repo, landing page, legal docs, market research, and outreach.
        </p>
      </div>

      {isSignedIn ? (
        <LiquidGlass style={{ width: "100%", maxWidth: 760, justifySelf: "end" }} contentStyle={{ padding: "28px 32px" }}>
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

          {/* Stack preferences */}
          <div style={{ border: "1px solid var(--line)", borderRadius: 24, padding: "12px 16px", background: "rgba(0,0,0,0.02)" }}>
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
                        style={{ padding: "8px 12px", fontSize: 13, color: "var(--fg)", background: "linear-gradient(135deg, rgba(255,255,255,0.08), rgba(180,205,228,0.04)), var(--glass-hi)" }}
                      >
                        {opts.map((o) => (
                          <option key={o} value={o} style={{ background: "#0b0e14" }}>{o}</option>
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
              <p style={{ borderRadius: 24, border: "1px solid rgba(200,50,50,0.4)", background: "rgba(180,20,20,0.15)", padding: "10px 14px", fontSize: 13, color: "#f87171", margin: 0 }}>
                {error}
              </p>
            )}
          </form>
        </LiquidGlass>
      ) : (
        <LiquidGlass style={{ width: "100%", maxWidth: 540, justifySelf: "end" }} contentStyle={{ padding: "36px 40px", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 24 }}>
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
        </LiquidGlass>
      )}

      <div style={{ width: "100%", maxWidth: 760, justifySelf: "end" }}>
        <LiquidGlass contentStyle={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span className="site-label">Starter templates</span>
              <h3 style={{ fontSize: 18 }}>Useful starting points</h3>
            </div>
            <span style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)" }}>click to fill the prompt</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            {STARTER_TEMPLATES.map((item) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setInstruction(item.prompt)}
                disabled={loading}
                style={{
                  textAlign: "left",
                  padding: "14px 15px",
                  borderRadius: 24,
                  border: "1px solid rgba(176,180,186,0.10)",
                  background: "rgba(255,255,255,0.03)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <h4 style={{ fontSize: 15 }}>{item.title}</h4>
                <p style={{ fontSize: 12, lineHeight: 1.6, color: "var(--fg-mute)" }}>{item.desc}</p>
              </button>
            ))}
          </div>
        </LiquidGlass>
      </div>
    </div>
  );
}
