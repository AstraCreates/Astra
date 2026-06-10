"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, getStacks, getAgentCatalog, recommendStack, getStackReadiness, getSetupStatus, saveServiceCredential, getComposioOAuthUrls, setupAccounts, submitGoal } from "@/lib/api";
import type { AgentStackTemplate, AgentCatalogEntry, StackReadiness } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Constants ─────────────────────────────────────────────────────────────────

const STACK_ICONS: Record<string, string> = {
  idea_to_revenue: "🚀", sales: "🤝", marketing: "📢",
  founder_ops: "🧭", support: "🎧", product: "📐", custom: "✨",
};

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
  "gmail",
  "linkedin",
  "google_calendar",
  "googlecalendar",
  "google_drive",
  "google_sheets",
  "notion",
  "linear",
  "product_tracker",
]);

const COMPOSIO_APP_KEYS: Record<string, string> = {
  google_calendar: "googlecalendar",
  google_sheets: "google_drive",
  product_tracker: "linear",
};

// ── Design tokens ─────────────────────────────────────────────────────────────

const T = {
  white: "#FFFFFF",
  surface: "#F3F4F7",
  textPrimary: "#111827",
  textSecondary: "#374151",
  textMuted: "#9CA3AF",
  grey: "#6B7280",
  blue: "#002EFF",
  blueHover: "#0024CC",
  blueTint: "#E8ECFF",
  blueMid: "#99AAFF",
  mint: "#7CFFC6",
  border: "#E5E7EB",
  borderStrong: "#D1D5DB",
  green: "#16A34A",
  greenTint: "#F0FDF4",
  greenBorder: "#86EFAC",
  red: "#DC2626",
  redTint: "#FEF2F2",
  redBorder: "#FECACA",
  shadow: "0 1px 3px rgba(0,0,0,0.08)",
  shadowMd: "0 4px 16px rgba(0,0,0,0.06)",
};

// ── Shared style objects ──────────────────────────────────────────────────────

const CARD: React.CSSProperties = {
  borderRadius: 16,
  border: `1px solid ${T.border}`,
  background: T.white,
  padding: "16px 18px",
  cursor: "pointer",
  transition: "border-color 0.15s, background 0.15s",
  boxShadow: T.shadow,
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
  color: T.white,
  border: "none",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  letterSpacing: "0.02em",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

const BTN_GHOST: React.CSSProperties = {
  padding: "10px 20px",
  borderRadius: 999,
  background: T.white,
  color: T.textSecondary,
  border: `1px solid ${T.border}`,
  fontSize: 13,
  cursor: "pointer",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

const INPUT: React.CSSProperties = {
  width: "100%",
  padding: "12px 16px",
  borderRadius: 12,
  border: `1px solid ${T.border}`,
  background: T.white,
  color: T.textPrimary,
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
  transition: "border-color 0.15s",
};

const LABEL: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase" as const,
  color: T.textMuted,
  fontWeight: 600,
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.1em",
  textTransform: "uppercase" as const,
  color: T.textMuted,
  fontWeight: 600,
  marginBottom: 6,
  fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
};

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ step, total = 4 }: { step: number; total?: number }) {
  return (
    <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 36 }}>
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          style={{
            width: 24,
            height: 8,
            borderRadius: 999,
            background: i === step ? T.blue : i < step ? T.blueMid : T.border,
            clipPath: `inset(0 ${i === step ? 0 : 66.67}% 0 0 round 999px)`,
            transition: "clip-path 0.25s cubic-bezier(0.22,1,0.36,1), background 0.25s",
          }}
        />
      ))}
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
  research: "🔍", legal: "⚖️", marketing: "📣", sales: "💰",
  technical: "⚙️", finance: "📊", ops: "🧭", web: "🌐", design: "🎨",
};

const _REQUIRED = new Set(["research"]);

function StepCustomStack({ selected, onToggle, onBack, onNext }: {
  selected: string[]; onToggle: (id: string) => void; onBack: () => void; onNext: () => void;
}) {
  const [catalog, setCatalog] = useState<AgentCatalogEntry[]>([]);
  useEffect(() => { getAgentCatalog().then(setCatalog).catch(() => {}); }, []);

  const grouped: Record<string, AgentCatalogEntry[]> = {};
  catalog.forEach(agent => {
    const group = agent.id.includes("_") ? agent.id.split("_")[0] : agent.id;
    if (!grouped[group]) grouped[group] = [];
    grouped[group].push(agent);
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 6px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Build your stack
        </h2>
        <p style={{ fontSize: 13, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          Pick the specific agents you need. Select at least 1.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxHeight: 420, overflowY: "auto", paddingRight: 4 }}>
        {GROUP_ORDER.filter(g => grouped[g]).map(group => (
          <div key={group}>
            <div style={{ ...SECTION_LABEL, display: "flex", alignItems: "center", gap: 5, marginBottom: 8 }}>
              <span>{GROUP_EMOJI[group]}</span>
              {GROUP_LABELS[group]}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {grouped[group].map(agent => {
                const active = selected.includes(agent.id);
                const required = _REQUIRED.has(agent.id);
                return (
                  <div
                    key={agent.id}
                    onClick={() => { if (!required) onToggle(agent.id); }}
                    style={{
                      borderRadius: 12,
                      border: `1.5px solid ${active ? T.blue : T.border}`,
                      background: active ? T.blueTint : T.white,
                      padding: "10px 12px",
                      cursor: required ? "default" : "pointer",
                      transition: "border-color 0.15s, background 0.15s",
                      opacity: required ? 0.75 : 1,
                      boxShadow: T.shadow,
                    }}
                  >
                    <div style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: active ? T.blue : T.textPrimary,
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
                    }}>
                      {agent.name}
                      {required
                        ? <span style={{ fontSize: 9, color: T.blue, textTransform: "uppercase", letterSpacing: "0.06em" }}>required</span>
                        : active && <span style={{ color: T.blue, fontSize: 13 }}>✓</span>}
                    </div>
                    <p style={{ fontSize: 10, color: T.textMuted, margin: "3px 0 0", lineHeight: 1.4 }}>
                      {agent.description.slice(0, 55)}…
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 12, color: T.textMuted, textAlign: "center" }}>
        {selected.length === 0 ? "Select at least 1 agent" : `${selected.length} agent${selected.length === 1 ? "" : "s"} selected`}
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
          __composio__: prev.__composio__ || !!status.composio,
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
    github: "🐙", vercel: "▲", supabase: "⚡", clerk: "🔐", gmail: "📧",
    google_drive: "📁", google_sheets: "📊", google_calendar: "📅", slack: "💬",
    notion: "📝", linear: "📐", crm: "👥", linkedin: "💼", meta_ads: "📱",
    analytics: "📈", website_cms: "🌐", helpdesk: "🎧", figma: "🎨", stripe: "💳",
  };

  const cardBtnStyle: React.CSSProperties = {
    padding: "6px 16px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    flexShrink: 0,
    whiteSpace: "nowrap",
    background: T.blue,
    color: T.white,
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
    background: T.white,
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
          <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>{icon}</span>
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
        <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>🔗</span>
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
      {expandedKey === "__composio__" && !composioConnected && (
        <div style={{
          borderTop: `1px solid ${T.border}`,
          padding: "12px 16px",
          background: T.blueTint,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}>
          <p style={{ margin: 0, fontSize: 11, color: T.textSecondary, lineHeight: 1.5 }}>
            In the popup go to <strong>Settings → API Keys</strong>, copy your key, paste here.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={tokenValues["__composio__"] ?? ""}
              onChange={e => setTokenValues(v => ({ ...v, "__composio__": e.target.value }))}
              placeholder="api_key_..."
              onKeyDown={e => e.key === "Enter" && saveComposio()}
              style={{ flex: 1, padding: "8px 12px", borderRadius: 10, fontSize: 12, fontFamily: "var(--font-mono, monospace)", border: `1px solid ${T.border}`, background: T.white, color: T.textPrimary, outline: "none" }}
            />
            <button
              onClick={saveComposio}
              disabled={saving === "__composio__" || !tokenValues["__composio__"]?.trim()}
              style={{ ...cardBtnStyle, padding: "0 16px", opacity: (!tokenValues["__composio__"]?.trim() || saving === "__composio__") ? 0.5 : 1 }}
            >
              {saving === "__composio__" ? "…" : "Save"}
            </button>
          </div>
          {errors["__composio__"] && <p style={{ margin: 0, fontSize: 11, color: T.red }}>{errors["__composio__"]}</p>}
        </div>
      )}
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
            {optional.map(c => card(c.key, ICONS[c.key] ?? "🔌", c.label, c.purpose, false))}
          </>
        )}
        <span style={{ ...SECTION_LABEL, marginTop: 12 }}>Payments</span>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <h1 style={{ fontSize: 32, fontWeight: 700, margin: "0 0 8px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          Welcome to Astra
        </h1>
        <p style={{ fontSize: 14, color: T.textMuted, margin: 0, lineHeight: 1.6 }}>
          8 AI agents working in parallel to build your startup. Let's get you set up.
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

// ── Step 4: Done ──────────────────────────────────────────────────────────────

function StepDone({ name, company, stackName, onLaunch }: {
  name: string; company: string; stackName: string; onLaunch: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28, alignItems: "center", textAlign: "center" }}>
      <div style={{ fontSize: 56, lineHeight: 1 }}>🎉</div>

      <div>
        <h2 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 10px", color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif", letterSpacing: "-0.02em" }}>
          You're all set{name ? `, ${name.split(" ")[0]}` : ""}!
        </h2>
        <p style={{ fontSize: 14, color: T.textMuted, margin: 0, lineHeight: 1.7 }}>
          {company && <><strong style={{ color: T.textPrimary }}>{company}</strong> is ready to build with the </>}
          {!company && "You're building with the "}
          <strong style={{ color: T.textPrimary }}>{stackName}</strong> stack.
          <br />
          A brief tour will show you around when you launch.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, width: "100%", maxWidth: 420 }}>
        {[
          ["🤖", "8 AI agents", "working in parallel"],
          ["📦", "Artifacts", "docs, code, plans"],
          ["⚡", "Real actions", "deploy, send, file"],
        ].map(([icon, label, desc]) => (
          <div key={label} style={{
            padding: "16px 12px",
            borderRadius: 14,
            border: `1px solid ${T.border}`,
            background: T.surface,
            display: "flex",
            flexDirection: "column",
            gap: 4,
            alignItems: "center",
            boxShadow: T.shadow,
          }}>
            <span style={{ fontSize: 22 }}>{icon}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.textPrimary, fontFamily: "var(--font-geist-sans), 'Geist', sans-serif" }}>{label}</span>
            <span style={{ fontSize: 10, color: T.textMuted }}>{desc}</span>
          </div>
        ))}
      </div>

      <button style={{ ...BTN_PRIMARY, padding: "14px 44px", fontSize: 15 }} onClick={onLaunch}>
        Launch workspace →
      </button>
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function OnboardingWizard() {
  const router = useRouter();
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const userEmail = "";

  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [goal, setGoal] = useState("");
  const [selectedStackId, setSelectedStackId] = useState("idea_to_revenue");
  const REQUIRED_AGENTS = new Set(["research"]);
  const [customAgents, setCustomAgents] = useState<string[]>(["research", "web", "technical", "marketing"]);
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [recommendation, setRecommendation] = useState<{ stack_id: string; reason: string } | null>(null);
  const [manualOverride, setManualOverride] = useState(false);
  const [readiness, setReadiness] = useState<StackReadiness | null>(null);

  function toggleCustomAgent(id: string) {
    if (REQUIRED_AGENTS.has(id)) return;
    setCustomAgents(prev => prev.includes(id) ? prev.filter(a => a !== id) : [...prev, id]);
  }

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
    if (selectedStackId === "custom") { setReadiness(null); return; }
    getStackReadiness(founderId, selectedStackId).then(setReadiness).catch(() => setReadiness(null));
  }, [founderId, selectedStackId]);

  const selectedStack = stacks.find(s => s.stack_id === selectedStackId);
  const stackName = selectedStackId === "custom" ? "Custom Stack" : (selectedStack?.name ?? "Idea to Revenue Stack");

  const [launching, setLaunching] = useState(false);

  // localStorage may be full (quota exceeded). A thrown setItem must never block
  // navigation, AND the onboarding-done flag MUST persist — AppHome gates the whole
  // app on it, so if it doesn't save the user is stuck on the welcome screen. Try
  // increasingly aggressive eviction until the (tiny) write succeeds.
  function lsSet(key: string, val: string) {
    try { localStorage.setItem(key, val); return; } catch { /* full */ }
    for (const k of ["astra_sessions", "astra_workspaces", "astra_events", "astra_chapters"]) {
      try { localStorage.removeItem(k); localStorage.setItem(key, val); return; } catch { /* keep evicting */ }
    }
    // Last resort: wipe everything so the critical flag lands (loses local history).
    try { localStorage.clear(); localStorage.setItem(key, val); } catch { /* localStorage unavailable */ }
  }

  async function handleLaunch() {
    if (launching) return;
    lsSet("astra_onboarding_done", "1");
    lsSet("astra_show_tour", "1");
    // Persist for any consumer that reads these (tour, prefill, etc.).
    if (name.trim()) lsSet("astra_onboarding_name", name.trim());
    if (goal.trim()) lsSet("astra_onboarding_goal", goal.trim());
    if (company.trim()) lsSet("astra_onboarding_company", company.trim());
    if (selectedStackId === "custom" && customAgents.length > 0) {
      lsSet("astra_custom_agents", JSON.stringify(customAgents));
      lsSet("astra_onboarding_stack", "custom");
    } else {
      lsSet("astra_onboarding_stack", selectedStackId);
    }
    const g = goal.trim();
    const nm = (company.trim() || name.trim());
    const stack = selectedStackId || "idea_to_revenue";
    // No goal yet → land on the dashboard (now onboarded) so the user can start one.
    if (!g) { router.push("/"); return; }
    setLaunching(true);
    try {
      // Same launch path as the New Goal view: submit, then open the live session.
      const instruction = nm ? `Company/project name: ${nm}\n\n${g}` : g;
      const constraints = (selectedStackId === "custom" && customAgents.length > 0)
        ? { custom_agents: customAgents } : {};
      const data = await submitGoal(founderId, instruction, constraints, stack);
      if (!data.session_id) throw new Error("No session_id returned");
      window.location.assign(`/s/${data.session_id}`);
    } catch (e) {
      // Never leave the button dead — fall back to the dashboard.
      console.error("onboarding launch failed:", e);
      setLaunching(false);
      router.push("/");
    }
  }

  async function handleSkip() {
    lsSet("astra_onboarding_done", "1");
    router.push("/");
  }

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "center",
      padding: "48px 16px",
      background: "linear-gradient(160deg, rgba(0,46,255,0.06) 0%, #F3F4F7 40%)",
      fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
    }}>
      {/* Logo */}
      <div style={{ position: "fixed", top: 24, left: 28, display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 28, height: 28, background: T.blue, flexShrink: 0,
          WebkitMask: "url('/logo.png') center/contain no-repeat",
          mask: "url('/logo.png') center/contain no-repeat",
        }} />
        <span style={{
          fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase",
          color: T.textPrimary, fontWeight: 700,
        }}>Astra</span>
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
        <StepDots step={step} total={4} />

        {step === 0 && (
          <StepWelcome
            name={name} setName={setName}
            company={company} setCompany={setCompany}
            goal={goal} setGoal={setGoal}
            onNext={() => setStep(1)}
          />
        )}

        {step === 1 && (
          <StepChooseStack
            stacks={stacks} selectedStackId={selectedStackId}
            onSelect={id => { setManualOverride(true); setSelectedStackId(id); }}
            recommendation={recommendation} onBack={() => setStep(0)}
            onNext={() => setStep(selectedStackId === "custom" ? 2 : 3)}
          />
        )}

        {step === 2 && selectedStackId === "custom" && (
          <StepCustomStack
            selected={customAgents} onToggle={toggleCustomAgent}
            onBack={() => setStep(1)} onNext={() => setStep(4)}
          />
        )}

        {step === 3 && (
          <StepConnectIntegrations
            stackName={stackName} readiness={readiness}
            founderId={founderId} userEmail={userEmail}
            onBack={() => setStep(1)} onNext={() => setStep(4)}
          />
        )}

        {step === 4 && (
          <StepDone name={name} company={company} stackName={stackName} onLaunch={handleLaunch} />
        )}

        {/* Dev skip */}
        <div style={{ marginTop: 24, textAlign: "center" }}>
          <button
            onClick={handleSkip}
            style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 11, color: T.textMuted, textDecoration: "underline", opacity: 0.5,
            }}
          >
            Skip onboarding (dev)
          </button>
        </div>
      </div>
    </div>
  );
}


