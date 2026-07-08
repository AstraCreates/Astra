"use client";

import { useState, useEffect, useCallback, useRef } from "react";

import ServiceLogo from "@/components/ServiceLogo";
import { useDevUser } from "@/lib/use-dev-user";
import Link from "next/link";
import {
  apiFetch,
  saveServiceCredential,
  getSetupStatus,
  getConnectorCoverage,
  getConnectorSetup,
  getConnectorValidation,
  importCompanyBrainSources,
  SetupStatus,
  ConnectorCoverage,
  ConnectorSetupPlan,
  ConnectorValidationReport,
} from "@/lib/api";


const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Design tokens ─────────────────────────────────────────────────────────────
const c = {
  bg: "var(--bg)",
  surface: "var(--bg-surface)",
  border: "var(--border)",
  borderStrong: "var(--border-strong)",
  text: "var(--text)",
  textSecondary: "var(--text-2)",
  textMuted: "var(--text-3)",
  grey: "var(--text-muted)",
  blue: "#002EFF",
  blueHover: "#1f36e0",
  blueTint: "var(--accent-light)",
  blueBorder: "rgba(47,85,255,0.35)",
  green: "#16a34a",
  greenTint: "rgba(22,163,74,0.10)",
  greenBorder: "rgba(22,163,74,0.30)",
  red: "#dc2626",
  redTint: "rgba(220,38,38,0.10)",
  redBorder: "rgba(220,38,38,0.30)",
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

const WORKSPACE_SERVICES = [
  {
    key: "notion",
    credKey: "token",
    label: "Notion",
    icon: "▷",
    desc: "Update wikis and documents",
    placeholder: "secret_xxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://www.notion.so/profile/integrations",
    createLabel: "notion.so/profile/integrations",
    steps: 2,
    oauthApp: "notion",
  },
  {
    key: "linear",
    credKey: "api_key",
    label: "Linear",
    icon: "◈",
    desc: "Create and track issues",
    placeholder: "lin_api_xxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://linear.app/settings/api",
    createLabel: "linear.app/settings/api",
    steps: 2,
    oauthApp: "linear",
  },
] as const;

const COLLABORATION_SERVICES = [
  {
    key: "slack",
    credKey: "token",
    label: "Slack",
    icon: "◻",
    desc: "Let agents post updates into your team channels",
    placeholder: "",
    createUrl: "https://slack.com/",
    createLabel: "slack.com",
    steps: 1,
    oauthApp: "slack",
  },
  {
    key: "discord",
    credKey: "token",
    label: "Discord",
    icon: "◻",
    desc: "Send Discord messages and status updates",
    placeholder: "",
    createUrl: "https://discord.com/",
    createLabel: "discord.com",
    steps: 1,
    oauthApp: "discord",
  },
  {
    key: "twitter",
    credKey: "token",
    label: "X / Twitter",
    icon: "◻",
    desc: "Publish posts directly from Astra",
    placeholder: "",
    createUrl: "https://x.com/",
    createLabel: "x.com",
    steps: 1,
    oauthApp: "twitter",
  },
  {
    key: "reddit",
    credKey: "token",
    label: "Reddit",
    icon: "◻",
    desc: "Post directly to community threads",
    placeholder: "",
    createUrl: "https://www.reddit.com/",
    createLabel: "reddit.com",
    steps: 1,
    oauthApp: "reddit",
  },
  {
    key: "telegram",
    credKey: "token",
    label: "Telegram",
    icon: "◻",
    desc: "Send Telegram messages and broadcast updates",
    placeholder: "",
    createUrl: "https://telegram.org/",
    createLabel: "telegram.org",
    steps: 1,
    oauthApp: "telegram",
  },
] as const;

const BUSINESS_SERVICES = [
  {
    key: "hubspot",
    credKey: "access_token",
    label: "HubSpot",
    icon: "◔",
    desc: "CRM sync and contact creation",
    placeholder: "",
    createUrl: "https://app.hubspot.com/",
    createLabel: "app.hubspot.com",
    steps: 1,
    oauthApp: "hubspot",
  },
  {
    key: "mailchimp",
    credKey: "api_key",
    label: "Mailchimp",
    icon: "◌",
    desc: "Audience sync and lifecycle campaigns",
    placeholder: "",
    createUrl: "https://mailchimp.com/",
    createLabel: "mailchimp.com",
    steps: 1,
    oauthApp: "mailchimp",
  },
  {
    key: "airtable",
    credKey: "access_token",
    label: "Airtable",
    icon: "▦",
    desc: "Structured records and lightweight ops data",
    placeholder: "",
    createUrl: "https://airtable.com/",
    createLabel: "airtable.com",
    steps: 1,
    oauthApp: "airtable",
  },
  {
    key: "dropbox",
    credKey: "access_token",
    label: "Dropbox",
    icon: "◫",
    desc: "File drop-offs and artifact handoff",
    placeholder: "",
    createUrl: "https://www.dropbox.com/",
    createLabel: "dropbox.com",
    steps: 1,
    oauthApp: "dropbox",
  },
] as const;

const OPS_SERVICES = [
  {
    key: "jira",
    credKey: "token",
    label: "Jira",
    icon: "◻",
    desc: "Create and track engineering issues",
    placeholder: "",
    createUrl: "https://www.atlassian.com/software/jira",
    createLabel: "atlassian.com/jira",
    steps: 1,
    oauthApp: "jira",
  },
  {
    key: "trello",
    credKey: "token",
    label: "Trello",
    icon: "◻",
    desc: "Create task cards and keep lightweight boards updated",
    placeholder: "",
    createUrl: "https://trello.com/",
    createLabel: "trello.com",
    steps: 1,
    oauthApp: "trello",
  },
  {
    key: "asana",
    credKey: "token",
    label: "Asana",
    icon: "◻",
    desc: "Create and manage work across project plans",
    placeholder: "",
    createUrl: "https://asana.com/",
    createLabel: "asana.com",
    steps: 1,
    oauthApp: "asana",
  },
  {
    key: "clickup",
    credKey: "token",
    label: "ClickUp",
    icon: "◻",
    desc: "Track tasks and action items in ClickUp",
    placeholder: "",
    createUrl: "https://clickup.com/",
    createLabel: "clickup.com",
    steps: 1,
    oauthApp: "clickup",
  },
  {
    key: "calendly",
    credKey: "token",
    label: "Calendly",
    icon: "◻",
    desc: "Read scheduling activity and booked events",
    placeholder: "",
    createUrl: "https://calendly.com/",
    createLabel: "calendly.com",
    steps: 1,
    oauthApp: "calendly",
  },
  {
    key: "zoom",
    credKey: "token",
    label: "Zoom",
    icon: "◻",
    desc: "Create meetings directly from Astra",
    placeholder: "",
    createUrl: "https://zoom.us/",
    createLabel: "zoom.us",
    steps: 1,
    oauthApp: "zoom",
  },
  {
    key: "youtube",
    credKey: "token",
    label: "YouTube",
    icon: "◻",
    desc: "Connect YouTube for research and publishing workflows",
    placeholder: "",
    createUrl: "https://youtube.com/",
    createLabel: "youtube.com",
    steps: 1,
    oauthApp: "youtube",
  },
  {
    key: "outlook",
    credKey: "token",
    label: "Outlook",
    icon: "◻",
    desc: "Send email via Microsoft 365",
    placeholder: "",
    createUrl: "https://outlook.office.com/",
    createLabel: "outlook.office.com",
    steps: 1,
    oauthApp: "outlook",
  },
] as const;

const MANUAL_SERVICES = [
  {
    key: "resend",
    credKey: "api_key",
    label: "Resend",
    icon: "◻",
    desc: "Transactional email and founder deliverables",
    placeholder: "re_xxxxxxxxxxxxxxxx",
    createUrl: "https://resend.com/api-keys",
    createLabel: "resend.com/api-keys",
    steps: 2,
  },
  {
    key: "figma",
    credKey: "token",
    label: "Figma",
    icon: "◉",
    desc: "Design context, files, and asset inspection",
    placeholder: "figd_xxxxxxxxxxxxxxxx",
    createUrl: "https://www.figma.com/developers/api#access-tokens",
    createLabel: "figma.com/developers/api",
    steps: 2,
  },
] as const;

const STACK_OPTIONS = [
  { key: "idea_to_revenue", label: "Idea to Revenue" },
  { key: "sales", label: "Sales" },
  { key: "marketing", label: "Marketing" },
  { key: "founder_ops", label: "Founder Ops" },
  { key: "support", label: "Support" },
  { key: "product", label: "Product" },
  { key: "ecomm", label: "Ecommerce / Medusa" },
  { key: "local_service", label: "Local Service" },
] as const;

const IMPORTABLE_SOURCES = new Set([
  "github",
  "slack",
  "discord",
  "notion",
  "google_drive",
  "gmail",
  "linear",
  "obsidian",
  "zendesk",
  "confluence",
]);

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

interface StackJourneyDefinition {
  id: string;
  title: string;
  description: string;
  connectors: string[];
}

interface StackJourneyConnectorState {
  connector: ConnectorSetupPlan["connectors"][number];
  coverage?: ConnectorCoverage["connectors"][number];
  status: ReturnType<typeof connectorJourneyStatus>;
}

type JourneyTone = "ready" | "needs_sync" | "connected" | "missing" | "optional";

interface StackJourneyState {
  id: string;
  title: string;
  description: string;
  connectors: StackJourneyConnectorState[];
  tone: JourneyTone;
  summary: string;
  nextStep: string;
}

const STACK_JOURNEYS: Partial<Record<(typeof STACK_OPTIONS)[number]["key"], StackJourneyDefinition[]>> = {
  ecomm: [
    {
      id: "storefront",
      title: "Store launch surface",
      description: "Get code, deploys, and the customer-facing storefront moving together.",
      connectors: ["github", "vercel"],
    },
    {
      id: "revenue_ops",
      title: "Checkout and fulfillment",
      description: "Make it possible to take payment, sell digital offers, and hand orders off cleanly.",
      connectors: ["stripe", "lemonsqueezy", "printful"],
    },
    {
      id: "lifecycle",
      title: "Lifecycle retention",
      description: "Cover transactional email, campaigns, and the post-purchase loop.",
      connectors: ["gmail", "resend", "klaviyo", "mailchimp"],
    },
  ],
  local_service: [
    {
      id: "lead_capture",
      title: "Lead capture and intake",
      description: "Keep inbound demand, contact capture, and CRM sync in one motion.",
      connectors: ["github", "vercel", "hubspot", "yelp"],
    },
    {
      id: "booking_ops",
      title: "Booking and reminders",
      description: "Handle appointments, payments, and reminder workflows without gaps.",
      connectors: ["square", "google_calendar", "twilio"],
    },
    {
      id: "follow_up",
      title: "Follow-up and repeat business",
      description: "Close the loop with email follow-up, nurture, and simple audience ops.",
      connectors: ["gmail", "resend", "mailchimp", "hubspot"],
    },
  ],
};

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
  const phaseRef = useRef<ModalPhase>("connecting");
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

    const updatePhase = (p: ModalPhase) => { phaseRef.current = p; setPhase(p); };
    ws.onopen = () => updatePhase("running");
    ws.onerror = () => { updatePhase("error"); setMessage("WebSocket connection failed."); };
    ws.onclose = () => { if (phaseRef.current !== "done" && phaseRef.current !== "error") updatePhase("error"); };

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
        updatePhase("user_control");
      } else if (msg.type === "status") {
        setStepName(msg.step); setStepNum(msg.step_num);
        updatePhase("running"); setMessage("");
      } else if (msg.type === "interaction_needed") {
        setStepName(msg.step); setMessage(msg.message);
        setFields(msg.fields || []); setFormValues({});
        setFormError(""); updatePhase("interaction_needed");
      } else if (msg.type === "bot_filling") {
        updatePhase("bot_filling"); setMessage("Filling your information…");
      } else if (msg.type === "done") {
        updatePhase("done"); onConnected();
      } else if (msg.type === "error") {
        updatePhase("error"); setMessage(msg.message || "An error occurred.");
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

type AnyService =
  | typeof SERVICES[number]
  | typeof ECOMM_SERVICES[number]
  | typeof WORKSPACE_SERVICES[number]
  | typeof COLLABORATION_SERVICES[number]
  | typeof BUSINESS_SERVICES[number]
  | typeof OPS_SERVICES[number]
  | typeof MANUAL_SERVICES[number];

function ServiceCard({
  svc, connected, founderId, onSaved,
}: {
  svc: AnyService;
  connected: boolean;
  founderId: string;
  onSaved: () => void;
}) {
  const [popupOpen, setPopupOpen] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);
  const oauthApp = "oauthApp" in svc ? svc.oauthApp : undefined;

  useEffect(() => {
    if (svc.key !== "github") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("github_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      setJustConnected(true);
      onSaved();
    } else if (params.get("github_error")) {
      window.history.replaceState({}, "", window.location.pathname);
      setError(`GitHub OAuth failed: ${params.get("github_error")}`);
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

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startOAuthPolling = () => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const res = await apiFetch(`${BASE}/setup/composio/connected/${founderId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (oauthApp && data?.apps?.[oauthApp]) {
          stopPolling();
          setJustConnected(true);
          setPopupOpen(false);
          setShowForm(false);
          setConnecting(false);
          popupRef.current?.close();
          onSaved();
        }
      } catch {
        // Keep polling while the OAuth popup is active.
      }
    }, 2000);
  };

  const openPopup = () => {
    const popup = window.open(svc.createUrl, `connect_${svc.key}`, "width=1060,height=720,scrollbars=yes,resizable=yes");
    popupRef.current = popup;
    setPopupOpen(true);
    setShowForm(true);
    setValue("");
    setError(null);
    setTimeout(() => inputRef.current?.focus(), 300);
  };

  useEffect(() => {
    if (!popupOpen) return;
    const interval = setInterval(() => {
      if (popupRef.current?.closed) {
        clearInterval(interval);
        stopPolling();
        setPopupOpen(false);
        setConnecting(false);
      }
    }, 600);
    return () => clearInterval(interval);
  }, [popupOpen]);

  useEffect(() => () => stopPolling(), []);

  const openOAuthPopup = async () => {
    if (!oauthApp) return;
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch(`${BASE}/setup/composio/connect/${founderId}?apps=${encodeURIComponent(oauthApp)}`);
      const data = await res.json();
      const oauthUrl = data?.oauth_urls?.[oauthApp];
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`);
        setConnecting(false);
        return;
      }
      if (!oauthUrl) {
        setError(`No OAuth URL returned for ${svc.label}`);
        setConnecting(false);
        return;
      }
      const popup = window.open(oauthUrl, `connect_${svc.key}`, "width=1060,height=720,scrollbars=yes,resizable=yes");
      if (!popup) {
        setError("Popup blocked by browser");
        setConnecting(false);
        return;
      }
      popupRef.current = popup;
      setPopupOpen(true);
      startOAuthPolling();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach server");
      setConnecting(false);
    }
  };

  async function save() {
    if (!value.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, svc.key, { [svc.credKey]: value.trim() });
      setJustConnected(true);
      setPopupOpen(false);
      setShowForm(false);
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
  const isOAuthApp = !!oauthApp;

  return (
    <div style={cardStyle(isConnected, showForm && !isConnected)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey={svc.key} label={svc.label} size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>{svc.label}</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
            {popupOpen && !isConnected && (
              <span style={{ fontSize: 11, color: c.blue, fontWeight: 500 }}>
                {isOAuthApp ? "Authorizing…" : "Popup open"}
              </span>
            )}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>{svc.desc}</span>
        </div>
        <button
          onClick={isGitHub ? connectGitHubOAuth : isOAuthApp ? openOAuthPopup : openPopup}
          disabled={connecting}
          className="m-tap"
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

      {isOAuthApp && popupOpen && !isConnected && (
        <div style={{
          borderTop: `1px solid ${c.blueBorder}`,
          padding: "14px 18px", background: c.blueTint,
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <p style={{ margin: 0, fontSize: 13, color: c.textSecondary, lineHeight: 1.6 }}>
            Finish the OAuth flow in the popup. Astra will mark this connected automatically as soon as the provider returns.
          </p>
          {error && <p style={{ fontSize: 12, color: c.red, margin: 0 }}>{error}</p>}
        </div>
      )}

      {!isGitHub && !isOAuthApp && showForm && (
        <div style={{
          borderTop: `1px solid ${c.blueBorder}`,
          padding: "14px 18px", background: c.blueTint,
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <p style={{ margin: 0, fontSize: 13, color: c.textSecondary, lineHeight: 1.6 }}>
              {popupOpen ? <>Create a token in the popup, then paste it here.{" "}<span style={{ color: c.blue, fontWeight: 500 }}>The popup is open ↗</span></> : "Paste your token below."}
            </p>
            <button onClick={() => setShowForm(false)} style={{ fontSize: 12, color: c.grey, background: "none", border: "none", cursor: "pointer", padding: "0 4px" }}>✕</button>
          </div>
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

// ── GmailDirectCard ────────────────────────────────────────────────────────

function GmailDirectCard({ founderId, onSaved, gmailConnected }: { founderId: string; onSaved: () => void; gmailConnected: boolean }) {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      setJustConnected(true);
      onSaved();
    }
    if (params.get("gmail_error")) {
      window.history.replaceState({}, "", window.location.pathname);
      setError(`Gmail connection failed: ${params.get("gmail_error")}`);
    }
  }, [onSaved]);

  const connect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch(`${BASE}/gmail/oauth-url/${founderId}`);
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? `Error ${res.status}`); setConnecting(false); return; }
      if (data.url) window.location.href = data.url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach server");
      setConnecting(false);
    }
  };

  const isConnected = gmailConnected || justConnected;

  return (
    <div style={cardStyle(isConnected, false)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey="gmail" label="Gmail" size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Gmail (direct send)</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>Required for agents to actually send emails from your inbox</span>
        </div>
        <button onClick={connect} disabled={connecting} className="m-tap" style={{
          padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
          background: isConnected ? c.greenTint : c.bg,
          border: `1px solid ${isConnected ? c.greenBorder : c.border}`,
          color: isConnected ? c.green : c.textSecondary,
          cursor: connecting ? "wait" : "pointer",
        }}>
          {connecting ? "Redirecting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>
      {error && <div style={{ borderTop: `1px solid ${c.redBorder}`, padding: "10px 18px", background: c.redTint }}>
        <p style={{ margin: 0, fontSize: 12, color: c.red }}>{error}</p>
      </div>}
    </div>
  );
}

function GoogleWorkspaceDirectCard({ founderId, onSaved, workspaceConnected }: { founderId: string; onSaved: () => void; workspaceConnected: boolean }) {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("google_workspace_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      setJustConnected(true);
      onSaved();
    }
    if (params.get("google_workspace_error")) {
      window.history.replaceState({}, "", window.location.pathname);
      setError(`Google Workspace connection failed: ${params.get("google_workspace_error")}`);
    }
  }, [onSaved]);

  const connect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch(`${BASE}/google-workspace/oauth-url/${founderId}`);
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? `Error ${res.status}`); setConnecting(false); return; }
      if (data.url) window.location.href = data.url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach server");
      setConnecting(false);
    }
  };

  const isConnected = workspaceConnected || justConnected;

  return (
    <div style={cardStyle(isConnected, false)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey="google_workspace" label="Google Workspace" size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>Google Workspace</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>Direct OAuth for Docs, Sheets, Slides, Drive, and Calendar actions</span>
        </div>
        <button onClick={connect} disabled={connecting} className="m-tap" style={{
          padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
          background: isConnected ? c.greenTint : c.bg,
          border: `1px solid ${isConnected ? c.greenBorder : c.border}`,
          color: isConnected ? c.green : c.textSecondary,
          cursor: connecting ? "wait" : "pointer",
        }}>
          {connecting ? "Redirecting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>
      {error && <div style={{ borderTop: `1px solid ${c.redBorder}`, padding: "10px 18px", background: c.redTint }}>
        <p style={{ margin: 0, fontSize: 12, color: c.red }}>{error}</p>
      </div>}
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
            className="m-tap"
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

// ── LinkedInCard ───────────────────────────────────────────────────────────

function LinkedInCard({ founderId, onSaved, linkedinConnected }: { founderId: string; onSaved: () => void; linkedinConnected: boolean }) {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("linkedin_connected") === "1") {
      window.history.replaceState({}, "", window.location.pathname);
      setJustConnected(true);
      onSaved();
    }
    if (params.get("linkedin_error")) {
      window.history.replaceState({}, "", window.location.pathname);
      setError(`LinkedIn connection failed: ${params.get("linkedin_error")}`);
    }
  }, [onSaved]);

  const connect = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await apiFetch(`${BASE}/linkedin/oauth-url/${founderId}`);
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? `Error ${res.status}`);
        setConnecting(false);
        return;
      }
      if (data.url) window.location.href = data.url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reach server");
      setConnecting(false);
    }
  };

  const isConnected = linkedinConnected || justConnected;

  return (
    <div style={cardStyle(isConnected, false)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", background: isConnected ? c.greenTint : c.bg }}>
        <ServiceLogo serviceKey="linkedin" label="LinkedIn" size={26} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>LinkedIn</span>
            <StatusDot connected={isConnected} />
            {isConnected && <span style={{ fontSize: 11, color: c.green, fontWeight: 500 }}>Connected</span>}
          </div>
          <span style={{ fontSize: 12, color: c.grey }}>Post thought leadership content from your account</span>
        </div>
        <button onClick={connect} disabled={connecting} className="m-tap" style={{
          padding: "6px 14px", borderRadius: 8, fontSize: 13, flexShrink: 0, fontWeight: 500,
          background: isConnected ? c.greenTint : c.bg,
          border: `1px solid ${isConnected ? c.greenBorder : c.border}`,
          color: isConnected ? c.green : c.textSecondary,
          cursor: connecting ? "wait" : "pointer",
        }}>
          {connecting ? "Redirecting…" : isConnected ? "Reconnect ↗" : "Connect ↗"}
        </button>
      </div>
      {error && <div style={{ borderTop: `1px solid ${c.redBorder}`, padding: "10px 18px", background: c.redTint }}>
        <p style={{ margin: 0, fontSize: 12, color: c.red }}>{error}</p>
      </div>}
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

function fieldPlaceholder(label: string, key: string) {
  const lower = key.toLowerCase();
  if (lower.includes("token")) return "Paste token";
  if (lower.includes("api_key") || lower === "api_key") return "Paste API key";
  if (lower.includes("access_token")) return "Paste access token";
  if (lower.includes("email")) return "name@company.com";
  if (lower.includes("url")) return "https://...";
  if (lower.includes("subdomain")) return "company";
  if (lower.includes("location_id")) return "Optional location ID";
  if (lower.includes("vault_path")) return "/Users/you/Obsidian/Vault";
  return label;
}

function stackImportSources(
  connector: ConnectorSetupPlan["connectors"][number],
  coverageConnector?: ConnectorCoverage["connectors"][number],
): string[] {
  const matched = (coverageConnector?.brain_sources ?? [])
    .map((source) => source.key)
    .filter((key) => IMPORTABLE_SOURCES.has(key));
  if (matched.length) return Array.from(new Set(matched));

  if (IMPORTABLE_SOURCES.has(connector.key)) return [connector.key];
  if (connector.key === "google_sheets" || connector.key === "google_docs" || connector.key === "google_slides" || connector.key === "google_workspace") return ["google_drive"];
  if (connector.key === "email_marketing") return ["gmail"];
  return [];
}

function connectorJourneyStatus(
  connector: ConnectorSetupPlan["connectors"][number],
  coverageConnector?: ConnectorCoverage["connectors"][number],
) {
  const coverageStatus = coverageConnector?.coverage_status ?? connector.sync.coverage_status;
  if (connector.setup_status === "ready" || coverageStatus === "ready") {
    return { tone: "ready" as const, label: "Ready" };
  }
  if (connector.setup_status === "connected_needs_sync" || coverageStatus === "connected_no_memory") {
    return { tone: "needs_sync" as const, label: "Needs sync" };
  }
  if (connector.connected) {
    return { tone: "connected" as const, label: "Connected" };
  }
  if (connector.required) {
    return { tone: "missing" as const, label: "Needs connection" };
  }
  return { tone: "optional" as const, label: "Optional" };
}

function journeyToneStyles(tone: JourneyTone) {
  switch (tone) {
    case "ready":
      return { color: c.green, background: c.greenTint, border: c.greenBorder };
    case "needs_sync":
      return { color: c.amber, background: "rgba(217,119,6,0.10)", border: "rgba(217,119,6,0.30)" };
    case "connected":
      return { color: c.blue, background: c.blueTint, border: c.blueBorder };
    case "missing":
      return { color: c.red, background: c.redTint, border: c.redBorder };
    default:
      return { color: c.textMuted, background: c.surface, border: c.border };
  }
}

// ── TwilioGuideCard ────────────────────────────────────────────────────────

function TwilioGuideCard({ connected, founderId, onSaved }: { connected: boolean; founderId: string; onSaved: () => void }) {
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
  const [error, setError] = useState<string | null>(null);

  async function saveTwilio() {
    if (!sid.trim() || !token.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, "twilio", { account_sid: sid.trim(), auth_token: token.trim() });
      setSaved(true);
      setSid("");
      setToken("");
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

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
          className="m-tap"
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
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button
              onClick={saveTwilio}
              disabled={saving || !sid.trim() || !token.trim()}
              style={{
                padding: "7px 18px", borderRadius: 8, fontSize: 13, fontWeight: 500,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: saving || !sid.trim() || !token.trim() ? "not-allowed" : "pointer",
                opacity: saving || !sid.trim() || !token.trim() ? 0.6 : 1,
              }}
            >
              {saving ? "Saving…" : "Save credentials →"}
            </button>
            <a href="https://www.twilio.com/try-twilio" target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 13, color: c.blue, textDecoration: "none" }}>twilio.com/try-twilio ↗</a>
          </div>
          {error && <p style={{ margin: 0, fontSize: 12, color: c.red }}>{error}</p>}
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
  const [autoProvisioning, setAutoProvisioning] = useState(false);
  const [autoEmail, setAutoEmail] = useState("");
  const [autoPassword, setAutoPassword] = useState("");
  const [autoResult, setAutoResult] = useState<string[] | null>(null);
  const [showAutoProvision, setShowAutoProvision] = useState(false);
  const [selectedStackId, setSelectedStackId] = useState<string>("ecomm");
  const [stackSetup, setStackSetup] = useState<ConnectorSetupPlan | null>(null);
  const [stackCoverage, setStackCoverage] = useState<ConnectorCoverage | null>(null);
  const [stackLoading, setStackLoading] = useState(false);
  const [stackError, setStackError] = useState<string | null>(null);
  const [importingKey, setImportingKey] = useState<string | null>(null);
  const [editingConnectorKey, setEditingConnectorKey] = useState<string | null>(null);
  const [connectorDrafts, setConnectorDrafts] = useState<Record<string, Record<string, string>>>({});
  const [connectorSavingKey, setConnectorSavingKey] = useState<string | null>(null);
  const [connectorSaveError, setConnectorSaveError] = useState<string | null>(null);
  const [validationReport, setValidationReport] = useState<ConnectorValidationReport | null>(null);
  const [validatingKey, setValidatingKey] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
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
  const workspaceConnected: Partial<Record<(typeof WORKSPACE_SERVICES)[number]["key"], boolean>> = {
    notion: !!status?.notion || !!status?.apps?.["notion"],
    linear: !!status?.linear || !!status?.apps?.["linear"],
  };
  const collaborationConnected: Partial<Record<(typeof COLLABORATION_SERVICES)[number]["key"], boolean>> = {
    slack: !!status?.slack || !!status?.apps?.["slack"],
    discord: !!status?.discord || !!status?.apps?.["discord"],
    twitter: !!status?.apps?.["twitter"],
    reddit: !!status?.apps?.["reddit"],
    telegram: !!status?.apps?.["telegram"],
  };
  const businessConnected: Partial<Record<(typeof BUSINESS_SERVICES)[number]["key"], boolean>> = {
    hubspot: !!status?.hubspot || !!status?.apps?.["hubspot"],
    mailchimp: !!status?.mailchimp || !!status?.apps?.["mailchimp"],
    airtable: !!status?.airtable || !!status?.apps?.["airtable"],
    dropbox: !!status?.dropbox || !!status?.apps?.["dropbox"],
  };
  const opsConnected: Partial<Record<(typeof OPS_SERVICES)[number]["key"], boolean>> = {
    jira: !!status?.apps?.["jira"],
    trello: !!status?.apps?.["trello"],
    asana: !!status?.apps?.["asana"],
    clickup: !!status?.apps?.["clickup"],
    calendly: !!status?.apps?.["calendly"],
    zoom: !!status?.apps?.["zoom"],
    youtube: !!status?.apps?.["youtube"],
    outlook: !!status?.apps?.["outlook"],
  };
  const manualConnected: Partial<Record<(typeof MANUAL_SERVICES)[number]["key"], boolean>> = {
    resend: !!status?.resend,
    figma: !!status?.figma,
  };

  const loadStatus = useCallback(async () => {
    try {
      const s = await getSetupStatus(founderId);
      setStatus(s);
    } catch { /* no creds yet */ }
  }, [founderId]);

  const loadStackData = useCallback(async () => {
    if (!founderId || !selectedStackId) return;
    setStackLoading(true);
    setStackError(null);
    try {
      const [setup, coverage] = await Promise.all([
        getConnectorSetup(founderId, selectedStackId),
        getConnectorCoverage(founderId, selectedStackId),
      ]);
      setStackSetup(setup);
      setStackCoverage(coverage);
      setValidationReport(null);
    } catch (e) {
      setStackError(e instanceof Error ? e.message : "Failed to load stack connector data");
    } finally {
      setStackLoading(false);
    }
  }, [founderId, selectedStackId]);

  useEffect(() => {
    if (!founderId) return;
    queueMicrotask(() => { loadStatus(); });
  }, [founderId, loadStatus]);

  useEffect(() => {
    if (!founderId) return;
    queueMicrotask(() => { loadStackData(); });
  }, [founderId, loadStackData]);

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
    } catch (e) {
      setAutoResult([e instanceof Error ? e.message : "Failed"]);
    } finally {
      setAutoProvisioning(false);
    }
  }

  async function importConnectorContext(connector: ConnectorSetupPlan["connectors"][number]) {
    const coverageConnector = stackCoverage?.connectors.find((item) => item.key === connector.key);
    const sources = stackImportSources(connector, coverageConnector);
    if (!sources.length) return;
    setImportingKey(connector.key);
    try {
      await importCompanyBrainSources(founderId, sources, 20);
      await loadStackData();
    } finally {
      setImportingKey(null);
    }
  }

  async function validateConnectorLive(connectorKey?: string) {
    if (!founderId || !selectedStackId) return;
    setValidatingKey(connectorKey || "__all__");
    setValidationError(null);
    try {
      const report = await getConnectorValidation(founderId, selectedStackId, true);
      setValidationReport(report);
    } catch (e) {
      setValidationError(e instanceof Error ? e.message : "Failed to validate connector");
    } finally {
      setValidatingKey(null);
    }
  }

  async function saveStackConnector(connector: ConnectorSetupPlan["connectors"][number]) {
    const draft = connectorDrafts[connector.key] || {};
    const payload = Object.fromEntries(
      connector.fields
        .map((field) => [field.key, (draft[field.key] ?? "").trim()])
        .filter(([_, value]) => value),
    );
    if (!Object.keys(payload).length) {
      setConnectorSaveError("Enter at least one credential value.");
      return;
    }
    setConnectorSavingKey(connector.key);
    setConnectorSaveError(null);
    try {
      await saveServiceCredential(founderId, connector.credential_service, payload);
      setEditingConnectorKey(null);
      setConnectorDrafts((current) => ({ ...current, [connector.key]: {} }));
      await Promise.all([loadStatus(), loadStackData()]);
    } catch (e) {
      setConnectorSaveError(e instanceof Error ? e.message : "Failed to save credentials");
    } finally {
      setConnectorSavingKey(null);
    }
  }

  const SERVICE_KEYS: (keyof SetupStatus)[] = [
    "github", "vercel", "sendgrid", "supabase",
    "stripe", "resend",
    "instagram", "tiktok", "meta_ads",
    "linkedin", "notion", "linear", "slack", "discord",
    "google_workspace", "google_drive", "google_sheets", "google_docs", "google_slides", "google_calendar",
    "hubspot", "mailchimp", "airtable", "dropbox", "figma", "obsidian", "zendesk", "confluence",
    "klaviyo", "printful", "lemonsqueezy", "square", "yelp", "twilio",
  ];
  const connectedCount = status ? SERVICE_KEYS.filter(k => status[k]).length : 0;
  const totalServices = SERVICE_KEYS.length;
  const connectorSetupMap = new Map(stackSetup?.connectors.map((connector) => [connector.key, connector]) ?? []);
  const connectorCoverageMap = new Map(stackCoverage?.connectors.map((connector) => [connector.key, connector]) ?? []);
  const selectedStackJourneyDefs = STACK_JOURNEYS[selectedStackId as keyof typeof STACK_JOURNEYS] ?? [];
  const stackJourneys: StackJourneyState[] = selectedStackJourneyDefs
    .map((journey: StackJourneyDefinition) => {
      const connectors = journey.connectors
        .map((key: string): StackJourneyConnectorState | null => {
          const connector = connectorSetupMap.get(key);
          if (!connector) return null;
          return {
            connector,
            coverage: connectorCoverageMap.get(key),
            status: connectorJourneyStatus(connector, connectorCoverageMap.get(key)),
          };
        })
        .filter((item: StackJourneyConnectorState | null): item is StackJourneyConnectorState => !!item);

      if (!connectors.length) return null;

      const readyCount = connectors.filter((item: StackJourneyConnectorState) => item.status.tone === "ready").length;
      const needsSyncCount = connectors.filter((item: StackJourneyConnectorState) => item.status.tone === "needs_sync").length;
      const missingCount = connectors.filter((item: StackJourneyConnectorState) => item.status.tone === "missing").length;
      const connectedCountForJourney = connectors.filter((item: StackJourneyConnectorState) => item.status.tone === "connected").length;
      const tone: JourneyTone =
        missingCount > 0 ? "missing" :
        needsSyncCount > 0 ? "needs_sync" :
        readyCount === connectors.length ? "ready" :
        connectedCountForJourney > 0 ? "connected" :
        "optional";

      const nextConnector =
        connectors.find((item: StackJourneyConnectorState) => item.status.tone === "missing") ??
        connectors.find((item: StackJourneyConnectorState) => item.status.tone === "needs_sync") ??
        connectors.find((item: StackJourneyConnectorState) => item.status.tone === "connected");

      const summary =
        missingCount > 0
          ? `${missingCount} connector${missingCount === 1 ? "" : "s"} still need setup`
          : needsSyncCount > 0
            ? `${needsSyncCount} connector${needsSyncCount === 1 ? "" : "s"} still need Company Brain sync`
            : readyCount === connectors.length
              ? "This bundle is covered"
              : `${connectedCountForJourney} connector${connectedCountForJourney === 1 ? "" : "s"} connected and waiting for the rest`;

      return {
        ...journey,
        connectors,
        tone,
        summary,
        nextStep: nextConnector
          ? nextConnector.status.tone === "missing"
            ? `Connect ${nextConnector.connector.label} next.`
            : nextConnector.status.tone === "needs_sync"
              ? `Import ${nextConnector.connector.label} into Company Brain next.`
              : `Validate ${nextConnector.connector.label} once the rest are in place.`
          : "No action needed.",
      };
    })
    .filter((journey: StackJourneyState | null): journey is StackJourneyState => !!journey);

  return (
    <>
      <div style={{ padding: "22px 24px 16px", flexShrink: 0, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-0.01em" }}>Integrations</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-3)" }}>Connect services once — agents use them everywhere</p>
        </div>
        {status && (
          <span style={{ fontSize: 12, color: "var(--text-3)", alignSelf: "center" }}>{connectedCount} / {totalServices} connected</span>
        )}
      </div>
      <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 32, padding: "24px 22px 48px", fontFamily: "var(--font-geist-sans)" }}>

      <div>
        <SectionLabel>Stack-aware setup</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, border: `1px solid ${c.border}`, borderRadius: 12, background: c.bg, boxShadow: "0 1px 3px rgba(0,0,0,0.08)", padding: 18 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {STACK_OPTIONS.map((stack) => {
              const active = stack.key === selectedStackId;
              return (
                <button
                  key={stack.key}
                  onClick={() => setSelectedStackId(stack.key)}
                  style={{
                    padding: "7px 12px",
                    borderRadius: 999,
                    border: `1px solid ${active ? c.blueBorder : c.border}`,
                    background: active ? c.blueTint : c.surface,
                    color: active ? c.blue : c.textSecondary,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  {stack.label}
                </button>
              );
            })}
          </div>

          {stackError ? (
            <p style={{ margin: 0, fontSize: 12, color: c.red }}>{stackError}</p>
          ) : stackLoading || !stackSetup || !stackCoverage ? (
            <p style={{ margin: 0, fontSize: 12, color: c.textMuted }}>Loading stack connector guidance…</p>
          ) : (
            <>
              <p style={{ margin: 0, fontSize: 12, color: c.textSecondary, lineHeight: 1.6 }}>{stackCoverage.summary}</p>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={() => void validateConnectorLive()}
                  disabled={validatingKey === "__all__"}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: `1px solid ${c.border}`,
                    background: c.bg,
                    color: c.textSecondary,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: validatingKey === "__all__" ? "wait" : "pointer",
                  }}
                >
                  {validatingKey === "__all__" ? "Running live checks…" : "Run live validation"}
                </button>
                {validationReport && (
                  <span style={{ fontSize: 12, color: validationReport.ready ? c.green : c.amber }}>
                    {validationReport.summary}
                  </span>
                )}
                {validationError && (
                  <span style={{ fontSize: 12, color: c.red }}>{validationError}</span>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {stackSetup.connectors.map((connector) => {
                  const coverageConnector = stackCoverage.connectors.find((item) => item.key === connector.key);
                  const liveValidation = validationReport?.connectors.find((item) => item.key === connector.key);
                  const importSources = stackImportSources(connector, coverageConnector);
                  const coverageStatus = coverageConnector?.coverage_status ?? connector.sync.coverage_status;
                  const needsSync = connector.setup_status === "connected_needs_sync" || coverageStatus === "connected_no_memory";
                  const isEditing = editingConnectorKey === connector.key;
                  const validation = liveValidation || connector.validation;
                  return (
                    <div key={connector.key} style={{ border: `1px solid ${c.border}`, borderRadius: 10, padding: 14, background: c.surface }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <ServiceLogo serviceKey={connector.key} label={connector.label} size={18} />
                            <span style={{ fontSize: 14, color: c.text, fontWeight: 600 }}>{connector.label}</span>
                            {connector.required && <span style={{ fontSize: 11, color: c.red, fontWeight: 600 }}>Required</span>}
                            <span style={{ fontSize: 11, color: needsSync ? c.amber : connector.connected ? c.green : c.textMuted }}>
                              {needsSync ? "Needs sync" : connector.connected ? "Connected" : "Not connected"}
                            </span>
                          </div>
                          <p style={{ margin: "6px 0 0", fontSize: 12, color: c.textSecondary, lineHeight: 1.5 }}>{connector.purpose}</p>
                          <p style={{ margin: "6px 0 0", fontSize: 11, color: c.textMuted }}>
                            {connector.missing_fields.length
                              ? `Missing fields: ${connector.missing_fields.join(", ")}`
                              : `Credential service: ${connector.credential_service}`}
                            {connector.sync.brain_record_count ? ` · Brain records: ${connector.sync.brain_record_count}` : ""}
                          </p>
                          {connector.setup_hint && (
                            <p style={{ margin: "6px 0 0", fontSize: 11, color: c.textMuted, lineHeight: 1.5 }}>
                              {connector.setup_hint}
                            </p>
                          )}
                          {validation?.provider?.status === "error" && validation.provider.detail && (
                            <p style={{ margin: "6px 0 0", fontSize: 11, color: c.red, lineHeight: 1.5 }}>
                              Validation issue: {validation.provider.detail}
                            </p>
                          )}
                          {validation?.provider?.status === "ok" && (
                            <p style={{ margin: "6px 0 0", fontSize: 11, color: c.green, lineHeight: 1.5 }}>
                              Live validation passed{validation.provider.http_status ? ` (HTTP ${validation.provider.http_status})` : ""}.
                            </p>
                          )}
                          {validation?.provider?.status === "not_checked" && (
                            <p style={{ margin: "6px 0 0", fontSize: 11, color: c.amber, lineHeight: 1.5 }}>
                              Live validation has not run yet for this connector.
                            </p>
                          )}
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                          {(connector.missing_fields.length > 0 || connector.setup_status === "missing_credentials") && (
                            <button
                              onClick={() => {
                                setEditingConnectorKey((current) => current === connector.key ? null : connector.key);
                                setConnectorSaveError(null);
                              }}
                              style={{
                                padding: "7px 12px",
                                borderRadius: 8,
                                border: `1px solid ${c.border}`,
                                background: c.bg,
                                color: c.textSecondary,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                              }}
                            >
                              {isEditing ? "Close form" : "Add credentials"}
                            </button>
                          )}
                          {connector.setup_url && (
                            <a
                              href={connector.setup_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                padding: "7px 12px",
                                borderRadius: 8,
                                border: `1px solid ${c.border}`,
                                background: c.bg,
                                color: c.textSecondary,
                                fontSize: 12,
                                fontWeight: 600,
                                textDecoration: "none",
                              }}
                            >
                              Open setup
                            </a>
                          )}
                          {importSources.length > 0 && (
                            <button
                              onClick={() => void importConnectorContext(connector)}
                              disabled={importingKey === connector.key}
                              style={{
                                padding: "7px 12px",
                                borderRadius: 8,
                                border: `1px solid ${c.border}`,
                                background: c.bg,
                                color: c.textSecondary,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: importingKey === connector.key ? "wait" : "pointer",
                              }}
                            >
                              {importingKey === connector.key ? "Importing…" : "Import context"}
                            </button>
                          )}
                        </div>
                      </div>
                      {isEditing && (
                        <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${c.border}` }}>
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
                            {connector.fields.map((field) => (
                              <div key={field.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                <label style={{ fontSize: 11, color: c.textMuted, fontWeight: 600 }}>
                                  {field.label}{field.required ? " *" : ""}
                                </label>
                                <input
                                  type={field.secret ? "password" : "text"}
                                  value={connectorDrafts[connector.key]?.[field.key] ?? ""}
                                  placeholder={fieldPlaceholder(field.label, field.key)}
                                  onChange={(event) => setConnectorDrafts((current) => ({
                                    ...current,
                                    [connector.key]: {
                                      ...(current[connector.key] || {}),
                                      [field.key]: event.target.value,
                                    },
                                  }))}
                                  style={{
                                    padding: "8px 12px",
                                    fontSize: 13,
                                    borderRadius: 8,
                                    border: `1px solid ${c.border}`,
                                    background: c.bg,
                                    color: c.text,
                                    outline: "none",
                                  }}
                                />
                              </div>
                            ))}
                          </div>
                          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
                            <button
                              onClick={() => void saveStackConnector(connector)}
                              disabled={connectorSavingKey === connector.key}
                              style={{
                                padding: "8px 14px",
                                borderRadius: 8,
                                border: "none",
                                background: c.blue,
                                color: "#fff",
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: connectorSavingKey === connector.key ? "wait" : "pointer",
                              }}
                            >
                              {connectorSavingKey === connector.key ? "Saving…" : "Save credentials"}
                            </button>
                            <span style={{ fontSize: 11, color: c.textMuted }}>
                              Saved to `"{connector.credential_service}"` for this founder.
                            </span>
                          </div>
                          {connectorSaveError && (
                            <p style={{ margin: "8px 0 0", fontSize: 11, color: c.red }}>{connectorSaveError}</p>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {stackSetup.next_actions.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {stackSetup.next_actions.slice(0, 4).map((action) => (
                    <div key={action} style={{ fontSize: 12, color: c.textSecondary }}>{action}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

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

      {/* Gmail */}
      <div>
        <SectionLabel>Email</SectionLabel>
        <GmailDirectCard founderId={founderId} onSaved={loadStatus} gmailConnected={!!status?.apps?.["gmail_direct"]} />
      </div>

      {/* Workspace tools */}
      <div>
        <SectionLabel>Workspace tools</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <GoogleWorkspaceDirectCard founderId={founderId} onSaved={loadStatus} workspaceConnected={!!status?.google_workspace} />
          <LinkedInCard founderId={founderId} onSaved={loadStatus} linkedinConnected={!!status?.linkedin} />
          {WORKSPACE_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={workspaceConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Collaboration & Social</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {COLLABORATION_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={collaborationConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>CRM & File Tools</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {BUSINESS_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={businessConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Ops & Meetings</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {OPS_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={opsConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Advanced Manual Credentials</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {MANUAL_SERVICES.map(svc => (
            <ServiceCard
              key={svc.key}
              svc={svc}
              connected={manualConnected[svc.key] ?? false}
              founderId={founderId}
              onSaved={loadStatus}
            />
          ))}
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
          {/* Twilio — SID + Auth Token */}
          <TwilioGuideCard connected={!!status?.twilio} founderId={founderId} onSaved={loadStatus} />
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

      <div>
        <SectionLabel>Ops, docs & support visibility</SectionLabel>
        <div style={{
          borderRadius: 12, border: `1px solid ${c.border}`,
          background: c.bg, boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
          padding: "14px 18px", display: "flex", gap: 10, flexWrap: "wrap",
        }}>
          {[
            { key: "slack", label: "Slack", connected: status?.slack },
            { key: "discord", label: "Discord", connected: status?.discord },
            { key: "google_workspace", label: "Google Workspace", connected: status?.google_workspace || status?.apps?.["google_workspace"] },
            { key: "google_drive", label: "Google Drive", connected: status?.google_drive || status?.apps?.["google_drive"] },
            { key: "google_sheets", label: "Google Sheets", connected: status?.google_sheets || status?.apps?.["google_sheets"] },
            { key: "google_docs", label: "Google Docs", connected: status?.google_docs || status?.apps?.["google_docs"] },
            { key: "google_slides", label: "Google Slides", connected: status?.google_slides || status?.apps?.["google_slides"] },
            { key: "google_calendar", label: "Google Calendar", connected: status?.google_calendar || status?.apps?.["google_calendar"] },
            { key: "obsidian", label: "Obsidian", connected: status?.obsidian },
            { key: "zendesk", label: "Zendesk", connected: status?.zendesk },
            { key: "confluence", label: "Confluence", connected: status?.confluence },
          ].map(svc => (
            <div key={svc.key} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "8px 14px",
              borderRadius: 8, background: c.surface, border: `1px solid ${c.border}`,
            }}>
              <ServiceLogo serviceKey={svc.key} label={svc.label} size={18} />
              <span style={{ fontSize: 13, color: c.text, fontWeight: 500 }}>{svc.label}</span>
              <StatusDot connected={!!svc.connected} />
              <span style={{ fontSize: 11, color: c.textMuted }}>
                {svc.connected ? "Connected" : "Not connected"}
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
          href="/dashboard"
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
