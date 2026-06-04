"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
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
  const { userId, isSignedIn, isLoading, user } = useDevUser();

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
        {isLoading ? null : isSignedIn ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {user.imageUrl && (
              <img src={user.imageUrl} alt={user.fullName} style={{ width: 28, height: 28, borderRadius: "50%", objectFit: "cover" }} />
            )}
            <span style={{ fontSize: 13, color: "#374151", fontWeight: 500 }}>{user.fullName}</span>
            <button
              onClick={() => signOut({ callbackUrl: "/" })}
              style={{ fontSize: 12, color: "#6B7280", background: "none", border: "none", cursor: "pointer", padding: "2px 8px" }}
            >Sign out</button>
          </div>
        ) : (
          <button
            onClick={() => signIn("google", { callbackUrl: "/" })}
            style={{
              display: "flex", alignItems: "center", gap: 7,
              fontSize: 13, fontWeight: 500, color: "#374151",
              padding: "6px 14px", borderRadius: 8,
              border: "1px solid #E5E7EB", background: "#fff",
              textDecoration: "none", cursor: "pointer",
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Sign in with Google
          </button>
        )}
      </nav>
    </header>
  );
}
