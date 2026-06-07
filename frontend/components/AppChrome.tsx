"use client";

/* App shell — redesign sidebar + main content, consistent on every page.
   Bare (no sidebar) on auth/onboarding routes. Home ("/") owns its own
   per-view topbar; other pages get a uniform topbar + padded scroll area. */
import { usePathname } from "next/navigation";
import RedesignSidebar from "@/components/RedesignSidebar";

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
  if (BARE_PREFIXES.some((b) => pathname.startsWith(b))) {
    return <main>{children}</main>;
  }

  const isHome = pathname === "/";
  const title = TITLES.find((t) => t.match(pathname))?.title;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      <RedesignSidebar />
      {isHome ? (
        // Home owns its own topbar/layout per view (dashboard / new / session).
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
