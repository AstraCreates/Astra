"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SignInButton, SignUpButton, UserButton, useUser } from "@clerk/nextjs";
import type { ReactNode } from "react";

function NavLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  const pathname = usePathname();
  const isActive = href === "/" ? pathname === "/" : href.startsWith("/") ? pathname === href.split("#")[0] : false;
  return (
    <Link href={href} className={`${className} ${isActive ? "active" : ""}`.trim()}>
      {children}
    </Link>
  );
}

export default function SiteNav() {
  const { isSignedIn, isLoaded } = useUser();

  return (
    <header className="site-nav">
      <Link href="/" className="site-brand" aria-label="Astra home">
        <span className="site-brand-mark" aria-hidden="true" />
        <span style={{ letterSpacing: "0.18em", fontSize: 13, textTransform: "uppercase" }}>Astra</span>
      </Link>

      <nav className="site-nav-links" aria-label="Primary">
        <NavLink href="/">Home</NavLink>
        {isSignedIn && <NavLink href="/dashboard">Dashboard</NavLink>}
        <NavLink href="/setup">Setup</NavLink>

        {!isLoaded ? null : isSignedIn ? (
          <>
            <NavLink href="/" className="site-btn site-btn-primary">
              New goal <span aria-hidden="true">→</span>
            </NavLink>
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "w-8 h-8 rounded-full ring-1 ring-[rgba(255,255,255,0.15)]",
                },
              }}
            />
          </>
        ) : (
          <>
            <SignInButton mode="modal">
              <button className="site-btn site-btn-ghost px-4">Sign in</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="site-btn site-btn-primary px-4">
                Get started <span aria-hidden="true">→</span>
              </button>
            </SignUpButton>
          </>
        )}
      </nav>
    </header>
  );
}
