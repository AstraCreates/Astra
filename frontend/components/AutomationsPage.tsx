"use client";

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

function statusTone(status: string) {
  if (status === "connected")   return { label: "Connected",    color: "var(--green)", bg: "var(--gdim)", border: "var(--gb)" };
  if (status === "degraded")    return { label: "Degraded",     color: "var(--amber)", bg: "var(--adim)", border: "var(--ab)" };
  if (status === "setup_needed") return { label: "Setup needed", color: "var(--amber)", bg: "var(--adim)", border: "var(--ab)" };
  return { label: "Standby", color: "var(--fm)", bg: "rgba(148,163,184,0.10)", border: "rgba(148,163,184,0.18)" };
}

function formatDate(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
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
    (async () => {
      try { await loadOverview(); }
      catch { if (!cancelled) setStatus("error"); }
    })();
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

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <PageHeader
        title="Automations"
        badge={{ label: "native beta", color: "blue" }}
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {overview && (
              <span style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                color: rt.color, background: rt.bg, border: `1px solid ${rt.border}`,
                borderRadius: 999,
              }}>{rt.label}</span>
            )}
            <HeaderSecondaryBtn label="Refresh" onClick={() => window.location.reload()} />
            <HeaderPrimaryBtn label="+ New flow" onClick={() => router.push("/automations/canvas/new")} />
          </div>
        }
      />

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Flash */}
        {flash && (
          <div style={{
            padding: "12px 16px", borderRadius: 10, fontSize: 13,
            color: flash.tone === "success" ? "var(--green)" : "var(--red)",
            background: flash.tone === "success" ? "var(--gdim)" : "var(--rdim)",
            border: `1px solid ${flash.tone === "success" ? "var(--gb)" : "var(--rb)"}`,
          }}>
            {flash.text}
            <button onClick={() => setFlash(null)} style={{ marginLeft: 12, background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 12, opacity: 0.7 }}>✕</button>
          </div>
        )}

        {status === "loading" && (
          <div style={{ padding: "48px 0", display: "flex", justifyContent: "center" }}>
            <div style={{ width: 20, height: 20, borderRadius: "50%", border: "2px solid var(--bd2)", borderTopColor: "var(--blue)", animation: "spin 0.7s linear infinite" }} />
          </div>
        )}

        {status === "error" && (
          <div className="err-banner" style={{ borderRadius: 10 }}>
            Could not load automations. Refresh and try again.
          </div>
        )}

        {status === "ready" && overview && (
          <>
            {/* Templates */}
            <section>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Starter templates</h2>
                  <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--fm)" }}>
                    One-click automations to get going fast.
                  </p>
                </div>
                <button
                  onClick={installAll}
                  disabled={busyKey === "install_all"}
                  className="btn pri"
                  style={{ whiteSpace: "nowrap" }}
                >
                  {busyKey === "install_all" ? "Installing…" : "Install all"}
                </button>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
                {overview.templates.map((t) => (
                  <div key={t.key} style={{
                    background: "var(--surface)",
                    border: "1px solid var(--bd)",
                    borderRadius: 12,
                    padding: "16px 18px",
                    backdropFilter: "var(--glass-blur)",
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
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

            {/* Recent flows */}
            <section>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Recent flows</h2>
              </div>

              {overview.workflows.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {overview.workflows.map((w, i) => {
                    const linkedTemplate = overview.templates.find((t) => t.path === w.id);
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
                          {linkedTemplate?.installed && (
                            <button
                              onClick={() => runTemplate(linkedTemplate.key)}
                              disabled={!!busyKey}
                              className="btn pri sm"
                            >
                              {busyKey === `run:${linkedTemplate.key}` ? "Running…" : "Run"}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty" style={{ padding: "40px 20px", border: "1px dashed var(--bd2)", borderRadius: 12, background: "var(--surface)" }}>
                  <div className="empty-title">No flows yet</div>
                  <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 4 }}>
                    Build your first flow or install a template above.
                  </div>
                  <button
                    onClick={() => router.push("/automations/canvas/new")}
                    className="btn pri"
                    style={{ marginTop: 14 }}
                  >
                    + New flow
                  </button>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
