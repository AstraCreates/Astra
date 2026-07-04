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
      if (res.ok) setFlows((await res.json())?.flows || []);
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
      vercel: Boolean(raw?.vercel),
      sendgrid: Boolean(raw?.sendgrid),
      gmail: Boolean(raw?.apps?.gmail || raw?.sendgrid),
      slack: Boolean(raw?.apps?.slack),
      notion: Boolean(raw?.notion),
      linear: Boolean(raw?.linear),
      stripe: Boolean(raw?.apps?.stripe),
      hubspot: Boolean(raw?.apps?.hubspot),
      apollo: Boolean(raw?.apps?.apollo),
      google_calendar: Boolean(raw?.apps?.google_calendar),
      klaviyo: Boolean(raw?.klaviyo),
      printful: Boolean(raw?.printful),
      lemonsqueezy: Boolean(raw?.lemonsqueezy),
      square: Boolean(raw?.square),
      yelp: Boolean(raw?.yelp),
      instagram: Boolean(raw?.instagram),
      tiktok: Boolean(raw?.tiktok),
      meta_ads: Boolean(raw?.meta_ads),
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

  const ACCENT = "#7CFFC6";
  const HG = "var(--font-hanken), 'Hanken Grotesk', sans-serif";

  function chipStyle(tone: "active" | "paused" | "draft"): React.CSSProperties {
    if (tone === "active")  return { padding: "3px 9px", borderRadius: 20, fontSize: 10.5, fontWeight: 600, background: "rgba(124,255,198,.12)", color: "#7CFFC6", border: "1px solid rgba(124,255,198,.25)" };
    if (tone === "paused")  return { padding: "3px 9px", borderRadius: 20, fontSize: 10.5, fontWeight: 600, background: "rgba(255,255,166,.08)", color: "#FFFFA6", border: "1px solid rgba(255,255,166,.20)" };
    return { padding: "3px 9px", borderRadius: 20, fontSize: 10.5, fontWeight: 600, background: "rgba(255,255,255,.06)", color: "#8A93AD", border: "1px solid rgba(255,255,255,.10)" };
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%", fontFamily: HG }}>

      {/* Header */}
      <div style={{ padding: "28px 28px 20px", borderBottom: "1px solid rgba(255,255,255,.07)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: "#EDF1FB", letterSpacing: "-0.02em" }}>Automations</h1>
            <p style={{ margin: "5px 0 0", fontSize: 13, color: "#8A93AD" }}>Build and manage automated workflows and AI agents</p>
          </div>
          <button onClick={() => { loadFlows(); loadOverview(); }} style={{ padding: "7px 14px", fontSize: 12, fontWeight: 500, color: "#8A93AD", background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.10)", borderRadius: 7, cursor: "pointer", fontFamily: HG }}>
            Refresh
          </button>
        </div>
      </div>

      {/* Flash */}
      {flash && (
        <div style={{ margin: "16px 28px 0", padding: "12px 16px", borderRadius: 10, fontSize: 13, color: flash.tone === "success" ? ACCENT : "#ff6b6b", background: flash.tone === "success" ? "rgba(124,255,198,.10)" : "rgba(255,107,107,.09)", border: `1px solid ${flash.tone === "success" ? "rgba(124,255,198,.25)" : "rgba(255,107,107,.28)"}` }}>
          {flash.text}
          <button onClick={() => setFlash(null)} style={{ marginLeft: 12, background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 12, opacity: 0.7 }}>✕</button>
        </div>
      )}

      <div style={{ flex: 1, padding: "24px 28px 48px", display: "flex", flexDirection: "column", gap: 32, overflowY: "auto" }}>

        {/* CTA cards */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <button onClick={() => router.push("/automations/canvas/new")} style={{ padding: "20px 22px", borderRadius: 12, cursor: "pointer", textAlign: "left", background: "rgba(124,255,198,.04)", border: "1px solid rgba(124,255,198,.22)", fontFamily: HG }}>
            <div style={{ fontSize: 20, marginBottom: 8 }}>⚡</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#EDF1FB", marginBottom: 4 }}>Create a workflow automation</div>
            <div style={{ fontSize: 12, color: "#8A93AD" }}>Build a multi-step pipeline with the canvas editor</div>
          </button>
          <button onClick={() => setAgentNewTrigger(n => n + 1)} style={{ padding: "20px 22px", borderRadius: 12, cursor: "pointer", textAlign: "left", background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.08)", fontFamily: HG }}>
            <div style={{ fontSize: 20, marginBottom: 8 }}>🤖</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#EDF1FB", marginBottom: 4 }}>Create a custom agent</div>
            <div style={{ fontSize: 12, color: "#8A93AD" }}>Configure a specialized AI agent with custom instructions</div>
          </button>
        </div>

        {/* Custom agents */}
        <section>
          <h2 style={{ margin: "0 0 14px", fontSize: 13, fontWeight: 700, color: "#6f7b98", letterSpacing: ".06em", textTransform: "uppercase" }}>Custom agents</h2>
          <CustomAgentsPanel embedded externalTriggerNew={agentNewTrigger} />
        </section>

        {/* Workflow automations */}
        <section>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: "#6f7b98", letterSpacing: ".06em", textTransform: "uppercase" }}>Workflow automations</h2>
            <button onClick={() => router.push("/automations/canvas/new")} style={{ padding: "5px 14px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", borderRadius: 7, cursor: "pointer", fontFamily: HG }}>+ New flow</button>
          </div>
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.07)", borderRadius: 12, overflow: "hidden" }}>
            {flowsLoading && (
              <div style={{ padding: "32px", display: "flex", justifyContent: "center" }}>
                <div style={{ width: 18, height: 18, borderRadius: "50%", border: "2px solid rgba(255,255,255,.12)", borderTopColor: "#002EFF", animation: "spin 0.7s linear infinite" }} />
              </div>
            )}
            {!flowsLoading && flows.length === 0 && (
              <div style={{ padding: "40px 24px", textAlign: "center", color: "#6f7b98", fontSize: 13 }}>No flows yet — create one above</div>
            )}
            {!flowsLoading && flows.map((f, i) => (
              <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", borderBottom: i < flows.length - 1 ? "1px solid rgba(255,255,255,.05)" : "none" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: ACCENT, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#EDF1FB" }}>{f.name}</div>
                  <div style={{ fontSize: 11, color: "#6f7b98", marginTop: 2 }}>
                    {f.nodes.length} node{f.nodes.length !== 1 ? "s" : ""}{formatDate(f.updated_at) ? ` · ${formatDate(f.updated_at)}` : ""}
                  </div>
                </div>
                <span style={chipStyle("active")}>Active</span>
                <button onClick={() => router.push(`/automations/canvas/${f.id}`)} style={{ padding: "5px 12px", fontSize: 11, fontWeight: 600, color: "#EDF1FB", background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.10)", borderRadius: 6, cursor: "pointer", fontFamily: HG }}>Open</button>
                <button onClick={() => runFlow(f.id)} disabled={flowRunning === f.id} style={{ padding: "5px 12px", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: HG, opacity: flowRunning === f.id ? 0.6 : 1 }}>
                  {flowRunning === f.id ? "Running…" : "Run"}
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Templates */}
        {overviewStatus === "ready" && overview && overview.templates.length > 0 && (
          <section>
            <h2 style={{ margin: "0 0 14px", fontSize: 13, fontWeight: 700, color: "#6f7b98", letterSpacing: ".06em", textTransform: "uppercase" }}>Templates</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
              {overview.templates.map((t) => (
                <div key={t.key} style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.07)", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#EDF1FB", lineHeight: 1.3 }}>{t.title}</span>
                    <span style={chipStyle(t.installed ? "active" : "draft")}>{t.installed ? "Installed" : t.category || "Template"}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: "#6f7b98", lineHeight: 1.55, flex: 1 }}>{t.summary}</p>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button onClick={() => installTemplate(t.key)} disabled={!!busyKey} style={{ padding: "5px 12px", fontSize: 11, fontWeight: 600, color: "#EDF1FB", background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.10)", borderRadius: 6, cursor: "pointer", fontFamily: HG, opacity: busyKey ? 0.6 : 1 }}>
                      {busyKey === `install:${t.key}` ? "Installing…" : t.installed ? "Reinstall" : "Install"}
                    </button>
                    {t.installed && (
                      <button onClick={() => runTemplate(t.key)} disabled={!!busyKey} style={{ padding: "5px 12px", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", borderRadius: 6, cursor: "pointer", fontFamily: HG, opacity: busyKey ? 0.6 : 1 }}>
                        {busyKey === `run:${t.key}` ? "Running…" : "Run"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
