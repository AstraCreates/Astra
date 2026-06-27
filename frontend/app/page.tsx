"use client";

import { useState, useEffect, useRef } from "react";
import { signIn } from "next-auth/react";
import Link from "next/link";
import LiquidGlass from "@/components/LiquidGlass";
import SpaceEnv from "@/components/SpaceEnv";
import { useDevUser } from "@/lib/use-dev-user";

// ─── content ─────────────────────────────────────────────────────────────────

const FLOW_STEPS = [
  { n: "01", action: "Goal",      detail: "Describe the outcome you want — a company launch, a market map, a product build. Plain English." },
  { n: "02", action: "Plan",      detail: "The orchestrator breaks your goal into an execution plan and routes work to the right specialists." },
  { n: "03", action: "Run",       detail: "Agents execute with shared memory, live tool access, and approval gates on every risky action." },
  { n: "04", action: "Stream",    detail: "Watch every agent action in real time via SSE — no black box, no waiting for a final answer." },
  { n: "05", action: "Collect",   detail: "Deliverables land in your vault: source files, legal docs, deployed sites, reports, PDFs." },
  { n: "06", action: "Operate",   detail: "Persistent memory, missions, and a workboard keep your company context alive between runs." },
];

const AGENTS = [
  { name: "Research",         role: "Market sizing, TAM/SAM/SOM, competitor intelligence, pricing benchmarks, regulatory landscape, go/no-go." },
  { name: "Legal",            role: "LLC formation via Computer Use, EIN retrieval, NDAs, privacy policy, terms, founder agreements, compliance." },
  { name: "Web",              role: "Site generation, copy, waitlist deployment, GitHub repo, Vercel deploy, domain setup, SEO metadata." },
  { name: "Technical",        role: "Product scaffolding, 20–30 source files, Supabase integration, Vercel CI, Linear tickets, Notion workspace." },
  { name: "Design",           role: "Wireframes, color palettes, logo briefs, UX direction, component specs, brand identity assets." },
  { name: "Marketing",        role: "Email sequences, social content, Reels scripts, TikTok hooks, Meta ad copy, campaign briefs." },
  { name: "SEO",              role: "Technical SEO audit, keyword strategy, meta tags, structured data, content calendar, link-building plan." },
  { name: "Sales",            role: "Lead enrichment via Apollo/Hunter, outreach sequences, inbox warming, CRM setup, investor emails." },
  { name: "Outreach",         role: "Prospecting lists, personalized cold email, follow-up cadences, LinkedIn sequences, reply handling." },
  { name: "Finance",          role: "Financial modeling, fundraise deck support, cap table, runway projections, investor-ready data room." },
  { name: "Ops",              role: "SOPs, weekly digests, calendar coordination, task scheduling, decision logs, workboard management." },
  { name: "Infrastructure",   role: "Cloud setup, CI/CD pipelines, Docker configuration, monitoring, environment provisioning." },
];

const INTEGRATIONS = [
  "Stripe", "Vercel", "GitHub", "Notion", "Supabase",
  "Apollo", "Hunter", "Klaviyo", "Twilio", "Composio",
  "Square", "Printful", "Yelp", "Lemon Squeezy", "Resend",
];

const PRICING = [
  {
    label: "Launch",
    sublabel: "Ship your first product",
    price: "$20",
    note: "/mo",
    alt: "1,000,000 credits · monthly grant",
    items: [
      "Access to pre-built agent stacks",
      "3rd-party platform integrations",
      "Financial modelling & tracking",
      "1 workspace · 1 seat",
      "Up to 3 concurrent agent runs",
      "Live preview deploys",
      "Knowledge map (lite)",
      "30-day credit rollover",
      "Email support",
    ],
    featured: false,
  },
  {
    label: "Build",
    sublabel: "Run the whole company on autopilot",
    price: "$75",
    note: "/mo",
    alt: "5,000,000 credits · priority queue",
    items: [
      "Everything in Launch, plus:",
      "Create custom agent stacks",
      "Automated entity formation",
      "Registered agent access",
      "3 seats",
      "API + webhook access",
      "Custom domains on deploys",
      "Auto-generated legal docs",
      "Priority support · 50% off extra usage",
    ],
    featured: true,
  },
  {
    label: "Scale",
    sublabel: "Operate a team across multiple ventures",
    price: "$200",
    note: "/mo",
    alt: "20,000,000 credits · white-glove",
    items: [
      "Everything in Build, plus:",
      "Teams & orgs",
      "Custom agent creation",
      "Full Company Brain (GraphRAG)",
      "Unlimited seats · role-based access",
      "SSO + audit log",
      "Dedicated success contact + SLA",
      "50% off all extra usage",
    ],
    featured: false,
  },
];

const FAQS = [
  {
    q: "How is this different from using ChatGPT or another AI assistant?",
    a: "Astra doesn't respond to prompts — it creates durable runs. Your goal becomes a session with a plan, specialist agents executing in parallel, live streaming progress, and real artifacts stored in a vault. It's infrastructure, not a chat window.",
  },
  {
    q: "What are approval gates?",
    a: "Any action Astra considers risky — deploying to production, sending emails, filing legal documents, changing account settings — pauses and waits for your explicit approval before proceeding. You stay in control.",
  },
  {
    q: "What is the Agent Stack Platform?",
    a: "It lets you compile a repeatable business outcome (e.g. 'launch a SaaS MVP') into a deployable AI department package: defined lanes, connectors, approval gates, quality checks, and an execution blueprint. Run it once or productize it.",
  },
  {
    q: "What integrations are live?",
    a: "Stripe, Vercel, GitHub, Notion, Supabase, Apollo, Hunter, Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy, Resend, and Composio. Agents can take live actions inside these systems — not just read data.",
  },
  {
    q: "What is shared memory?",
    a: "Every run writes to a persistent context store. Agents read each other's outputs. When the session ends, the full record — decisions, files, conversations — transfers to your company brain for future runs to reference.",
  },
];

const HERO_TERMINAL = [
  { key: "goal",      val: '"Launch a B2B musician collaboration platform"' },
  { key: "plan",      val: "11 agents · 6 phases · approval gate on LLC filing" },
  { key: "research",  val: "TAM $2.4B · 6 competitors mapped · go/no-go: launch" },
  { key: "legal",     val: "Resonant Technologies LLC filed · EIN retrieved" },
  { key: "web",       val: "resonant.fm live · GitHub repo · SEO complete" },
  { key: "technical", val: "24 source files · Next.js + Supabase + Clerk" },
  { key: "status",    val: "✓  done · 14 min 22 sec · $0.09 · 6 artifacts in vault" },
];

const EXAMPLE_TERMINAL = [
  { key: "→ research",  val: "TAM $2.4B · SAM $480M · 6 competitors · pricing $29–$199/mo · go: launch" },
  { key: "→ legal",     val: "Resonant Technologies LLC filed · EIN 84-XXXXXXX · NDA.pdf · FounderAgreement.pdf" },
  { key: "→ web",       val: "resonant.fm live · /waitlist + /pricing · github.com/resonantfm · SEO meta done" },
  { key: "→ technical", val: "24 source files · Next.js + Supabase + Clerk · 6 Linear tickets · Notion workspace" },
  { key: "→ design",    val: "Brand palette · logo brief · 3 wireframes · UX direction doc" },
  { key: "→ marketing", val: "3 Reels scripts · 2 TikTok hooks · Meta ad copy × 4 · 5-email drip sequence" },
  { key: "→ sales",     val: "50 leads enriched via Apollo · 3 outreach sequences · CRM template ready" },
  { key: "→ ops",       val: "SOP deck · weekly digest template · decision log · workboard updated" },
];

// ─── component ───────────────────────────────────────────────────────────────

export default function Home() {
  const { isSignedIn } = useDevUser();
  const agentListRef = useRef<HTMLDivElement>(null);
  const [openFaq, setOpenFaq]   = useState<number | null>(null);

  // GSAP + Lenis scroll animations
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const [{ default: gsap }, { ScrollTrigger }, { default: Lenis }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
        import("lenis"),
      ]);

      if (cancelled) return;
      gsap.registerPlugin(ScrollTrigger);

      const lenis = new (Lenis as any)({
        duration: 1.4,
        easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        touchMultiplier: 2,
      });
      const rafFn = (time: number) => lenis.raf(time * 1000);
      gsap.ticker.add(rafFn);
      gsap.ticker.lagSmoothing(0);
      lenis.on("scroll", (ScrollTrigger as any).update);

      // Hero entrance
      gsap.from(".lp-hero-left > *", { y: 28, opacity: 0, duration: 0.8, stagger: 0.1, ease: "power3.out", delay: 0.2 });
      gsap.from(".lp-hero-right",     { x: 24, opacity: 0, duration: 1.0, ease: "power3.out", delay: 0.4 });

      // Section reveals
      document.querySelectorAll<HTMLElement>(".lp-section-h2").forEach(el => {
        gsap.from(el, { y: 40, opacity: 0, duration: 0.85, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 86%" } });
      });
      document.querySelectorAll<HTMLElement>(".lp-section-p").forEach(el => {
        gsap.from(el, { y: 22, opacity: 0, duration: 0.7,  ease: "power3.out", delay: 0.08, scrollTrigger: { trigger: el, start: "top 89%" } });
      });

      gsap.from(".lp-flow-step", { y: 32, opacity: 0, duration: 0.65, stagger: 0.09, ease: "power2.out", scrollTrigger: { trigger: ".lp-flow-grid", start: "top 82%" } });
      gsap.from(".lp-example .lp-example-right", { x: 40, opacity: 0, rotateY: -6, duration: 1.0, ease: "power3.out", transformOrigin: "0% 50%", scrollTrigger: { trigger: ".lp-example", start: "top 80%" } });
      gsap.from(".lp-memory-check", { x: -20, opacity: 0, duration: 0.55, stagger: 0.08, ease: "power2.out", scrollTrigger: { trigger: ".lp-memory-checks", start: "top 82%" } });
      gsap.from(".lp-integration-tag", { scale: 0.88, opacity: 0, duration: 0.5, stagger: 0.04, ease: "power2.out", scrollTrigger: { trigger: ".lp-integration-wrap", start: "top 82%" } });

      document.querySelectorAll<HTMLElement>(".lp-pricing-grid > *").forEach((card, i) => {
        gsap.from(card, { y: 55, opacity: 0, scale: 0.94, rotateX: 10, duration: 0.9, ease: "power3.out", delay: i * 0.13, transformOrigin: "50% 0%", scrollTrigger: { trigger: ".lp-pricing-grid", start: "top 82%" } });
      });
      gsap.from(".lp-cohort-card",   { y: 44, opacity: 0, scale: 0.96, duration: 0.9,  ease: "power3.out", scrollTrigger: { trigger: ".lp-cohort-card",    start: "top 84%" } });
      gsap.from(".lp-faq-item",      { y: 16, opacity: 0, duration: 0.5, stagger: 0.06, ease: "power2.out", scrollTrigger: { trigger: ".lp-faq-list",        start: "top 84%" } });
      gsap.from(".lp-close-h2",      { y: 50, opacity: 0, duration: 0.9,  ease: "power3.out", scrollTrigger: { trigger: ".lp-close", start: "top 82%" } });
      gsap.from(".lp-close-p",       { y: 24, opacity: 0, duration: 0.7,  ease: "power3.out", delay: 0.12, scrollTrigger: { trigger: ".lp-close", start: "top 82%" } });
    })();

    return () => { cancelled = true; };
  }, []);

  // Agent list stagger reveal
  useEffect(() => {
    const el = agentListRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { el.setAttribute("data-revealed", ""); io.disconnect(); } },
      { threshold: 0.05 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const CtaButtons = () => isSignedIn ? (
    <Link href="/dashboard" className="site-btn site-btn-primary">Go to dashboard →</Link>
  ) : (
    <>
      <button className="site-btn site-btn-primary" onClick={() => signIn("google", { callbackUrl: "/dashboard" })}>
        Start building →
      </button>
      <button className="site-btn site-btn-ghost" onClick={() => signIn("google", { callbackUrl: "/dashboard" })}>
        Sign in
      </button>
    </>
  );

  return (
    <>
      <SpaceEnv />

      <div style={{ position: "relative", zIndex: 1 }}>

        {/* ── Nav ───────────────────────────────────────────────── */}
        <nav className="lp-nav">
          <div className="lp-nav-inner">
            <div className="lp-nav-brand">
              <svg viewBox="0 0 320 295" className="lp-nav-mark" aria-hidden="true">
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(0, 160, 175)" />
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(120, 160, 175)" />
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(240, 160, 175)" />
              </svg>
              <span className="lp-nav-wordmark">ASTRA</span>
            </div>
            <div className="lp-nav-actions">
              <CtaButtons />
            </div>
          </div>
        </nav>

        {/* ── Hero ──────────────────────────────────────────────── */}
        <section className="lp-hero">
          <div className="lp-hero-left">
            <h1 className="lp-hero-h1">
              You bring the idea.<br />
              <span style={{ color: "var(--brand-dim)" }}>Astra handles everything else.</span>
            </h1>
            <p className="lp-hero-lede">
              Entity formation, market research, legal documents, live deployments,
              and customer acquisition — handled by twelve specialist agents working
              in parallel, every action visible, every deliverable in your vault.
            </p>
            <div className="lp-hero-cta">
              <CtaButtons />
            </div>
            <p className="lp-stats-inline">12+ specialist agents · live SSE stream · approval gates · from $20/mo</p>
          </div>

          <div className="lp-hero-right">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-terminal-card">
                {HERO_TERMINAL.map((row, i) => (
                  <div key={row.key} className="lp-terminal-row" style={i === HERO_TERMINAL.length - 1 ? { marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" } : undefined}>
                    <span className="lp-terminal-key">{row.key}</span>
                    <span className="lp-terminal-val" style={i === HERO_TERMINAL.length - 1 ? { color: "var(--sg-color)" } : undefined}>{row.val}</span>
                  </div>
                ))}
              </div>
            </LiquidGlass>
          </div>
        </section>

        {/* ── How it works ──────────────────────────────────────── */}
        <section className="lp-section">
          <h2 className="lp-section-h2">How a run works</h2>
          <p className="lp-section-p">Six phases. Fully orchestrated. Every step visible.</p>
          <div className="lp-flow-grid">
            {FLOW_STEPS.map(step => (
              <div key={step.n} className="lp-flow-step">
                <span className="lp-flow-n">{step.n}</span>
                <span className="lp-flow-action">{step.action}</span>
                <span className="lp-flow-detail">{step.detail}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ── Example run ───────────────────────────────────────── */}
        <section className="lp-section lp-example">
          <div className="lp-example-left">
            <h2 className="lp-section-h2">One goal.<br />This is what runs.</h2>
            <p className="lp-section-p" style={{ marginBottom: 0 }}>
              Input: <em>"Launch a B2B musician collaboration platform."</em>
              {" "}Eight agents, 14 minutes, six vault artifacts.
            </p>
          </div>
          <div className="lp-example-right">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-terminal-card">
                <div style={{ marginBottom: 14, paddingBottom: 14, borderBottom: "1px solid var(--line)", fontFamily: "var(--font-jetbrains-mono), monospace", fontSize: 11, color: "var(--text-3)" }}>
                  $ astra run <span style={{ color: "var(--sg-color)" }}>"B2B musician collaboration platform"</span>
                </div>
                {EXAMPLE_TERMINAL.map(row => (
                  <div key={row.key} className="lp-terminal-row">
                    <span className="lp-terminal-key">{row.key}</span>
                    <span className="lp-terminal-val">{row.val}</span>
                  </div>
                ))}
                <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)", fontFamily: "var(--font-jetbrains-mono), monospace", fontSize: 11, color: "var(--sg-color)" }}>
                  ✓ 8 agents · 14 min 22 sec · $0.09 · 6 artifacts
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        {/* ── Specialist bench ──────────────────────────────────── */}
        <section className="lp-section">
          <div className="lp-agents-head">
            <h2 className="lp-section-h2">The full specialist bench.</h2>
            <p className="lp-section-p">Every agent has a defined role, dedicated tools, and access to the shared company brain.</p>
          </div>
          <div ref={agentListRef} className="lp-agent-list">
            {AGENTS.map((agent, i) => (
              <div
                key={agent.name}
                className="lp-agent-row"
                style={{ "--row-i": i } as React.CSSProperties}
              >
                <span className="lp-agent-label">{agent.name}</span>
                <span className="lp-agent-outputs-text">{agent.role}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ── Company brain ─────────────────────────────────────── */}
        <section className="lp-section lp-two-col">
          <div>
            <h2 className="lp-section-h2">Company brain.<br />Persistent by default.</h2>
            <p className="lp-section-p" style={{ marginBottom: 0 }}>
              Every run writes to a durable context store. Agents read each other's outputs.
              Sessions become digests. Digests become workboards. Your company accumulates
              memory the way a team does — across every run, every agent, every decision.
            </p>
          </div>
          <LiquidGlass contentStyle={{ padding: 0 }}>
            <div className="lp-memory-checks">
              {[
                "Shared context across all agents",
                "Session digests + workboards",
                "Subteam + company reports",
                "Missions and persistent goals",
                "Full history on run completion",
              ].map(item => (
                <div key={item} className="lp-memory-check">
                  <span className="lp-memory-tick">✓</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </LiquidGlass>
        </section>

        {/* ── Integrations ──────────────────────────────────────── */}
        <section className="lp-section">
          <h2 className="lp-section-h2">Agents that actually act.</h2>
          <p className="lp-section-p">
            Not summaries of what you could do. Live actions inside real systems —
            with your approval on anything irreversible.
          </p>
          <div className="lp-integration-wrap">
            {INTEGRATIONS.map(name => (
              <span key={name} className="lp-integration-tag">{name}</span>
            ))}
          </div>
        </section>

        {/* ── Pricing ───────────────────────────────────────────── */}
        <section className="lp-section lp-perspective">
          <h2 className="lp-section-h2">Simple pricing.</h2>
          <p className="lp-section-p">A full-stack ops team costs $15,000/month to hire. Astra starts at $40.</p>
          <div className="lp-pricing-grid">
            {PRICING.map(plan => (
              <LiquidGlass
                key={plan.label}
                contentStyle={{ padding: 0 }}
                style={plan.featured ? { border: "1px solid oklch(59% 0.26 250 / 0.35)" } : undefined}
              >
                <div className="lp-pricing-card">
                  <div>
                    <div className={plan.featured ? "lp-price-label lp-price-label-featured" : "lp-price-label"}>{plan.label}</div>
                    <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 3 }}>{plan.sublabel}</div>
                  </div>
                  <div>
                    <div className={plan.featured ? "lp-price-amount lp-price-amount-featured" : "lp-price-amount"}>
                      {plan.price}<span style={{ fontSize: "0.38em", fontWeight: 400, letterSpacing: 0, color: "var(--text-3)", verticalAlign: "middle", marginLeft: 2 }}>{plan.note}</span>
                    </div>
                  </div>
                  <div className="lp-price-alt">{plan.alt}</div>
                  <ul className="lp-price-items">
                    {plan.items.map((item, i) => (
                      <li key={item} style={i === 0 && plan.featured ? { color: "var(--brand)", fontWeight: 500 } : undefined}>{item}</li>
                    ))}
                  </ul>
                </div>
              </LiquidGlass>
            ))}
          </div>
          <p className="lp-pricing-note">Usage-based credits meter agent work · every plan includes a monthly grant · extra usage billed at discounted rates</p>
        </section>

        {/* ── Founding cohort ───────────────────────────────────── */}
        <section className="lp-section">
          <LiquidGlass contentStyle={{ padding: 0 }}>
            <div className="lp-cohort-card">
              <span className="lp-agent-label" style={{ letterSpacing: "0.14em" }}>Founding Cohort</span>
              <h2 className="lp-section-h2" style={{ textAlign: "center", margin: 0 }}>Limited to 25 founders.</h2>
              <p style={{ fontSize: 15, lineHeight: 1.7, color: "var(--text)", maxWidth: "46ch", margin: 0 }}>
                The first cohort gets hands-on onboarding, priority support, and a direct line to the team.
                We ask for a brief case study at 90 days. Cohort one opens June 1st.
              </p>
              <div className="lp-hero-cta" style={{ justifyContent: "center" }}>
                <CtaButtons />
              </div>
            </div>
          </LiquidGlass>
        </section>

        {/* ── FAQ ───────────────────────────────────────────────── */}
        <section className="lp-section">
          <h2 className="lp-section-h2">Questions.</h2>
          <div className="lp-faq-list">
            {FAQS.map((faq, i) => (
              <div key={i} className="lp-faq-item">
                <button
                  className="lp-faq-q"
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  aria-expanded={openFaq === i}
                >
                  <span>{faq.q}</span>
                  <span className="lp-faq-icon" aria-hidden="true">{openFaq === i ? "−" : "+"}</span>
                </button>
                {openFaq === i && <p className="lp-faq-a">{faq.a}</p>}
              </div>
            ))}
          </div>
        </section>

        {/* ── Final CTA ─────────────────────────────────────────── */}
        <section className="lp-close">
          <h2 className="lp-close-h2">
            You bring the idea.<br />
            <span style={{ color: "var(--brand-dim)" }}>Astra handles everything else.</span>
          </h2>
          <p className="lp-close-p">From first prompt to launchable company.</p>
          <div className="lp-hero-cta" style={{ justifyContent: "center" }}>
            <CtaButtons />
          </div>
        </section>

        {/* ── Footer ────────────────────────────────────────────── */}
        <footer className="lp-footer-line">
          <span>© 2026 Astra Technologies Inc.</span>
          <Link href="/terms">Terms</Link>
          <Link href="/privacy">Privacy</Link>
          <a href="mailto:hello@astracreates.com">hello@astracreates.com</a>
        </footer>

      </div>
    </>
  );
}
