"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { desktopDownloadHref } from "@/lib/desktop-download";
import {
  LayoutDashboard,
  ListChecks,
  Send,
  Globe,
  BookOpen,
  Plug,
  Zap,
  CreditCard,
  Download,
  type LucideIcon,
} from "lucide-react";

const LINKS: { href: string; Icon: LucideIcon; label: string; match: (p: string) => boolean }[] = [
  { href: "/dashboard",    Icon: LayoutDashboard, label: "Dashboard",     match: (p) => p.startsWith("/dashboard") },
  { href: "/goals",        Icon: ListChecks,       label: "Checklist",     match: (p) => p.startsWith("/goals") },
  { href: "/outreach",     Icon: Send,             label: "Outreach",      match: (p) => p.startsWith("/outreach") },
  { href: "/brain",        Icon: Globe,            label: "Company Brain", match: (p) => p.startsWith("/brain") },
  { href: "/library",      Icon: BookOpen,         label: "Library",       match: (p) => p.startsWith("/library") || p.startsWith("/funding") },
  { href: "/integrations", Icon: Plug,             label: "Integrations",  match: (p) => p.startsWith("/integrations") },
  { href: "/automations",  Icon: Zap,              label: "Automations",   match: (p) => p.startsWith("/automations") || p.startsWith("/agents") },
  { href: "/payments",     Icon: CreditCard,       label: "Payments",      match: (p) => p.startsWith("/payments") },
];

function initials(id: string) {
  return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase();
}

const ACCENT = "#7CFFC6";
const HG = "var(--font-hanken), 'Hanken Grotesk', sans-serif";

export default function RedesignSidebar({ mobile = false, open = false, onClose }: { mobile?: boolean; open?: boolean; onClose?: () => void } = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const [credits, setCredits] = useState<number | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
    const stored = localStorage.getItem("astra_credits");
    if (stored) setCredits(parseInt(stored, 10));
  }, []);

  const sidebarStyle: React.CSSProperties = mobile
    ? {
        width: 214, maxWidth: "82vw", display: "flex", flexDirection: "column",
        background: "#080A12", borderRight: "1px solid rgba(255,255,255,.07)",
        height: "100dvh", boxShadow: "0 30px 70px -30px rgba(0,0,0,.6)",
        position: "fixed", top: 0, left: 0, zIndex: 60,
        transform: open ? "translateX(0)" : "translateX(-104%)",
        transition: "transform 0.28s cubic-bezier(0.22, 1, 0.36, 1)",
        fontFamily: HG,
      }
    : {
        width: 214, flexShrink: 0, display: "flex", flexDirection: "column",
        background: "#080A12", borderRight: "1px solid rgba(255,255,255,.07)",
        height: "100vh", position: "sticky", top: 0, fontFamily: HG,
      };

  const displayName = hydrated
    ? (isSignedIn ? (user?.fullName || userId.replace(/^user_/, "").slice(0, 14)) : userId.replace(/^user_/, "").slice(0, 14))
    : "Astra";
  const userInitials = hydrated ? initials(isSignedIn ? (user?.fullName || userId) : userId) : "AN";

  return (
    <nav
      onClick={(e) => { if (mobile && (e.target as HTMLElement).closest("a")) onClose?.(); }}
      style={sidebarStyle}
    >
      {/* Logo + status */}
      <div style={{ padding: "20px 16px 16px", display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{
          width: 24, height: 24, background: "#002EFF", flexShrink: 0,
          WebkitMask: "url('/logo.png') center/contain no-repeat",
          mask: "url('/logo.png') center/contain no-repeat",
        }} />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".1em", color: "#EDF1FB" }}>ASTRA</span>
          <span style={{ fontSize: 10, letterSpacing: ".08em", color: "#8A93AD", marginTop: 5, display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: ACCENT, flexShrink: 0, animation: "pulseDot 2.6s infinite" }} />
            Ready
          </span>
        </div>
      </div>

      {/* New run button */}
      <div style={{ padding: "0 16px 16px" }}>
        <Link
          href="/dashboard?new=1"
          onClick={(e) => { e.preventDefault(); window.location.assign("/dashboard?new=1"); }}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            width: "100%", background: "#002EFF", color: "#fff", borderRadius: 8,
            padding: "11px 0", fontWeight: 600, fontSize: 13, textDecoration: "none",
            fontFamily: HG,
          }}
        >
          + New run
        </Link>
      </div>

      {/* Nav links */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 10px", flex: 1, overflowY: "auto" }}>
        {LINKS.map((l) => {
          const active = l.match(pathname);
          return (
            <Link
              key={l.href}
              href={l.href}
              prefetch={["automations", "dashboard"].some(s => l.href.includes(s)) ? false : undefined}
              onClick={l.href === "/dashboard" ? (e) => { e.preventDefault(); window.location.assign("/dashboard"); } : undefined}
              style={{
                display: "flex", alignItems: "center", gap: 11,
                padding: "9px 11px", borderRadius: 7, textDecoration: "none",
                fontWeight: active ? 600 : 500, fontSize: 13,
                color: active ? "#EDF1FB" : "#8A93AD",
                background: active ? "rgba(255,255,255,.06)" : "transparent",
                borderLeft: `2px solid ${active ? ACCENT : "transparent"}`,
                fontFamily: HG,
              }}
            >
              <l.Icon size={16} strokeWidth={1.8} style={{ flexShrink: 0 }} />
              {l.label}
            </Link>
          );
        })}
      </div>

      {/* Bottom */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px", borderTop: "1px solid rgba(255,255,255,.07)" }}>
        <a
          href={desktopDownloadHref}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
            width: "100%", background: "transparent", color: "#c3cbe0",
            border: "1px solid rgba(255,255,255,.13)", borderRadius: 8,
            padding: 10, fontSize: 12.5, fontWeight: 500, textDecoration: "none",
            fontFamily: HG, cursor: "pointer",
          }}
        >
          <Download size={13} strokeWidth={2.2} />
          Download macOS
        </a>

        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "9px 12px", border: "1px solid rgba(255,255,255,.10)",
          borderRadius: 8, background: "rgba(255,255,255,.03)",
        }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#EDF1FB" }}>
            {credits !== null ? credits.toLocaleString() : "4,993,690"}
          </span>
          <span style={{ fontSize: 10, letterSpacing: ".04em", color: "#6f7b98" }}>credits</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,.07)" }}>
          <div style={{
            width: 28, height: 28, borderRadius: "50%", background: "#1c2536",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 11, fontWeight: 700, color: "#EDF1FB", flexShrink: 0,
          }}>
            {userInitials}
          </div>
          <div style={{ lineHeight: 1.3, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "#EDF1FB", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {displayName}
            </div>
            <div style={{ fontSize: 10, color: "#6f7b98" }}>
              <Link href="/settings" style={{ color: "#6f7b98", textDecoration: "none" }}>Settings</Link>
              {" · "}
              {hydrated && isSignedIn
                ? <button onClick={() => { localStorage.removeItem("astra_remember_me"); signOut({ callbackUrl: "/" }); }} style={{ background: "none", border: "none", fontSize: 10, color: "#6f7b98", cursor: "pointer", padding: 0, fontFamily: HG }}>Sign out</button>
                : <button onClick={() => signIn("google", { callbackUrl: "/" })} style={{ background: "none", border: "none", fontSize: 10, color: ACCENT, cursor: "pointer", padding: 0, fontFamily: HG, fontWeight: 600 }}>Sign in</button>
              }
            </div>
          </div>
        </div>
      </div>

      <style>{`@keyframes pulseDot{0%,100%{opacity:1}50%{opacity:.35}}`}</style>
    </nav>
  );
}
