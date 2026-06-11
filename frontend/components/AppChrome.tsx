"use client";

/* App shell — responsive. Desktop: fixed sidebar + main. Mobile: sidebar becomes
   an off-canvas drawer toggled by a floating hamburger; content is full-width.
   Bare (no sidebar) on auth/onboarding routes. */
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { signIn } from "next-auth/react";
import RedesignSidebar from "@/components/RedesignSidebar";
import WorkspaceTour from "@/components/WorkspaceTour";
import { useIsMobile } from "@/lib/use-is-mobile";
import { useDevUser } from "@/lib/use-dev-user";

const BARE_PREFIXES = ["/sign-in", "/sign-up", "/onboarding", "/invite", "/cookies"];
// Public routes accessible without login (shareable session links)
const PUBLIC_PREFIXES = [...BARE_PREFIXES, "/s/"];

const TITLES: { match: (p: string) => boolean; title: string }[] = [
  { match: (p) => p.startsWith("/goals"), title: "Checklist" },
  { match: (p) => p.startsWith("/brain"), title: "Company Brain" },
  { match: (p) => p.startsWith("/integrations"), title: "Integrations" },
  { match: (p) => p.startsWith("/payments"), title: "Payments" },
  { match: (p) => p.startsWith("/settings"), title: "Settings" },
  { match: (p) => p.startsWith("/outreach"), title: "Outreach" },
];

function SignInScreen() {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "#F3F4F7",
      backgroundImage: "radial-gradient(ellipse 70% 45% at 50% 0%, rgba(0,46,255,0.07) 0%, transparent 70%)",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
    }}>
      <div style={{
        background: "#fff",
        border: "1px solid rgba(0,0,0,0.08)",
        borderRadius: 20,
        boxShadow: "0 4px 40px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.04)",
        padding: "40px 40px 32px",
        maxWidth: 400, width: "calc(100% - 48px)",
        display: "flex", flexDirection: "column", alignItems: "center",
        textAlign: "center",
      }}>
        {/* Logo + wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <div style={{
            width: 30, height: 30, background: "#111018", flexShrink: 0,
            WebkitMask: "url('/logo.png') center/contain no-repeat",
            mask: "url('/logo.png') center/contain no-repeat",
          }} />
          <span style={{ fontSize: 20, fontWeight: 700, color: "#111018", letterSpacing: "-0.02em" }}>Astra</span>
        </div>

        <h1 style={{ fontSize: 26, fontWeight: 700, margin: "0 0 10px", color: "#111018", letterSpacing: "-0.02em", lineHeight: 1.2 }}>
          Your AI founding team
        </h1>
        <p style={{ fontSize: 13.5, color: "#737373", margin: "0 0 28px", lineHeight: 1.65, maxWidth: 290 }}>
          8 specialized agents working in parallel — research, strategy, engineering, and marketing.
        </p>

        {/* White Google button */}
        <button
          onClick={() => signIn("google", { callbackUrl: "/" })}
          style={{
            display: "flex", alignItems: "center", gap: 10, width: "100%",
            justifyContent: "center",
            padding: "12px 24px", borderRadius: 10,
            background: "#fff", color: "#111018",
            border: "1px solid rgba(0,0,0,0.16)",
            fontSize: 14, fontWeight: 600, cursor: "pointer",
            letterSpacing: "0.01em",
            boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
            fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
            transition: "box-shadow 0.18s, border-color 0.18s",
          }}
          onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 2px 10px rgba(0,0,0,0.1)"; e.currentTarget.style.borderColor = "rgba(0,0,0,0.26)"; }}
          onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.06)"; e.currentTarget.style.borderColor = "rgba(0,0,0,0.16)"; }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48" style={{ flexShrink: 0 }}>
            <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.9z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.8 19 12 24 12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 9.8-2 13.3-5.2l-6.2-5.2C29.2 35.5 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.6 39.6 16.3 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.4 4.2-4.4 5.5l6.2 5.2C36.9 41 44 36 44 24c0-1.3-.1-2.7-.4-3.9z"/>
          </svg>
          Continue with Google
        </button>

        {/* Feature grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 20, width: "100%" }}>
          {[
            { ic: "◈", label: "Research" },
            { ic: "⚙", label: "Technical" },
            { ic: "✦", label: "Marketing" },
          ].map(({ ic, label }) => (
            <div key={label} style={{
              background: "#F3F4F7", borderRadius: 10,
              padding: "12px 8px",
              display: "flex", flexDirection: "column", alignItems: "center", gap: 5,
            }}>
              <span style={{ fontSize: 15, color: "#002EFF" }}>{ic}</span>
              <span style={{ fontSize: 10, color: "#737373", fontWeight: 500, letterSpacing: "0.03em" }}>{label}</span>
            </div>
          ))}
        </div>

        <p style={{ fontSize: 11, color: "#9CA3AF", margin: "20px 0 0", lineHeight: 1.5 }}>
          By continuing, you agree to our terms and privacy policy.
        </p>
      </div>
    </div>
  );
}

export default function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [showTour, setShowTour] = useState(false);
  const { isSignedIn, isLoading } = useDevUser();

  useEffect(() => {
    if (typeof window === "undefined") return;
    // Tour spotlights the desktop sidebar, which is an off-canvas drawer on phones —
    // skip on mobile and consume the flag so it doesn't linger.
    if (window.matchMedia("(max-width: 768px)").matches) {
      if (localStorage.getItem("astra_show_tour") === "1") {
        try { localStorage.removeItem("astra_show_tour"); localStorage.setItem("astra_tour_done", "1"); } catch {}
      }
      return;
    }
    const shouldShow = localStorage.getItem("astra_show_tour") === "1"
      && !localStorage.getItem("astra_tour_done");
    if (shouldShow) {
      // Small delay so sidebar is fully mounted before tour measures elements
      const t = setTimeout(() => setShowTour(true), 600);
      return () => clearTimeout(t);
    }
  }, []);

  // Close the drawer whenever the route changes.
  useEffect(() => { setDrawerOpen(false); }, [pathname]);
  // Never leave the drawer "open" lingering when switching to desktop.
  useEffect(() => { if (!isMobile) setDrawerOpen(false); }, [isMobile]);

  if (BARE_PREFIXES.some((b) => pathname.startsWith(b))) {
    return <main>{children}</main>;
  }

  // Auth gate — protect all non-public routes
  if (!PUBLIC_PREFIXES.some((b) => pathname.startsWith(b))) {
    if (isLoading) {
      return <div style={{ position: "fixed", inset: 0, background: "var(--bg, #F3F4F7)" }} />;
    }
    if (!isSignedIn) {
      return <SignInScreen />;
    }
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
        <AnimatePresence>
          {drawerOpen && (
            <motion.div
              key="drawer-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
              onClick={() => setDrawerOpen(false)}
              style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 55 }}
            />
          )}
        </AnimatePresence>
        {/* Floating hamburger — always reachable */}
        <button
          aria-label="Open menu"
          onClick={() => setDrawerOpen((v) => !v)}
          style={{ position: "fixed", top: 8, left: 8, zIndex: 65, width: 38, height: 38, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", border: "1px solid var(--bd)", color: "var(--fg)", fontSize: 17, lineHeight: 1, cursor: "pointer", boxShadow: "0 1px 6px rgba(0,0,0,.12)" }}
        >
          ☰
        </button>
        {isHome ? (
          <main style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative", zIndex: 100 }}>{children}</main>
        ) : (
          <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ height: 46, display: "flex", alignItems: "center", padding: "0 14px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
              <div className="topbar-title">{title || "Astra"}</div>
            </div>
            <div key={pathname} className="page-fade" style={{ flex: 1, padding: 0 }}>{children}</div>
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
        <main style={{ flex: 1, minWidth: 0, height: "100vh", overflow: "hidden", position: "relative", zIndex: 100 }}>{children}</main>
      ) : (
        <main style={{ flex: 1, minWidth: 0, height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
            <div className="topbar-title">{title || "Astra"}</div>
          </div>
          <div key={pathname} className="page-fade" style={{ flex: 1, overflowY: "auto", padding: 0 }}>{children}</div>
        </main>
      )}
    </div>
  );
}
