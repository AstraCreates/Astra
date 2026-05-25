"use client";

import { useState, useEffect, useCallback } from "react";
import { useUser } from "@clerk/nextjs";
import Link from "next/link";
import { saveServiceCredential, getComposioOAuthUrls, getSetupStatus, SetupStatus } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SERVICES = [
  {
    key: "github",
    credKey: "token",
    label: "GitHub",
    icon: "🐙",
    desc: "Scaffold repos, push code, open PRs",
    placeholder: "ghp_xxxxxxxxxxxx",
    createUrl: "https://github.com/settings/tokens/new?description=Astra&scopes=repo,workflow",
    createLabel: "github.com/settings/tokens",
  },
  {
    key: "vercel",
    credKey: "token",
    label: "Vercel",
    icon: "▲",
    desc: "Deploy landing pages and apps",
    placeholder: "xxxxxxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://vercel.com/account/tokens",
    createLabel: "vercel.com/account/tokens",
  },
  {
    key: "sendgrid",
    credKey: "api_key",
    label: "SendGrid",
    icon: "✉️",
    desc: "Send email campaigns",
    placeholder: "SG.xxxxxxxxxxxxxxxx",
    createUrl: "https://app.sendgrid.com/settings/api_keys",
    createLabel: "app.sendgrid.com/settings/api_keys",
  },
] as const;

const COMPOSIO_APPS = [
  { key: "gmail", label: "Gmail", icon: "📧", desc: "Send from your inbox" },
  { key: "linkedin", label: "LinkedIn", icon: "💼", desc: "Post announcements" },
  { key: "googlecalendar", label: "Calendar", icon: "📅", desc: "Schedule meetings" },
  { key: "notion", label: "Notion", icon: "📝", desc: "Update wiki" },
  { key: "linear", label: "Linear", icon: "📋", desc: "Track issues" },
  { key: "github", label: "GitHub PRs", icon: "🔀", desc: "Open PRs via Composio" },
];

function glass(extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: "rgba(255,255,255,0.06)",
    backdropFilter: "blur(28px) saturate(180%)",
    WebkitBackdropFilter: "blur(28px) saturate(180%)",
    border: "1px solid rgba(255,255,255,0.09)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.12)",
    borderRadius: 14,
    ...extra,
  };
}

function StatusDot({ connected }: { connected: boolean }) {
  return (
    <span style={{
      width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
      background: connected ? "#6DC98A" : "rgba(255,255,255,0.18)",
      boxShadow: connected ? "0 0 6px rgba(109,201,138,0.5)" : "none",
      display: "inline-block",
    }} />
  );
}

function ServiceCard({
  svc, connected, founderId, onSaved,
}: {
  svc: typeof SERVICES[number];
  connected: boolean;
  founderId: string;
  onSaved: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    if (!value.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, svc.key, { [svc.credKey]: value.trim() });
      setSaved(true);
      setExpanded(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const isConnected = connected || saved;

  return (
    <div style={{
      ...glass(),
      border: `1px solid ${isConnected ? "rgba(60,170,100,0.28)" : "rgba(255,255,255,0.09)"}`,
      boxShadow: isConnected
        ? "inset 0 1px 0 rgba(255,255,255,0.10), 0 0 20px rgba(60,170,100,0.04)"
        : "inset 0 1px 0 rgba(255,255,255,0.10)",
      overflow: "hidden",
      transition: "border-color 0.3s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px" }}>
        <span style={{ fontSize: 20, flexShrink: 0 }}>{svc.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{svc.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{svc.desc}</span>
        </div>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{
            padding: "5px 14px", borderRadius: 8, fontSize: 12,
            background: isConnected ? "rgba(60,170,100,0.10)" : "rgba(255,255,255,0.07)",
            border: `1px solid ${isConnected ? "rgba(60,170,100,0.2)" : "rgba(255,255,255,0.10)"}`,
            color: isConnected ? "#6DC98A" : "var(--fg-dim)",
            cursor: "pointer", transition: "all 0.12s", flexShrink: 0,
          }}
        >
          {isConnected ? "Update →" : "Connect →"}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: "14px 18px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>
            Get token at{" "}
            <a href={svc.createUrl} target="_blank" rel="noopener noreferrer"
              style={{ color: "#8BA8C8", textDecoration: "none" }}>
              {svc.createLabel} ↗
            </a>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={svc.placeholder}
              onKeyDown={e => e.key === "Enter" && save()}
              className="site-input"
              style={{ flex: 1, padding: "8px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
            <button
              onClick={save}
              disabled={saving || !value.trim()}
              className="site-btn site-btn-primary"
              style={{ padding: "0 16px", fontSize: 12, flexShrink: 0 }}
            >
              {saving ? "…" : "Save"}
            </button>
          </div>
          {error && <p style={{ fontSize: 11, color: "#C97070", margin: 0 }}>{error}</p>}
        </div>
      )}
    </div>
  );
}

export default function SetupPage() {
  const { user, isLoaded } = useUser();
  const founderId = user?.id ?? "founder_001";

  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [composioKey, setComposioKey] = useState("");
  const [savingComposio, setSavingComposio] = useState(false);
  const [composioUrls, setComposioUrls] = useState<Record<string, string> | null>(null);
  const [loadingUrls, setLoadingUrls] = useState(false);
  const [composioError, setComposioError] = useState<string | null>(null);
  const [autoProvisioning, setAutoProvisioning] = useState(false);
  const [autoEmail, setAutoEmail] = useState("");
  const [autoPassword, setAutoPassword] = useState("");
  const [autoResult, setAutoResult] = useState<string[] | null>(null);
  const [showAutoProvision, setShowAutoProvision] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getSetupStatus(founderId);
      setStatus(s);
    } catch { /* no creds yet */ }
  }, [founderId]);

  const loadComposioUrls = useCallback(async () => {
    setLoadingUrls(true);
    setComposioError(null);
    try {
      const urls = await getComposioOAuthUrls(founderId);
      setComposioUrls(urls);
    } catch (e) {
      setComposioError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoadingUrls(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (!isLoaded || !user) return;
    loadStatus();
    loadComposioUrls();
  }, [isLoaded, user, loadStatus, loadComposioUrls]);

  async function saveComposioKey() {
    const key = composioKey.trim();
    if (!key) return;
    setSavingComposio(true);
    try {
      await saveServiceCredential(founderId, "composio", { api_key: key });
      setComposioKey("");
      await loadComposioUrls();
    } catch (e) {
      setComposioError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingComposio(false);
    }
  }

  async function runAutoProvision() {
    if (!autoEmail.trim() || !autoPassword.trim()) return;
    setAutoProvisioning(true);
    setAutoResult(null);
    try {
      const r = await fetch(`${BASE}/setup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: founderId, email: autoEmail, password: autoPassword }),
      });
      const d = await r.json();
      setAutoResult(d.summary ?? ["Done"]);
      await loadStatus();
      await loadComposioUrls();
    } catch (e) {
      setAutoResult([e instanceof Error ? e.message : "Failed"]);
    } finally {
      setAutoProvisioning(false);
    }
  }

  const connectedCount = status ? Object.values(status).filter(Boolean).length : 0;
  const totalServices = status ? Object.keys(status).length : 6;

  return (
    <div style={{ maxWidth: 740, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24, padding: "0 0 40px" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>
            Integrations
          </h1>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>
            Connect services once — agents use them everywhere
          </p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {status && (
            <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-mute)" }}>
              {connectedCount}/{totalServices} connected
            </span>
          )}
          <div style={{ height: 4, width: 120, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
            <div style={{
              height: "100%", borderRadius: 999,
              width: status ? `${(connectedCount / totalServices) * 100}%` : "0%",
              background: "linear-gradient(90deg,#1E6AFF,#5E9AE0)",
              transition: "width 0.6s",
            }} />
          </div>
        </div>
      </div>

      {/* Founder ID chip */}
      {isLoaded && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 14px", borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", width: "fit-content" }}>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Founder ID</span>
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>{founderId}</span>
        </div>
      )}

      {/* Core services */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.3)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Core services
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={status?.[svc.key as keyof SetupStatus] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      {/* Composio OAuth */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.3)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Composio — Gmail · LinkedIn · Calendar · Notion · Linear
        </p>
        <div style={{ ...glass(), padding: "16px 18px", display: "flex", flexDirection: "column", gap: 14 }}>
          {/* API key row */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: 12, fontWeight: 500, color: "var(--fg)", margin: "0 0 4px" }}>Composio API Key</p>
              <p style={{ fontSize: 11, color: "var(--fg-mute)", margin: 0 }}>
                Free at{" "}
                <a href="https://app.composio.dev/settings" target="_blank" rel="noopener noreferrer" style={{ color: "#8BA8C8", textDecoration: "none" }}>
                  app.composio.dev ↗
                </a>
              </p>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={composioKey}
                onChange={e => setComposioKey(e.target.value)}
                placeholder="api_key_..."
                onKeyDown={e => e.key === "Enter" && saveComposioKey()}
                className="site-input"
                style={{ width: 200, padding: "7px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }}
              />
              <button
                onClick={saveComposioKey}
                disabled={savingComposio || !composioKey.trim()}
                className="site-btn site-btn-primary"
                style={{ padding: "0 14px", fontSize: 12 }}
              >
                {savingComposio ? "…" : "Save"}
              </button>
            </div>
          </div>

          {composioError && <p style={{ fontSize: 11, color: "#C97070", margin: 0 }}>{composioError}</p>}

          {/* OAuth app grid */}
          {composioUrls && Object.keys(composioUrls).length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
              {COMPOSIO_APPS.map(app => {
                const url = composioUrls[app.key];
                const isError = !url || url.startsWith("error:");
                return (
                  <a
                    key={app.key}
                    href={isError ? undefined : url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 10,
                      background: isError ? "rgba(255,255,255,0.02)" : "rgba(30,106,255,0.07)",
                      border: `1px solid ${isError ? "rgba(255,255,255,0.06)" : "rgba(30,106,255,0.22)"}`,
                      textDecoration: "none", opacity: isError ? 0.45 : 1,
                      cursor: isError ? "not-allowed" : "pointer",
                      transition: "all 0.12s",
                    }}
                    onMouseEnter={e => { if (!isError) (e.currentTarget as HTMLElement).style.background = "rgba(30,106,255,0.13)"; }}
                    onMouseLeave={e => { if (!isError) (e.currentTarget as HTMLElement).style.background = "rgba(30,106,255,0.07)"; }}
                  >
                    <span style={{ fontSize: 16 }}>{app.icon}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: "var(--fg)" }}>{app.label}</p>
                      <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{app.desc}</p>
                    </div>
                    {!isError && <span style={{ fontSize: 11, color: "#8BA8C8", flexShrink: 0 }}>↗</span>}
                  </a>
                );
              })}
            </div>
          )}

          {!composioUrls && (
            <button
              onClick={loadComposioUrls}
              disabled={loadingUrls}
              style={{ alignSelf: "flex-start", padding: "7px 16px", borderRadius: 8, fontSize: 12, background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.10)", color: "var(--fg-dim)", cursor: "pointer" }}
            >
              {loadingUrls ? "Loading OAuth links…" : "Load OAuth links →"}
            </button>
          )}
        </div>
      </div>

      {/* Social — manual */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.3)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Social accounts — manual OAuth
        </p>
        <div style={{ ...glass(), padding: "14px 18px", display: "flex", gap: 12, flexWrap: "wrap" }}>
          {[
            { key: "instagram", label: "Instagram", icon: "📸", connected: status?.instagram },
            { key: "tiktok", label: "TikTok", icon: "🎵", connected: status?.tiktok },
            { key: "meta_ads", label: "Meta Ads", icon: "📢", connected: status?.meta_ads },
          ].map(svc => (
            <div key={svc.key} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
              <span>{svc.icon}</span>
              <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>{svc.label}</span>
              <StatusDot connected={!!svc.connected} />
              <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>
                {svc.connected ? "connected" : "requires phone verify"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Auto-provision (advanced) */}
      <div>
        <button
          onClick={() => setShowAutoProvision(v => !v)}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}
        >
          <span style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.3)", fontFamily: "var(--font-mono)" }}>
            Auto-provision (advanced) {showAutoProvision ? "▾" : "▸"}
          </span>
        </button>

        {showAutoProvision && (
          <div style={{ ...glass(), padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: 0, lineHeight: 1.6 }}>
              Astra can auto-create GitHub, Vercel, SendGrid, and Composio accounts using Playwright.
              Provide the email/password for a <strong style={{ color: "var(--fg-dim)" }}>new dedicated</strong> account — not your personal one.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input
                value={autoEmail}
                onChange={e => setAutoEmail(e.target.value)}
                placeholder="email@example.com"
                type="email"
                className="site-input"
                style={{ padding: "8px 12px", fontSize: 12 }}
              />
              <input
                value={autoPassword}
                onChange={e => setAutoPassword(e.target.value)}
                placeholder="Strong password"
                type="password"
                className="site-input"
                style={{ padding: "8px 12px", fontSize: 12 }}
              />
            </div>
            <button
              onClick={runAutoProvision}
              disabled={autoProvisioning || !autoEmail.trim() || !autoPassword.trim()}
              className="site-btn site-btn-primary"
              style={{ alignSelf: "flex-start", padding: "0 20px", fontSize: 13 }}
            >
              {autoProvisioning ? "Provisioning… (2–5 min)" : "Auto-provision →"}
            </button>
            {autoResult && (
              <div style={{ borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
                {autoResult.map((line, i) => (
                  <p key={i} style={{ margin: 0, fontSize: 12, color: line.startsWith("✓") ? "#6DC98A" : line.startsWith("✗") ? "#C97070" : "var(--fg-mute)", lineHeight: 1.5 }}>
                    {line}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* CTA */}
      <div style={{ display: "flex", gap: 10, paddingTop: 4 }}>
        <Link href="/dashboard" className="site-btn site-btn-primary" style={{ fontSize: 13, padding: "0 20px" }}>
          Go to dashboard →
        </Link>
      </div>
    </div>
  );
}
