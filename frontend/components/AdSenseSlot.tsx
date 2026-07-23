"use client";

import Script from "next/script";
import { useEffect } from "react";

declare global {
  interface Window {
    adsbygoogle?: Record<string, unknown>[];
  }
}

type AdSenseSlotProps = {
  slot?: string;
  label?: string;
  minHeight?: number;
};

const ADSENSE_CLIENT = process.env.NEXT_PUBLIC_ADSENSE_CLIENT || "ca-pub-3644250649570397";

export default function AdSenseSlot({ slot, label = "Advertisement", minHeight = 96 }: AdSenseSlotProps) {
  const enabled = Boolean(ADSENSE_CLIENT && slot);

  useEffect(() => {
    if (!enabled) return;
    try {
      window.adsbygoogle = window.adsbygoogle || [];
      window.adsbygoogle.push({});
    } catch {
      // Ad blockers, policy review, and unfilled inventory should not break Astra.
    }
  }, [enabled, slot]);

  if (!enabled) return null;

  return (
    <section
      aria-label={label}
      style={{
        background: "rgb(10,13,23)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 12,
        padding: "10px 12px 12px",
        minHeight,
        overflow: "hidden",
      }}
    >
      <Script
        async
        src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
        crossOrigin="anonymous"
        strategy="afterInteractive"
      />
      <div style={{ marginBottom: 8, fontSize: 10, letterSpacing: "0.08em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase" }}>
        {label}
      </div>
      <ins
        className="adsbygoogle"
        style={{ display: "block", minHeight }}
        data-ad-client={ADSENSE_CLIENT}
        data-ad-slot={slot}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </section>
  );
}
