"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { getCredits, purchaseCredits, CreditBalance } from "@/lib/api";

// ── Pack definitions ──────────────────────────────────────────────────────────

const PACKS: {
  id: "starter" | "pro" | "scale";
  label: string;
  credits: number;
  price: string;
  tagline: string;
  popular?: boolean;
}[] = [
  {
    id: "starter",
    label: "Starter",
    credits: 50,
    price: "$4.99",
    tagline: "Good for 5 runs",
  },
  {
    id: "pro",
    label: "Pro",
    credits: 200,
    price: "$14.99",
    tagline: "Most popular",
    popular: true,
  },
  {
    id: "scale",
    label: "Scale",
    credits: 1000,
    price: "$49.99",
    tagline: "Best value",
  },
];

// ── Coin icon ─────────────────────────────────────────────────────────────────

function CoinIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="7.5" stroke="#002EFF" strokeWidth="1" fill="#EFF6FF" />
      <circle cx="8" cy="8" r="5" fill="#002EFF" opacity="0.15" />
      <text
        x="8"
        y="11.5"
        textAnchor="middle"
        fontSize="7"
        fontWeight="700"
        fill="#002EFF"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
      >
        C
      </text>
    </svg>
  );
}

// ── Transaction row ───────────────────────────────────────────────────────────

function TxRow({
  tx,
}: {
  tx: CreditBalance["transactions"][number];
}) {
  const isCredit = tx.amount > 0;
  const date = new Date(tx.ts).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 0",
        borderBottom: "1px solid #F3F4F6",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "#111827",
            lineHeight: 1.3,
          }}
        >
          {tx.description}
        </div>
        <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>
          {date} &middot; {tx.type}
        </div>
      </div>
      <span
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: isCredit ? "#059669" : "#DC2626",
          fontVariantNumeric: "tabular-nums",
          flexShrink: 0,
          marginLeft: 12,
        }}
      >
        {isCredit ? "+" : ""}
        {tx.amount}
      </span>
    </div>
  );
}

// ── Pack card ─────────────────────────────────────────────────────────────────

function PackCard({
  pack,
  onBuy,
  buying,
}: {
  pack: (typeof PACKS)[number];
  onBuy: (id: "starter" | "pro" | "scale") => void;
  buying: string | null;
}) {
  const [hovered, setHovered] = useState(false);
  const isLoading = buying === pack.id;

  return (
    <button
      onClick={() => onBuy(pack.id)}
      disabled={buying !== null}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 6,
        padding: "16px 12px",
        border: pack.popular
          ? "2px solid #002EFF"
          : `1px solid ${hovered ? "#D1D5DB" : "#E5E7EB"}`,
        borderRadius: 12,
        background: pack.popular
          ? hovered
            ? "#EFF6FF"
            : "#F8FAFF"
          : hovered
          ? "#F9FAFB"
          : "#FFFFFF",
        cursor: buying !== null ? "not-allowed" : "pointer",
        transition: "background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease",
        boxShadow:
          hovered && !buying
            ? "0 2px 8px rgba(37,99,235,0.10)"
            : "0 1px 3px rgba(0,0,0,0.06)",
        position: "relative",
        opacity: buying !== null && !isLoading ? 0.6 : 1,
      }}
    >
      {pack.popular && (
        <span
          style={{
            position: "absolute",
            top: -10,
            left: "50%",
            transform: "translateX(-50%)",
            background: "#002EFF",
            color: "#FFFFFF",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.06em",
            padding: "2px 8px",
            borderRadius: 999,
            whiteSpace: "nowrap",
          }}
        >
          POPULAR
        </span>
      )}

      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: "#002EFF",
          letterSpacing: "-0.02em",
          lineHeight: 1,
        }}
      >
        {pack.credits.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: "#6B7280", fontWeight: 500 }}>
        credits
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: "#111827",
          marginTop: 4,
        }}
      >
        {pack.price}
      </div>
      <div style={{ fontSize: 11, color: "#9CA3AF" }}>{pack.tagline}</div>

      {isLoading ? (
        <div
          style={{
            marginTop: 6,
            width: 16,
            height: 16,
            border: "2px solid #BFDBFE",
            borderTopColor: "#002EFF",
            borderRadius: "50%",
            animation: "credits-spin 0.7s linear infinite",
          }}
        />
      ) : (
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            fontWeight: 600,
            color: pack.popular ? "#002EFF" : "#374151",
          }}
        >
          Buy
        </div>
      )}
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CreditsDisplay() {
  const { userId } = useDevUser();
  const [open, setOpen] = useState(false);
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [loadingBalance, setLoadingBalance] = useState(false);
  const [buying, setBuying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const founderId = userId === "anon" ? "" : userId;

  const fetchBalance = useCallback(async () => {
    if (!founderId) return;
    try {
      setLoadingBalance(true);
      const data = await getCredits(founderId);
      setBalance(data);
    } catch {
      // silently ignore — balance may not exist yet
    } finally {
      setLoadingBalance(false);
    }
  }, [founderId]);

  // Initial load when user resolves
  useEffect(() => {
    if (founderId) {
      fetchBalance();
    }
  }, [founderId, fetchBalance]);

  // Poll every 30 s when modal is open
  useEffect(() => {
    if (open && founderId) {
      fetchBalance();
      pollRef.current = setInterval(fetchBalance, 30_000);
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [open, founderId, fetchBalance]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open]);

  async function handleBuy(pack: "starter" | "pro" | "scale") {
    if (!founderId) return;
    setError(null);
    setBuying(pack);
    try {
      const { checkout_url } = await purchaseCredits(founderId, pack);
      window.location.href = checkout_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purchase failed. Please try again.");
      setBuying(null);
    }
  }

  if (!founderId) return null;

  const isLow = balance !== null && balance.balance < 10;
  const recent = balance?.transactions.slice(0, 10) ?? [];

  return (
    <>
      {/* Spinner keyframe */}
      <style>{`
        @keyframes credits-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      {/* Trigger button */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="View credits"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 12px",
          borderRadius: 9999,
          border: isLow ? "1px solid #FCA5A5" : "1px solid #E5E7EB",
          background: isLow ? "#FEF2F2" : "#EFF6FF",
          color: isLow ? "#DC2626" : "#002EFF",
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          transition: "background 0.15s ease, border-color 0.15s ease",
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          position: "relative",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = isLow
            ? "#FEE2E2"
            : "#DBEAFE";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = isLow
            ? "#FEF2F2"
            : "#EFF6FF";
        }}
      >
        <CoinIcon size={14} />
        {balance === null ? (
          loadingBalance ? (
            <span style={{ color: "#9CA3AF" }}>...</span>
          ) : (
            <span>Credits</span>
          )
        ) : (
          <span>{balance.balance.toLocaleString()} credits</span>
        )}
        {isLow && (
          <span
            style={{
              marginLeft: 2,
              fontSize: 10,
              fontWeight: 700,
              background: "#DC2626",
              color: "#FFFFFF",
              borderRadius: 999,
              padding: "1px 5px",
              letterSpacing: "0.04em",
            }}
          >
            LOW
          </span>
        )}
      </button>

      {/* Price / spend tracker */}
      {balance !== null && (
        <div style={{ marginTop: 5, paddingLeft: 2, fontSize: 9.5, color: "#9CA3AF", fontFamily: "var(--font-ibm-mono), monospace", lineHeight: 1.5 }}>
          spent {balance.total_used.toLocaleString()} cr · ~${(balance.total_used * 0.0998).toFixed(2)}
        </div>
      )}

      {/* Modal overlay */}
      {open && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 200,
            background: "rgba(17,24,39,0.35)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "flex-end",
            padding: "64px 24px 0 0",
          }}
        >
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-label="Credits"
            style={{
              background: "#FFFFFF",
              borderRadius: 16,
              border: "1px solid #E5E7EB",
              boxShadow:
                "0 2px 8px rgba(0,0,0,0.06), 0 16px 40px rgba(0,0,0,0.12)",
              width: 380,
              maxHeight: "calc(100vh - 80px)",
              overflowY: "auto",
              padding: "24px 20px",
              fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif",
              animation: "fadeIn 0.18s ease both",
            }}
          >
            {/* Header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 20,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <CoinIcon size={20} />
                <span
                  style={{
                    fontSize: 16,
                    fontWeight: 700,
                    color: "#111827",
                    letterSpacing: "-0.01em",
                  }}
                >
                  Credits
                </span>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "#9CA3AF",
                  fontSize: 18,
                  lineHeight: 1,
                  padding: 4,
                  borderRadius: 6,
                  transition: "color 0.12s ease",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = "#374151";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = "#9CA3AF";
                }}
              >
                &times;
              </button>
            </div>

            {/* Balance summary */}
            <div
              style={{
                background: "#EFF6FF",
                border: "1px solid #BFDBFE",
                borderRadius: 12,
                padding: "16px 18px",
                marginBottom: 20,
              }}
            >
              {isLow && (
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    background: "#FEF2F2",
                    border: "1px solid #FCA5A5",
                    borderRadius: 999,
                    padding: "2px 8px",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#DC2626",
                    marginBottom: 10,
                    letterSpacing: "0.04em",
                  }}
                >
                  <span aria-hidden="true">&#9888;</span> Low credits
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 6,
                  marginBottom: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 36,
                    fontWeight: 800,
                    color: "#002EFF",
                    letterSpacing: "-0.03em",
                    lineHeight: 1,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {balance?.balance.toLocaleString() ?? "—"}
                </span>
                <span style={{ fontSize: 15, color: "#3B82F6", fontWeight: 500 }}>
                  credits
                </span>
              </div>

              {balance && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 4,
                    marginTop: 4,
                  }}
                >
                  {[
                    { label: "Granted", value: balance.total_granted },
                    { label: "Purchased", value: balance.total_purchased },
                    { label: "Used", value: balance.total_used },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ textAlign: "center" }}>
                      <div
                        style={{
                          fontSize: 15,
                          fontWeight: 700,
                          color: "#1E40AF",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {value.toLocaleString()}
                      </div>
                      <div style={{ fontSize: 10, color: "#60A5FA", fontWeight: 500 }}>
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Purchase packs */}
            <div style={{ marginBottom: 20 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#6B7280",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  marginBottom: 12,
                }}
              >
                Buy Credits
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {PACKS.map((p) => (
                  <PackCard key={p.id} pack={p} onBuy={handleBuy} buying={buying} />
                ))}
              </div>

              {error && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12,
                    color: "#DC2626",
                    background: "#FEF2F2",
                    border: "1px solid #FCA5A5",
                    borderRadius: 8,
                    padding: "8px 12px",
                  }}
                >
                  {error}
                </div>
              )}
            </div>

            {/* Transaction history */}
            {recent.length > 0 && (
              <div>
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#6B7280",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    marginBottom: 8,
                  }}
                >
                  Recent Activity
                </div>
                <div>
                  {recent.map((tx) => (
                    <TxRow key={tx.id} tx={tx} />
                  ))}
                </div>
              </div>
            )}

            {balance && recent.length === 0 && (
              <div
                style={{
                  textAlign: "center",
                  padding: "16px 0 4px",
                  fontSize: 13,
                  color: "#9CA3AF",
                }}
              >
                No transactions yet.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

