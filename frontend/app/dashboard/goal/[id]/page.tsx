"use client";

import { use, useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { streamGoal, AGENT_LABELS, AGENT_ORDER, TOOL_DESCRIPTIONS, sortAgentNamesByOrder, sortAgentsByOrder } from "@/lib/api";
import { updateSession } from "@/lib/history";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AgentTask { id: string; agent: string; instruction: string; }

interface LogEntry { ts: number; type: string; text: string; }

interface AgentState {
  task_id: string;
  agent: string;
  instruction: string;
  status: "waiting" | "running" | "done" | "error";
  currentAction: string | null;
  currentTool: string | null;
  reasoning: string | null;
  result: Record<string, unknown> | null;
  log: LogEntry[];
  mirrorVerdict?: "pass" | "flag" | "block";
  mirrorCritique?: string;
  currentUrl?: string;
  visitedUrls?: string[];
  previewUrl?: string;
  colors?: string[];
  commits?: string[];
  socialContent?: Record<string, string>;
  legalText?: string;
  salesLead?: string;
  designSpec?: string;
}

const AGENT_ICONS: Record<string, string> = {
  research: "🔬", web: "🌐", marketing: "📢", technical: "⚙️",
  legal: "⚖️", ops: "🚀", sales: "🤝", design: "🎨",
};

const STATUS_COLOR = {
  waiting: "rgba(0,0,0,0.2)",
  running: "#2563EB",
  done: "#3D9E5F",
  error: "#C0392B",
};

function pct(state: AgentState): number {
  if (state.status === "done") return 100;
  if (state.status === "waiting") return 0;
  const steps = Math.max(state.log.filter(l => l.type === "result" || l.type === "action").length, 1);
  return Math.min(90, Math.round((steps / 12) * 90));
}

function extractColors(log: LogEntry[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const l of log) {
    const matches = l.text.match(/#([0-9a-fA-F]{6})\b/g) ?? [];
    for (const c of matches) { if (!seen.has(c)) { seen.add(c); out.push(c); } }
  }
  return out;
}

function extractUrls(log: LogEntry[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const l of log) {
    const matches = l.text.match(/https?:\/\/[^\s"')\]]+/g) ?? [];
    for (const u of matches) {
      const clean = u.replace(/[.,;]+$/, "");
      if (!seen.has(clean) && !clean.includes("localhost")) { seen.add(clean); out.push(clean); }
    }
  }
  return out;
}

function faviconUrl(url: string): string {
  try { return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=16`; } catch { return ""; }
}

// ── Agent-specific preview panels ──────────────────────────────────────────

function ResearchPreview({ state }: { state: AgentState }) {
  const urls = extractUrls(state.log);
  const current = state.currentUrl ?? urls[urls.length - 1];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%" }}>
      {current && (
        <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid rgba(0,0,0,0.07)", background: "#F5F5F3" }}>
            <img src={faviconUrl(current)} width={12} height={12} style={{ opacity: 0.6 }} onError={e => (e.currentTarget.style.display = "none")} />
            <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{current}</span>
            <a href={current} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none" }}>↗</a>
          </div>
          <div style={{ height: 280, position: "relative" }}>
            <iframe
              src={current}
              sandbox="allow-scripts allow-same-origin"
              style={{ width: "100%", height: "100%", border: "none", opacity: 0.95 }}
              title="Research preview"
            />
            <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "linear-gradient(to bottom, transparent 80%, rgba(232,232,230,0.7))" }} />
          </div>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 160, overflowY: "auto" }}>
        <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 4 }}>Sites visited ({urls.length})</span>
        {urls.map((u, i) => (
          <a key={i} href={u} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 6, padding: "5px 8px", background: u === current ? "rgba(37,99,235,0.06)" : "rgba(0,0,0,0.03)", border: `1px solid ${u === current ? "rgba(37,99,235,0.2)" : "rgba(0,0,0,0.07)"}`, textDecoration: "none" }}>
            <img src={faviconUrl(u)} width={12} height={12} onError={e => (e.currentTarget.style.display = "none")} />
            <span style={{ fontSize: 11, color: "var(--fg-dim)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.replace(/^https?:\/\//, "").slice(0, 60)}</span>
          </a>
        ))}
        {urls.length === 0 && state.status === "running" && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--fg-mute)" }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563EB" }} className="animate-pulse" /> Searching…
          </div>
        )}
      </div>
    </div>
  );
}

function WebPreview({ state }: { state: AgentState }) {
  const url = state.previewUrl ?? (state.result?.url ?? state.result?.deployment_url ?? state.result?.project_url) as string | undefined;
  const commits = state.commits ?? [];
  if (url) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
        <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(0,0,0,0.09)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", background: "#F5F5F3", borderBottom: "1px solid rgba(0,0,0,0.07)" }}>
            <div style={{ display: "flex", gap: 5 }}>
              {["#ff5f57","#febc2e","#28c840"].map(c => <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />)}
            </div>
            <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{url}</span>
            <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none" }}>↗</a>
          </div>
          <div style={{ height: 340, background: "#FFFFFF" }}>
            <iframe src={url} style={{ width: "100%", height: "100%", border: "none" }} title="Site preview" />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {commits.length > 0 ? (
        <>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Recent commits</span>
          {commits.map((c, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 6, background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)" }}>
              <span style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: 10, color: "#2563EB" }}>●</span>
              <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{c}</span>
            </div>
          ))}
        </>
      ) : (
        <BuildingIndicator label="Building site…" />
      )}
    </div>
  );
}

function TechnicalPreview({ state }: { state: AgentState }) {
  const repo = (state.result?.repo_url ?? state.result?.github_url) as string | undefined;
  const deploy = (state.result?.deployment_url ?? state.result?.project_url) as string | undefined;
  const files = (state.result?.files_preview ?? state.result?.files_in_repo) as unknown;
  const commits = state.commits ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {deploy && (
        <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid rgba(37,99,235,0.18)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", background: "#F5F5F3", borderBottom: "1px solid rgba(0,0,0,0.07)" }}>
            <div style={{ display: "flex", gap: 5 }}>
              {["#ff5f57","#febc2e","#28c840"].map(c => <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />)}
            </div>
            <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, textAlign: "center" }}>{deploy}</span>
            <a href={deploy} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none" }}>↗</a>
          </div>
          <div style={{ height: 260 }}>
            <iframe src={deploy} style={{ width: "100%", height: "100%", border: "none" }} title="App preview" />
          </div>
        </div>
      )}
      {repo && (
        <a href={repo} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 8, border: "1px solid rgba(0,0,0,0.1)", background: "rgba(0,0,0,0.03)", padding: "8px 12px", color: "#2563EB", textDecoration: "none", fontSize: 12 }}>
          🐙 <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{repo}</span> <span style={{ opacity: 0.5 }}>↗</span>
        </a>
      )}
      {commits.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Commits ({commits.length})</span>
          {commits.map((c, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)" }}>
              <span style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: 10, color: "#2563EB" }}>{c.slice(0, 7)}</span>
              <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>round committed</span>
            </div>
          ))}
        </div>
      )}
      {Array.isArray(files) && files.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 140, overflowY: "auto" }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 4 }}>Files</span>
          {(files as string[]).map((f, i) => (
            <div key={i} style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", padding: "2px 6px" }}>
              {f.startsWith("frontend/") ? "🔷" : f.startsWith("backend/") ? "🔶" : "📄"} {f}
            </div>
          ))}
        </div>
      )}
      {!repo && !deploy && <BuildingIndicator label="Building MVP…" />}
    </div>
  );
}

function DesignPreview({ state }: { state: AgentState }) {
  const colors = extractColors(state.log);
  const spec = state.designSpec ?? (state.result?.design_spec as string | undefined);
  const palette = state.result?.color_palette as Record<string, string> | undefined;

  const allColors = palette ? Object.values(palette).filter(v => typeof v === "string" && v.startsWith("#")) : colors;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {allColors.length > 0 && (
        <div>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", display: "block", marginBottom: 8 }}>Color Palette</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {allColors.map((c, i) => (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <div style={{ width: 44, height: 44, borderRadius: 10, background: c, border: "1px solid rgba(0,0,0,0.1)", boxShadow: `0 2px 8px ${c}44` }} />
                <span style={{ fontSize: 9, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)" }}>{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {palette && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {Object.entries(palette).map(([k, v]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(0,0,0,0.03)" }}>
              {typeof v === "string" && v.startsWith("#") && <div style={{ width: 14, height: 14, borderRadius: 3, background: v, flexShrink: 0 }} />}
              <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span>
              <span style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-dim)", marginLeft: "auto" }}>{String(v).slice(0, 40)}</span>
            </div>
          ))}
        </div>
      )}
      {spec && (
        <div>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", display: "block", marginBottom: 6 }}>Design Spec</span>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 200, overflowY: "auto", padding: "10px 12px", background: "#F5F5F3", borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)" }}>
            {typeof spec === "string" ? spec.slice(0, 600) : JSON.stringify(spec, null, 2).slice(0, 600)}
          </div>
        </div>
      )}
      {allColors.length === 0 && !spec && <BuildingIndicator label="Designing…" />}
    </div>
  );
}

function MarketingPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const reel = r?.instagram_reel as string | undefined;
  const tiktok = r?.tiktok as string | undefined;
  const ad = r?.meta_ad as string | undefined;
  const email = r?.email as string | undefined;

  if (!r || (!reel && !tiktok && !ad && !email)) return <BuildingIndicator label="Creating content…" />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {[["📸 Instagram Reel", reel], ["🎵 TikTok", tiktok], ["📣 Meta Ad", ad], ["📧 Email", email]].map(([label, content]) =>
        content ? (
          <div key={String(label)} style={{ borderRadius: 8, border: "1px solid rgba(0,0,0,0.09)", background: "rgba(0,0,0,0.02)", padding: "10px 12px" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-dim)", marginBottom: 6 }}>{label}</div>
            <div style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.6, maxHeight: 80, overflowY: "auto", whiteSpace: "pre-wrap" }}>{String(content).slice(0, 300)}</div>
          </div>
        ) : null
      )}
    </div>
  );
}

function LegalPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const text = (r?.formatted_text ?? r?.content ?? r?.document_text) as string | undefined;
  const path = (r?.path ?? r?.privacy_policy_path ?? r?.filename) as string | undefined;
  if (!r || !text) return <BuildingIndicator label="Drafting documents…" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {path && <div style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "#2563EB", padding: "4px 8px", background: "rgba(37,99,235,0.06)", borderRadius: 6, border: "1px solid rgba(37,99,235,0.15)" }}>📄 {String(path)}</div>}
      <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 280, overflowY: "auto", padding: "10px 12px", background: "#F5F5F3", borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)" }}>
        {String(text).slice(0, 1200)}
      </div>
    </div>
  );
}

function SalesPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const lead = (r?.lead ?? r?.company) as string | undefined;
  const seq = r?.sequence;
  if (!r || !lead) return <BuildingIndicator label="Building outreach…" />;
  const steps: unknown[] = Array.isArray(seq) ? seq : typeof seq === "string" ? JSON.parse(seq.startsWith("[") ? seq : "[]") : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ padding: "8px 12px", borderRadius: 8, background: "rgba(37,99,235,0.06)", border: "1px solid rgba(37,99,235,0.15)" }}>
        <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 3 }}>Target Lead</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{lead}</div>
      </div>
      {steps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Email Sequence ({steps.length} steps)</span>
          {(steps as Record<string, unknown>[]).slice(0, 4).map((s, i) => (
            <div key={i} style={{ padding: "8px 10px", borderRadius: 6, background: "#FFFFFF", border: "1px solid rgba(0,0,0,0.09)" }}>
              <div style={{ fontSize: 10, color: "#2563EB", marginBottom: 3 }}>Day {String(s.send_day ?? i + 1)}</div>
              <div style={{ fontSize: 11, fontWeight: 500, color: "var(--fg)" }}>{String(s.subject ?? "").slice(0, 60)}</div>
              <div style={{ fontSize: 10, color: "var(--fg-mute)", marginTop: 2 }}>{String(s.body ?? "").slice(0, 80)}…</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OpsPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const sop = (r?.SOP ?? r?.content ?? r?.sop) as string | undefined;
  const title = (r?.title) as string | undefined;
  if (!r || !sop) return <BuildingIndicator label="Handling operations…" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {title && <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{title}</div>}
      <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 280, overflowY: "auto", padding: "10px 12px", background: "#F5F5F3", borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)" }}>
        {String(sop).slice(0, 1200)}
      </div>
    </div>
  );
}

function BuildingIndicator({ label }: { label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "20px 0", color: "var(--fg-mute)", fontSize: 12 }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
      {label}
    </div>
  );
}

function AgentPreview({ state }: { state: AgentState }) {
  switch (state.agent) {
    case "research": return <ResearchPreview state={state} />;
    case "web": return <WebPreview state={state} />;
    case "technical": return <TechnicalPreview state={state} />;
    case "design": return <DesignPreview state={state} />;
    case "marketing": return <MarketingPreview state={state} />;
    case "legal": return <LegalPreview state={state} />;
    case "sales": return <SalesPreview state={state} />;
    case "ops": return <OpsPreview state={state} />;
    default: return <BuildingIndicator label="Working…" />;
  }
}

// ── Agent detail panel ──────────────────────────────────────────────────────

type DetailTab = "preview" | "plan" | "log";

function AgentDetail({ state, planTask }: { state: AgentState; planTask: AgentTask | undefined }) {
  const [tab, setTab] = useState<DetailTab>("preview");
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [state.log.length]);

  const p = pct(state);
  const isRunning = state.status === "running";
  const isDone = state.status === "done";

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    fontSize: 11, fontWeight: 500, letterSpacing: "0.04em", padding: "5px 14px", borderRadius: 6,
    cursor: "pointer", border: "none",
    background: active ? "rgba(37,99,235,0.09)" : "transparent",
    color: active ? "#2563EB" : "var(--fg-mute)", transition: "all 0.15s",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 20 }}>{AGENT_ICONS[state.agent] ?? "🤖"}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>{AGENT_LABELS[state.agent] ?? state.agent}</span>
            <span style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: STATUS_COLOR[state.status] }}>{state.status}</span>
          </div>
          {state.instruction && (
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>{state.instruction.slice(0, 100)}</p>
          )}
        </div>
        {/* % badge */}
        <div style={{ position: "relative", width: 40, height: 40, flexShrink: 0 }}>
          <svg viewBox="0 0 40 40" style={{ transform: "rotate(-90deg)" }}>
            <circle cx="20" cy="20" r="17" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="3" />
            <circle cx="20" cy="20" r="17" fill="none" stroke={isDone ? "#3D9E5F" : "#2563EB"} strokeWidth="3"
              strokeDasharray={`${2 * Math.PI * 17}`}
              strokeDashoffset={`${2 * Math.PI * 17 * (1 - p / 100)}`}
              style={{ transition: "stroke-dashoffset 0.6s" }} />
          </svg>
          <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 600, fontFamily: "var(--font-jetbrains-mono)", color: isDone ? "#3D9E5F" : "var(--fg-mute)" }}>{p}%</span>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ height: 3, borderRadius: 999, background: "rgba(0,0,0,0.08)", overflow: "hidden" }}>
        <div style={{ height: "100%", borderRadius: 999, width: `${p}%`, background: isDone ? "linear-gradient(90deg,#3D9E5F,#5AC87A)" : "linear-gradient(90deg,#2563EB,#60A5FA)", transition: "width 0.6s" }} />
      </div>

      {/* Current action pill */}
      {isRunning && state.currentAction && (
        <div style={{ display: "flex", alignItems: "center", gap: 7, borderRadius: 8, background: "rgba(37,99,235,0.06)", padding: "6px 11px", fontSize: 11, color: "var(--fg-dim)", border: "1px solid rgba(37,99,235,0.14)" }}>
          <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {state.currentTool ? `${state.currentTool.replace(/_/g, " ")}` : state.currentAction}
            {state.currentUrl ? ` — ${state.currentUrl.replace(/^https?:\/\//, "").slice(0, 50)}` : ""}
          </span>
        </div>
      )}

      {/* Sub-tabs */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid rgba(0,0,0,0.08)", paddingBottom: 8 }}>
        {(["preview", "plan", "log"] as DetailTab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={TAB_STYLE(tab === t)}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {tab === "preview" && <AgentPreview state={state} />}

        {tab === "plan" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {planTask && (
              <div style={{ padding: "10px 14px", borderRadius: 8, background: "#F5F5F3", border: "1px solid rgba(0,0,0,0.08)" }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 5 }}>Task instruction</div>
                <p style={{ margin: 0, fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.6 }}>{planTask.instruction}</p>
              </div>
            )}
            {state.result && (
              <div style={{ padding: "10px 14px", borderRadius: 8, background: "#F5F5F3", border: "1px solid rgba(0,0,0,0.08)" }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 5 }}>Output</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {Object.entries(state.result).filter(([, v]) => v !== null && v !== undefined).slice(0, 8).map(([k, v]) => (
                    <div key={k} style={{ display: "flex", gap: 8, fontSize: 11 }}>
                      <span style={{ color: "var(--fg-mute)", minWidth: 100, flexShrink: 0 }}>{k.replace(/_/g, " ")}</span>
                      <span style={{ color: "var(--fg-dim)", wordBreak: "break-all" }}>{typeof v === "string" ? v.slice(0, 120) : JSON.stringify(v).slice(0, 80)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "log" && (
          <div ref={logRef} style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 380, overflowY: "auto" }}>
            {state.log.length === 0 && <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Waiting to start…</span>}
            {state.log.map((entry, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 10, lineHeight: 1.5, padding: "2px 0" }}>
                <span style={{ fontFamily: "var(--font-jetbrains-mono)", flexShrink: 0, color: "rgba(0,0,0,0.3)", minWidth: 56 }}>
                  {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
                <span style={{ color: entry.type === "error" ? "#C0392B" : entry.type === "result" ? "#3D9E5F" : "var(--fg-dim)" }}>{entry.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sidebar agent list ──────────────────────────────────────────────────────

function AgentSidebar({ agentList, agents, activeAgent, onSelect }: {
  agentList: string[];
  agents: Record<string, AgentState>;
  activeAgent: string;
  onSelect: (a: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {agentList.map(name => {
        const state = agents[name];
        const status = state?.status ?? "waiting";
        const isActive = name === activeAgent;
        const p = state ? pct(state) : 0;
        return (
          <button key={name} onClick={() => onSelect(name)} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, border: "none",
            background: isActive ? "rgba(37,99,235,0.08)" : "transparent",
            cursor: "pointer", textAlign: "left", transition: "background 0.15s",
            outline: isActive ? "1px solid rgba(37,99,235,0.22)" : "none",
          }}>
            <div style={{ position: "relative", width: 28, height: 28, flexShrink: 0 }}>
              <svg viewBox="0 0 28 28" style={{ transform: "rotate(-90deg)", width: 28, height: 28 }}>
                <circle cx="14" cy="14" r="11" fill="none" stroke="rgba(0,0,0,0.1)" strokeWidth="2.5" />
                <circle cx="14" cy="14" r="11" fill="none" stroke={status === "done" ? "#3D9E5F" : status === "running" ? "#2563EB" : status === "error" ? "#C0392B" : "transparent"}
                  strokeWidth="2.5"
                  strokeDasharray={`${2 * Math.PI * 11}`}
                  strokeDashoffset={`${2 * Math.PI * 11 * (1 - p / 100)}`}
                  style={{ transition: "stroke-dashoffset 0.5s" }} />
              </svg>
              <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>{AGENT_ICONS[name] ?? "🤖"}</span>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: isActive ? "var(--fg)" : "var(--fg-mute)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {AGENT_LABELS[name] ?? name}
              </div>
              <div style={{ fontSize: 10, color: STATUS_COLOR[status] ?? "rgba(0,0,0,0.25)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{status}</div>
            </div>
            {status === "running" && (
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Steer + Ask panels ─────────────────────────────────────────────────────

function SteerPanel({ sessionId, isRunning }: { sessionId: string; isRunning: boolean }) {
  const [msg, setMsg] = useState("");
  const [sent, setSent] = useState(false);
  if (!isRunning) return null;
  const send = async () => {
    if (!msg.trim()) return;
    await fetch(`${BASE}/steer/${sessionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg }) });
    setSent(true); setMsg(""); setTimeout(() => setSent(false), 2000);
  };
  return (
    <div style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF", padding: "12px 14px" }}>
      <div style={{ fontSize: 11, color: "var(--fg-mute)", marginBottom: 8 }}>Steer agents mid-run</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
          placeholder="e.g. focus on B2B customers"
          style={{ flex: 1, background: "#F5F5F3", border: "1px solid rgba(0,0,0,0.12)", borderRadius: 8, padding: "7px 12px", fontSize: 12, color: "var(--fg)", outline: "none" }} />
        <button onClick={send} style={{ padding: "7px 14px", borderRadius: 8, background: sent ? "#3D9E5F" : "#2563EB", border: "none", color: "#fff", fontSize: 12, cursor: "pointer" }}>
          {sent ? "Sent" : "Send"}
        </button>
      </div>
    </div>
  );
}

function AskPanel({ sessionId, founderId }: { sessionId: string; founderId: string }) {
  const [msg, setMsg] = useState(""); const [reply, setReply] = useState(""); const [loading, setLoading] = useState(false);
  const ask = async () => {
    if (!msg.trim()) return;
    setLoading(true); setReply("");
    const r = await fetch(`${BASE}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, founder_id: founderId, question: msg }) });
    const d = await r.json(); setReply(d.answer ?? d.response ?? JSON.stringify(d)); setLoading(false);
  };
  return (
    <div style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>Ask about your results</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === "Enter" && ask()}
          placeholder="What are the top competitors?"
          style={{ flex: 1, background: "#F5F5F3", border: "1px solid rgba(0,0,0,0.12)", borderRadius: 8, padding: "7px 12px", fontSize: 12, color: "var(--fg)", outline: "none" }} />
        <button onClick={ask} style={{ padding: "7px 14px", borderRadius: 8, background: "#2563EB", border: "none", color: "#fff", fontSize: 12, cursor: "pointer" }}>
          {loading ? "…" : "Ask"}
        </button>
      </div>
      {reply && <div style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.6, padding: "8px 10px", background: "#F5F5F3", borderRadius: 8 }}>{reply}</div>}
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────

export default function GoalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = use(params);
  const searchParams = useSearchParams();
  const instruction = searchParams.get("instruction") ?? "";
  const founderId = searchParams.get("founder") ?? "founder_001";
  const company = searchParams.get("company") ?? "";

  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [planTasks, setPlanTasks] = useState<AgentTask[]>([]);
  const [activeAgent, setActiveAgent] = useState<string>("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const everConnected = useRef(false);
  const notified = useRef(false);
  const errorCount = useRef(0);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined") return;
    const es = streamGoal(sessionId);
    es.onopen = () => { setConnected(true); setReconnecting(false); errorCount.current = 0; everConnected.current = true; };
    es.onerror = () => {
      setConnected(false); errorCount.current += 1;
      if (errorCount.current >= 5) setError(everConnected.current ? "Connection lost — refresh to reconnect." : "Could not connect. Is the backend running?");
      else setReconnecting(true);
    };

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ping" || event.type === "founder_steer") return;
      if (event.type === "session_expired") { setError("Session expired — backend was restarted. Run a new goal."); es.close(); return; }

      setAgents((prev) => {
        const next = { ...prev };
        const SEARCH_TOOLS = new Set(["web_search", "search_and_read", "news_search", "fetch_page", "patent_search", "search_and_fetch", "fetch_and_read", "research_papers"]);

        if (event.type === "plan_done") {
          setPlanTasks(event.tasks);
          for (const t of event.tasks) {
            next[t.agent] = { task_id: t.id, agent: t.agent, instruction: t.instruction, status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
          }
          if (!activeAgent && event.tasks.length > 0) setActiveAgent(event.tasks[0].agent);
          return next;
        }

        const agent = event.agent;
        if (!agent) return next;

        const cur: AgentState = next[agent] ?? { task_id: "", agent, instruction: "", status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
        const addLog = (type: string, text: string): LogEntry[] => [...cur.log, { ts: Date.now(), type, text }];

        if (event.type === "agent_start") {
          setActiveAgent(agent);
          next[agent] = { ...cur, status: "running", instruction: event.instruction ?? cur.instruction, task_id: event.task_id ?? cur.task_id, log: addLog("info", "Started") };
        } else if (event.type === "agent_action") {
          const rawArgs = event.args;
          const argsStr = typeof rawArgs === "string" ? rawArgs : (rawArgs?.query ?? rawArgs?.url ?? null);
          const isFetch = event.tool === "fetch_and_read" || event.tool === "fetch_page";
          const urlArg = isFetch ? (rawArgs?.url ?? argsStr ?? "") : "";
          const text = argsStr && event.tool && SEARCH_TOOLS.has(event.tool)
            ? `${event.tool.replace(/_/g, " ")}: "${String(argsStr).slice(0, 80)}"` : event.tool ?? event.action;
          next[agent] = {
            ...cur,
            currentAction: event.action, currentTool: event.tool ?? null, reasoning: event.reasoning ?? null,
            currentUrl: urlArg || cur.currentUrl,
            log: addLog("action", text),
          };
        } else if (event.type === "agent_action_result") {
          const ok = !event.result?.error;
          let text: string;
          let newUrl: string | undefined;
          if (!ok) {
            text = `✗ ${event.tool}: ${event.result?.error ?? "failed"}`;
          } else if (SEARCH_TOOLS.has(event.tool)) {
            const resultStr = typeof event.result === "string" ? event.result : JSON.stringify(event.result ?? "");
            const urlMatch = resultStr.match(/https?:\/\/[^\s"')\]]+/);
            newUrl = urlMatch?.[0]?.replace(/[.,;]+$/, "");
            text = newUrl ? `✓ Read ${newUrl.slice(0, 70)}…` : `✓ ${resultStr.slice(0, 80).replace(/\n/g, " ")}`;
          } else {
            text = `✓ ${TOOL_DESCRIPTIONS[event.tool] ?? event.tool ?? "Done"}`;
          }
          const newVisited = newUrl ? [...(cur.visitedUrls ?? []), newUrl] : cur.visitedUrls;
          const newCommit = event.result?.commit ?? event.result?.commits;
          const newCommits = newCommit
            ? [...(cur.commits ?? []), ...(Array.isArray(newCommit) ? newCommit : [String(newCommit)])]
            : cur.commits;
          next[agent] = { ...cur, log: addLog(ok ? "result" : "error", text), visitedUrls: newVisited, currentUrl: newUrl ?? cur.currentUrl, commits: newCommits };
        } else if (event.type === "agent_thinking") {
          next[agent] = { ...cur, log: addLog("info", `Thinking… (step ${event.iteration})`) };
        } else if (event.type === "agent_done") {
          const result = event.result ?? {};
          const previewUrl = (result.url ?? result.deployment_url ?? result.project_url ?? result.github_url) as string | undefined;
          next[agent] = { ...cur, status: "done", currentAction: null, currentTool: null, result, previewUrl, log: addLog("result", "Complete") };
        } else if (event.type === "agent_error") {
          next[agent] = { ...cur, status: "error", log: addLog("error", event.error ?? "Error") };
        } else if (event.type === "mirror_verdict") {
          next[agent] = { ...cur, mirrorVerdict: event.verdict, mirrorCritique: event.critique };
        } else if (event.type === "goal_done") { setDone(true); }
        else if (event.type === "goal_error") { setError(event.error ?? "Unknown error"); }

        return next;
      });
    };
    return () => es.close();
  }, [sessionId]);

  useEffect(() => {
    if (!done || notified.current) return;
    notified.current = true;
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Astra — goal complete", { body: "Your company is live.", icon: "/favicon.ico" });
    }
  }, [done, sessionId]);

  const agentList = planTasks.length > 0 ? sortAgentNamesByOrder(planTasks.map(t => t.agent)) : AGENT_ORDER;
  const doneCount = Object.values(agents).filter(a => a.status === "done").length;
  const total = agentList.length;

  const visibleAgents: Record<string, AgentState> = { ...agents };
  for (const a of agentList) {
    if (!visibleAgents[a]) visibleAgents[a] = { task_id: "", agent: a, instruction: "", status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
  }

  const selected = activeAgent || agentList[0] || "";
  const selectedState = visibleAgents[selected];
  const selectedPlanTask = planTasks.find(t => t.agent === selected);
  const title = company || instruction.slice(0, 48) || "Goal";

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--fg)", margin: 0 }}>{title}</h1>
          <span style={{
            fontSize: 11, letterSpacing: "0.06em", padding: "3px 10px", borderRadius: 999,
            color: done ? "#3D9E5F" : error ? "#C0392B" : reconnecting ? "#B45309" : connected ? "#2563EB" : "var(--fg-mute)",
            background: done ? "rgba(61,158,95,0.08)" : error ? "rgba(192,57,43,0.08)" : reconnecting ? "rgba(180,83,9,0.08)" : connected ? "rgba(37,99,235,0.08)" : "rgba(0,0,0,0.04)",
            border: `1px solid ${done ? "rgba(61,158,95,0.22)" : error ? "rgba(192,57,43,0.22)" : reconnecting ? "rgba(180,83,9,0.22)" : connected ? "rgba(37,99,235,0.22)" : "rgba(0,0,0,0.1)"}`,
          }}>
            {done ? "✦ complete" : error ? "error" : reconnecting ? "reconnecting…" : connected ? "running" : "connecting"}
          </span>
          <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>{sessionId}</span>
        </div>
        {total > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 3, borderRadius: 999, background: "rgba(0,0,0,0.08)", overflow: "hidden" }}>
              <div style={{ height: "100%", borderRadius: 999, transition: "width 0.7s", width: `${(doneCount / total) * 100}%`, background: done ? "linear-gradient(90deg,#3D9E5F,#5AC87A)" : "linear-gradient(90deg,#2563EB,#60A5FA)" }} />
            </div>
            <span style={{ fontSize: 11, color: "var(--fg-dim)", flexShrink: 0, fontFamily: "var(--font-jetbrains-mono)" }}>{doneCount}/{total}</span>
          </div>
        )}
        {total === 0 && connected && !error && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--fg-mute)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563EB" }} className="animate-pulse" />
            Planner building task graph…
          </div>
        )}
        {error && <p style={{ borderRadius: 8, border: "1px solid rgba(192,57,43,0.25)", background: "rgba(192,57,43,0.06)", padding: "8px 14px", fontSize: 12, color: "#C0392B", margin: 0 }}>{error}</p>}
      </div>

      {/* Main layout: sidebar + detail */}
      {agentList.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 12, alignItems: "start" }}>
          {/* Agent sidebar */}
          <div style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF", padding: "8px", display: "flex", flexDirection: "column", gap: 2 }}>
            <AgentSidebar agentList={agentList} agents={visibleAgents} activeAgent={selected} onSelect={setActiveAgent} />
          </div>

          {/* Detail panel */}
          <div style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF", padding: "18px 20px", minHeight: 480 }}>
            {selectedState ? (
              <AgentDetail state={selectedState} planTask={selectedPlanTask} />
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 200, color: "var(--fg-mute)", fontSize: 13 }}>Select an agent</div>
            )}
          </div>
        </div>
      )}

      {/* Bottom panels */}
      {connected && !error && <SteerPanel sessionId={sessionId} isRunning={!done} />}
      {planTasks.length > 0 && <AskPanel sessionId={sessionId} founderId={founderId} />}
    </div>
  );
}
