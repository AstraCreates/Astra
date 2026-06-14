"use client";

/* "Live" panel — shows that the company keeps running after the build: each shipped
   artifact's current health, 7-day uptime, and what Astra auto-fixed. Polls the
   monitoring endpoint. Self-contained; safe to drop anywhere inside CompanyProvider. */

import { useEffect, useState } from "react";
import { useCompany } from "@/lib/company-context";
import { apiFetch } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Mon = {
  artifacts: { artifact_key: string; status: string; checked_at?: string; uptime_7d?: number }[];
  recent_heals: { artifact_key: string; at?: string; agent?: string; reason?: string }[];
};

const DOT: Record<string, string> = { up: "#3D9E5F", down: "#C0392B", stale: "#D89614", unknown: "rgba(176,180,186,0.4)" };

export default function LiveStatusPanel() {
  const { founderId, companyId } = useCompany();
  const [mon, setMon] = useState<Mon | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await apiFetch(`${API}/api/company/${companyId || founderId}/monitoring`);
        if (!res.ok) return;
        const data = await res.json();
        if (alive) setMon(data);
      } catch { /* best-effort */ }
    };
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [founderId, companyId]);

  if (!mon || !mon.artifacts?.length) return null;

  return (
    <div style={{ border: "1px solid var(--bd, rgba(176,180,186,0.15))", borderRadius: 12, padding: "14px 16px", marginBottom: 18 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--fd)", marginBottom: 12 }}>
        Live · company runs itself
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mon.artifacts.map((a) => (
          <div key={a.artifact_key} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: 8, background: DOT[a.status] ?? DOT.unknown, flexShrink: 0 }} />
            <span style={{ color: "var(--fg)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.artifact_key}</span>
            <span style={{ color: "rgba(176,180,186,0.5)", fontSize: 10.5 }}>{a.status}</span>
            {typeof a.uptime_7d === "number" && (
              <span style={{ color: "rgba(176,180,186,0.4)", fontSize: 10.5, width: 64, textAlign: "right" }}>{a.uptime_7d}% 7d</span>
            )}
          </div>
        ))}
      </div>
      {mon.recent_heals?.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(176,180,186,0.1)" }}>
          <div style={{ fontSize: 9.5, color: "rgba(61,158,95,0.8)", marginBottom: 6 }}>Auto-fixed</div>
          {mon.recent_heals.slice(-3).reverse().map((h, i) => (
            <div key={i} style={{ fontSize: 11, color: "rgba(176,180,186,0.6)", lineHeight: 1.5 }}>
              {h.agent} re-ran <b style={{ color: "var(--fg)" }}>{h.artifact_key}</b>{h.reason ? ` — ${h.reason}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
