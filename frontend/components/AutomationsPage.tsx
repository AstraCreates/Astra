"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import {
  apiFetch,
  listCustomAgents,
  createCustomAgent,
  runCustomAgent,
  waitForAuthReady,
  type CustomAgent,
} from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type CanvasFlow = {
  id: string;
  name: string;
  nodes: Array<{ type: string }>;
  updated_at: string;
};

type OverviewWorkflow = {
  id: string;
  name: string;
  active: boolean;
  updated_at?: string | null;
};

// ── Status chip ───────────────────────────────────────────────────────────────
type ChipTone = "active" | "paused" | "draft";
function Chip({ tone }: { tone: ChipTone }) {
  const styles: Record<ChipTone, { fg: string; bg: string; label: string }> = {
    active: { fg: "#7d8fff", bg: "rgba(125,143,255,.12)", label: "Active" },
    paused: { fg: "#FFFFA6", bg: "rgba(255,255,166,.08)", label: "Paused" },
    draft:  { fg: "#c3cbe0", bg: "rgba(255,255,255,.06)", label: "Draft" },
  };
  const s = styles[tone];
  return (
    <span style={{
      padding: "3px 9px", borderRadius: 20, fontSize: 10.5, fontWeight: 600,
      background: s.bg, color: s.fg, whiteSpace: "nowrap", flexShrink: 0,
    }}>{s.label}</span>
  );
}

function agentTone(a: CustomAgent): ChipTone {
  if (!a.schedule) return "draft";
  return a.schedule.enabled ? "active" : "paused";
}

function agentMeta(a: CustomAgent): string {
  const parts: string[] = [];
  if (a.role) parts.push(a.role);
  if (a.schedule?.enabled) {
    const days = a.schedule.every_days;
    parts.push(`Runs every ${days === 1 ? "day" : `${days} days`}`);
  }
  return parts.join(" · ");
}

function formatDate(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  if (isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(d);
}

// ── Flash ─────────────────────────────────────────────────────────────────────
function Flash({ msg, onClose }: { msg: { tone: "success" | "error"; text: string }; onClose: () => void }) {
  return (
    <div style={{
      padding: "11px 16px", borderRadius: 9, fontSize: 13, marginBottom: 14,
      color: msg.tone === "success" ? "#7d8fff" : "#f87171",
      background: msg.tone === "success" ? "rgba(125,143,255,.1)" : "rgba(248,113,113,.1)",
      border: `1px solid ${msg.tone === "success" ? "rgba(125,143,255,.3)" : "rgba(248,113,113,.3)"}`,
      display: "flex", alignItems: "center", justifyContent: "space-between",
    }}>
      {msg.text}
      <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 13, opacity: 0.7, padding: "0 0 0 12px" }}>✕</button>
    </div>
  );
}

// ── New agent drawer ──────────────────────────────────────────────────────────
function NewAgentDrawer({ onClose, onCreated }: { onClose: () => void; onCreated: (a: CustomAgent) => void }) {
  const { userId } = useDevUser();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    if (!name.trim() || !role.trim()) { setErr("Name and role are required."); return; }
    setBusy(true); setErr("");
    try {
      const a = await createCustomAgent(userId, { name: name.trim(), role: role.trim(), tool_keys: [] });
      onCreated(a);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create agent.");
    } finally { setBusy(false); }
  }

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", zIndex: 900 }} />
      <div style={{
        position: "fixed", right: 0, top: 0, bottom: 0, width: 380, zIndex: 901,
        background: "#0A0D17", borderLeft: "1px solid rgba(255,255,255,.1)",
        display: "flex", flexDirection: "column", padding: 28,
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>New custom agent</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 18 }}>✕</button>
        </div>
        {err && <div style={{ marginBottom: 14, color: "#f87171", fontSize: 12.5 }}>{err}</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="f-field" style={{ marginBottom: 0 }}>
            <label className="f-label">Agent name</label>
            <input className="f-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Outbound SDR agent" />
          </div>
          <div className="f-field" style={{ marginBottom: 0 }}>
            <label className="f-label">Role / goal</label>
            <textarea className="f-input f-ta" rows={4} value={role} onChange={e => setRole(e.target.value)}
              placeholder="e.g. Find leads, write personalised outreach copy, send emails and follow up until a meeting is booked." />
            <div className="f-hint">Plain English. The agent will use this as its ongoing objective.</div>
          </div>
        </div>
        <div style={{ marginTop: "auto", display: "flex", gap: 10 }}>
          <button className="btn pri" disabled={busy} onClick={submit} style={{ flex: 1 }}>
            {busy ? "Creating…" : "Create agent →"}
          </button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AutomationsPage() {
  const router = useRouter();
  const { userId } = useDevUser();

  const [agents, setAgents] = useState<CustomAgent[]>([]);
  const [flows, setFlows] = useState<CanvasFlow[]>([]);
  const [overviewFlows, setOverviewFlows] = useState<OverviewWorkflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [showNewAgent, setShowNewAgent] = useState(false);
  const [runningAgent, setRunningAgent] = useState("");
  const [runningFlow, setRunningFlow] = useState("");
  const [deletingAgent, setDeletingAgent] = useState("");

  function showFlash(tone: "success" | "error", text: string) {
    setFlash({ tone, text });
    setTimeout(() => setFlash(null), 5000);
  }

  async function load() {
    if (!userId || userId === "anon") return;
    setLoading(true);
    await waitForAuthReady();
    try {
      const [agentList, flowsRes, overviewRes] = await Promise.allSettled([
        listCustomAgents(userId),
        apiFetch(`${BASE}/automations/flows?founder_id=${encodeURIComponent(userId)}`).then(r => r.json()),
        apiFetch(`${BASE}/automations/overview?founder_id=${encodeURIComponent(userId)}`).then(r => r.json()),
      ]);
      if (agentList.status === "fulfilled") setAgents(agentList.value);
      if (flowsRes.status === "fulfilled") setFlows(flowsRes.value?.flows || []);
      if (overviewRes.status === "fulfilled") setOverviewFlows(overviewRes.value?.workflows || []);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [userId]);

  async function doRunAgent(agent: CustomAgent) {
    setRunningAgent(agent.id);
    try {
      const r = await runCustomAgent(userId, agent.id);
      showFlash("success", `${agent.name} started — session ${r.session_id.slice(0, 8)}`);
    } catch (e) {
      showFlash("error", e instanceof Error ? e.message : "Could not start agent.");
    } finally { setRunningAgent(""); }
  }

  async function doRunFlow(flowId: string) {
    setRunningFlow(flowId);
    try {
      const res = await apiFetch(`${BASE}/automations/flows/${encodeURIComponent(flowId)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || String(res.status));
      showFlash("success", `Flow started (${data?.run_id || "queued"}).`);
    } catch (e) {
      showFlash("error", e instanceof Error ? e.message : "Could not start flow.");
    } finally { setRunningFlow(""); }
  }

  async function doDeleteAgent(agent: CustomAgent) {
    if (!confirm(`Delete "${agent.name}"?`)) return;
    setDeletingAgent(agent.id);
    try {
      await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(userId)}/${encodeURIComponent(agent.id)}`, { method: "DELETE" });
      setAgents(prev => prev.filter(a => a.id !== agent.id));
      showFlash("success", `${agent.name} deleted.`);
    } catch (e) {
      showFlash("error", e instanceof Error ? e.message : "Could not delete.");
    } finally { setDeletingAgent(""); }
  }

  const allFlows: Array<{ id: string; name: string; meta: string; tone: ChipTone; isCanvas: boolean }> = [
    ...flows.map(f => ({
      id: f.id, name: f.name, isCanvas: true,
      meta: `${f.nodes.length} node${f.nodes.length !== 1 ? "s" : ""}${formatDate(f.updated_at) ? ` · Updated ${formatDate(f.updated_at)}` : ""}`,
      tone: "active" as ChipTone,
    })),
    ...overviewFlows
      .filter(w => !flows.find(f => f.id === w.id))
      .map(w => ({
        id: w.id, name: w.name, isCanvas: false,
        meta: formatDate(w.updated_at) ? `Updated ${formatDate(w.updated_at)}` : "",
        tone: (w.active ? "active" : "draft") as ChipTone,
      })),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%", padding: "24px 30px", gap: 20 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-.01em" }}>Automations</h1>
        <button className="btn" onClick={load} style={{ fontSize: 12.5 }}>Refresh</button>
      </div>

      {flash && <Flash msg={flash} onClose={() => setFlash(null)} />}

      {/* Quick-action cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <button
          onClick={() => setShowNewAgent(true)}
          style={{
            background: "#0A0D17", border: "1.5px solid #7d8fff", borderRadius: 12,
            padding: 18, display: "flex", flexDirection: "column", gap: 8,
            cursor: "pointer", textAlign: "left", color: "inherit",
          }}
        >
          <div style={{ width: 32, height: 32, borderRadius: 9, background: "rgba(125,143,255,.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#7d8fff" strokeWidth="1.6">
              <path d="M12 2.5l1.9 4.6 4.6 1.9-4.6 1.9-1.9 4.6-1.9-4.6-4.6-1.9 4.6-1.9L12 2.5Z" />
              <circle cx="19" cy="19" r="2.2" />
            </svg>
          </div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Create a custom agent</div>
          <div style={{ fontSize: 11.5, color: "#6f7b98" }}>Give it a goal and let it own the job end-to-end.</div>
        </button>

        <button
          onClick={() => router.push("/automations/canvas/new")}
          style={{
            background: "#0A0D17", border: "1.5px solid rgba(255,255,255,.1)", borderRadius: 12,
            padding: 18, display: "flex", flexDirection: "column", gap: 8,
            cursor: "pointer", textAlign: "left", color: "inherit",
          }}
        >
          <div style={{ width: 32, height: 32, borderRadius: 9, background: "rgba(125,143,255,.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#7d8fff" strokeWidth="1.8">
              <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z" />
            </svg>
          </div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Create a workflow automation</div>
          <div style={{ fontSize: 11.5, color: "#6f7b98" }}>One action, on a schedule or a trigger.</div>
        </button>
      </div>

      {loading && (
        <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
          <div style={{ width: 20, height: 20, borderRadius: "50%", border: "2px solid rgba(255,255,255,.1)", borderTopColor: "#7d8fff", animation: "spin 0.7s linear infinite" }} />
        </div>
      )}

      {!loading && (
        <>
          {/* ── Custom agents ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>
              Custom agents {agents.length > 0 && <span style={{ opacity: 0.6, textTransform: "none", letterSpacing: 0 }}>({agents.length})</span>}
            </div>

            {agents.length === 0 ? (
              <div style={{ padding: "32px 20px", border: "1px dashed rgba(255,255,255,.1)", borderRadius: 12, background: "#0A0D17", textAlign: "center" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 5 }}>No custom agents yet</div>
                <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 14 }}>Build an agent that works continuously on a goal.</div>
                <button className="btn pri" onClick={() => setShowNewAgent(true)}>+ New agent</button>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                {agents.map(a => (
                  <div key={a.id} style={{
                    background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)",
                    borderRadius: 11, padding: 13, display: "flex", flexDirection: "column", gap: 6,
                  }}>
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.3 }}>{a.name}</span>
                      <Chip tone={agentTone(a)} />
                    </div>
                    <div style={{ fontSize: 10.5, color: "#6f7b98", flex: 1 }}>{agentMeta(a)}</div>
                    <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                      <button className="btn pri sm" disabled={runningAgent === a.id} onClick={() => doRunAgent(a)} style={{ fontSize: 11 }}>
                        {runningAgent === a.id ? "Running…" : "▶ Run"}
                      </button>
                      <button className="btn sm" onClick={() => router.push(`/automations/canvas?agent=${a.id}`)} style={{ fontSize: 11 }}>Edit</button>
                      <button
                        className="btn sm" disabled={deletingAgent === a.id} onClick={() => doDeleteAgent(a)}
                        style={{ fontSize: 11, color: "#f87171", borderColor: "rgba(248,113,113,.3)", marginLeft: "auto" }}
                      >
                        {deletingAgent === a.id ? "…" : "✕"}
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  onClick={() => setShowNewAgent(true)}
                  style={{
                    background: "transparent", border: "1px dashed rgba(255,255,255,.1)", borderRadius: 11,
                    padding: 13, cursor: "pointer", color: "#6f7b98", fontSize: 12.5,
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 7, minHeight: 80,
                  }}
                >
                  <span style={{ fontSize: 16 }}>+</span> New agent
                </button>
              </div>
            )}
          </div>

          {/* ── Workflow automations ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>
                Workflow automations {allFlows.length > 0 && <span style={{ opacity: 0.6, textTransform: "none", letterSpacing: 0 }}>({allFlows.length})</span>}
              </div>
              <button className="btn sm" onClick={() => router.push("/automations/canvas/new")} style={{ fontSize: 11 }}>
                + New workflow
              </button>
            </div>

            {allFlows.length === 0 ? (
              <div style={{ padding: "32px 20px", border: "1px dashed rgba(255,255,255,.1)", borderRadius: 12, background: "#0A0D17", textAlign: "center" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 5 }}>No workflows yet</div>
                <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 14 }}>Scheduled actions and event-triggered flows live here.</div>
                <button className="btn pri" onClick={() => router.push("/automations/canvas/new")}>+ New workflow</button>
              </div>
            ) : (
              <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: "6px 14px" }}>
                {allFlows.map((f, i) => (
                  <div key={f.id} style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "10px 0",
                    borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,.06)",
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{f.name}</div>
                      {f.meta && <div style={{ fontSize: 10.5, color: "#6f7b98", marginTop: 1 }}>{f.meta}</div>}
                    </div>
                    <Chip tone={f.tone} />
                    {f.isCanvas && (
                      <button className="btn sm" onClick={() => router.push(`/automations/canvas/${f.id}`)} style={{ fontSize: 11 }}>Open</button>
                    )}
                    <button
                      className="btn pri sm" disabled={runningFlow === f.id} onClick={() => doRunFlow(f.id)} style={{ fontSize: 11 }}
                    >
                      {runningFlow === f.id ? "Running…" : "▶ Run"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {showNewAgent && (
        <NewAgentDrawer
          onClose={() => setShowNewAgent(false)}
          onCreated={a => {
            setAgents(prev => [a, ...prev]);
            setShowNewAgent(false);
            showFlash("success", `${a.name} created.`);
          }}
        />
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
