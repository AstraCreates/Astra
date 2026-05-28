"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useUser } from "@clerk/nextjs";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  if (s === "succeeded" || s === "paid") return "#4ade80";
  if (s === "pending" || s === "in_transit") return "#facc15";
  return "#f87171";
}

// ── Chart data builders ───────────────────────────────────────────────────────

function buildRevenueByDay(charges: Charge[]) {
  const map: Record<string, number> = {};
  const succeeded = charges.filter(c => c.status === "succeeded");
  for (const c of succeeded) {
    const day = fmtDate(c.created, true);
    map[day] = (map[day] ?? 0) + c.amount;
  }
  // Last 14 days skeleton
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
      borderRadius: 20, border: "1px solid var(--line)", background: "var(--glass)",
      backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)",
      boxShadow: "var(--shadow-sm)", padding: "20px 24px",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{label}</span>
        {badge && <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: "rgba(74,222,128,0.10)", color: "#4ade80", border: "1px solid rgba(74,222,128,0.22)", fontFamily: "var(--font-mono)" }}>{badge}</span>}
      </div>
      <span style={{ fontSize: 28, fontWeight: 600, color: accent ?? "var(--fg)", letterSpacing: "-0.03em", fontFamily: "var(--font-mono)" }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{sub}</span>}
    </div>
  );
}

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div style={{
      borderRadius: 20, border: "1px solid var(--line)", background: "var(--glass)",
      backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)",
      boxShadow: "var(--shadow-sm)", overflow: "hidden",
    }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--line-2)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

const CHART_COLORS = ["#4ade80", "#facc15", "#f87171", "#60a5fa", "#a78bfa"];

const tooltipStyle = {
  contentStyle: {
    background: "var(--glass, rgba(20,24,32,0.92))",
    border: "1px solid var(--line, rgba(255,255,255,0.12))",
    borderRadius: 12,
    fontSize: 12,
    color: "var(--fg, #dce6f0)",
    boxShadow: "0 4px 24px rgba(0,0,0,0.3)",
  },
  labelStyle: { color: "var(--fg-mute, rgba(220,230,240,0.5))", marginBottom: 4 },
};

// ── Connect screen ────────────────────────────────────────────────────────────

function ConnectStripe({ founderId, email }: { founderId: string; email: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const connect = async () => {
    setLoading(true); setError("");
    try {
      const res = await fetch(`${BASE}/stripe/oauth-url/${founderId}?email=${encodeURIComponent(email)}`);
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
        <div style={{ fontSize: 36, fontFamily: "var(--font-mono)", fontWeight: 700, marginBottom: 14, color: "var(--fg)" }}>$</div>
        <h2 style={{ fontSize: 18, fontWeight: 600, color: "var(--fg)", margin: "0 0 10px", letterSpacing: "-0.02em" }}>Connect your Stripe account</h2>
        <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: 0, lineHeight: 1.7 }}>
          Click below to connect or create your Stripe account. Astra will securely link it so you can track revenue, balance, and payouts right here.
        </p>
        <p style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 10, lineHeight: 1.6 }}>
          No EIN required — upgrade to a business account after your LLC is filed.
        </p>
      </div>
      {error && <div style={{ padding: "10px 16px", borderRadius: 10, background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.22)", fontSize: 12, color: "#f87171", maxWidth: 420, textAlign: "center" }}>{error}</div>}
      <button onClick={connect} disabled={loading} className="site-btn site-btn-primary" style={{ minHeight: 44, padding: "0 36px", fontSize: 14, opacity: loading ? 0.7 : 1 }}>
        {loading ? "Redirecting to Stripe…" : "Connect Stripe →"}
      </button>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
        {["Stripe opens — sign in or create a free account", "Authorize Astra to read your data", "You're redirected back here automatically"].map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--fg-mute)" }}>
            <span style={{ width: 16, height: 16, borderRadius: "50%", background: "var(--glass-hi)", border: "1px solid var(--line)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, flexShrink: 0, fontFamily: "var(--font-mono)" }}>{i + 1}</span>
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
      const res = await fetch(`${BASE}/stripe/products/${founderId}`);
      if (res.ok) { const d = await res.json(); setProducts(d.products ?? []); }
    } finally { setLoading(false); }
  }, [founderId]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.name || !form.amount) return;
    setCreating(true);
    try {
      const res = await fetch(`${BASE}/stripe/products/${founderId}`, {
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
      <button onClick={() => setShowForm(v => !v)} className="site-btn site-btn-ghost" style={{ fontSize: 11, padding: "0 12px", minHeight: 28 }}>
        {showForm ? "Cancel" : "+ New product"}
      </button>
    }>
      {showForm && (
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line-2)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "var(--fg-mute)" }}>Product name *</label>
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Pro Plan" className="site-input" style={{ padding: "7px 10px", fontSize: 12 }} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "var(--fg-mute)" }}>Price (USD) *</label>
              <input value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} placeholder="29.00" type="number" className="site-input" style={{ padding: "7px 10px", fontSize: 12 }} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "var(--fg-mute)" }}>Description</label>
              <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="Access to all features" className="site-input" style={{ padding: "7px 10px", fontSize: 12 }} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "var(--fg-mute)" }}>Billing</label>
              <select value={form.interval} onChange={e => setForm(f => ({ ...f, interval: e.target.value }))} className="site-input" style={{ padding: "7px 10px", fontSize: 12 }}>
                <option value="">One-time</option>
                <option value="month">Monthly</option>
                <option value="year">Yearly</option>
              </select>
            </div>
          </div>
          <button onClick={create} disabled={creating || !form.name || !form.amount} className="site-btn site-btn-primary" style={{ alignSelf: "flex-start", fontSize: 12, padding: "0 20px", minHeight: 34 }}>
            {creating ? "Creating…" : "Create product + payment link →"}
          </button>
        </div>
      )}

      {loading ? (
        <p style={{ padding: "20px", fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>Loading…</p>
      ) : products.length === 0 ? (
        <p style={{ padding: "20px", fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>
          No products yet. Create one above — Astra will generate a shareable Stripe payment link instantly.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {products.map((prod, i) => (
            <div key={prod.product_id} style={{ padding: "14px 20px", borderBottom: i < products.length - 1 ? "1px solid var(--line-2)" : "none", display: "flex", alignItems: "flex-start", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{prod.name}</div>
                {prod.description && <div style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 2 }}>{prod.description}</div>}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {prod.prices.map(pr => (
                    <div key={pr.price_id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 8, background: "var(--glass-lo)", border: "1px solid var(--line)" }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", fontFamily: "var(--font-mono)" }}>{fmt(pr.amount, pr.currency)}</span>
                      {pr.interval && <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>/ {pr.interval}</span>}
                      {pr.payment_link && (
                        <button onClick={() => copy(pr.payment_link!)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: copied === pr.payment_link ? "#4ade80" : "#60a5fa", padding: "0 4px" }}>
                          {copied === pr.payment_link ? "Copied!" : "Copy link"}
                        </button>
                      )}
                      {pr.payment_link && (
                        <a href={pr.payment_link} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "var(--fg-mute)", textDecoration: "none" }}>↗</a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)", flexShrink: 0, marginTop: 2 }}>{fmtDate(prod.created)}</span>
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
      const res = await fetch(`${BASE}/stripe/events/${founderId}`);
      if (res.ok) { const d = await res.json(); setEvents(d.events ?? []); setWebhookRegistered(d.events?.length > 0 || false); }
    } catch { /* silent */ }
  }, [founderId]);

  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t); }, [load]);

  const registerWebhook = async () => {
    setRegistering(true);
    try {
      const res = await fetch(`${BASE}/stripe/register-webhook/${founderId}`, {
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
    if (type.includes("succeeded") || type.includes("paid")) return "#4ade80";
    if (type.includes("failed")) return "#f87171";
    if (type.includes("deleted")) return "#facc15";
    return "#60a5fa";
  };

  return (
    <SectionCard title="Payment Alerts" action={
      !webhookRegistered ? (
        <button onClick={registerWebhook} disabled={registering} className="site-btn site-btn-ghost" style={{ fontSize: 11, padding: "0 12px", minHeight: 28 }}>
          {registering ? "Registering…" : "Enable alerts"}
        </button>
      ) : (
        <span style={{ fontSize: 10, color: "#4ade80", fontFamily: "var(--font-mono)" }}>● Live</span>
      )
    }>
      {events.length === 0 ? (
        <div style={{ padding: "20px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>
            {webhookRegistered ? "No events yet — alerts will appear here when payments come in." : "Enable alerts to get notified instantly when payments come in, subscriptions churn, or payouts complete."}
          </p>
          {!webhookRegistered && (
            <p style={{ fontSize: 11, color: "var(--fg-mute)", margin: 0 }}>
              Note: requires your backend to be publicly accessible (production URL).
            </p>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {events.map((ev, i) => (
            <div key={ev.id || i} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "11px 20px", borderBottom: i < events.length - 1 ? "1px solid var(--line-2)" : "none" }}>
              <span style={{ fontSize: 14, color: alertColor(ev.type), flexShrink: 0, marginTop: 1 }}>{alertIcon(ev.type)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: 13, color: "var(--fg)" }}>{ev.alert}</p>
                <p style={{ margin: "2px 0 0", fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{ev.type}</p>
              </div>
              <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>{fmtDate(ev.created)}</span>
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
              <p style={{ margin: "0 0 4px", fontSize: 13, fontWeight: 600, color: "#4ade80" }}>✓ Upgraded to business account</p>
              <p style={{ margin: 0, fontSize: 12, color: "var(--fg-mute)", lineHeight: 1.6 }}>Registered under <strong>{businessName ?? "your LLC"}</strong>. Tax reporting now uses your EIN.</p>
            </>
          ) : (
            <>
              <p style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>Upgrade to LLC / Business</p>
              <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--fg-mute)", lineHeight: 1.6 }}>Once your LLC is filed via Astra and your EIN arrives from the IRS, you&apos;ll update your Stripe account to your business entity. Switches tax reporting from SSN to EIN.</p>
              <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)" }}><strong style={{ color: "var(--fg-dim)" }}>Timeline:</strong> File LLC → IRS issues EIN in 1–4 weeks → update Stripe → done.</p>
            </>
          )}
        </div>
        <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, whiteSpace: "nowrap", flexShrink: 0, background: upgraded ? "rgba(74,222,128,0.10)" : "rgba(176,180,186,0.10)", color: upgraded ? "#4ade80" : "var(--fg-mute)", border: `1px solid ${upgraded ? "rgba(74,222,128,0.22)" : "var(--line)"}`, fontFamily: "var(--font-mono)" }}>
          {upgraded ? "Complete" : "Pending LLC"}
        </span>
      </div>
    </SectionCard>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PaymentsPage() {
  const { user } = useUser();
  const founderId = user?.id ?? "founder_001";
  const email = user?.primaryEmailAddress?.emailAddress ?? "";

  const [status, setStatus] = useState<StripeStatus | null>(null);
  const [data, setData] = useState<StripeData | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const res = await fetch(`${BASE}/stripe/status/${founderId}`);
      setStatus(await res.json());
    } catch {
      setStatus({ connected: false, charges_enabled: false, payouts_enabled: false });
    } finally {
      setLoadingStatus(false);
    }
  }, [founderId]);

  const fetchData = useCallback(async () => {
    setLoadingData(true); setDataError(null);
    try {
      const res = await fetch(`${BASE}/stripe/data/${founderId}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? "Failed"); }
      setData(await res.json());
    } catch (e: unknown) {
      setDataError(e instanceof Error ? e.message : "Failed to load Stripe data");
    } finally {
      setLoadingData(false);
    }
  }, [founderId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("stripe_error")) setConnectError(`Stripe error: ${params.get("stripe_error")}`);
    if (params.get("stripe_connected") === "1" || params.get("stripe_error")) {
      window.history.replaceState({}, "", "/payments");
    }
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (status?.connected) fetchData();
  }, [status?.connected, fetchData]);

  const revenueData = data ? buildRevenueByDay(data.charges) : [];
  const statusData = data ? buildStatusBreakdown(data.charges) : [];
  const payoutData = data ? buildPayoutsByMonth(data.payouts) : [];
  const hasActivity = data && (data.charges.length > 0 || data.payouts.length > 0);

  return (
    <div style={{ width: "100%", maxWidth: 1020, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>← Back</Link>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Payments</h1>
            <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>Revenue, balance, and transactions</p>
          </div>
        </div>
        {status?.connected && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: status.livemode ? "rgba(74,222,128,0.10)" : "rgba(250,204,21,0.10)", color: status.livemode ? "#4ade80" : "#facc15", border: `1px solid ${status.livemode ? "rgba(74,222,128,0.22)" : "rgba(250,204,21,0.22)"}`, fontFamily: "var(--font-mono)" }}>
              {status.livemode ? "● Live" : "● Test mode"}
            </span>
            <button onClick={fetchData} disabled={loadingData} className="site-btn site-btn-ghost" style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}>
              {loadingData ? "Loading…" : "Refresh"}
            </button>
          </div>
        )}
      </div>

      {connectError && <div style={{ padding: "12px 16px", borderRadius: 12, background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.22)", fontSize: 13, color: "#f87171" }}>{connectError}</div>}

      {loadingStatus && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "48px 0", justifyContent: "center", color: "var(--fg-mute)", fontSize: 13 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--fg-mute)", display: "inline-block" }} />
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
          {dataError && <div style={{ padding: "12px 16px", borderRadius: 12, background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.22)", fontSize: 13, color: "#f87171" }}>{dataError}</div>}

          {data && (
            <>
              {/* Stat cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                <StatCard label="Available Balance" value={fmt(data.balance.available, data.currency)} sub="Ready to pay out" accent="#4ade80" />
                <StatCard label="Pending Balance" value={fmt(data.balance.pending, data.currency)} sub="Processing" />
                <StatCard label="MRR" value={fmt(data.mrr, data.currency)} sub="This calendar month" accent="#60a5fa" />
                <StatCard label="Total Revenue" value={fmt(data.total_revenue, data.currency)} sub={`${data.charges.filter(c => c.status === "succeeded").length} successful charges`} />
              </div>

              {/* Products + Alerts */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <ProductsSection founderId={founderId} currency={data.currency} />
                <AlertsFeed founderId={founderId} />
              </div>

              {/* Revenue chart */}
              <SectionCard title="Revenue — Last 14 Days">
                <div style={{ padding: "20px 20px 12px" }}>
                  {hasActivity ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={revenueData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                        <defs>
                          <linearGradient id="revenueGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#60a5fa" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#60a5fa" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--fg-mute)" }} tickLine={false} axisLine={false} interval={2} />
                        <YAxis tickFormatter={fmtShort} tick={{ fontSize: 10, fill: "var(--fg-mute)" }} tickLine={false} axisLine={false} width={44} />
                        <Tooltip {...tooltipStyle} formatter={(v: number) => [fmt(v), "Revenue"]} />
                        <Area type="monotone" dataKey="revenue" stroke="#60a5fa" strokeWidth={2} fill="url(#revenueGrad)" dot={false} activeDot={{ r: 4, fill: "#60a5fa" }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg-mute)", fontSize: 13, flexDirection: "column", gap: 8 }}>
                      <span style={{ fontSize: 24 }}>$</span>
                      No transactions yet — create a test payment in Stripe to see your chart
                    </div>
                  )}
                </div>
              </SectionCard>

              {/* Payouts chart + status breakdown */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>

                <SectionCard title="Payouts by Month">
                  <div style={{ padding: "20px 20px 12px" }}>
                    {payoutData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={payoutData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                          <XAxis dataKey="month" tick={{ fontSize: 10, fill: "var(--fg-mute)" }} tickLine={false} axisLine={false} />
                          <YAxis tickFormatter={fmtShort} tick={{ fontSize: 10, fill: "var(--fg-mute)" }} tickLine={false} axisLine={false} width={44} />
                          <Tooltip {...tooltipStyle} formatter={(v: number) => [fmt(v), "Payout"]} />
                          <Bar dataKey="amount" fill="#4ade80" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg-mute)", fontSize: 12 }}>No payouts yet</div>
                    )}
                  </div>
                </SectionCard>

                <SectionCard title="Charge Status Breakdown">
                  <div style={{ padding: "20px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    {statusData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={180}>
                        <PieChart>
                          <Pie data={statusData} cx="50%" cy="50%" innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                            {statusData.map((entry, i) => (
                              <Cell key={i} fill={statusColor(entry.name)} opacity={0.85} />
                            ))}
                          </Pie>
                          <Tooltip {...tooltipStyle} formatter={(v: number, name: string) => [v, name]} />
                          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: "var(--fg-mute)" }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg-mute)", fontSize: 12 }}>No charges yet</div>
                    )}
                  </div>
                </SectionCard>
              </div>

              {/* Charges table */}
              <SectionCard title={`Recent Charges (${data.charges.length})`}>
                {data.charges.length === 0 ? (
                  <p style={{ padding: "20px", fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>No charges yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--line-2)" }}>
                          {["Date", "Customer", "Description", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "var(--fg-mute)", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.charges.map((c, i) => (
                          <tr key={c.id} style={{ borderBottom: i < data.charges.length - 1 ? "1px solid var(--line-2)" : "none" }}>
                            <td style={{ padding: "10px 16px", color: "var(--fg-mute)", whiteSpace: "nowrap", fontFamily: "var(--font-mono)", fontSize: 11 }}>{fmtDate(c.created)}</td>
                            <td style={{ padding: "10px 16px", color: "var(--fg-dim)" }}>{c.customer_email ?? "—"}</td>
                            <td style={{ padding: "10px 16px", color: "var(--fg-dim)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.description ?? "—"}</td>
                            <td style={{ padding: "10px 16px", color: "var(--fg)", fontFamily: "var(--font-mono)", fontWeight: 500, whiteSpace: "nowrap" }}>{fmt(c.amount, c.currency)}</td>
                            <td style={{ padding: "10px 16px" }}>
                              <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: `${statusColor(c.status)}18`, color: statusColor(c.status), border: `1px solid ${statusColor(c.status)}30`, fontFamily: "var(--font-mono)", textTransform: "capitalize" }}>{c.status}</span>
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
                  <p style={{ padding: "20px", fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>No payouts yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--line-2)" }}>
                          {["Created", "Arrival Date", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "var(--fg-mute)", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.payouts.map((p, i) => (
                          <tr key={p.id} style={{ borderBottom: i < data.payouts.length - 1 ? "1px solid var(--line-2)" : "none" }}>
                            <td style={{ padding: "10px 16px", color: "var(--fg-mute)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{fmtDate(p.created)}</td>
                            <td style={{ padding: "10px 16px", color: "var(--fg-mute)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{fmtDate(p.arrival_date)}</td>
                            <td style={{ padding: "10px 16px", color: "var(--fg)", fontFamily: "var(--font-mono)", fontWeight: 500 }}>{fmt(p.amount, p.currency)}</td>
                            <td style={{ padding: "10px 16px" }}>
                              <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: `${statusColor(p.status)}18`, color: statusColor(p.status), border: `1px solid ${statusColor(p.status)}30`, fontFamily: "var(--font-mono)", textTransform: "capitalize" }}>{p.status.replace("_", " ")}</span>
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
  );
}
