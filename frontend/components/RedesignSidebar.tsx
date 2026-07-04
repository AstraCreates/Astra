"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { desktopDownloadHref } from "@/lib/desktop-download";

const LINKS: { href: string; label: string; match: (p: string) => boolean; svg: string }[] = [
  { href: "/dashboard",    label: "Dashboard",     match: p => p.startsWith("/dashboard"),
    svg: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>' },
  { href: "/goals",        label: "Checklist",     match: p => p.startsWith("/goals"),
    svg: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>' },
  { href: "/outreach",     label: "Outreach",      match: p => p.startsWith("/outreach"),
    svg: '<path d="M22 2 11 13M22 2 15 22l-4-9-9-4 20-7Z"/>' },
  { href: "/brain",        label: "Company Brain", match: p => p.startsWith("/brain"),
    svg: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 4 5.5 4 9s-1.5 6.5-4 9c-2.5-2.5-4-5.5-4-9s1.5-6.5 4-9Z"/>' },
  { href: "/library",      label: "Library",       match: p => p.startsWith("/library") || p.startsWith("/funding"),
    svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15Z"/>' },
  { href: "/integrations", label: "Integrations",  match: p => p.startsWith("/integrations"),
    svg: '<path d="M9 2v4M15 2v4M6 10h12l-1 4a5 5 0 0 1-10 0l-1-4ZM10 22v-4M14 22v-4"/>' },
  { href: "/automations",  label: "Automations",   match: p => p.startsWith("/automations") || p.startsWith("/agents"),
    svg: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/>' },
  { href: "/payments",     label: "Payments",      match: p => p.startsWith("/payments"),
    svg: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>' },
];

function initials(id: string) {
  return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase();
}

export default function RedesignSidebar({ mobile = false, open = false, onClose }: { mobile?: boolean; open?: boolean; onClose?: () => void } = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const [credits, setCredits] = useState<number | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
    // load credits
    const id = typeof window !== "undefined" ? localStorage.getItem("astra_user_id") || "" : "";
    if (id) {
      fetch(`/api/credits?founder_id=${encodeURIComponent(id)}`)
        .then(r => r.json())
        .then(d => { if (typeof d.credits === "number") setCredits(d.credits); })
        .catch(() => {});
    }
  }, []);

  const displayName = hydrated ? (user?.fullName?.split(" ")[0] || initials(userId)) : "…";
  const accentColor = "#7CFFC6";

  const sidebarStyle: React.CSSProperties = mobile
    ? { width: 214, display: "flex", flexDirection: "column", background: "#080A12", borderRight: "1px solid rgba(255,255,255,.07)", height: "100dvh", position: "fixed", top: 0, left: 0, zIndex: 60, transform: open ? "translateX(0)" : "translateX(-104%)", transition: "transform 0.28s cubic-bezier(0.22,1,0.36,1)" }
    : { width: 214, flexShrink: 0, display: "flex", flexDirection: "column", background: "#080A12", borderRight: "1px solid rgba(255,255,255,.07)", height: "100vh", position: "sticky", top: 0 };

  return (
    <nav onClick={e => { if (mobile && (e.target as HTMLElement).closest("a")) onClose?.(); }} style={sidebarStyle}>
      <style>{`
        @keyframes pulseDot { 0%,100%{opacity:1} 50%{opacity:.35} }
        .sb-link { display:flex;align-items:center;gap:11px;padding:9px 11px;border-radius:7px;text-decoration:none;font:500 13px 'Hanken Grotesk',system-ui,sans-serif;color:#8A93AD;border-left:2px solid transparent;transition:background .12s,color .12s; }
        .sb-link:hover { background:rgba(255,255,255,.04);color:#EDF1FB; }
        .sb-link.active { font-weight:600;color:#fff;background:rgba(255,255,255,.06);border-left-color:${accentColor}; }
      `}</style>

      {/* Logo */}
      <div style={{ padding: "20px 16px", display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{ width: 24, height: 24, background: accentColor, flexShrink: 0, WebkitMask: "url('/logo.png') center/contain no-repeat", mask: "url('/logo.png') center/contain no-repeat" }} />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".1em", color: "#EDF1FB" }}>ASTRA</span>
          <span style={{ fontSize: 10, letterSpacing: ".08em", color: "#8A93AD", marginTop: 5, display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: accentColor, animation: "pulseDot 2.6s infinite" }} />
            Ready
          </span>
        </div>
      </div>

      {/* New run */}
      <div style={{ padding: "0 16px 16px" }}>
        <Link data-tour="new-goal-btn" href="/dashboard?new=1"
          style={{ display: "block", width: "100%", background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: 11, fontFamily: "'Hanken Grotesk',system-ui,sans-serif", fontWeight: 600, fontSize: 13, cursor: "pointer", textAlign: "center", textDecoration: "none" }}>
          + New run
        </Link>
      </div>

      {/* Nav */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 8px", flex: 1, overflowY: "auto" }}>
        {LINKS.map(l => {
          const active = l.match(pathname);
          const href = l.href === "/dashboard" ? undefined : l.href;
          const handleClick = l.href === "/dashboard" ? (e: React.MouseEvent) => { e.preventDefault(); window.location.assign("/dashboard"); } : undefined;
          return (
            <Link key={l.href} href={l.href} prefetch={false}
              onClick={handleClick}
              data-tour={`nav-${l.label.toLowerCase().replace(/\s+/g, "-")}`}
              className={`sb-link${active ? " active" : ""}`}
            >
              <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}
                dangerouslySetInnerHTML={{ __html: l.svg }} />
              {l.label}
            </Link>
          );
        })}
      </div>

      {/* Bottom */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px 16px 20px", marginTop: "auto" }}>
        {/* Download macOS */}
        <a href={desktopDownloadHref} target="_blank" rel="noopener noreferrer"
          style={{ width: "100%", background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.13)", borderRadius: 8, padding: 10, fontFamily: "'Hanken Grotesk',system-ui,sans-serif", fontWeight: 500, fontSize: 12.5, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, textDecoration: "none" }}>
          <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" /></svg>
          Download macOS
        </a>

        {/* Credits */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 12px", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, background: "rgba(255,255,255,.03)" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#EDF1FB" }}>{credits !== null ? credits.toLocaleString() : "—"}</span>
          <span style={{ fontSize: 10, letterSpacing: ".04em", color: "#6f7b98" }}>credits</span>
        </div>

        {/* User row */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,.07)" }}>
          <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#1c2536", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#EDF1FB", flexShrink: 0 }}>
            {hydrated ? initials(userId) : "…"}
          </div>
          <div style={{ lineHeight: 1.2, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "#EDF1FB", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{displayName}</div>
            <div style={{ fontSize: 10, color: "#6f7b98", display: "flex", gap: 6 }}>
              <Link href="/settings" style={{ color: "inherit", textDecoration: "none" }}>Settings</Link>
              <span>·</span>
              {hydrated && isSignedIn
                ? <button onClick={() => { localStorage.removeItem("astra_remember_me"); signOut({ callbackUrl: "/" }); }} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, fontSize: 10, fontFamily: "inherit" }}>Sign out</button>
                : <span>—</span>}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
