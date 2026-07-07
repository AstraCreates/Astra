"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch } from "@/lib/api";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts";
import PageHeader, { HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── MOCKUP: set true temporarily to preview connected Stripe UI ───────────────
const MOCKUP = false;
const MOCK_STATUS: StripeStatus = { connected: true, charges_enabled: true, payouts_enabled: true, email: "jhinkesh05@gmail.com", livemode: false, upgraded_to_business: false };
const MOCK_DATA: StripeData = {
  balance: { available: 184200, pending: 29900, currency: "usd" },
  mrr: 124700,
  total_revenue: 381400,
  currency: "usd",
  charges: [
    { id: "ch_1", amount: 4900, currency: "usd", status: "succeeded", description: "NearBy Pro Plan", customer_email: "alex@example.com", created: Math.floor(Date.now() / 1000) - 3600 },
    { id: "ch_2", amount: 4900, currency: "usd", status: "succeeded", description: "NearBy Pro Plan", customer_email: "priya@example.com", created: Math.floor(Date.now() / 1000) - 86400 },
    { id: "ch_3", amount: 9900, currency: "usd", status: "succeeded", description: "NearBy Business Plan", customer_email: "marcus@example.com", created: Math.floor(Date.now() / 1000) - 172800 },
    { id: "ch_4", amount: 4900, currency: "usd", status: "succeeded", description: "NearBy Pro Plan", customer_email: "sara@example.com", created: Math.floor(Date.now() / 1000) - 259200 },
    { id: "ch_5", amount: 4900, currency: "usd", status: "pending", description: "NearBy Pro Plan", customer_email: "dan@example.com", created: Math.floor(Date.now() / 1000) - 300 },
    { id: "ch_6", amount: 9900, currency: "usd", status: "succeeded", description: "NearBy Business Plan", customer_email: "lin@example.com", created: Math.floor(Date.now() / 1000) - 432000 },
    { id: "ch_7", amount: 4900, currency: "usd", status: "failed", description: "NearBy Pro Plan", customer_email: "tom@example.com", created: Math.floor(Date.now() / 1000) - 518400 },
  ],
  payouts: [
    { id: "po_1", amount: 89200, currency: "usd", status: "paid", arrival_date: Math.floor(Date.now() / 1000) - 604800, created: Math.floor(Date.now() / 1000) - 691200 },
    { id: "po_2", amount: 62400, currency: "usd", status: "in_transit", arrival_date: Math.floor(Date.now() / 1000) + 172800, created: Math.floor(Date.now() / 1000) - 86400 },
  ],
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface StripeStatus {
  connected: boolean;
  charges_enabled: boolean;
  payouts_enabled: boolean;
  email?: string;
  livemode?: boolean;
  upgraded_to_business?: boolean;
}

interface StripeData {
  balance: { available: number; pending: number; currency: string };
  charges: Charge[];
  payouts: Payout[];
  mrr: number;
  total_revenue: number;
  currency: string;
}

interface Charge {
  id: string; amount: number; currency: string;
  status: "succeeded" | "pending" | "failed";
  description: string | null; customer_email: string | null; created: number;
}

interface Payout {
  id: string; amount: number; currency: string;
  status: string; arrival_date: number; created: number;
}

interface StripePrice {
  price_id: string; amount: number; currency: string;
  interval: string | null; payment_link: string | null;
}

interface StripeProduct {
  product_id: string; name: string; description: string;
  created: number; prices: StripePrice[];
}

interface WebhookEvent {
  id: string; type: string; alert: string; created: number;
  data: Record<string, unknown>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(amount: number, currency = "usd") {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: currency.toUpperCase(), minimumFractionDigits: 2,
  }).format(amount / 100);
}

function fmtShort(amount: number) {
  if (amount >= 100000) return `$${(amount / 100000).toFixed(1)}k`;
  return `$${(amount / 100).toFixed(0)}`;
}

function fmtDate(ts: number, short = false) {
  return new Date(ts * 1000).toLocaleDateString("en-US", short
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" });
}

function statusColor(s: string) {
  if (s === "succeeded" || s === "paid") return "#16a34a";
  if (s === "pending" || s === "in_transit") return "#d97706";
  return "#dc2626";
}

// ── Chart data builders ───────────────────────────────────────────────────────

function buildRevenueByDay(charges: Charge[]) {
  const map: Record<string, number> = {};
  const succeeded = charges.filter(c => c.status === "succeeded");
  for (const c of succeeded) {
    const day = fmtDate(c.created, true);
    map[day] = (map[day] ?? 0) + c.amount;
  }
  const days: { date: string; revenue: number }[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const label = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    days.push({ date: label, revenue: map[label] ?? 0 });
  }
  return days;
}

function buildStatusBreakdown(charges: Charge[]) {
  const counts: Record<string, number> = {};
  for (const c of charges) {
    counts[c.status] = (counts[c.status] ?? 0) + 1;
  }
  return Object.entries(counts).map(([name, value]) => ({ name, value }));
}

function buildPayoutsByMonth(payouts: Payout[]) {
  const map: Record<string, number> = {};
  for (const p of payouts) {
    const month = new Date(p.created * 1000).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
    map[month] = (map[month] ?? 0) + p.amount;
  }
  return Object.entries(map).map(([month, amount]) => ({ month, amount }));
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent, badge }: {
  label: string; value: string; sub?: string; accent?: string; badge?: string;
}) {
  return (
    <div style={{
      borderRadius: 14,
      border: "1px solid var(--border)",
      background: "var(--bg-surface)",
      boxShadow: "none",
      padding: "20px 24px",
      display: "flex",
      flexDirection: "column",
      gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-3)", fontWeight: 500 }}>{label}</span>
        {badge && (
          <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: "rgba(22,163,74,0.12)", color: "#16a34a", border: "1px solid rgba(22,163,74,0.30)", fontWeight: 500 }}>
            {badge}
          </span>
        )}
      </div>
      <span style={{ fontSize: 26, fontWeight: 600, color: accent ?? "var(--text)", letterSpacing: "-0.02em", fontFamily: "var(--font-geist-sans)" }}>{value}</span>
      {sub && <span style={{ fontSize: 12, color: "var(--text-3)" }}>{sub}</span>}
    </div>
  );
}

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div style={{
      borderRadius: 14,
      border: "1px solid var(--border)",
      background: "var(--bg-surface)",
      boxShadow: "none",
      overflow: "hidden",
    }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--bg-sunken)" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

const CHART_COLORS = ["#002EFF", "#16a34a", "#d97706", "#dc2626", "#7c3aed"];

const tooltipStyle = {
  contentStyle: {
    background: "var(--bg-surface)",
    border: "1px solid var(--border)",
    borderRadius: 10,
    fontSize: 12,
    color: "var(--text)",
    boxShadow: "0 4px 16px rgba(0,0,0,0.30)",
  },
  labelStyle: { color: "var(--text-3)", marginBottom: 4 },
};

// ── Connect screen ────────────────────────────────────────────────────────────

function ConnectStripe({ founderId, email }: { founderId: string; email: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const connect = async () => {
    setLoading(true); setError("");
    try {
      const res = await apiFetch(`${BASE}/stripe/oauth-url/${founderId}?email=${encodeURIComponent(email)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Failed to get OAuth URL");
      window.location.href = data.url;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 360, gap: 24, padding: "48px 24px" }}>
      <div style={{ textAlign: "center", maxWidth: 460 }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14,
          background: "var(--accent-light)", border: "1px solid rgba(47,85,255,0.35)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 24, margin: "0 auto 20px", color: "#002EFF",
        }}>$</div>
        <h2 style={{ fontSize: 18, fontWeight: 600, color: "var(--text)", margin: "0 0 10px", letterSpacing: "-0.02em" }}>Connect your Stripe account</h2>
        <p style={{ fontSize: 13, color: "var(--text-3)", margin: 0, lineHeight: 1.7 }}>
          Click below to connect or create your Stripe account. Astra will securely link it so you can track revenue, balance, and payouts right here.
        </p>
        <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 10, lineHeight: 1.6 }}>
          No EIN required — upgrade to a business account after your LLC is filed.
        </p>
      </div>
      {error && (
        <div style={{ padding: "10px 16px", borderRadius: 10, background: "rgba(220,38,38,0.10)", border: "1px solid rgba(220,38,38,0.30)", fontSize: 12, color: "#dc2626", maxWidth: 420, textAlign: "center" }}>
          {error}
        </div>
      )}
      <button onClick={connect} disabled={loading} className="site-btn site-btn-primary" style={{ minHeight: 44, padding: "0 36px", fontSize: 14, opacity: loading ? 0.7 : 1 }}>
        {loading ? "Redirecting to Stripe…" : "Connect Stripe →"}
      </button>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
        {["Stripe opens — sign in or create a free account", "Authorize Astra to read your data", "You're redirected back here automatically"].map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "var(--text-3)" }}>
            <span style={{
              width: 20, height: 20, borderRadius: "50%",
              background: "var(--accent-light)", border: "1px solid rgba(47,85,255,0.35)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, flexShrink: 0, color: "#002EFF", fontWeight: 600,
            }}>{i + 1}</span>
            {s}
          </div>
        ))}
      </div>
    </div>
  );
}

function ProductsSection({ founderId, currency }: { founderId: string; currency: string }) {
  const [products, setProducts] = useState<StripeProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", description: "", amount: "", interval: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${BASE}/stripe/products/${founderId}`);
      if (res.ok) { const d = await res.json(); setProducts(d.products ?? []); }
    } finally { setLoading(false); }
  }, [founderId]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.name || !form.amount) return;
    setCreating(true);
    try {
      const res = await apiFetch(`${BASE}/stripe/products/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: form.name, description: form.description, amount: Math.round(parseFloat(form.amount) * 100), currency, interval: form.interval }),
      });
      if (res.ok) { setForm({ name: "", description: "", amount: "", interval: "" }); setShowForm(false); await load(); }
    } finally { setCreating(false); }
  };

  const copy = (url: string) => {
    navigator.clipboard.writeText(url);
    setCopied(url);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <SectionCard title={`Products & Payment Links (${products.length})`} action={
      <button
        onClick={() => setShowForm(v => !v)}
        style={{
          fontSize: 12, padding: "4px 12px", borderRadius: 8,
          background: showForm ? "#F3F4F6" : "#002EFF",
          color: showForm ? "#374151" : "#FFFFFF",
          border: showForm ? "1px solid #E5E7EB" : "1px solid #002EFF",
          cursor: "pointer", fontWeight: 500,
        }}
      >
        {showForm ? "Cancel" : "+ New product"}
      </button>
    }>
      {showForm && (
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E7EB", display: "flex", flexDirection: "column", gap: 12, background: "var(--bg-sunken)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {[
              { label: "Product name *", field: "name" as const, placeholder: "Pro Plan", type: "text" },
              { label: "Price (USD) *", field: "amount" as const, placeholder: "29.00", type: "number" },
              { label: "Description", field: "description" as const, placeholder: "Access to all features", type: "text" },
            ].map(({ label, field, placeholder, type }) => (
              <div key={field} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <label style={{ fontSize: 11, color: "var(--text-3)", fontWeight: 500 }}>{label}</label>
                <input
                  value={form[field]}
                  onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
                  placeholder={placeholder}
                  type={type}
                  style={{
                    padding: "8px 12px", fontSize: 13, borderRadius: 8,
                    border: "1px solid var(--border)", background: "var(--bg-surface)",
                    color: "var(--text)", outline: "none",
                  }}
                  onFocus={e => (e.target.style.borderColor = "#002EFF")}
                  onBlur={e => (e.target.style.borderColor = "var(--border)")}
                />
              </div>
            ))}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "var(--text-3)", fontWeight: 500 }}>Billing</label>
              <select
                value={form.interval}
                onChange={e => setForm(f => ({ ...f, interval: e.target.value }))}
                style={{
                  padding: "8px 12px", fontSize: 13, borderRadius: 8,
                  border: "1px solid var(--border)", background: "var(--bg-surface)",
                  color: "var(--text)", outline: "none",
                }}
              >
                <option value="">One-time</option>
                <option value="month">Monthly</option>
                <option value="year">Yearly</option>
              </select>
            </div>
          </div>
          <button
            onClick={create}
            disabled={creating || !form.name || !form.amount}
            style={{
              alignSelf: "flex-start", fontSize: 13, padding: "8px 20px", borderRadius: 8,
              background: "#002EFF", color: "#FFFFFF", border: "none", cursor: "pointer",
              opacity: (creating || !form.name || !form.amount) ? 0.6 : 1, fontWeight: 500,
            }}
          >
            {creating ? "Creating…" : "Create product + payment link →"}
          </button>
        </div>
      )}

      {loading ? (
        <p style={{ padding: "20px", fontSize: 13, color: "var(--text-3)", margin: 0 }}>Loading…</p>
      ) : products.length === 0 ? (
        <p style={{ padding: "20px", fontSize: 13, color: "var(--text-3)", margin: 0 }}>
          No products yet. Create one above — Astra will generate a shareable Stripe payment link instantly.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {products.map((prod, i) => (
            <div key={prod.product_id} style={{ padding: "14px 20px", borderBottom: i < products.length - 1 ? "1px solid #E5E7EB" : "none", display: "flex", alignItems: "flex-start", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{prod.name}</div>
                {prod.description && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{prod.description}</div>}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {prod.prices.map(pr => (
                    <div key={pr.price_id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 8, background: "var(--bg-sunken)", border: "1px solid var(--border)" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{fmt(pr.amount, pr.currency)}</span>
                      {pr.interval && <span style={{ fontSize: 11, color: "var(--text-3)" }}>/ {pr.interval}</span>}
                      {pr.payment_link && (
                        <button
                          onClick={() => copy(pr.payment_link!)}
                          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: copied === pr.payment_link ? "#16a34a" : "#002EFF", padding: "0 4px", fontWeight: 500 }}
                        >
                          {copied === pr.payment_link ? "Copied!" : "Copy link"}
                        </button>
                      )}
                      {pr.payment_link && (
                        <a href={pr.payment_link} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: "var(--text-3)", textDecoration: "none" }}>↗</a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <span style={{ fontSize: 11, color: "var(--text-3)", flexShrink: 0, marginTop: 2 }}>{fmtDate(prod.created)}</span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function AlertsFeed({ founderId }: { founderId: string }) {
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [webhookRegistered, setWebhookRegistered] = useState(false);
  const [registering, setRegistering] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${BASE}/stripe/events/${founderId}`);
      if (res.ok) { const d = await res.json(); setEvents(d.events ?? []); setWebhookRegistered(d.events?.length > 0 || false); }
    } catch { /* silent */ }
  }, [founderId]);

  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  const registerWebhook = async () => {
    setRegistering(true);
    try {
      const res = await apiFetch(`${BASE}/stripe/register-webhook/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: founderId, backend_url: BASE }),
      });
      if (res.ok) setWebhookRegistered(true);
    } finally { setRegistering(false); }
  };

  const alertIcon = (type: string) => {
    if (type.includes("succeeded") || type.includes("paid")) return "✓";
    if (type.includes("failed")) return "✗";
    if (type.includes("subscription.deleted")) return "↩";
    if (type.includes("subscription")) return "↻";
    if (type.includes("refund")) return "↲";
    return "●";
  };

  const alertColor = (type: string) => {
    if (type.includes("succeeded") || type.includes("paid")) return "#16a34a";
    if (type.includes("failed")) return "#dc2626";
    if (type.includes("deleted")) return "#d97706";
    return "#002EFF";
  };

  return (
    <SectionCard title="Payment Alerts" action={
      !webhookRegistered ? (
        <button
          onClick={registerWebhook}
          disabled={registering}
          style={{
            fontSize: 12, padding: "4px 12px", borderRadius: 8,
            background: "var(--bg-surface)", color: "var(--text-2)",
            border: "1px solid var(--border)", cursor: "pointer", fontWeight: 500,
          }}
        >
          {registering ? "Registering…" : "Enable alerts"}
        </button>
      ) : (
        <span style={{ fontSize: 11, color: "#16a34a", fontWeight: 500, display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#16a34a", display: "inline-block" }} />
          Live
        </span>
      )
    }>
      {events.length === 0 ? (
        <div style={{ padding: "20px", display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ fontSize: 13, color: "var(--text-3)", margin: 0 }}>
            {webhookRegistered ? "No events yet — alerts will appear here when payments come in." : "Enable alerts to get notified instantly when payments come in, subscriptions churn, or payouts complete."}
          </p>
          {!webhookRegistered && (
            <p style={{ fontSize: 12, color: "var(--text-3)", margin: 0 }}>
              Note: requires your backend to be publicly accessible (production URL).
            </p>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {events.map((ev, i) => (
            <div key={ev.id || i} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 20px", borderBottom: i < events.length - 1 ? "1px solid #E5E7EB" : "none", background: i % 2 === 1 ? "#F9FAFB" : "#FFFFFF" }}>
              <span style={{ fontSize: 13, color: alertColor(ev.type), flexShrink: 0, marginTop: 1, fontWeight: 600 }}>{alertIcon(ev.type)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: 13, color: "var(--text)" }}>{ev.alert}</p>
                <p style={{ margin: "2px 0 0", fontSize: 11, color: "var(--text-3)" }}>{ev.type}</p>
              </div>
              <span style={{ fontSize: 11, color: "var(--text-3)", flexShrink: 0 }}>{fmtDate(ev.created)}</span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function EINUpgradeSection({ upgraded, businessName }: { upgraded: boolean; businessName?: string }) {
  return (
    <SectionCard title="Business Upgrade · EIN">
      <div style={{ padding: "20px 24px", display: "flex", alignItems: "flex-start", gap: 16 }}>
        <div style={{ flex: 1 }}>
          {upgraded ? (
            <>
              <p style={{ margin: "0 0 4px", fontSize: 13, fontWeight: 600, color: "#16a34a" }}>Upgraded to business account</p>
              <p style={{ margin: 0, fontSize: 13, color: "var(--text-3)", lineHeight: 1.6 }}>Registered under <strong style={{ color: "var(--text)" }}>{businessName ?? "your LLC"}</strong>. Tax reporting now uses your EIN.</p>
            </>
          ) : (
            <>
              <p style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "var(--text)" }}>Upgrade to LLC / Business</p>
              <p style={{ margin: "0 0 10px", fontSize: 13, color: "var(--text-3)", lineHeight: 1.6 }}>Once your LLC is filed via Astra and your EIN arrives from the IRS, you&apos;ll update your Stripe account to your business entity. Switches tax reporting from SSN to EIN.</p>
              <p style={{ margin: 0, fontSize: 12, color: "var(--text-3)" }}><strong style={{ color: "var(--text-2)" }}>Timeline:</strong> File LLC → IRS issues EIN in 1–4 weeks → update Stripe → done.</p>
            </>
          )}
        </div>
        <span style={{
          fontSize: 11, padding: "4px 12px", borderRadius: 999, whiteSpace: "nowrap", flexShrink: 0, fontWeight: 500,
          background: upgraded ? "#DCFCE7" : "#F3F4F6",
          color: upgraded ? "#16a34a" : "#6B7280",
          border: `1px solid ${upgraded ? "#BBF7D0" : "#E5E7EB"}`,
        }}>
          {upgraded ? "Complete" : "Pending LLC"}
        </span>
      </div>
    </SectionCard>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PaymentsPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const email = "";

  const [status, setStatus] = useState<StripeStatus | null>(MOCKUP ? MOCK_STATUS : null);
  const [data, setData] = useState<StripeData | null>(MOCKUP ? MOCK_DATA : null);
  const [loadingStatus, setLoadingStatus] = useState(!MOCKUP);
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    if (MOCKUP) return;
    setLoadingStatus(true);
    try {
      const res = await apiFetch(`${BASE}/stripe/status/${founderId}`);
      setStatus(await res.json());
    } catch {
      setStatus({ connected: false, charges_enabled: false, payouts_enabled: false });
    } finally {
      setLoadingStatus(false);
    }
  }, [founderId]);

  const fetchData = useCallback(async () => {
    if (MOCKUP) return;
    setLoadingData(true); setDataError(null);
    try {
      const res = await apiFetch(`${BASE}/stripe/data/${founderId}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? "Failed"); }
      setData(await res.json());
    } catch (e: unknown) {
      setDataError(e instanceof Error ? e.message : "Failed to load Stripe data");
    } finally {
      setLoadingData(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (MOCKUP) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("stripe_error")) setConnectError(`Stripe error: ${params.get("stripe_error")}`);
    if (params.get("stripe_connected") === "1" || params.get("stripe_error")) {
      window.history.replaceState({}, "", "/payments");
    }
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (status?.connected && !MOCKUP) fetchData();
  }, [status?.connected, fetchData]);

  const revenueData = data ? buildRevenueByDay(data.charges) : [];
  const statusData = data ? buildStatusBreakdown(data.charges) : [];
  const payoutData = data ? buildPayoutsByMonth(data.payouts) : [];
  const hasActivity = data && (data.charges.length > 0 || data.payouts.length > 0);

  return (
    <>
      <PageHeader
        title="Payments"
        subtitle="Revenue, balance, and transactions"
        badge={status?.connected ? { label: status.livemode ? "Live" : "Test", color: status.livemode ? "green" : "amber" } : undefined}
        actions={status?.connected ? <HeaderSecondaryBtn label={loadingData ? "Loading…" : "Refresh"} onClick={() => { void fetchData(); }} disabled={loadingData} /> : undefined}
      />
      <div style={{ width: "100%", maxWidth: 1020, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24, padding: "24px 22px 48px", fontFamily: "var(--font-geist-sans)" }}>

      {connectError && (
        <div style={{ padding: "12px 16px", borderRadius: 10, background: "rgba(220,38,38,0.10)", border: "1px solid rgba(220,38,38,0.30)", fontSize: 13, color: "#dc2626" }}>
          {connectError}
        </div>
      )}

      {loadingStatus && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "48px 0", justifyContent: "center", color: "var(--text-3)", fontSize: 13 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#9CA3AF", display: "inline-block" }} />
          Checking Stripe connection…
        </div>
      )}

      {!loadingStatus && !status?.connected && (
        <SectionCard title="Stripe">
          <ConnectStripe founderId={founderId} email={email} />
        </SectionCard>
      )}

      {status?.connected && (
        <>
          {dataError && (
            <div style={{ padding: "12px 16px", borderRadius: 10, background: "rgba(220,38,38,0.10)", border: "1px solid rgba(220,38,38,0.30)", fontSize: 13, color: "#dc2626" }}>
              {dataError}
            </div>
          )}

          {data && (
            <>
              {/* Stat cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 14 }}>
                <StatCard label="Available Balance" value={fmt(data.balance.available, data.currency)} sub="Ready to pay out" accent="#16a34a" />
                <StatCard label="Pending Balance" value={fmt(data.balance.pending, data.currency)} sub="Processing" />
                <StatCard label="MRR" value={fmt(data.mrr, data.currency)} sub="This calendar month" accent="#002EFF" />
                <StatCard label="Total Revenue" value={fmt(data.total_revenue, data.currency)} sub={`${data.charges.filter(c => c.status === "succeeded").length} successful charges`} />
              </div>

              {/* Products + Alerts */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <ProductsSection founderId={founderId} currency={data.currency} />
                <AlertsFeed founderId={founderId} />
              </div>

              {/* Revenue chart */}
              <SectionCard title="Revenue — Last 14 Days">
                <div style={{ padding: "24px 20px 16px" }}>
                  {hasActivity ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={revenueData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                        <defs>
                          <linearGradient id="revenueGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#002EFF" stopOpacity={0.12} />
                            <stop offset="95%" stopColor="#002EFF" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} axisLine={false} interval={2} />
                        <YAxis tickFormatter={fmtShort} tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} axisLine={false} width={44} />
                        <Tooltip {...tooltipStyle} formatter={(v) => [fmt(Number(v)), "Revenue"]} />
                        <Area type="monotone" dataKey="revenue" stroke="#002EFF" strokeWidth={2} fill="url(#revenueGrad)" dot={false} activeDot={{ r: 4, fill: "#002EFF" }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)", fontSize: 13, flexDirection: "column", gap: 8 }}>
                      <span style={{ fontSize: 28, color: "#D1D5DB" }}>$</span>
                      No transactions yet — create a test payment in Stripe to see your chart
                    </div>
                  )}
                </div>
              </SectionCard>

              {/* Payouts chart + status breakdown */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <SectionCard title="Payouts by Month">
                  <div style={{ padding: "24px 20px 16px" }}>
                    {payoutData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={payoutData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                          <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} axisLine={false} />
                          <YAxis tickFormatter={fmtShort} tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} axisLine={false} width={44} />
                          <Tooltip {...tooltipStyle} formatter={(v) => [fmt(Number(v)), "Payout"]} />
                          <Bar dataKey="amount" fill="#002EFF" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)", fontSize: 13 }}>No payouts yet</div>
                    )}
                  </div>
                </SectionCard>

                <SectionCard title="Charge Status Breakdown">
                  <div style={{ padding: "24px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {statusData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={180}>
                        <PieChart>
                          <Pie data={statusData} cx="50%" cy="50%" innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                            {statusData.map((entry, i) => (
                              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip {...tooltipStyle} formatter={(v, name) => [String(v), String(name)]} />
                          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: "var(--text-3)" }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)", fontSize: 13 }}>No charges yet</div>
                    )}
                  </div>
                </SectionCard>
              </div>

              {/* Charges table */}
              <SectionCard title={`Recent Charges (${data.charges.length})`}>
                {data.charges.length === 0 ? (
                  <p style={{ padding: "20px", fontSize: 13, color: "var(--text-3)", margin: 0 }}>No charges yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" }}>
                          {["Date", "Customer", "Description", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "var(--text-3)", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.charges.map((c, i) => (
                          <tr key={c.id} style={{ borderBottom: i < data.charges.length - 1 ? "1px solid #E5E7EB" : "none", background: i % 2 === 1 ? "#F9FAFB" : "#FFFFFF" }}>
                            <td style={{ padding: "11px 16px", color: "var(--text-3)", whiteSpace: "nowrap", fontSize: 12 }}>{fmtDate(c.created)}</td>
                            <td style={{ padding: "11px 16px", color: "var(--text-2)" }}>{c.customer_email ?? "—"}</td>
                            <td style={{ padding: "11px 16px", color: "var(--text-2)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.description ?? "—"}</td>
                            <td style={{ padding: "11px 16px", color: "var(--text)", fontWeight: 600, whiteSpace: "nowrap" }}>{fmt(c.amount, c.currency)}</td>
                            <td style={{ padding: "11px 16px" }}>
                              <span style={{
                                fontSize: 11, padding: "3px 9px", borderRadius: 999, fontWeight: 500,
                                background: c.status === "succeeded" ? "#DCFCE7" : c.status === "pending" ? "#FEF9C3" : "#FEF2F2",
                                color: statusColor(c.status),
                                border: `1px solid ${c.status === "succeeded" ? "#BBF7D0" : c.status === "pending" ? "#FDE68A" : "#FECACA"}`,
                                textTransform: "capitalize",
                              }}>{c.status}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </SectionCard>

              {/* Payouts table */}
              <SectionCard title={`Payouts (${data.payouts.length})`}>
                {data.payouts.length === 0 ? (
                  <p style={{ padding: "20px", fontSize: 13, color: "var(--text-3)", margin: 0 }}>No payouts yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" }}>
                          {["Created", "Arrival Date", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "var(--text-3)", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.payouts.map((p, i) => (
                          <tr key={p.id} style={{ borderBottom: i < data.payouts.length - 1 ? "1px solid #E5E7EB" : "none", background: i % 2 === 1 ? "#F9FAFB" : "#FFFFFF" }}>
                            <td style={{ padding: "11px 16px", color: "var(--text-3)", fontSize: 12 }}>{fmtDate(p.created)}</td>
                            <td style={{ padding: "11px 16px", color: "var(--text-3)", fontSize: 12 }}>{fmtDate(p.arrival_date)}</td>
                            <td style={{ padding: "11px 16px", color: "var(--text)", fontWeight: 600 }}>{fmt(p.amount, p.currency)}</td>
                            <td style={{ padding: "11px 16px" }}>
                              <span style={{
                                fontSize: 11, padding: "3px 9px", borderRadius: 999, fontWeight: 500,
                                background: (p.status === "paid" || p.status === "in_transit") ? "#DCFCE7" : "#F3F4F6",
                                color: statusColor(p.status),
                                border: `1px solid ${(p.status === "paid" || p.status === "in_transit") ? "#BBF7D0" : "#E5E7EB"}`,
                                textTransform: "capitalize",
                              }}>{p.status.replace("_", " ")}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </SectionCard>

              <EINUpgradeSection upgraded={status.upgraded_to_business ?? false} />
            </>
          )}
        </>
      )}
      </div>
    </>
  );
}
