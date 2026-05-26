export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      position: "relative",
      minHeight: "100vh",
      zIndex: 101,
      display: "flex",
      overflow: "hidden",
      background:
        "radial-gradient(1100px 760px at 18% 12%, rgba(90,114,144,0.14), transparent 58%), radial-gradient(900px 700px at 88% 18%, rgba(180,205,228,0.08), transparent 54%), var(--ink)",
    }}>
      <div aria-hidden="true" style={{
        position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", top: "-8vh", left: "-10vw", width: "32vw", height: "32vw",
          borderRadius: "50%", background: "radial-gradient(circle, rgba(180,205,228,0.08), transparent 68%)",
          filter: "blur(34px)",
        }} />
        <div style={{
          position: "absolute", right: "-8vw", bottom: "-12vh", width: "36vw", height: "36vw",
          borderRadius: "50%", background: "radial-gradient(circle, rgba(90,114,144,0.12), transparent 70%)",
          filter: "blur(44px)",
        }} />
      </div>
      <main style={{
        flex: 1,
        overflowY: "auto",
        padding: "clamp(28px, 4vw, 60px)",
        position: "relative",
        zIndex: 1,
      }}>
        {children}
      </main>
    </div>
  );
}
