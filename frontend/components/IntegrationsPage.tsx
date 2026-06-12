"use client";

import { useState, useEffect, useCallback, useRef } from "react";

import ServiceLogo from "@/components/ServiceLogo";
import { useDevUser } from "@/lib/use-dev-user";
import Link from "next/link";
import { apiFetch, saveServiceCredential, getComposioOAuthUrls, getSetupStatus, SetupStatus } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Design tokens ─────────────────────────────────────────────────────────────
const c = {
  bg: "#FFFFFF",
  surface: "#F8F9FA",
  border: "#E5E7EB",
  borderStrong: "#D1D5DB",
  text: "#111827",
  textSecondary: "#374151",
  textMuted: "#9CA3AF",
  grey: "#6B7280",
  blue: "#002EFF",
  blueHover: "#1f36e0",
  blueTint: "#EFF6FF",
  blueBorder: "#BFDBFE",
  green: "#16a34a",
  greenTint: "#F0FDF4",
  greenBorder: "#BBF7D0",
  red: "#dc2626",
  redTint: "#FEF2F2",
  redBorder: "#FECACA",
  amber: "#d97706",
};

const SERVICES = [
  {
    key: "github",
    credKey: "token",
    label: "GitHub",
    icon: "●",
    desc: "Scaffold repos, push code, open PRs",
    placeholder: "ghp_xxxxxxxxxxxx",
    createUrl: "https://github.com/settings/tokens/new?description=Astra&scopes=repo,workflow",
    createLabel: "github.com/settings/tokens",
    steps: 3,
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
    steps: 3,
  },
  {
    key: "sendgrid",
    credKey: "api_key",
    label: "SendGrid",
    icon: "◻",
    desc: "Send email campaigns",
    placeholder: "SG.xxxxxxxxxxxxxxxx",
    createUrl: "https://app.sendgrid.com/settings/api_keys",
    createLabel: "app.sendgrid.com/settings/api_keys",
    steps: 3,
  },
] as const;

const ECOMM_SERVICES = [
  {
    key: "klaviyo",
    credKey: "api_key",
    label: "Klaviyo",
    icon: "◻",
    desc: "Email flows & campaigns for ecomm",
    placeholder: "pk_xxxxxxxxxxxxxxxx",
    createUrl: "https://www.klaviyo.com/account#api-keys-tab",
    createLabel: "klaviyo.com/account",
    steps: 3,
  },
  {
    key: "printful",
    credKey: "api_key",
    label: "Printful",
    icon: "◻",
    desc: "Print-on-demand fulfillment",
    placeholder: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://www.printful.com/dashboard/settings/api",
    createLabel: "printful.com/dashboard/settings/api",
    steps: 3,
  },
  {
    key: "lemonsqueezy",
    credKey: "api_key",
    label: "Lemon Squeezy",
    icon: "◻",
    desc: "Digital product sales (5%+50¢/txn)",
    placeholder: "eyJhbGciOiJSUzI1...",
    createUrl: "https://app.lemonsqueezy.com/settings/api",
    createLabel: "app.lemonsqueezy.com/settings/api",
    steps: 3,
  },
  {
    key: "square",
    credKey: "access_token",
    label: "Square",
    icon: "◻",
    desc: "POS, bookings & payments (sandbox first)",
    placeholder: "EAAAlb...",
    createUrl: "https://developer.squareup.com/apps",
    createLabel: "developer.squareup.com/apps",
    steps: 3,
  },
  {
    key: "yelp",
    credKey: "api_key",
    label: "Yelp Fusion",
    icon: "◻",
    desc: "Competitor & market research (500 req/day free)",
    placeholder: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://www.yelp.com/developers/v3/manage_app",
    createLabel: "yelp.com/developers",
    steps: 3,
  },
] as const;

const COMPOSIO_APPS = [
  { key: "gmail", label: "Gmail", icon: "◻", desc: "Send from your inbox" },
  { key: "linkedin", label: "LinkedIn", icon: "▪", desc: "Post announcements" },
  { key: "googlecalendar", label: "Calendar", icon: "▣", desc: "Schedule meetings" },
  { key: "notion", label: "Notion", icon: "▷", desc: "Update wiki" },
  { key: "linear", label: "Linear", icon: "◈", desc: "Track issues" },
  { key: "github", label: "GitHub PRs", icon: "●", desc: "Open PRs via Composio" },
];

// ── Types ──────────────────────────────────────────────────────────────────

interface FilingField {
  name: string;
  label: string;
  type: "text" | "email" | "password" | "tel" | "select" | "disclaimer";
  required?: boolean;
  placeholder?: string;
  default?: string;
  options?: { value: string; label: string; description?: string }[];
}

type ModalPhase = "connecting" | "running" | "user_control" | "interaction_needed" | "bot_filling" | "done" | "error";

// ── Shared card style helper ───────────────────────────────────────────────

function cardStyle(connected: boolean, active = false): React.CSSProperties {
  return {
    background: c.bg,
    border: `1px solid ${connected ? c.greenBorder : active ? c.blue : c.border}`,
    borderRadius: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
    overflow: "hidden",
    transition: "border-color 0.2s",
  };
}

// ── StatusDot ────────────────────────────────────────────────────────────────

function StatusDot({ connected }: { connected: boolean }) {
  return (
    <span style={{
      width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
      background: connected ? c.green : c.borderStrong,
      display: "inline-block",
    }} />
  );
}

// ── IntegrationModal ───────────────────────────────────────────────────────

function IntegrationModal({
  serviceKey, label, icon, stepCount, founderId, onConnected, onClose,
}: {
  serviceKey: string;
  label: string;
  icon: string;
  stepCount: number;
  founderId: string;
  onConnected: () => void;
  onClose: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [phase, setPhase] = useState<ModalPhase>("connecting");
  const [stepName, setStepName] = useState("Starting…");
  const [stepNum, setStepNum] = useState(0);
  const [message, setMessage] = useState("");
  const [fields, setFields] = useState<FilingField[]>([]);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const wsBase = BASE.replace("https://", "wss://").replace("http://", "ws://");
    const ws = new WebSocket(`${wsBase}/connect/${serviceKey}/stream/${founderId}`);
    wsRef.current = ws;

    ws.onopen = () => setPhase("running");
    ws.onerror = () => { setPhase("error"); setMessage("WebSocket connection failed."); };
    ws.onclose = () => { if (phase !== "done" && phase !== "error") setPhase("error"); };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "frame") {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const img = new Image();
        img.onload = () => {
          canvas.width = img.naturalWidth || 1280;
          canvas.height = img.naturalHeight || 800;
          ctx.drawImage(img, 0, 0);
        };
        img.src = `data:image/jpeg;base64,${msg.data}`;
        return;
      }
      if (msg.type === "user_control") {
        setStepName(msg.step); setStepNum(msg.step_num ?? 1);
        setMessage(msg.message || "Sign in in the browser below.");
        setPhase("user_control");
      } else if (msg.type === "status") {
        setStepName(msg.step); setStepNum(msg.step_num);
        setPhase("running"); setMessage("");
      } else if (msg.type === "interaction_needed") {
        setStepName(msg.step); setMessage(msg.message);
        setFields(msg.fields || []); setFormValues({});
        setFormError(""); setPhase("interaction_needed");
      } else if (msg.type === "bot_filling") {
        setPhase("bot_filling"); setMessage("Filling your information…");
      } else if (msg.type === "done") {
        setPhase("done"); onConnected();
      } else if (msg.type === "error") {
        setPhase("error"); setMessage(msg.message || "An error occurred.");
      }
    };

    return () => { ws.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitInput = () => {
    const data = { ...formValues };
    fields.forEach(f => { if (f.type === "select" && !data[f.name] && f.default) data[f.name] = f.default; });
    const missing = fields.filter(f => f.required && f.type !== "select" && f.type !== "disclaimer" && !data[f.name]?.trim());
    if (missing.length) { setFormError(`Required: ${missing.map(f => f.label).join(", ")}`); return; }
    setSubmitting(true); setFormError("");
    wsRef.current?.send(JSON.stringify({ type: "founder_input", data }));
    setPhase("bot_filling"); setSubmitting(false);
  };

  const stepPercent = stepCount > 0 ? Math.round((stepNum / stepCount) * 100) : 0;
  const isUserControl = phase === "user_control";
  const isLocked = phase !== "interaction_needed" && !isUserControl;

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isUserControl) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.round((e.clientX - rect.left) * (canvas.width / rect.width));
    const y = Math.round((e.clientY - rect.top) * (canvas.height / rect.height));
    wsRef.current?.send(JSON.stringify({ type: "mouse_event", x, y }));
    canvas.focus();
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isUserControl) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.round((e.clientX - rect.left) * (canvas.width / rect.width));
    const y = Math.round((e.clientY - rect.top) * (canvas.height / rect.height));
    wsRef.current?.send(JSON.stringify({ type: "mouse_move", x, y }));
  };

  const handleCanvasKey = (e: React.KeyboardEvent<HTMLCanvasElement>) => {
    if (!isUserControl) return;
    e.preventDefault();
    const printable = e.key.length === 1 ? e.key : "";
    const special = ["Enter","Tab","Backspace","Delete","ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Escape"].includes(e.key) ? e.key : "";
    if (printable || special) {
      wsRef.current?.send(JSON.stringify({ type: "key_event", key: e.key, char: printable }));
    }
  };

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(0,0,0,0.5)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        width: "100%", maxWidth: 960, maxHeight: "calc(100vh - 48px)",
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 16,
        boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
        overflow: "hidden", display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: `1px solid ${c.border}`, background: c.surface }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <ServiceLogo serviceKey={serviceKey} label={label} size={20} />
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Connecting {label}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 12, color: c.textMuted }}>
              {stepNum > 0 ? `Step ${stepNum}/${stepCount} — ${stepName}` : stepName}
            </span>
            {phase !== "done" && (
              <button
                onClick={() => { wsRef.current?.close(); onClose(); }}
                style={{
                  fontSize: 12, padding: "5px 12px", borderRadius: 8,
                  background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ height: 3, background: c.border }}>
          <div style={{
            height: "100%", borderRadius: 999, width: "100%",
            transform: `scaleX(${(phase === "done" ? 100 : stepPercent) / 100})`,
            transformOrigin: "left",
            transition: "transform 0.6s cubic-bezier(0.22,1,0.36,1)",
            background: phase === "done" ? c.green : c.blue,
          }} />
        </div>

        {/* Browser canvas */}
        <div style={{ position: "relative", background: "#0f172a", flex: "1 1 auto", overflow: "auto", minHeight: 280 }}>
          <canvas
            ref={canvasRef}
            tabIndex={isUserControl ? 0 : -1}
            onClick={handleCanvasClick}
            onMouseMove={handleCanvasMouseMove}
            onKeyDown={handleCanvasKey}
            style={{
              width: "100%", height: "auto", maxHeight: "55vh",
              objectFit: "contain", display: "block",
              pointerEvents: isUserControl ? "auto" : "none",
              cursor: isUserControl ? "crosshair" : "default",
              outline: isUserControl ? `2px solid ${c.blue}` : "none",
            }}
          />

          {isLocked && phase !== "done" && phase !== "error" && phase !== "connecting" && (
            <div style={{ position: "absolute", inset: 0, cursor: "not-allowed", zIndex: 10 }} />
          )}

          {isUserControl && (
            <div style={{
              position: "absolute", top: 10, left: "50%", transform: "translateX(-50%)",
              padding: "8px 18px", borderRadius: 24, zIndex: 20,
              background: c.blueTint, border: `1px solid ${c.blueBorder}`,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: c.blue, flexShrink: 0 }} />
              <span style={{ fontSize: 12, color: c.blue, whiteSpace: "nowrap" }}>
                {message || "Sign in — click and type directly in the browser"}
              </span>
            </div>
          )}

          {phase === "connecting" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 }}>
              <div style={{ width: 28, height: 28, border: "3px solid rgba(255,255,255,0.15)", borderTopColor: c.blue, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
              <span style={{ fontSize: 13, color: "rgba(255,255,255,0.5)" }}>Connecting…</span>
            </div>
          )}

          {(phase === "running" || phase === "bot_filling") && (
            <div style={{ position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)", padding: "8px 20px", borderRadius: 20, background: "rgba(0,0,0,0.7)", border: "1px solid rgba(255,255,255,0.1)", display: "flex", alignItems: "center", gap: 8, zIndex: 20, whiteSpace: "nowrap" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: c.blue, animation: "spin 0.8s linear infinite" }} />
              <span style={{ fontSize: 12, color: "rgba(255,255,255,0.7)" }}>{stepName || "Working…"}</span>
            </div>
          )}

          {phase === "done" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20, background: "rgba(0,0,0,0.5)" }}>
              <div style={{ padding: "28px 40px", borderRadius: 16, background: c.bg, border: `1px solid ${c.greenBorder}`, textAlign: "center", boxShadow: "0 10px 40px rgba(0,0,0,0.2)" }}>
                <div style={{ width: 48, height: 48, borderRadius: "50%", background: c.greenTint, border: `1px solid ${c.greenBorder}`, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 12px", fontSize: 20 }}>✓</div>
                <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: c.green }}>{label} Connected!</p>
                <button
                  onClick={onClose}
                  style={{ marginTop: 16, padding: "8px 24px", borderRadius: 8, background: c.blue, color: "#FFFFFF", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500 }}
                >Done</button>
              </div>
            </div>
          )}

          {phase === "error" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20, background: "rgba(0,0,0,0.5)" }}>
              <div style={{ padding: "24px 32px", borderRadius: 16, background: c.bg, border: `1px solid ${c.redBorder}`, textAlign: "center", maxWidth: 400, boxShadow: "0 10px 40px rgba(0,0,0,0.2)" }}>
                <div style={{ fontSize: 24, marginBottom: 8, color: c.red }}>⚠</div>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: c.red }}>Connection failed</p>
                <p style={{ margin: "6px 0 0", fontSize: 13, color: c.grey }}>{message}</p>
                <button
                  onClick={onClose}
                  style={{ marginTop: 14, fontSize: 13, padding: "6px 18px", borderRadius: 8, color: c.red, background: c.redTint, border: `1px solid ${c.redBorder}`, cursor: "pointer" }}
                >Close</button>
              </div>
            </div>
          )}
        </div>

        {/* Interaction form */}
        {phase === "interaction_needed" && fields.length > 0 && (
          <div style={{ padding: "16px 20px", borderTop: `1px solid ${c.border}`, display: "flex", flexDirection: "column", gap: 12, background: c.surface }}>
            {message && <p style={{ margin: 0, fontSize: 13, color: c.textSecondary }}>{message}</p>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
              {fields.filter(f => f.type !== "disclaimer").map(f => (
                <div key={f.name} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <label style={{ fontSize: 11, color: c.grey, fontWeight: 500 }}>{f.label}{f.required && " *"}</label>
                  {f.type === "select" && f.options ? (
                    <select
                      value={formValues[f.name] ?? f.default ?? ""}
                      onChange={e => setFormValues(v => ({ ...v, [f.name]: e.target.value }))}
                      style={{ padding: "8px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none" }}
                    >
                      {f.options.map(o => (
                        <option key={o.value} value={o.value}>{o.label}{o.description ? ` — ${o.description}` : ""}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={f.type}
                      placeholder={f.placeholder}
                      value={formValues[f.name] ?? ""}
                      onChange={e => setFormValues(v => ({ ...v, [f.name]: e.target.value }))}
                      onKeyDown={e => { if (e.key === "Enter") submitInput(); }}
                      style={{ padding: "8px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none" }}
                      onFocus={e => (e.target.style.borderColor = c.blue)}
                      onBlur={e => (e.target.style.borderColor = c.border)}
                    />
                  )}
                </div>
              ))}
            </div>
            {fields.find(f => f.type === "disclaimer") && (
              <p style={{ margin: 0, fontSize: 12, color: c.textMuted, fontStyle: "italic" }}>
                {fields.find(f => f.type === "disclaimer")!.label}
              </p>
            )}
            {formError && <p style={{ margin: 0, fontSize: 12, color: c.red }}>{formError}</p>}
            <button
              onClick={submitInput}
              disabled={submitting}
              style={{ alignSelf: "flex-start", padding: "8px 20px", borderRadius: 8, background: c.blue, color: "#FFFFFF", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500 }}
            >
              {submitting ? "…" : "Continue →"}
            </button>
          </div>
        )}
      </div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

// ── ServiceCard ────────────────────────────────────────────────────────────

type AnyService = typeof SERVICES[number] | typeof ECOMM_SERVICES[number];

function ServiceCard({
  svc, connected, founderId, onSaved,
}: {
  svc: AnyService;
  connected: boolean;
  founderId: string;
  onSaved: () => void;
}) {
  const [popupOpen, setPopupOpen] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (svc.key !== "github") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("github_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      setJustConnected(true);
      onSaved();
    }
  }, [svc.key, onSaved]);

  const connectGitHubOAuth = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch(`${BASE}/github/oauth-url/${founderId}`);
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`);
        setConnecting(false);
        return;
      }
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError("No OAuth URL returned from server");
        setConnecting(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach server");
      setConnecting(false);
    }
  };

  const openPopup = () => {
    const popup = window.open(svc.createUrl, `connect_${svc.key}`, "width=1060,height=720,scrollbars=yes,resizable=yes");
    popupRef.current = popup;
    setPopupOpen(true);
    setValue("");
    setError(null);
    setTimeout(() => inputRef.current?.focus(), 300);
  };

  useEffect(() => {
    if (!popupOpen) return;
    const interval = setInterval(() => {
      if (popupRef.current?.closed) { clearInterval(interval); setPopupOpen(false); }
    }, 600);
    return () => clearInterval(interval);
  }, [popupOpen]);

  async function save() {
    if (!value.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, svc.key, { [svc.credKey]: value.trim() });
      setJustConnected(true);
      setPopupOpen(false);
      popupRef.current?.close();
      setValue("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const isConnected = connected || justConnected;
  const isGitHub = svc.key === "github";

  return (
    <div style={cardStyle(isConnected, popupOpen && !isConnected)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey={svc.key} label={svc.label} size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>{svc.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
            {popupOpen && !isConnected && <span style={{ fontSize: 11, color: c.blue, fontWeight: 500 }}>Popup open</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>{svc.desc}</span>
        </div>
        <button
          onClick={isGitHub ? connectGitHubOAuth : openPopup}
          disabled={connecting}
          style={{
            padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
            background: isConnected ? c.greenTint : c.bg,
            border: `1px solid ${isConnected ? c.greenBorder : c.border}`,
            color: isConnected ? c.green : c.textSecondary,
            cursor: connecting ? "wait" : "pointer",
          }}
        >
          {connecting ? "Redirecting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>

      {isGitHub && error && (
        <div style={{ borderTop: `1px solid ${c.redBorder}`, padding: "10px 18px", background: c.redTint }}>
          <p style={{ margin: 0, fontSize: 12, color: c.red }}>{error}</p>
        </div>
      )}

      {!isGitHub && popupOpen && (
        <div style={{
          borderTop: `1px solid ${c.blueBorder}`,
          padding: "14px 18px", background: c.blueTint,
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          <p style={{ margin: 0, fontSize: 13, color: c.textSecondary, lineHeight: 1.6 }}>
            Create a token in the popup, then paste it here.{" "}
            <span style={{ color: c.blue, fontWeight: 500 }}>The popup is open ↗</span>
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={svc.placeholder}
              onKeyDown={e => e.key === "Enter" && save()}
              style={{
                flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8,
                border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none",
                fontFamily: "var(--font-geist-mono, monospace)",
              }}
              onFocus={e => (e.target.style.borderColor = c.blue)}
              onBlur={e => (e.target.style.borderColor = c.border)}
            />
            <button
              onClick={save}
              disabled={saving || !value.trim()}
              style={{
                padding: "0 16px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: saving || !value.trim() ? "not-allowed" : "pointer",
                opacity: saving || !value.trim() ? 0.6 : 1,
              }}
            >
              {saving ? "…" : "Save"}
            </button>
          </div>
          {error && <p style={{ fontSize: 12, color: c.red, margin: 0 }}>{error}</p>}
        </div>
      )}
    </div>
  );
}

// ── StripeCard ─────────────────────────────────────────────────────────────

function StripeCard({ founderId, email }: { founderId: string; email: string }) {
  const [stripeStatus, setStripeStatus] = useState<{ connected: boolean; charges_enabled?: boolean; email?: string; livemode?: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    apiFetch(`${BASE}/stripe/status/${founderId}`)
      .then(r => r.json())
      .then(setStripeStatus)
      .catch(() => setStripeStatus({ connected: false }))
      .finally(() => setLoading(false));
  }, [founderId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("stripe_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      apiFetch(`${BASE}/stripe/status/${founderId}`).then(r => r.json()).then(setStripeStatus);
    }
  }, [founderId]);

  const connect = async () => {
    setConnecting(true);
    try {
      const res = await apiFetch(`${BASE}/stripe/oauth-url/${founderId}?email=${encodeURIComponent(email)}`);
      const data = await res.json();
      if (data.url) window.location.href = data.url;
    } finally {
      setConnecting(false);
    }
  };

  const isConnected = stripeStatus?.connected;

  return (
    <div style={cardStyle(!!isConnected)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <span style={{ fontSize: 18, fontWeight: 700, flexShrink: 0, color: c.text, width: 28, textAlign: "center" }}>$</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Stripe</span>
            {!loading && <StatusDot connected={!!isConnected} />}
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
            {isConnected && stripeStatus?.livemode === false && (
              <span style={{ fontSize: 11, color: c.textMuted }}>· Test mode</span>
            )}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>
            {isConnected ? stripeStatus?.email ?? "Account linked" : "Accept payments, track revenue"}
          </span>
        </div>
        {loading ? (
          <span style={{ fontSize: 13, color: c.textMuted }}>…</span>
        ) : isConnected ? (
          <span style={{ fontSize: 12, color: c.green, fontWeight: 500, flexShrink: 0 }}>Ready for stack runs</span>
        ) : (
          <button
            onClick={connect}
            disabled={connecting}
            style={{
              padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500, flexShrink: 0,
              background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
            }}
          >
            {connecting ? "Redirecting…" : "Connect →"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── ComposioKeyCard ────────────────────────────────────────────────────────

function ComposioKeyCard({ connected, saving, error, onSave }: {
  connected: boolean;
  saving: boolean;
  error: string | null;
  onSave: (key: string) => Promise<void>;
}) {
  const [popupOpen, setPopupOpen] = useState(false);
  const [value, setValue] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const popupRef = useRef<Window | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const openPopup = () => {
    const popup = window.open(
      "https://app.composio.dev/settings",
      "connect_composio",
      "width=1060,height=720,scrollbars=yes,resizable=yes",
    );
    popupRef.current = popup;
    setPopupOpen(true);
    setValue("");
    setLocalError(null);
    setTimeout(() => inputRef.current?.focus(), 300);
  };

  useEffect(() => {
    if (!popupOpen) return;
    const interval = setInterval(() => {
      if (popupRef.current?.closed) { clearInterval(interval); setPopupOpen(false); }
    }, 600);
    return () => clearInterval(interval);
  }, [popupOpen]);

  const save = async () => {
    if (!value.trim()) return;
    setLocalError(null);
    try {
      await onSave(value.trim());
      setPopupOpen(false);
      popupRef.current?.close();
      setValue("");
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Save failed");
    }
  };

  return (
    <div style={cardStyle(connected, popupOpen && !connected)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: connected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey="composio" label="Composio" size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Composio</span>
            <StatusDot connected={connected} />
            {connected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
            {popupOpen && !connected && <span style={{ fontSize: 11, color: c.blue, fontWeight: 500 }}>Popup open</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>Enables Gmail, LinkedIn, Notion, Linear, Calendar</span>
        </div>
        <button
          onClick={openPopup}
          style={{
            padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
            background: connected ? c.greenTint : c.bg,
            border: `1px solid ${connected ? c.greenBorder : c.border}`,
            color: connected ? c.green : c.textSecondary,
            cursor: "pointer",
          }}
        >
          {connected ? "Update key ↗" : "Connect ↗"}
        </button>
      </div>

      {popupOpen && (
        <div style={{
          borderTop: `1px solid ${c.blueBorder}`,
          padding: "14px 18px", background: c.blueTint,
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          <p style={{ margin: 0, fontSize: 13, color: c.textSecondary, lineHeight: 1.6 }}>
            Copy your API key from the popup (Settings → API Keys), then paste it here.{" "}
            <span style={{ color: c.blue, fontWeight: 500 }}>Popup is open ↗</span>
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder="api_key_..."
              onKeyDown={e => e.key === "Enter" && save()}
              style={{
                flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8,
                border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none",
                fontFamily: "var(--font-geist-mono, monospace)",
              }}
              onFocus={e => (e.target.style.borderColor = c.blue)}
              onBlur={e => (e.target.style.borderColor = c.border)}
            />
            <button
              onClick={save}
              disabled={saving || !value.trim()}
              style={{
                padding: "0 16px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: saving || !value.trim() ? "not-allowed" : "pointer",
                opacity: saving || !value.trim() ? 0.6 : 1,
              }}
            >
              {saving ? "…" : "Save"}
            </button>
          </div>
          {(localError || error) && <p style={{ fontSize: 12, color: c.red, margin: 0 }}>{localError || error}</p>}
        </div>
      )}
    </div>
  );
}

// ── ComposioAppCard ────────────────────────────────────────────────────────

function ComposioAppCard({
  app, oauthUrl, founderId, initialConnected,
}: {
  app: typeof COMPOSIO_APPS[number];
  oauthUrl: string;
  founderId: string;
  initialConnected: boolean;
}) {
  const [isConnected, setIsConnected] = useState(initialConnected);
  const [popupOpen, setPopupOpen] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => { setIsConnected(initialConnected); }, [initialConnected]);

  const isError = !oauthUrl || oauthUrl.startsWith("error:");

  const openOAuth = () => {
    if (isError) return;
    const popup = window.open(oauthUrl, `composio_${app.key}`, "width=900,height=660,scrollbars=yes,resizable=yes");
    if (!popup) { window.open(oauthUrl, "_blank"); return; }
    popupRef.current = popup;
    setPopupOpen(true);

    pollRef.current = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollRef.current!);
        setPopupOpen(false);
        apiFetch(`${BASE}/setup/composio/connected/${founderId}`)
          .then(r => r.json())
          .then(data => { if (data.apps?.[app.key]) setIsConnected(true); })
          .catch(() => {});
        return;
      }
      apiFetch(`${BASE}/setup/composio/connected/${founderId}`)
        .then(r => r.json())
        .then(data => {
          if (data.apps?.[app.key]) {
            setIsConnected(true);
            popup.close();
            clearInterval(pollRef.current!);
            setPopupOpen(false);
          }
        })
        .catch(() => {});
    }, 2500);
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  return (
    <div style={{ ...cardStyle(isConnected, popupOpen && !isConnected), opacity: isError ? 0.45 : 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey={app.key} label={app.label} size={24} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>{app.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
            {popupOpen && !isConnected && <span style={{ fontSize: 11, color: c.blue, fontWeight: 500 }}>Authorizing…</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>{isError ? "Requires Composio API key" : app.desc}</span>
        </div>
        <button
          onClick={openOAuth}
          disabled={isError || popupOpen}
          style={{
            padding: "5px 14px", borderRadius: 8, fontSize: 12, flexShrink: 0, fontWeight: 500,
            background: isConnected ? c.greenTint : c.bg,
            border: `1px solid ${isConnected ? c.greenBorder : c.border}`,
            color: isConnected ? c.green : isError ? c.textMuted : c.textSecondary,
            cursor: isError || popupOpen ? "not-allowed" : "pointer",
          }}
        >
          {popupOpen ? "Waiting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>
    </div>
  );
}

function ComposioAppGrid({ founderId, composioUrls }: { founderId: string; composioUrls: Record<string, string> }) {
  const [connected, setConnected] = useState<Record<string, boolean>>({});

  useEffect(() => {
    apiFetch(`${BASE}/setup/composio/connected/${founderId}`)
      .then(r => r.json())
      .then(data => setConnected(data.apps ?? {}))
      .catch(() => {});
  }, [founderId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {COMPOSIO_APPS.map(app => (
        <ComposioAppCard
          key={app.key}
          app={app}
          oauthUrl={composioUrls[app.key] ?? ""}
          founderId={founderId}
          initialConnected={connected[app.key] === true}
        />
      ))}
    </div>
  );
}

// ── Section label ──────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "#9CA3AF", marginBottom: 10, fontWeight: 600, margin: "0 0 10px" }}>
      {children}
    </p>
  );
}

// ── TwilioGuideCard ────────────────────────────────────────────────────────

function TwilioGuideCard({ connected }: { connected: boolean }) {
  const [open, setOpen] = useState(false);
  const steps = [
    "Go to twilio.com/try-twilio and sign up (free trial includes $15 credit)",
    "Verify your phone number when prompted",
    "In Console → Account Info, copy Account SID and Auth Token",
    "Get a free number: Console → Phone Numbers → Manage → Buy a Number",
    "Paste Account SID and Auth Token in the fields below",
  ];
  const [sid, setSid] = useState("");
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  return (
    <div style={cardStyle(connected || saved, open)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: (connected || saved) ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey="twilio" label="Twilio" size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Twilio</span>
            <StatusDot connected={connected || saved} />
            {(connected || saved) && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>SMS reminders for local service bookings (~$0.008/SMS)</span>
        </div>
        <button
          onClick={() => setOpen(v => !v)}
          style={{
            padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
            background: (connected || saved) ? c.greenTint : c.bg,
            border: `1px solid ${(connected || saved) ? c.greenBorder : c.border}`,
            color: (connected || saved) ? c.green : c.textSecondary,
            cursor: "pointer",
          }}
        >
          {(connected || saved) ? "Reconnect ↗" : "Setup guide →"}
        </button>
      </div>
      {open && (
        <div style={{ borderTop: `1px solid ${c.border}`, padding: "14px 18px", background: c.surface, display: "flex", flexDirection: "column", gap: 12 }}>
          <p style={{ margin: 0, fontSize: 12, color: c.textSecondary, fontWeight: 600 }}>Requires phone verification — follow these steps:</p>
          <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
            {steps.map((s, i) => (
              <li key={i} style={{ fontSize: 13, color: c.text, lineHeight: 1.5 }}>{s}</li>
            ))}
          </ol>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={sid} onChange={e => setSid(e.target.value)} placeholder="Account SID (ACxxxxxxxx)"
              style={{ flex: 1, minWidth: 180, padding: "8px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none", fontFamily: "var(--font-geist-mono, monospace)" }}
              onFocus={e => (e.target.style.borderColor = c.blue)} onBlur={e => (e.target.style.borderColor = c.border)}
            />
            <input value={token} onChange={e => setToken(e.target.value)} placeholder="Auth Token"
              style={{ flex: 1, minWidth: 180, padding: "8px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none", fontFamily: "var(--font-geist-mono, monospace)" }}
              onFocus={e => (e.target.style.borderColor = c.blue)} onBlur={e => (e.target.style.borderColor = c.border)}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <a href="https://www.twilio.com/try-twilio" target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 13, color: c.blue, textDecoration: "none" }}>twilio.com/try-twilio ↗</a>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function SetupPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const email = "";

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
  const coreConnected: Partial<Record<(typeof SERVICES)[number]["key"], boolean>> = {
    github: !!status?.github,
    vercel: !!status?.vercel,
    sendgrid: !!status?.sendgrid,
  };
  const ecommConnected: Partial<Record<(typeof ECOMM_SERVICES)[number]["key"], boolean>> = {
    klaviyo: !!status?.klaviyo,
    printful: !!status?.printful,
    lemonsqueezy: !!status?.lemonsqueezy,
    square: !!status?.square,
    yelp: !!status?.yelp,
  };

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
    if (!founderId) return;
    queueMicrotask(() => {
      loadStatus();
      loadComposioUrls();
    });
  }, [founderId, loadStatus, loadComposioUrls]);

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
      const r = await apiFetch(`${BASE}/setup`, {
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
  const progressPct = status ? (connectedCount / totalServices) * 100 : 0;

  return (
    <>
      <PageHeader
        title="Integrations"
        subtitle="Connect services once — agents use them everywhere"
        stats={status ? [{ label: "Connected", value: `${connectedCount} / ${totalServices}` }] : undefined}
      />
      <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 32, padding: "24px 22px 48px", fontFamily: "var(--font-geist-sans)" }}>

      {/* Core services */}
      <div>
        <SectionLabel>Core services</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={coreConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      {/* Stripe */}
      <div>
        <SectionLabel>Payments</SectionLabel>
        <StripeCard founderId={founderId} email={email} />
      </div>

      {/* Composio */}
      <div>
        <SectionLabel>Composio — Gmail · LinkedIn · Calendar · Notion · Linear</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <ComposioKeyCard
            connected={!!composioUrls && Object.keys(composioUrls).length > 0}
            saving={savingComposio}
            error={composioError}
            onSave={async (key) => {
              setSavingComposio(true);
              setComposioError(null);
              try {
                await saveServiceCredential(founderId, "composio", { api_key: key });
                setComposioKey("");
                await loadComposioUrls();
              } catch (e) {
                setComposioError(e instanceof Error ? e.message : "Save failed");
              } finally {
                setSavingComposio(false);
              }
            }}
          />

          {composioError && <p style={{ fontSize: 12, color: c.red, margin: "0 0 4px 0" }}>{composioError}</p>}

          {composioUrls && Object.keys(composioUrls).length > 0 && (
            <ComposioAppGrid founderId={founderId} composioUrls={composioUrls} />
          )}

          {!composioUrls && !loadingUrls && (
            <button
              onClick={loadComposioUrls}
              style={{
                alignSelf: "flex-start", padding: "7px 16px", borderRadius: 8, fontSize: 13,
                background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer", fontWeight: 500,
              }}
            >
              Load OAuth links →
            </button>
          )}
        </div>
      </div>

      {/* Ecomm & Local Service */}
      <div>
        <SectionLabel>Ecomm &amp; Local Service</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {ECOMM_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={ecommConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
          {/* Twilio — guide only (phone verify required) */}
          <TwilioGuideCard connected={!!status?.twilio} />
        </div>
      </div>

      {/* Social — manual */}
      <div>
        <SectionLabel>Social accounts — manual OAuth</SectionLabel>
        <div style={{
          borderRadius: 12, border: `1px solid ${c.border}`,
          background: c.bg, boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
          padding: "14px 18px", display: "flex", gap: 10, flexWrap: "wrap",
        }}>
          {[
            { key: "instagram", label: "Instagram", icon: "◎", connected: status?.instagram },
            { key: "tiktok", label: "TikTok", icon: "◆", connected: status?.tiktok },
            { key: "meta_ads", label: "Meta Ads", icon: "✦", connected: status?.meta_ads },
          ].map(svc => (
            <div key={svc.key} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "8px 14px",
              borderRadius: 8, background: c.surface, border: `1px solid ${c.border}`,
            }}>
              <ServiceLogo serviceKey={svc.key} label={svc.label} size={18} />
              <span style={{ fontSize: 13, color: c.text, fontWeight: 500 }}>{svc.label}</span>
              <StatusDot connected={!!svc.connected} />
              <span style={{ fontSize: 11, color: c.textMuted }}>
                {svc.connected ? "Connected" : "Requires phone verify"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Auto-provision (advanced) */}
      <div>
        <button
          onClick={() => setShowAutoProvision(v => !v)}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 6, marginBottom: showAutoProvision ? 12 : 0 }}
        >
          <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 600 }}>
            Auto-provision (advanced) {showAutoProvision ? "▾" : "▸"}
          </span>
        </button>

        {showAutoProvision && (
          <div style={{
            borderRadius: 12, border: `1px solid ${c.border}`,
            background: c.bg, boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
            padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14,
          }}>
            <p style={{ fontSize: 13, color: c.grey, margin: 0, lineHeight: 1.6 }}>
              Astra can auto-create GitHub, Vercel, SendGrid, and Composio accounts using Playwright.
              Provide the email/password for a <strong style={{ color: c.text }}>new dedicated</strong> account — not your personal one.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <input
                value={autoEmail}
                onChange={e => setAutoEmail(e.target.value)}
                placeholder="email@example.com"
                type="email"
                style={{ padding: "9px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none" }}
                onFocus={e => (e.target.style.borderColor = c.blue)}
                onBlur={e => (e.target.style.borderColor = c.border)}
              />
              <input
                value={autoPassword}
                onChange={e => setAutoPassword(e.target.value)}
                placeholder="Strong password"
                type="password"
                style={{ padding: "9px 12px", fontSize: 13, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, outline: "none" }}
                onFocus={e => (e.target.style.borderColor = c.blue)}
                onBlur={e => (e.target.style.borderColor = c.border)}
              />
            </div>
            <button
              onClick={runAutoProvision}
              disabled={autoProvisioning || !autoEmail.trim() || !autoPassword.trim()}
              style={{
                alignSelf: "flex-start", padding: "8px 20px", borderRadius: 8, fontSize: 13, fontWeight: 500,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: autoProvisioning || !autoEmail.trim() || !autoPassword.trim() ? "not-allowed" : "pointer",
                opacity: autoProvisioning || !autoEmail.trim() || !autoPassword.trim() ? 0.6 : 1,
              }}
            >
              {autoProvisioning ? "Provisioning… (2–5 min)" : "Auto-provision →"}
            </button>
            {autoResult && (
              <div style={{ borderRadius: 8, background: c.surface, border: `1px solid ${c.border}`, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 5 }}>
                {autoResult.map((line, i) => (
                  <p key={i} style={{ margin: 0, fontSize: 13, color: line.startsWith("✓") ? c.green : line.startsWith("✗") ? c.red : c.text, lineHeight: 1.5 }}>
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
        <Link
          href="/"
          style={{
            fontSize: 13, padding: "8px 20px", borderRadius: 8,
            background: c.blue, color: "#FFFFFF", textDecoration: "none", fontWeight: 500,
            display: "inline-block",
          }}
        >
          Back to app →
        </Link>
      </div>
      </div>
    </>
  );
}

