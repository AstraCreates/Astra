"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, getSetupStatus, SetupStatus, waitForAuthReady } from "@/lib/api";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";
import CustomAgentsPanel from "@/components/CustomAgentsPanel";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Tab = "flows" | "agents" | "templates";

type Overview = {
  provider: string;
  native: boolean;
  runtime: { status: string; detail: string };
  workflows: Array<{ id: string; name: string; active: boolean; updated_at?: string | null }>;
  workflow_count: number;
  templates: Array<{
    key: string; path: string; title: string;
    category: string; integrations: string[];
    summary: string; installed: boolean;
  }>;
  next_steps: string[];
};

type CanvasFlow = {
  id: string;
  name: string;
  nodes: Array<{ type: string }>;
  updated_at: string;
};

function statusTone(status: string) {
  if (status === "connected")    return { label: "Connected",    color: "var(--green)", bg: "var(--gdim)", border: "var(--gb)" };
  if (status === "degraded")     return { label: "Degraded",     color: "var(--amber)", bg: "var(--adim)", border: "var(--ab)" };
  if (status === "setup_needed") return { label: "Setup needed", color: "var(--amber)", bg: "var(--adim)", border: "var(--ab)" };
  return { label: "Standby", color: "var(--fm)", bg: "rgba(148,163,184,0.10)", border: "rgba(148,163,184,0.18)" };
}

function formatDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
}

const TAB_LABELS: Record<Tab, string> = { flows: "Flows", agents: "Agents", templates: "Templates" };

export default function AutomationsPage() {
  const router = useRouter();
  const { userId } = useDevUser();

  // Tab
  const [tab, setTab] = useState<Tab>("flows");
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const t = p.get("tab") as Tab | null;
    if (t === "agents" || t === "templates" || t === "flows") setTab(t);
  }, []);

  // Templates / overview data
  const [overviewStatus, setOverviewStatus] = useState<"loading" | "ready" | "error">("loading");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [busyKey, setBusyKey] = useState<string>("");
  const [flash, setFlash] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  // Canvas flows
  const [flows, setFlows] = useState<CanvasFlow[]>([]);
  const [flowsLoading, setFlowsLoading] = useState(false);
  const [flowRunning, setFlowRunning] = useState<string>("");

  // Agent panel trigger
  const [agentNewTrigger, setAgentNewTrigger] = useState(0);

  async function loadOverview() {
    if (!userId || userId === "anon") return;
    setOverviewStatus("loading");
    await waitForAuthReady();
    const res = await apiFetch(`${BASE}/automations/overview?founder_id=${encodeURIComponent(userId)}`);
    if (!res.ok) throw new Error(String(res.status));
    setOverview(await res.json());
    try { setSetupStatus(await getSetupStatus(userId)); } catch { setSetupStatus(null); }
    setOverviewStatus("ready");
  }

  async function loadFlows() {
    if (!userId || userId === "anon") return;
    setFlowsLoading(true);
    try {
      await waitForAuthReady();
      const res = await apiFetch(`${BASE}/automations/flows?founder_id=${encodeURIComponent(userId)}`);
      if (res.ok) setFlows((await res.json()) || []);
    } finally {
      setFlowsLoading(false);
    }
  }

  useEffect(() => {
    if (!userId || userId === "anon") return;
    let cancelled = false;
    (async () => {
      try { await loadOverview(); }
      catch { if (!cancelled) setOverviewStatus("error"); }
    })();
    return () => { cancelled = true; };
  }, [userId]);

  useEffect(() => {
    if (tab === "flows" && userId && userId !== "anon") loadFlows();
  }, [tab, userId]);

  async function runFlow(flowId: string) {
    if (!userId) return;
    setFlowRunning(flowId);
    try {
      const res = await apiFetch(`${BASE}/automations/flows/${encodeURIComponent(flowId)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || String(res.status));
      setFlash({ tone: "success", text: `Flow started (${data?.run_id || "queued"}).` });
    } catch (e) {
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not start flow." });
    } finally {
      setFlowRunning("");
    }
  }

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
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not install." });
    } finally { setBusyKey(""); }
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
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not install." });
    } finally { setBusyKey(""); }
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
      setFlash({ tone: "success", text: `Run started (${runId}).` });
    } catch (e) {
      setFlash({ tone: "error", text: e instanceof Error ? e.message : "Could not start run." });
    } finally { setBusyKey(""); }
  }

  const rt = useMemo(() => statusTone(overview?.runtime.status || "standby"), [overview?.runtime.status]);
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

  const headerAction =
    tab === "flows" ? (
      <HeaderPrimaryBtn label="+ New flow" onClick={() => router.push("/automations/canvas/new")} />
    ) : tab === "agents" ? (
      <HeaderPrimaryBtn label="+ New agent" onClick={() => setAgentNewTrigger((n) => n + 1)} />
    ) : (
      <HeaderPrimaryBtn label="Install all" onClick={installAll} disabled={busyKey === "install_all"} />
    );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <PageHeader
        title="Automations"
        badge={{ label: "beta", color: "blue" }}
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {overview && tab !== "agents" && (
              <span style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                color: rt.color, background: rt.bg, border: `1px solid ${rt.border}`,
                borderRadius: 999,
              }}>{rt.label}</span>
            )}
            <HeaderSecondaryBtn label="Refresh" onClick={() => { loadFlows(); loadOverview(); }} />
            {headerAction}
          </div>
        }
      />

      {/* Tab bar */}
      <div style={{
        display: "flex", gap: 0, padding: "0 24px",
        borderBottom: "1px solid var(--bd)",
        background: "var(--surface)",
        flexShrink: 0,
      }}>
        {(["flows", "agents", "templates"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "11px 16px",
              fontSize: 13,
              fontWeight: tab === t ? 600 : 400,
              color: tab === t ? "var(--blue)" : "var(--fm)",
              background: "none",
              border: "none",
              borderBottom: tab === t ? "2px solid var(--blue)" : "2px solid transparent",
              marginBottom: -1,
              cursor: "pointer",
              transition: "color 0.15s, border-color 0.15s",
            }}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Flash */}
      {flash && (
        <div style={{
          margin: "16px 24px 0",
          padding: "12px 16px", borderRadius: 10, fontSize: 13,
          color: flash.tone === "success" ? "var(--green)" : "var(--red)",
          background: flash.tone === "success" ? "var(--gdim)" : "var(--rdim)",
          border: `1px solid ${flash.tone === "success" ? "var(--gb)" : "var(--rb)"}`,
        }}>
          {flash.text}
          <button onClick={() => setFlash(null)} style={{ marginLeft: 12, background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 12, opacity: 0.7 }}>✕</button>
        </div>
      )}

      {/* ── Flows tab ────────────────────────────────────────────── */}
      {tab === "flows" && (
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
          {flowsLoading && (
            <div style={{ padding: "48px 0", display: "flex", justifyContent: "center" }}>
              <div style={{ width: 20, height: 20, borderRadius: "50%", border: "2px solid var(--bd2)", borderTopColor: "var(--blue)", animation: "spin 0.7s linear infinite" }} />
            </div>
          )}
          {!flowsLoading && flows.length === 0 && (
            <div className="empty" style={{ padding: "60px 20px", border: "1px dashed var(--bd2)", borderRadius: 12, background: "var(--surface)" }}>
              <div className="empty-title">No canvas flows yet</div>
              <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 4 }}>Build a multi-step agent pipeline from scratch.</div>
              <button onClick={() => router.push("/automations/canvas/new")} className="btn pri" style={{ marginTop: 14 }}>
                + New flow
              </button>
            </div>
          )}
          {!flowsLoading && flows.length > 0 && flows.map((f, i) => (
            <div key={f.id} className="sc-row" style={{
              "--i": i,
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto auto auto",
              alignItems: "center",
              gap: 12,
              padding: "14px 16px",
              background: "var(--surface)",
              border: "1px solid var(--bd)",
              borderRadius: 10,
              backdropFilter: "var(--glass-blur)",
            } as React.CSSProperties}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{f.name}</div>
                <div style={{ marginTop: 2, fontSize: 11, color: "var(--fm)" }}>
                  {f.nodes.length} node{f.nodes.length !== 1 ? "s" : ""}
                  {formatDate(f.updated_at) ? ` · Updated ${formatDate(f.updated_at)}` : ""}
                </div>
              </div>
              <span className="pill">{f.nodes.filter((n) => n.type === "agent").length} agents</span>
              <button onClick={() => router.push(`/automations/canvas/${f.id}`)} className="btn sm">Open</button>
              <button onClick={() => runFlow(f.id)} disabled={flowRunning === f.id} className="btn pri sm">
                {flowRunning === f.id ? "Running…" : "Run"}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ── Agents tab ───────────────────────────────────────────── */}
      {tab === "agents" && (
        <CustomAgentsPanel embedded externalTriggerNew={agentNewTrigger} />
      )}

      {/* ── Templates tab ────────────────────────────────────────── */}
      {tab === "templates" && (
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
          {overviewStatus === "loading" && (
            <div style={{ padding: "48px 0", display: "flex", justifyContent: "center" }}>
              <div style={{ width: 20, height: 20, borderRadius: "50%", border: "2px solid var(--bd2)", borderTopColor: "var(--blue)", animation: "spin 0.7s linear infinite" }} />
            </div>
          )}
          {overviewStatus === "error" && (
            <div className="err-banner" style={{ borderRadius: 10 }}>
              Could not load templates. Refresh and try again.
            </div>
          )}
          {overviewStatus === "ready" && overview && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
                {overview.templates.map((t) => (
                  <div key={t.key} style={{
                    background: "var(--surface)", border: "1px solid var(--bd)",
                    borderRadius: 12, padding: "16px 18px",
                    backdropFilter: "var(--glass-blur)",
                    display: "flex", flexDirection: "column", gap: 10,
                  }}>
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ minWidth: 0 }}>
                        {t.category && (
                          <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)", marginBottom: 4 }}>{t.category}</div>
                        )}
                        <span style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.3 }}>{t.title}</span>
                      </div>
                      <span className={`pill ${t.installed ? "green" : ""}`} style={{ flexShrink: 0 }}>
                        {t.installed ? "Installed" : "Template"}
                      </span>
                    </div>
                    <p style={{ margin: 0, fontSize: 13, color: "var(--fm)", lineHeight: 1.55, flex: 1 }}>{t.summary}</p>
                    {t.integrations?.length > 0 && (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {t.integrations.map((integration) => {
                          const connected = Boolean(connectorState[integration]);
                          return (
                            <span key={`${t.key}:${integration}`} className={`pill ${connected ? "green" : "amber"}`}>
                              {integration.replace(/_/g, " ")} {connected ? "✓" : "needed"}
                            </span>
                          );
                        })}
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 8 }}>
                      <button onClick={() => installTemplate(t.key)} disabled={!!busyKey} className="btn sm">
                        {busyKey === `install:${t.key}` ? "Installing…" : t.installed ? "Reinstall" : "Install"}
                      </button>
                      {t.installed && (
                        <button onClick={() => runTemplate(t.key)} disabled={!!busyKey} className="btn pri sm">
                          {busyKey === `run:${t.key}` ? "Running…" : "Run"}
                        </button>
                      )}
                      {t.integrations?.some((i) => !connectorState[i]) && (
                        <button onClick={() => router.push("/integrations")} className="btn sm" style={{ color: "var(--amber)", borderColor: "var(--ab)" }}>
                          Connect
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Installed template flows */}
              {overview.workflows.length > 0 && (
                <section>
                  <h2 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700 }}>Installed flows</h2>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {overview.workflows.map((w, i) => {
                      const linked = overview.templates.find((t) => t.path === w.id);
                      return (
                        <div key={w.id} className="sc-row" style={{
                          "--i": i,
                          display: "grid",
                          gridTemplateColumns: "minmax(0, 1fr) auto auto",
                          alignItems: "center",
                          gap: 12,
                          padding: "12px 16px",
                          background: "var(--surface)",
                          border: "1px solid var(--bd)",
                          borderRadius: 10,
                          backdropFilter: "var(--glass-blur)",
                        } as React.CSSProperties}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{w.name}</div>
                            {formatDate(w.updated_at) && (
                              <div style={{ marginTop: 2, fontSize: 11, color: "var(--fm)" }}>Updated {formatDate(w.updated_at)}</div>
                            )}
                          </div>
                          <span className={`pill ${w.active ? "green" : ""}`}>{w.active ? "Active" : "Draft"}</span>
                          <div style={{ display: "flex", gap: 8 }}>
                            {linked?.installed && (
                              <button onClick={() => runTemplate(linked.key)} disabled={!!busyKey} className="btn pri sm">
                                {busyKey === `run:${linked.key}` ? "Running…" : "Run"}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
