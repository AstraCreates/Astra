"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { submitGoal } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [companyName, setCompanyName] = useState("");
  const [domain, setDomain] = useState("");
  const [instruction, setInstruction] = useState("");
  const [founderId, setFounderId] = useState("founder_001");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);

    // Prepend company name + domain context to the instruction
    const context = [
      companyName.trim() && `Company name: ${companyName.trim()}.`,
      domain.trim() && `Domain: ${domain.trim()}.`,
    ].filter(Boolean).join(" ");

    const full = context ? `${context}\n\n${instruction}` : instruction;

    try {
      const result = await submitGoal(founderId, full);
      router.push(`/goal/${result.session_id}?instruction=${encodeURIComponent(instruction)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  const EXAMPLES = [
    "Build a waitlist SaaS for creators, deploy a landing page and scaffold the full Next.js app with Supabase auth.",
    "Launch a B2B invoice automation tool — repo, database, auth, landing page, and three investor emails.",
    "Build a real-time co-founder matching platform with Next.js, Supabase, Clerk auth, and a deployed Vercel URL.",
  ];

  return (
    <div className="flex flex-col gap-20">
      {/* Hero */}
      <section className="grid gap-12 lg:grid-cols-[1fr_1fr] lg:items-center">
        <div className="flex flex-col gap-8">
          <div className="flex flex-col gap-5">
            <div className="eyebrow">Astra · AI founding team</div>
            <h1>
              You bring<br />
              the idea.<br />
              <span className="display-italic">Astra does<br />the rest.</span>
            </h1>
            <p className="lede">
              One instruction. A full company — GitHub repo, Supabase database, Vercel deploy, landing page, legal docs, investor outreach — all running in parallel.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            {[
              { value: "8", label: "Agents" },
              { value: "Auto", label: "Deploy" },
              { value: "1", label: "Prompt" },
            ].map((stat) => (
              <div key={stat.label} className="site-card site-card-soft px-5 py-4 flex items-center gap-3">
                <div className="text-2xl font-bold text-white">{stat.value}</div>
                <div className="site-label">{stat.label}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <Link href="/setup" className="site-btn site-btn-ghost">Connect accounts</Link>
            <Link href="/#process" className="site-btn site-btn-ghost">See how it works</Link>
          </div>
        </div>

        {/* Launch card */}
        <div className="site-card p-6 sm:p-7 flex flex-col gap-5">
          <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] pb-5">
            <div>
              <p className="site-label">Launch prompt</p>
              <p className="mt-2 text-sm text-[var(--fg-dim)]">
                Describe what you&rsquo;re building. Astra plans, builds, and deploys.
              </p>
            </div>
            <span className="site-pill">Live</span>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Company + domain row */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <label className="site-label">Company name</label>
                <input
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="site-input px-4 py-3 text-sm text-white"
                  placeholder="Astra"
                  disabled={loading}
                />
              </div>
              <div className="flex flex-col gap-2">
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

            {/* Goal textarea */}
            <div className="flex flex-col gap-2">
              <label className="site-label">Goal</label>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Build a SaaS product for indie hackers to track MRR across Stripe, Lemon Squeezy, and Paddle — landing page, GitHub repo, Supabase backend, Clerk auth, and Vercel deploy."
                rows={5}
                className="site-textarea resize-none px-4 py-4 text-sm leading-6"
                disabled={loading}
              />
            </div>

            {/* Example prompts */}
            <div className="flex flex-col gap-1.5">
              <p className="site-label">Examples</p>
              <div className="flex flex-col gap-1.5">
                {EXAMPLES.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setInstruction(ex)}
                    disabled={loading}
                    className="text-left text-xs text-[var(--fg-mute)] hover:text-[var(--fg-dim)] transition-colors leading-relaxed truncate"
                  >
                    · {ex}
                  </button>
                ))}
              </div>
            </div>

            {/* Founder ID + Submit */}
            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <div className="flex flex-col gap-2">
                <label className="site-label">Founder ID</label>
                <input
                  value={founderId}
                  onChange={(e) => setFounderId(e.target.value)}
                  className="site-input px-4 py-3 text-sm text-white"
                  placeholder="founder_001"
                  disabled={loading}
                />
              </div>
              <button
                type="submit"
                disabled={loading || !instruction.trim()}
                className="site-btn site-btn-primary px-6 self-end"
              >
                {loading ? "Launching…" : "Launch Astra"}
                <span aria-hidden="true">→</span>
              </button>
            </div>

            {error && (
              <p className="rounded-2xl border border-red-900/70 bg-red-950/30 px-4 py-3 text-sm text-red-300">
                {error}
              </p>
            )}
          </form>
        </div>
      </section>

      <div className="site-rule" />

      {/* Process */}
      <section id="process" className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
        <div className="flex flex-col gap-5">
          <div className="eyebrow">The flow</div>
          <h2>
            One instruction.<br />
            <span className="display-italic">A full founding stack.</span>
          </h2>
          <p className="lede">
            Astra turns a plain-English goal into a coordinated work plan across 8 specialist agents — each executing real actions, not descriptions.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {[
            { step: "01", title: "Research", desc: "Market sizing, competitors, TAM/SAM/SOM before you spend a dollar." },
            { step: "02", title: "Build & Deploy", desc: "GitHub repo → Supabase DB → Claude Code scaffold → Vercel deploy. Live URL." },
            { step: "03", title: "Launch", desc: "Landing page, campaigns, social content — all from the same strategy." },
            { step: "04", title: "Operate", desc: "Legal docs, investor outreach, Linear tickets, and persistent memory." },
          ].map((item) => (
            <article key={item.step} className="site-card site-card-soft p-5">
              <div className="site-label">{item.step}</div>
              <h3 className="mt-3 text-[26px] leading-none">{item.title}</h3>
              <p className="mt-4 text-sm leading-6 text-[var(--fg-dim)]">{item.desc}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Agents grid */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { icon: "🔬", label: "Research", desc: "TAM, SAM, SOM, competitors, customer profile." },
          { icon: "🌐", label: "Web", desc: "Landing pages + full app deploys with Vercel + Supabase." },
          { icon: "📢", label: "Marketing", desc: "Campaigns, social content, outreach from one strategy." },
          { icon: "⚙️", label: "Technical", desc: "GitHub → Supabase → Claude Code → Vercel. Live." },
          { icon: "⚖️", label: "Legal", desc: "Entity setup, policies, compliance drafting." },
          { icon: "🚀", label: "Ops", desc: "Fundraising docs, investor outreach, scheduling." },
          { icon: "🤝", label: "Sales", desc: "Lead finding, enrichment, outreach sequences." },
          { icon: "🎨", label: "Design", desc: "Wireframes, color palettes, logo briefs, specs." },
        ].map((item) => (
          <div key={item.label} className="site-card site-card-soft p-5">
            <span className="text-2xl">{item.icon}</span>
            <p className="mt-4 text-sm font-medium tracking-wide text-white">{item.label}</p>
            <p className="mt-2 text-xs leading-5 text-[var(--fg-dim)]">{item.desc}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
