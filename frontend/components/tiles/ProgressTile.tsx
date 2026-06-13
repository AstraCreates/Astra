"use client";

interface Config {
  value?: number;
  max?: number;
  label?: string;
  color?: string;
  show_percent?: boolean;
}

export default function ProgressTile({ config }: { config: Config }) {
  const { value = 0, max = 100, label = "", color = "var(--blue)", show_percent = true } = config;
  const pct = max > 0 ? Math.min(100, Math.round((Number(value) / Number(max)) * 100)) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={{ fontSize: 13, color: "var(--fg)", fontWeight: 500 }}>{label}</span>
        {show_percent && (
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{pct}%</span>
        )}
      </div>
      <div
        style={{
          height: 8,
          borderRadius: 4,
          background: "var(--bd)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: 4,
            background: color,
            transition: "width 0.4s ease",
          }}
        />
      </div>
      <div style={{ fontSize: 11, color: "var(--fm)" }}>
        {String(value)} / {String(max)}
      </div>
    </div>
  );
}
