"use client";

import { useState } from "react";

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

type Step = "type" | "customer" | "stage" | "sub" | "done";

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

export const STACK_MAP: Record<string, string> = {
  saas: "idea_to_revenue",
  ecomm: "ecomm",
  local: "local_service",
  agency: "idea_to_revenue",
  content: "idea_to_revenue",
};

export function buildQuizContext(type: string, customer: string, stage: string, sub: string): string {
  const typeLabel = BIZ_TYPES.find(t => t.id === type)?.label || type;
  const customerLabel = CUSTOMER_TYPES.find(c => c.id === customer)?.label || customer;
  const stageLabel = STAGES.find(s => s.id === stage)?.label || stage;
  const subLabel = sub
    ? ([...LOCAL_CATEGORIES, ...ECOMM_CATEGORIES].find(c => c.id === sub)?.label || sub)
    : "";

  const lines = [
    `Business type: ${typeLabel}${subLabel ? ` — ${subLabel}` : ""}`,
    `Customers: ${customerLabel}`,
    `Stage: ${stageLabel}`,
  ];
  return lines.join("\n");
}

export default function BusinessQuizModal({ onComplete, onSkip }: Props) {
  const [step, setStep] = useState<Step>("type");
  const [bizType, setBizType] = useState("");
  const [customer, setCustomer] = useState("");
  const [stage, setStage] = useState("");
  const [sub, setSub] = useState("");

  const needsSub = bizType === "local" || bizType === "ecomm";
  const subOptions = bizType === "local" ? LOCAL_CATEGORIES : ECOMM_CATEGORIES;

  const advance = () => {
    if (step === "type") { setStep("customer"); return; }
    if (step === "customer") { setStep("stage"); return; }
    if (step === "stage") {
      if (needsSub) { setStep("sub"); return; }
      finish("");
      return;
    }
    if (step === "sub") { finish(sub); return; }
  };

  const finish = (subVal: string) => {
    const contextBlock = buildQuizContext(bizType, customer, stage, subVal);
    onComplete({ contextBlock, businessType: bizType, customerType: customer, stage, subCategory: subVal });
  };

  const canAdvance =
    (step === "type" && bizType) ||
    (step === "customer" && customer) ||
    (step === "stage" && stage) ||
    (step === "sub");

  const STEPS: Step[] = needsSub ? ["type", "customer", "stage", "sub"] : ["type", "customer", "stage"];
  const stepIdx = STEPS.indexOf(step);
  const progress = ((stepIdx + 1) / STEPS.length) * 100;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--surface, #111)", border: "1px solid var(--bd, #2a2a2a)",
        borderRadius: 12, padding: "32px 28px", width: "100%", maxWidth: 480,
        boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
      }}>
        {/* Progress bar */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: "var(--fm, #666)", fontFamily: "var(--font-ibm-mono)" }}>
              Step {stepIdx + 1} of {STEPS.length}
            </span>
            <button
              onClick={onSkip}
              style={{ fontSize: 11, color: "var(--fm, #666)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
            >
              Skip →
            </button>
          </div>
          <div style={{ height: 2, background: "var(--bd, #2a2a2a)", borderRadius: 2 }}>
            <div style={{ height: "100%", width: `${progress}%`, background: "var(--blue, #3b82f6)", borderRadius: 2, transition: "width 0.25s ease" }} />
          </div>
        </div>

        {step === "type" && (
          <>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              What type of business is this?
            </div>
            <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
              Helps Astra tailor agent prompts and suggested integrations.
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {BIZ_TYPES.map(t => (
                <button
                  key={t.id}
                  onClick={() => setBizType(t.id)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
                    background: bizType === t.id ? "var(--blue-subtle, rgba(59,130,246,0.1))" : "var(--surface2, #1a1a1a)",
                    border: `1px solid ${bizType === t.id ? "var(--blue, #3b82f6)" : "var(--bd, #2a2a2a)"}`,
                    borderRadius: 8, cursor: "pointer", textAlign: "left", width: "100%",
                  }}
                >
                  <span style={{ fontSize: 18, lineHeight: 1, color: "var(--fm)" }}>{t.icon}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{t.label}</div>
                    <div style={{ fontSize: 11, color: "var(--fm)" }}>{t.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {step === "customer" && (
          <>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              Who are your customers?
            </div>
            <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
              Shapes sales motion, channels, and pricing model.
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {CUSTOMER_TYPES.map(c => (
                <button
                  key={c.id}
                  onClick={() => setCustomer(c.id)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
                    background: customer === c.id ? "var(--blue-subtle, rgba(59,130,246,0.1))" : "var(--surface2, #1a1a1a)",
                    border: `1px solid ${customer === c.id ? "var(--blue, #3b82f6)" : "var(--bd, #2a2a2a)"}`,
                    borderRadius: 8, cursor: "pointer", textAlign: "left", width: "100%",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{c.label}</div>
                    <div style={{ fontSize: 11, color: "var(--fm)" }}>{c.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {step === "stage" && (
          <>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              Where are you right now?
            </div>
            <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
              Agents adjust their output to your starting point.
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {STAGES.map(s => (
                <button
                  key={s.id}
                  onClick={() => setStage(s.id)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
                    background: stage === s.id ? "var(--blue-subtle, rgba(59,130,246,0.1))" : "var(--surface2, #1a1a1a)",
                    border: `1px solid ${stage === s.id ? "var(--blue, #3b82f6)" : "var(--bd, #2a2a2a)"}`,
                    borderRadius: 8, cursor: "pointer", textAlign: "left", width: "100%",
                  }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{s.label}</div>
                    <div style={{ fontSize: 11, color: "var(--fm)" }}>{s.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {step === "sub" && (
          <>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              {bizType === "local" ? "What kind of service?" : "What are you selling?"}
            </div>
            <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 20 }}>
              Narrows agent instructions to your specific category.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {subOptions.map(c => (
                <button
                  key={c.id}
                  onClick={() => setSub(c.id)}
                  style={{
                    display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px",
                    background: sub === c.id ? "var(--blue-subtle, rgba(59,130,246,0.1))" : "var(--surface2, #1a1a1a)",
                    border: `1px solid ${sub === c.id ? "var(--blue, #3b82f6)" : "var(--bd, #2a2a2a)"}`,
                    borderRadius: 8, cursor: "pointer", textAlign: "left",
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>{c.label}</div>
                  <div style={{ fontSize: 10, color: "var(--fm)" }}>{c.desc}</div>
                </button>
              ))}
            </div>
          </>
        )}

        {/* Nav */}
        <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
          {stepIdx > 0 && (
            <button
              className="btn"
              onClick={() => {
                const prev = STEPS[stepIdx - 1];
                setStep(prev);
              }}
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
            {step === "sub" || (!needsSub && step === "stage") ? "Launch →" : "Next →"}
          </button>
        </div>

      </div>
    </div>
  );
}
