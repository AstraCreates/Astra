"use client";

import { useEffect, useState } from "react";
import { getSessions } from "@/lib/history";

interface Artifact { label: string; value: string; href?: string; icon: string; company: string; sessionId: string; }

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const sessions = getSessions();
    const arts: Artifact[] = sessions.flatMap(s =>
      (s.artifacts ?? []).map(a => ({ ...a, company: s.companyName || s.instruction.slice(0, 30), sessionId: s.sessionId }))
    );
    setArtifacts(arts);
    setMounted(true);
  }, []);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Artifacts</h1>
        <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>All links and files produced by your goals</p>
      </div>

      {mounted && artifacts.length === 0 && (
        <div style={{ padding: "40px 0", textAlign: "center", color: "rgba(255,255,255,0.2)", fontSize: 13 }}>No artifacts yet. Complete a goal to see outputs here.</div>
      )}

      {mounted && artifacts.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
          {artifacts.map((a, i) => (
            a.href ? (
              <a key={i} href={a.href} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderRadius: 14, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10)", textDecoration: "none", transition: "all 0.15s" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.09)"; (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.14)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.05)"; (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.08)"; }}
              >
                <span style={{ fontSize: 22, flexShrink: 0 }}>{a.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: "var(--fg)" }}>{a.label}</p>
                  <p style={{ margin: "2px 0 0", fontSize: 11, color: "rgba(255,255,255,0.3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.company}</p>
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 14, flexShrink: 0 }}>↗</span>
              </a>
            ) : (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderRadius: 14, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>{a.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: "var(--fg-dim)" }}>{a.label}</p>
                  <p style={{ margin: "2px 0 0", fontSize: 11, color: "rgba(255,255,255,0.2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.value}</p>
                </div>
              </div>
            )
          ))}
        </div>
      )}
    </div>
  );
}
