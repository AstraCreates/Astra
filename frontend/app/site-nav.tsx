"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import CreditsDisplay from "@/components/CreditsDisplay";

function TeamBadge() {
  const { userId } = useDevUser();
  const [teamName, setTeamName] = useState<string | null>(null);

  useEffect(() => {
    if (!userId || userId === "anon") return;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    fetch(`${apiBase}/api/teams/me?founder_id=${encodeURIComponent(userId)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.teams?.[0]?.name) setTeamName(data.teams[0].name);
      })
      .catch(() => {});
  }, [userId]);

  if (!teamName) return null;
  return (
    <span
      style={{
        fontSize: 11,
        padding: "2px 10px",
        borderRadius: 20,
        background: "#EFF6FF",
        color: "#2563EB",
        border: "1px solid #BFDBFE",
        letterSpacing: "0.04em",
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {teamName}
    </span>
  );
}

export default function SiteNav() {
  const pathname = usePathname();
  const { userId } = useDevUser();

  if (
    pathname === "/" ||
    pathname === "/onboarding" ||
    pathname === "/settings" ||
    pathname === "/integrations" ||
    pathname === "/payments" ||
    pathname === "/brain" ||
    pathname.startsWith("/dashboard") ||
    pathname.startsWith("/admin")
  )
    return null;

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        height: 56,
        background: "#FFFFFF",
        borderBottom: "1px solid #E5E7EB",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        paddingLeft: 24,
        paddingRight: 24,
        fontFamily: "var(--font-geist-sans), sans-serif",
      }}
    >
      {/* Brand */}
      <Link
        href="/"
        aria-label="Astra home"
        style={{
          textDecoration: "none",
          color: "#111827",
          fontWeight: 700,
          fontSize: 13,
          letterSpacing: "0.15em",
          textTransform: "uppercase",
        }}
      >
        ASTRA
      </Link>

      {/* Nav links */}
      <nav
        aria-label="Primary"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
        }}
      >
        <a
          href="https://astracreates.com"
          style={{
            textDecoration: "none",
            color: "#374151",
            fontSize: 14,
            fontWeight: 500,
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = "#111827";
            (e.currentTarget as HTMLAnchorElement).style.textDecoration = "underline";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.color = "#374151";
            (e.currentTarget as HTMLAnchorElement).style.textDecoration = "none";
          }}
        >
          About
        </a>

        <TeamBadge />
        <CreditsDisplay />
        <Link
          href="/?new=1"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            textDecoration: "none",
            background: "#2563EB",
            color: "#FFFFFF",
            fontSize: 13,
            fontWeight: 500,
            padding: "6px 16px",
            borderRadius: 9999,
            border: "none",
            cursor: "pointer",
            transition: "background 0.15s",
            lineHeight: 1,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.background = "#1D4ED8";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLAnchorElement).style.background = "#2563EB";
          }}
        >
          New goal <span aria-hidden="true">→</span>
        </Link>
        <span
          style={{
            fontSize: 12,
            color: "#6B7280",
            fontFamily: "var(--font-jetbrains-mono), monospace",
          }}
          title={userId}
        >
          Dev: {userId === "anon" ? "…" : userId.slice(0, 12)}
        </span>
      </nav>
    </header>
  );
}
