import Link from "next/link";

/** Phase 3 removal response. This route intentionally never reads session data. */
export default function RemovedSessionPage() {
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "var(--bg)" }}>
      <section style={{ maxWidth: 520, padding: 32, border: "1px solid var(--border)", borderRadius: 16, background: "var(--bg-surface)", textAlign: "center" }}>
        <p style={{ margin: "0 0 10px", color: "var(--accent)", fontSize: 12, fontWeight: 700, letterSpacing: ".12em" }}>REMOVED</p>
        <h1 style={{ margin: "0 0 12px" }}>Runs and sessions no longer exist</h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-muted)", lineHeight: 1.6 }}>Astra now operates from one permanent Company Home conversation with named initiatives, squads, missions, and tasks.</p>
        <Link href="/dashboard" style={{ display: "inline-block", padding: "11px 16px", borderRadius: 8, background: "var(--accent)", color: "white", fontWeight: 700, textDecoration: "none" }}>Open Company Home</Link>
      </section>
    </main>
  );
}
