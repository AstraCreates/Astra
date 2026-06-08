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

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

// â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

// â”€â”€ Chart data builders â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

// â”€â”€ Sub-components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function StatCard({ label, value, sub, accent, badge }: {
  label: string; value: string; sub?: string; accent?: string; badge?: string;
}) {
  return (
    <div style={{
      borderRadius: 14,
      border: "1px solid #E5E7EB",
      background: "#FFFFFF",
      boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
      padding: "20px 24px",
      display: "flex",
      flexDirection: "column",
      gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "#9CA3AF", fontWeight: 500 }}>{label}</span>
        {badge && (
          <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: "#DCFCE7", color: "#16a34a", border: "1px solid #BBF7D0", fontWeight: 500 }}>
            {badge}
          </span>
        )}
      </div>
      <span style={{ fontSize: 26, fontWeight: 600, color: accent ?? "#111827", letterSpacing: "-0.02em", fontFamily: "var(--font-geist-sans)" }}>{value}</span>
      {sub && <span style={{ fontSize: 12, color: "#9CA3AF" }}>{sub}</span>}
    </div>
  );
}

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div style={{
      borderRadius: 14,
      border: "1px solid #E5E7EB",
      background: "#FFFFFF",
      boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
      overflow: "hidden",
    }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid #E5E7EB", display: "flex", alignItems: "center", justifyContent: "space-between", background: "#F8F9FA" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

const CHART_COLORS = ["#002EFF", "#16a34a", "#d97706", "#dc2626", "#7c3aed"];

const tooltipStyle = {
  contentStyle: {
    background: "#FFFFFF",
    border: "1px solid #E5E7EB",
    borderRadius: 10,
    fontSize: 12,
    color: "#111827",
    boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
  },
  labelStyle: { color: "#9CA3AF", marginBottom: 4 },
};

// â”€â”€ Connect screen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
          background: "#EFF6FF", border: "1px solid #BFDBFE",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 24, margin: "0 auto 20px", color: "#002EFF",
        }}>$</div>
        <h2 style={{ fontSize: 18, fontWeight: 600, color: "#111827", margin: "0 0 10px", letterSpacing: "-0.02em" }}>Connect your Stripe account</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: 0, lineHeight: 1.7 }}>
          Click below to connect or create your Stripe account. Astra will securely link it so you can track revenue, balance, and payouts right here.
        </p>
        <p style={{ fontSize: 12, color: "#9CA3AF", marginTop: 10, lineHeight: 1.6 }}>
          No EIN required â€” upgrade to a business account after your LLC is filed.
        </p>
      </div>
      {error && (
        <div style={{ padding: "10px 16px", borderRadius: 10, background: "#FEF2F2", border: "1px solid #FECACA", fontSize: 12, color: "#dc2626", maxWidth: 420, textAlign: "center" }}>
          {error}
        </div>
      )}
      <button onClick={connect} disabled={loading} className="site-btn site-btn-primary" style={{ minHeight: 44, padding: "0 36px", fontSize: 14, opacity: loading ? 0.7 : 1 }}>
        {loading ? "Redirecting to Stripeâ€¦" : "Connect Stripe â†’"}
      </button>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
        {["Stripe opens â€” sign in or create a free account", "Authorize Astra to read your data", "You're redirected back here automatically"].map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "#6B7280" }}>
            <span style={{
              width: 20, height: 20, borderRadius: "50%",
              background: "#EFF6FF", border: "1px solid #BFDBFE",
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
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E7EB", display: "flex", flexDirection: "column", gap: 12, background: "#F8F9FA" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {[
              { label: "Product name *", field: "name" as const, placeholder: "Pro Plan", type: "text" },
              { label: "Price (USD) *", field: "amount" as const, placeholder: "29.00", type: "number" },
              { label: "Description", field: "description" as const, placeholder: "Access to all features", type: "text" },
            ].map(({ label, field, placeholder, type }) => (
              <div key={field} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <label style={{ fontSize: 11, color: "#6B7280", fontWeight: 500 }}>{label}</label>
                <input
                  value={form[field]}
                  onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
                  placeholder={placeholder}
                  type={type}
                  style={{
                    padding: "8px 12px", fontSize: 13, borderRadius: 8,
                    border: "1px solid #E5E7EB", background: "#FFFFFF",
                    color: "#111827", outline: "none",
                  }}
                  onFocus={e => (e.target.style.borderColor = "#002EFF")}
                  onBlur={e => (e.target.style.borderColor = "#E5E7EB")}
                />
              </div>
            ))}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label style={{ fontSize: 11, color: "#6B7280", fontWeight: 500 }}>Billing</label>
              <select
                value={form.interval}
                onChange={e => setForm(f => ({ ...f, interval: e.target.value }))}
                style={{
                  padding: "8px 12px", fontSize: 13, borderRadius: 8,
                  border: "1px solid #E5E7EB", background: "#FFFFFF",
                  color: "#111827", outline: "none",
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
            {creating ? "Creatingâ€¦" : "Create product + payment link â†’"}
          </button>
        </div>
      )}

      {loading ? (
        <p style={{ padding: "20px", fontSize: 13, color: "#9CA3AF", margin: 0 }}>Loadingâ€¦</p>
      ) : products.length === 0 ? (
        <p style={{ padding: "20px", fontSize: 13, color: "#9CA3AF", margin: 0 }}>
          No products yet. Create one above â€” Astra will generate a shareable Stripe payment link instantly.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {products.map((prod, i) => (
            <div key={prod.product_id} style={{ padding: "14px 20px", borderBottom: i < products.length - 1 ? "1px solid #E5E7EB" : "none", display: "flex", alignItems: "flex-start", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>{prod.name}</div>
                {prod.description && <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{prod.description}</div>}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {prod.prices.map(pr => (
                    <div key={pr.price_id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 8, background: "#F8F9FA", border: "1px solid #E5E7EB" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>{fmt(pr.amount, pr.currency)}</span>
                      {pr.interval && <span style={{ fontSize: 11, color: "#9CA3AF" }}>/ {pr.interval}</span>}
                      {pr.payment_link && (
                        <button
                          onClick={() => copy(pr.payment_link!)}
                          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: copied === pr.payment_link ? "#16a34a" : "#002EFF", padding: "0 4px", fontWeight: 500 }}
                        >
                          {copied === pr.payment_link ? "Copied!" : "Copy link"}
                        </button>
                      )}
                      {pr.payment_link && (
                        <a href={pr.payment_link} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: "#9CA3AF", textDecoration: "none" }}>â†—</a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <span style={{ fontSize: 11, color: "#9CA3AF", flexShrink: 0, marginTop: 2 }}>{fmtDate(prod.created)}</span>
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
    if (type.includes("succeeded") || type.includes("paid")) return "âœ“";
    if (type.includes("failed")) return "âœ—";
    if (type.includes("subscription.deleted")) return "â†©";
    if (type.includes("subscription")) return "â†»";
    if (type.includes("refund")) return "â†²";
    return "â—";
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
            background: "#FFFFFF", color: "#374151",
            border: "1px solid #E5E7EB", cursor: "pointer", fontWeight: 500,
          }}
        >
          {registering ? "Registeringâ€¦" : "Enable alerts"}
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
          <p style={{ fontSize: 13, color: "#6B7280", margin: 0 }}>
            {webhookRegistered ? "No events yet â€” alerts will appear here when payments come in." : "Enable alerts to get notified instantly when payments come in, subscriptions churn, or payouts complete."}
          </p>
          {!webhookRegistered && (
            <p style={{ fontSize: 12, color: "#9CA3AF", margin: 0 }}>
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
                <p style={{ margin: 0, fontSize: 13, color: "#111827" }}>{ev.alert}</p>
                <p style={{ margin: "2px 0 0", fontSize: 11, color: "#9CA3AF" }}>{ev.type}</p>
              </div>
              <span style={{ fontSize: 11, color: "#9CA3AF", flexShrink: 0 }}>{fmtDate(ev.created)}</span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function EINUpgradeSection({ upgraded, businessName }: { upgraded: boolean; businessName?: string }) {
  return (
    <SectionCard title="Business Upgrade Â· EIN">
      <div style={{ padding: "20px 24px", display: "flex", alignItems: "flex-start", gap: 16 }}>
        <div style={{ flex: 1 }}>
          {upgraded ? (
            <>
              <p style={{ margin: "0 0 4px", fontSize: 13, fontWeight: 600, color: "#16a34a" }}>Upgraded to business account</p>
              <p style={{ margin: 0, fontSize: 13, color: "#6B7280", lineHeight: 1.6 }}>Registered under <strong style={{ color: "#111827" }}>{businessName ?? "your LLC"}</strong>. Tax reporting now uses your EIN.</p>
            </>
          ) : (
            <>
              <p style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "#111827" }}>Upgrade to LLC / Business</p>
              <p style={{ margin: "0 0 10px", fontSize: 13, color: "#6B7280", lineHeight: 1.6 }}>Once your LLC is filed via Astra and your EIN arrives from the IRS, you&apos;ll update your Stripe account to your business entity. Switches tax reporting from SSN to EIN.</p>
              <p style={{ margin: 0, fontSize: 12, color: "#9CA3AF" }}><strong style={{ color: "#374151" }}>Timeline:</strong> File LLC â†’ IRS issues EIN in 1â€“4 weeks â†’ update Stripe â†’ done.</p>
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

// â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function PaymentsPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const email = "";

  const [status, setStatus] = useState<StripeStatus | null>(null);
  const [data, setData] = useState<StripeData | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
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
    <div style={{ width: "100%", maxWidth: 1020, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24, fontFamily: "var(--font-geist-sans)" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Link href="/" style={{
            fontSize: 13, padding: "6px 14px", borderRadius: 8,
            background: "#FFFFFF", color: "#374151",
            border: "1px solid #E5E7EB", textDecoration: "none", fontWeight: 500,
          }}>â† Back</Link>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: "#111827", letterSpacing: "-0.02em" }}>Payments</h1>
            <p style={{ fontSize: 13, color: "#6B7280", margin: "3px 0 0" }}>Revenue, balance, and transactions</p>
          </div>
        </div>
        {status?.connected && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 999, fontWeight: 500,
              background: status.livemode ? "#DCFCE7" : "#FEF9C3",
              color: status.livemode ? "#16a34a" : "#854d0e",
              border: `1px solid ${status.livemode ? "#BBF7D0" : "#FDE68A"}`,
              display: "flex", alignItems: "center", gap: 5,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: status.livemode ? "#16a34a" : "#ca8a04", display: "inline-block" }} />
              {status.livemode ? "Live" : "Test mode"}
            </span>
            <button
              onClick={fetchData}
              disabled={loadingData}
              style={{
                fontSize: 13, padding: "6px 16px", borderRadius: 8,
                background: "#FFFFFF", color: "#374151",
                border: "1px solid #E5E7EB", cursor: "pointer", fontWeight: 500,
              }}
            >
              {loadingData ? "Loadingâ€¦" : "Refresh"}
            </button>
          </div>
        )}
      </div>

      {connectError && (
        <div style={{ padding: "12px 16px", borderRadius: 10, background: "#FEF2F2", border: "1px solid #FECACA", fontSize: 13, color: "#dc2626" }}>
          {connectError}
        </div>
      )}

      {loadingStatus && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "48px 0", justifyContent: "center", color: "#9CA3AF", fontSize: 13 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#9CA3AF", display: "inline-block" }} />
          Checking Stripe connectionâ€¦
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
            <div style={{ padding: "12px 16px", borderRadius: 10, background: "#FEF2F2", border: "1px solid #FECACA", fontSize: 13, color: "#dc2626" }}>
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
              <SectionCard title="Revenue â€” Last 14 Days">
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
                    <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "#9CA3AF", fontSize: 13, flexDirection: "column", gap: 8 }}>
                      <span style={{ fontSize: 28, color: "#D1D5DB" }}>$</span>
                      No transactions yet â€” create a test payment in Stripe to see your chart
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
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "#9CA3AF", fontSize: 13 }}>No payouts yet</div>
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
                          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: "#6B7280" }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "#9CA3AF", fontSize: 13 }}>No charges yet</div>
                    )}
                  </div>
                </SectionCard>
              </div>

              {/* Charges table */}
              <SectionCard title={`Recent Charges (${data.charges.length})`}>
                {data.charges.length === 0 ? (
                  <p style={{ padding: "20px", fontSize: 13, color: "#9CA3AF", margin: 0 }}>No charges yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" }}>
                          {["Date", "Customer", "Description", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#6B7280", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.charges.map((c, i) => (
                          <tr key={c.id} style={{ borderBottom: i < data.charges.length - 1 ? "1px solid #E5E7EB" : "none", background: i % 2 === 1 ? "#F9FAFB" : "#FFFFFF" }}>
                            <td style={{ padding: "11px 16px", color: "#6B7280", whiteSpace: "nowrap", fontSize: 12 }}>{fmtDate(c.created)}</td>
                            <td style={{ padding: "11px 16px", color: "#374151" }}>{c.customer_email ?? "â€”"}</td>
                            <td style={{ padding: "11px 16px", color: "#374151", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.description ?? "â€”"}</td>
                            <td style={{ padding: "11px 16px", color: "#111827", fontWeight: 600, whiteSpace: "nowrap" }}>{fmt(c.amount, c.currency)}</td>
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
                  <p style={{ padding: "20px", fontSize: 13, color: "#9CA3AF", margin: 0 }}>No payouts yet.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" }}>
                          {["Created", "Arrival Date", "Amount", "Status"].map(h => (
                            <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#6B7280", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.payouts.map((p, i) => (
                          <tr key={p.id} style={{ borderBottom: i < data.payouts.length - 1 ? "1px solid #E5E7EB" : "none", background: i % 2 === 1 ? "#F9FAFB" : "#FFFFFF" }}>
                            <td style={{ padding: "11px 16px", color: "#6B7280", fontSize: 12 }}>{fmtDate(p.created)}</td>
                            <td style={{ padding: "11px 16px", color: "#6B7280", fontSize: 12 }}>{fmtDate(p.arrival_date)}</td>
                            <td style={{ padding: "11px 16px", color: "#111827", fontWeight: 600 }}>{fmt(p.amount, p.currency)}</td>
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
  );
}

