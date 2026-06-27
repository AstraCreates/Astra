"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import LiquidGlass from "@/components/LiquidGlass";
import SpaceEnv from "@/components/SpaceEnv";
import ThemeToggle from "@/components/ThemeToggle";
import { useDevUser } from "@/lib/use-dev-user";

type TerminalRow = { key: string; val: string };
type ScenarioMetric = { label: string; value: string };
type ScenarioLane = { name: string; status: string; progress: number };
type Scenario = {
  id: string;
  label: string;
  kicker: string;
  title: string;
  prompt: string;
  summary: string;
  duration: string;
  agents: string;
  approvals: string;
  artifacts: string;
  heroStats: string;
  outcomeCards: ScenarioMetric[];
  proofPoints: string[];
  outputs: string[];
  lanes: ScenarioLane[];
  heroTerminal: TerminalRow[];
  exampleTerminal: TerminalRow[];
};

const FLOW_STEPS = [
  { n: "01", action: "Goal", detail: "Describe the outcome you want — a company launch, a market map, a product build. Plain English." },
  { n: "02", action: "Plan", detail: "The orchestrator breaks your goal into an execution plan and routes work to the right specialists." },
  { n: "03", action: "Run", detail: "Agents execute with shared memory, live tool access, and approval gates on every risky action." },
  { n: "04", action: "Stream", detail: "Watch every agent action in real time via SSE — no black box, no waiting for a final answer." },
  { n: "05", action: "Collect", detail: "Deliverables land in your vault: source files, legal docs, deployed sites, reports, PDFs." },
  { n: "06", action: "Operate", detail: "Persistent memory, missions, and a workboard keep your company context alive between runs." },
];

const SCENARIOS: Scenario[] = [
  {
    id: "saas",
    label: "B2B SaaS",
    kicker: "Launch profile 01",
    title: "Turn a rough SaaS idea into a launch-ready company stack.",
    prompt: "Launch a B2B musician collaboration platform.",
    summary: "Astra maps the category, shapes the offer, provisions the product shell, drafts the legal stack, deploys the site, and sets up the first growth loops without losing continuity between teams.",
    duration: "14 min 22 sec",
    agents: "8 agents",
    approvals: "2 approvals",
    artifacts: "6 artifacts",
    heroStats: "B2B SaaS playbook · 8 agents · 14 min 22 sec · 6 vault artifacts",
    outcomeCards: [
      { label: "First deploy", value: "Same day" },
      { label: "Core assets", value: "24 files" },
      { label: "Growth loop", value: "Email + waitlist" },
    ],
    proofPoints: [
      "Research pack with TAM/SAM/SOM and pricing bands",
      "Launch site, waitlist funnel, and repo wired to deploy",
      "Founder docs, privacy policy, terms, and operating checklist",
    ],
    outputs: [
      "Market map + differentiation memo",
      "Landing page + pricing page deployed",
      "Auth + database scaffolding",
      "Founder agreement + NDA packet",
      "SEO metadata + content brief",
      "Launch checklist for week one",
    ],
    lanes: [
      { name: "Research", status: "TAM + competitor map", progress: 96 },
      { name: "Legal", status: "Entity docs drafted", progress: 82 },
      { name: "Web", status: "Landing page deployed", progress: 100 },
      { name: "Technical", status: "Core product scaffold", progress: 88 },
      { name: "Marketing", status: "Launch sequence loaded", progress: 74 },
    ],
    heroTerminal: [
      { key: "goal", val: "\"Launch a B2B musician collaboration platform\"" },
      { key: "plan", val: "8 agents · 6 phases · approval gate on LLC filing" },
      { key: "research", val: "TAM $2.4B · 6 competitors mapped · go/no-go: launch" },
      { key: "legal", val: "Resonant Technologies LLC filed · EIN retrieved" },
      { key: "web", val: "resonant.fm live · GitHub repo · SEO complete" },
      { key: "technical", val: "24 source files · Next.js + Supabase + Clerk" },
      { key: "status", val: "done · 14 min 22 sec · $0.09 · 6 artifacts in vault" },
    ],
    exampleTerminal: [
      { key: "→ research", val: "TAM $2.4B · SAM $480M · 6 competitors · pricing $29-$199/mo · go: launch" },
      { key: "→ legal", val: "Resonant Technologies LLC filed · EIN 84-XXXXXXX · NDA.pdf · FounderAgreement.pdf" },
      { key: "→ web", val: "resonant.fm live · /waitlist + /pricing · github.com/resonantfm · SEO meta done" },
      { key: "→ technical", val: "24 source files · Next.js + Supabase + Clerk · 6 Linear tickets · Notion workspace" },
      { key: "→ marketing", val: "3 launch emails · 2 ad concepts · waitlist incentive loop · onboarding copy" },
      { key: "→ ops", val: "Weekly cadence doc · KPI dashboard · approval queue configured" },
    ],
  },
  {
    id: "commerce",
    label: "Creator Commerce",
    kicker: "Launch profile 02",
    title: "Spin up a creator-led commerce engine with campaign assets baked in.",
    prompt: "Launch a premium digital-products brand for a creator audience.",
    summary: "Astra identifies the best offer ladder, creates the storefront and product packaging, drafts upsell sequences, and hands back a runbook ready for launch week and post-purchase nurturing.",
    duration: "11 min 05 sec",
    agents: "7 agents",
    approvals: "1 approval",
    artifacts: "9 artifacts",
    heroStats: "Creator commerce playbook · 7 agents · 11 min 05 sec · 9 launch assets",
    outcomeCards: [
      { label: "Offer ladder", value: "3 products" },
      { label: "Ad creatives", value: "12 hooks" },
      { label: "Store stack", value: "Payments live" },
    ],
    proofPoints: [
      "Offer architecture from low-ticket lead magnet to flagship product",
      "Storefront, payment flow, email automation, and creator copy",
      "A/B-tested hooks and launch-week posting calendar",
    ],
    outputs: [
      "Brand positioning + customer language doc",
      "Storefront copy + product detail pages",
      "Checkout, payment, and fulfillment wiring",
      "5-email cart + welcome sequence",
      "UGC brief + short-form script bank",
      "Launch analytics dashboard setup",
    ],
    lanes: [
      { name: "Research", status: "Audience demand clusters", progress: 91 },
      { name: "Design", status: "Offer packaging + art direction", progress: 78 },
      { name: "Web", status: "Storefront + checkout live", progress: 94 },
      { name: "Marketing", status: "Creative library generated", progress: 97 },
      { name: "Finance", status: "Margin model finalized", progress: 73 },
    ],
    heroTerminal: [
      { key: "goal", val: "\"Launch a premium digital-products brand for creators\"" },
      { key: "plan", val: "7 agents · pricing pass · storefront deploy" },
      { key: "research", val: "3 audience clusters · strongest hook: monetise existing fan demand" },
      { key: "design", val: "Brand kit · product packaging · creative direction approved" },
      { key: "web", val: "Storefront live · Stripe + email capture connected" },
      { key: "marketing", val: "12 short-form hooks · 5 launch emails · creator brief" },
      { key: "status", val: "done · 11 min 05 sec · $0.07 · 9 assets in vault" },
    ],
    exampleTerminal: [
      { key: "→ research", val: "Demand strongest for templates + premium workshop bundle · price sweet spot $49-$149" },
      { key: "→ design", val: "Brand kit delivered · hero imagery direction · product mockups staged" },
      { key: "→ web", val: "Storefront live · checkout + upsell flow · post-purchase thank-you page" },
      { key: "→ marketing", val: "Launch-day calendar · 12 reels hooks · 4 story CTA templates · 5-email sequence" },
      { key: "→ finance", val: "Gross margin 86% · break-even at 38 sales · bundle upsell lifts AOV 27%" },
      { key: "→ ops", val: "Support macros, dashboard, and creator approval queue configured" },
    ],
  },
  {
    id: "local",
    label: "Local Services",
    kicker: "Launch profile 03",
    title: "Stand up a local business growth machine with outreach, reviews, and booking flow.",
    prompt: "Launch an AI-assisted home services company in one city.",
    summary: "Astra defines the service menu, builds the site and booking flow, seeds outreach lists, sets up review requests, and creates the operational backbone needed to run the business consistently.",
    duration: "16 min 41 sec",
    agents: "9 agents",
    approvals: "3 approvals",
    artifacts: "8 artifacts",
    heroStats: "Local services playbook · 9 agents · 16 min 41 sec · city launch kit included",
    outcomeCards: [
      { label: "Lead list", value: "150 contacts" },
      { label: "Booking flow", value: "Live" },
      { label: "Review loop", value: "Automated" },
    ],
    proofPoints: [
      "Service packaging and territory-focused positioning for one metro area",
      "Booking experience, outbound list, and reputation flywheel configured",
      "Ops checklist for dispatch, follow-up, and quoting discipline",
    ],
    outputs: [
      "Local positioning + market density memo",
      "Booking page + intake funnel",
      "Outreach sequences for referral partners",
      "Review request + win-back messaging",
      "Pricing calculator + quoting template",
      "Operations SOP for first hires",
    ],
    lanes: [
      { name: "Research", status: "Zip-code opportunity map", progress: 89 },
      { name: "Sales", status: "Referral list + outreach", progress: 93 },
      { name: "Web", status: "Booking funnel deployed", progress: 90 },
      { name: "Ops", status: "SOP + dispatch workflow", progress: 86 },
      { name: "Marketing", status: "Review flywheel + ads", progress: 76 },
    ],
    heroTerminal: [
      { key: "goal", val: "\"Launch an AI-assisted home services company in one city\"" },
      { key: "plan", val: "9 agents · city-market pack · booking + outreach workflow" },
      { key: "research", val: "Service radius chosen · 3 profitable neighborhoods prioritised" },
      { key: "sales", val: "150 lead list built · 3 referral sequences loaded" },
      { key: "web", val: "Booking flow live · quote request form integrated" },
      { key: "ops", val: "Dispatch SOP + review request loop configured" },
      { key: "status", val: "done · 16 min 41 sec · $0.12 · 8 assets in vault" },
    ],
    exampleTerminal: [
      { key: "→ research", val: "High-intent search demand concentrated in North Austin + Round Rock + Cedar Park" },
      { key: "→ sales", val: "150 contacts enriched · referral outreach ready · first 20 prospects personalized" },
      { key: "→ web", val: "Booking funnel + pricing calculator live · lead capture + analytics firing" },
      { key: "→ marketing", val: "Review request SMS + email workflow · neighborhood ad set copy delivered" },
      { key: "→ ops", val: "Dispatch checklist, quoting SOP, and support playbook loaded into workboard" },
      { key: "→ finance", val: "Target CAC $46 · first-month revenue target $8.1k · margin guardrails set" },
    ],
  },
];

const AGENTS = [
  { name: "Research", role: "Market sizing, TAM/SAM/SOM, competitor intelligence, pricing benchmarks, regulatory landscape, go/no-go." },
  { name: "Legal", role: "LLC formation via Computer Use, EIN retrieval, NDAs, privacy policy, terms, founder agreements, compliance." },
  { name: "Web", role: "Site generation, copy, waitlist deployment, GitHub repo, Vercel deploy, domain setup, SEO metadata." },
  { name: "Technical", role: "Product scaffolding, 20-30 source files, Supabase integration, Vercel CI, Linear tickets, Notion workspace." },
  { name: "Design", role: "Wireframes, color palettes, logo briefs, UX direction, component specs, brand identity assets." },
  { name: "Marketing", role: "Email sequences, social content, Reels scripts, TikTok hooks, Meta ad copy, campaign briefs." },
  { name: "SEO", role: "Technical SEO audit, keyword strategy, meta tags, structured data, content calendar, link-building plan." },
  { name: "Sales", role: "Lead enrichment via Apollo/Hunter, outreach sequences, inbox warming, CRM setup, investor emails." },
  { name: "Outreach", role: "Prospecting lists, personalized cold email, follow-up cadences, LinkedIn sequences, reply handling." },
  { name: "Finance", role: "Financial modeling, fundraise deck support, cap table, runway projections, investor-ready data room." },
  { name: "Ops", role: "SOPs, weekly digests, calendar coordination, task scheduling, decision logs, workboard management." },
  { name: "Infrastructure", role: "Cloud setup, CI/CD pipelines, Docker configuration, monitoring, environment provisioning." },
];

const CONTROL_PILLARS = [
  {
    label: "Governance",
    title: "Approval gates on anything irreversible.",
    text: "Deploys, filings, outbound email, billing changes, and account actions all pause for explicit approval instead of slipping through a hidden chain of tool calls.",
  },
  {
    label: "Auditability",
    title: "Every action is visible while it happens.",
    text: "Runs stream in real time with agent-by-agent receipts, artifacts, and context handoffs, so founders can step in without breaking the workflow.",
  },
  {
    label: "Continuity",
    title: "Each run compounds instead of starting over.",
    text: "Astra promotes outputs into shared memory, workboards, and company reports so the next run begins with actual history, not a blank prompt box.",
  },
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
    a: "Astra does not just answer prompts. It creates durable runs with a plan, specialist agents executing in parallel, live progress, and real artifacts stored in a vault. It behaves more like company infrastructure than a chat tab.",
  },
  {
    q: "What are approval gates?",
    a: "Any action Astra considers risky — deploying to production, sending emails, filing legal documents, or changing account settings — pauses and waits for your explicit approval before proceeding.",
  },
  {
    q: "What is the Agent Stack Platform?",
    a: "It lets you turn a repeatable business outcome into a reusable AI department package with lanes, connectors, approval gates, quality checks, and an execution blueprint.",
  },
  {
    q: "What integrations are live?",
    a: "Stripe, Vercel, GitHub, Notion, Supabase, Apollo, Hunter, Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy, Resend, and Composio. Agents can take live actions inside these systems, not just read data.",
  },
  {
    q: "What is shared memory?",
    a: "Every run writes to a persistent context store. Agents read each other's outputs, and the full record — decisions, files, conversations — carries forward into the company brain for future runs.",
  },
];

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export default function Home() {
  const { isSignedIn } = useDevUser();
  const router = useRouter();
  const agentListRef = useRef<HTMLDivElement>(null);

  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [scenarioIndex, setScenarioIndex] = useState(0);
  const [scenarioPinned, setScenarioPinned] = useState(false);
  const [teamSize, setTeamSize] = useState(6);
  const [weeklyRuns, setWeeklyRuns] = useState(18);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (scenarioPinned) return;
    const timer = window.setInterval(() => {
      setScenarioIndex((current) => (current + 1) % SCENARIOS.length);
    }, 5200);
    return () => window.clearInterval(timer);
  }, [scenarioPinned]);

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
        duration: 1.4,
        easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        touchMultiplier: 2,
      });

      const rafFn = (time: number) => lenis.raf(time * 1000);
      gsap.ticker.add(rafFn);
      gsap.ticker.lagSmoothing(0);
      lenis.on("scroll", (ScrollTrigger as { update: () => void }).update);

      gsap.from(".lp-hero-left > *", { y: 28, opacity: 0, duration: 0.8, stagger: 0.09, ease: "power3.out", delay: 0.15 });
      gsap.from(".lp-hero-right", { x: 26, opacity: 0, duration: 1, ease: "power3.out", delay: 0.3 });
      gsap.from(".lp-hero-metric", { y: 18, opacity: 0, duration: 0.55, stagger: 0.08, ease: "power2.out", delay: 0.4 });

      document.querySelectorAll<HTMLElement>(".lp-section-h2").forEach((el) => {
        gsap.from(el, { y: 40, opacity: 0, duration: 0.85, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 86%" } });
      });
      document.querySelectorAll<HTMLElement>(".lp-section-p").forEach((el) => {
        gsap.from(el, { y: 20, opacity: 0, duration: 0.72, ease: "power3.out", delay: 0.06, scrollTrigger: { trigger: el, start: "top 89%" } });
      });

      gsap.from(".lp-flow-step", { y: 30, opacity: 0, duration: 0.65, stagger: 0.08, ease: "power2.out", scrollTrigger: { trigger: ".lp-flow-grid", start: "top 82%" } });
      gsap.from(".lp-example .lp-example-right", { x: 42, opacity: 0, rotateY: -6, duration: 1, ease: "power3.out", transformOrigin: "0% 50%", scrollTrigger: { trigger: ".lp-example", start: "top 80%" } });
      gsap.from(".lp-profile-panel", { y: 32, opacity: 0, duration: 0.75, stagger: 0.1, ease: "power3.out", scrollTrigger: { trigger: ".lp-profile-grid", start: "top 82%" } });
      gsap.from(".lp-control-card", { y: 28, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power2.out", scrollTrigger: { trigger: ".lp-control-grid", start: "top 84%" } });
      gsap.from(".lp-memory-check", { x: -20, opacity: 0, duration: 0.55, stagger: 0.08, ease: "power2.out", scrollTrigger: { trigger: ".lp-memory-checks", start: "top 82%" } });
      gsap.from(".lp-integration-tag", { scale: 0.88, opacity: 0, duration: 0.48, stagger: 0.03, ease: "power2.out", scrollTrigger: { trigger: ".lp-integration-wrap", start: "top 82%" } });
      gsap.from(".lp-calc-shell", { y: 34, opacity: 0, duration: 0.85, ease: "power3.out", scrollTrigger: { trigger: ".lp-calc-shell", start: "top 84%" } });

      document.querySelectorAll<HTMLElement>(".lp-pricing-grid > *").forEach((card, i) => {
        gsap.from(card, { y: 55, opacity: 0, scale: 0.94, rotateX: 10, duration: 0.9, ease: "power3.out", delay: i * 0.12, transformOrigin: "50% 0%", scrollTrigger: { trigger: ".lp-pricing-grid", start: "top 82%" } });
      });

      gsap.from(".lp-cohort-card", { y: 44, opacity: 0, scale: 0.96, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: ".lp-cohort-card", start: "top 84%" } });
      gsap.from(".lp-faq-item", { y: 16, opacity: 0, duration: 0.5, stagger: 0.06, ease: "power2.out", scrollTrigger: { trigger: ".lp-faq-list", start: "top 84%" } });
      gsap.from(".lp-close-h2", { y: 50, opacity: 0, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: ".lp-close", start: "top 82%" } });
      gsap.from(".lp-close-p", { y: 24, opacity: 0, duration: 0.7, ease: "power3.out", delay: 0.12, scrollTrigger: { trigger: ".lp-close", start: "top 82%" } });
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
      { threshold: 0.05 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const readySignedIn = hydrated && isSignedIn;
  const activeScenario = SCENARIOS[scenarioIndex];

  const includedRuns = teamSize <= 3 ? 12 : teamSize <= 8 ? 30 : 70;
  const recommendedPlan = teamSize <= 3 ? PRICING[0] : teamSize <= 8 ? PRICING[1] : PRICING[2];
  const astraBase = Number(recommendedPlan.price.replace("$", ""));
  const monthlyHuman = teamSize * 6200 + 1800;
  const monthlyAstra = astraBase + Math.max(0, weeklyRuns - includedRuns) * 3;
  const annualSavings = Math.max(0, (monthlyHuman - monthlyAstra) * 12);
  const humanLaunchDays = Math.max(18, Math.round(35 - weeklyRuns * 0.2 + teamSize * 0.9));
  const astraLaunchHours = Math.max(4, Math.round(18 - Math.min(weeklyRuns, 30) * 0.25));
  const astraSpendRatio = Math.max(8, Math.round((monthlyAstra / monthlyHuman) * 100));
  const runCadence = weeklyRuns * 4;

  const CtaButtons = () => (
    <>
      <button
        className="site-btn site-btn-primary"
        onClick={() => {
          if (readySignedIn) {
            router.push("/dashboard");
            return;
          }
          signIn("google", { callbackUrl: "/dashboard" });
        }}
      >
        {readySignedIn ? "Go to dashboard ->" : "Start building ->"}
      </button>
      <button
        className="site-btn site-btn-ghost"
        onClick={() => signIn("google", { callbackUrl: "/dashboard" })}
        aria-hidden={readySignedIn}
        tabIndex={readySignedIn ? -1 : 0}
        style={readySignedIn ? { opacity: 0, pointerEvents: "none" } : undefined}
      >
        Sign in
      </button>
    </>
  );

  return (
    <>
      <SpaceEnv />

      <div className="lp-page" style={{ position: "relative", zIndex: 1 }}>
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
              <ThemeToggle />
              <CtaButtons />
            </div>
          </div>
        </nav>

        <section className="lp-hero">
          <div className="lp-hero-left">
            <span className="lp-eyebrow">AI founding team for launch, growth, and operations</span>
            <h1 className="lp-hero-h1">
              You bring the idea.
              <br />
              <span style={{ color: "var(--lp-brand-dim)" }}>Astra handles everything else.</span>
            </h1>
            <p className="lp-hero-lede">
              Entity formation, market research, legal documents, live deployments,
              and customer acquisition — coordinated by specialist agents working in
              parallel, with every action visible and every deliverable preserved.
            </p>

            <div className="lp-hero-pills" role="tablist" aria-label="Launch scenario">
              {SCENARIOS.map((scenario, index) => (
                <button
                  key={scenario.id}
                  className={index === scenarioIndex ? "lp-scenario-pill lp-scenario-pill-active" : "lp-scenario-pill"}
                  onClick={() => {
                    setScenarioPinned(true);
                    setScenarioIndex(index);
                  }}
                  role="tab"
                  aria-selected={index === scenarioIndex}
                >
                  {scenario.label}
                </button>
              ))}
            </div>

            <div className="lp-hero-metrics">
              {activeScenario.outcomeCards.map((card) => (
                <div key={card.label} className="lp-hero-metric">
                  <span className="lp-hero-metric-label">{card.label}</span>
                  <strong className="lp-hero-metric-value">{card.value}</strong>
                </div>
              ))}
            </div>

            <div className="lp-hero-cta">
              <CtaButtons />
            </div>
            <p className="lp-stats-inline">{activeScenario.heroStats}</p>
          </div>

          <div className="lp-hero-right">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-terminal-card">
                <div className="lp-terminal-prompt">{activeScenario.prompt}</div>
                {activeScenario.heroTerminal.map((row, i) => (
                  <div
                    key={row.key}
                    className="lp-terminal-row"
                    style={i === activeScenario.heroTerminal.length - 1 ? { marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" } : undefined}
                  >
                    <span className="lp-terminal-key">{row.key}</span>
                    <span className="lp-terminal-val" style={i === activeScenario.heroTerminal.length - 1 ? { color: "var(--sg-color)" } : undefined}>
                      {row.val}
                    </span>
                  </div>
                ))}
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section">
          <h2 className="lp-section-h2">How a run works</h2>
          <p className="lp-section-p">Six phases. Fully orchestrated. Every step visible.</p>
          <div className="lp-flow-grid">
            {FLOW_STEPS.map((step) => (
              <div key={step.n} className="lp-flow-step">
                <span className="lp-flow-n">{step.n}</span>
                <span className="lp-flow-action">{step.action}</span>
                <span className="lp-flow-detail">{step.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-section lp-example">
          <div className="lp-example-left">
            <h2 className="lp-section-h2">One goal. This is what runs.</h2>
            <p className="lp-section-p" style={{ marginBottom: 0 }}>
              Input: <em>"{activeScenario.prompt}"</em>
              {" "}Astra routes the work, coordinates specialists, and hands back the actual operating kit.
            </p>
          </div>
          <div className="lp-example-right">
            <LiquidGlass contentStyle={{ padding: 0 }}>
              <div className="lp-terminal-card">
                <div className="lp-terminal-prompt">
                  $ astra run <span style={{ color: "var(--sg-color)" }}>"{activeScenario.prompt}"</span>
                </div>
                {activeScenario.exampleTerminal.map((row) => (
                  <div key={row.key} className="lp-terminal-row">
                    <span className="lp-terminal-key">{row.key}</span>
                    <span className="lp-terminal-val">{row.val}</span>
                  </div>
                ))}
                <div className="lp-terminal-summary">
                  ✓ {activeScenario.agents} · {activeScenario.duration} · {activeScenario.artifacts}
                </div>
              </div>
            </LiquidGlass>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-profile-head">
            <span className="lp-eyebrow">Interactive run preview</span>
            <h2 className="lp-section-h2">Pick the kind of company you want to build.</h2>
            <p className="lp-section-p">
              The same orchestration layer behaves differently depending on the business outcome.
              Switch the launch profile and the stack, outputs, and lane priorities all adapt.
            </p>
          </div>

          <div className="lp-profile-grid">
            <LiquidGlass contentStyle={{ padding: 0 }} className="lp-profile-panel">
              <div className="lp-profile-card">
                <div className="lp-profile-topline">
                  <span className="lp-profile-kicker">{activeScenario.kicker}</span>
                  <span className="lp-profile-duration">{activeScenario.duration}</span>
                </div>
                <h3 className="lp-profile-title">{activeScenario.title}</h3>
                <p className="lp-profile-copy">{activeScenario.summary}</p>

                <div className="lp-profile-stat-grid">
                  <div className="lp-profile-stat">
                    <span className="lp-profile-stat-label">Agents engaged</span>
                    <strong>{activeScenario.agents}</strong>
                  </div>
                  <div className="lp-profile-stat">
                    <span className="lp-profile-stat-label">Approval gates</span>
                    <strong>{activeScenario.approvals}</strong>
                  </div>
                  <div className="lp-profile-stat">
                    <span className="lp-profile-stat-label">Artifacts shipped</span>
                    <strong>{activeScenario.artifacts}</strong>
                  </div>
                </div>

                <div className="lp-profile-lanes">
                  {activeScenario.lanes.map((lane) => (
                    <div key={lane.name} className="lp-lane">
                      <div className="lp-lane-top">
                        <span className="lp-lane-name">{lane.name}</span>
                        <span className="lp-lane-status">{lane.status}</span>
                      </div>
                      <div className="lp-lane-bar">
                        <span className="lp-lane-fill" style={{ width: `${lane.progress}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </LiquidGlass>

            <LiquidGlass contentStyle={{ padding: 0 }} className="lp-profile-panel">
              <div className="lp-profile-card">
                <div className="lp-profile-proof">
                  <div>
                    <span className="lp-profile-kicker">What comes back</span>
                    <h3 className="lp-profile-title" style={{ fontSize: "clamp(24px, 2.6vw, 34px)", marginBottom: 10 }}>
                      Deliverables, not just suggestions.
                    </h3>
                  </div>
                  <ul className="lp-profile-output-list">
                    {activeScenario.outputs.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="lp-profile-proof-box">
                  {activeScenario.proofPoints.map((item) => (
                    <div key={item} className="lp-profile-proof-item">
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
          <div className="lp-agents-head">
            <h2 className="lp-section-h2">The full specialist bench.</h2>
            <p className="lp-section-p">Every agent has a defined role, dedicated tools, and access to the shared company brain.</p>
          </div>
          <div ref={agentListRef} className="lp-agent-list">
            {AGENTS.map((agent, i) => (
              <div key={agent.name} className="lp-agent-row" style={{ "--row-i": i } as React.CSSProperties}>
                <span className="lp-agent-label">{agent.name}</span>
                <span className="lp-agent-outputs-text">{agent.role}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="lp-section lp-two-col">
          <div>
            <span className="lp-eyebrow">Company brain</span>
            <h2 className="lp-section-h2">Persistent by default.</h2>
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
              ].map((item) => (
                <div key={item} className="lp-memory-check">
                  <span className="lp-memory-tick">✓</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </LiquidGlass>
        </section>

        <section className="lp-section">
          <span className="lp-eyebrow">Connectors that matter</span>
          <h2 className="lp-section-h2">Agents that actually act.</h2>
          <p className="lp-section-p">
            Not summaries of what you could do. Live actions inside real systems —
            with your approval on anything irreversible.
          </p>
          <div className="lp-integration-wrap">
            {INTEGRATIONS.map((name) => (
              <span key={name} className="lp-integration-tag">{name}</span>
            ))}
          </div>
        </section>

        <section className="lp-section">
          <span className="lp-eyebrow">Trust surfaces</span>
          <h2 className="lp-section-h2">Speed without surrendering control.</h2>
          <p className="lp-section-p">
            Astra is built for founders who want leverage, not mystery.
          </p>
          <div className="lp-control-grid">
            {CONTROL_PILLARS.map((pillar) => (
              <LiquidGlass key={pillar.title} contentStyle={{ padding: 0 }}>
                <div className="lp-control-card">
                  <span className="lp-profile-kicker">{pillar.label}</span>
                  <h3 className="lp-control-title">{pillar.title}</h3>
                  <p className="lp-control-copy">{pillar.text}</p>
                </div>
              </LiquidGlass>
            ))}
          </div>
        </section>

        <section className="lp-section">
          <span className="lp-eyebrow">Value calculator</span>
          <h2 className="lp-section-h2">Model the work you want off your plate.</h2>
          <p className="lp-section-p">
            Slide the assumptions. The economics shift fast when the same system can research, draft, ship, and coordinate without losing context.
          </p>

          <LiquidGlass contentStyle={{ padding: 0 }} className="lp-calc-shell">
            <div className="lp-calc-grid">
              <div className="lp-calc-controls">
                <label className="lp-calc-control">
                  <div className="lp-calc-control-top">
                    <span>Equivalent team size</span>
                    <strong>{teamSize} people</strong>
                  </div>
                  <input
                    type="range"
                    min="2"
                    max="18"
                    value={teamSize}
                    onChange={(event) => setTeamSize(Number(event.target.value))}
                  />
                </label>

                <label className="lp-calc-control">
                  <div className="lp-calc-control-top">
                    <span>Agent runs per week</span>
                    <strong>{weeklyRuns} runs</strong>
                  </div>
                  <input
                    type="range"
                    min="6"
                    max="60"
                    value={weeklyRuns}
                    onChange={(event) => setWeeklyRuns(Number(event.target.value))}
                  />
                </label>

                <div className="lp-calc-notes">
                  <div className="lp-calc-note">
                    <span className="lp-calc-note-label">Recommended plan</span>
                    <strong>{recommendedPlan.label}</strong>
                  </div>
                  <div className="lp-calc-note">
                    <span className="lp-calc-note-label">Monthly cadence</span>
                    <strong>{runCadence} runs</strong>
                  </div>
                  <div className="lp-calc-note">
                    <span className="lp-calc-note-label">Typical launch time</span>
                    <strong>{astraLaunchHours} hrs</strong>
                  </div>
                </div>
              </div>

              <div className="lp-calc-results">
                <div className="lp-calc-comparison">
                  <div className="lp-calc-row">
                    <div className="lp-calc-row-top">
                      <span>Conventional team monthly cost</span>
                      <strong>{money.format(monthlyHuman)}</strong>
                    </div>
                    <div className="lp-calc-bar">
                      <span className="lp-calc-bar-fill lp-calc-bar-fill-human" style={{ width: "100%" }} />
                    </div>
                  </div>

                  <div className="lp-calc-row">
                    <div className="lp-calc-row-top">
                      <span>Astra monthly cost</span>
                      <strong>{money.format(monthlyAstra)}</strong>
                    </div>
                    <div className="lp-calc-bar">
                      <span className="lp-calc-bar-fill lp-calc-bar-fill-astra" style={{ width: `${astraSpendRatio}%` }} />
                    </div>
                  </div>
                </div>

                <div className="lp-calc-summary-grid">
                  <div className="lp-calc-summary">
                    <span className="lp-calc-summary-label">Annual savings</span>
                    <strong>{money.format(annualSavings)}</strong>
                  </div>
                  <div className="lp-calc-summary">
                    <span className="lp-calc-summary-label">Typical human-team launch</span>
                    <strong>{humanLaunchDays} days</strong>
                  </div>
                  <div className="lp-calc-summary">
                    <span className="lp-calc-summary-label">Approval touches / month</span>
                    <strong>{Math.round(weeklyRuns * 1.5)}</strong>
                  </div>
                </div>
              </div>
            </div>
          </LiquidGlass>
        </section>

        <section className="lp-section lp-perspective">
          <h2 className="lp-section-h2">Simple pricing.</h2>
          <p className="lp-section-p">A full-stack ops team costs more in a week than Astra costs in a year.</p>
          <div className="lp-pricing-grid">
            {PRICING.map((plan) => (
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
                  <div className={plan.featured ? "lp-price-amount lp-price-amount-featured" : "lp-price-amount"}>
                    {plan.price}
                    <span style={{ fontSize: "0.38em", fontWeight: 400, letterSpacing: 0, color: "var(--text-3)", verticalAlign: "middle", marginLeft: 2 }}>
                      {plan.note}
                    </span>
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

        <section className="lp-section">
          <LiquidGlass contentStyle={{ padding: 0 }}>
            <div className="lp-cohort-card">
              <span className="lp-agent-label" style={{ letterSpacing: "0.14em" }}>Founding Cohort</span>
              <h2 className="lp-section-h2" style={{ textAlign: "center", margin: 0 }}>Limited to 25 founders.</h2>
              <p style={{ fontSize: 15, lineHeight: 1.7, color: "var(--lp-text)", maxWidth: "46ch", margin: 0 }}>
                The first cohort gets hands-on onboarding, priority support, and a direct line to the team.
                We ask for a brief case study at 90 days. Cohort one opens June 1st.
              </p>
              <div className="lp-hero-cta" style={{ justifyContent: "center" }}>
                <CtaButtons />
              </div>
            </div>
          </LiquidGlass>
        </section>

        <section className="lp-section">
          <h2 className="lp-section-h2">Questions.</h2>
          <div className="lp-faq-list">
            {FAQS.map((faq, i) => (
              <div key={faq.q} className="lp-faq-item">
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

        <section className="lp-close">
          <h2 className="lp-close-h2">
            You bring the idea.
            <br />
            <span style={{ color: "var(--lp-brand-dim)" }}>Astra handles everything else.</span>
          </h2>
          <p className="lp-close-p">From first prompt to launchable company, with the receipts to prove what happened.</p>
          <div className="lp-hero-cta" style={{ justifyContent: "center" }}>
            <CtaButtons />
          </div>
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
