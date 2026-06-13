"use client";

interface Config {
  value?: string | number;
  unit?: string;
  label?: string;
  trend?: string;
  trend_up?: boolean;
  color?: string;
}

export default function MetricTile({ config }: { config: Config }) {
  const { value = "—", unit = "", label = "", trend, trend_up } = config;
  const trendColor = trend_up === true ? "var(--green)" : trend_up === false ? "var(--red)" : "var(--fm)";

  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        {unit && (
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--fm)" }}>{unit}</span>
        )}
        <span style={{ fontSize: 32, fontWeight: 700, color: "var(--fg)", lineHeight: 1, letterSpacing: "-0.02em" }}>
          {String(value)}
        </span>
      </div>
      {label && (
        <div style={{ fontSize: 12, color: "var(--fm)" }}>{label}</div>
      )}
      {trend && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: trendColor }}>
            {trend_up === true ? "▲" : trend_up === false ? "▼" : ""} {trend}
          </span>
        </div>
      )}
    </div>
  );
}
