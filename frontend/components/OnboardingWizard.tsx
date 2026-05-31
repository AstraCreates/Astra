"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { apiFetch, getStacks, recommendStack, getStackReadiness, saveServiceCredential, getComposioOAuthUrls } from "@/lib/api";
import type { AgentStackTemplate, StackReadiness } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Constants ─────────────────────────────────────────────────────────────────

const STACK_ICONS: Record<string, string> = {
  idea_to_revenue: "🚀", sales: "🤝", marketing: "📢",
  founder_ops: "🧭", support: "🎧", product: "📐", custom: "✨",
};

// Map connector key → token-based config (popup link + paste)
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

// Connectors handled via Composio (Gmail connects through Composio OAuth)
const COMPOSIO_APPS = new Set(["gmail", "linkedin", "google_calendar", "googlecalendar"]);

// ── Styles ────────────────────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  borderRadius: 20, border: "1px solid rgba(0,0,0,0.08)",
  background: "rgba(255,255,255,0.05)", padding: "16px 18px",
  cursor: "pointer", transition: "border-color 0.15s, background 0.15s",
};
const CARD_SELECTED: React.CSSProperties = {
  ...CARD, border: "1.5px solid #2563EB", background: "rgba(37,99,235,0.06)",
};
const BTN_PRIMARY: React.CSSProperties = {
  padding: "10px 28px", borderRadius: 999, background: "#2563EB", color: "#fff",
  border: "none", fontSize: 14, fontWeight: 600, cursor: "pointer", letterSpacing: "0.02em",
};
const BTN_GHOST: React.CSSProperties = {
  padding: "10px 20px", borderRadius: 999, background: "transparent",
  color: "#94a3b8", border: "1px solid rgba(255,255,255,0.14)", fontSize: 13, cursor: "pointer",
};
const INPUT: React.CSSProperties = {
  width: "100%", padding: "12px 16px", borderRadius: 14,
  border: "1px solid rgba(0,0,0,0.12)", background: "rgba(255,255,255,0.04)",
  color: "#e2e8f0", fontSize: 14, outline: "none", boxSizing: "border-box",
};

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ step, total = 4 }: { step: number; total?: number }) {
  return (
    <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 32 }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{
          width: i === step ? 24 : 8, height: 8, borderRadius: 999,
          background: i === step ? "#2563EB" : i < step ? "rgba(37,99,235,0.35)" : "rgba(0,0,0,0.12)",
          transition: "width 0.25s, background 0.25s",
        }} />
      ))}
    </div>
  );
}

const C = {
  cardBg: "rgba(255,255,255,0.06)",
  connectedBg: "rgba(60,170,100,0.10)",
  expandedBg: "rgba(96,165,250,0.08)",
  border: "1px solid rgba(255,255,255,0.10)",
  borderRequired: "1.5px solid rgba(192,57,43,0.45)",
  borderConnected: "1.5px solid rgba(60,170,100,0.45)",
  borderExpanded: "1.5px solid rgba(96,165,250,0.45)",
};

const cardBtn: React.CSSProperties = {
  padding: "6px 16px", borderRadius: 999, fontSize: 12, fontWeight: 600,
  flexShrink: 0, whiteSpace: "nowrap" as const,
  background: "#2563EB", color: "#fff",
  border: "none", cursor: "pointer",
};

const pasteInput: React.CSSProperties = {
  flex: 1, padding: "8px 12px", borderRadius: 10, fontSize: 12,
  fontFamily: "var(--font-mono, monospace)",
  border: "1px solid rgba(255,255,255,0.15)",
  background: "rgba(0,0,0,0.2)",
  color: "var(--fg)", outline: "none",
};

// ── Step 3: Connect integrations ─────────────────────────────────────────────
// Everything is rendered inline (no sub-components) to avoid hook/scope issues.

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
  const composioConnected = !!connected["__composio__"];

  // Detect OAuth returns (GitHub / Stripe)
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const updates: Record<string, boolean> = {};
    if (p.get("github_connected") === "1") { updates["github"] = true; window.history.replaceState({}, "", window.location.pathname); }
    if (p.get("stripe_connected") === "1") { updates["stripe"] = true; window.history.replaceState({}, "", window.location.pathname); }
    if (Object.keys(updates).length) setConnected(prev => ({ ...prev, ...updates }));
  }, []);

  const required = readiness?.connectors.filter(c => c.required) ?? [];
  const optional = readiness?.connectors.filter(c => !c.required) ?? [];
  const hasComposioApp = [...required, ...optional].some(c => COMPOSIO_APPS.has(c.key));

  const ICONS: Record<string, string> = {
    github: "🐙", vercel: "▲", supabase: "⚡", clerk: "🔐", gmail: "📧",
    google_drive: "📁", google_sheets: "📊", google_calendar: "📅", slack: "💬",
    notion: "📝", linear: "📐", crm: "👥", linkedin: "💼", meta_ads: "📱",
    analytics: "📈", website_cms: "🌐", helpdesk: "🎧", figma: "🎨", stripe: "💳",
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
    const url = composioOAuthUrls[key] ?? composioOAuthUrls[key.replace("google_", "google")];
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

  // Card renderer — plain function returning JSX, not a React component
  function card(key: string, icon: string, label: string, purpose: string, isRequired: boolean) {
    const isConnected = !!connected[key];
    const isExpanded = expandedKey === key;
    const cfg = TOKEN_CONFIG[key];
    const isGH = key === "github";
    const isStripe = key === "stripe";
    const isComp = COMPOSIO_APPS.has(key);
    const border = isConnected ? C.borderConnected : isExpanded ? C.borderExpanded : isRequired ? C.borderRequired : C.border;

    return (
      <div key={key} style={{ borderRadius: 16, border, background: isConnected ? C.connectedBg : C.cardBg, transition: "border 0.2s" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
          <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>{icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{label}</span>
              {isRequired && !isConnected && <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 999, background: "rgba(192,57,43,0.12)", color: "#C0392B", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase" }}>Required</span>}
              {isConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
            </div>
            <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{purpose}</span>
          </div>
          {!isConnected && (
            isGH ? (
              <button style={cardBtn} onClick={connectGitHub}>Connect ↗</button>
            ) : isStripe ? (
              <button style={cardBtn} onClick={connectStripe}>Connect ↗</button>
            ) : isComp && composioConnected ? (
              <button style={cardBtn} onClick={() => connectComposioApp(key)}>Connect ↗</button>
            ) : isComp ? (
              <span style={{ fontSize: 11, color: "var(--fg-mute)", flexShrink: 0 }}>Set up Composio first ↑</span>
            ) : cfg ? (
              <button style={{ ...cardBtn, background: isExpanded ? "rgba(96,165,250,0.18)" : cardBtn.background }} onClick={() => toggleExpand(key)}>
                {isExpanded ? "Popup open ↗" : "Connect ↗"}
              </button>
            ) : (
              <button style={cardBtn} onClick={() => window.open("/integrations", "_blank")}>Connect ↗</button>
            )
          )}
        </div>
        {isExpanded && cfg && !isConnected && (
          <div style={{ borderTop: "1px solid var(--line-2)", padding: "12px 16px", background: C.expandedBg, display: "flex", flexDirection: "column", gap: 8 }}>
            <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>Copy your token from the popup, paste it here, then Save.</p>
            <div style={{ display: "flex", gap: 8 }}>
              <input value={tokenValues[key] ?? ""} onChange={e => setTokenValues(v => ({ ...v, [key]: e.target.value }))}
                placeholder={cfg.placeholder} onKeyDown={e => e.key === "Enter" && saveToken(key)}
                className="site-input" style={{ flex: 1, padding: "8px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }} />
              <button onClick={() => saveToken(key)} disabled={saving === key || !tokenValues[key]?.trim()}
                className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 12, flexShrink: 0 }}>
                {saving === key ? "…" : "Save"}
              </button>
            </div>
            {errors[key] && <p style={{ margin: 0, fontSize: 11, color: "#C0392B" }}>{errors[key]}</p>}
          </div>
        )}
      </div>
    );
  }

  // Composio card (inline)
  const composioCard = (
    <div style={{ borderRadius: 16, border: composioConnected ? C.borderConnected : expandedKey === "__composio__" ? C.borderExpanded : C.border, background: composioConnected ? C.connectedBg : C.cardBg, transition: "border 0.2s" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
        <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>🔗</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Composio</span>
            {composioConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Enables Gmail, LinkedIn, Notion, Calendar</span>
        </div>
        {!composioConnected && (
          <button style={{ ...cardBtn, background: expandedKey === "__composio__" ? "rgba(96,165,250,0.12)" : cardBtn.background, borderColor: expandedKey === "__composio__" ? "rgba(96,165,250,0.3)" : undefined }} onClick={() => toggleExpand("__composio__")}>
            {expandedKey === "__composio__" ? "Popup open ↗" : "Connect ↗"}
          </button>
        )}
      </div>
      {expandedKey === "__composio__" && !composioConnected && (
        <div style={{ borderTop: "1px solid var(--line-2)", padding: "12px 16px", background: C.expandedBg, display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>In the popup go to <strong>Settings → API Keys</strong>, copy your key, paste here.</p>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={tokenValues["__composio__"] ?? ""} onChange={e => setTokenValues(v => ({ ...v, "__composio__": e.target.value }))}
              placeholder="api_key_..." onKeyDown={e => e.key === "Enter" && saveComposio()}
              className="site-input" style={{ flex: 1, padding: "8px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }} />
            <button onClick={saveComposio} disabled={saving === "__composio__" || !tokenValues["__composio__"]?.trim()}
              className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 12, flexShrink: 0 }}>
              {saving === "__composio__" ? "…" : "Save"}
            </button>
          </div>
          {errors["__composio__"] && <p style={{ margin: 0, fontSize: 11, color: "#C0392B" }}>{errors["__composio__"]}</p>}
        </div>
      )}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 6px", color: "var(--fg)" }}>Connect your tools</h2>
        <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: 0, lineHeight: 1.6 }}>
          Based on <strong style={{ color: "var(--fg)" }}>{stackName}</strong>. Everything connects right here.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {hasComposioApp && (
          <>
            <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 2 }}>Communication hub</span>
            {composioCard}
          </>
        )}
        {required.length > 0 && (
          <>
            <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginTop: 8, marginBottom: 2 }}>Required for {stackName}</span>
            {required.map(c => card(c.key, ICONS[c.key] ?? "🔌", c.label, c.purpose, true))}
          </>
        )}
        {optional.length > 0 && (
          <>
            <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginTop: 8, marginBottom: 2 }}>Optional</span>
            {optional.map(c => card(c.key, ICONS[c.key] ?? "🔌", c.label, c.purpose, false))}
          </>
        )}
        <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginTop: 8, marginBottom: 2 }}>Payments</span>
        {card("stripe", "💳", "Stripe", "Accept payments and track revenue — optional", false)}
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

function StepWelcome({ name, setName, company, setCompany, goal, setGoal, onNext }: {
  name: string; setName: (v: string) => void;
  company: string; setCompany: (v: string) => void;
  goal: string; setGoal: (v: string) => void;
  onNext: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 6px", color: "#e2e8f0" }}>Welcome to Astra</h1>
        <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0, lineHeight: 1.6 }}>
          8 AI agents working in parallel to build your startup. Let's get you set up.
        </p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "#94a3b8" }}>Your name</label>
            <input style={INPUT} placeholder="Alex" value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "#94a3b8" }}>
              Startup name <span style={{ fontWeight: 400 }}>(optional)</span>
            </label>
            <input style={INPUT} placeholder="Acme Inc." value={company} onChange={e => setCompany(e.target.value)} />
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "#94a3b8" }}>
            What are you building? <span style={{ color: "#C0392B" }}>*</span>
          </label>
          <textarea style={{ ...INPUT, minHeight: 100, resize: "vertical", lineHeight: 1.6 }}
            placeholder="e.g. A SaaS tool that helps restaurant owners manage their inventory using AI predictions."
            value={goal} onChange={e => setGoal(e.target.value)} />
          <span style={{ fontSize: 11, color: "#94a3b8" }}>Be specific — agents tailor every artifact to your startup.</span>
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button style={{ ...BTN_PRIMARY, opacity: goal.trim().length > 10 ? 1 : 0.4 }} onClick={onNext} disabled={goal.trim().length <= 10}>
          Continue →
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
    { stack_id: "custom", name: "Build your own stack", target_user: "Founders with a unique workflow not covered by presets.", primary_outcome: "A fully custom agent configuration built from the workspace.", description: "", input_prompts: [], tasks: [], artifacts: [], approval_gates: [], connector_requirements: [], dashboard_sections: [], completion_rules: [] },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 6px", color: "#e2e8f0" }}>Choose your agent stack</h2>
        <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: 0, lineHeight: 1.6 }}>Each stack is a preset team of agents optimised for a specific goal. You can switch anytime.</p>
      </div>
      {recommendation && selectedStackId === recommendation.stack_id && (
        <div style={{ padding: "10px 14px", borderRadius: 12, background: "rgba(37,99,235,0.07)", border: "1px solid rgba(37,99,235,0.18)", fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.5 }}>
          <span style={{ fontWeight: 600, color: "#2563EB" }}>Suggested for you</span> — {recommendation.reason}
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
                    <span style={{ fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>{stack.name}</span>
                    {recommendation?.stack_id === stack.stack_id && (
                      <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 999, background: "rgba(37,99,235,0.12)", color: "#2563EB", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>Suggested</span>
                    )}
                  </div>
                  <p style={{ fontSize: 11, color: "var(--fg-mute)", margin: "3px 0 0", lineHeight: 1.45 }}>{stack.target_user}</p>
                </div>
              </div>
              {selected && stack.primary_outcome && (
                <p style={{ fontSize: 11, color: "var(--fg-dim)", margin: "10px 0 0", lineHeight: 1.5, borderTop: "1px solid rgba(0,0,0,0.06)", paddingTop: 10 }}>
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

// ── Step 4: Done ──────────────────────────────────────────────────────────────

function StepDone({ name, company, stackName, onLaunch }: { name: string; company: string; stackName: string; onLaunch: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, alignItems: "center", textAlign: "center" }}>
      <div style={{ fontSize: 56 }}>🎉</div>
      <div>
        <h2 style={{ fontSize: 26, fontWeight: 700, margin: "0 0 8px", color: "#e2e8f0" }}>
          You're all set{name ? `, ${name.split(" ")[0]}` : ""}!
        </h2>
        <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0, lineHeight: 1.7 }}>
          {company && <><strong style={{ color: "#e2e8f0" }}>{company}</strong> is ready to build with the </>}
          {!company && "You're building with the "}
          <strong style={{ color: "#e2e8f0" }}>{stackName}</strong> stack.
          <br />
          A brief tour will show you around when you launch.
        </p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, width: "100%", maxWidth: 420 }}>
        {[["🤖", "8 AI agents", "working in parallel"], ["📦", "Artifacts", "docs, code, plans"], ["⚡", "Real actions", "deploy, send, file"]].map(([icon, label, desc]) => (
          <div key={label} style={{ padding: "14px 10px", borderRadius: 16, border: "1px solid rgba(0,0,0,0.08)", background: "rgba(255,255,255,0.03)", display: "flex", flexDirection: "column", gap: 4, alignItems: "center" }}>
            <span style={{ fontSize: 22 }}>{icon}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0" }}>{label}</span>
            <span style={{ fontSize: 10, color: "#94a3b8" }}>{desc}</span>
          </div>
        ))}
      </div>
      <button style={{ ...BTN_PRIMARY, padding: "14px 40px", fontSize: 15 }} onClick={onLaunch}>
        Launch workspace →
      </button>
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function OnboardingWizard() {
  const router = useRouter();
  const { user, isLoaded } = useUser();
  const founderId = user?.id ?? "founder_001";
  const userEmail = user?.primaryEmailAddress?.emailAddress ?? "";

  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [goal, setGoal] = useState("");
  const [selectedStackId, setSelectedStackId] = useState("idea_to_revenue");
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [recommendation, setRecommendation] = useState<{ stack_id: string; reason: string } | null>(null);
  const [manualOverride, setManualOverride] = useState(false);
  const [readiness, setReadiness] = useState<StackReadiness | null>(null);

  useEffect(() => { getStacks().then(setStacks).catch(() => setStacks([])); }, []);

  useEffect(() => {
    if (goal.trim().length < 16) { setRecommendation(null); return; }
    const timer = window.setTimeout(() => {
      recommendStack(goal).then(r => {
        setRecommendation({ stack_id: r.stack.stack_id, reason: r.reason });
        if (!manualOverride) setSelectedStackId(r.stack.stack_id);
      }).catch(() => setRecommendation(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [goal, manualOverride]);

  useEffect(() => {
    if (!isLoaded || selectedStackId === "custom") { setReadiness(null); return; }
    getStackReadiness(founderId, selectedStackId).then(setReadiness).catch(() => setReadiness(null));
  }, [founderId, selectedStackId, isLoaded]);

  const selectedStack = stacks.find(s => s.stack_id === selectedStackId);
  const stackName = selectedStackId === "custom" ? "Custom Stack" : (selectedStack?.name ?? "Idea to Revenue Stack");

  async function handleLaunch() {
    try { await user?.update({ unsafeMetadata: { onboarding_done: true } }); } catch {}
    localStorage.setItem("astra_show_tour", "1");
    if (goal.trim()) localStorage.setItem("astra_onboarding_goal", goal.trim());
    if (company.trim()) localStorage.setItem("astra_onboarding_company", company.trim());
    // from_onboarding=1 tells AppHome not to open the new-goal overlay
    router.push("/?from_onboarding=1");
  }

  async function handleSkip() {
    try { await user?.update({ unsafeMetadata: { onboarding_done: true } }); } catch {}
    router.push("/?from_onboarding=1");
  }

  if (!isLoaded) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", color: "var(--fg-mute)", fontSize: 13 }}>Loading…</div>
  );

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "40px 16px", background: "var(--bg)" }}>
      {/* Logo */}
      <div style={{ position: "fixed", top: 24, left: 28, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 28, height: 28, borderRadius: "50%", background: "linear-gradient(135deg,#2563EB 0%,#7C3AED 100%)", display: "inline-block" }} />
        <span style={{ fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--fg)", fontWeight: 600 }}>Astra</span>
      </div>

      {/* Card */}
      <div style={{ width: "100%", maxWidth: 580, borderRadius: 28, border: "1px solid rgba(0,0,0,0.09)", background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", boxShadow: "var(--shadow-sm)", padding: "36px 40px" }}>
        <StepDots step={step} />

        {step === 0 && <StepWelcome name={name} setName={setName} company={company} setCompany={setCompany} goal={goal} setGoal={setGoal} onNext={() => setStep(1)} />}

        {step === 1 && (
          <StepChooseStack
            stacks={stacks} selectedStackId={selectedStackId}
            onSelect={id => { setManualOverride(true); setSelectedStackId(id); }}
            recommendation={recommendation} onBack={() => setStep(0)}
            onNext={() => setStep(selectedStackId === "custom" ? 3 : 2)}
          />
        )}

        {step === 2 && (
          <StepConnectIntegrations
            stackName={stackName} readiness={readiness}
            founderId={founderId} userEmail={userEmail}
            onBack={() => setStep(1)} onNext={() => setStep(3)}
          />
        )}

        {step === 3 && <StepDone name={name} company={company} stackName={stackName} onLaunch={handleLaunch} />}

        {/* Dev skip */}
        <div style={{ marginTop: 20, textAlign: "center" }}>
          <button onClick={handleSkip} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "var(--fg-mute)", textDecoration: "underline", opacity: 0.45 }}>
            Skip onboarding (dev)
          </button>
        </div>
      </div>
    </div>
  );
}
