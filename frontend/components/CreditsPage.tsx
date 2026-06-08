"use client";

import { useEffect, useCallback, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { getCredits, purchaseCredits, CreditBalance } from "@/lib/api";

const PACKS: {
  id: "starter" | "pro" | "scale";
  label: string;
  credits: number;
  price: string;
  tagline: string;
  popular?: boolean;
}[] = [
  { id: "starter", label: "Starter", credits: 50,   price: "$4.99",  tagline: "Good for 5 runs" },
  { id: "pro",     label: "Pro",     credits: 200,  price: "$14.99", tagline: "Most popular", popular: true },
  { id: "scale",   label: "Scale",   credits: 1000, price: "$49.99", tagline: "Best value" },
];

function CoinIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7.5" stroke="#002EFF" strokeWidth="1" fill="#EFF6FF" />
      <circle cx="8" cy="8" r="5" fill="#002EFF" opacity="0.15" />
      <text x="8" y="11.5" textAnchor="middle" fontSize="7" fontWeight="700" fill="#002EFF" fontFamily="ui-sans-serif, system-ui, sans-serif">C</text>
    </svg>
  );
}

function TxRow({ tx }: { tx: CreditBalance["transactions"][number] }) {
  const isCredit = tx.amount > 0;
  const date = new Date(tx.ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--bd)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)", lineHeight: 1.3 }}>{tx.description}</div>
        <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 2 }}>{date} · {tx.type}</div>
      </div>
      <span style={{ fontSize: 13, fontWeight: 600, color: isCredit ? "#059669" : "#DC2626", fontVariantNumeric: "tabular-nums", flexShrink: 0, marginLeft: 12 }}>
        {isCredit ? "+" : ""}{tx.amount}
      </span>
    </div>
  );
}

function PackCard({ pack, onBuy, buying }: { pack: (typeof PACKS)[number]; onBuy: (id: "starter" | "pro" | "scale") => void; buying: string | null }) {
  const isLoading = buying === pack.id;
  return (
    <button
      onClick={() => onBuy(pack.id)}
      disabled={buying !== null}
      style={{
        flex: 1, minWidth: 0,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
        padding: "18px 14px",
        border: pack.popular ? "2px solid var(--blue)" : "1px solid var(--bd2)",
        background: pack.popular ? "rgba(0,46,255,0.04)" : "var(--surface)",
        cursor: buying !== null ? "not-allowed" : "pointer",
        position: "relative",
        opacity: buying !== null && !isLoading ? 0.6 : 1,
        transition: "background .12s",
      }}
    >
      {pack.popular && (
        <span style={{ position: "absolute", top: -10, left: "50%", transform: "translateX(-50%)", background: "var(--blue)", color: "#fff", fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", padding: "2px 8px", whiteSpace: "nowrap" }}>
          POPULAR
        </span>
      )}
      <div style={{ fontSize: 26, fontWeight: 800, color: "var(--blue)", letterSpacing: "-0.02em", lineHeight: 1 }}>{pack.credits.toLocaleString()}</div>
      <div style={{ fontSize: 10, color: "var(--fm)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>credits</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: "var(--fg)", marginTop: 4 }}>{pack.price}</div>
      <div style={{ fontSize: 11, color: "var(--fm)" }}>{pack.tagline}</div>
      {isLoading ? (
        <div style={{ marginTop: 6, width: 16, height: 16, border: "2px solid var(--bdim)", borderTopColor: "var(--blue)", borderRadius: "50%", animation: "credits-spin 0.7s linear infinite" }} />
      ) : (
        <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600, color: pack.popular ? "var(--blue)" : "var(--fd)" }}>Buy</div>
      )}
    </button>
  );
}

export default function CreditsPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "" : userId;
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [loading, setLoading] = useState(false);
  const [buying, setBuying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchBalance = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    try {
      setBalance(await getCredits(founderId));
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [founderId]);

  useEffect(() => {
    fetchBalance();
    const t = setInterval(fetchBalance, 30_000);
    return () => clearInterval(t);
  }, [fetchBalance]);

  async function handleBuy(pack: "starter" | "pro" | "scale") {
    if (!founderId) return;
    setError(null);
    setBuying(pack);
    try {
      const { checkout_url } = await purchaseCredits(founderId, pack);
      window.location.href = checkout_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purchase failed.");
      setBuying(null);
    }
  }

  if (!founderId) return null;

  const isLow = balance !== null && balance.balance < 10;
  const recent = balance?.transactions.slice(0, 20) ?? [];

  return (
    <>
      <style>{`@keyframes credits-spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ maxWidth: 680, margin: "0 auto", display: "grid", gap: 24 }}>

        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <CoinIcon size={22} />
          <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--fg)", fontFamily: "var(--font-chakra)", letterSpacing: "0.04em", textTransform: "uppercase", margin: 0 }}>
            Credits
          </h1>
        </div>

        {/* balance card */}
        <div style={{ border: "1px solid var(--bd2)", background: "rgba(0,46,255,0.04)", padding: "22px 24px" }}>
          {isLow && (
            <div style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "#FEF2F2", border: "1px solid #FCA5A5", padding: "2px 10px", fontSize: 11, fontWeight: 600, color: "#DC2626", marginBottom: 12, letterSpacing: "0.04em" }}>
              ⚠ Low credits
            </div>
          )}
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 48, fontWeight: 800, color: "var(--blue)", letterSpacing: "-0.04em", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
              {loading && !balance ? "—" : (balance?.balance.toLocaleString() ?? "—")}
            </span>
            <span style={{ fontSize: 16, color: "var(--fm)", fontWeight: 500 }}>credits remaining</span>
          </div>
          {balance && (
            <div style={{ display: "flex", gap: 24 }}>
              {[
                { label: "Granted", value: balance.total_granted },
                { label: "Purchased", value: balance.total_purchased },
                { label: "Used", value: balance.total_used },
              ].map(({ label, value }) => (
                <div key={label}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: "var(--fg)", fontVariantNumeric: "tabular-nums" }}>{value.toLocaleString()}</div>
                  <div style={{ fontSize: 10, color: "var(--fm)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* packs */}
        <div>
          <div className="sec-label" style={{ marginBottom: 12 }}>Buy credits</div>
          <div style={{ display: "flex", gap: 10 }}>
            {PACKS.map(p => <PackCard key={p.id} pack={p} onBuy={handleBuy} buying={buying} />)}
          </div>
          {error && (
            <div style={{ marginTop: 10, fontSize: 12, color: "#DC2626", background: "#FEF2F2", border: "1px solid #FCA5A5", padding: "9px 12px" }}>
              {error}
            </div>
          )}
        </div>

        {/* history */}
        <div>
          <div className="sec-label" style={{ marginBottom: 10 }}>Transaction history</div>
          {recent.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--fm)", padding: "16px 0" }}>No transactions yet.</div>
          ) : (
            recent.map(tx => <TxRow key={tx.id} tx={tx} />)
          )}
        </div>
      </div>
    </>
  );
}
