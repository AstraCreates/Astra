"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, getSetupStatus, SetupStatus, waitForAuthReady } from "@/lib/api";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Overview = {
  provider: string;
  native: boolean;
  runtime: {
    status: string;
    detail: string;
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
    path: string;
    title: string;
    category: string;
    integrations: string[];
    summary: string;
    installed: boolean;
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
  const router = useRouter();
  const { userId } = useDevUser();
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [busyKey, setBusyKey] = useState<string>("");
  const [flash, setFlash] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  async function loadOverview() {
    if (!userId || userId === "anon") return;
    setStatus("loading");
    await waitForAuthReady();
    const res = await apiFetch(`${BASE}/automations/overview?founder_id=${encodeURIComponent(userId)}`);
    if (!res.ok) throw new Error(String(res.status));
    setOverview(await res.json());
    try {
      setSetupStatus(await getSetupStatus(userId));
    } catch {
      setSetupStatus(null);
    }
    setStatus("ready");
  }

  useEffect(() => {
    if (!userId || userId === "anon") return;
    let cancelled = false;

    async function load() {
      try {
        await loadOverview();
      } catch {
        if (!cancelled) setStatus("error");
      }
    }

    load();
    return () => { cancelled = true; };
  }, [userId]);

  async function installAll() {
    if (!userId) return;
    try {
      setBusyKey("install_all");
      const res = await apiFetch(`${BASE}/automations/templates/install_all?founder_id=${encodeURIComponent(userId)}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || String(res.status));
      setFlash({ tone: "success", text: `Installed ${data.installed?.length || 0} starter automations.` });
      await loadOverview();
    } catch (e) {
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not install starter automations." });
    } finally {
      setBusyKey("");
    }
  }

  async function installTemplate(templateKey: string) {
    if (!userId) return;
    try {
      setBusyKey(`install:${templateKey}`);
      const res = await apiFetch(`${BASE}/automations/templates/${encodeURIComponent(templateKey)}/install?founder_id=${encodeURIComponent(userId)}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || String(res.status));
      setFlash({ tone: "success", text: `${data.title || "Automation"} installed.` });
      await loadOverview();
    } catch (e) {
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not install automation." });
    } finally {
      setBusyKey("");
    }
  }

  async function runTemplate(templateKey: string) {
    if (!userId) return;
    try {
      setBusyKey(`run:${templateKey}`);
      const res = await apiFetch(`${BASE}/automations/templates/${encodeURIComponent(templateKey)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId, payload: {} }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || String(res.status));
      const runId = data?.result?.job_id || data?.result?.id || data?.result?.uuid || "queued";
      setFlash({ tone: "success", text: `Automation run started (${runId}).` });
    } catch (e) {
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not start automation run." });
    } finally {
      setBusyKey("");
    }
  }

  const runtimeTone = useMemo(() => tone(overview?.runtime.status || "standby"), [overview?.runtime.status]);
  const connectorState = useMemo(() => {
    const raw = setupStatus;
    return {
      github: Boolean(raw?.github),
      gmail: Boolean(raw?.apps?.gmail || raw?.sendgrid),
      slack: Boolean(raw?.apps?.slack),
      notion: Boolean(raw?.notion),
      linear: Boolean(raw?.linear),
      stripe: Boolean(raw?.apps?.stripe),
      hubspot: Boolean(raw?.apps?.hubspot),
      apollo: Boolean(raw?.apps?.apollo),
      google_calendar: Boolean(raw?.apps?.google_calendar),
      klaviyo: Boolean(raw?.klaviyo),
    } as Record<string, boolean>;
  }, [setupStatus]);
  const stats = overview ? [
    { label: "Surface", value: overview.native ? "Astra-native" : "External" },
    { label: "Workflows", value: String(overview.workflow_count) },
    { label: "Runtime", value: runtimeTone.label },
  ] : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%", background: SURFACE_BG }}>
      <PageHeader
        title="Automations"
        subtitle="Run workflow automation inside Astra without a separate login."
        badge={{ label: "native beta", color: "blue" }}
        stats={stats}
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            <HeaderSecondaryBtn label="Refresh" onClick={() => window.location.reload()} />
            <HeaderPrimaryBtn label="+ New automation" onClick={() => router.push("/automations/canvas/new")} />
          </div>
        }
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
            {flash && (
              <div style={cardStyle({
                padding: 16,
                color: flash.tone === "success" ? "#0F8A4B" : "#991B1B",
                border: `1px solid ${flash.tone === "success" ? "rgba(27,169,92,0.22)" : "rgba(185,28,28,0.18)"}`,
              })}>
                {flash.text}
              </div>
            )}
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
                    color: runtimeTone.color,
                    background: runtimeTone.background,
                    border: `1px solid ${runtimeTone.border}`,
                    fontSize: 12,
                    fontWeight: 700,
                  }}>
                    {runtimeTone.label}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "var(--fg-mute)", maxWidth: 760 }}>
                  {overview.runtime.detail}
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
                    <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Runtime</div>
                    <div style={{ marginTop: 6, fontSize: 18, fontWeight: 700 }}>Astra-managed</div>
                    <div style={{ marginTop: 6, fontSize: 13, color: "var(--fg-mute)" }}>Execution runs behind Astra instead of exposing a separate vendor app.</div>
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
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 13, color: "var(--fg-mute)" }}>These are the first flows we should turn into one-click Astra actions.</div>
                  <button
                    onClick={installAll}
                    disabled={busyKey === "install_all"}
                    style={{
                      borderRadius: 12,
                      border: "1px solid rgba(0,26,255,0.16)",
                      background: "#001AFF",
                      color: "#fff",
                      fontSize: 12,
                      fontWeight: 700,
                      padding: "10px 14px",
                      cursor: "pointer",
                      opacity: busyKey === "install_all" ? 0.7 : 1,
                    }}
                  >
                    {busyKey === "install_all" ? "Installing..." : "Install all"}
                  </button>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
                {overview.templates.map((template) => (
                  <div key={template.key} style={cardStyle({ padding: 18, background: "linear-gradient(180deg, #FFFFFF 0%, #F8FAFF 100%)", boxShadow: "none" })}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 5 }}>{template.category}</div>
                        <div style={{ fontSize: 16, fontWeight: 700 }}>{template.title}</div>
                      </div>
                      <span style={{
                        padding: "4px 8px",
                        borderRadius: 999,
                        fontSize: 10,
                        fontWeight: 700,
                        color: template.installed ? "#0F8A4B" : "var(--fg-mute)",
                        background: template.installed ? "rgba(27,169,92,0.10)" : "rgba(148,163,184,0.12)",
                        border: `1px solid ${template.installed ? "rgba(27,169,92,0.22)" : "rgba(148,163,184,0.18)"}`,
                      }}>
                        {template.installed ? "Installed" : "Template"}
                      </span>
                    </div>
                    <div style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6, color: "var(--fg-mute)" }}>{template.summary}</div>
                    {template.integrations.length > 0 && (
                      <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {template.integrations.map((integration) => {
                          const connected = Boolean(connectorState[integration]);
                          return (
                            <span
                              key={`${template.key}:${integration}`}
                              style={{
                                padding: "5px 8px",
                                borderRadius: 999,
                                fontSize: 10,
                                fontWeight: 700,
                                color: connected ? "#0F8A4B" : "#7C2D12",
                                background: connected ? "rgba(27,169,92,0.10)" : "rgba(251,146,60,0.10)",
                                border: `1px solid ${connected ? "rgba(27,169,92,0.22)" : "rgba(251,146,60,0.22)"}`,
                              }}
                            >
                              {integration.replace(/_/g, " ")} {connected ? "connected" : "needed"}
                            </span>
                          );
                        })}
                      </div>
                    )}
                    <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <button
                        onClick={() => installTemplate(template.key)}
                        disabled={busyKey === `install:${template.key}`}
                        style={{
                          borderRadius: 10,
                          border: "1px solid rgba(15,23,42,0.10)",
                          background: "#fff",
                          color: "var(--fg)",
                          fontSize: 12,
                          fontWeight: 700,
                          padding: "9px 12px",
                          cursor: "pointer",
                        }}
                      >
                        {busyKey === `install:${template.key}` ? "Installing..." : (template.installed ? "Update flow" : "Install flow")}
                      </button>
                      {template.installed && (
                        <button
                          onClick={() => runTemplate(template.key)}
                          disabled={busyKey === `run:${template.key}`}
                          style={{
                            borderRadius: 10,
                            border: "1px solid rgba(0,26,255,0.16)",
                            background: "rgba(0,26,255,0.08)",
                            color: "#001AFF",
                            fontSize: 12,
                            fontWeight: 700,
                            padding: "9px 12px",
                            cursor: "pointer",
                          }}
                        >
                          {busyKey === `run:${template.key}` ? "Running..." : "Run demo"}
                        </button>
                      )}
                      {template.integrations.some((integration) => !connectorState[integration]) && (
                        <button
                          onClick={() => router.push("/integrations")}
                          style={{
                            borderRadius: 10,
                            border: "1px solid rgba(245,158,11,0.24)",
                            background: "rgba(251,191,36,0.10)",
                            color: "#92400E",
                            fontSize: 12,
                            fontWeight: 700,
                            padding: "9px 12px",
                            cursor: "pointer",
                          }}
                        >
                          Connect integrations
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section style={cardStyle({ padding: 24, display: "grid", gap: 16 })}>
              <div>
                <div style={{ fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Automation data</div>
                <h3 style={{ margin: "6px 0 0", fontSize: 20 }}>Recent flows</h3>
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
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 12, color: "var(--fg-mute)", fontFamily: "var(--font-code)" }}>{workflow.id}</span>
                        {overview.templates.find((template) => template.path === workflow.id)?.installed && (
                          <button
                            onClick={() => runTemplate(overview.templates.find((template) => template.path === workflow.id)!.key)}
                            disabled={busyKey === `run:${overview.templates.find((template) => template.path === workflow.id)!.key}`}
                            style={{
                              borderRadius: 10,
                              border: "1px solid rgba(0,26,255,0.16)",
                              background: "rgba(0,26,255,0.08)",
                              color: "#001AFF",
                              fontSize: 11,
                              fontWeight: 700,
                              padding: "8px 10px",
                              cursor: "pointer",
                            }}
                          >
                            Run
                          </button>
                        )}
                      </div>
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
                  No flows are being listed yet. The native Astra surface is live, and this panel will populate once the automation runtime is fully connected.
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
