"use client";
import { useEffect, useRef, useState } from "react";
import { refreshElement } from "@/lib/dashboard-api";
import type { DashboardElement } from "@/lib/dashboard-api";

interface StatusInfo {
  label?: string;
  status?: string;
  fields?: Record<string, unknown>;
  last_updated?: string;
  error?: string;
}

interface Config {
  session_id?: string;
  poll_url?: string;
  status_map?: Record<string, string>;
  fields?: string[];
  // Initial display values (may be overlaid by live data)
  label?: string;
  status?: string;
}

const STATUS_COLORS: Record<string, string> = {
  ok: "var(--green)",
  running: "var(--blue)",
  done: "var(--green)",
  error: "var(--red)",
  warn: "var(--amber)",
  pending: "var(--fm)",
  stalled: "var(--amber)",
  killed: "var(--red)",
};

export default function MonitorTile({ element }: { element: DashboardElement }) {
  const config = element.config as Config;
  const [info, setInfo] = useState<StatusInfo>({
    label: config.label ?? "Monitoring…",
    status: config.status ?? "pending",
  });
  const [ticking, setTicking] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = async () => {
    setTicking(true);
    try {
      if (element.data_source) {
        const updated = await refreshElement(element.founder_id, element.id);
        setInfo((prev) => ({ ...prev, ...updated, last_updated: new Date().toISOString() }));
      } else if (config.poll_url) {
        const res = await fetch(config.poll_url);
        if (res.ok) {
          const data = await res.json();
          setInfo({ ...data, last_updated: new Date().toISOString() });
        }
      }
    } catch {
      // silent — don't crash tile on network error
    } finally {
      setTicking(false);
    }
  };

  useEffect(() => {
    const interval = element.refresh_interval;
    if (interval > 0) {
      intervalRef.current = setInterval(poll, interval * 1000);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [element.id, element.refresh_interval]);

  const status = String(info.status ?? "pending").toLowerCase();
  const statusColor = (config.status_map?.[status]) ?? STATUS_COLORS[status] ?? "var(--fm)";
  const lastUpdated = info.last_updated ? new Date(info.last_updated) : null;
  const displayFields = config.fields ?? [];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: statusColor,
            flexShrink: 0,
            ...(status === "running" || ticking ? { animation: "dc-pulse 1.4s ease-in-out infinite" } : {}),
          }}
        />
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>
          {String(info.label ?? status)}
        </span>
        <span style={{ fontSize: 11, color: "var(--fm)", marginLeft: "auto", textTransform: "capitalize" }}>
          {status}
        </span>
      </div>

      {displayFields.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {displayFields.map((f) => {
            const val = (info.fields as Record<string, unknown>)?.[f] ?? (info as Record<string, unknown>)[f];
            if (val === undefined) return null;
            return (
              <div key={f} style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                <span style={{ color: "var(--fm)" }}>{f}</span>
                <span style={{ color: "var(--fd)", fontWeight: 500 }}>{String(val)}</span>
              </div>
            );
          })}
        </div>
      )}

      {lastUpdated && (
        <div style={{ fontSize: 10, color: "var(--fm)", marginTop: "auto" }}>
          Updated {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
      )}
    </div>
  );
}
