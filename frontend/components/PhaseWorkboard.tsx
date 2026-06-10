"use client";

import { useState } from "react";
import { AGENT_LABELS } from "@/lib/api";

// ── Shared types (mirror GoalWorkspace — not exported from there) ──────────
export interface LogEntry { ts: number; type: string; text: string; }

export interface AgentStateSlice {
  status: "waiting" | "running" | "done" | "error";
  currentAction: string | null;
  currentTool: string | null;
  reasoning: string | null;
  log: LogEntry[];
  visitedUrls?: string[];
  previewUrl?: string;
  colors?: string[];
  commits?: string[];
  filesPreview?: string[];
  filesCount?: number;
  legalText?: string;
  designSpec?: string;
  socialContent?: Record<string, string>;
  adImages?: Array<{ url?: string; base64?: string; prompt?: string }>;
}

export interface RunArtifactSlice {
  key: string;
  title: string;
  owner_agent: string;
  description: string;
  required: boolean;
  status: "pending" | "ready";
  preview?: string;
}

export interface ApprovalSlice {
  key: string;
  title: string;
  reason: string;
  status: "armed" | "triggered" | "approved" | "skipped";
  note?: string | null;
}

export interface PhaseWorkboardProps {
  agentList: string[];
  agents: Record<string, AgentStateSlice>;
  runArtifacts: RunArtifactSlice[];
  approvalQueue: ApprovalSlice[];
  activeAgent: string;
  done: boolean;
  onSelectAgent: (name: string) => void;
  onApprove?: (gateKey: string, decision: "approved" | "skipped") => void;
}

// ── Dept mapping ──────────────────────────────────────────────────────────
const AGENT_DEPT: Record<string, string> = {
  research: "research", research_competitors: "research", research_execution: "research",
  research_market: "research", research_financial: "research", research_regulatory: "research",
  design: "design",
  technical: "technical", technical_scaffold: "technical", technical_data: "technical", technical_infra: "technical",
  marketing: "marketing", marketing_content: "marketing", marketing_outreach: "marketing",
  marketing_paid: "marketing", marketing_seo: "marketing",
  legal: "legal", legal_docs: "legal", legal_entity: "legal", legal_ip: "legal",
  sales: "sales", sales_enablement: "sales", sales_pipeline: "sales",
  web: "web", web_navigator: "web",
  finance_model: "finance", finance_fundraise: "finance",
  ops: "ops",
};

const DEPT_META: Record<string, { label: string; icon: string }> = {
  research: { label: "Research",   icon: "◈" },
  design:   { label: "Design",     icon: "◉" },
  technical:{ label: "Technical",  icon: "⚙" },
  marketing:{ label: "Marketing",  icon: "✦" },
  legal:    { label: "Legal",      icon: "≡" },
  sales:    { label: "Sales",      icon: "⊕" },
  web:      { label: "Web",        icon: "◎" },
  finance:  { label: "Finance",    icon: "▦" },
  ops:      { label: "Ops",        icon: "▲" },
};

const DEPT_ORDER = ["research","design","technical","marketing","legal","sales","web","finance","ops"];

const PHASE_DEPTS = [
  { id: "discover",  label: "Discover",  depts: ["research"] },
  { id: "blueprint", label: "Blueprint", depts: ["design", "legal"] },
  { id: "build",     label: "Build",     depts: ["technical", "web"] },
  { id: "launch",    label: "Launch",    depts: ["marketing", "sales"] },
  { id: "scale",     label: "Scale",     depts: ["finance", "ops"] },
];

// ── Helpers ───────────────────────────────────────────────────────────────
type DeptStatus = "done" | "running" | "waiting" | "absent";

function deptStatus(dept: string, agentList: string[], agents: Record<string, AgentStateSlice>): DeptStatus {
  const deptAgents = agentList.filter(a => (AGENT_DEPT[a] ?? a) === dept);
  if (!deptAgents.length) return "absent";
  const statuses = deptAgents.map(a => agents[a]?.status ?? "waiting");
  if (statuses.some(s => s === "running")) return "running";
  if (statuses.every(s => s === "done")) return "done";
  return "waiting";
}

function phaseStatus(phaseDepts: string[], agentList: string[], agents: Record<string, AgentStateSlice>): "done" | "active" | "locked" {
  const relevant = phaseDepts.filter(d => agentList.some(a => (AGENT_DEPT[a] ?? a) === d));
  if (!relevant.length) return "locked";
  const statuses = relevant.map(d => deptStatus(d, agentList, agents));
  if (statuses.every(s => s === "done")) return "done";
  if (statuses.some(s => s === "running")) return "active";
  // If prior phase done → active, else locked
  return statuses.some(s => s === "waiting") ? "active" : "locked";
}

const STATUS_DOT: Record<string, string> = {
  running: "#2563EB", done: "#3D9E5F", waiting: "rgba(176,180,186,0.3)", absent: "transparent",
};
const STATUS_BORDER: Record<string, string> = {
  running: "rgba(37,99,235,0.3)", done: "rgba(61,158,95,0.2)", waiting: "rgba(176,180,186,0.10)", absent: "rgba(176,180,186,0.07)",
};
const STATUS_BG: Record<string, string> = {
  running: "rgba(37,99,235,0.06)", done: "rgba(61,158,95,0.05)", waiting: "rgba(255,255,255,0.02)", absent: "rgba(255,255,255,0.01)",
};

// ── Sub-components ────────────────────────────────────────────────────────

function PhaseBar({ agentList, agents }: { agentList: string[]; agents: Record<string, AgentStateSlice> }) {
  const phases = PHASE_DEPTS.map(p => ({ ...p, status: phaseStatus(p.depts, agentList, agents) }));
  // Only include phases that have at least one relevant agent
  const relevant = phases.filter((_, i) => {
    const present = phases.slice(0, i + 1).some(p => p.status !== "locked" || p.depts.some(d => agentList.some(a => (AGENT_DEPT[a] ?? a) === d)));
    return present;
  });
  if (relevant.length < 2) return null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0, padding: "10px 16px", borderBottom: "1px solid rgba(176,180,186,0.10)", overflowX: "auto", flexShrink: 0 }}>
      {relevant.map((phase, i) => {
        const col = phase.status === "done" ? "#3D9E5F" : phase.status === "active" ? "#2563EB" : "rgba(176,180,186,0.35)";
        const icon = phase.status === "done" ? "✓" : phase.status === "active" ? "●" : "○";
        return (
          <div key={phase.id} style={{ display: "flex", alignItems: "center", gap: 0 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "4px 11px", borderRadius: 99,
              background: phase.status === "done" ? "rgba(61,158,95,0.09)" : phase.status === "active" ? "rgba(37,99,235,0.09)" : "transparent",
              border: `1px solid ${phase.status !== "locked" ? col + "44" : "transparent"}`,
              color: col, fontSize: 11, fontWeight: 600, whiteSpace: "nowrap",
            }}>
              <span>{icon}</span>
              <span>{phase.label}</span>
            </div>
            {i < relevant.length - 1 && (
              <div style={{ width: 20, height: 1, background: phase.status === "done" ? "rgba(61,158,95,0.3)" : "rgba(176,180,186,0.15)" }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function ArtifactVault({ artifacts, selectedKey, onSelect }: {
  artifacts: RunArtifactSlice[];
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  if (!artifacts.length) return null;
  const ready = artifacts.filter(a => a.status === "ready");
  const pending = artifacts.filter(a => a.status === "pending");

  return (
    <div style={{ width: 172, flexShrink: 0, borderRight: "1px solid rgba(176,180,186,0.10)", padding: "10px 6px", display: "flex", flexDirection: "column", gap: 2, overflowY: "auto" }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: "rgba(176,180,186,0.5)", textTransform: "uppercase", letterSpacing: "0.09em", padding: "2px 6px 6px" }}>Artifacts</div>
      {ready.length > 0 && (
        <>
          <div style={{ fontSize: 9, color: "rgba(61,158,95,0.7)", textTransform: "uppercase", letterSpacing: "0.08em", padding: "3px 6px 2px" }}>Ready</div>
          {ready.map(a => (
            <button key={a.key} type="button" onClick={() => onSelect(a.key)}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 7px", borderRadius: 6, border: "none", cursor: "pointer", textAlign: "left",
                background: selectedKey === a.key ? "rgba(37,99,235,0.12)" : "transparent",
                color: selectedKey === a.key ? "#2563EB" : "rgba(176,180,186,0.75)",
              }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#3D9E5F", flexShrink: 0 }} />
              <span style={{ fontSize: 11, lineHeight: 1.3 }}>{a.title}</span>
            </button>
          ))}
        </>
      )}
      {pending.length > 0 && (
        <>
          <div style={{ fontSize: 9, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.08em", padding: "6px 6px 2px" }}>Pending</div>
          {pending.map(a => (
            <button key={a.key} type="button" onClick={() => onSelect(a.key)}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 7px", borderRadius: 6, border: "none", cursor: "pointer", textAlign: "left",
                background: selectedKey === a.key ? "rgba(37,99,235,0.08)" : "transparent",
                color: "rgba(176,180,186,0.35)",
              }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "rgba(176,180,186,0.25)", flexShrink: 0 }} />
              <span style={{ fontSize: 11, lineHeight: 1.3 }}>{a.title}</span>
            </button>
          ))}
        </>
      )}
    </div>
  );
}

function DeptCard({ dept, meta, agentList, agents, isSelected, onClick }: {
  dept: string;
  meta: { label: string; icon: string };
  agentList: string[];
  agents: Record<string, AgentStateSlice>;
  isSelected: boolean;
  onClick: () => void;
}) {
  const st = deptStatus(dept, agentList, agents);
  const deptAgents = agentList.filter(a => (AGENT_DEPT[a] ?? a) === dept);
  const runningAgent = deptAgents.find(a => agents[a]?.status === "running");
  const currentTool = runningAgent ? agents[runningAgent]?.currentTool : null;
  const doneCount = deptAgents.filter(a => agents[a]?.status === "done").length;

  return (
    <button type="button" onClick={onClick} style={{
      display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px",
      borderRadius: 12, border: `1px solid ${isSelected ? "#2563EB" : STATUS_BORDER[st]}`,
      background: isSelected ? "rgba(37,99,235,0.10)" : STATUS_BG[st],
      cursor: "pointer", textAlign: "left", minWidth: 140, flex: 1,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700, color: "var(--fg)" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_DOT[st], flexShrink: 0,
            boxShadow: st === "running" ? "0 0 0 0 rgba(37,99,235,0.4)" : "none",
            animation: st === "running" ? "pwb-pulse 1.5s ease-in-out infinite" : "none",
          }} />
          <span>{meta.icon}</span>
          <span>{meta.label}</span>
        </div>
        <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 99,
          background: st === "done" ? "rgba(61,158,95,0.12)" : st === "running" ? "rgba(37,99,235,0.12)" : "rgba(176,180,186,0.07)",
          color: st === "done" ? "#3D9E5F" : st === "running" ? "#2563EB" : "rgba(176,180,186,0.4)",
          fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", whiteSpace: "nowrap",
        }}>
          {st === "done" ? "Done" : st === "running" ? "Running" : "Queued"}
        </span>
      </div>
      {currentTool && (
        <div style={{ fontSize: 10, color: "#2563EB", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          ⟳ {currentTool.replace(/_/g, " ")}
        </div>
      )}
      <div style={{ fontSize: 10, color: "rgba(176,180,186,0.5)" }}>
        <span style={{ color: "#3D9E5F" }}>{doneCount}</span>/{deptAgents.length} agents
      </div>
      {deptAgents.length > 1 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
          {deptAgents.map(a => {
            const s = agents[a]?.status ?? "waiting";
            return (
              <span key={a} style={{ fontSize: 9, padding: "1px 5px", borderRadius: 99,
                background: s === "done" ? "rgba(61,158,95,0.1)" : s === "running" ? "rgba(37,99,235,0.1)" : "rgba(176,180,186,0.07)",
                color: s === "done" ? "#3D9E5F" : s === "running" ? "#2563EB" : "rgba(176,180,186,0.35)",
                border: "1px solid " + (s === "done" ? "rgba(61,158,95,0.2)" : s === "running" ? "rgba(37,99,235,0.2)" : "rgba(176,180,186,0.10)"),
              }}>
                {a}
              </span>
            );
          })}
        </div>
      )}
    </button>
  );
}

function AgentLog({ log, currentTool, maxEntries = 20 }: { log: LogEntry[]; currentTool: string | null; maxEntries?: number }) {
  const recent = log.slice(-maxEntries);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {recent.map((entry, i) => {
        let color = "rgba(176,180,186,0.65)";
        let prefix = "›";
        if (entry.type === "thinking") { color = "#A78BFA"; prefix = "◦"; }
        else if (entry.type === "tool") { color = "#2563EB"; prefix = "⚙"; }
        else if (entry.type === "result") { color = "#3D9E5F"; prefix = "✓"; }
        return (
          <div key={i} style={{ display: "flex", gap: 8, borderBottom: "1px solid rgba(255,255,255,0.03)", paddingBottom: 4 }}>
            <span style={{ fontSize: 10, color: "rgba(176,180,186,0.35)", flexShrink: 0, marginTop: 1 }}>{prefix}</span>
            <span style={{ fontSize: 11.5, color, lineHeight: 1.5, fontStyle: entry.type === "thinking" ? "italic" : "normal" }}>
              {entry.text}
            </span>
          </div>
        );
      })}
      {currentTool && (
        <div style={{ display: "flex", gap: 8 }}>
          <span style={{ fontSize: 10, color: "#2563EB", flexShrink: 0, marginTop: 1 }}>⟳</span>
          <span style={{ fontSize: 11.5, color: "#2563EB", lineHeight: 1.5 }}>{currentTool.replace(/_/g, " ")}…</span>
        </div>
      )}
    </div>
  );
}

function AgentPreview({ agentName, state }: { agentName: string; state: AgentStateSlice }) {
  const [previewTab, setPreviewTab] = useState<"activity" | "preview" | "sources">("activity");
  const dept = AGENT_DEPT[agentName] ?? agentName;

  const hasSources = (state.visitedUrls?.length ?? 0) > 0;
  const hasPreview = !!(state.previewUrl || state.colors?.length || state.filesPreview?.length || state.legalText || state.designSpec || state.socialContent);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Tab bar */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid rgba(176,180,186,0.10)" }}>
        {(["activity", "preview", "sources"] as const).map(t => {
          const labels = { activity: "Log", preview: "Preview", sources: `Sources (${state.visitedUrls?.length ?? 0})` };
          const show = t === "sources" ? hasSources : t === "preview" ? hasPreview : true;
          if (!show) return null;
          return (
            <button key={t} type="button" onClick={() => setPreviewTab(t)} style={{
              fontSize: 12, fontWeight: 600, color: previewTab === t ? "#2563EB" : "rgba(176,180,186,0.5)",
              padding: "7px 12px", border: "none", background: "none", cursor: "pointer",
              borderBottom: `2px solid ${previewTab === t ? "#2563EB" : "transparent"}`, marginBottom: -1,
            }}>
              {labels[t]}
            </button>
          );
        })}
      </div>

      {/* Activity */}
      {previewTab === "activity" && (
        <AgentLog log={state.log} currentTool={state.currentTool} />
      )}

      {/* Preview */}
      {previewTab === "preview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Research: URL iframe */}
          {(dept === "research") && state.previewUrl && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>Browsing now</div>
              <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(176,180,186,0.12)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 10px", background: "rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", gap: 4 }}>
                    {["#FF5F56","#FFBD2E","#27C93F"].map(c => <span key={c} style={{ width: 8, height: 8, borderRadius: "50%", background: c }} />)}
                  </div>
                  <span style={{ flex: 1, fontSize: 10, color: "rgba(176,180,186,0.5)", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {state.previewUrl}
                  </span>
                </div>
                <div style={{ background: "#fff", height: 240, position: "relative" }}>
                  <iframe src={state.previewUrl} style={{ width: "100%", height: "100%", border: "none" }} sandbox="allow-scripts allow-same-origin" />
                </div>
              </div>
            </div>
          )}

          {/* Web / Technical: deployed site iframe */}
          {(dept === "web" || dept === "technical") && state.previewUrl && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>
                {dept === "web" ? "Live site" : "Deploy preview"}
              </div>
              <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(176,180,186,0.12)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 10px", background: "rgba(255,255,255,0.04)" }}>
                  <div style={{ display: "flex", gap: 4 }}>
                    {["#FF5F56","#FFBD2E","#27C93F"].map(c => <span key={c} style={{ width: 8, height: 8, borderRadius: "50%", background: c }} />)}
                  </div>
                  <span style={{ flex: 1, fontSize: 10, color: "#2563EB", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {state.previewUrl}
                  </span>
                  <a href={state.previewUrl} target="_blank" rel="noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none", flexShrink: 0 }}>↗</a>
                </div>
                <div style={{ background: "#fff", height: 260, position: "relative" }}>
                  <iframe src={state.previewUrl} style={{ width: "100%", height: "100%", border: "none" }} />
                  <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 40, background: "linear-gradient(transparent,rgba(0,0,0,0.5))", pointerEvents: "none" }} />
                </div>
              </div>
            </div>
          )}

          {/* Files / commits */}
          {(dept === "web" || dept === "technical") && (state.filesPreview?.length || state.commits?.length) && (
            <div style={{ display: "grid", gridTemplateColumns: state.filesPreview?.length && state.commits?.length ? "1fr 1fr" : "1fr", gap: 10 }}>
              {state.filesPreview?.length ? (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>
                    Files ({state.filesCount ?? state.filesPreview.length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    {state.filesPreview.slice(0, 12).map((f, i) => {
                      const emoji = f.includes("frontend") || f.endsWith(".tsx") || f.endsWith(".ts") || f.endsWith(".css") ? "🔷"
                        : f.includes("backend") || f.endsWith(".py") ? "🔶"
                        : "📄";
                      return (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, fontFamily: "monospace", color: "rgba(176,180,186,0.65)", padding: "2px 5px", borderRadius: 4, background: "rgba(255,255,255,0.02)" }}>
                          <span>{emoji}</span><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              {state.commits?.length ? (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>
                    Commits ({state.commits.length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {state.commits.slice(-6).reverse().map((c, i) => (
                      <div key={i} style={{ fontSize: 10.5, color: "rgba(176,180,186,0.6)", fontFamily: "monospace", padding: "2px 5px", borderLeft: "2px solid rgba(61,158,95,0.3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}

          {/* Design: color palette */}
          {dept === "design" && state.colors?.length ? (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 8 }}>Brand colours</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {state.colors.map((c, i) => (
                  <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center" }}>
                    <div style={{ width: 40, height: 40, borderRadius: 8, background: c, border: "1px solid rgba(255,255,255,0.1)", cursor: "pointer" }} title={c} />
                    <span style={{ fontSize: 9, fontFamily: "monospace", color: "rgba(176,180,186,0.5)" }}>{c}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {dept === "design" && state.designSpec && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>Brand spec</div>
              <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.08)", fontSize: 12, color: "rgba(176,180,186,0.7)", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                {state.designSpec}
              </div>
            </div>
          )}

          {/* Legal text */}
          {dept === "legal" && state.legalText && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 6 }}>Draft document</div>
              <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.08)", fontSize: 11.5, color: "rgba(176,180,186,0.7)", lineHeight: 1.6, whiteSpace: "pre-wrap", maxHeight: 300, overflowY: "auto" }}>
                {state.legalText}
              </div>
            </div>
          )}

          {/* Marketing: social content */}
          {dept === "marketing" && state.socialContent && Object.keys(state.socialContent).length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 8 }}>Content created</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {Object.entries(state.socialContent).slice(0, 4).map(([key, val]) => (
                  <div key={key} style={{ padding: "8px 11px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.08)" }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 4 }}>{key}</div>
                    <div style={{ fontSize: 11.5, color: "rgba(176,180,186,0.7)", lineHeight: 1.5 }}>{val}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Marketing: ad images */}
          {dept === "marketing" && state.adImages?.length ? (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 8 }}>Ad creatives</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {state.adImages.slice(0, 4).map((img, i) => {
                  const src = img.url ?? (img.base64 ? `data:image/png;base64,${img.base64}` : null);
                  if (!src) return null;
                  return <img key={i} src={src} alt={img.prompt ?? "ad"} style={{ width: 120, height: 80, objectFit: "cover", borderRadius: 8, border: "1px solid rgba(176,180,186,0.12)" }} />;
                })}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Sources */}
      {previewTab === "sources" && hasSources && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "rgba(176,180,186,0.4)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 2 }}>
            {state.visitedUrls!.length} sources visited
          </div>
          {state.visitedUrls!.map((url, i) => {
            let domain = url;
            try { domain = new URL(url).hostname.replace(/^www\./, ""); } catch {}
            return (
              <a key={i} href={url} target="_blank" rel="noreferrer"
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderRadius: 7, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.09)", fontSize: 11, color: "rgba(176,180,186,0.65)", textDecoration: "none" }}>
                <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=16`} alt="" width={13} height={13} style={{ borderRadius: 2, flexShrink: 0 }} onError={e => (e.currentTarget.style.display = "none")} />
                <span style={{ fontWeight: 600, color: "rgba(176,180,186,0.8)", flexShrink: 0 }}>{domain}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, color: "rgba(176,180,186,0.4)" }}>
                  {url.replace(/^https?:\/\/[^/]+/, "")}
                </span>
                <span style={{ fontSize: 10, color: "#2563EB", flexShrink: 0 }}>↗</span>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ArtifactDetail({ artifact, onCopy, onDownload }: {
  artifact: RunArtifactSlice;
  onCopy: () => void;
  onDownload: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--fg)" }}>{artifact.title}</div>
          <div style={{ fontSize: 11, color: "rgba(176,180,186,0.5)", marginTop: 3 }}>
            {AGENT_LABELS[artifact.owner_agent] ?? artifact.owner_agent} · {" "}
            <span style={{ color: artifact.status === "ready" ? "#3D9E5F" : "rgba(176,180,186,0.35)" }}>
              {artifact.status === "ready" ? "✓ Ready" : "⋯ In progress"}
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button type="button" onClick={onCopy} style={{ fontSize: 11, fontWeight: 600, padding: "5px 11px", borderRadius: 7, border: "1px solid rgba(176,180,186,0.15)", background: "rgba(255,255,255,0.04)", color: "rgba(176,180,186,0.65)", cursor: "pointer" }}>Copy</button>
          <button type="button" onClick={onDownload} style={{ fontSize: 11, fontWeight: 600, padding: "5px 11px", borderRadius: 7, border: "1px solid rgba(37,99,235,0.35)", background: "#2563EB", color: "#fff", cursor: "pointer" }}>Download</button>
        </div>
      </div>
      {artifact.description && (
        <div style={{ fontSize: 12, color: "rgba(176,180,186,0.55)", lineHeight: 1.5 }}>{artifact.description}</div>
      )}
      {artifact.preview ? (
        <div style={{ padding: "12px 14px", borderRadius: 10, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(176,180,186,0.08)", fontSize: 12, color: "rgba(176,180,186,0.75)", lineHeight: 1.65, whiteSpace: "pre-wrap", overflowY: "auto", maxHeight: 400 }}>
          {artifact.preview}
        </div>
      ) : (
        <div style={{ padding: "16px", borderRadius: 10, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(176,180,186,0.08)", fontSize: 12, color: "rgba(176,180,186,0.35)", lineHeight: 1.5 }}>
          {artifact.status === "ready" ? "Content not available for preview." : "This artifact will be ready when the agent completes."}
        </div>
      )}
    </div>
  );
}

function ApprovalBanner({ approvals, onApprove }: {
  approvals: ApprovalSlice[];
  onApprove?: (key: string, decision: "approved" | "skipped") => void;
}) {
  const triggered = approvals.filter(a => a.status === "triggered");
  if (!triggered.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "12px 14px", borderRadius: 11, border: "1px solid rgba(192,57,43,0.28)", background: "rgba(192,57,43,0.06)" }}>
      {triggered.map(ap => (
        <div key={ap.key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
            <span style={{ fontSize: 16, flexShrink: 0 }}>🔒</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#C0392B" }}>{ap.title}</div>
              <div style={{ fontSize: 11.5, color: "rgba(176,180,186,0.7)", lineHeight: 1.45, marginTop: 3 }}>{ap.reason}</div>
              {ap.note && <div style={{ fontSize: 11, color: "rgba(176,180,186,0.5)", marginTop: 4 }}>{ap.note}</div>}
            </div>
          </div>
          {onApprove && (
            <div style={{ display: "flex", gap: 7 }}>
              <button type="button" onClick={() => onApprove(ap.key, "approved")}
                style={{ fontSize: 12, fontWeight: 700, padding: "6px 14px", borderRadius: 8, background: "rgba(61,158,95,0.12)", color: "#3D9E5F", border: "1px solid rgba(61,158,95,0.25)", cursor: "pointer" }}>
                ✓ Approve
              </button>
              <button type="button" onClick={() => onApprove(ap.key, "skipped")}
                style={{ fontSize: 12, padding: "6px 12px", borderRadius: 8, background: "transparent", color: "rgba(176,180,186,0.5)", border: "1px solid rgba(176,180,186,0.12)", cursor: "pointer" }}>
                Skip
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────
type SelectedView = { type: "agent"; dept: string; agentName: string } | { type: "artifact"; key: string };

export default function PhaseWorkboard({
  agentList, agents, runArtifacts, approvalQueue,
  activeAgent, done, onSelectAgent, onApprove,
}: PhaseWorkboardProps) {
  // Derive which depts are present
  const presentDepts = DEPT_ORDER.filter(d => agentList.some(a => (AGENT_DEPT[a] ?? a) === d));

  // Default selected view: use activeAgent if set, else first running dept
  const defaultDept = (() => {
    if (activeAgent) return AGENT_DEPT[activeAgent] ?? activeAgent;
    const running = presentDepts.find(d => deptStatus(d, agentList, agents) === "running");
    return running ?? presentDepts[0] ?? "";
  })();
  const defaultAgent = (() => {
    if (activeAgent && presentDepts.includes(AGENT_DEPT[activeAgent] ?? "")) return activeAgent;
    const runningInDept = agentList.find(a => (AGENT_DEPT[a] ?? a) === defaultDept && agents[a]?.status === "running");
    return runningInDept ?? agentList.find(a => (AGENT_DEPT[a] ?? a) === defaultDept) ?? "";
  })();

  const [selectedView, setSelectedView] = useState<SelectedView>(
    defaultAgent ? { type: "agent", dept: defaultDept, agentName: defaultAgent } : { type: "artifact", key: runArtifacts[0]?.key ?? "" }
  );
  const [selectedArtifact, setSelectedArtifact] = useState<string>("");

  if (!presentDepts.length) return null;

  const triggeredApprovals = approvalQueue.filter(a => a.status === "triggered");
  const readyArtifacts = runArtifacts.filter(a => a.status === "ready").length;
  const runningCount = Object.values(agents).filter(a => a.status === "running").length;

  function selectDept(dept: string) {
    const deptAgents = agentList.filter(a => (AGENT_DEPT[a] ?? a) === dept);
    const best = deptAgents.find(a => agents[a]?.status === "running") ?? deptAgents[0];
    if (best) {
      onSelectAgent(best);
      setSelectedView({ type: "agent", dept, agentName: best });
    }
  }

  function selectArtifact(key: string) {
    setSelectedArtifact(key);
    setSelectedView({ type: "artifact", key });
  }

  function handleCopy(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  function handleDownload(title: string, content: string) {
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${title.toLowerCase().replace(/\s+/g, "-")}.txt`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", borderRadius: 16, border: "1px solid rgba(176,180,186,0.12)", overflow: "hidden", background: "rgba(255,255,255,0.015)", minHeight: 560 }}>
      {/* Inline keyframe for pulsing dot */}
      <style>{`
        @keyframes pwb-pulse {
          0%,100% { box-shadow: 0 0 0 0 rgba(37,99,235,0.5); }
          50% { box-shadow: 0 0 0 5px rgba(37,99,235,0); }
        }
      `}</style>

      {/* Phase bar */}
      <PhaseBar agentList={agentList} agents={agents} />

      {/* Stats strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "8px 16px", borderBottom: "1px solid rgba(176,180,186,0.08)", fontSize: 11, color: "rgba(176,180,186,0.5)", flexWrap: "wrap" }}>
        {runningCount > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563EB", animation: "pwb-pulse 1.5s ease-in-out infinite" }} />
            <span style={{ color: "#2563EB", fontWeight: 700 }}>{runningCount}</span>&nbsp;running
          </span>
        )}
        <span><span style={{ color: "#3D9E5F", fontWeight: 700 }}>{readyArtifacts}</span> artifacts ready</span>
        <span style={{ color: "rgba(176,180,186,0.3)" }}>·</span>
        <span>{agentList.filter(a => agents[a]?.status === "done").length}/{agentList.length} agents done</span>
        {done && <span style={{ color: "#3D9E5F", fontWeight: 600 }}>✓ Run complete</span>}
        {triggeredApprovals.length > 0 && (
          <span style={{ color: "#C0392B", fontWeight: 600 }}>⚠ {triggeredApprovals.length} approval{triggeredApprovals.length > 1 ? "s" : ""} needed</span>
        )}
      </div>

      {/* Main body */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", minHeight: 0 }}>
        {/* Artifact vault sidebar */}
        {runArtifacts.length > 0 && (
          <ArtifactVault
            artifacts={runArtifacts}
            selectedKey={selectedView.type === "artifact" ? selectedView.key : ""}
            onSelect={selectArtifact}
          />
        )}

        {/* Main area */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
          {/* Dept cards */}
          <div style={{ display: "flex", gap: 8, padding: "12px 14px", borderBottom: "1px solid rgba(176,180,186,0.08)", overflowX: "auto", flexShrink: 0 }}>
            {presentDepts.map(dept => (
              <DeptCard
                key={dept}
                dept={dept}
                meta={DEPT_META[dept] ?? { label: dept, icon: "●" }}
                agentList={agentList}
                agents={agents}
                isSelected={selectedView.type === "agent" && selectedView.dept === dept}
                onClick={() => selectDept(dept)}
              />
            ))}
          </div>

          {/* Approvals */}
          {triggeredApprovals.length > 0 && (
            <div style={{ padding: "10px 14px", borderBottom: "1px solid rgba(176,180,186,0.08)" }}>
              <ApprovalBanner approvals={triggeredApprovals} onApprove={onApprove} />
            </div>
          )}

          {/* Detail panel */}
          <div style={{ flex: 1, overflowY: "auto", padding: "14px 16px" }}>
            {selectedView.type === "agent" && (() => {
              const st = agents[selectedView.agentName];
              if (!st) return (
                <div style={{ fontSize: 12, color: "rgba(176,180,186,0.35)", padding: "20px 0" }}>
                  Select a department to view its activity.
                </div>
              );
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "rgba(176,180,186,0.5)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                    {AGENT_LABELS[selectedView.agentName] ?? selectedView.agentName}
                    {agentList.filter(a => (AGENT_DEPT[a] ?? a) === selectedView.dept).length > 1 && (
                      <span style={{ fontWeight: 400, fontSize: 10, marginLeft: 8, textTransform: "none", letterSpacing: 0 }}>
                        — click a sub-agent chip to switch
                      </span>
                    )}
                  </div>
                  {/* Sub-agent switcher for multi-agent depts */}
                  {agentList.filter(a => (AGENT_DEPT[a] ?? a) === selectedView.dept).length > 1 && (
                    <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                      {agentList.filter(a => (AGENT_DEPT[a] ?? a) === selectedView.dept).map(a => {
                        const s = agents[a]?.status ?? "waiting";
                        return (
                          <button key={a} type="button" onClick={() => { onSelectAgent(a); setSelectedView({ type: "agent", dept: selectedView.dept, agentName: a }); }}
                            style={{ fontSize: 10, padding: "3px 8px", borderRadius: 99, border: `1px solid ${a === selectedView.agentName ? "#2563EB" : "rgba(176,180,186,0.15)"}`,
                              background: a === selectedView.agentName ? "rgba(37,99,235,0.12)" : "transparent",
                              color: s === "done" ? "#3D9E5F" : s === "running" ? "#2563EB" : "rgba(176,180,186,0.5)",
                              cursor: "pointer", fontWeight: 600 }}>
                            {a}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  <AgentPreview agentName={selectedView.agentName} state={st} />
                </div>
              );
            })()}

            {selectedView.type === "artifact" && (() => {
              const art = runArtifacts.find(a => a.key === selectedView.key);
              if (!art) return <div style={{ fontSize: 12, color: "rgba(176,180,186,0.35)", padding: "20px 0" }}>Artifact not found.</div>;
              return (
                <ArtifactDetail
                  artifact={art}
                  onCopy={() => handleCopy(art.preview ?? art.title)}
                  onDownload={() => handleDownload(art.title, art.preview ?? art.description ?? "")}
                />
              );
            })()}
          </div>
        </div>
      </div>
    </div>
  );
}
