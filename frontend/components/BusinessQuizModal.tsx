"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

export interface QuizResult {
  stackId?: string;
  contextBlock: string;
  businessType: string;
  customerType: string;
  stage: string;
  subCategory: string;
}

interface Props {
  onComplete: (result: QuizResult) => void;
  onSkip: () => void;
}

type Step = "type" | "customer" | "stage" | "sub";

export const BIZ_TYPES = [
  { id: "saas", label: "SaaS / Web App", icon: "⬡", desc: "Software, tools, platforms, dashboards" },
  { id: "ecomm", label: "Ecommerce", icon: "◈", desc: "Online store — physical, digital, or POD" },
  { id: "local", label: "Local Service", icon: "◉", desc: "Salon, gym, restaurant, cleaning, tutoring…" },
  { id: "agency", label: "Agency / Consulting", icon: "◇", desc: "Services sold to other businesses" },
  { id: "content", label: "Content / Creator", icon: "◈", desc: "Media, newsletter, community, info products" },
];

export const CUSTOMER_TYPES = [
  { id: "b2c", label: "Consumers (B2C)", desc: "Individuals or households" },
  { id: "b2b", label: "Businesses (B2B)", desc: "Companies, teams, or professionals" },
  { id: "both", label: "Both / Marketplace", desc: "Serve both sides or a two-sided market" },
];

export const STAGES = [
  { id: "idea", label: "Idea — build from scratch", desc: "No product yet, starting fresh" },
  { id: "mvp", label: "Have a prototype / MVP", desc: "Something exists, needs shipping or improving" },
  { id: "live", label: "Already live, need to grow", desc: "Customers exist, focus is scale or expansion" },
];

export const LOCAL_CATEGORIES = [
  { id: "beauty", label: "Beauty & Wellness", desc: "Salons, barbershops, spas, nails" },
  { id: "fitness", label: "Fitness & Sports", desc: "Gyms, yoga, personal training" },
  { id: "food", label: "Food & Beverage", desc: "Restaurants, cafes, catering, bakeries" },
  { id: "professional", label: "Professional Services", desc: "Tutoring, coaching, legal, accounting" },
  { id: "home", label: "Home Services", desc: "Cleaning, landscaping, repairs, moving" },
  { id: "retail", label: "Retail / Boutique", desc: "Physical shop or pop-up" },
];

export const ECOMM_CATEGORIES = [
  { id: "physical", label: "Physical Products", desc: "Ship tangible goods to customers" },
  { id: "digital", label: "Digital Products", desc: "Files, templates, software, courses" },
  { id: "subscription", label: "Subscriptions / Box", desc: "Recurring physical or digital deliveries" },
  { id: "pod", label: "Print-on-Demand", desc: "Custom merch via Printful/Printify" },
];

export const SAAS_PRICING = [
  { id: "freemium", label: "Freemium", desc: "Free tier, paid upgrade for power features" },
  { id: "subscription", label: "Subscription", desc: "Flat monthly/annual seat or plan pricing" },
  { id: "usage", label: "Usage-Based", desc: "Pay per API call, seat-active, or credit consumed" },
  { id: "license", label: "One-Time License", desc: "Single purchase, perpetual or per-version" },
];

export const AGENCY_NICHES = [
  { id: "marketing", label: "Marketing / Growth", desc: "SEO, ads, content, social for clients" },
  { id: "devit", label: "Dev / IT", desc: "Software builds, infra, technical consulting" },
  { id: "design", label: "Design / Brand", desc: "Visual identity, product, UX work" },
  { id: "ops", label: "Finance / Ops", desc: "Bookkeeping, fractional exec, operations" },
];

export const CONTENT_MONETIZATION = [
  { id: "ads", label: "Ads / Sponsorship", desc: "Brand deals, ad slots, sponsored posts" },
  { id: "membership", label: "Subscriptions / Membership", desc: "Paid tier, Patreon-style recurring support" },
  { id: "courses", label: "Courses / Digital Products", desc: "Cohorts, templates, downloadable products" },
  { id: "affiliate", label: "Affiliate / Referral", desc: "Commission on products you recommend" },
];

export const STACK_MAP: Record<string, string> = {
  saas: "idea_to_revenue",
  ecomm: "ecomm",
  local: "local_service",
  agency: "idea_to_revenue",
  content: "idea_to_revenue",
};

const ALL_DETAIL_OPTIONS = [...LOCAL_CATEGORIES, ...ECOMM_CATEGORIES, ...SAAS_PRICING, ...AGENCY_NICHES, ...CONTENT_MONETIZATION];

function detailOptionsFor(bizType: string) {
  if (bizType === "local") return LOCAL_CATEGORIES;
  if (bizType === "ecomm") return ECOMM_CATEGORIES;
  if (bizType === "saas") return SAAS_PRICING;
  if (bizType === "agency") return AGENCY_NICHES;
  if (bizType === "content") return CONTENT_MONETIZATION;
  return [];
}

function detailCopyFor(bizType: string): { title: string; sub: string } {
  switch (bizType) {
    case "local": return { title: "What kind of service?", sub: "Narrows agent instructions to your specific category." };
    case "ecomm": return { title: "What are you selling?", sub: "Narrows agent instructions to your specific category." };
    case "saas": return { title: "How will you price it?", sub: "Shapes billing setup, landing page copy, and growth motion." };
    case "agency": return { title: "What's your specialty?", sub: "Tailors outreach, positioning, and case-study angles." };
    case "content": return { title: "How will you monetize?", sub: "Shapes the funnel agents build toward." };
    default: return { title: "One more detail", sub: "Narrows agent instructions to your specific category." };
  }
}

export function buildQuizContext(type: string, customer: string, stage: string, sub: string): string {
  const typeLabel = BIZ_TYPES.find(t => t.id === type)?.label || type;
  const customerLabel = CUSTOMER_TYPES.find(c => c.id === customer)?.label || customer;
  const stageLabel = STAGES.find(s => s.id === stage)?.label || stage;
  const subLabel = sub ? (ALL_DETAIL_OPTIONS.find(c => c.id === sub)?.label || sub) : "";

  const lines = [
    `Business type: ${typeLabel}${subLabel ? ` — ${subLabel}` : ""}`,
    `Customers: ${customerLabel}`,
    `Stage: ${stageLabel}`,
  ];
  return lines.join("\n");
}

const STEP_VARIANTS = {
  enter: (dir: number) => ({ opacity: 0, x: dir > 0 ? 28 : -28 }),
  center: { opacity: 1, x: 0 },
  exit: (dir: number) => ({ opacity: 0, x: dir > 0 ? -28 : 28 }),
};

export default function BusinessQuizModal({ onComplete, onSkip }: Props) {
  const [step, setStep] = useState<Step>("type");
  const [dir, setDir] = useState(1);
  const [bizType, setBizType] = useState("");
  const [customer, setCustomer] = useState("");
  const [stage, setStage] = useState("");
  const [sub, setSub] = useState("");

  const subOptions = detailOptionsFor(bizType);
  const detailCopy = detailCopyFor(bizType);
  const typeLabel = BIZ_TYPES.find(t => t.id === bizType)?.label || "";
  const customerLabel = CUSTOMER_TYPES.find(c => c.id === customer)?.label || "";

  const goTo = (next: Step, direction: number) => { setDir(direction); setStep(next); };

  const advance = () => {
    if (step === "type") { goTo("customer", 1); return; }
    if (step === "customer") { goTo("stage", 1); return; }
    if (step === "stage") { goTo("sub", 1); return; }
    if (step === "sub") { finish(sub); return; }
  };

  const back = () => {
    if (step === "sub") { goTo("stage", -1); return; }
    if (step === "stage") { goTo("customer", -1); return; }
    if (step === "customer") { goTo("type", -1); return; }
  };

  const finish = (subVal: string) => {
    const contextBlock = buildQuizContext(bizType, customer, stage, subVal);
    onComplete({ contextBlock, businessType: bizType, customerType: customer, stage, subCategory: subVal });
  };

  const canAdvance =
    (step === "type" && bizType) ||
    (step === "customer" && customer) ||
    (step === "stage" && stage) ||
    (step === "sub" && sub);

  const STEPS: Step[] = ["type", "customer", "stage", "sub"];
  const stepIdx = STEPS.indexOf(step);
  const progress = ((stepIdx + 1) / STEPS.length) * 100;

  return (
    <div className="astra-modal-backdrop">
      <div className="astra-modal-shell" style={{ maxWidth: 540 }}>
        <div className="astra-modal-panel">
        <div className="astra-modal-header">
          <div className="astra-modal-header-row">
            <div>
              <div className="astra-modal-eyebrow">guided launch</div>
              <h2 className="astra-modal-title">Let&apos;s tailor this run</h2>
              <p className="astra-modal-sub">A few quick answers help Astra choose better agent prompts, stacks, and integrations for this business.</p>
            </div>
            <button
              onClick={onSkip}
              className="astra-modal-close"
              aria-label="Skip quiz"
            >
              ×
            </button>
          </div>
        </div>
        <div className="astra-modal-body">
        <div style={{ marginBottom: 2 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <span style={{ fontSize: 11, color: "var(--fm, #666)", fontFamily: "var(--font-ibm-mono)" }}>
              Step {stepIdx + 1} of {STEPS.length}
            </span>
            <button
              onClick={onSkip}
              style={{ fontSize: 11, color: "var(--blue)", background: "none", border: "none", cursor: "pointer", padding: 0, fontWeight: 600 }}
            >
              Skip →
            </button>
          </div>
          <div className="astra-modal-progress">
            <motion.div
              initial={false}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.32, ease: "easeOut" }}
            />
          </div>
        </div>

        <div style={{ position: "relative", overflow: "hidden" }}>
        <AnimatePresence mode="wait" custom={dir} initial={false}>
          {step === "type" && (
            <motion.div key="type" custom={dir} variants={STEP_VARIANTS} initial="enter" animate="center" exit="exit" transition={{ duration: 0.22, ease: "easeOut" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
                What type of business is this?
              </div>
              <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
                Helps Astra tailor agent prompts and suggested integrations.
              </div>
              <div className="astra-choice-grid">
                {BIZ_TYPES.map(t => (
                  <button
                    key={t.id}
                    onClick={() => { setBizType(t.id); setSub(""); }}
                    className={`astra-choice-card${bizType === t.id ? " is-selected" : ""}`}
                    style={{ display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <span style={{ fontSize: 18, lineHeight: 1, color: "var(--fm)" }}>{t.icon}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{t.label}</div>
                      <div style={{ fontSize: 11, color: "var(--fm)" }}>{t.desc}</div>
                    </div>
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {step === "customer" && (
            <motion.div key="customer" custom={dir} variants={STEP_VARIANTS} initial="enter" animate="center" exit="exit" transition={{ duration: 0.22, ease: "easeOut" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
                Who are your customers?
              </div>
              <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
                {typeLabel ? `Since you're building a ${typeLabel.toLowerCase()}, this shapes sales motion, channels, and pricing model.` : "Shapes sales motion, channels, and pricing model."}
              </div>
              <div className="astra-choice-grid">
                {CUSTOMER_TYPES.map(c => (
                  <button
                    key={c.id}
                    onClick={() => setCustomer(c.id)}
                    className={`astra-choice-card${customer === c.id ? " is-selected" : ""}`}
                    style={{ display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{c.label}</div>
                      <div style={{ fontSize: 11, color: "var(--fm)" }}>{c.desc}</div>
                    </div>
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {step === "stage" && (
            <motion.div key="stage" custom={dir} variants={STEP_VARIANTS} initial="enter" animate="center" exit="exit" transition={{ duration: 0.22, ease: "easeOut" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
                Where are you right now?
              </div>
              <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
                {customerLabel ? `Agents adjust their output for a ${customerLabel.toLowerCase()} business at your starting point.` : "Agents adjust their output to your starting point."}
              </div>
              <div className="astra-choice-grid">
                {STAGES.map(s => (
                  <button
                    key={s.id}
                    onClick={() => setStage(s.id)}
                    className={`astra-choice-card${stage === s.id ? " is-selected" : ""}`}
                    style={{ display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{s.label}</div>
                      <div style={{ fontSize: 11, color: "var(--fm)" }}>{s.desc}</div>
                    </div>
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {step === "sub" && (
            <motion.div key="sub" custom={dir} variants={STEP_VARIANTS} initial="enter" animate="center" exit="exit" transition={{ duration: 0.22, ease: "easeOut" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
                {detailCopy.title}
              </div>
              <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
                {detailCopy.sub}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {subOptions.map(c => (
                  <button
                    key={c.id}
                    onClick={() => setSub(c.id)}
                    className={`astra-choice-card${sub === c.id ? " is-selected" : ""}`}
                    style={{ display: "flex", flexDirection: "column", gap: 4 }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>{c.label}</div>
                    <div style={{ fontSize: 10, color: "var(--fm)" }}>{c.desc}</div>
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        </div>

        {/* Nav */}
        <div className="astra-modal-actions" style={{ marginTop: 8 }}>
          {stepIdx > 0 && (
            <button
              className="btn"
              onClick={back}
              style={{ flex: "0 0 auto" }}
            >
              ← Back
            </button>
          )}
          <button
            className="btn pri"
            disabled={!canAdvance}
            onClick={advance}
            style={{ flex: 1 }}
          >
            {step === "sub" ? "Launch →" : "Next →"}
          </button>
        </div>
        </div>
        </div>
      </div>
    </div>
  );
}
