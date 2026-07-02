"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, waitForAuthReady } from "@/lib/api";
import PageHeader, { HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Overview = {
  provider: string;
  native: boolean;
  engine: {
    name: string;
    status: string;
    detail: string;
    source: string;
  };
  workflows: Array<{
    id: string;
    name: string;
    active: boolean;
    updated_at?: string | null;
  }>;
  workflow_count: number;
  templates: Array<{
    key: string;
    title: string;
    summary: string;
  }>;
  next_steps: string[];
};

const SURFACE_BG = "linear-gradient(180deg, rgba(0,26,255,0.08) 0%, rgba(0,26,255,0.02) 20%, rgba(255,255,255,0) 100%)";

function tone(status: string): { label: string; color: string; background: string; border: string } {
  if (status === "connected") {
    return { label: "Connected", color: "#0F8A4B", background: "rgba(27, 169, 92, 0.10)", border: "rgba(27, 169, 92, 0.22)" };
  }
  if (status === "degraded") {
    return { label: "Degraded", color: "#B45309", background: "rgba(245, 158, 11, 0.10)", border: "rgba(245, 158, 11, 0.22)" };
  }
  if (status === "setup_needed") {
    return { label: "Setup needed", color: "#7C2D12", background: "rgba(251, 146, 60, 0.10)", border: "rgba(251, 146, 60, 0.22)" };
  }
  return { label: "Standby", color: "var(--fg-mute)", background: "rgba(148, 163, 184, 0.12)", border: "rgba(148, 163, 184, 0.18)" };
}

function formatDate(value?: string | null): string {
  if (!value) return "No recent update";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No recent update";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function cardStyle(extra?: CSSProperties): CSSProperties {
  return {
    background: "rgba(255,255,255,0.92)",
    border: "1px solid rgba(15, 23, 42, 0.08)",
    borderRadius: 22,
    boxShadow: "0 20px 60px rgba(15, 23, 42, 0.06)",
    ...extra,
  };
}

export default function AutomationsPage() {
  const { userId } = useDevUser();
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [overview, setOverview] = useState<Overview | null>(null);

  useEffect(() => {
    if (!userId || userId === "anon") return;
    let cancelled = false;

    async function load() {
      try {
        setStatus("loading");
        await waitForAuthReady();
        const res = await apiFetch(`${BASE}/automations/overview?founder_id=${encodeURIComponent(userId)}`);
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!cancelled) {
          setOverview(data);
          setStatus("ready");
        }
      } catch {
        if (!cancelled) setStatus("error");
      }
    }

    load();
    return () => { cancelled = true; };
  }, [userId]);

  const engineTone = useMemo(() => tone(overview?.engine.status || "standby"), [overview?.engine.status]);
  const stats = overview ? [
    { label: "Surface", value: overview.native ? "Astra-native" : "External" },
    { label: "Workflows", value: String(overview.workflow_count) },
    { label: "Engine", value: engineTone.label },
  ] : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%", background: SURFACE_BG }}>
      <PageHeader
        title="Automations"
        subtitle="Run workflow automation inside Astra without a separate login."
        badge={{ label: "native beta", color: "blue" }}
        stats={stats}
        actions={<HeaderSecondaryBtn label="Refresh" onClick={() => window.location.reload()} />}
      />

      <div style={{ padding: 24, display: "grid", gap: 18 }}>
        {status === "loading" && (
          <div style={cardStyle({ padding: 24, color: "var(--fg-mute)" })}>
            Loading your automations workspace…
          </div>
        )}

        {status === "error" && (
          <div style={cardStyle({ padding: 24, color: "#991B1B" })}>
            Astra couldn&apos;t load the automations overview right now. Refresh and try again.
          </div>
        )}

        {status === "ready" && overview && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 18 }}>
              <section style={cardStyle({ padding: 24, display: "grid", gap: 14 })}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Workspace</div>
                    <h2 style={{ margin: "6px 0 0", fontSize: 26, lineHeight: 1.1 }}>Astra owns the automation experience now.</h2>
                  </div>
                  <span style={{
                    padding: "8px 12px",
                    borderRadius: 999,
                    color: engineTone.color,
                    background: engineTone.background,
                    border: `1px solid ${engineTone.border}`,
                    fontSize: 12,
                    fontWeight: 700,
                  }}>
                    {engineTone.label}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "var(--fg-mute)", maxWidth: 760 }}>
                  {overview.engine.detail}
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                  <div style={cardStyle({ padding: 16, background: "#F8FAFF", boxShadow: "none" })}>
                    <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Auth</div>
                    <div style={{ marginTop: 6, fontSize: 18, fontWeight: 700 }}>Astra only</div>
                    <div style={{ marginTop: 6, fontSize: 13, color: "var(--fg-mute)" }}>No extra sign-in wall inside this tab.</div>
                  </div>
                  <div style={cardStyle({ padding: 16, background: "#F8FAFF", boxShadow: "none" })}>
                    <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Builder</div>
                    <div style={{ marginTop: 6, fontSize: 18, fontWeight: 700 }}>Native shell</div>
                    <div style={{ marginTop: 6, fontSize: 13, color: "var(--fg-mute)" }}>Stable UI inside Astra instead of an embedded app runtime.</div>
                  </div>
                  <div style={cardStyle({ padding: 16, background: "#F8FAFF", boxShadow: "none" })}>
                    <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Engine</div>
                    <div style={{ marginTop: 6, fontSize: 18, fontWeight: 700 }}>{overview.engine.name}</div>
                    <div style={{ marginTop: 6, fontSize: 13, color: "var(--fg-mute)" }}>{overview.engine.source === "n8n" ? "Using engine data directly." : "Engine integration is being phased in."}</div>
                  </div>
                </div>
              </section>

              <aside style={cardStyle({ padding: 24, display: "grid", gap: 14, alignContent: "start" })}>
                <div>
                  <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Next</div>
                  <h3 style={{ margin: "6px 0 0", fontSize: 20 }}>What this tab is for</h3>
                </div>
                <div style={{ display: "grid", gap: 10 }}>
                  {overview.next_steps.map((step) => (
                    <div key={step} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                      <div style={{ width: 8, height: 8, borderRadius: 999, background: "#001AFF", marginTop: 6 }} />
                      <div style={{ fontSize: 14, lineHeight: 1.5 }}>{step}</div>
                    </div>
                  ))}
                </div>
              </aside>
            </div>

            <section style={cardStyle({ padding: 24, display: "grid", gap: 16 })}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Templates</div>
                  <h3 style={{ margin: "6px 0 0", fontSize: 20 }}>Starter automations</h3>
                </div>
                <div style={{ fontSize: 13, color: "var(--fg-mute)" }}>These are the first flows we should turn into one-click Astra actions.</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
                {overview.templates.map((template) => (
                  <div key={template.key} style={cardStyle({ padding: 18, background: "linear-gradient(180deg, #FFFFFF 0%, #F8FAFF 100%)", boxShadow: "none" })}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>{template.title}</div>
                    <div style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6, color: "var(--fg-mute)" }}>{template.summary}</div>
                  </div>
                ))}
              </div>
            </section>

            <section style={cardStyle({ padding: 24, display: "grid", gap: 16 })}>
              <div>
                <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Engine data</div>
                <h3 style={{ margin: "6px 0 0", fontSize: 20 }}>Recent workflows</h3>
              </div>

              {overview.workflows.length > 0 ? (
                <div style={{ display: "grid", gap: 10 }}>
                  {overview.workflows.map((workflow) => (
                    <div key={workflow.id} style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0, 1fr) auto auto",
                      gap: 12,
                      alignItems: "center",
                      padding: "14px 16px",
                      borderRadius: 18,
                      border: "1px solid rgba(15,23,42,0.08)",
                      background: "#FCFDFF",
                    }}>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 700 }}>{workflow.name}</div>
                        <div style={{ marginTop: 4, fontSize: 12, color: "var(--fg-mute)" }}>Updated {formatDate(workflow.updated_at)}</div>
                      </div>
                      <span style={{
                        padding: "6px 10px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 700,
                        color: workflow.active ? "#0F8A4B" : "var(--fg-mute)",
                        background: workflow.active ? "rgba(27,169,92,0.10)" : "rgba(148,163,184,0.12)",
                        border: `1px solid ${workflow.active ? "rgba(27,169,92,0.22)" : "rgba(148,163,184,0.18)"}`,
                      }}>
                        {workflow.active ? "Active" : "Draft"}
                      </span>
                      <span style={{ fontSize: 12, color: "var(--fg-mute)", fontFamily: "var(--font-code)" }}>{workflow.id}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{
                  padding: 20,
                  borderRadius: 18,
                  border: "1px dashed rgba(15, 23, 42, 0.14)",
                  color: "var(--fg-mute)",
                  background: "rgba(248,250,252,0.7)",
                }}>
                  No workflows are being listed yet. The native Astra surface is live, and the engine connection will populate here once workflow listing is configured.
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
