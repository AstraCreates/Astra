"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
    icon: "✉️",
    desc: "Send email campaigns",
    placeholder: "SG.xxxxxxxxxxxxxxxx",
    createUrl: "https://app.sendgrid.com/settings/api_keys",
    createLabel: "app.sendgrid.com/settings/api_keys",
    steps: 3,
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
      background: "rgba(0,0,0,0.85)", backdropFilter: "blur(12px)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        width: "100%", maxWidth: 960, maxHeight: "calc(100vh - 48px)",
        background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)",
        border: "1px solid var(--line)", borderRadius: 24,
        boxShadow: "var(--shadow-lg)", overflow: "hidden", display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 16 }}>{icon}</span>
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>Connecting {label}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>
              {stepNum > 0 ? `Step ${stepNum}/${stepCount} — ${stepName}` : stepName}
            </span>
            {phase !== "done" && (
              <button onClick={() => { wsRef.current?.close(); onClose(); }}
                className="site-btn site-btn-ghost" style={{ fontSize: 11, padding: "0 12px", minHeight: 28 }}>
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ height: 3, background: "var(--line-2)" }}>
          <div style={{
            height: "100%", borderRadius: 999, transition: "width 0.6s",
            width: `${phase === "done" ? 100 : stepPercent}%`,
            background: phase === "done" ? "linear-gradient(90deg,#4ade80,#22d3ee)" : "linear-gradient(90deg,#60a5fa,#a78bfa)",
          }} />
        </div>

        {/* Browser canvas */}
        <div style={{ position: "relative", background: "#0a0a0a", flex: "1 1 auto", overflow: "auto", minHeight: 280 }}>
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
              outline: isUserControl ? "2px solid rgba(96,165,250,0.4)" : "none",
            }}
          />

          {/* Lock overlay when bot is running */}
          {isLocked && phase !== "done" && phase !== "error" && phase !== "connecting" && (
            <div style={{ position: "absolute", inset: 0, cursor: "not-allowed", zIndex: 10 }} />
          )}

          {/* User control banner */}
          {isUserControl && (
            <div style={{
              position: "absolute", top: 10, left: "50%", transform: "translateX(-50%)",
              padding: "8px 18px", borderRadius: 20, zIndex: 20,
              background: "rgba(96,165,250,0.15)", border: "1px solid rgba(96,165,250,0.4)",
              display: "flex", alignItems: "center", gap: 8,
              backdropFilter: "blur(8px)",
            }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#60a5fa", flexShrink: 0 }} className="animate-pulse" />
              <span style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", whiteSpace: "nowrap" }}>
                {message || "Sign in — click and type directly in the browser"}
              </span>
            </div>
          )}

          {phase === "connecting" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 }}>
              <div style={{ width: 28, height: 28, border: "3px solid rgba(255,255,255,0.15)", borderTopColor: "#60a5fa", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
              <span style={{ fontSize: 13, color: "rgba(255,255,255,0.5)" }}>Connecting…</span>
            </div>
          )}

          {(phase === "running" || phase === "bot_filling") && (
            <div style={{ position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)", padding: "8px 20px", borderRadius: 20, background: "rgba(0,0,0,0.7)", border: "1px solid rgba(255,255,255,0.1)", display: "flex", alignItems: "center", gap: 8, zIndex: 20, whiteSpace: "nowrap" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#60a5fa", animation: "spin 0.8s linear infinite" }} />
              <span style={{ fontSize: 12, color: "rgba(255,255,255,0.7)" }}>{stepName || "Working…"}</span>
            </div>
          )}

          {phase === "done" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20, background: "rgba(0,0,0,0.6)" }}>
              <div style={{ padding: "24px 36px", borderRadius: 24, background: "rgba(0,0,0,0.8)", border: "1px solid rgba(74,222,128,0.3)", textAlign: "center" }}>
                <div style={{ fontSize: 36, marginBottom: 10 }}>✓</div>
                <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#4ade80" }}>{label} Connected!</p>
                <button onClick={onClose} className="site-btn site-btn-primary" style={{ marginTop: 14, padding: "0 24px", fontSize: 13 }}>Done</button>
              </div>
            </div>
          )}

          {phase === "error" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20, background: "rgba(0,0,0,0.6)" }}>
              <div style={{ padding: "20px 28px", borderRadius: 20, background: "rgba(0,0,0,0.8)", border: "1px solid rgba(248,113,113,0.3)", textAlign: "center", maxWidth: 400 }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>⚠</div>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#f87171" }}>Connection failed</p>
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "rgba(255,255,255,0.5)" }}>{message}</p>
                <button onClick={onClose} className="site-btn" style={{ marginTop: 12, fontSize: 12, padding: "0 16px", color: "#f87171", background: "rgba(248,113,113,0.1)", borderColor: "rgba(248,113,113,0.2)" }}>Close</button>
              </div>
            </div>
          )}
        </div>

        {/* Interaction form */}
        {phase === "interaction_needed" && fields.length > 0 && (
          <div style={{ padding: "16px 20px", borderTop: "1px solid var(--line-2)", display: "flex", flexDirection: "column", gap: 12 }}>
            {message && <p style={{ margin: 0, fontSize: 12, color: "var(--fg-dim)" }}>{message}</p>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
              {fields.filter(f => f.type !== "disclaimer").map(f => (
                <div key={f.name} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <label style={{ fontSize: 11, color: "var(--fg-mute)" }}>{f.label}{f.required && " *"}</label>
                  {f.type === "select" && f.options ? (
                    <select
                      value={formValues[f.name] ?? f.default ?? ""}
                      onChange={e => setFormValues(v => ({ ...v, [f.name]: e.target.value }))}
                      className="site-input"
                      style={{ padding: "7px 10px", fontSize: 12 }}
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
                      className="site-input"
                      style={{ padding: "7px 10px", fontSize: 12 }}
                    />
                  )}
                </div>
              ))}
            </div>
            {fields.find(f => f.type === "disclaimer") && (
              <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", fontStyle: "italic" }}>
                {fields.find(f => f.type === "disclaimer")!.label}
              </p>
            )}
            {formError && <p style={{ margin: 0, fontSize: 11, color: "#f87171" }}>{formError}</p>}
            <button onClick={submitInput} disabled={submitting} className="site-btn site-btn-primary"
              style={{ alignSelf: "flex-start", padding: "0 20px", fontSize: 13 }}>
              {submitting ? "…" : "Continue →"}
            </button>
          </div>
        )}
      </div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

function glass(extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: "var(--glass)",
    backdropFilter: "var(--blur)",
    WebkitBackdropFilter: "var(--blur)",
    border: "1px solid var(--line)",
    boxShadow: "var(--shadow-sm)",
    borderRadius: 28,
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
  const [popupOpen, setPopupOpen] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // GitHub uses OAuth redirect — detect return from callback
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
      const res = await fetch(`${BASE}/github/oauth-url/${founderId}`);
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
    <div style={{
      ...glass(),
      border: `1px solid ${isConnected ? "rgba(60,170,100,0.28)" : popupOpen ? "rgba(96,165,250,0.35)" : "rgba(255,255,255,0.09)"}`,
      boxShadow: isConnected
        ? "inset 0 1px 0 rgba(255,255,255,0.10), 0 0 20px rgba(60,170,100,0.04)"
        : "inset 0 1px 0 rgba(255,255,255,0.10)",
      overflow: "hidden", transition: "border-color 0.3s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px" }}>
        <span style={{ fontSize: 20, flexShrink: 0 }}>{svc.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{svc.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
            {popupOpen && !isConnected && <span style={{ fontSize: 10, color: "#60a5fa", fontFamily: "var(--font-mono)" }}>popup open</span>}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{svc.desc}</span>
        </div>
        <button
          onClick={isGitHub ? connectGitHubOAuth : openPopup}
          disabled={connecting}
          style={{
            padding: "5px 14px", borderRadius: 24, fontSize: 12, flexShrink: 0,
            background: isConnected ? "rgba(60,170,100,0.10)" : "rgba(255,255,255,0.07)",
            border: `1px solid ${isConnected ? "rgba(60,170,100,0.2)" : "rgba(255,255,255,0.12)"}`,
            color: isConnected ? "#6DC98A" : "var(--fg-dim)",
            cursor: connecting ? "wait" : "pointer", transition: "all 0.12s",
          }}
        >
          {connecting ? "Redirecting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>

      {/* OAuth error — shown for GitHub when redirect fails */}
      {isGitHub && error && (
        <div style={{ borderTop: "1px solid rgba(248,113,113,0.15)", padding: "10px 18px", background: "rgba(248,113,113,0.05)" }}>
          <p style={{ margin: 0, fontSize: 11, color: "#f87171" }}>{error}</p>
        </div>
      )}

      {/* Popup + paste panel — only for non-GitHub services */}
      {!isGitHub && popupOpen && (
        <div style={{
          borderTop: "1px solid rgba(96,165,250,0.15)",
          padding: "12px 18px", background: "rgba(96,165,250,0.04)",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>
            Create a token in the popup, then paste it here.{" "}
            <span style={{ color: "#60a5fa" }}>The popup is open ↗</span>
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={svc.placeholder}
              onKeyDown={e => e.key === "Enter" && save()}
              className="site-input"
              style={{ flex: 1, padding: "8px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
            <button onClick={save} disabled={saving || !value.trim()}
              className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 12, flexShrink: 0 }}>
              {saving ? "…" : "Save"}
            </button>
          </div>
          {error && <p style={{ fontSize: 11, color: "#C97070", margin: 0 }}>{error}</p>}
        </div>
      )}
    </div>
  );
}

function StripeCard({ founderId, email }: { founderId: string; email: string }) {
  const [stripeStatus, setStripeStatus] = useState<{ connected: boolean; charges_enabled?: boolean; email?: string; livemode?: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    fetch(`${BASE}/stripe/status/${founderId}`)
      .then(r => r.json())
      .then(setStripeStatus)
      .catch(() => setStripeStatus({ connected: false }))
      .finally(() => setLoading(false));
  }, [founderId]);

  // Handle return from Stripe OAuth
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("stripe_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      fetch(`${BASE}/stripe/status/${founderId}`).then(r => r.json()).then(setStripeStatus);
    }
  }, [founderId]);

  const connect = async () => {
    setConnecting(true);
    try {
      const res = await fetch(`${BASE}/stripe/oauth-url/${founderId}?email=${encodeURIComponent(email)}`);
      const data = await res.json();
      if (data.url) window.location.href = data.url;
    } finally {
      setConnecting(false);
    }
  };

  const isConnected = stripeStatus?.connected;

  return (
    <div style={{
      ...glass(),
      border: `1px solid ${isConnected ? "rgba(60,170,100,0.28)" : "rgba(255,255,255,0.09)"}`,
      boxShadow: isConnected ? "inset 0 1px 0 rgba(255,255,255,0.10), 0 0 20px rgba(60,170,100,0.04)" : "inset 0 1px 0 rgba(255,255,255,0.10)",
      overflow: "hidden", transition: "border-color 0.3s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px" }}>
        <span style={{ fontSize: 18, fontFamily: "var(--font-mono)", fontWeight: 700, flexShrink: 0, color: "var(--fg)" }}>$</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Stripe</span>
            {!loading && <StatusDot connected={!!isConnected} />}
            {isConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
            {isConnected && stripeStatus?.livemode === false && (
              <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>test mode</span>
            )}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>
            {isConnected ? stripeStatus?.email ?? "Account linked" : "Accept payments, track revenue"}
          </span>
        </div>
        {loading ? (
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>…</span>
        ) : isConnected ? (
          <Link href="/payments" className="site-btn site-btn-ghost" style={{ padding: "5px 14px", fontSize: 12, flexShrink: 0 }}>
            View dashboard →
          </Link>
        ) : (
          <button onClick={connect} disabled={connecting} style={{ padding: "5px 14px", borderRadius: 24, fontSize: 12, background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.10)", color: "var(--fg-dim)", cursor: "pointer", flexShrink: 0 }}>
            {connecting ? "Redirecting…" : "Connect →"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Composio API key card — popup + paste ────────────────────────────────────

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
    <div style={{
      ...glass(),
      border: `1px solid ${connected ? "rgba(60,170,100,0.28)" : popupOpen ? "rgba(96,165,250,0.35)" : "rgba(255,255,255,0.09)"}`,
      boxShadow: connected
        ? "inset 0 1px 0 rgba(255,255,255,0.10), 0 0 20px rgba(60,170,100,0.04)"
        : "inset 0 1px 0 rgba(255,255,255,0.10)",
      overflow: "hidden", transition: "border-color 0.3s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px" }}>
        <span style={{ fontSize: 20, flexShrink: 0 }}>🔗</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Composio</span>
            <StatusDot connected={connected} />
            {connected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
            {popupOpen && !connected && <span style={{ fontSize: 10, color: "#60a5fa", fontFamily: "var(--font-mono)" }}>popup open</span>}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Enables Gmail, LinkedIn, Notion, Linear, Calendar</span>
        </div>
        <button
          onClick={openPopup}
          style={{
            padding: "5px 14px", borderRadius: 24, fontSize: 12, flexShrink: 0,
            background: connected ? "rgba(60,170,100,0.10)" : "rgba(255,255,255,0.07)",
            border: `1px solid ${connected ? "rgba(60,170,100,0.2)" : "rgba(255,255,255,0.12)"}`,
            color: connected ? "#6DC98A" : "var(--fg-dim)",
            cursor: "pointer", transition: "all 0.12s",
          }}
        >
          {connected ? "Update key ↗" : "Connect ↗"}
        </button>
      </div>

      {popupOpen && (
        <div style={{
          borderTop: "1px solid rgba(96,165,250,0.15)",
          padding: "12px 18px", background: "rgba(96,165,250,0.04)",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>
            Copy your API key from the popup (Settings → API Keys), then paste it here.{" "}
            <span style={{ color: "#60a5fa" }}>Popup is open ↗</span>
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              ref={inputRef}
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder="api_key_..."
              onKeyDown={e => e.key === "Enter" && save()}
              className="site-input"
              style={{ flex: 1, padding: "8px 12px", fontSize: 12, fontFamily: "var(--font-mono)" }}
            />
            <button onClick={save} disabled={saving || !value.trim()}
              className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 12, flexShrink: 0 }}>
              {saving ? "…" : "Save"}
            </button>
          </div>
          {(localError || error) && <p style={{ fontSize: 11, color: "#C97070", margin: 0 }}>{localError || error}</p>}
        </div>
      )}
    </div>
  );
}

// ── Composio app card (one per app, same style as ServiceCard) ───────────────

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

  // Sync if parent refreshes initial status
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
        // Final check after popup closes
        fetch(`${BASE}/setup/composio/connected/${founderId}`)
          .then(r => r.json())
          .then(data => { if (data.apps?.[app.key]) setIsConnected(true); })
          .catch(() => {});
        return;
      }
      fetch(`${BASE}/setup/composio/connected/${founderId}`)
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
    <div style={{
      ...glass(),
      border: `1px solid ${isConnected ? "rgba(60,170,100,0.28)" : popupOpen ? "rgba(96,165,250,0.35)" : "rgba(255,255,255,0.09)"}`,
      boxShadow: isConnected
        ? "inset 0 1px 0 rgba(255,255,255,0.10), 0 0 20px rgba(60,170,100,0.04)"
        : "inset 0 1px 0 rgba(255,255,255,0.10)",
      overflow: "hidden", transition: "border-color 0.3s",
      opacity: isError ? 0.45 : 1,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px" }}>
        <span style={{ fontSize: 20, flexShrink: 0 }}>{app.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{app.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 10, color: "#6DC98A", fontFamily: "var(--font-mono)" }}>connected</span>}
            {popupOpen && !isConnected && <span style={{ fontSize: 10, color: "#60a5fa", fontFamily: "var(--font-mono)" }}>authorizing…</span>}
          </div>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{isError ? "requires Composio API key" : app.desc}</span>
        </div>
        <button
          onClick={openOAuth}
          disabled={isError || popupOpen}
          style={{
            padding: "5px 14px", borderRadius: 24, fontSize: 12, flexShrink: 0,
            background: isConnected ? "rgba(60,170,100,0.10)" : isError ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.07)",
            border: `1px solid ${isConnected ? "rgba(60,170,100,0.2)" : "rgba(255,255,255,0.12)"}`,
            color: isConnected ? "#6DC98A" : isError ? "var(--fg-mute)" : "var(--fg-dim)",
            cursor: isError || popupOpen ? "not-allowed" : "pointer",
            transition: "all 0.12s",
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
    fetch(`${BASE}/setup/composio/connected/${founderId}`)
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

export default function SetupPage() {
  const { user, isLoaded } = useUser();
  const founderId = user?.id ?? "founder_001";
  const email = user?.primaryEmailAddress?.emailAddress ?? "";

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
    queueMicrotask(() => {
      loadStatus();
      loadComposioUrls();
    });
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
    <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24, padding: "0 0 40px" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <Link href="/" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>
            ← Back
          </Link>
          <Link href="/brain" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>
            Company brain
          </Link>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>
              Integrations
            </h1>
            <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>
              Connect services once — agents use them everywhere
            </p>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {status && (
            <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-mute)" }}>
              {connectedCount}/{totalServices} connected
            </span>
          )}
          <div style={{ height: 4, width: 120, borderRadius: 999, background: "var(--line-2)", overflow: "hidden" }}>
            <div style={{
              height: "100%", borderRadius: 999,
              width: status ? `${(connectedCount / totalServices) * 100}%` : "0%",
              background: "linear-gradient(90deg,var(--text),var(--text-2))",
              transition: "width 0.6s",
            }} />
          </div>
        </div>
      </div>

      {/* Founder ID chip */}
      {isLoaded && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 14px", borderRadius: 24, background: "var(--glass-lo)", border: "1px solid var(--line)", width: "fit-content" }}>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Founder ID</span>
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>{founderId}</span>
        </div>
      )}

      {/* Core services */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
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

      {/* Stripe */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Payments
        </p>
        <StripeCard founderId={founderId} email={email} />
      </div>

      {/* Composio OAuth */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Composio — Gmail · LinkedIn · Calendar · Notion · Linear
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>

          {/* Composio API key — popup + paste, same as GitHub/Vercel */}
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

          {composioError && <p style={{ fontSize: 11, color: "#C97070", margin: "0 0 4px 0" }}>{composioError}</p>}

          {/* Per-app OAuth cards */}
          {composioUrls && Object.keys(composioUrls).length > 0 && (
            <ComposioAppGrid founderId={founderId} composioUrls={composioUrls} />
          )}

          {!composioUrls && !loadingUrls && (
            <button onClick={loadComposioUrls} className="site-btn site-btn-ghost"
              style={{ alignSelf: "flex-start", padding: "0 16px", fontSize: 12 }}>
              Load OAuth links →
            </button>
          )}
        </div>
      </div>

      {/* Social — manual */}
      <div>
        <p style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
          Social accounts — manual OAuth
        </p>
        <div style={{ ...glass(), padding: "14px 18px", display: "flex", gap: 12, flexWrap: "wrap" }}>
          {[
            { key: "instagram", label: "Instagram", icon: "📸", connected: status?.instagram },
            { key: "tiktok", label: "TikTok", icon: "🎵", connected: status?.tiktok },
            { key: "meta_ads", label: "Meta Ads", icon: "📢", connected: status?.meta_ads },
          ].map(svc => (
            <div key={svc.key} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 24, background: "var(--glass-lo)", border: "1px solid var(--line)" }}>
              <span>{svc.icon}</span>
              <span style={{ fontSize: 12, color: "var(--fg)" }}>{svc.label}</span>
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
          <span style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>
            Auto-provision (advanced) {showAutoProvision ? "▾" : "▸"}
          </span>
        </button>

        {showAutoProvision && (
          <div style={{ ...glass(), padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: 0, lineHeight: 1.6 }}>
              Astra can auto-create GitHub, Vercel, SendGrid, and Composio accounts using Playwright.
              Provide the email/password for a <strong style={{ color: "var(--fg)" }}>new dedicated</strong> account — not your personal one.
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
              <div style={{ borderRadius: 24, background: "var(--glass-lo)", border: "1px solid var(--line)", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
                {autoResult.map((line, i) => (
                  <p key={i} style={{ margin: 0, fontSize: 12, color: line.startsWith("✓") ? "#6DC98A" : line.startsWith("✗") ? "#C97070" : "var(--fg)", lineHeight: 1.5 }}>
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
        <Link href="/" className="site-btn site-btn-primary" style={{ fontSize: 13, padding: "0 20px" }}>
          Back to app →
        </Link>
      </div>
    </div>
  );
}
