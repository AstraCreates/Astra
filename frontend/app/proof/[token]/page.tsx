"use client";

/* Public, unauthenticated proof page. Renders a company's verification receipts,
   re-verified live by the backend at request time. This is the "prove it's real"
   link a founder shares with an investor or customer. */

import { use, useEffect, useState } from "react";
import { ReceiptTrail, type ArtifactReceipt } from "@/components/PhaseWorkboard";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ProofArtifact = {
  artifact_key?: string;
  artifact_title?: string;
  agent?: string;
  status?: string;
  checks?: ArtifactReceipt["checks"];
  evidence?: Record<string, unknown>;
  attempts?: number;
  checked_at?: string;
  live?: { url?: string; ok?: boolean; status?: number; bytes?: number; error?: string } | null;
};

type Proof = { artifact_count: number; verified_count: number; artifacts: ProofArtifact[] };

export default function ProofPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [proof, setProof] = useState<Proof | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API}/api/share/${token}`);
        if (!res.ok) throw new Error(res.status === 404 ? "This proof link is invalid or has been revoked." : `Error ${res.status}`);
        const data = await res.json();
        if (alive) setProof(data);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load proof.");
      }
    })();
    return () => { alive = false; };
  }, [token]);

  return (
    <div className="site-shell" style={{ paddingTop: 64, paddingBottom: 88 }}>
      <div style={{ maxWidth: 860, margin: "0 auto", display: "grid", gap: 22 }}>
        <div style={{ display: "grid", gap: 8 }}>
          <span className="site-label">Verified by Astra</span>
          <h1 style={{ fontSize: "clamp(28px, 4.5vw, 50px)", lineHeight: 1.04 }}>Proof of work</h1>
          <p style={{ color: "var(--fg-dim)", fontSize: 15, lineHeight: 1.7 }}>
            Every deliverable below was independently verified — shape, live execution, and a
            semantic quality review. Live links were re-checked the moment this page loaded.
          </p>
        </div>

        {error && <div style={{ color: "var(--amber, #D89614)", fontSize: 14 }}>{error}</div>}
        {!proof && !error && <div style={{ color: "var(--fg-dim)", fontSize: 14 }}>Verifying live…</div>}

        {proof && (
          <>
            <div style={{ display: "flex", gap: 18, alignItems: "baseline" }}>
              <span style={{ fontSize: 34, fontWeight: 800 }}>{proof.verified_count}/{proof.artifact_count}</span>
              <span style={{ color: "var(--fg-dim)", fontSize: 14 }}>deliverables verified</span>
            </div>
            <div style={{ display: "grid", gap: 14 }}>
              {proof.artifacts.map((a) => (
                <div key={a.artifact_key} style={{ borderRadius: 18, border: "1px solid var(--line, rgba(176,180,186,0.15))", background: "var(--glass, rgba(255,255,255,0.02))", padding: "16px 18px", display: "grid", gap: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>{a.artifact_title || a.artifact_key}</div>
                    <div style={{ fontSize: 11, color: "var(--fg-dim)" }}>{a.agent}</div>
                  </div>
                  {a.live && (
                    <div style={{ fontSize: 11, color: a.live.ok ? "#3D9E5F" : "#C0392B" }}>
                      {a.live.ok
                        ? `● Live now — HTTP ${a.live.status} (${a.live.bytes} bytes)`
                        : `● Down right now — ${a.live.error || `HTTP ${a.live.status}`}`}
                    </div>
                  )}
                  <ReceiptTrail receipt={{ status: a.status, attempts: a.attempts, checks: a.checks, evidence: a.evidence }} />
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
