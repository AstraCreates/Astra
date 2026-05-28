"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import ThemeToggle from "@/components/ThemeToggle";

export default function SiteNav() {
  const pathname = usePathname();
  if (pathname === "/" || pathname === "/settings" || pathname === "/integrations" || pathname === "/brain" || pathname === "/payments" || pathname.startsWith("/dashboard") || pathname.startsWith("/admin")) return null;

  return (
    <header className="site-nav">
      <Link href="/" className="site-brand" aria-label="Astra home">
        <span className="site-brand-mark" aria-hidden="true" />
        <span style={{ letterSpacing: "0.18em", fontSize: 13, textTransform: "uppercase" }}>Astra</span>
      </Link>

      <nav className="site-nav-links" aria-label="Primary">
        <a href="https://astracreates.com">About</a>

        <Show when="signed-in">
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
