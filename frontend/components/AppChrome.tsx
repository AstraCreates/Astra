"use client";

/* App shell — redesign sidebar + main content. Bare (no sidebar) on auth/
   onboarding routes. Mounted once in the root layout so every page matches. */
import { usePathname } from "next/navigation";
import RedesignSidebar from "@/components/RedesignSidebar";

const BARE_PREFIXES = ["/sign-in", "/sign-up", "/onboarding", "/invite", "/cookies"];

export default function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  if (BARE_PREFIXES.some((b) => pathname.startsWith(b))) {
    return <main>{children}</main>;
  }
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      <RedesignSidebar />
      <main style={{ flex: 1, minWidth: 0, height: "100vh", overflowY: "auto" }}>{children}</main>
    </div>
  );
}
