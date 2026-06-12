"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  COOKIE_NOTICE_MAX_AGE_SECONDS,
  COOKIE_NOTICE_NAME,
  COOKIE_NOTICE_VALUE,
} from "@/lib/necessary-cookies";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function writeNoticeCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = [
    `${COOKIE_NOTICE_NAME}=${encodeURIComponent(COOKIE_NOTICE_VALUE)}`,
    `Max-Age=${COOKIE_NOTICE_MAX_AGE_SECONDS}`,
    "Path=/",
    "SameSite=Lax",
    window.location.protocol === "https:" ? "Secure" : "",
  ].filter(Boolean).join("; ");
}

export default function CookieNotice() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setVisible(readCookie(COOKIE_NOTICE_NAME) !== COOKIE_NOTICE_VALUE);
    });
  }, []);

  if (!visible) return null;

  return (
    <div
      role="region"
      aria-label="Necessary cookies"
      style={{
        position: "fixed",
        left: "50%",
        bottom: 20,
        transform: "translateX(-50%)",
        zIndex: 10000,
        width: "min(720px, calc(100vw - 32px))",
        borderRadius: 28,
        border: "1px solid var(--bd2)",
        background: "var(--surface)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
        padding: "14px 16px",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, color: "var(--fg)", fontSize: 13, lineHeight: 1.45 }}>
          Astra uses necessary cookies for sign-in, security, and remembering this notice.
        </p>
        <Link href="/cookies" style={{ color: "var(--fg-dim)", fontSize: 12, textDecoration: "underline", textUnderlineOffset: 3 }}>
          View cookie details
        </Link>
      </div>
      <button
        type="button"
        className="btn pri"
        onClick={() => {
          writeNoticeCookie();
          setVisible(false);
        }}
        style={{ minHeight: 34, padding: "0 16px", fontSize: 12, flexShrink: 0 }}
      >
        OK
      </button>
    </div>
  );
}
