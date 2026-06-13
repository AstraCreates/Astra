"use client";
import { useRouter } from "next/navigation";

interface Config {
  label?: string;
  action?: "new_goal" | "open_url";
  payload?: Record<string, unknown>;
  variant?: "primary" | "secondary" | "danger";
  icon?: string;
  description?: string;
}

export default function ButtonTile({ config }: { config: Config }) {
  const router = useRouter();
  const { label = "Action", action, payload = {}, variant = "primary", icon, description } = config;

  const handleClick = () => {
    if (action === "new_goal") {
      const instruction = String(payload.instruction ?? "");
      if (instruction) {
        try { sessionStorage.setItem("astra_prefill_goal", instruction); } catch {}
      }
      router.push("/?new=1");
    } else if (action === "open_url") {
      const url = String(payload.url ?? "");
      if (/^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener,noreferrer");
    }
  };

  const isPrimary = variant === "primary";
  const isDanger = variant === "danger";

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        textAlign: "center",
      }}
    >
      {icon && (
        <div style={{ fontSize: 28, lineHeight: 1 }}>{icon}</div>
      )}
      <button
        onClick={handleClick}
        style={{
          padding: "10px 20px",
          borderRadius: 8,
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          border: isPrimary ? "none" : isDanger ? "1px solid var(--red)" : "1px solid var(--bd2)",
          background: isPrimary ? "var(--blue)" : isDanger ? "transparent" : "transparent",
          color: isPrimary ? "#fff" : isDanger ? "var(--red)" : "var(--fg)",
          letterSpacing: "0.01em",
          transition: "opacity 0.15s",
          fontFamily: "inherit",
        }}
        onMouseEnter={e => { e.currentTarget.style.opacity = "0.82"; }}
        onMouseLeave={e => { e.currentTarget.style.opacity = "1"; }}
      >
        {label}
      </button>
      {description && (
        <div style={{ fontSize: 11, color: "var(--fm)", maxWidth: 220, lineHeight: 1.5 }}>
          {description}
        </div>
      )}
    </div>
  );
}
