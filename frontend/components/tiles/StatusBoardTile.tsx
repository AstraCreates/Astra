"use client";

type StatusValue = "ok" | "warn" | "error" | "pending";

interface Indicator {
  label?: string;
  status?: StatusValue;
  detail?: string;
  url?: string;
}

interface Config {
  indicators?: Indicator[];
}

const STATUS_COLORS: Record<StatusValue, string> = {
  ok: "var(--green)",
  warn: "var(--amber)",
  error: "var(--red)",
  pending: "var(--blue)",
};

const STATUS_LABELS: Record<StatusValue, string> = {
  ok: "OK",
  warn: "Warning",
  error: "Error",
  pending: "Pending",
};

export default function StatusBoardTile({ config }: { config: Config }) {
  const { indicators = [] } = config;

  if (!indicators.length) {
    return <div style={{ fontSize: 12, color: "var(--fm)", paddingTop: 8 }}>No indicators.</div>;
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
      {indicators.map((ind, i) => {
        const st = (ind.status ?? "pending") as StatusValue;
        const color = STATUS_COLORS[st] ?? "var(--fm)";
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "5px 0",
              borderBottom: i < indicators.length - 1 ? "1px solid var(--bd)" : "none",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: color,
                flexShrink: 0,
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, color: "var(--fg)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {ind.url ? (
                  <a href={ind.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "underline" }}>
                    {ind.label ?? "—"}
                  </a>
                ) : (ind.label ?? "—")}
              </div>
              {ind.detail && (
                <div style={{ fontSize: 11, color: "var(--fm)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {ind.detail}
                </div>
              )}
            </div>
            <span style={{ fontSize: 10, fontWeight: 600, color, flexShrink: 0 }}>
              {STATUS_LABELS[st]}
            </span>
          </div>
        );
      })}
    </div>
  );
}
