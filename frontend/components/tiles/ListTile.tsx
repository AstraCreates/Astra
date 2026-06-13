"use client";
import { useState } from "react";

interface Config {
  items?: string[];
  style?: "bullet" | "numbered" | "checklist";
  checked?: number[];
}

export default function ListTile({ config }: { config: Config }) {
  const { items = [], style: listStyle = "bullet", checked: initialChecked = [] } = config;
  const [checked, setChecked] = useState<Set<number>>(new Set(initialChecked));
  const visible = items.slice(0, 8);
  const overflow = items.length - 8;

  const toggle = (i: number) => {
    if (listStyle !== "checklist") return;
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 5 }}>
        {visible.map((item, i) => (
          <li
            key={i}
            onClick={() => toggle(i)}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 8,
              fontSize: 12,
              color: checked.has(i) ? "var(--fm)" : "var(--fg)",
              textDecoration: checked.has(i) ? "line-through" : "none",
              cursor: listStyle === "checklist" ? "pointer" : "default",
              lineHeight: 1.5,
            }}
          >
            <span style={{ flexShrink: 0, marginTop: 1, fontSize: 11, color: "var(--fm)" }}>
              {listStyle === "numbered" ? `${i + 1}.` : listStyle === "checklist" ? (checked.has(i) ? "✓" : "○") : "•"}
            </span>
            {item}
          </li>
        ))}
      </ol>
      {overflow > 0 && (
        <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 6 }}>
          + {overflow} more
        </div>
      )}
    </div>
  );
}
