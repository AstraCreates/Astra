"use client";

import { useSyncExternalStore } from "react";
import { isBetaGateBlocked, subscribeBetaGate } from "@/lib/api";

export default function BetaGateOverlay() {
  const blocked = useSyncExternalStore(subscribeBetaGate, isBetaGateBlocked, () => false);
  if (!blocked) return null;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "var(--bg)", display: "grid", placeItems: "center",
        padding: 24, textAlign: "center",
      }}
    >
      <div style={{ display: "grid", gap: 14, maxWidth: 420 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>
          You&apos;re on the waitlist
        </div>
        <p style={{ color: "var(--fd)", fontSize: 13, lineHeight: 1.6, margin: 0 }}>
          Astra is currently invite-only for testers. We&apos;ll email you as soon
          as your access is ready.
        </p>
        <a
          href="https://astracreates.com/waitlist"
          style={{ color: "var(--blue)", fontSize: 13, fontWeight: 500 }}
        >
          Back to astracreates.com →
        </a>
      </div>
    </div>
  );
}
