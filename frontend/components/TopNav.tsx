"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import CreditsDisplay from "@/components/CreditsDisplay";
import NotificationBell from "@/components/NotificationBell";
import {
  LayoutDashboard,
  ListChecks,
  Send,
  Brain,
  Plug,
  CreditCard,
  Settings,
  type LucideIcon,
} from "lucide-react";

const NAV_LINKS: { href: string; Icon: LucideIcon; label: string; match: (p: string) => boolean }[] = [
  { href: "/dashboard",    Icon: LayoutDashboard, label: "Dashboard",     match: (p) => p.startsWith("/dashboard") },
  { href: "/goals",        Icon: ListChecks,       label: "Checklist",     match: (p) => p.startsWith("/goals") },
  { href: "/outreach",     Icon: Send,             label: "Outreach",      match: (p) => p.startsWith("/outreach") },
  { href: "/brain",        Icon: Brain,            label: "Company Brain", match: (p) => p.startsWith("/brain") },
  { href: "/integrations", Icon: Plug,             label: "Integrations",  match: (p) => p.startsWith("/integrations") },
  { href: "/payments",     Icon: CreditCard,       label: "Payments",      match: (p) => p.startsWith("/payments") },
];

function initials(id: string) {
  return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase();
}

export default function TopNav({
  mobile = false,
  mobileOpen = false,
  onMobileToggle,
}: {
  mobile?: boolean;
  mobileOpen?: boolean;
  onMobileToggle?: () => void;
} = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => { setHydrated(true); }, []);

  const navBg = "#0e1117";
  const navBorder = "rgba(255,255,255,0.08)";
  const activeColor = "#4ade80";
  const mutedColor = "rgba(255,255,255,0.55)";
  const fgColor = "#f4f7ff";

  return (
    <>
      <nav style={{
        position: "fixed",
        top: 0, left: 0, right: 0,
        zIndex: 100,
        height: 48,
        background: navBg,
        borderBottom: `1px solid ${navBorder}`,
        display: "flex",
        alignItems: "center",
        padding: "0 16px",
        gap: 0,
      }}>
        {/* Logo */}
        <Link
          href="/dashboard"
          onClick={(e) => { e.preventDefault(); window.location.assign("/dashboard"); }}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            textDecoration: "none", flexShrink: 0, marginRight: 24,
          }}
        >
          <div style={{
            width: 24, height: 24, flexShrink: 0,
            background: activeColor,
            WebkitMask: "url('/logo.png') center/contain no-repeat",
            mask: "url('/logo.png') center/contain no-repeat",
          }} />
          <span style={{
            fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
            fontSize: 15, fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: fgColor,
          }}>
            ASTRA
          </span>
        </Link>

        {/* Desktop nav items */}
        {!mobile && (
          <div style={{ display: "flex", alignItems: "stretch", height: "100%", flex: 1, gap: 0 }}>
            {NAV_LINKS.map((l) => {
              const active = l.match(pathname);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  prefetch={l.href === "/automations" ? false : undefined}
                  data-tour={`nav-${l.label.toLowerCase().replace(/\s+/g, "-")}`}
                  onClick={l.href === "/dashboard" ? (e) => { e.preventDefault(); window.location.assign("/dashboard"); } : undefined}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "0 14px",
                    textDecoration: "none",
                    fontSize: 13,
                    fontWeight: active ? 600 : 500,
                    color: active ? fgColor : mutedColor,
                    fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
                    borderBottom: active ? `2px solid ${activeColor}` : "2px solid transparent",
                    transition: "color 0.14s, border-color 0.14s",
                    whiteSpace: "nowrap",
                    position: "relative",
                  }}
                  onMouseEnter={(e) => {
                    if (!active) (e.currentTarget as HTMLAnchorElement).style.color = fgColor;
                  }}
                  onMouseLeave={(e) => {
                    if (!active) (e.currentTarget as HTMLAnchorElement).style.color = mutedColor;
                  }}
                >
                  <l.Icon size={14} strokeWidth={active ? 2 : 1.75} />
                  {l.label}
                </Link>
              );
            })}
          </div>
        )}

        {/* Right side */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {/* Mobile hamburger */}
          {mobile && (
            <button
              aria-label="Open menu"
              onClick={onMobileToggle}
              style={{
                background: "none", border: "none", color: fgColor,
                fontSize: 18, cursor: "pointer", padding: "4px 6px",
                display: "flex", alignItems: "center",
              }}
            >
              ☰
            </button>
          )}

          {!mobile && (
            <>
              <NotificationBell />
              <CreditsDisplay />
              <Link
                href="/settings"
                style={{
                  display: "flex", alignItems: "center",
                  padding: "4px 6px", borderRadius: 6,
                  color: pathname.startsWith("/settings") ? fgColor : mutedColor,
                  transition: "color 0.14s",
                  textDecoration: "none",
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = fgColor; }}
                onMouseLeave={(e) => {
                  if (!pathname.startsWith("/settings"))
                    (e.currentTarget as HTMLAnchorElement).style.color = mutedColor;
                }}
              >
                <Settings size={15} strokeWidth={1.75} />
              </Link>

              {/* User avatar */}
              <div style={{
                width: 26, height: 26, borderRadius: "50%",
                background: hydrated && isSignedIn ? "var(--green)" : "var(--blue)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 9, fontWeight: 700, color: "#fff",
                fontFamily: "var(--font-instrument), sans-serif",
                cursor: "pointer", flexShrink: 0,
                title: hydrated ? (isSignedIn ? (user.fullName || userId) : userId) : "Astra user",
              }}>
                {hydrated ? initials(userId) : "AN"}
              </div>

              {hydrated && isSignedIn ? (
                <button
                  onClick={() => { localStorage.removeItem("astra_remember_me"); signOut({ callbackUrl: "/" }); }}
                  style={{
                    background: "none", border: "none",
                    fontSize: 10, color: mutedColor,
                    cursor: "pointer", padding: "2px 4px",
                    fontFamily: "var(--font-instrument), sans-serif",
                  }}
                >
                  sign out
                </button>
              ) : (
                hydrated && (
                  <button
                    onClick={() => signIn("google", { callbackUrl: "/" })}
                    style={{
                      background: "none", border: "none",
                      fontSize: 10, color: activeColor,
                      cursor: "pointer", padding: "2px 4px",
                      fontFamily: "var(--font-instrument), sans-serif",
                      fontWeight: 600,
                    }}
                  >
                    sign in
                  </button>
                )
              )}
            </>
          )}
        </div>
      </nav>

      {/* Mobile drawer */}
      {mobile && mobileOpen && (
        <div style={{
          position: "fixed", top: 48, left: 0, right: 0, bottom: 0,
          background: navBg, zIndex: 99,
          display: "flex", flexDirection: "column",
          padding: "12px 8px",
          borderTop: `1px solid ${navBorder}`,
        }}>
          {NAV_LINKS.map((l) => {
            const active = l.match(pathname);
            return (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => onMobileToggle?.()}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "12px 16px", borderRadius: 8,
                  textDecoration: "none",
                  fontSize: 14, fontWeight: active ? 600 : 500,
                  color: active ? fgColor : mutedColor,
                  background: active ? "rgba(255,255,255,0.06)" : "transparent",
                  borderLeft: active ? `3px solid ${activeColor}` : "3px solid transparent",
                  marginBottom: 2,
                }}
              >
                <l.Icon size={16} strokeWidth={active ? 2 : 1.75} />
                {l.label}
              </Link>
            );
          })}

          <div style={{ height: 1, background: navBorder, margin: "12px 8px" }} />

          <Link
            href="/settings"
            onClick={() => onMobileToggle?.()}
            style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "12px 16px", borderRadius: 8,
              textDecoration: "none",
              fontSize: 14, fontWeight: 500,
              color: pathname.startsWith("/settings") ? fgColor : mutedColor,
              background: pathname.startsWith("/settings") ? "rgba(255,255,255,0.06)" : "transparent",
            }}
          >
            <Settings size={16} strokeWidth={1.75} />
            Settings
          </Link>

          <div style={{ flex: 1 }} />
          <div style={{ padding: "8px 16px", display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%",
              background: hydrated && isSignedIn ? "var(--green)" : "var(--blue)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, fontWeight: 700, color: "#fff",
            }}>
              {hydrated ? initials(userId) : "AN"}
            </div>
            <span style={{ fontSize: 12, color: mutedColor, flex: 1 }}>
              {hydrated ? (isSignedIn ? (user.fullName || userId) : "Guest") : "Astra user"}
            </span>
            {hydrated && isSignedIn ? (
              <button
                onClick={() => { localStorage.removeItem("astra_remember_me"); signOut({ callbackUrl: "/" }); }}
                style={{ background: "none", border: "none", fontSize: 11, color: mutedColor, cursor: "pointer" }}
              >
                sign out
              </button>
            ) : (
              hydrated && (
                <button
                  onClick={() => signIn("google", { callbackUrl: "/" })}
                  style={{ background: "none", border: "none", fontSize: 11, color: activeColor, cursor: "pointer", fontWeight: 600 }}
                >
                  sign in
                </button>
              )
            )}
          </div>
        </div>
      )}
    </>
  );
}
