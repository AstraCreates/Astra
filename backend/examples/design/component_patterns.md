---
title: React Component Patterns — Design System Consistency
tags: [design, react, components, css, tailwind, patterns]
category: design
applies_to: [design, technical, technical_scaffold, web]
---

# React Component Patterns

## Button variants (using CSS custom properties)
```typescript
// Matches Astra's design system pattern
export function Button({
  children, variant = "primary", size = "md", onClick, disabled, type = "button",
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const base = "inline-flex items-center justify-center rounded-lg font-medium transition-all focus:outline-none focus-visible:ring-2";
  const variants = {
    primary:   "bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-500",
    secondary: "bg-transparent border border-gray-300 text-gray-700 hover:bg-gray-50",
    danger:    "bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-500",
    ghost:     "bg-transparent text-gray-600 hover:bg-gray-100",
  };
  const sizes = { sm: "px-3 py-1.5 text-sm", md: "px-4 py-2 text-sm", lg: "px-6 py-3 text-base" };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variants[variant]} ${sizes[size]} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      {children}
    </button>
  );
}
```

## Loading state pattern
```typescript
"use client";
import { useState } from "react";

export function AsyncButton({ children, action }: { children: React.ReactNode; action: () => Promise<void> }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button onClick={handleClick} disabled={loading}>
        {loading ? "Loading…" : children}
      </button>
      {error && <p style={{ color: "red", fontSize: 12 }}>{error}</p>}
    </div>
  );
}
```

## Empty state
```typescript
export function EmptyState({ title, description, action }: {
  title: string; description?: string; action?: { label: string; onClick: () => void };
}) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px" }}>
      <p style={{ fontSize: 16, fontWeight: 600, color: "var(--fg)" }}>{title}</p>
      {description && <p style={{ fontSize: 14, color: "var(--fm)", marginTop: 8 }}>{description}</p>}
      {action && (
        <button onClick={action.onClick} style={{ marginTop: 16 }} className="btn pri">
          {action.label}
        </button>
      )}
    </div>
  );
}
```

## Modal / dialog
```typescript
"use client";
import { useEffect } from "react";

export function Modal({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!open) return null;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onClose}>
      <div style={{ background: "var(--bg)", borderRadius: 12, padding: 24, maxWidth: 480, width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}
        onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{title}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "var(--fm)" }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}
```

## Design system CSS variables (put in globals.css)
```css
:root {
  --fg: #0f172a;     /* primary text */
  --fm: #64748b;     /* muted text */
  --bg: #ffffff;     /* page background */
  --s2: #f8fafc;     /* surface 2 (cards) */
  --bd: #e2e8f0;     /* border */
  --blue: #2563eb;
  --mint: #10b981;
  --red: #ef4444;
  --line: #e2e8f0;
}

@media (prefers-color-scheme: dark) {
  :root {
    --fg: #f1f5f9;
    --fm: #94a3b8;
    --bg: #0f172a;
    --s2: #1e293b;
    --bd: #334155;
    --line: #334155;
  }
}
```

## Notes
- Every button/link must be wired to a real route or handler — no dead UI
- Use `var(--fg)` / `var(--fm)` / `var(--bg)` etc. for theme compatibility
- Always add `:focus-visible` ring for keyboard accessibility
- Loading state on all async actions — never leave user wondering
