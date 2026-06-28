"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, getStacks, getAgentCatalog, recommendStack, getStackReadiness, getSetupStatus, saveServiceCredential, getComposioOAuthUrls, setupAccounts, submitGoal } from "@/lib/api";
import ServiceLogo from "@/components/ServiceLogo";
import type { AgentStackTemplate, AgentCatalogEntry, StackReadiness } from "@/lib/api";
import {
  BIZ_TYPES, CUSTOMER_TYPES, STAGES, LOCAL_CATEGORIES, ECOMM_CATEGORIES,
  STACK_MAP, buildQuizContext, type QuizResult,
} from "@/components/BusinessQuizModal";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Constants ─────────────────────────────────────────────────────────────────

const STACK_ICONS: Record<string, string> = {
  idea_to_revenue: "▲", sales: "⊕", marketing: "✦",
  founder_ops: "◎", support: "◈", product: "◇", custom: "✦",
  ecomm: "◈", local_service: "⬡",
};

const FALLBACK_STACKS: AgentStackTemplate[] = [
  { stack_id: "idea_to_revenue", name: "Idea to Revenue Stack", target_user: "Founders starting from a rough startup idea.", primary_outcome: "Turn a startup idea into a launch-ready company foundation.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "sales", name: "Sales Stack", target_user: "Existing teams that need repeatable pipeline without hiring a full sales team.", primary_outcome: "Turn a revenue goal into a measurable outbound and CRM operating system.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "marketing", name: "Marketing Stack", target_user: "Teams that need campaigns, positioning, content, and launch execution.", primary_outcome: "Turn a growth goal into a campaign engine with assets, channels, and measurement.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "founder_ops", name: "Founder Ops Stack", target_user: "Founders who need an operating system for priorities, fundraising, decisions, and execution.", primary_outcome: "Turn company context into a weekly operating cadence and founder command center.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "support", name: "Customer Support Stack", target_user: "Teams that need support workflows, knowledge base, and customer feedback loops.", primary_outcome: "Turn support chaos into a support operating system with triage, answers, and escalation.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "product", name: "Product Stack", target_user: "Teams that need product strategy, roadmap, specs, and delivery coordination.", primary_outcome: "Turn product ambiguity into a roadmap, specs, architecture, and delivery plan.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "ecomm", name: "Ecommerce Stack", target_user: "Founders launching or scaling an online store (physical goods, digital products, subscriptions, or print-on-demand).", primary_outcome: "Launch a complete ecommerce operation: store, product copy, email flows, paid + organic acquisition, and supply chain basics.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  { stack_id: "local_service", name: "Local Service Stack", target_user: "Small service businesses: salons, barbershops, gyms, restaurants, cleaning, tutoring, pet care, and other local/appointment-based operations.", primary_outcome: "Launch a complete local service operation: booking site, Google Business presence, local acquisition, and operational playbook.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
];

const TOKEN_CONFIG: Record<string, { service: string; credKey: string; createUrl: string; placeholder: string }> = {
  vercel:           { service: "vercel",   credKey: "token",            createUrl: "https://vercel.com/account/tokens",              placeholder: "xxxxxxxxxxxxxxxx" },
  supabase:         { service: "supabase", credKey: "service_role_key", createUrl: "https://supabase.com/dashboard/account/tokens",  placeholder: "sbp_..." },
  clerk:            { service: "clerk",    credKey: "secret_key",        createUrl: "https://dashboard.clerk.com",                   placeholder: "sk_live_..." },
  figma:            { service: "figma",    credKey: "token",            createUrl: "https://www.figma.com/settings",                 placeholder: "fig-..." },
  notion:           { service: "notion",   credKey: "token",            createUrl: "https://www.notion.so/my-integrations",          placeholder: "ntn_..." },
  google_drive:     { service: "google",   credKey: "access_token",     createUrl: "https://console.cloud.google.com",               placeholder: "ya29..." },
  google_sheets:    { service: "google",   credKey: "access_token",     createUrl: "https://console.cloud.google.com",               placeholder: "ya29..." },
  analytics:        { service: "analytics",credKey: "api_key",          createUrl: "https://posthog.com/settings",                   placeholder: "phc_..." },
  helpdesk:         { service: "helpdesk", credKey: "token",            createUrl: "https://www.zendesk.com",                        placeholder: "..." },
  crm:              { service: "crm",      credKey: "access_token",     createUrl: "https://app.hubspot.com/api-key",                placeholder: "..." },
  slack:            { service: "slack",    credKey: "bot_token",        createUrl: "https://api.slack.com/apps",                     placeholder: "xoxb-..." },
  website_cms:      { service: "vercel",   credKey: "token",            createUrl: "https://vercel.com/account/tokens",              placeholder: "..." },
  product_tracker:  { service: "linear",   credKey: "api_key",          createUrl: "https://linear.app/settings/api",               placeholder: "lin_api_..." },
  linear:           { service: "linear",   credKey: "api_key",          createUrl: "https://linear.app/settings/api",               placeholder: "lin_api_..." },
};

const COMPOSIO_APPS = new Set([
  // Only services that still require Composio OAuth (no direct connection yet)
  "google_drive",
  "google_sheets",
]);

const COMPOSIO_APP_KEYS: Record<string, string> = {
  google_calendar: "googlecalendar",
  google_sheets: "google_drive",
  product_tracker: "linear",
};

// ── Design tokens ─────────────────────────────────────────────────────────────

const T = {
  bg:            "#05070D",           // page background
  white:         "#0D111C",           // panel / card surface (dark)
  surface:       "#141926",           // elevated surface within panel
  textPrimary:   "#F6F8FF",
  textSecondary: "#CAD2E4",
  textMuted:     "#8590A6",
  grey:          "#8590A6",
  blue:          "#0B31FF",
  blueHover:     "#0024D9",
  blueTint:      "rgba(11,49,255,0.12)",
  blueMid:       "rgba(11,49,255,0.35)",
  mint:          "#7CFFC6",
  border:        "rgba(255,255,255,0.09)",
  borderStrong:  "rgba(255,255,255,0.18)",
  green:         "#22C55E",
  greenTint:     "rgba(34,197,94,0.10)",
  greenBorder:   "rgba(34,197,94,0.30)",
  red:           "#F87171",
  redTint:       "rgba(248,113,113,0.10)",
  redBorder:     "rgba(248,113,113,0.30)",
  shadow:        "0 1px 4px rgba(0,0,0,0.5)",
  shadowMd:      "0 8px 40px rgba(0,0,0,0.6)",
};

// ── Shared style objects ──────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  borderRadius: 12,
  border: `1px solid ${T.border}`,
  background: T.white,
  padding: "14px 16px",
  cursor: "pointer",
  transition: "border-color 0.14s, background 0.14s",
};

const CARD_SELECTED: React.CSSProperties = {
  ...CARD,
  border: `1.5px solid ${T.blue}`,
  background: T.blueTint,
};

const BTN_PRIMARY: React.CSSProperties = {
  padding: "10px 28px",
  borderRadius: 999,
  background: T.blue,
  color: "#FFFFFF",
  border: "none",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  letterSpacing: "0.01em",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  transition: "opacity 0.15s",
};

const BTN_GHOST: React.CSSProperties = {
  padding: "10px 20px",
  borderRadius: 999,
  background: "transparent",
  color: T.textMuted,
  border: `1px solid ${T.border}`,
  fontSize: 13,
  cursor: "pointer",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  transition: "border-color 0.14s",
};

const INPUT: React.CSSProperties = {
  width: "100%",
  padding: "11px 14px",
  borderRadius: 10,
  border: `1px solid ${T.border}`,
  background: "#05070D",
  color: T.textPrimary,
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  transition: "border-color 0.14s",
};

const LABEL: React.CSSProperties = {
  fontSize: 12,
  color: T.textMuted,
  fontWeight: 500,
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 11,
  color: T.textMuted,
  fontWeight: 500,
  marginBottom: 6,
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ step, total = 4 }: { step: number; total?: number }) {
  const pct = total <= 1 ? 100 : Math.round((step / (total - 1)) * 100);
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ height: 2, background: "rgba(255,255,255,0.08)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: "100%",
          background: T.blue,
          borderRadius: 2,
          transform: `scaleX(${pct / 100})`,
          transformOrigin: "left",
          transition: "transform 0.35s cubic-bezier(0.22,1,0.36,1)",
        }} />
      </div>
      <div style={{ marginTop: 10, fontSize: 11, color: T.textMuted }}>
        Step {step + 1} of {total}
      </div>
    </div>
  );
}

// ── Step 2: Custom agent picker ───────────────────────────────────────────────

const GROUP_ORDER = ["research", "legal", "marketing", "sales", "technical", "finance", "ops", "web", "design"];
const GROUP_LABELS: Record<string, string> = {
  research: "Research", legal: "Legal", marketing: "Marketing", sales: "Sales",
  technical: "Technical", finance: "Finance", ops: "Ops", web: "Web", design: "Design",
};
const GROUP_EMOJI: Record<string, string> = {
  research: "◈", legal: "≡", marketing: "✦", sales: "⊕",
  technical: "⚙", finance: "▦", ops: "▲", web: "◎", design: "◉",
};

const _REQUIRED = new Set(["research"]);

// Fallback catalog — mirrors backend/stacks/catalog.py exactly.
// Used when the backend is unreachable so the UI always works.
const FALLBACK_CATALOG: AgentCatalogEntry[] = [
  { id: "research",             name: "Research",              description: "Market sizing, competitor analysis, TAM/SAM/SOM, customer profile. Deep web, news, patent, and video research.", produces: ["market_research_report","competitor_analysis","customer_personas","market_brief"], depends_on: [] },
  { id: "research_competitors", name: "Competitor Intel",      description: "Deep competitor intelligence: named competitors, pricing pages, funding and review mining, market maps.",           produces: ["competitor_table","whitespace_opportunities"],                                    depends_on: [] },
  { id: "research_execution",   name: "Execution Strategy",    description: "GTM strategy, revenue model, recommended tech stack, unit economics, and a first-90-days plan.",                  produces: ["execution_strategy","gtm_strategy","recommended_tech_stack"],                     depends_on: [] },
  { id: "research_market",      name: "Market Research",       description: "Deep TAM/SAM/SOM sizing, ICP profiling, pricing benchmarks, competitor landscape.",                                produces: ["tam_sam_som_report","icp_brief","pricing_benchmark"],                             depends_on: [] },
  { id: "research_financial",   name: "Financial Research",    description: "Unit economics benchmarks, fundraising comps, burn rate analysis, investor readiness scoring.",                   produces: ["unit_economics_report","fundraising_comps"],                                      depends_on: ["research_market"] },
  { id: "research_regulatory",  name: "Regulatory Research",   description: "GDPR/HIPAA/SOC2 compliance mapping, regulatory risk flags, compliance checklist PDF.",                            produces: ["compliance_checklist","regulatory_risk_report"],                                  depends_on: ["research_market"] },
  { id: "legal",                name: "Legal",                 description: "Privacy policies, terms of service, founder agreements, IP assignment, entity formation guidance.",               produces: ["legal_checklist","policy_outline","founder_agreement"],                          depends_on: ["research"] },
  { id: "legal_docs",           name: "Legal Documents",       description: "Privacy policy, terms of service, NDA, IP assignment — full PDFs.",                                               produces: ["privacy_policy_pdf","tos_pdf","nda_pdf"],                                         depends_on: ["research"] },
  { id: "legal_entity",         name: "Entity Formation",      description: "LLC/C-Corp formation guidance, EIN walkthrough, founder agreement, cap table setup.",                             produces: ["entity_formation_guide","founder_agreement_pdf"],                                 depends_on: ["research"] },
  { id: "legal_ip",             name: "IP Strategy",           description: "Patent search, trademark clearance, IP assignment, trade secret playbook.",                                       produces: ["patent_landscape","trademark_report"],                                            depends_on: ["research"] },
  { id: "marketing",            name: "Marketing",             description: "Go-to-market strategy, social media content, Meta ad copy, email campaigns, and growth channel planning.",        produces: ["gtm_plan","launch_content","ad_creatives","email_sequence"],                     depends_on: ["research"] },
  { id: "marketing_content",    name: "Content Marketing",     description: "Instagram Reels scripts, TikTok packages, Meta ad copy, 30-day content calendar PDF.",                           produces: ["reels_scripts","tiktok_package","meta_ads","content_calendar_pdf"],              depends_on: ["research"] },
  { id: "marketing_outreach",   name: "Outreach & Lead Gen",   description: "Hunter lead discovery, cold email sequences, SendGrid campaign execution.",                                       produces: ["lead_list","email_sequence","outreach_report"],                                   depends_on: ["research"] },
  { id: "marketing_seo",        name: "SEO Strategy",          description: "Keyword research, content calendar, blog outlines, on-page SEO checklist PDF.",                                  produces: ["keyword_research","seo_content_calendar"],                                        depends_on: ["research"] },
  { id: "marketing_paid",       name: "Paid Advertising",      description: "Google/Meta campaign strategy, budget allocation, creative briefs, audience targeting PDF.",                     produces: ["paid_strategy_pdf","campaign_briefs"],                                            depends_on: ["research"] },
  { id: "sales",                name: "Sales & Outreach",      description: "Lead discovery, personalized multi-step outreach sequences, and CRM contact records.",                            produces: ["leads","outreach_sequences","crm_contacts"],                                      depends_on: ["research"] },
  { id: "sales_pipeline",       name: "Sales Pipeline",        description: "CRM stage design, MEDDIC/BANT qualification, objection scripts, sales playbook PDF.",                            produces: ["sales_playbook_pdf","crm_stage_map"],                                             depends_on: ["research"] },
  { id: "sales_enablement",     name: "Sales Enablement",      description: "Pitch deck, one-pager, case study templates, competitive battlecards PDFs.",                                     produces: ["pitch_deck_pdf","one_pager_pdf","battlecards_pdf"],                               depends_on: ["research"] },
  { id: "technical",            name: "Technical",             description: "Software architecture, MVP development, GitHub repo creation, Vercel deployment, full-stack planning.",           produces: ["mvp_roadmap","technical_plan","github_repo","deployed_app"],                     depends_on: ["research"] },
  { id: "technical_scaffold",   name: "Code Scaffold",         description: "GitHub repo creation, Claude Code CLI scaffolding — 20-30 working files committed.",                              produces: ["github_repo","scaffolded_codebase"],                                              depends_on: ["research"] },
  { id: "technical_infra",      name: "Infrastructure",        description: "CI/CD pipeline, Docker setup, hosting config, monitoring, runbook PDF.",                                          produces: ["cicd_config","docker_compose","infra_runbook_pdf"],                               depends_on: ["technical_scaffold"] },
  { id: "technical_data",       name: "Data Architecture",     description: "ER diagram, Postgres schema, analytics event plan, data pipeline spec PDF.",                                     produces: ["er_diagram","postgres_schema"],                                                    depends_on: ["research"] },
  { id: "finance_model",        name: "Financial Model",       description: "12-month revenue model, 3 scenarios (base/bull/bear), unit economics, P&L PDF.",                                 produces: ["financial_model_pdf","unit_economics_sheet"],                                     depends_on: ["research_financial"] },
  { id: "finance_fundraise",    name: "Fundraising Strategy",  description: "Raise recommendation, investor target list, SAFE/priced terms, pitch narrative PDF.",                            produces: ["raise_recommendation","investor_list"],                                           depends_on: ["finance_model"] },
  { id: "ops",                  name: "Operations",            description: "Synthesizes every agent lane into a founder operating plan: 30-day calendar, investor memo, Notion/Linear setup.", produces: ["thirty_day_plan","investor_memo","founder_next_actions"],                        depends_on: ["research"] },
  { id: "web",                  name: "Web",                   description: "Landing page generation, Vercel deployment, conversion-focused copy and website architecture.",                  produces: ["landing_page","website_copy","deployed_url"],                                     depends_on: ["research"] },
  { id: "design",               name: "Design & Brand",        description: "Visual identity, logo and wordmark generation, brand color systems, wireframes, and design spec.",               produces: ["design_spec","brand_direction","logo"],                                           depends_on: ["research"] },
];

function StepCustomStack({ selected, onToggle, onBack, onNext, stackName, setStackName }: {
  selected: string[]; onToggle: (id: string) => void; onBack: () => void; onNext: () => void;
  stackName: string; setStackName: (v: string) => void;
}) {
  const [catalog, setCatalog] = useState<AgentCatalogEntry[]>(FALLBACK_CATALOG);
  const [teamNames, setTeamNames] = useState<Record<string, string>>({});
  const [editingTeam, setEditingTeam] = useState<string | null>(null);
  useEffect(() => { getAgentCatalog().then(c => { if (c.length > 0) setCatalog(c); }).catch(() => {}); }, []);

  const grouped: Record<string, AgentCatalogEntry[]> = {};
  catalog.forEach(agent => {
    const group = agent.id.includes("_") ? agent.id.split("_")[0] : agent.id;
    if (!grouped[group]) grouped[group] = [];
    grouped[group].push(agent);
  });

  const getTeamLabel = (group: string) => teamNames[group] ?? GROUP_LABELS[group] ?? group;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Build your stack
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Name your stack, rename sub-teams, then pick the agents you need.
        </p>
      </div>

      {/* Stack name */}
      <div>
        <label style={{ ...SECTION_LABEL, display: "block", marginBottom: 6 }}>Stack name</label>
        <input
          value={stackName}
          onChange={e => setStackName(e.target.value)}
          placeholder="e.g. My Growth Stack"
          style={{ width: "100%", padding: "9px 12px", fontSize: 14, fontWeight: 600, border: `1.5px solid ${T.border}`, borderRadius: 10, background: "#05070D", color: T.textPrimary, outline: "none", fontFamily: "var(--font-geist-sans), sans-serif", boxSizing: "border-box" }}
        />
      </div>

      {/* Agent groups */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxHeight: 460, overflowY: "auto", paddingRight: 4 }}>
        {GROUP_ORDER.filter(g => grouped[g]).map(group => {
          const groupAgents = grouped[group];
          const groupSelected = groupAgents.filter(a => selected.includes(a.id)).length;
          return (
            <div key={group}>
              {/* Group header with inline rename */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <span style={{ fontSize: 13 }}>{GROUP_EMOJI[group]}</span>
                {editingTeam === group ? (
                  <input
                    autoFocus
                    value={teamNames[group] ?? GROUP_LABELS[group]}
                    onChange={e => setTeamNames(p => ({ ...p, [group]: e.target.value }))}
                    onBlur={() => setEditingTeam(null)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === "Escape") setEditingTeam(null); }}
                    style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", border: `1px solid ${T.blue}`, borderRadius: 6, padding: "2px 7px", background: T.blueTint, color: T.blue, outline: "none", width: 130, fontFamily: "var(--font-geist-sans), sans-serif" }}
                  />
                ) : (
                  <span style={{ ...SECTION_LABEL, cursor: "pointer" }} onClick={() => setEditingTeam(group)} title="Click to rename">
                    {getTeamLabel(group)}
                    <span style={{ marginLeft: 5, fontSize: 9, color: T.textMuted, fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>✎</span>
                  </span>
                )}
                <span style={{ marginLeft: "auto", fontSize: 10, color: groupSelected > 0 ? T.blue : T.textMuted }}>
                  {groupSelected}/{groupAgents.length}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {groupAgents.map(agent => {
                  const active = selected.includes(agent.id);
                  const required = _REQUIRED.has(agent.id);
                  return (
                    <div
                      key={agent.id}
                      onClick={() => { if (!required) onToggle(agent.id); }}
                      style={{
                        borderRadius: 10,
                        border: `1.5px solid ${active ? T.blue : T.border}`,
                        background: active ? T.blueTint : T.white,
                        padding: "9px 11px",
                        cursor: required ? "default" : "pointer",
                        transition: "border-color 0.12s, background 0.12s",
                        opacity: required ? 0.75 : 1,
                        boxShadow: T.shadow,
                      }}
                    >
                      <div style={{ fontSize: 11, fontWeight: 600, color: active ? T.blue : T.textPrimary, display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: "var(--font-geist-sans), sans-serif" }}>
                        {agent.name}
                        {required
                          ? <span style={{ fontSize: 8, color: T.blue, textTransform: "uppercase", letterSpacing: "0.06em" }}>required</span>
                          : active && <span style={{ color: T.blue, fontSize: 12 }}>✓</span>}
                      </div>
                      <p style={{ fontSize: 9.5, color: T.textMuted, margin: "3px 0 0", lineHeight: 1.4 }}>
                        {agent.description.slice(0, 60)}{agent.description.length > 60 ? "…" : ""}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ fontSize: 12, color: T.textMuted, textAlign: "center" }}>
        {selected.length === 0 ? "Select at least 1 agent" : `${selected.length} agent${selected.length === 1 ? "" : "s"} selected across ${GROUP_ORDER.filter(g => grouped[g] && grouped[g].some(a => selected.includes(a.id))).length} team${GROUP_ORDER.filter(g => grouped[g] && grouped[g].some(a => selected.includes(a.id))).length === 1 ? "" : "s"}`}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button style={BTN_GHOST} onClick={onBack}>← Back</button>
        <button
          style={{ ...BTN_PRIMARY, opacity: selected.length === 0 ? 0.4 : 1 }}
          onClick={onNext}
          disabled={selected.length === 0}
        >
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── Step 3: Connect integrations ──────────────────────────────────────────────

function StepConnectIntegrations({ stackName, readiness, founderId, userEmail, onBack, onNext }: {
  stackName: string; readiness: StackReadiness | null;
  founderId: string; userEmail: string;
  onBack: () => void; onNext: () => void;
}) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [connected, setConnected] = useState<Record<string, boolean>>({});
  const [tokenValues, setTokenValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [composioOAuthUrls, setComposioOAuthUrls] = useState<Record<string, string>>({});
  const [autoEmail, setAutoEmail] = useState(userEmail || "");
  const [autoPassword, setAutoPassword] = useState("");
  const [autoProvisioning, setAutoProvisioning] = useState(false);
  const [autoSummary, setAutoSummary] = useState<string[]>([]);
  const composioConnected = !!connected["__composio__"];

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const updates: Record<string, boolean> = {};
    if (p.get("github_connected") === "1") { updates["github"] = true; window.history.replaceState({}, "", window.location.pathname); }
    if (p.get("stripe_connected") === "1") { updates["stripe"] = true; window.history.replaceState({}, "", window.location.pathname); }
    if (Object.keys(updates).length) setConnected(prev => ({ ...prev, ...updates }));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const nextConnected: Record<string, boolean> = {};
    for (const connector of readiness?.connectors ?? []) {
      if (connector.connected) nextConnected[connector.key] = true;
    }

    getSetupStatus(founderId)
      .then((status) => {
        if (cancelled) return;
        const appStatus = status.apps ?? {};
        setConnected((prev) => ({
          ...prev,
          ...nextConnected,
          github: prev.github || status.github,
          vercel: prev.vercel || status.vercel,
          sendgrid: prev.sendgrid || status.sendgrid,
          supabase: prev.supabase || status.supabase,
          __composio__: prev.__composio__,
          ...Object.fromEntries(Object.entries(appStatus).filter(([, value]) => value)),
        }));
      })
      .catch(() => {
        if (!cancelled && Object.keys(nextConnected).length) {
          setConnected((prev) => ({ ...prev, ...nextConnected }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [founderId, readiness]);

  const required = readiness?.connectors.filter(c => c.required) ?? [];
  const optional = readiness?.connectors.filter(c => !c.required) ?? [];
  const hasComposioApp = [...required, ...optional].some(c => COMPOSIO_APPS.has(c.key));

  const ICONS: Record<string, string> = {
    github: "●", vercel: "▲", supabase: "◆", clerk: "◇", gmail: "◻",
    google_drive: "△", google_sheets: "▦", google_calendar: "▣", slack: "◎",
    notion: "▷", linear: "◈", crm: "⊕", linkedin: "▪", meta_ads: "◻",
    analytics: "▲", website_cms: "◎", helpdesk: "◈", figma: "◈", stripe: "≡",
  };

  const cardBtnStyle: React.CSSProperties = {
    padding: "6px 16px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    flexShrink: 0,
    whiteSpace: "nowrap",
    background: T.blue,
    color: "#FFFFFF",
    border: "none",
    cursor: "pointer",
    fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  };

  const expandedBtnStyle: React.CSSProperties = {
    ...cardBtnStyle,
    background: T.blueTint,
    color: T.blue,
    border: `1px solid ${T.blueMid}`,
  };

  const pasteInputStyle: React.CSSProperties = {
    flex: 1,
    padding: "8px 12px",
    borderRadius: 10,
    fontSize: 12,
    fontFamily: "var(--font-mono, monospace)",
    border: `1px solid ${T.border}`,
    background: "#05070D",
    color: T.textPrimary,
    outline: "none",
  };

  async function connectGitHub() {
    try {
      const res = await apiFetch(`${BASE}/github/oauth-url/${founderId}`);
      const data = await res.json();
      if (data.url) window.location.href = data.url;
    } catch { setErrors(e => ({ ...e, github: "Failed to reach server" })); }
  }

  async function connectStripe() {
    try {
      const res = await apiFetch(`${BASE}/stripe/oauth-url/${founderId}?email=${encodeURIComponent(userEmail)}`);
      const data = await res.json();
      if (data.url) window.location.href = data.url;
    } catch { setErrors(e => ({ ...e, stripe: "Failed to reach server" })); }
  }

  async function saveComposio() {
    const val = tokenValues["__composio__"]?.trim();
    if (!val) return;
    setSaving("__composio__");
    try {
      await saveServiceCredential(founderId, "composio", { api_key: val });
      const urls = await getComposioOAuthUrls(founderId).catch(() => ({} as Record<string, string>));
      setConnected(prev => ({ ...prev, "__composio__": true }));
      setComposioOAuthUrls(urls);
      setExpandedKey(null);
    } catch (e) { setErrors(prev => ({ ...prev, "__composio__": e instanceof Error ? e.message : "Save failed" })); }
    finally { setSaving(null); }
  }

  async function saveToken(key: string) {
    const cfg = TOKEN_CONFIG[key];
    const val = tokenValues[key]?.trim();
    if (!cfg || !val) return;
    setSaving(key);
    try {
      await saveServiceCredential(founderId, cfg.service, { [cfg.credKey]: val });
      setConnected(prev => ({ ...prev, [key]: true }));
      setExpandedKey(null);
    } catch (e) { setErrors(prev => ({ ...prev, [key]: e instanceof Error ? e.message : "Save failed" })); }
    finally { setSaving(null); }
  }

  function connectComposioApp(key: string) {
    const appKey = COMPOSIO_APP_KEYS[key] ?? key;
    const url = composioOAuthUrls[appKey] ?? composioOAuthUrls[key];
    if (url) { window.open(url, "_blank", "width=860,height=640"); setConnected(prev => ({ ...prev, [key]: true })); }
  }

  function toggleExpand(key: string) {
    if (!TOKEN_CONFIG[key] && key !== "__composio__") return;
    if (key !== "__composio__" && TOKEN_CONFIG[key]) {
      window.open(TOKEN_CONFIG[key].createUrl, `connect_${key}`, "width=1060,height=720,scrollbars=yes,resizable=yes");
    } else if (key === "__composio__") {
      window.open("https://app.composio.dev/settings", "composio", "width=1060,height=720,scrollbars=yes");
    }
    setExpandedKey(prev => prev === key ? null : key);
  }

  async function runAutoProvision() {
    if (!autoEmail.trim() || !autoPassword.trim()) return;
    setAutoProvisioning(true);
    setAutoSummary([]);
    try {
      const result = await setupAccounts(founderId, autoEmail.trim(), autoPassword, readiness?.stack_id ?? "", true);
      const serviceCreated = (key: string) => Boolean((result.services?.[key] as { created?: boolean } | undefined)?.created);
      setConnected(prev => ({
        ...prev,
        github: prev.github || serviceCreated("github"),
        vercel: prev.vercel || serviceCreated("vercel"),
        sendgrid: prev.sendgrid || serviceCreated("sendgrid"),
        supabase: prev.supabase || serviceCreated("supabase"),
        __composio__: prev.__composio__ || serviceCreated("composio"),
      }));
      if (result.composio_oauth_urls) setComposioOAuthUrls(result.composio_oauth_urls);
      setAutoSummary([
        ...(result.summary ?? []),
        ...(result.pending_manual_connectors?.length
          ? [`Manual follow-up still needed: ${result.pending_manual_connectors.join(", ")}`]
          : []),
      ]);
    } catch (e) {
      setAutoSummary([e instanceof Error ? e.message : "Auto-connect failed"]);
    } finally {
      setAutoProvisioning(false);
    }
  }

  function card(key: string, icon: string, label: string, purpose: string, isRequired: boolean) {
    const isConnected = !!connected[key];
    const isExpanded = expandedKey === key;
    const cfg = TOKEN_CONFIG[key];
    const isGH = key === "github";
    const isStripe = key === "stripe";
    const isComp = COMPOSIO_APPS.has(key);

    let borderStyle: string;
    let bgStyle: string;
    if (isConnected) {
      borderStyle = `1.5px solid ${T.greenBorder}`;
      bgStyle = T.greenTint;
    } else if (isExpanded) {
      borderStyle = `1.5px solid ${T.blueMid}`;
      bgStyle = T.blueTint;
    } else if (isRequired) {
      borderStyle = `1.5px solid ${T.redBorder}`;
      bgStyle = T.redTint;
    } else {
      borderStyle = `1px solid ${T.border}`;
      bgStyle = T.white;
    }

    return (
      <div key={key} style={{ borderRadius: 14, border: borderStyle, background: bgStyle, transition: "border 0.2s, background 0.2s", boxShadow: T.shadow }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
          <ServiceLogo serviceKey={key} label={label} size={24} fallback={icon} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>{label}</span>
              {isRequired && !isConnected && (
                <span style={{
                  fontSize: 9, padding: "2px 6px", borderRadius: 999,
                  background: T.redTint, color: T.red, fontWeight: 600,
                  letterSpacing: "0.07em", textTransform: "uppercase",
                  border: `1px solid ${T.redBorder}`,
                }}>Required</span>
              )}
              {isConnected && (
                <span style={{ fontSize: 10, color: T.green, fontWeight: 600 }}>Connected</span>
              )}
            </div>
            <span style={{ fontSize: 11, color: T.textMuted }}>{purpose}</span>
          </div>
          {!isConnected && (
            isGH ? (
              <button style={cardBtnStyle} onClick={connectGitHub}>Connect ↗</button>
            ) : isStripe ? (
              <button style={cardBtnStyle} onClick={connectStripe}>Connect ↗</button>
            ) : isComp && composioConnected ? (
              <button style={cardBtnStyle} onClick={() => connectComposioApp(key)}>Connect ↗</button>
            ) : isComp ? (
              <span style={{ fontSize: 11, color: T.textMuted, flexShrink: 0 }}>Set up Composio first</span>
            ) : cfg ? (
              <button style={isExpanded ? expandedBtnStyle : cardBtnStyle} onClick={() => toggleExpand(key)}>
                {isExpanded ? "Popup open ↗" : "Connect ↗"}
              </button>
            ) : (
              <button style={cardBtnStyle} onClick={() => window.open("/integrations", "_blank")}>Connect ↗</button>
            )
          )}
        </div>
        {isExpanded && cfg && !isConnected && (
          <div style={{
            borderTop: `1px solid ${T.border}`,
            padding: "12px 16px",
            background: T.blueTint,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}>
            <p style={{ margin: 0, fontSize: 11, color: T.textSecondary, lineHeight: 1.5 }}>
              Copy your token from the popup, paste it here, then Save.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={tokenValues[key] ?? ""}
                onChange={e => setTokenValues(v => ({ ...v, [key]: e.target.value }))}
                placeholder={cfg.placeholder}
                onKeyDown={e => e.key === "Enter" && saveToken(key)}
                style={pasteInputStyle}
              />
              <button
                onClick={() => saveToken(key)}
                disabled={saving === key || !tokenValues[key]?.trim()}
                style={{ ...cardBtnStyle, padding: "0 16px", opacity: (!tokenValues[key]?.trim() || saving === key) ? 0.5 : 1 }}
              >
                {saving === key ? "…" : "Save"}
              </button>
            </div>
            {errors[key] && <p style={{ margin: 0, fontSize: 11, color: T.red }}>{errors[key]}</p>}
          </div>
        )}
      </div>
    );
  }

  const composioCard = (
    <div style={{
      borderRadius: 14,
      border: composioConnected ? `1.5px solid ${T.greenBorder}` : expandedKey === "__composio__" ? `1.5px solid ${T.blueMid}` : `1px solid ${T.border}`,
      background: composioConnected ? T.greenTint : expandedKey === "__composio__" ? T.blueTint : T.white,
      transition: "border 0.2s, background 0.2s",
      boxShadow: T.shadow,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
        <span style={{ fontSize: 16, lineHeight: 1, flexShrink: 0, color: T.blue }}>◈</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>Composio</span>
            {composioConnected && <span style={{ fontSize: 10, color: T.green, fontWeight: 600 }}>Connected</span>}
          </div>
          <span style={{ fontSize: 11, color: T.textMuted }}>Enables Gmail, LinkedIn, Notion, Calendar</span>
        </div>
        {!composioConnected && (
          <button
            style={expandedKey === "__composio__" ? expandedBtnStyle : cardBtnStyle}
            onClick={() => toggleExpand("__composio__")}
          >
            {expandedKey === "__composio__" ? "Popup open ↗" : "Connect ↗"}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Connect your tools
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Based on <strong style={{ color: T.textPrimary }}>{stackName}</strong>. Everything connects right here.
        </p>
      </div>

      <div style={{
        border: `1px solid ${T.border}`,
        borderRadius: 14,
        background: T.blueTint,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.textPrimary }}>Auto-connect required accounts</div>
            <div style={{ fontSize: 11, color: T.textMuted, lineHeight: 1.5 }}>
              For testing, Astra will try to sign up or log in and fetch the keys for the required stack accounts automatically.
            </div>
          </div>
          <button
            style={{ ...cardBtnStyle, opacity: autoProvisioning || !autoEmail.trim() || !autoPassword.trim() ? 0.55 : 1 }}
            onClick={runAutoProvision}
            disabled={autoProvisioning || !autoEmail.trim() || !autoPassword.trim()}
          >
            {autoProvisioning ? "Connecting…" : "Auto-connect now"}
          </button>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            value={autoEmail}
            onChange={e => setAutoEmail(e.target.value)}
            placeholder="Email"
            style={{ ...pasteInputStyle, minWidth: 220, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}
          />
          <input
            type="password"
            value={autoPassword}
            onChange={e => setAutoPassword(e.target.value)}
            placeholder="Password"
            style={{ ...pasteInputStyle, minWidth: 220, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}
          />
        </div>
        {autoSummary.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {autoSummary.map((line, idx) => (
              <div key={idx} style={{ fontSize: 11, color: T.textSecondary }}>{line}</div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {hasComposioApp && (
          <>
            <span style={SECTION_LABEL}>Communication hub</span>
            {composioCard}
          </>
        )}
        {required.length > 0 && (
          <>
            <span style={{ ...SECTION_LABEL, marginTop: 12 }}>Required for {stackName}</span>
            {required.map(c => card(c.key, ICONS[c.key] ?? "🔌", c.label, c.purpose, true))}
          </>
        )}
        {optional.length > 0 && (
          <>
            <span style={{ ...SECTION_LABEL, marginTop: 12 }}>Optional</span>
            {optional.map(c => card(c.key, ICONS[c.key] ?? "◇", c.label, c.purpose, false))}
          </>
        )}
        <span style={{ ...SECTION_LABEL, marginTop: 12 }}>Payments</span>
        {card("stripe", "≡", "Stripe", "Accept payments and track revenue — optional", false)}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button style={BTN_GHOST} onClick={onBack}>← Back</button>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button style={{ ...BTN_GHOST, fontSize: 12 }} onClick={onNext}>Skip for now</button>
          <button style={BTN_PRIMARY} onClick={onNext}>Continue →</button>
        </div>
      </div>
    </div>
  );
}

// ── Step 1: Welcome ───────────────────────────────────────────────────────────

// ── Brand starting point (founder-owned choices) ──────────────────────────────
const COLOR_PRESETS: { id: string; label: string; hex: string }[] = [
  { id: "auto",    label: "Let Astra pick", hex: "" },
  { id: "indigo",  label: "Indigo",         hex: "#0B31FF" },
  { id: "emerald", label: "Emerald",        hex: "#059669" },
  { id: "violet",  label: "Violet",         hex: "#7C3AED" },
  { id: "crimson", label: "Crimson",        hex: "#DC2626" },
  { id: "amber",   label: "Amber",          hex: "#D97706" },
  { id: "teal",    label: "Teal",           hex: "#0D9488" },
  { id: "slate",   label: "Slate",          hex: "#334155" },
];
const VOICE_OPTIONS = ["Professional", "Friendly", "Bold", "Minimal", "Playful", "Luxury"];

function BrandPicker({ brandColor, setBrandColor, brandVoice, setBrandVoice }: {
  brandColor: string; setBrandColor: (v: string) => void;
  brandVoice: string; setBrandVoice: (v: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "14px 16px", border: `1px solid ${T.border}`, borderRadius: 12, background: T.white }}>
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: T.textMuted }}>
        Brand starting point <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>— optional, your agents adapt to it</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <label style={{ ...LABEL, fontSize: 11 }}>Color direction</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {COLOR_PRESETS.map(c => {
            const active = brandColor === c.hex;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setBrandColor(c.hex)}
                title={c.label}
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 10px 5px 7px",
                  border: `1.5px solid ${active ? T.blue : T.border}`, borderRadius: 999,
                  background: active ? T.blueTint : T.surface, color: T.textSecondary,
                  fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: "var(--font-geist-sans), sans-serif",
                }}
              >
                <span style={{
                  width: 14, height: 14, borderRadius: "50%", flexShrink: 0,
                  background: c.hex || "conic-gradient(#0B31FF,#059669,#DC2626,#D97706,#7C3AED,#0B31FF)",
                  border: "1px solid rgba(255,255,255,0.25)",
                }} />
                {c.label}
              </button>
            );
          })}
          {(() => {
            const isCustom = !!brandColor && !COLOR_PRESETS.some(c => c.hex === brandColor);
            return (
              <label
                title="Pick any color"
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 10px 5px 7px",
                  border: `1.5px solid ${isCustom ? T.blue : T.border}`, borderRadius: 999,
                  background: isCustom ? T.blueTint : T.surface, color: T.textSecondary,
                  fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: "var(--font-geist-sans), sans-serif",
                }}
              >
                <span style={{
                  width: 14, height: 14, borderRadius: "50%", flexShrink: 0,
                  background: isCustom ? brandColor : "repeating-conic-gradient(#888 0% 25%, #555 0% 50%) 50% / 8px 8px",
                  border: "1px solid rgba(255,255,255,0.25)",
                }} />
                {isCustom ? brandColor.toUpperCase() : "Custom"}
                <input
                  type="color"
                  value={/^#[0-9a-fA-F]{6}$/.test(brandColor) ? brandColor : "#0B31FF"}
                  onChange={e => setBrandColor(e.target.value)}
                  style={{ width: 0, height: 0, opacity: 0, position: "absolute" }}
                />
              </label>
            );
          })()}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <label style={{ ...LABEL, fontSize: 11 }}>Brand voice</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {VOICE_OPTIONS.map(v => {
            const active = brandVoice === v;
            return (
              <button
                key={v}
                type="button"
                onClick={() => setBrandVoice(active ? "" : v)}
                style={{
                  padding: "5px 12px", border: `1.5px solid ${active ? T.blue : T.border}`,
                  borderRadius: 999, background: active ? T.blueTint : T.surface,
                  color: active ? T.textPrimary : T.textSecondary, fontSize: 11.5, fontWeight: 600,
                  cursor: "pointer", fontFamily: "var(--font-geist-sans), sans-serif",
                }}
              >
                {v}
              </button>
            );
          })}
        </div>
        <input
          style={{ ...INPUT, fontSize: 12.5, padding: "8px 11px" }}
          placeholder="…or describe your own voice (e.g. witty and irreverent, warm and clinical)"
          value={VOICE_OPTIONS.includes(brandVoice) ? "" : brandVoice}
          onChange={e => setBrandVoice(e.target.value)}
        />
      </div>
    </div>
  );
}

function StepWelcome({ name, setName, company, setCompany, goal, setGoal, brandColor, setBrandColor, brandVoice, setBrandVoice, onNext }: {
  name: string; setName: (v: string) => void;
  company: string; setCompany: (v: string) => void;
  goal: string; setGoal: (v: string) => void;
  brandColor: string; setBrandColor: (v: string) => void;
  brandVoice: string; setBrandVoice: (v: string) => void;
  onNext: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <h1 style={{ fontSize: 32, fontWeight: 700, margin: "0 0 8px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Welcome to Astra
        </h1>
        <p style={{ fontSize: 14, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          A team of AI agents working in parallel to build your startup. Let's get you set up.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={LABEL}>Your name</label>
            <input
              style={INPUT}
              placeholder="Alex"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={LABEL}>
              Startup name <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>(optional)</span>
            </label>
            <input
              style={INPUT}
              placeholder="Acme Inc."
              value={company}
              onChange={e => setCompany(e.target.value)}
            />
            <span style={{ fontSize: 10.5, color: T.textMuted }}>Leave blank and Astra will propose names for you.</span>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>
            What are you building? <span style={{ color: T.red }}>*</span>
          </label>
          <textarea
            style={{ ...INPUT, minHeight: 108, resize: "vertical", lineHeight: 1.6 }}
            placeholder="e.g. A SaaS tool that helps restaurant owners manage their inventory using AI predictions."
            value={goal}
            onChange={e => setGoal(e.target.value)}
          />
          <span style={{ fontSize: 11, color: T.textMuted }}>Be specific — agents tailor every artifact to your startup.</span>
        </div>

        <BrandPicker brandColor={brandColor} setBrandColor={setBrandColor} brandVoice={brandVoice} setBrandVoice={setBrandVoice} />
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button
          style={{ ...BTN_PRIMARY, opacity: goal.trim().length > 10 ? 1 : 0.4 }}
          onClick={onNext}
          disabled={goal.trim().length <= 10}
        >
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── Step 1.5: Business quiz ────────────────────────────────────────────────────

type QuizSub = "type" | "customer" | "stage" | "sub";

function StepQuiz({ onComplete, onBack, onSkip }: {
  onComplete: (result: QuizResult) => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const [sub, setSub] = useState<QuizSub>("type");
  const [bizType, setBizType] = useState("");
  const [customer, setCustomer] = useState("");
  const [stage, setStage] = useState("");
  const [subCat, setSubCat] = useState("");

  const needsSub = bizType === "local" || bizType === "ecomm";
  const subOptions = bizType === "local" ? LOCAL_CATEGORIES : ECOMM_CATEGORIES;
  const SUBS: QuizSub[] = needsSub ? ["type", "customer", "stage", "sub"] : ["type", "customer", "stage"];
  const subIdx = SUBS.indexOf(sub);
  const isLast = sub === "sub" || (!needsSub && sub === "stage");

  const canAdvance =
    (sub === "type" && bizType) ||
    (sub === "customer" && customer) ||
    (sub === "stage" && stage) ||
    (sub === "sub" && subCat);

  function finish(subVal: string) {
    const stackId = STACK_MAP[bizType] || "idea_to_revenue";
    const contextBlock = buildQuizContext(bizType, customer, stage, subVal);
    onComplete({ stackId, contextBlock, businessType: bizType, customerType: customer, stage, subCategory: subVal });
  }

  function advance() {
    if (sub === "type") { setSub("customer"); return; }
    if (sub === "customer") { setSub("stage"); return; }
    if (sub === "stage") { needsSub ? setSub("sub") : finish(""); return; }
    if (sub === "sub") { finish(subCat); return; }
  }

  const TITLES: Record<QuizSub, { h: string; p: string }> = {
    type:     { h: "What type of business is this?", p: "Astra picks the right agents and stack for you." },
    customer: { h: "Who are your customers?",        p: "Shapes sales motion, channels, and pricing model." },
    stage:    { h: "Where are you right now?",       p: "Agents adjust their output to your starting point." },
    sub:      { h: bizType === "local" ? "What kind of service?" : "What are you selling?", p: "Narrows agent instructions to your specific category." },
  };

  const optionRow = (key: string, selected: boolean, onClick: () => void, label: string, desc: string, icon?: string) => (
    <div
      key={key}
      onClick={onClick}
      style={{
        ...(selected ? CARD_SELECTED : CARD),
        display: "flex", alignItems: "center", gap: 12, padding: "13px 16px",
      }}
    >
      {icon && <span style={{ fontSize: 18, lineHeight: 1, color: T.grey }}>{icon}</span>}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>{label}</div>
        <div style={{ fontSize: 11, color: T.textMuted, marginTop: 2 }}>{desc}</div>
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={SECTION_LABEL}>Step {subIdx + 1} of {SUBS.length}</span>
        <button onClick={onSkip} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: T.textMuted, padding: 0 }}>
          Skip quiz →
        </button>
      </div>

      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          {TITLES[sub].h}
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>{TITLES[sub].p}</p>
      </div>

      {sub === "type" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {BIZ_TYPES.map(t => optionRow(t.id, bizType === t.id, () => setBizType(t.id), t.label, t.desc, t.icon))}
        </div>
      )}
      {sub === "customer" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {CUSTOMER_TYPES.map(c => optionRow(c.id, customer === c.id, () => setCustomer(c.id), c.label, c.desc))}
        </div>
      )}
      {sub === "stage" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {STAGES.map(s => optionRow(s.id, stage === s.id, () => setStage(s.id), s.label, s.desc))}
        </div>
      )}
      {sub === "sub" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {subOptions.map(c => optionRow(c.id, subCat === c.id, () => setSubCat(c.id), c.label, c.desc))}
        </div>
      )}

      {bizType && (
        <div style={{ padding: "10px 14px", background: T.blueTint, border: `1px solid ${T.blueMid}`, borderRadius: 12, fontSize: 12, color: T.textSecondary }}>
          Stack: <span style={{ color: T.blue, fontWeight: 600 }}>
            {STACK_MAP[bizType] === "ecomm" ? "Ecommerce Stack" :
             STACK_MAP[bizType] === "local_service" ? "Local Service Stack" :
             "Idea to Revenue Stack"}
          </span>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button style={BTN_GHOST} onClick={() => { subIdx > 0 ? setSub(SUBS[subIdx - 1]) : onBack(); }}>← Back</button>
        <button style={{ ...BTN_PRIMARY, opacity: canAdvance ? 1 : 0.4 }} disabled={!canAdvance} onClick={advance}>
          {isLast ? "Continue →" : "Next →"}
        </button>
      </div>
    </div>
  );
}

// ── Step 2: Choose stack ──────────────────────────────────────────────────────

function StepChooseStack({ stacks, selectedStackId, onSelect, recommendation, onBack, onNext }: {
  stacks: AgentStackTemplate[]; selectedStackId: string;
  onSelect: (id: string) => void;
  recommendation: { stack_id: string; reason: string } | null;
  onBack: () => void; onNext: () => void;
}) {
  const allOptions: AgentStackTemplate[] = [
    ...stacks,
    {
      stack_id: "custom", name: "Build your own stack",
      target_user: "Founders with a unique workflow not covered by presets.",
      primary_outcome: "A fully custom agent configuration built from the workspace.",
      description: "", input_prompts: [], tasks: [], artifacts: [],
      approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [],
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Choose your agent stack
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Each stack is a preset team of agents optimised for a specific goal. You can switch anytime.
        </p>
      </div>

      {recommendation && selectedStackId === recommendation.stack_id && (
        <div style={{
          padding: "12px 16px",
          borderRadius: 12,
          background: T.blueTint,
          border: `1px solid ${T.blueMid}`,
          fontSize: 12,
          color: T.textSecondary,
          lineHeight: 1.5,
        }}>
          <span style={{ fontWeight: 600, color: T.blue }}>Suggested for you</span> — {recommendation.reason}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, maxHeight: 360, overflowY: "auto", paddingRight: 4 }}>
        {allOptions.map(stack => {
          const selected = stack.stack_id === selectedStackId;
          return (
            <div key={stack.stack_id} style={selected ? CARD_SELECTED : CARD} onClick={() => onSelect(stack.stack_id)}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <span style={{ fontSize: 22, lineHeight: 1 }}>{STACK_ICONS[stack.stack_id] ?? "📦"}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>
                      {stack.name}
                    </span>
                    {recommendation?.stack_id === stack.stack_id && (
                      <span style={{
                        fontSize: 9, padding: "2px 6px", borderRadius: 999,
                        background: T.blueTint, color: T.blue,
                        fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
                        border: `1px solid ${T.blueMid}`,
                      }}>Suggested</span>
                    )}
                  </div>
                  <p style={{ fontSize: 11, color: T.textMuted, margin: "3px 0 0", lineHeight: 1.45 }}>
                    {stack.target_user}
                  </p>
                </div>
              </div>
              {selected && stack.primary_outcome && (
                <p style={{
                  fontSize: 11, color: T.textSecondary, margin: "10px 0 0", lineHeight: 1.5,
                  borderTop: `1px solid ${T.border}`, paddingTop: 10,
                }}>
                  {stack.primary_outcome}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button style={BTN_GHOST} onClick={onBack}>← Back</button>
        <button style={BTN_PRIMARY} onClick={onNext}>Continue →</button>
      </div>
    </div>
  );
}

// ── Mode select (new vs existing business) ────────────────────────────────────

function ModeIcon({ type }: { type: "new" | "existing" }) {
  if (type === "new") return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      <circle cx="11" cy="11" r="9" fill={T.blue} fillOpacity="0.12" stroke={T.blue} strokeWidth="1.4" />
      <path d="M11 15V8" stroke={T.blue} strokeWidth="1.7" strokeLinecap="round" />
      <path d="M7.5 11.5L11 8L14.5 11.5" stroke={T.blue} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      <rect x="2" y="2" width="8" height="8" rx="1.5" fill={T.blue} fillOpacity="0.18" stroke={T.blue} strokeWidth="1.4" />
      <rect x="12" y="2" width="8" height="8" rx="1.5" fill={T.blue} fillOpacity="0.18" stroke={T.blue} strokeWidth="1.4" />
      <rect x="2" y="12" width="8" height="8" rx="1.5" fill={T.blue} fillOpacity="0.18" stroke={T.blue} strokeWidth="1.4" />
      <rect x="12" y="12" width="8" height="8" rx="1.5" fill={T.blue} fillOpacity="0.12" stroke={T.blue} strokeWidth="1.4" strokeDasharray="2 1.5" />
    </svg>
  );
}

function StepModeSelect({ onSelect }: { onSelect: (mode: "new" | "existing") => void }) {
  const [hovered, setHovered] = useState<"new" | "existing" | null>(null);
  const opts: { mode: "new" | "existing"; title: string; sub: string }[] = [
    { mode: "new", title: "New business", sub: "Starting from scratch — turn an idea into a real company" },
    { mode: "existing", title: "Existing business", sub: "Already operating — scale, automate, and grow what's working" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <h1 style={{ fontSize: 30, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Welcome to Astra
        </h1>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          A team of AI agents working in parallel. Where are you starting from?
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {opts.map(opt => {
          const isHovered = hovered === opt.mode;
          return (
            <div
              key={opt.mode}
              onClick={() => onSelect(opt.mode)}
              onMouseEnter={() => setHovered(opt.mode)}
              onMouseLeave={() => setHovered(null)}
              style={{
                display: "flex", alignItems: "center", gap: 16,
                padding: "18px 20px",
                borderRadius: 14,
                border: `1.5px solid ${isHovered ? T.blue : T.border}`,
                background: isHovered ? T.blueTint : T.white,
                cursor: "pointer",
                boxShadow: isHovered ? "0 4px 16px rgba(0,46,255,0.08)" : T.shadow,
                transition: "border-color 0.14s, background 0.14s, box-shadow 0.14s",
              }}
            >
              <div style={{
                width: 44, height: 44, borderRadius: 12, flexShrink: 0,
                background: isHovered ? "rgba(0,46,255,0.1)" : T.surface,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "background 0.14s",
              }}>
                <ModeIcon type={opt.mode} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", marginBottom: 3 }}>
                  {opt.title}
                </div>
                <div style={{ fontSize: 12, color: T.textMuted, lineHeight: 1.5 }}>
                  {opt.sub}
                </div>
              </div>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, opacity: isHovered ? 1 : 0.3, transition: "opacity 0.14s" }}>
                <path d="M6 3L11 8L6 13" stroke={T.blue} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Existing biz: step 0 — Business profile ───────────────────────────────────

const INDUSTRIES = [
  { id: "saas", label: "Tech / SaaS", icon: "⬡" },
  { id: "ecomm", label: "E-commerce", icon: "◈" },
  { id: "local", label: "Local Service", icon: "◉" },
  { id: "agency", label: "Agency / Consulting", icon: "◇" },
  { id: "food", label: "Food & Beverage", icon: "▦" },
  { id: "retail", label: "Retail / Shop", icon: "▣" },
  { id: "health", label: "Health & Wellness", icon: "◎" },
  { id: "finance", label: "Finance", icon: "≡" },
  { id: "education", label: "Education", icon: "◉" },
  { id: "real_estate", label: "Real Estate", icon: "▲" },
  { id: "content", label: "Media / Creator", icon: "◈" },
  { id: "other", label: "Other", icon: "◇" },
];

const TEAM_SIZES = [
  { id: "solo", label: "Solo / Just me" },
  { id: "small", label: "2–10 people" },
  { id: "mid", label: "11–50 people" },
  { id: "large", label: "50+ people" },
];

const BIZ_AGE = [
  { id: "lt1", label: "< 1 year" },
  { id: "1to3", label: "1–3 years" },
  { id: "3to10", label: "3–10 years" },
  { id: "gt10", label: "10+ years" },
];

function StepExistingBiz({ name, setName, company, setCompany, industry, setIndustry, teamSize, setTeamSize, yearsInBiz, setYearsInBiz, brandColor, setBrandColor, brandVoice, setBrandVoice, onNext, onBack }: {
  name: string; setName: (v: string) => void;
  company: string; setCompany: (v: string) => void;
  industry: string; setIndustry: (v: string) => void;
  teamSize: string; setTeamSize: (v: string) => void;
  yearsInBiz: string; setYearsInBiz: (v: string) => void;
  brandColor: string; setBrandColor: (v: string) => void;
  brandVoice: string; setBrandVoice: (v: string) => void;
  onNext: () => void; onBack: () => void;
}) {
  const canAdvance = company.trim().length > 0 && industry && teamSize && yearsInBiz;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Tell us about your business
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Agents use this to tailor every output to your specific situation.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>Your name</label>
          <input style={INPUT} placeholder="Alex" value={name} onChange={e => setName(e.target.value)} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>Business name <span style={{ color: T.red }}>*</span></label>
          <input style={INPUT} placeholder="Acme Co." value={company} onChange={e => setCompany(e.target.value)} />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={LABEL}>Industry <span style={{ color: T.red }}>*</span></label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 7 }}>
          {INDUSTRIES.map(ind => (
            <div
              key={ind.id}
              onClick={() => setIndustry(ind.id)}
              style={{
                borderRadius: 10, border: `1.5px solid ${industry === ind.id ? T.blue : T.border}`,
                background: industry === ind.id ? T.blueTint : T.white,
                padding: "8px 10px", cursor: "pointer",
                transition: "border-color 0.12s, background 0.12s",
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              <span style={{ fontSize: 12, color: T.grey }}>{ind.icon}</span>
              <span style={{ fontSize: 10.5, fontWeight: 500, color: industry === ind.id ? T.blue : T.textPrimary, fontFamily: "var(--font-geist-sans), sans-serif" }}>
                {ind.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>Team size <span style={{ color: T.red }}>*</span></label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {TEAM_SIZES.map(t => (
              <div
                key={t.id}
                onClick={() => setTeamSize(t.id)}
                style={{
                  borderRadius: 10, border: `1.5px solid ${teamSize === t.id ? T.blue : T.border}`,
                  background: teamSize === t.id ? T.blueTint : T.white,
                  padding: "8px 12px", cursor: "pointer",
                  fontSize: 12, fontWeight: 500, color: teamSize === t.id ? T.blue : T.textPrimary,
                  fontFamily: "var(--font-geist-sans), sans-serif",
                  transition: "border-color 0.12s, background 0.12s",
                }}
              >
                {t.label}
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>Time in business <span style={{ color: T.red }}>*</span></label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {BIZ_AGE.map(a => (
              <div
                key={a.id}
                onClick={() => setYearsInBiz(a.id)}
                style={{
                  borderRadius: 10, border: `1.5px solid ${yearsInBiz === a.id ? T.blue : T.border}`,
                  background: yearsInBiz === a.id ? T.blueTint : T.white,
                  padding: "8px 12px", cursor: "pointer",
                  fontSize: 12, fontWeight: 500, color: yearsInBiz === a.id ? T.blue : T.textPrimary,
                  fontFamily: "var(--font-geist-sans), sans-serif",
                  transition: "border-color 0.12s, background 0.12s",
                }}
              >
                {a.label}
              </div>
            ))}
          </div>
        </div>
      </div>

      <BrandPicker brandColor={brandColor} setBrandColor={setBrandColor} brandVoice={brandVoice} setBrandVoice={setBrandVoice} />

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button style={BTN_GHOST} onClick={onBack}>← Back</button>
        <button style={{ ...BTN_PRIMARY, opacity: canAdvance ? 1 : 0.4 }} onClick={onNext} disabled={!canAdvance}>
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── Existing biz: step 1 — Priority & first goal ──────────────────────────────

const PRIORITIES = [
  { id: "customers", icon: "⊕", label: "Get more customers", desc: "Fill the pipeline, grow leads, drive conversions", stack: "sales" },
  { id: "scale", icon: "▲", label: "Scale sales", desc: "Build a repeatable sales system and hit revenue targets", stack: "sales" },
  { id: "brand", icon: "✦", label: "Build brand presence", desc: "Create content, grow social, run campaigns", stack: "marketing" },
  { id: "ops", icon: "◎", label: "Automate operations", desc: "Streamline workflows, cut admin work, save time", stack: "founder_ops" },
  { id: "support", icon: "◈", label: "Improve customer support", desc: "Faster responses, better retention, happier customers", stack: "support" },
  { id: "product", icon: "◇", label: "Launch something new", desc: "New product, service line, or market expansion", stack: "product" },
];

function StepGoalPicker({ priority, setPriority, goal, setGoal, company, onNext, onBack }: {
  priority: string; setPriority: (v: string) => void;
  goal: string; setGoal: (v: string) => void;
  company: string; onNext: () => void; onBack: () => void;
}) {
  const selected = PRIORITIES.find(p => p.id === priority);
  const canAdvance = priority && goal.trim().length > 8;
  const placeholder =
    priority === "customers" ? `e.g. Build an outbound email sequence targeting ${company || "our ideal customers"} — I want 50 new leads per week.` :
    priority === "brand" ? `e.g. Create a 30-day content calendar for ${company || "our brand"} across Instagram and LinkedIn.` :
    priority === "ops" ? `e.g. Automate our client onboarding — it currently takes 2 hours of manual work per new client.` :
    priority === "scale" ? `e.g. Build a sales playbook and CRM pipeline for ${company || "our sales team"}.` :
    priority === "support" ? `e.g. Set up a help-desk system and first-response templates for ${company || "our customers"}.` :
    priority === "product" ? `e.g. Launch a ${company ? company + " " : ""}loyalty subscription tier — I want it live in 60 days.` :
    `Tell us what you want Astra to do for ${company || "your business"} first.`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          What's your main priority?
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Agents build everything around this — you can adjust anytime.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {PRIORITIES.map(p => (
          <div
            key={p.id}
            onClick={() => setPriority(p.id)}
            style={{
              borderRadius: 12, border: `1.5px solid ${priority === p.id ? T.blue : T.border}`,
              background: priority === p.id ? T.blueTint : T.white,
              padding: "12px 14px", cursor: "pointer",
              transition: "border-color 0.12s, background 0.12s",
              boxShadow: T.shadow,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 13, color: priority === p.id ? T.blue : T.grey, lineHeight: 1, flexShrink: 0 }}>{p.icon}</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: priority === p.id ? T.blue : T.textPrimary, fontFamily: "var(--font-geist-sans), sans-serif" }}>
                {p.label}
              </span>
            </div>
            <p style={{ fontSize: 10, color: T.textMuted, margin: 0, lineHeight: 1.4, paddingLeft: 21 }}>
              {p.desc}
            </p>
          </div>
        ))}
      </div>

      {selected && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={LABEL}>
            What specifically do you want Astra to tackle first? <span style={{ color: T.red }}>*</span>
          </label>
          <textarea
            style={{ ...INPUT, minHeight: 88, resize: "vertical", lineHeight: 1.6 }}
            placeholder={placeholder}
            value={goal}
            onChange={e => setGoal(e.target.value)}
          />
          <span style={{ fontSize: 11, color: T.textMuted }}>Be specific — agents use this as their first objective.</span>
        </div>
      )}

      {selected && (
        <div style={{ padding: "10px 14px", background: T.blueTint, border: `1px solid ${T.blueMid}`, borderRadius: 12, fontSize: 12, color: T.textSecondary }}>
          Recommended stack: <span style={{ color: T.blue, fontWeight: 600 }}>
            {FALLBACK_STACKS.find(s => s.stack_id === selected.stack)?.name ?? selected.stack}
          </span>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button style={BTN_GHOST} onClick={onBack}>← Back</button>
        <button style={{ ...BTN_PRIMARY, opacity: canAdvance ? 1 : 0.4 }} onClick={onNext} disabled={!canAdvance}>
          Continue →
        </button>
      </div>
    </div>
  );
}

// ── Step 4: Done ──────────────────────────────────────────────────────────────

function StepDone({ name, company, stackName, onLaunch }: {
  name: string; company: string; stackName: string; onLaunch: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32, alignItems: "center", textAlign: "center" }}>
      {/* Pulsing blue mark */}
      <div style={{ position: "relative", width: 64, height: 64, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="astra-pulse" style={{
          position: "absolute", inset: -14, borderRadius: "50%",
          border: "1px solid rgba(11,49,255,0.4)",
          animation: "pulse-ring 2.2s ease-out infinite",
        }} />
        <div style={{
          width: 48, height: 48, background: T.blue,
          WebkitMask: "url('/logo.png') center/contain no-repeat",
          mask: "url('/logo.png') center/contain no-repeat",
          position: "relative", zIndex: 1,
        }} />
      </div>

      <div>
        <h2 style={{ fontSize: 30, fontWeight: 700, margin: "0 0 10px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          {name ? `${name.split(" ")[0]}, you're ready` : "You're ready"}
        </h2>
        <p style={{ fontSize: 14, color: T.textMuted, margin: 0, lineHeight: 1.7, maxWidth: "36ch" }}>
          {company && <><strong style={{ color: T.textSecondary }}>{company}</strong> launches with the </>}
          {!company && "Running the "}
          <strong style={{ color: T.textSecondary }}>{stackName}</strong> stack.
          Agents start immediately.
        </p>
      </div>

      {/* Flat stat row — no cards */}
      <div style={{ display: "flex", borderTop: `1px solid ${T.border}`, paddingTop: 24, width: "100%" }}>
        {[
          ["Agents", "work in parallel"],
          ["Artifacts", "docs, code, plans"],
          ["Actions", "deploy, send, file"],
        ].map(([label, desc], i) => (
          <div key={label} style={{ flex: 1, textAlign: "center", borderLeft: i > 0 ? `1px solid ${T.border}` : "none", padding: "0 12px" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.textSecondary, marginBottom: 3, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>{label}</div>
            <div style={{ fontSize: 11, color: T.textMuted }}>{desc}</div>
          </div>
        ))}
      </div>

      <button style={{ ...BTN_PRIMARY, padding: "14px 48px", fontSize: 15 }} onClick={onLaunch}>
        Launch workspace →
      </button>
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function OnboardingWizard() {
  const router = useRouter();
  const { userId, user } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const userEmail = user.email ?? "";

  // "": show mode select; "new": startup flow; "existing": business owner flow
  const [mode, setMode] = useState<"" | "new" | "existing">("");
  const [step, setStep] = useState(0);

  // Shared fields
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [goal, setGoal] = useState("");
  const [brandColor, setBrandColor] = useState("");  // hex; "" = let Astra pick
  const [brandVoice, setBrandVoice] = useState("");  // e.g. "Bold"; "" = unset
  const [selectedStackId, setSelectedStackId] = useState("idea_to_revenue");
  const REQUIRED_AGENTS = new Set(["research"]);
  const [customAgents, setCustomAgents] = useState<string[]>(["research", "web", "technical", "marketing"]);
  const [customStackName, setCustomStackName] = useState("My Custom Stack");
  const [stacks, setStacks] = useState<AgentStackTemplate[]>(FALLBACK_STACKS);
  const [recommendation, setRecommendation] = useState<{ stack_id: string; reason: string } | null>(null);
  const [manualOverride, setManualOverride] = useState(false);
  const [readiness, setReadiness] = useState<StackReadiness | null>(null);
  const [quizContext, setQuizContext] = useState("");

  // Existing-biz-only fields
  const [industry, setIndustry] = useState("");
  const [teamSize, setTeamSize] = useState("");
  const [yearsInBiz, setYearsInBiz] = useState("");
  const [bizPriority, setBizPriority] = useState("");

  function onQuizComplete(r: QuizResult) {
    setQuizContext(r.contextBlock);
    setManualOverride(true);
    if (r.stackId) setSelectedStackId(r.stackId);
    setStep(2);
  }

  function toggleCustomAgent(id: string) {
    if (REQUIRED_AGENTS.has(id)) return;
    setCustomAgents(prev => prev.includes(id) ? prev.filter(a => a !== id) : [...prev, id]);
  }

  useEffect(() => { getStacks().then(s => setStacks(s.length > 0 ? s : FALLBACK_STACKS)).catch(() => setStacks(FALLBACK_STACKS)); }, []);

  useEffect(() => {
    if (mode !== "new") return;
    if (goal.trim().length < 16) { setRecommendation(null); return; }
    const timer = window.setTimeout(() => {
      recommendStack(goal).then(r => {
        setRecommendation({ stack_id: r.stack.stack_id, reason: r.reason });
        if (!manualOverride) setSelectedStackId(r.stack.stack_id);
      }).catch(() => setRecommendation(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [goal, manualOverride, mode]);

  useEffect(() => {
    if (selectedStackId === "custom") { setReadiness(null); return; }
    getStackReadiness(founderId, selectedStackId).then(setReadiness).catch(() => setReadiness(null));
  }, [founderId, selectedStackId]);

  const selectedStack = stacks.find(s => s.stack_id === selectedStackId);
  const stackName = selectedStackId === "custom" ? customStackName : (selectedStack?.name ?? "Idea to Revenue Stack");

  const [launching, setLaunching] = useState(false);

  function lsSet(key: string, val: string) {
    try { localStorage.setItem(key, val); return; } catch { /* full */ }
    for (const k of ["astra_sessions", "astra_workspaces", "astra_events", "astra_chapters"]) {
      try { localStorage.removeItem(k); localStorage.setItem(key, val); return; } catch { /* keep evicting */ }
    }
    try { localStorage.clear(); localStorage.setItem(key, val); } catch { /* localStorage unavailable */ }
  }

  async function handleLaunch() {
    if (launching) return;
    setLaunching(true);
    lsSet("astra_onboarding_done", "1");
    if (name.trim()) lsSet("astra_onboarding_name", name.trim());
    if (goal.trim()) lsSet("astra_onboarding_goal", goal.trim());
    if (company.trim()) lsSet("astra_onboarding_company", company.trim());
    if (selectedStackId === "custom" && customAgents.length > 0) {
      lsSet("astra_custom_agents", JSON.stringify(customAgents));
      lsSet("astra_custom_stack_name", customStackName);
      lsSet("astra_onboarding_stack", "custom");
    } else {
      lsSet("astra_onboarding_stack", selectedStackId);
    }

    const g = goal.trim();
    if (g) {
      const nm = company.trim() || name.trim();
      const stack = selectedStackId || "idea_to_revenue";
      let instruction: string;

      if (mode === "existing") {
        const industryLabel = INDUSTRIES.find(i => i.id === industry)?.label ?? industry;
        const teamLabel = TEAM_SIZES.find(t => t.id === teamSize)?.label ?? teamSize;
        const ageLabel = BIZ_AGE.find(a => a.id === yearsInBiz)?.label ?? yearsInBiz;
        const priorityLabel = PRIORITIES.find(p => p.id === bizPriority)?.label ?? bizPriority;
        const ctx = [
          `[Existing business — context for Astra agents]`,
          nm ? `Company: ${nm}` : null,
          industry ? `Industry: ${industryLabel}` : null,
          teamSize ? `Team size: ${teamLabel}` : null,
          yearsInBiz ? `In business: ${ageLabel}` : null,
          bizPriority ? `Priority focus: ${priorityLabel}` : null,
        ].filter(Boolean).join("\n");
        instruction = `${ctx}\n\n---\n${g}`;
      } else {
        const base = nm ? `Company/project name: ${nm}\n\n${g}` : g;
        instruction = quizContext ? `${quizContext}\n\n---\n${base}` : base;
      }

      // Founder's brand choices → honored by design/web/marketing agents instead of
      // being auto-decided. Prepended so they're read as source-of-truth context.
      const brandColorLabel = COLOR_PRESETS.find(c => c.hex && c.hex === brandColor)?.label;
      const brandBits = [
        brandColor ? `Primary brand color: ${brandColorLabel ? `${brandColorLabel} (${brandColor})` : brandColor}` : null,
        brandVoice ? `Brand voice / tone: ${brandVoice}` : null,
      ].filter(Boolean);
      if (brandBits.length) {
        instruction = `[Brand preferences — founder's choices, honor these over any auto-generated defaults]\n${brandBits.join("\n")}\n\n---\n${instruction}`;
      }

      const constraints = selectedStackId === "custom" && customAgents.length > 0
        ? { agents: customAgents } : {};
      submitGoal(founderId, instruction, constraints, stack).catch(() => {});
    }

    lsSet("astra_show_welcome", "1");
    router.replace(`/dashboard?welcome=1&name=${encodeURIComponent(name.trim())}`);
  }

  async function handleSkip() {
    lsSet("astra_onboarding_done", "1");
    router.push("/dashboard");
  }

  // Dot counts per mode and step
  const isCustom = selectedStackId === "custom";
  const dotStep = mode === "new"
    ? (isCustom ? step : step >= 4 ? step - 1 : step)
    : step; // existing: 0=profile,1=priority,2=stack,(3=custom),4=connect,5=done
  const dotTotal = isCustom ? 6 : 5;

  return (
    <>
    {launching && (
      <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "linear-gradient(135deg, #002eff 0%, #1a45ff 25%, #5df5e0 65%, #fefff6 100%)" }} />
    )}
    <style>{`
      body::before, body::after { display: none !important; }
      body { background: #02040A !important; }
      @keyframes pulse-ring {
        0%   { transform: scale(0.85); opacity: 0.9; }
        70%  { transform: scale(1.22); opacity: 0;   }
        100% { transform: scale(1.22); opacity: 0;   }
      }
      @media (prefers-reduced-motion: reduce) {
        .astra-pulse { animation: none !important; }
      }
    `}</style>
    <div style={{ position: "fixed", inset: 0, pointerEvents: "none", background: "radial-gradient(ellipse 70% 45% at 50% 0%, rgba(11,49,255,0.13) 0%, transparent 70%)" }} />
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "center",
      padding: "48px 16px",
      background: "#05070D",
      fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
      position: "relative",
    }}>
      {/* Logo */}
      <div style={{ position: "fixed", top: 24, left: 28, display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 28, height: 28, background: T.blue, flexShrink: 0,
          WebkitMask: "url('/logo.png') center/contain no-repeat",
          mask: "url('/logo.png') center/contain no-repeat",
        }} />
        <span style={{ fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase", color: T.textPrimary, fontWeight: 700 }}>Astra</span>
      </div>

      {/* Wizard card */}
      <div style={{
        width: "100%",
        maxWidth: 560,
        borderRadius: 20,
        border: `1px solid ${T.border}`,
        background: T.white,
        boxShadow: T.shadowMd,
        padding: "36px 40px",
      }}>
        {/* Mode select — no step dots */}
        {mode === "" && (
          <StepModeSelect onSelect={m => { setMode(m); setStep(0); }} />
        )}

        {/* ── New business path ─────────────────────────────────────────── */}
        {mode === "new" && (
          <>
            <StepDots step={dotStep} total={dotTotal} />

            {step === 0 && (
              <StepWelcome
                name={name} setName={setName}
                company={company} setCompany={setCompany}
                goal={goal} setGoal={setGoal}
                brandColor={brandColor} setBrandColor={setBrandColor}
                brandVoice={brandVoice} setBrandVoice={setBrandVoice}
                onNext={() => setStep(1)}
              />
            )}
            {step === 1 && (
              <StepQuiz onComplete={onQuizComplete} onBack={() => setStep(0)} onSkip={() => setStep(2)} />
            )}
            {step === 2 && (
              <StepChooseStack
                stacks={stacks} selectedStackId={selectedStackId}
                onSelect={id => { setManualOverride(true); setSelectedStackId(id); }}
                recommendation={recommendation} onBack={() => setStep(1)}
                onNext={() => setStep(isCustom ? 3 : 4)}
              />
            )}
            {step === 3 && isCustom && (
              <StepCustomStack
                selected={customAgents} onToggle={toggleCustomAgent}
                onBack={() => setStep(2)} onNext={() => setStep(4)}
                stackName={customStackName} setStackName={setCustomStackName}
              />
            )}
            {step === 4 && (
              <StepConnectIntegrations
                stackName={stackName} readiness={readiness}
                founderId={founderId} userEmail={userEmail}
                onBack={() => setStep(isCustom ? 3 : 2)} onNext={() => setStep(5)}
              />
            )}
            {step === 5 && (
              <StepDone name={name} company={company} stackName={stackName} onLaunch={handleLaunch} />
            )}
          </>
        )}

        {/* ── Existing business path ────────────────────────────────────── */}
        {mode === "existing" && (
          <>
            <StepDots step={dotStep} total={dotTotal} />

            {step === 0 && (
              <StepExistingBiz
                name={name} setName={setName}
                company={company} setCompany={setCompany}
                industry={industry} setIndustry={setIndustry}
                teamSize={teamSize} setTeamSize={setTeamSize}
                yearsInBiz={yearsInBiz} setYearsInBiz={setYearsInBiz}
                brandColor={brandColor} setBrandColor={setBrandColor}
                brandVoice={brandVoice} setBrandVoice={setBrandVoice}
                onBack={() => setMode("")}
                onNext={() => setStep(1)}
              />
            )}
            {step === 1 && (
              <StepGoalPicker
                priority={bizPriority} setPriority={setBizPriority}
                goal={goal} setGoal={setGoal}
                company={company}
                onBack={() => setStep(0)}
                onNext={() => {
                  const p = PRIORITIES.find(pr => pr.id === bizPriority);
                  if (p && !manualOverride) setSelectedStackId(p.stack);
                  setStep(2);
                }}
              />
            )}
            {step === 2 && (
              <StepChooseStack
                stacks={stacks} selectedStackId={selectedStackId}
                onSelect={id => { setManualOverride(true); setSelectedStackId(id); }}
                recommendation={null}
                onBack={() => setStep(1)}
                onNext={() => setStep(isCustom ? 3 : 4)}
              />
            )}
            {step === 3 && isCustom && (
              <StepCustomStack
                selected={customAgents} onToggle={toggleCustomAgent}
                onBack={() => setStep(2)} onNext={() => setStep(4)}
                stackName={customStackName} setStackName={setCustomStackName}
              />
            )}
            {step === 4 && (
              <StepConnectIntegrations
                stackName={stackName} readiness={readiness}
                founderId={founderId} userEmail={userEmail}
                onBack={() => setStep(isCustom ? 3 : 2)} onNext={() => setStep(5)}
              />
            )}
            {step === 5 && (
              <StepDone name={name} company={company} stackName={stackName} onLaunch={handleLaunch} />
            )}
          </>
        )}

        {/* Dev skip */}
        <div style={{ marginTop: 24, textAlign: "center" }}>
          <button
            onClick={handleSkip}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: T.textMuted, textDecoration: "underline", opacity: 0.5 }}
          >
            Skip onboarding (dev)
          </button>
        </div>
      </div>
    </div>
    </>
  );
}
