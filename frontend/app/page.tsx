"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser, SignInButton } from "@clerk/nextjs";
import { submitGoal } from "@/lib/api";
import { saveSession } from "@/lib/history";

const STACK_OPTIONS = {
  frontend: ["Next.js", "React + Vite", "SvelteKit", "Remix"],
  backend: ["FastAPI", "Express / Node", "Django", "Serverless"],
  database: ["Supabase (Postgres)", "PlanetScale (MySQL)", "MongoDB", "SQLite"],
  auth: ["Clerk", "Supabase Auth", "NextAuth", "Custom JWT"],
};

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
      showStack && `Tech stack preferences: Frontend=${stack.frontend}, Backend=${stack.backend}, Database=${stack.database}, Auth=${stack.auth}.`,
    ].filter(Boolean);

    const full = parts.length ? `${parts.join(" ")}\n\n${instruction}` : instruction;
    const founderId = user?.id ?? "anon";

    try {
      const result = await submitGoal(founderId, full);

      // Save to history
      saveSession({
        sessionId: result.session_id,
        founderId,
        companyName: companyName.trim() || instruction.slice(0, 40),
        instruction,
        startedAt: Date.now(),
        status: "running",
        artifacts: [],
      });

      // Request browser notification permission
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission();
      }

      router.push(`/goal/${result.session_id}?instruction=${encodeURIComponent(instruction)}&founder=${encodeURIComponent(founderId)}&company=${encodeURIComponent(companyName)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  const EXAMPLES = [
    "Build a waitlist SaaS for creators — landing page, Next.js app, Supabase DB, Clerk auth, Vercel deploy.",
    "Launch a B2B invoice automation tool — repo, database, auth, landing page, three investor emails.",
    "Build a real-time co-founder matching platform with live URL, auth, and a pitch deck PDF.",
  ];

  return (
    <div className="flex flex-col gap-20">
      {/* Hero */}
      <section className="grid gap-10 lg:grid-cols-[1fr_1.1fr] lg:items-center">
        <div className="flex flex-col gap-8">
          <div className="flex flex-col gap-5">
            <div className="eyebrow">Astra · AI founding team</div>
            <h1>
              You bring<br />the idea.<br />
              <span className="display-italic">Astra does<br />the rest.</span>
            </h1>
            <p className="lede">
              One instruction. Eight agents running in parallel — GitHub repo, Supabase database, Vercel deploy, landing page, legal docs, investor outreach.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            {[
              { value: "8", label: "Agents" },
              { value: "Auto", label: "GitHub + Vercel" },
              { value: "1", label: "Prompt" },
            ].map((s) => (
              <div key={s.label} className="site-card site-card-soft px-5 py-3 flex items-center gap-3">
                <span className="text-xl font-bold text-white">{s.value}</span>
                <span className="site-label">{s.label}</span>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <Link href="/dashboard" className="site-btn site-btn-ghost">Dashboard</Link>
            <Link href="/setup" className="site-btn site-btn-ghost">Connect accounts</Link>
          </div>
        </div>

        {/* Launch card */}
        <div className="site-card p-6 sm:p-7 flex flex-col gap-5">
          <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] pb-5">
            <div>
              <p className="site-label">Launch prompt</p>
              <p className="mt-1.5 text-sm text-[var(--fg-dim)]">
                Describe what you&rsquo;re building. Astra plans, builds, and deploys.
              </p>
            </div>
            <span className="site-pill">Live</span>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Company + domain */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <label className="site-label">Company name</label>
                <input
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="site-input px-4 py-3 text-sm text-white"
                  placeholder="Astra"
                  disabled={loading}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="site-label">Domain (optional)</label>
                <input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  className="site-input px-4 py-3 text-sm text-white"
                  placeholder="astra.ai"
                  disabled={loading}
                />
              </div>
            </div>

            {/* Goal */}
            <div className="flex flex-col gap-1.5">
              <label className="site-label">Goal</label>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Build a SaaS product for indie hackers to track MRR — landing page, GitHub repo, Supabase backend, Clerk auth, Vercel deploy."
                rows={5}
                className="site-textarea resize-none px-4 py-4 text-sm leading-6"
                disabled={loading}
              />
            </div>

            {/* Examples */}
            <div className="flex flex-col gap-1.5">
              <p className="site-label">Examples</p>
              {EXAMPLES.map((ex, i) => (
                <button key={i} type="button" onClick={() => setInstruction(ex)} disabled={loading}
                  className="text-left text-xs text-[var(--fg-mute)] hover:text-[var(--fg-dim)] transition-colors leading-relaxed">
                  · {ex}
                </button>
              ))}
            </div>

            {/* Stack preferences toggle */}
            <div className="flex flex-col gap-3 border border-[var(--line)] rounded-xl p-4 bg-[rgba(255,255,255,0.02)]">
              <button type="button" onClick={() => setShowStack(v => !v)}
                className="flex items-center justify-between w-full text-left">
                <span className="site-label">Tech stack preferences</span>
                <span className="text-xs text-[var(--fg-mute)]">{showStack ? "▲ hide" : "▼ show"}</span>
              </button>
              {showStack && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {(Object.entries(STACK_OPTIONS) as [string, string[]][]).map(([key, opts]) => (
                    <div key={key} className="flex flex-col gap-1.5">
                      <label className="site-label">{key}</label>
                      <select
                        value={stack[key]}
                        onChange={(e) => setStack(p => ({ ...p, [key]: e.target.value }))}
                        disabled={loading}
                        className="site-input px-3 py-2.5 text-sm text-white"
                        style={{ background: "rgba(255,255,255,0.04)" }}
                      >
                        {opts.map(o => <option key={o} value={o} style={{ background: "#0d1117" }}>{o}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Submit */}
            <div className="flex justify-end">
              {isSignedIn ? (
                <button type="submit" disabled={loading || !instruction.trim()}
                  className="site-btn site-btn-primary px-6">
                  {loading ? "Launching…" : "Launch Astra"}
                  <span aria-hidden="true">→</span>
                </button>
              ) : (
                <SignInButton mode="modal">
                  <button type="button" className="site-btn site-btn-primary px-6">
                    Sign in to launch →
                  </button>
                </SignInButton>
              )}
            </div>

            {error && (
              <p className="rounded-2xl border border-red-900/70 bg-red-950/30 px-4 py-3 text-sm text-red-300">{error}</p>
            )}
          </form>
        </div>
      </section>

      <div className="site-rule" />

      {/* Process */}
      <section id="process" className="grid gap-10 lg:grid-cols-[0.75fr_1.25fr] lg:items-start">
        <div className="flex flex-col gap-5">
          <div className="eyebrow">The flow</div>
          <h2>One instruction.<br /><span className="display-italic">A full founding stack.</span></h2>
          <p className="lede">
            Eight specialists run in parallel — each executing real actions, not describing them.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            { step: "01", title: "Research", desc: "Market sizing, competitors, TAM/SAM/SOM before you spend a dollar." },
            { step: "02", title: "Build & Deploy", desc: "GitHub repo → Supabase DB → Claude Code scaffold → Vercel. Live URL." },
            { step: "03", title: "Launch", desc: "Landing page, campaigns, social content from the same strategy." },
            { step: "04", title: "Operate", desc: "Legal docs, investor outreach, Linear tickets, persistent memory." },
          ].map((item) => (
            <article key={item.step} className="site-card site-card-soft p-5">
              <div className="site-label">{item.step}</div>
              <h3 className="mt-3 text-[24px] leading-none">{item.title}</h3>
              <p className="mt-3 text-sm leading-6 text-[var(--fg-dim)]">{item.desc}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Agents */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { icon: "🔬", label: "Research", desc: "TAM, SAM, SOM, competitors, customer profile." },
          { icon: "🌐", label: "Web", desc: "Landing pages + full app deploys to Vercel." },
          { icon: "📢", label: "Marketing", desc: "Campaigns, social content, outreach." },
          { icon: "⚙️", label: "Technical", desc: "GitHub → Supabase → Claude Code → Vercel. Live." },
          { icon: "⚖️", label: "Legal", desc: "Entity setup, policies, compliance drafting." },
          { icon: "🚀", label: "Ops", desc: "Fundraising docs, investor outreach, scheduling." },
          { icon: "🤝", label: "Sales", desc: "Lead finding, enrichment, outreach sequences." },
          { icon: "🎨", label: "Design", desc: "Wireframes, color palettes, logo briefs, specs." },
        ].map((item) => (
          <div key={item.label} className="site-card site-card-soft p-5">
            <span className="text-2xl">{item.icon}</span>
            <p className="mt-4 text-sm font-medium tracking-wide text-white">{item.label}</p>
            <p className="mt-1.5 text-xs leading-5 text-[var(--fg-dim)]">{item.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
