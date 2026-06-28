"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import LiquidGlass from "@/components/LiquidGlass";
import SpaceEnv from "@/components/SpaceEnv";
import { useDevUser } from "@/lib/use-dev-user";

type TerminalRow = { key: string; val: string };
type CaseStudy = {
  label: string;
  title: string;
  summary: string;
  time: string;
  agents: string;
  outputs: string[];
};

const HERO_METRICS = [
  { label: "Specialist agents", value: "12 lanes" },
  { label: "Approval model", value: "Visible by default" },
  { label: "Outputs", value: "Deploys, docs, ops" },
];

const FLOW_STEPS = [
  { n: "01", action: "Goal", detail: "Describe the business outcome in plain English." },
  { n: "02", action: "Plan", detail: "Astra turns the ask into a run blueprint with the right specialist lanes." },
  { n: "03", action: "Run", detail: "Agents execute in parallel with shared memory and live tool access." },
  { n: "04", action: "Approve", detail: "Risky actions pause for review instead of slipping through a hidden chain." },
  { n: "05", action: "Collect", detail: "Files, deploys, documents, and decisions stay attached to the same run." },
  { n: "06", action: "Operate", detail: "The company brain keeps the next run grounded in what already happened." },
];

const FEATURED_TERMINAL: TerminalRow[] = [
  { key: "goal", val: "\"Launch a B2B musician collaboration platform\"" },
  { key: "plan", val: "research · legal · web · product · growth · ops" },
  { key: "research", val: "TAM $2.4B · 6 competitors mapped · positioning chosen" },
  { key: "legal", val: "LLC filed · EIN retrieved · founder docs stored" },
  { key: "web", val: "waitlist site live · repo connected · deploy healthy" },
  { key: "growth", val: "launch emails, hooks, and SEO brief generated" },
  { key: "status", val: "8 agents · 14 min 22 sec · 6 artifacts in vault" },
];

const FEATURED_OUTPUTS = [
  "Live landing page and waitlist funnel",
  "Market map and pricing memo",
  "Founder docs and policy stack",
  "Product scaffold with deployment wiring",
];

const CASE_STUDIES: CaseStudy[] = [
  {
    label: "B2B SaaS",
    title: "Launch an early-stage SaaS company with product, legal, and GTM moving together.",
    summary: "Astra handles the positioning work, launch site, repo scaffolding, founder docs, and first acquisition loop in one visible run.",
    time: "14 min 22 sec",
    agents: "8 agents",
    outputs: ["TAM and competitor memo", "Landing page + pricing page", "Founder agreement + NDA", "Launch checklist"],
  },
  {
    label: "Creator Commerce",
    title: "Build a storefront, offer ladder, and campaign system around a creator brand.",
    summary: "The run packages products, drafts the merchandising and email system, and hands back a launch-week operating kit instead of notes.",
    time: "11 min 05 sec",
    agents: "7 agents",
    outputs: ["Storefront copy", "Checkout + fulfillment wiring", "5-email sequence", "Creative brief bank"],
  },
  {
    label: "Local Services",
    title: "Stand up a city-first services business with outreach, booking, and review loops.",
    summary: "Astra defines the offer, builds the booking path, seeds prospecting lists, and creates the SOP backbone needed to actually run it.",
    time: "16 min 41 sec",
    agents: "9 agents",
    outputs: ["Booking funnel", "Referral outreach list", "Review request workflow", "Dispatch SOP"],
  },
];

const AGENTS = [
  { name: "Research", role: "Market sizing, competitor mapping, pricing benchmarks, and category framing." },
  { name: "Legal", role: "Entity filing, EIN retrieval, NDAs, policies, compliance, and founder docs." },
  { name: "Web", role: "Launch sites, waitlists, storefronts, deploys, domains, analytics, and SEO metadata." },
  { name: "Technical", role: "Product scaffolding, database wiring, integrations, tickets, and delivery structure." },
  { name: "Design", role: "Wireframes, visual systems, product packaging, brand assets, and interface direction." },
  { name: "Marketing", role: "Email sequences, hooks, campaign briefs, launch calendars, and offer messaging." },
  { name: "Sales", role: "Lead enrichment, outbound sequencing, CRM setup, and investor or partner outreach." },
  { name: "Finance", role: "Margin models, runway views, pricing math, and investor-ready planning." },
  { name: "Ops", role: "SOPs, workboards, approval paths, recurring digests, and company coordination." },
  { name: "Infrastructure", role: "Cloud setup, CI/CD, monitoring, environments, and production hygiene." },
];

const SYSTEM_PANELS = [
  {
    label: "Control",
    title: "Every irreversible action stays reviewable.",
    text: "Deploys, filings, outbound email, billing changes, and account actions do not disappear into tool chatter. Astra pauses for explicit approval.",
  },
  {
    label: "Memory",
    title: "Runs compound into a real operating context.",
    text: "Outputs become shared memory, workboards, and decision history so the next run starts with actual context instead of another blank prompt.",
  },
  {
    label: "Reach",
    title: "The system acts inside the stack that already matters.",
    text: "GitHub, Vercel, Stripe, Notion, Supabase, Apollo, Twilio, Resend, and other tools become action surfaces, not passive references.",
  },
];

const MEMORY_CHECKS = [
  "Shared context across specialist lanes",
  "Run digests and company workboards",
  "Artifacts preserved with source-of-truth history",
  "Mission memory carried forward into future runs",
];

const INTEGRATIONS = [
  "GitHub",
  "Vercel",
  "Stripe",
  "Notion",
  "Supabase",
  "Apollo",
  "Hunter",
  "Klaviyo",
  "Twilio",
  "Resend",
];

const VALUE_SNAPSHOTS = [
  {
    label: "Typical human stack",
    value: "$82,400 / mo",
    detail: "Cross-functional launch team across research, legal, product, web, growth, and ops.",
  },
  {
    label: "Astra scale plan",
    value: "$200 / mo",
    detail: "20,000,000 monthly credits with org support, memory depth, and priority execution.",
  },
  {
    label: "Typical launch speed",
    value: "< 1 day",
    detail: "The run can research, draft, ship, and package outputs in one coordinated pass.",
  },
  {
    label: "Typical human-team launch",
    value: "43 days",
    detail: "Coordination overhead, handoffs, and context loss stretch the same work across weeks.",
  },
];

const PRICING = [
  {
    label: "Launch",
    sublabel: "Ship the first company version",
    price: "$20",
    note: "/mo",
    alt: "1,000,000 credits included",
    items: [
      "Pre-built launch agent stacks",
      "Core third-party integrations",
      "1 workspace · 1 seat",
      "Up to 3 concurrent runs",
      "Live preview deploys",
    ],
    featured: false,
  },
  {
    label: "Build",
    sublabel: "Run the whole business layer",
    price: "$75",
    note: "/mo",
    alt: "5,000,000 credits included",
    items: [
      "Custom stacks and reusable workflows",
      "Entity formation and legal automation",
      "3 seats with shared company memory",
      "API, webhooks, and custom domains",
      "Priority support and discounted overage",
    ],
    featured: true,
  },
  {
    label: "Scale",
    sublabel: "Operate across ventures or teams",
    price: "$200",
    note: "/mo",
    alt: "20,000,000 credits included",
    items: [
      "Unlimited seats with role controls",
      "Deep company brain and audit log",
      "Dedicated support and SLA coverage",
      "Org-level workboards and reporting",
      "Best-rate usage expansion",
    ],
    featured: false,
  },
];

const FAQS = [
  {
    q: "How is this different from a normal AI assistant?",
    a: "Astra is structured around runs, specialist lanes, approvals, and durable artifacts. It is closer to an operating layer for company work than a chat tab that gives suggestions.",
  },
  {
    q: "What actually comes back from a run?",
    a: "Depending on the outcome, you get deploys, repos, policy docs, campaign systems, research packs, SOPs, and a preserved history of what the agents did.",
  },
  {
    q: "Can I keep control over risky actions?",
    a: "Yes. Production deploys, legal filings, outbound communications, and similar irreversible steps are meant to pause for approval before execution.",
  },
  {
    q: "Does the system remember prior work?",
    a: "Yes. Astra carries forward run memory, artifacts, decisions, and workboard context so the next execution starts with history instead of a fresh prompt.",
  },
];

export default function Home() {
  const { isSignedIn } = useDevUser();
  const router = useRouter();
  const agentListRef = useRef<HTMLDivElement>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

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

      const lenis = new (Lenis as { new(args: Record<string, unknown>): { raf: (time: number) => void; on: (name: string, handler: () => void) => void } })({
        duration: 1.25,
        easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        touchMultiplier: 1.8,
      });

      const rafFn = (time: number) => lenis.raf(time * 1000);
      gsap.ticker.add(rafFn);
      gsap.ticker.lagSmoothing(0);
      lenis.on("scroll", (ScrollTrigger as { update: () => void }).update);

      gsap.from(".lp-hero-left > *", {
        y: 28,
        opacity: 0,
        duration: 0.82,
        stagger: 0.08,
        ease: "power3.out",
        delay: 0.12,
      });
      gsap.from(".lp-hero-panel", {
        x: 28,
        opacity: 0,
        duration: 0.95,
        ease: "power3.out",
        delay: 0.24,
      });

      document.querySelectorAll<HTMLElement>(".lp-section-h2, .lp-section-p").forEach((el) => {
        gsap.from(el, {
          y: 24,
          opacity: 0,
          duration: 0.72,
          ease: "power3.out",
          scrollTrigger: { trigger: el, start: "top 88%" },
        });
      });

      gsap.from(".lp-flow-step", {
        y: 24,
        opacity: 0,
        duration: 0.56,
        stagger: 0.06,
        ease: "power2.out",
        scrollTrigger: { trigger: ".lp-run-grid", start: "top 84%" },
      });

      [".lp-run-panel", ".lp-case-card", ".lp-platform-card", ".lp-value-card", ".lp-price-card", ".lp-faq-card"].forEach((selector) => {
        gsap.from(selector, {
          y: 26,
          opacity: 0,
          duration: 0.68,
          stagger: 0.07,
          ease: "power3.out",
          scrollTrigger: { trigger: selector, start: "top 88%" },
        });
      });
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = agentListRef.current;
    if (!el) return;

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.setAttribute("data-revealed", "");
          io.disconnect();
        }
      },
      { threshold: 0.08 },
    );

    io.observe(el);
    return () => io.disconnect();
  }, []);

  const readySignedIn = hydrated && isSignedIn;

  const handlePrimaryCta = () => {
    if (readySignedIn) {
      router.push("/dashboard");
      return;
    }

    signIn("google", { callbackUrl: "/dashboard" });
  };

  return (
    <>
      <SpaceEnv />

      <div className="lp-page" style={{ position: "relative", zIndex: 1 }}>
        <nav className="lp-nav">
          <div className="lp-nav-inner lp-nav-inner-minimal">
            <div className="lp-nav-brand">
              <svg viewBox="0 0 320 295" className="lp-nav-mark" aria-hidden="true">
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(0, 160, 175)" />
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(120, 160, 175)" />
                <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(240, 160, 175)" />
              </svg>
              <span className="lp-nav-wordmark">ASTRA</span>
            </div>

            <div className="lp-nav-actions">
              <button className="site-btn site-btn-primary lp-primary-cta" onClick={handlePrimaryCta}>
                {readySignedIn ? "Go to dashboard ->" : "Start a run ->"}
              </button>
            </div>
          </div>
        </nav>

        <section className="lp-hero">
          <div className="lp-hero-left">
            <span className="lp-eyebrow">Operating system for launching companies</span>
            <h1 className="lp-hero-h1">
              Astra launches the company,
              <br />
              <span style={{ color: "var(--lp-brand-dim)" }}>not just the copy.</span>
            </h1>
            <p className="lp-hero-lede">
              Give it a business outcome and it coordinates research, legal, product, deploys,
              growth, and ops as one visible run with approvals, memory, and real deliverables.
            </p>

            <div className="lp-hero-cta">
              <button className="site-btn site-btn-primary lp-primary-cta" onClick={handlePrimaryCta}>
                {readySignedIn ? "Open dashboard ->" : "Start with Astra ->"}
              </button>
              {!readySignedIn && <a href="#pricing" className="lp-text-link">See pricing</a>}
            </div>

            <div className="lp-hero-metrics">
              {HERO_METRICS.map((item) => (
                <div key={item.label} className="lp-hero-metric">
                  <span className="lp-hero-metric-label">{item.label}</span>
                  <strong className="lp-hero-metric-value">{item.value}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="lp-hero-right">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-hero-panel">
                <div className="lp-hero-panel-head">
                  <span className="lp-profile-kicker">Featured run</span>
                  <span className="lp-profile-duration">Launch preview</span>
                </div>

                <div className="lp-terminal-card">
                  <div className="lp-terminal-prompt">
                    $ astra run <span style={{ color: "var(--sg-color)" }}>"Launch a B2B musician collaboration platform."</span>
                  </div>
                  {FEATURED_TERMINAL.map((row, i) => (
                    <div
                      key={row.key}
                      className="lp-terminal-row"
                      style={i === FEATURED_TERMINAL.length - 1 ? { marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" } : undefined}
                    >
                      <span className="lp-terminal-key">{row.key}</span>
                      <span className="lp-terminal-val" style={i === FEATURED_TERMINAL.length - 1 ? { color: "var(--sg-color)" } : undefined}>
                        {row.val}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="lp-hero-output-block">
                  <div className="lp-hero-output-copy">
                    <h3 className="lp-platform-subtitle">What comes back</h3>
                    <p className="lp-control-copy">
                      Not advice in a chat window. A live deploy, company documents, launch systems,
                      and a preserved run history you can keep operating from.
                    </p>
                  </div>
                  <ul className="lp-profile-output-list">
                    {FEATURED_OUTPUTS.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section lp-run-grid">
          <div className="lp-run-story">
            <span className="lp-eyebrow">Execution model</span>
            <h2 className="lp-section-h2">One goal. One run. No dead handoffs.</h2>
            <p className="lp-section-p">
              Astra is designed to feel like one operating system instead of a relay race between prompts,
              teammates, tabs, and forgotten context.
            </p>

            <div className="lp-flow-grid">
              {FLOW_STEPS.map((step) => (
                <div key={step.n} className="lp-flow-step">
                  <span className="lp-flow-n">{step.n}</span>
                  <span className="lp-flow-action">{step.action}</span>
                  <span className="lp-flow-detail">{step.detail}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="lp-run-stack">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-run-panel">
                <span className="lp-profile-kicker">Run receipt</span>
                <h3 className="lp-platform-subtitle">The entire outcome stays attached to the run.</h3>
                <p className="lp-control-copy">
                  Decisions, files, approvals, deploys, and summaries stay in one timeline so there is no mystery about what happened or what is ready next.
                </p>

                <div className="lp-run-proof-grid">
                  <div className="lp-run-proof-item">
                    <span className="lp-run-proof-label">Visibility</span>
                    <strong>Live status by lane</strong>
                  </div>
                  <div className="lp-run-proof-item">
                    <span className="lp-run-proof-label">Approvals</span>
                    <strong>Only where risk exists</strong>
                  </div>
                  <div className="lp-run-proof-item">
                    <span className="lp-run-proof-label">Artifacts</span>
                    <strong>Stored and shareable</strong>
                  </div>
                  <div className="lp-run-proof-item">
                    <span className="lp-run-proof-label">Memory</span>
                    <strong>Compounds into the next run</strong>
                  </div>
                </div>
              </div>
            </LiquidGlass>

            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-run-panel">
                <span className="lp-profile-kicker">Operating notes</span>
                <div className="lp-memory-checks">
                  {MEMORY_CHECKS.map((item) => (
                    <div key={item} className="lp-memory-check">
                      <span className="lp-memory-tick">✓</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-section-intro">
            <span className="lp-eyebrow">Run profiles</span>
            <h2 className="lp-section-h2">Same system. Different company shapes.</h2>
            <p className="lp-section-p">
              Astra changes what it prioritises based on the business you are trying to stand up,
              but the operating model stays consistent.
            </p>
          </div>

          <div className="lp-case-grid">
            {CASE_STUDIES.map((study) => (
              <LiquidGlass key={study.label} contentStyle={{ padding: 0 }}>
                <div className="lp-case-card">
                  <div className="lp-case-topline">
                    <span className="lp-profile-kicker">{study.label}</span>
                    <span className="lp-profile-duration">{study.time}</span>
                  </div>
                  <h3 className="lp-platform-subtitle">{study.title}</h3>
                  <p className="lp-control-copy">{study.summary}</p>
                  <div className="lp-case-meta">{study.agents}</div>
                  <ul className="lp-profile-output-list">
                    {study.outputs.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </LiquidGlass>
            ))}
          </div>
        </section>

        <section className="lp-section lp-platform-grid">
          <div className="lp-platform-main">
            <div className="lp-agents-head">
              <div>
                <span className="lp-eyebrow">Specialist bench</span>
                <h2 className="lp-section-h2">Every lane has a defined job.</h2>
              </div>
              <p className="lp-section-p">
                The product feels cohesive because the system itself is cohesive: each specialist has a clear role,
                but all of them read from and write to the same company context.
              </p>
            </div>

            <div ref={agentListRef} className="lp-agent-list">
              {AGENTS.map((agent) => (
                <div key={agent.name} className="lp-agent-row">
                  <span className="lp-agent-label">{agent.name}</span>
                  <span className="lp-agent-outputs-text">{agent.role}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="lp-platform-side">
            {SYSTEM_PANELS.map((panel) => (
              <LiquidGlass key={panel.title} contentStyle={{ padding: 0 }}>
                <div className="lp-platform-card">
                  <span className="lp-profile-kicker">{panel.label}</span>
                  <h3 className="lp-platform-subtitle">{panel.title}</h3>
                  <p className="lp-control-copy">{panel.text}</p>
                </div>
              </LiquidGlass>
            ))}

            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-platform-card">
                <span className="lp-profile-kicker">Core connectors</span>
                <div className="lp-integration-wrap">
                  {INTEGRATIONS.map((name) => (
                    <span key={name} className="lp-integration-tag">{name}</span>
                  ))}
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section lp-value-section">
          <div className="lp-value-head">
            <span className="lp-eyebrow">Economics</span>
            <h2 className="lp-section-h2">The leverage shows up in cost, speed, and continuity.</h2>
            <p className="lp-section-p">
              This is not an abstract productivity claim. The advantage comes from compressing a multi-role launch stack into one coordinated system.
            </p>
          </div>

          <div className="lp-value-grid">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-value-card lp-value-card-large">
                <span className="lp-profile-kicker">Snapshot</span>
                <h3 className="lp-platform-subtitle">Astra replaces coordination drag, not just labor hours.</h3>
                <div className="lp-value-stat-grid">
                  {VALUE_SNAPSHOTS.map((item) => (
                    <div key={item.label} className="lp-value-stat">
                      <span className="lp-run-proof-label">{item.label}</span>
                      <strong>{item.value}</strong>
                      <p>{item.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            </LiquidGlass>

            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-pricing-panel" id="pricing">
                <div className="lp-pricing-panel-head">
                  <div>
                    <span className="lp-profile-kicker">Pricing</span>
                    <h3 className="lp-platform-subtitle">Three plans. One operating model.</h3>
                  </div>
                  <p className="lp-control-copy">
                    The difference is depth, credits, and team scale, not a completely different product.
                  </p>
                </div>

                <div className="lp-pricing-columns">
                  {PRICING.map((plan) => (
                    <div
                      key={plan.label}
                      className={plan.featured ? "lp-price-card lp-price-card-featured" : "lp-price-card"}
                    >
                      <div className="lp-price-head">
                        <div>
                          <div className={plan.featured ? "lp-price-label lp-price-label-featured" : "lp-price-label"}>{plan.label}</div>
                          <div className="lp-price-sublabel">{plan.sublabel}</div>
                        </div>
                        <div className={plan.featured ? "lp-price-amount lp-price-amount-featured" : "lp-price-amount"}>
                          {plan.price}
                          <span className="lp-price-note-inline">{plan.note}</span>
                        </div>
                      </div>

                      <div className="lp-price-alt">{plan.alt}</div>
                      <ul className="lp-price-items">
                        {plan.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section lp-closeout-grid">
          <LiquidGlass contentStyle={{ padding: 0 }}>
            <div className="lp-closeout-panel">
              <div className="lp-closeout-main">
                <span className="lp-eyebrow">Questions</span>
                <h2 className="lp-section-h2">A few things founders usually ask.</h2>
                <div className="lp-faq-grid">
                  {FAQS.map((faq) => (
                    <div key={faq.q} className="lp-faq-card">
                      <h3 className="lp-faq-title">{faq.q}</h3>
                      <p className="lp-control-copy">{faq.a}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="lp-closeout-cta">
                <div className="lp-closeout-copy">
                  <span className="lp-agent-label">Start from one clear outcome</span>
                  <h2 className="lp-section-h2" style={{ margin: 0 }}>
                    You bring the idea.
                    <span style={{ color: "var(--lp-brand-dim)" }}> Astra handles everything else.</span>
                  </h2>
                  <p className="lp-control-copy">
                    From first prompt to launchable company, with a visible run log, preserved outputs, and a system that keeps compounding from there.
                  </p>
                </div>
                <div className="lp-hero-cta lp-closeout-actions">
                  <button className="site-btn site-btn-primary lp-primary-cta" onClick={handlePrimaryCta}>
                    {readySignedIn ? "Go to dashboard ->" : "Start a run ->"}
                  </button>
                </div>
              </div>
            </div>
          </LiquidGlass>
        </section>

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
