"use client";

import { useEffect, useSyncExternalStore } from "react";

type Theme = "dark" | "light";

const THEME_KEY = "astra-theme";
const THEME_EVENT = "astra:theme-change";

function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getThemeSnapshot(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "dark" || stored === "light" ? stored : getSystemTheme();
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

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <button
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--line)",
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        height: 34,
        padding: "0 12px",
        borderRadius: 999,
        flexShrink: 0,
        color: "var(--text-2)",
        fontSize: 12,
        lineHeight: 1,
        transition: "color 0.15s, background 0.15s, border-color 0.15s, transform 0.15s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--bg-sunken)"; (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "var(--bg-surface)"; (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
    >
      <span aria-hidden="true" style={{ fontSize: 13 }}>{dark ? "☾" : "☼"}</span>
      <span>{dark ? "Dark" : "Light"}</span>
    </button>
  );
}
