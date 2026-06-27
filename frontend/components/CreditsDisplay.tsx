"use client";

import { useEffect, useCallback, useState } from "react";
import Link from "next/link";
import { useDevUser } from "@/lib/use-dev-user";
import { getCredits, CreditBalance } from "@/lib/api";

function CoinIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7.5" stroke="#002EFF" strokeWidth="1" fill="#EFF6FF" />
      <circle cx="8" cy="8" r="5" fill="#002EFF" opacity="0.15" />
      <text x="8" y="11.5" textAnchor="middle" fontSize="7" fontWeight="700" fill="#002EFF" fontFamily="ui-sans-serif, system-ui, sans-serif">C</text>
    </svg>
  );
}

export default function CreditsDisplay() {
  const { userId } = useDevUser();
  const [hydrated, setHydrated] = useState(false);
  const founderId = userId === "anon" ? "" : userId;
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  const fetchBalance = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    try { setBalance(await getCredits(founderId)); } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [founderId]);

  useEffect(() => {
    fetchBalance();
    const t = setInterval(fetchBalance, 30_000);
    return () => clearInterval(t);
  }, [fetchBalance]);

  if (!hydrated || !founderId) return null;

  const isLow = balance !== null && balance.balance < 10;

  return (
    <Link
      href="/credits"
      aria-label="View credits"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: "6px 14px",
        border: isLow ? "1px solid #FCA5A5" : "1px solid var(--bd2)",
        background: isLow ? "#FEF2F2" : "var(--s2)",
        color: isLow ? "#DC2626" : "var(--blue)",
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
        textDecoration: "none",
        lineHeight: 1,
        fontVariantNumeric: "tabular-nums",
        transition: "background .12s",
        width: "100%",
      }}
    >
      <CoinIcon size={13} />
      {loading && !balance ? (
        <span style={{ color: "var(--fm)" }}>...</span>
      ) : balance ? (
        <>
          <span>{balance.balance.toLocaleString()}</span>
          <span style={{ fontWeight: 400, color: "var(--fm)", fontSize: 11 }}>credits</span>
          {isLow && (
            <span style={{ fontSize: 9, fontWeight: 700, background: "#DC2626", color: "#fff", padding: "1px 5px", letterSpacing: "0.04em", marginLeft: 2 }}>
              LOW
            </span>
          )}
        </>
      ) : (
        <span>Credits</span>
      )}
    </Link>
  );
}
