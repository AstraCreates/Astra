"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { useEffect, useMemo, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { desktopDownloadHref } from "@/lib/desktop-download";

type NavItem = {
  href: string;
  label: string;
  match: (pathname: string) => boolean;
  svg: string;
};

type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
};

const CORE_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Workspace",
    match: (pathname) => pathname.startsWith("/dashboard"),
    svg: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  },
  {
    href: "/goals",
    label: "Runs",
    match: (pathname) => pathname.startsWith("/goals"),
    svg: '<path d="M4 6h16M4 12h16M4 18h10"/><path d="M19 17v4m-2-2h4"/>',
  },
  {
    href: "/settings",
    label: "Settings",
    match: (pathname) => pathname.startsWith("/settings"),
    svg: '<path d="M12 3v3M12 18v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M3 12h3M18 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/><circle cx="12" cy="12" r="3"/>',
  },
];

const GROUPS: NavGroup[] = [
  {
    id: "knowledge",
    label: "Knowledge",
    items: [
      {
        href: "/brain",
        label: "Company Brain",
        match: (pathname) => pathname.startsWith("/brain"),
        svg: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 4 5.5 4 9s-1.5 6.5-4 9c-2.5-2.5-4-5.5-4-9s1.5-6.5 4-9Z"/>',
      },
      {
        href: "/library",
        label: "Library",
        match: (pathname) => pathname.startsWith("/library") || pathname.startsWith("/funding"),
        svg: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15Z"/>',
      },
    ],
  },
  {
    id: "operations",
    label: "Operations",
    items: [
      {
        href: "/outreach",
        label: "Outreach",
        match: (pathname) => pathname.startsWith("/outreach"),
        svg: '<path d="M22 2 11 13M22 2 15 22l-4-9-9-4 20-7Z"/>',
      },
      {
        href: "/integrations",
        label: "Integrations",
        match: (pathname) => pathname.startsWith("/integrations"),
        svg: '<path d="M9 2v4M15 2v4M6 10h12l-1 4a5 5 0 0 1-10 0l-1-4ZM10 22v-4M14 22v-4"/>',
      },
      {
        href: "/automations",
        label: "Automations",
        match: (pathname) => pathname.startsWith("/automations") || pathname.startsWith("/agents"),
        svg: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/>',
      },
      {
        href: "/payments",
        label: "Payments",
        match: (pathname) => pathname.startsWith("/payments"),
        svg: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
      },
    ],
  },
];

function initials(id: string) {
  return (id || "?").replace(/^(user_|google_)/, "").slice(0, 2).toUpperCase();
}

function NavLink({
  item,
  active,
  compact = false,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  compact?: boolean;
  onClick?: () => void;
}) {
  const handleClick = item.href === "/dashboard"
    ? (e: React.MouseEvent) => {
        e.preventDefault();
        window.location.assign("/dashboard");
        onClick?.();
      }
    : () => onClick?.();

  return (
    <Link
      href={item.href}
      prefetch={false}
      onClick={handleClick}
      className={`sb-link${active ? " active" : ""}${compact ? " compact" : ""}`}
    >
      <svg
        width={16}
        height={16}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ flexShrink: 0 }}
        dangerouslySetInnerHTML={{ __html: item.svg }}
      />
      {item.label}
    </Link>
  );
}

export default function RedesignSidebar({
  mobile = false,
  open = false,
  onClose,
}: {
  mobile?: boolean;
  open?: boolean;
  onClose?: () => void;
} = {}) {
  const pathname = usePathname() || "/";
  const { userId, isSignedIn, user } = useDevUser();
  const [credits, setCredits] = useState<number | null>(null);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const id = typeof window !== "undefined" ? localStorage.getItem("astra_user_id") || "" : "";
    if (id) {
      fetch(`/api/credits?founder_id=${encodeURIComponent(id)}`)
        .then((res) => res.json())
        .then((data) => { if (typeof data.credits === "number") setCredits(data.credits); })
        .catch(() => {});
    }
  }, []);

  const activeCore = useMemo(() => CORE_ITEMS.find((item) => item.match(pathname))?.href, [pathname]);
  const accentColor = "#7D8FFF";
  const displayName = user?.fullName?.split(" ")[0] || initials(userId);

  const sidebarStyle: React.CSSProperties = mobile
    ? {
        width: 232,
        display: "flex",
        flexDirection: "column",
        background: "#080A12",
        borderRight: "1px solid rgba(255,255,255,.07)",
        height: "100dvh",
        position: "fixed",
        top: 0,
        left: 0,
        zIndex: 60,
        transform: open ? "translateX(0)" : "translateX(-104%)",
        transition: "transform 0.28s cubic-bezier(0.22,1,0.36,1)",
      }
    : {
        width: 232,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        background: "#080A12",
        borderRight: "1px solid rgba(255,255,255,.07)",
        height: "100vh",
        position: "sticky",
        top: 0,
      };

  return (
    <nav onClick={(e) => { if (mobile && (e.target as HTMLElement).closest("a")) onClose?.(); }} style={sidebarStyle}>
      <style>{`
        @keyframes pulseDot { 0%,100%{opacity:1} 50%{opacity:.35} }
        .sb-link { display:flex;align-items:center;gap:11px;padding:10px 12px;border-radius:10px;text-decoration:none;font:500 13px 'Hanken Grotesk',system-ui,sans-serif;color:#8A93AD;transition:background .12s,color .12s,border-color .12s; border: 1px solid transparent; }
        .sb-link.compact { padding: 8px 11px; font-size: 12.5px; color: #97A3BC; }
        .sb-link:hover { background:rgba(255,255,255,.04);color:#EDF1FB; }
        .sb-link.active { font-weight:700;color:#fff;background:rgba(0,46,255,.12);border-color:rgba(125,143,255,.26); }
        .sb-group-toggle { width: 100%; display:flex; align-items:center; justify-content:space-between; gap:10px; padding: 10px 12px; border-radius: 10px; background: transparent; border: 1px solid transparent; color: #C8D1E4; font: 600 12.5px 'Hanken Grotesk',system-ui,sans-serif; cursor: pointer; }
        .sb-group-toggle:hover { background: rgba(255,255,255,.04); }
      `}</style>

      <div style={{ padding: "20px 16px 14px", display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 24, height: 24, background: accentColor, flexShrink: 0, WebkitMask: "url('/logo.png') center/contain no-repeat", mask: "url('/logo.png') center/contain no-repeat" }} />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".1em", color: "#EDF1FB" }}>ASTRA</span>
          <span style={{ fontSize: 10, letterSpacing: ".08em", color: "#8A93AD", marginTop: 5, display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: accentColor, animation: "pulseDot 2.6s infinite" }} />
            Workspace Ready
          </span>
        </div>
      </div>

      <div style={{ padding: "0 16px 16px" }}>
        <Link
          data-tour="new-goal-btn"
          href="/dashboard?new=1"
          style={{ display: "block", width: "100%", background: "#002EFF", color: "#fff", border: "1px solid rgba(0,46,255,.4)", borderRadius: 10, padding: 12, fontFamily: "'Hanken Grotesk',system-ui,sans-serif", fontWeight: 700, fontSize: 13, cursor: "pointer", textAlign: "center", textDecoration: "none", boxShadow: "0 16px 30px rgba(0,46,255,.16)" }}
        >
          + Start task
        </Link>
      </div>

      <div style={{ padding: "0 10px", display: "flex", flexDirection: "column", gap: 4 }}>
        {CORE_ITEMS.map((item) => (
          <NavLink key={item.href} item={item} active={activeCore === item.href} onClick={onClose} />
        ))}
      </div>

      <div style={{ padding: "14px 10px 0", display: "flex", flexDirection: "column", gap: 8, flex: 1, overflowY: "auto" }}>
        {GROUPS.map((group) => {
          const active = group.items.some((item) => item.match(pathname));
          const expanded = openGroups[group.id] ?? active;
          return (
            <div key={group.id} style={{ borderRadius: 12, border: active ? "1px solid rgba(125,143,255,.18)" : "1px solid rgba(255,255,255,.05)", background: active ? "rgba(255,255,255,.025)" : "transparent", overflow: "hidden" }}>
              <button
                type="button"
                className="sb-group-toggle"
                onClick={() => setOpenGroups((prev) => ({ ...prev, [group.id]: !expanded }))}
              >
                <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                  <span>{group.label}</span>
                  <span style={{ fontSize: 10, color: "#77839D", fontWeight: 500 }}>{group.items.map((item) => item.label).join(" · ")}</span>
                </span>
                <span style={{ color: "#8F9BBC", fontSize: 12 }}>{expanded ? "−" : "+"}</span>
              </button>
              {expanded && (
                <div style={{ padding: "0 8px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                  {group.items.map((item) => (
                    <NavLink key={item.href} item={item} active={item.match(pathname)} compact onClick={onClose} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "16px 16px 20px", marginTop: "auto" }}>
        <a
          href={desktopDownloadHref}
          target="_blank"
          rel="noopener noreferrer"
          style={{ width: "100%", background: "transparent", color: "#C3CBE0", border: "1px solid rgba(255,255,255,.13)", borderRadius: 10, padding: 10, fontFamily: "'Hanken Grotesk',system-ui,sans-serif", fontWeight: 500, fontSize: 12.5, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, textDecoration: "none" }}
        >
          <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" /></svg>
          Download macOS
        </a>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", border: "1px solid rgba(255,255,255,.1)", borderRadius: 10, background: "rgba(255,255,255,.03)" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#EDF1FB" }}>{credits !== null ? credits.toLocaleString() : "—"}</span>
          <span style={{ fontSize: 10, letterSpacing: ".04em", color: "#6F7B98" }}>credits</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,.07)" }}>
          <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#1C2536", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#EDF1FB", flexShrink: 0 }}>
            {initials(userId)}
          </div>
          <div style={{ lineHeight: 1.2, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "#EDF1FB", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{displayName}</div>
            <div style={{ fontSize: 10, color: "#6F7B98", display: "flex", gap: 6 }}>
              <Link href="/settings" style={{ color: "inherit", textDecoration: "none" }}>Settings</Link>
              <span>·</span>
              {isSignedIn ? (
                <button
                  onClick={() => {
                    localStorage.removeItem("astra_remember_me");
                    signOut({ callbackUrl: "/" });
                  }}
                  style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, fontSize: 10, fontFamily: "inherit" }}
                >
                  Sign out
                </button>
              ) : (
                <span>—</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
