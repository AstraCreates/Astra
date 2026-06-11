"use client";

/* Shared redesign sidebar — one consistent shell across every app page. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import { useDevUser } from "@/lib/use-dev-user";
import CreditsDisplay from "@/components/CreditsDisplay";
import NotificationBell from "@/components/NotificationBell";
import { useEffect, useState } from "react";

const LINKS: { href: string; ic: string; label: string; match: (p: string) => boolean }[] = [
  { href: "/", ic: "⬡", label: "Dashboard", match: (p) => p === "/" },
  { href: "/goals", ic: "◎", label: "Checklist", match: (p) => p.startsWith("/goals") },
  { href: "/outreach", ic: "✦", label: "Outreach", match: (p) => p.startsWith("/outreach") },
  { href: "/brain", ic: "◈", label: "Company Brain", match: (p) => p.startsWith("/brain") },
  { href: "/integrations", ic: "⌘", label: "Integrations", match: (p) => p.startsWith("/integrations") },
  { href: "/payments", ic: "$", label: "Payments", match: (p) => p.startsWith("/payments") },
];

function initials(id: string) { return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase(); }

export default function RedesignSidebar({ mobile = false, open = false, onClose }: { mobile?: boolean; open?: boolean; onClose?: () => void } = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const [companyName, setCompanyName] = useState("");
  useEffect(() => {
    setCompanyName(localStorage.getItem("astra_onboarding_company") || "");
  }, []);

  // On mobile the sidebar is an off-canvas drawer (fixed, slides in over content);
  // on desktop it's the usual sticky in-flow column.
  const navStyle: React.CSSProperties = mobile
    ? { width: 240, maxWidth: "82vw", display: "flex", flexDirection: "column", background: "rgba(255,255,255,0.12)", borderRight: "1px solid rgba(255,255,255,0.65)", height: "100dvh", boxShadow: "inset -1px 0 0 rgba(255,255,255,0.5), 4px 0 40px rgba(0,0,0,0.08)", position: "fixed", top: 0, left: 0, zIndex: 60, transform: open ? "translateX(0)" : "translateX(-104%)", transition: "transform 0.28s cubic-bezier(0.22, 1, 0.36, 1)", backdropFilter: "blur(20px) saturate(1.8)", WebkitBackdropFilter: "blur(20px) saturate(1.8)" }
    : { width: 210, flexShrink: 0, display: "flex", flexDirection: "column", background: "rgba(255,255,255,0.12)", borderRight: "1px solid rgba(255,255,255,0.65)", height: "100vh", boxShadow: "inset -1px 0 0 rgba(255,255,255,0.5), 4px 0 40px rgba(0,0,0,0.08)", position: "sticky", top: 0, zIndex: 3, backdropFilter: "blur(20px) saturate(1.8)", WebkitBackdropFilter: "blur(20px) saturate(1.8)" };

  // Close the drawer after any in-drawer navigation on mobile.
  const closeOnNav = mobile ? onClose : undefined;

  return (
    <nav onClick={(e) => { if (mobile && (e.target as HTMLElement).closest("a")) closeOnNav?.(); }} style={navStyle}>
      <div style={{ padding: "20px 16px 16px", borderBottom: "1px solid var(--bd)" }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, textDecoration: "none" }}>
          <div style={{ width: 28, height: 28, background: "var(--blue)", flexShrink: 0, WebkitMask: "url('/logo.png') center/contain no-repeat", mask: "url('/logo.png') center/contain no-repeat" }} />
          <div>
            <div className="nav-wordmark">Astra</div>
            <div style={{ fontSize: 9, color: "var(--blue)", letterSpacing: ".06em", textTransform: "uppercase" }}>ready</div>
          </div>
        </Link>
        {companyName && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 8px", marginBottom: 8, background: "var(--s2)", border: "1px solid var(--bd)" }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)", flexShrink: 0 }} />
            <span style={{ fontSize: 10.5, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{companyName}</span>
          </div>
        )}
        <NotificationBell />
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 2 }}>
          <Link data-tour="new-goal-btn" href="/?new=1" className="btn" style={{ display: "flex", justifyContent: "center", gap: 7, textDecoration: "none" }}>＋ New run</Link>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 1, padding: "10px 8px", flex: 1, overflowY: "auto" }}>
        {LINKS.map((l) => (
          l.href === "/" ? (
            // Dashboard: hard-navigate to the clean site root so it ALWAYS resets to
            // the dashboard (a Next <Link href="/"> from /?session=x stays put).
            <Link key={l.href} href="/" data-tour="nav-dashboard"
               onClick={(e) => { e.preventDefault(); window.location.assign("/"); }}
               className={`nl${l.match(pathname) ? " on" : ""}`} style={{ textDecoration: "none" }}>
              <span style={{ width: 18, textAlign: "center" }}>{l.ic}</span>{l.label}
            </Link>
          ) : (
            <Link key={l.href} href={l.href} data-tour={`nav-${l.label.toLowerCase().replace(/\s+/g, "-")}`} className={`nl${l.match(pathname) ? " on" : ""}`} style={{ textDecoration: "none" }}>
              <span style={{ width: 18, textAlign: "center" }}>{l.ic}</span>{l.label}
            </Link>
          )
        ))}
      </div>

      <div style={{ height: 1, background: "var(--bd)", margin: "6px 8px" }} />
      <div style={{ padding: "6px 12px 10px", display: "flex", justifyContent: "center" }}><CreditsDisplay /></div>
      <div style={{ padding: "0 8px 14px", display: "flex", flexDirection: "column", gap: 1 }}>
        <Link href="/settings" className={`nl${pathname.startsWith("/settings") ? " on" : ""}`} style={{ textDecoration: "none" }}><span style={{ width: 18, textAlign: "center" }}>⚙</span>Settings</Link>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
          <div style={{ width: 24, height: 24, background: isSignedIn ? "var(--green)" : "var(--blue)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-chakra)", fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{initials(userId)}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 9, color: "var(--fm)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {isSignedIn ? (user.fullName || userId) : `${userId.replace(/^user_/, "").slice(0, 12)}…`}
            </div>
          </div>
          {isSignedIn
            ? <button onClick={() => signOut({ callbackUrl: "/" })} style={{ background: "none", border: "none", fontSize: 9, color: "var(--fm)", cursor: "pointer", fontFamily: "var(--font-code)" }}>sign out</button>
            : <button onClick={() => signIn("google", { callbackUrl: "/" })} style={{ background: "none", border: "none", fontSize: 9, color: "var(--blue)", cursor: "pointer", fontFamily: "var(--font-code)" }}>sign in</button>}
        </div>
      </div>
    </nav>
  );
}
