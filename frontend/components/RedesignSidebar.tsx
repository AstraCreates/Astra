"use client";

/* Shared redesign sidebar — one consistent shell across every app page. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import { useDevUser } from "@/lib/use-dev-user";
import CreditsDisplay from "@/components/CreditsDisplay";
import NotificationBell from "@/components/NotificationBell";
import ThemeToggle from "@/components/ThemeToggle";
import { desktopDownloadHref } from "@/lib/desktop-download";

const LINKS: { href: string; ic: string; label: string; match: (p: string) => boolean }[] = [
  { href: "/", ic: "⬡", label: "Dashboard", match: (p) => p === "/" },
  { href: "/goals", ic: "◎", label: "Checklist", match: (p) => p.startsWith("/goals") },
  { href: "/outreach", ic: "✦", label: "Outreach", match: (p) => p.startsWith("/outreach") },
  { href: "/brain", ic: "⌬", label: "Company Brain", match: (p) => p.startsWith("/brain") },
  { href: "/library", ic: "▤", label: "Library", match: (p) => p.startsWith("/library") || p.startsWith("/funding") },
  { href: "/agents", ic: "✺", label: "Custom Agents", match: (p) => p.startsWith("/agents") },
  { href: "/integrations", ic: "⌘", label: "Integrations", match: (p) => p.startsWith("/integrations") },
  { href: "/payments", ic: "$", label: "Payments", match: (p) => p.startsWith("/payments") },
];

function initials(id: string) { return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase(); }

export default function RedesignSidebar({ mobile = false, open = false, onClose }: { mobile?: boolean; open?: boolean; onClose?: () => void } = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const companyName = typeof window !== "undefined"
    ? localStorage.getItem("astra_onboarding_company") || ""
    : "";

  // On mobile the sidebar is an off-canvas drawer (fixed, slides in over content);
  // on desktop it's the usual sticky in-flow column.
  const navStyle: React.CSSProperties = mobile
    ? { width: 248, maxWidth: "82vw", display: "flex", flexDirection: "column", background: "var(--surface)", borderRight: "1px solid var(--bd)", height: "100dvh", boxShadow: "var(--shell-shadow)", backdropFilter: "var(--glass-blur)", position: "fixed", top: 0, left: 0, zIndex: 60, transform: open ? "translateX(0)" : "translateX(-104%)", transition: "transform 0.28s cubic-bezier(0.22, 1, 0.36, 1)" }
    : { width: 218, flexShrink: 0, display: "flex", flexDirection: "column", background: "var(--surface)", borderRight: "1px solid var(--bd)", height: "100vh", boxShadow: "var(--shell-shadow)", backdropFilter: "var(--glass-blur)", position: "sticky", top: 0 };

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
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", marginBottom: 10, background: "linear-gradient(135deg, var(--s2), transparent)", border: "1px solid var(--bd)", borderRadius: 10, backdropFilter: "var(--glass-blur)" }}>
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
      <div style={{ padding: "6px 8px 8px" }}>
        <a href={desktopDownloadHref} target="_blank" rel="noopener noreferrer" style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          padding: "9px 12px",
          fontSize: 11,
          fontWeight: 600,
          color: "var(--fg)",
          background: "linear-gradient(135deg, var(--surface), var(--s2))",
          border: "1px solid var(--bd2)",
          borderRadius: 10,
          textDecoration: "none",
          backdropFilter: "var(--glass-blur)",
          boxShadow: "var(--card-shadow)",
          transition: "transform 0.18s ease, background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease",
          cursor: "pointer",
          fontFamily: "var(--font-geist-sans), 'Geist', sans-serif",
        }} onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.transform = "translateY(-1px)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--bb)";
          (e.currentTarget as HTMLElement).style.boxShadow = "var(--card-shadow-hover)";
        }} onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.transform = "translateY(0)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--bd2)";
          (e.currentTarget as HTMLElement).style.boxShadow = "var(--card-shadow)";
        }}>
          🍎 Download macOS
        </a>
      </div>
      <div style={{ padding: "6px 12px 4px", display: "flex", justifyContent: "center" }}><ThemeToggle /></div>
      <div style={{ padding: "6px 12px 10px", display: "flex", justifyContent: "center" }}><CreditsDisplay /></div>
      <div style={{ padding: "0 8px 14px", display: "flex", flexDirection: "column", gap: 1 }}>
        <Link href="/settings" className={`nl${pathname.startsWith("/settings") ? " on" : ""}`} style={{ textDecoration: "none" }}><span style={{ width: 18, textAlign: "center" }}>⚙</span>Settings</Link>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
          <div style={{ width: 28, height: 28, borderRadius: "50%", background: isSignedIn ? "var(--green)" : "var(--blue)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-chakra)", fontSize: 10, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{initials(userId)}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: "var(--fg)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {isSignedIn ? (user.fullName || userId) : `${userId.replace(/^user_/, "").slice(0, 12)}…`}
            </div>
          </div>
          {isSignedIn
            ? <button onClick={() => signOut({ callbackUrl: "/" })} className="m-tap" style={{ background: "none", border: "none", fontSize: 10, color: "var(--fm)", cursor: "pointer", fontFamily: "var(--font-instrument), sans-serif", padding: "2px 4px", borderRadius: 4, flexShrink: 0 }}>sign out</button>
            : <button onClick={() => signIn("google", { callbackUrl: "/" })} className="m-tap" style={{ background: "none", border: "none", fontSize: 10, color: "var(--blue)", cursor: "pointer", fontFamily: "var(--font-instrument), sans-serif", padding: "2px 4px", borderRadius: 4, flexShrink: 0, fontWeight: 600 }}>sign in</button>}
        </div>
      </div>
    </nav>
  );
}
