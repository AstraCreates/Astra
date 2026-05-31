"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton, useUser } from "@clerk/nextjs";
import ThemeToggle from "@/components/ThemeToggle";

function TeamBadge() {
  const { user, isLoaded } = useUser();
  const [teamName, setTeamName] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded || !user) return;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    fetch(`${apiBase}/api/teams/me?founder_id=${encodeURIComponent(user.id)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.teams?.[0]?.name) setTeamName(data.teams[0].name);
      })
      .catch(() => {});
  }, [isLoaded, user]);

  if (!teamName) return null;
  return (
    <span
      style={{
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 20,
        background: "rgba(99,102,241,0.18)",
        color: "var(--color-accent, #818cf8)",
        border: "1px solid rgba(99,102,241,0.28)",
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
  if (pathname === "/" || pathname === "/onboarding" || pathname === "/settings" || pathname === "/integrations" || pathname === "/payments" || pathname === "/brain" || pathname.startsWith("/dashboard") || pathname.startsWith("/admin")) return null;

  return (
    <header className="site-nav">
      <Link href="/" className="site-brand" aria-label="Astra home">
        <span className="site-brand-mark" aria-hidden="true" />
        <span style={{ letterSpacing: "0.18em", fontSize: 13, textTransform: "uppercase" }}>Astra</span>
      </Link>

      <nav className="site-nav-links" aria-label="Primary">
        <a href="https://astracreates.com">About</a>

        <Show when="signed-in">
          <TeamBadge />
          <Link href="/?new=1" className="site-btn site-btn-primary">
            New goal <span aria-hidden="true">→</span>
          </Link>
          <UserButton
            appearance={{
              elements: { avatarBox: "w-8 h-8 rounded-full ring-1 ring-[rgba(0,0,0,0.12)]" },
            }}
          />
        </Show>

        <Show when="signed-out">
          <SignInButton mode="modal">
            <button className="site-btn site-btn-ghost px-4">Sign in</button>
          </SignInButton>
          <SignUpButton mode="modal">
            <button className="site-btn site-btn-primary px-4">
              Get started <span aria-hidden="true">→</span>
            </button>
          </SignUpButton>
        </Show>

        <ThemeToggle />
      </nav>
    </header>
  );
}
