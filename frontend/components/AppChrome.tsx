"use client";

/* App shell — responsive. Desktop: fixed sidebar + main. Mobile: sidebar becomes
   an off-canvas drawer toggled by a floating hamburger; content is full-width.
   Bare (no sidebar) on auth/onboarding routes. */
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import RedesignSidebar from "@/components/RedesignSidebar";
import WorkspaceTour from "@/components/WorkspaceTour";
import { useIsMobile } from "@/lib/use-is-mobile";

const BARE_PREFIXES = ["/sign-in", "/sign-up", "/onboarding", "/invite", "/cookies"];

const TITLES: { match: (p: string) => boolean; title: string }[] = [
  { match: (p) => p.startsWith("/brain"), title: "Company Brain" },
  { match: (p) => p.startsWith("/integrations"), title: "Integrations" },
  { match: (p) => p.startsWith("/payments"), title: "Payments" },
  { match: (p) => p.startsWith("/settings"), title: "Settings" },
  { match: (p) => p.startsWith("/outreach"), title: "Outreach" },
];

export default function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [showTour, setShowTour] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const shouldShow = localStorage.getItem("astra_show_tour") === "1"
        && !localStorage.getItem("astra_tour_done");
      if (shouldShow) {
        // Small delay so sidebar is fully mounted before tour measures elements
        const t = setTimeout(() => setShowTour(true), 600);
        return () => clearTimeout(t);
      }
    }
  }, []);

  // Close the drawer whenever the route changes.
  useEffect(() => { setDrawerOpen(false); }, [pathname]);
  // Never leave the drawer "open" lingering when switching to desktop.
  useEffect(() => { if (!isMobile) setDrawerOpen(false); }, [isMobile]);

  if (BARE_PREFIXES.some((b) => pathname.startsWith(b))) {
    return <main>{children}</main>;
  }

  const tour = showTour ? <WorkspaceTour onDone={() => { localStorage.removeItem("astra_show_tour"); setShowTour(false); }} /> : null;

  const isHome = pathname === "/";
  const title = TITLES.find((t) => t.match(pathname))?.title;

  // ── Mobile: full-width content, hamburger, off-canvas drawer ────────────────
  if (isMobile) {
    return (
      <div style={{ display: "flex", flexDirection: "column", minHeight: "100dvh", background: "var(--bg)" }}>
        {tour}
        <RedesignSidebar mobile open={drawerOpen} onClose={() => setDrawerOpen(false)} />
        {/* Backdrop */}
        {drawerOpen && (
          <div onClick={() => setDrawerOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 55 }} />
        )}
        {/* Floating hamburger — always reachable */}
        <button
          aria-label="Open menu"
          onClick={() => setDrawerOpen((v) => !v)}
          style={{ position: "fixed", top: 8, left: 8, zIndex: 65, width: 38, height: 38, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", border: "1px solid var(--bd)", color: "var(--fg)", fontSize: 17, lineHeight: 1, cursor: "pointer", boxShadow: "0 1px 6px rgba(0,0,0,.12)" }}
        >
          ☰
        </button>
        {isHome ? (
          <main style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>{children}</main>
        ) : (
          <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ height: 46, display: "flex", alignItems: "center", padding: "0 14px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
              <div className="topbar-title">{title || "Astra"}</div>
            </div>
            <div style={{ flex: 1, padding: "18px 16px 64px" }}>{children}</div>
          </main>
        )}
      </div>
    );
  }

  // ── Desktop: fixed sidebar + main ───────────────────────────────────────────
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      {tour}
      <RedesignSidebar />
      {isHome ? (
        <main style={{ flex: 1, minWidth: 0, height: "100vh", overflow: "hidden" }}>{children}</main>
      ) : (
        <main style={{ flex: 1, minWidth: 0, height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">{title || "Astra"}</div>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "24px 22px 48px" }}>{children}</div>
        </main>
      )}
    </div>
  );
}
