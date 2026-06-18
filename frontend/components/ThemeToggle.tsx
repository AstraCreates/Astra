"use client";

import { useEffect, useSyncExternalStore } from "react";

type Theme = "dark" | "light";

const THEME_KEY = "astra-theme";
const THEME_EVENT = "astra:theme-change";

function getThemeSnapshot(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "dark" || stored === "light" ? stored : "light";
}

function subscribeTheme(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  window.addEventListener(THEME_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(THEME_EVENT, callback);
  };
}

function setTheme(theme: Theme): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(THEME_KEY, theme);
  document.documentElement.setAttribute("data-theme", theme);
  window.dispatchEvent(new Event(THEME_EVENT));
}

export default function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot, () => "dark");
  const dark = theme === "dark";
  const nextLabel = dark ? "Light mode" : "Dark mode";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <button
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      style={{
        background: "linear-gradient(135deg, var(--surface), var(--s2))",
        border: "1px solid var(--bd2)",
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        justifyContent: "space-between",
        minWidth: 126,
        height: 38,
        padding: "0 8px 0 12px",
        borderRadius: 999,
        flexShrink: 0,
        color: "var(--fd)",
        fontSize: 12,
        lineHeight: 1,
        backdropFilter: "var(--glass-blur)",
        boxShadow: "var(--card-shadow)",
        transition: "color 0.15s, background 0.15s, border-color 0.15s, transform 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--bb)";
        (e.currentTarget as HTMLElement).style.color = "var(--fg)";
        (e.currentTarget as HTMLElement).style.boxShadow = "var(--card-shadow-hover)";
        (e.currentTarget as HTMLElement).style.transform = "translateY(-1px)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--bd2)";
        (e.currentTarget as HTMLElement).style.color = "var(--fd)";
        (e.currentTarget as HTMLElement).style.boxShadow = "var(--card-shadow)";
        (e.currentTarget as HTMLElement).style.transform = "translateY(0)";
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span aria-hidden="true" style={{ fontSize: 13 }}>{dark ? "☾" : "☼"}</span>
        <span>{dark ? "Dark" : "Light"}</span>
      </span>
      <span
        aria-hidden="true"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          minWidth: 26,
          height: 26,
          borderRadius: 999,
          background: "var(--blue)",
          color: "#fff",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: ".04em",
          boxShadow: "0 8px 18px rgba(0,46,255,0.22)",
        }}
      >
        {nextLabel.slice(0, 1)}
      </span>
    </button>
  );
}
