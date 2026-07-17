"use client";

/* App shell — responsive. Desktop: fixed sidebar + main. Mobile: sidebar becomes
   an off-canvas drawer toggled by a floating hamburger; content is full-width.
   Bare (no sidebar) on auth/onboarding routes. */
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { signIn, signOut } from "next-auth/react";
import RedesignSidebar from "@/components/RedesignSidebar";
import WorkspaceTour from "@/components/WorkspaceTour";
import { useIsMobile } from "@/lib/use-is-mobile";
import { useDevUser } from "@/lib/use-dev-user";

// Routes rendered without sidebar chrome. Distinct from which routes skip the
// auth gate — /onboarding is bare-chrome but NOT public (see PUBLIC_PREFIXES):
// it creates real backend goal/founder data, so it must require sign-in like
// the rest of the app, it just doesn't show the sidebar while doing it.
const BARE_CHROME_PREFIXES = ["/sign-in", "/sign-up", "/onboarding", "/invite", "/cookies"];
// Public routes accessible without login (shareable session links)
const PUBLIC_PREFIXES = ["/sign-in", "/sign-up", "/invite", "/cookies", "/s/"];
// Exact routes that are public landing/marketing pages — no sidebar, no auth gate
const BARE_EXACT = ["/"];


function SignInScreen() {
  const [rememberMe, setRememberMe] = useState(true);

  const handleSignIn = () => {
    if (typeof window !== "undefined") {
      localStorage.setItem("astra_remember_me", rememberMe ? "1" : "0");
      // survives the OAuth redirect so we know we came from a fresh sign-in
      sessionStorage.setItem("astra_session_active", "1");
    }
    signIn("google", { callbackUrl: typeof window !== "undefined" ? window.location.href : "/dashboard" });
  };

  return (
    <div className="astra-auth-shell" style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "var(--bg)",
      backgroundImage: "radial-gradient(circle at 18% 14%, rgba(0,46,255,0.14), transparent 0 22%), radial-gradient(circle at 82% 16%, rgba(124,255,198,0.12), transparent 0 18%), linear-gradient(180deg, rgba(255,255,255,0.06), transparent 32%)",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
    }}>
      <div className="astra-auth-panel" style={{
        background: "linear-gradient(180deg, var(--surface), var(--s2))",
        border: "1px solid var(--bd2)",
        borderRadius: 24,
        boxShadow: "var(--shell-shadow)",
        backdropFilter: "var(--glass-blur)",
        padding: "40px 40px 32px",
        maxWidth: 400, width: "calc(100% - 48px)",
        display: "flex", flexDirection: "column", alignItems: "center",
        textAlign: "center",
      }}>
        {/* Logo + wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <div style={{
            width: 30, height: 30, background: "var(--fg)", flexShrink: 0,
            WebkitMask: "url('/logo.png') center/contain no-repeat",
            mask: "url('/logo.png') center/contain no-repeat",
          }} />
          <span style={{ fontSize: 20, fontWeight: 700, color: "var(--fg)", letterSpacing: "-0.02em" }}>Astra</span>
        </div>

        <h1 style={{ fontSize: 26, fontWeight: 700, margin: "0 0 10px", color: "var(--fg)", letterSpacing: "-0.02em", lineHeight: 1.2 }}>
          Your AI founding team
        </h1>
        <p style={{ fontSize: 13.5, color: "rgba(255,255,255,0.82)", margin: "0 0 28px", lineHeight: 1.65, maxWidth: 290 }}>
          A team of specialized agents working in parallel — research, strategy, engineering, and marketing.
        </p>

        {/* White Google button */}
        <button
          onClick={handleSignIn}
          style={{
            display: "flex", alignItems: "center", gap: 10, width: "100%",
            justifyContent: "center",
            padding: "12px 24px", borderRadius: 10,
            background: "rgba(255,255,255,0.82)", color: "var(--fg)",
            border: "1px solid var(--bd2)",
            fontSize: 14, fontWeight: 600, cursor: "pointer",
            letterSpacing: "0.01em",
            boxShadow: "var(--card-shadow)",
            backdropFilter: "var(--glass-blur)",
            fontFamily: "var(--font-instrument), 'Instrument Sans', sans-serif",
            transition: "box-shadow 0.18s, border-color 0.18s",
          }}
          onMouseEnter={e => { e.currentTarget.style.boxShadow = "var(--card-shadow-hover)"; e.currentTarget.style.borderColor = "var(--bb)"; }}
          onMouseLeave={e => { e.currentTarget.style.boxShadow = "var(--card-shadow)"; e.currentTarget.style.borderColor = "var(--bd2)"; }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48" style={{ flexShrink: 0 }}>
            <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.9z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.8 19 12 24 12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 9.8-2 13.3-5.2l-6.2-5.2C29.2 35.5 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.6 39.6 16.3 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.4 4.2-4.4 5.5l6.2 5.2C36.9 41 44 36 44 24c0-1.3-.1-2.7-.4-3.9z"/>
          </svg>
          Continue with Google
        </button>

        {/* Stay signed in */}
        <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16, cursor: "pointer", userSelect: "none" }}>
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={e => setRememberMe(e.target.checked)}
            style={{ width: 15, height: 15, cursor: "pointer", accentColor: "#002EFF" }}
          />
          <span style={{ fontSize: 13, color: "var(--fd)", fontFamily: "var(--font-instrument), sans-serif" }}>Stay signed in</span>
        </label>

        <p style={{ fontSize: 11, color: "var(--fm)", margin: "12px 0 0", lineHeight: 1.5 }}>
          By continuing, you agree to our <a href="#" onClick={e => e.preventDefault()} style={{ color: "var(--blue)", textDecoration: "underline", cursor: "pointer" }}>terms</a> and <a href="#" onClick={e => e.preventDefault()} style={{ color: "var(--blue)", textDecoration: "underline", cursor: "pointer" }}>privacy policy</a>.
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
  const [sessionChecked, setSessionChecked] = useState(false);
  const [qaBypass, setQaBypass] = useState(false);
  const { isSignedIn, isLoading } = useDevUser();

  useEffect(() => {
    if (process.env.NODE_ENV !== "production" &&
        typeof window !== "undefined" &&
        localStorage.getItem("astra_qa_bypass") === "1") {
      setQaBypass(true);
      setSessionChecked(true);
    }
  }, []);

  // "Stay signed in" enforcement: if user opted out, sign them out on fresh browser open.
  // sessionStorage survives in-tab redirects (including OAuth) but clears on browser close.
  useEffect(() => {
    if (qaBypass) {
      sessionStorage.setItem("astra_session_active", "1");
      setSessionChecked(true);
      return;
    }
    if (isLoading) return;
    if (!isSignedIn) { setSessionChecked(true); return; }
    const rememberMe = localStorage.getItem("astra_remember_me");
    const sessionActive = sessionStorage.getItem("astra_session_active");
    if (rememberMe === "0" && !sessionActive) {
      // Clear the flag before signing out — stale "0" otherwise re-triggers
      // this sign-out on every future browser open, looping indefinitely.
      localStorage.removeItem("astra_remember_me");
      signOut({ callbackUrl: "/" });
      return;
    }
    sessionStorage.setItem("astra_session_active", "1");
    setSessionChecked(true);
  }, [isLoading, isSignedIn, qaBypass]);

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

  const isBareChrome = BARE_CHROME_PREFIXES.some((b) => pathname.startsWith(b)) || BARE_EXACT.includes(pathname);
  const isPublic = PUBLIC_PREFIXES.some((b) => pathname.startsWith(b)) || BARE_EXACT.includes(pathname);

  // Auth gate — protect all non-public routes (checked before the bare-chrome
  // early-return so /onboarding can't skip it just because it's sidebar-less).
  if (!isPublic) {
    if (!qaBypass && (isLoading || (isSignedIn && !sessionChecked))) {
      return <div style={{ position: "fixed", inset: 0, background: "var(--bg, #F3F4F7)" }} />;
    }
    if (!isSignedIn && !qaBypass) {
      return <SignInScreen />;
    }
  }

  if (isBareChrome) {
    return <main>{children}</main>;
  }

  const tour = showTour ? <WorkspaceTour onDone={() => { localStorage.removeItem("astra_show_tour"); setShowTour(false); }} /> : null;

  const isHome = pathname === "/";

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
            {/* Slim spacer so page content clears the floating hamburger */}
            <div style={{ height: 46, flexShrink: 0 }} />
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
          <div key={pathname} className="page-fade" style={{ flex: 1, overflowY: "auto", padding: 0 }}>{children}</div>
        </main>
      )}
    </div>
  );
}
