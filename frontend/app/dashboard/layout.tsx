import Sidebar from "./Sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 101,
      display: "flex", background: "var(--ink)",  /* var(--ink) = #E8E8E6 warm gray */
    }}>
      <Sidebar />
      <main style={{ flex: 1, overflowY: "auto", padding: "40px 48px" }}>
        {children}
      </main>
    </div>
  );
}
