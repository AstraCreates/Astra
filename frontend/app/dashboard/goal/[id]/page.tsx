"use client";

import { use, useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { streamGoal, AGENT_LABELS, AGENT_ORDER, TOOL_DESCRIPTIONS, sortAgentNamesByOrder, sortAgentsByOrder } from "@/lib/api";
import { updateSession } from "@/lib/history";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AgentTask {
  id: string;
  agent: string;
  instruction: string;
}

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
}

interface LogEntry {
  ts: number;
  type: string;
  text: string;
}

const AGENT_ICONS: Record<string, string> = {
  research: "🔬", web: "🌐", marketing: "📢", technical: "⚙️",
  legal: "⚖️", ops: "🚀", sales: "🤝", design: "🎨",
};

function humanizeToolLog(action: string, tool?: string | null): string {
  if (action === "tool" && tool) return TOOL_DESCRIPTIONS[tool] ?? tool.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  if (action === "computer_use") return "Browser action";
  if (action === "delegate") return "Delegating to sub-agent";
  return action;
}

interface Artifact {
  label: string;
  value: string;
  href?: string;
  icon: string;
}

function extractArtifacts(agents: Record<string, AgentState>): Artifact[] {
  const arts: Artifact[] = [];
  for (const [agentName, state] of Object.entries(agents)) {
    if (state.status !== "done" || !state.result) continue;
    const r = state.result;
    if (agentName === "technical") {
      const repo = r.repo_url ?? r.github_url;
      if (repo && typeof repo === "string") arts.push({ label: "GitHub Repo", value: repo, href: repo, icon: "🐙" });
      const deploy = r.deployment_url ?? r.project_url;
      if (deploy && typeof deploy === "string") arts.push({ label: "Live App", value: deploy, href: deploy, icon: "🚀" });
    }
    if (agentName === "web") {
      const url = r.url ?? r.site_url ?? r.deployment_url;
      if (url && typeof url === "string") arts.push({ label: "Landing Page", value: url, href: url, icon: "🌐" });
    }
    if (agentName === "legal") {
      const path = r.path ?? r.filename;
      if (path) arts.push({ label: "Legal Doc", value: String(path), icon: "⚖️" });
    }
    if (agentName === "ops") {
      const pdf = r.pdf_path ?? r.output_path;
      if (pdf) arts.push({ label: "Pitch Deck", value: String(pdf), icon: "📄" });
    }
    if (agentName === "research") {
      const tam = r.tam ?? r.market_size;
      if (tam) arts.push({ label: "TAM", value: String(tam), icon: "📊" });
    }
  }
  return arts;
}

function ResultView({ agent, result }: { agent: string; result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(([, v]) => v !== null && v !== undefined && v !== "");
  function fmt(v: unknown, max = 180): string {
    if (!v && v !== 0) return "";
    if (typeof v === "string") return v.slice(0, max);
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    if (Array.isArray(v)) {
      const strs = v.map(i => typeof i === "object" && i ? ((i as Record<string, unknown>).name ?? JSON.stringify(i).slice(0, 60)) : String(i));
      return strs.slice(0, 3).join(", ") + (v.length > 3 ? ` +${v.length - 3}` : "");
    }
    return JSON.stringify(v).slice(0, max);
  }

  if (agent === "technical") {
    const repo = result.repo_url ?? result.github_url;
    const deploy = result.deployment_url ?? result.project_url;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {typeof repo === "string" && repo && (
          <a href={repo} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", padding: "6px 10px", color: "#8BA8C8", textDecoration: "none", fontSize: 12, fontFamily: "var(--font-mono)" }}>
            🐙 <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{repo}</span> <span style={{ opacity: 0.6 }}>↗</span>
          </a>
        )}
        {typeof deploy === "string" && deploy && (
          <a href={deploy} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 8, border: "1px solid rgba(30,106,255,0.22)", background: "rgba(30,106,255,0.08)", padding: "6px 10px", color: "#8BA8C8", textDecoration: "none", fontSize: 12, fontFamily: "var(--font-mono)" }}>
            🚀 <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{deploy}</span> <span style={{ opacity: 0.6 }}>↗</span>
          </a>
        )}
      </div>
    );
  }
  if (agent === "web") {
    const url = result.url ?? result.site_url ?? result.deployment_url;
    return typeof url === "string" && url ? (
      <a href={url} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 8, border: "1px solid rgba(30,106,255,0.22)", background: "rgba(30,106,255,0.08)", padding: "6px 10px", color: "#8BA8C8", textDecoration: "none", fontSize: 12, fontFamily: "var(--font-mono)" }}>
        🌐 <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{url}</span> <span style={{ opacity: 0.6 }}>↗</span>
      </a>
    ) : null;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {entries.slice(0, 4).map(([k, v]) => (
        <div key={k} style={{ fontSize: 12 }}>
          <span className="site-label">{k.replace(/_/g, " ")}: </span>
          <span style={{ color: "var(--fg)" }}>{fmt(v)}</span>
        </div>
      ))}
    </div>
  );
}

function AgentCard({ state }: { state: AgentState }) {
  const label = AGENT_LABELS[state.agent] ?? state.agent;
  const icon = AGENT_ICONS[state.agent] ?? "🤖";
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [state.log.length]);

  const isWaiting = state.status === "waiting";
  const isRunning = state.status === "running";
  const isDone = state.status === "done";
  const isError = state.status === "error";

  const borderColor = isDone ? "rgba(60,170,100,0.22)" : isRunning ? "rgba(30,106,255,0.32)" : isError ? "rgba(200,80,80,0.22)" : "rgba(255,255,255,0.08)";
  const glowColor = isDone ? "0 0 24px rgba(60,170,100,0.06)" : isRunning ? "0 0 24px rgba(30,106,255,0.08)" : "none";
  const dotColor = isDone ? "#6DC98A" : isRunning ? "#1E6AFF" : isError ? "#C97070" : "rgba(255,255,255,0.2)";

  return (
    <article style={{
      background: "rgba(255,255,255,0.07)",
      backdropFilter: "blur(28px) saturate(190%)",
      WebkitBackdropFilter: "blur(28px) saturate(190%)",
      border: `1px solid ${borderColor}`,
      boxShadow: `inset 0 1px 0 rgba(255,255,255,0.22), 0 8px 32px rgba(0,0,0,0.3), ${glowColor}`,
      borderRadius: 14, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10, transition: "border-color 0.4s, box-shadow 0.4s",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: dotColor, boxShadow: isRunning ? `0 0 6px ${dotColor}` : "none" }} className={isRunning ? "animate-pulse" : ""} />
          <span style={{ fontSize: 16, lineHeight: 1 }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 500, color: isWaiting ? "var(--fg-dim)" : "var(--fg)", letterSpacing: "0.01em" }}>{label}</span>
        </div>
        <span style={{
          fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: "var(--font-mono)",
          color: isDone ? "#6DC98A" : isRunning ? "#8BA8C8" : isError ? "#C97070" : "rgba(255,255,255,0.25)",
        }}>
          {state.status}
        </span>
      </div>

      {state.instruction && (
        <p style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {state.instruction}
        </p>
      )}

      {isRunning && state.currentAction && (
        <div style={{ display: "flex", alignItems: "center", gap: 7, borderRadius: 8, background: "rgba(30,106,255,0.07)", padding: "6px 11px", fontSize: 11, color: "rgba(200,220,240,0.8)" }}>
          <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#5E9AE0", flexShrink: 0 }} className="animate-pulse" />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{humanizeToolLog(state.currentAction, state.currentTool)}</span>
        </div>
      )}

      {state.log.length > 0 && (
        <div ref={logRef} style={{ maxHeight: 90, overflowY: "auto", borderRadius: 8, background: "rgba(0,0,0,0.25)", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 2 }}>
          {state.log.map((entry, i) => (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 10, lineHeight: 1.5 }}>
              <span style={{ fontFamily: "var(--font-mono)", flexShrink: 0, color: "rgba(255,255,255,0.2)", minWidth: 60 }}>
                {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span style={{ color: entry.type === "error" ? "#C97070" : entry.type === "result" ? "#6DC98A" : "rgba(255,255,255,0.45)" }}>{entry.text}</span>
            </div>
          ))}
        </div>
      )}

      {state.status === "done" && state.result && (
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          <ResultView agent={state.agent} result={state.result} />
          {state.mirrorVerdict && (
            <div style={{
              borderRadius: 8,
              background: state.mirrorVerdict === "pass" ? "rgba(60,170,100,0.06)" : state.mirrorVerdict === "block" ? "rgba(180,60,60,0.08)" : "rgba(200,140,50,0.07)",
              border: `1px solid ${state.mirrorVerdict === "pass" ? "rgba(60,170,100,0.18)" : state.mirrorVerdict === "block" ? "rgba(180,60,60,0.2)" : "rgba(200,140,50,0.18)"}`,
              padding: "8px 11px",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: state.mirrorCritique ? 5 : 0 }}>
                <span style={{ fontSize: 10, color: state.mirrorVerdict === "pass" ? "#6DC98A" : state.mirrorVerdict === "block" ? "#C97070" : "#E8A44A" }}>
                  {state.mirrorVerdict === "pass" ? "✓" : state.mirrorVerdict === "block" ? "✗" : "⚑"}
                </span>
                <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: state.mirrorVerdict === "pass" ? "#6DC98A" : state.mirrorVerdict === "block" ? "#C97070" : "#E8A44A" }}>
                  Mirror · {state.mirrorVerdict}
                </span>
              </div>
              {state.mirrorCritique && (
                <p style={{ margin: 0, fontSize: 11, color: "rgba(255,255,255,0.45)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {state.mirrorCritique}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function PlanPreview({ tasks }: { tasks: AgentTask[] }) {
  const orderedTasks = sortAgentsByOrder(tasks);
  return (
    <div style={{ background: "rgba(12,20,42,0.55)", backdropFilter: "blur(20px) saturate(160%)", WebkitBackdropFilter: "blur(20px) saturate(160%)", border: "1px solid rgba(255,255,255,0.07)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.07)", borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>📋</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Plan</span>
        <span style={{ fontSize: 11, color: "var(--fg-mute)", marginLeft: 4 }}>{tasks.length} agents in parallel</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {orderedTasks.map((t, i) => (
          <div key={t.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, borderRadius: 6, border: "1px solid var(--line)", background: "rgba(255,255,255,0.02)", padding: "8px 12px" }}>
            <span className="site-label" style={{ width: 20, flexShrink: 0, marginTop: 1 }}>{String(i + 1).padStart(2, "0")}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontSize: 12, color: "var(--fg)", display: "flex", alignItems: "center", gap: 6 }}>
                {AGENT_ICONS[t.agent] ?? "🤖"} {AGENT_LABELS[t.agent] ?? t.agent}
              </span>
              <span style={{ fontSize: 11, color: "var(--fg-mute)", display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{t.instruction}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CompletionSummary({ agents, instruction }: { agents: Record<string, AgentState>; instruction: string }) {
  const artifacts = extractArtifacts(agents);
  const doneCount = Object.values(agents).filter(a => a.status === "done").length;
  return (
    <div style={{ background: "rgba(255,255,255,0.06)", backdropFilter: "blur(24px) saturate(180%)", WebkitBackdropFilter: "blur(24px) saturate(180%)", border: "1px solid rgba(60,170,100,0.28)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.16), 0 0 30px rgba(60,170,100,0.06)", borderRadius: 12, padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 16 }}>✦</span>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>Complete</span>
          <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{doneCount} agents · {artifacts.length} artifacts</span>
        </div>
        {instruction && (
          <p style={{ fontSize: 12, color: "var(--fg-mute)", fontStyle: "italic", borderLeft: "2px solid rgba(30,106,255,0.28)", paddingLeft: 10, margin: 0 }}>
            &ldquo;{instruction.slice(0, 120)}{instruction.length > 120 ? "…" : ""}&rdquo;
          </p>
        )}
      </div>
      {artifacts.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {artifacts.map((art, i) => art.href ? (
            <a key={i} href={art.href} target="_blank" rel="noopener noreferrer"
              style={{ display: "flex", alignItems: "center", gap: 10, borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(255,255,255,0.04)", padding: "10px 14px", textDecoration: "none", transition: "all 0.15s" }}>
              <span style={{ fontSize: 18 }}>{art.icon}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{art.label}</div>
                <div style={{ fontSize: 12, color: "#8BA8C8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>{art.value}</div>
              </div>
              <span style={{ marginLeft: "auto", color: "var(--fg-mute)", fontSize: 14 }}>↗</span>
            </a>
          ) : (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, borderRadius: 8, border: "1px solid rgba(255,255,255,0.07)", background: "rgba(255,255,255,0.02)", padding: "10px 14px" }}>
              <span style={{ fontSize: 18 }}>{art.icon}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{art.label}</div>
                <div style={{ fontSize: 12, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{art.value}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, paddingTop: 4, borderTop: "1px solid var(--line)" }}>
        <Link href="/dashboard" className="site-btn site-btn-accent" style={{ fontSize: 13, padding: "0 18px" }}>New goal →</Link>
        <Link href="/dashboard/integrations" className="site-btn site-btn-ghost" style={{ fontSize: 13, padding: "0 18px" }}>Manage accounts</Link>
      </div>
    </div>
  );
}

function AskPanel({ sessionId, founderId }: { sessionId: string; founderId: string }) {
  const [target, setTarget] = useState("research");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const res = await fetch(`${BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_agent: target, question, founder_id: founderId, context: `session_id: ${sessionId}` }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setResponse(typeof data.response === "string" ? data.response : JSON.stringify(data.response, null, 2));
      setQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ask failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ background: "rgba(12,20,42,0.55)", backdropFilter: "blur(20px) saturate(160%)", WebkitBackdropFilter: "blur(20px) saturate(160%)", border: "1px solid rgba(255,255,255,0.07)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.07)", borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid rgba(255,255,255,0.06)", paddingBottom: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>💬</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Ask an agent</span>
        <span style={{ fontSize: 11, color: "var(--fg-mute)", marginLeft: "auto" }}>Follow-up after run</span>
      </div>
      <form onSubmit={ask} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <select value={target} onChange={e => setTarget(e.target.value)}
            className="site-input" style={{ padding: "8px 10px", fontSize: 12, width: 140, flexShrink: 0, background: "rgba(255,255,255,0.04)" }}>
            {Object.entries(AGENT_LABELS).map(([k, v]) => (
              <option key={k} value={k} style={{ background: "#0d1117" }}>{v}</option>
            ))}
          </select>
          <input value={question} onChange={e => setQuestion(e.target.value)}
            placeholder="What competitors should I watch?"
            className="site-input" style={{ padding: "8px 12px", fontSize: 12, flex: 1 }}
            disabled={loading} />
          <button type="submit" disabled={loading || !question.trim()}
            className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 13, flexShrink: 0 }}>
            {loading ? "…" : "Ask →"}
          </button>
        </div>
        {error && <p style={{ fontSize: 11, color: "#C97070" }}>{error}</p>}
        {response && (
          <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "12px 14px", fontSize: 12, color: "var(--fg-dim)", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
            {response}
          </div>
        )}
      </form>
    </div>
  );
}

function SteerPanel({ sessionId, isRunning }: { sessionId: string; isRunning: boolean }) {
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<string[]>([]);

  async function steer(e: React.FormEvent) {
    e.preventDefault();
    const msg = message.trim();
    if (!msg) return;
    setSending(true);
    try {
      await fetch(`${BASE}/steer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: msg }),
      });
      setSent(prev => [...prev, msg]);
      setMessage("");
    } catch {
      /* ignore */
    } finally {
      setSending(false);
    }
  }

  return (
    <div style={{ background: "rgba(255,255,255,0.06)", backdropFilter: "blur(24px) saturate(180%)", WebkitBackdropFilter: "blur(24px) saturate(180%)", border: "1px solid rgba(30,106,255,0.20)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.12)", borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid rgba(255,255,255,0.06)", paddingBottom: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>✦</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>Steer</span>
        <span style={{ fontSize: 11, color: "var(--fg-mute)", marginLeft: "auto" }}>
          {isRunning ? "Live — agents will pick up your directive" : "Run finished"}
        </span>
      </div>

      {sent.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 10 }}>
          {sent.map((m, i) => (
            <div key={i} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, background: "rgba(30,106,255,0.08)", color: "rgba(200,220,240,0.8)", borderLeft: "2px solid rgba(30,106,255,0.35)" }}>
              {m}
            </div>
          ))}
        </div>
      )}

      <form onSubmit={steer} style={{ display: "flex", gap: 8 }}>
        <input
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder={isRunning ? "Focus on B2B SaaS companies only…" : "Run a new goal to steer"}
          disabled={!isRunning || sending}
          className="site-input"
          style={{ flex: 1, padding: "8px 12px", fontSize: 12 }}
        />
        <button type="submit" disabled={!isRunning || sending || !message.trim()}
          className="site-btn site-btn-primary" style={{ padding: "0 16px", fontSize: 13, flexShrink: 0 }}>
          {sending ? "…" : "Send →"}
        </button>
      </form>
    </div>
  );
}

export default function GoalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = use(params);
  const searchParams = useSearchParams();
  const instruction = searchParams.get("instruction") ?? "";
  const founderId = searchParams.get("founder") ?? "founder_001";
  const company = searchParams.get("company") ?? "";

  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [planTasks, setPlanTasks] = useState<AgentTask[]>([]);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const everConnected = useRef(false);
  const notified = useRef(false);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined") return;
    const es = streamGoal(sessionId);
    es.onopen = () => { setConnected(true); everConnected.current = true; };
    es.onerror = () => {
      setConnected(false);
      if (everConnected.current) setError("Connection lost — refresh to reconnect.");
      else setError("Could not connect. Is the backend running?");
    };

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ping") return;
      if (event.type === "founder_steer") return;
      if (event.type === "session_expired") { setError("Session expired — backend was restarted. Run a new goal."); es.close(); return; }

      setAgents((prev) => {
        const next = { ...prev };

        if (event.type === "plan_done") {
          setPlanTasks(event.tasks);
          for (const t of event.tasks) {
            next[t.agent] = { task_id: t.id, agent: t.agent, instruction: t.instruction, status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [] };
          }
          return next;
        }

        const agent = event.agent;
        if (!agent) return next;

        const cur = next[agent] ?? { task_id: "", agent, instruction: "", status: "waiting" as const, currentAction: null, currentTool: null, reasoning: null, result: null, log: [] };
        const addLog = (type: string, text: string): LogEntry[] => [...cur.log, { ts: Date.now(), type, text }];

        if (event.type === "agent_start") {
          next[agent] = { ...cur, status: "running", instruction: event.instruction ?? cur.instruction, task_id: event.task_id ?? cur.task_id, log: addLog("info", "Started") };
        } else if (event.type === "agent_action") {
          const text = humanizeToolLog(event.action, event.tool);
          next[agent] = { ...cur, currentAction: event.action, currentTool: event.tool ?? null, reasoning: event.reasoning ?? null, log: addLog("action", text) };
        } else if (event.type === "agent_action_result") {
          const ok = !event.result?.error;
          const text = ok ? `✓ ${TOOL_DESCRIPTIONS[event.tool] ?? event.tool ?? "Done"}` : `✗ ${event.tool}: ${event.result?.error ?? "failed"}`;
          next[agent] = { ...cur, log: addLog(ok ? "result" : "error", text) };
        } else if (event.type === "agent_thinking") {
          next[agent] = { ...cur, log: addLog("info", `Thinking… (step ${event.iteration})`) };
        } else if (event.type === "agent_done") {
          next[agent] = { ...cur, status: "done", currentAction: null, currentTool: null, result: event.result ?? {}, log: addLog("result", "Complete") };
        } else if (event.type === "agent_error") {
          next[agent] = { ...cur, status: "error", log: addLog("error", event.error ?? "Error") };
        } else if (event.type === "mirror_verdict") {
          next[agent] = { ...cur, mirrorVerdict: event.verdict, mirrorCritique: event.critique };
        } else if (event.type === "goal_done") {
          setDone(true);
        } else if (event.type === "goal_error") {
          setError(event.error ?? "Unknown error");
        }

        return next;
      });
    };

    return () => es.close();
  }, [sessionId]);

  useEffect(() => {
    if (!done || notified.current) return;
    notified.current = true;
    const arts = extractArtifacts(agents);
    updateSession(sessionId, { status: "done", artifacts: arts });
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Astra — goal complete", {
        body: `Your company is live. ${arts.length} artifacts ready.`,
        icon: "/favicon.ico",
      });
    }
  }, [done, agents, sessionId]);

  const agentList = planTasks.length > 0 ? sortAgentNamesByOrder(planTasks.map(t => t.agent)) : AGENT_ORDER;
  const doneCount = Object.values(agents).filter(a => a.status === "done").length;
  const total = agentList.length;

  const visibleAgents: Record<string, AgentState> = { ...agents };
  for (const a of agentList) {
    if (!visibleAgents[a]) visibleAgents[a] = { task_id: "", agent: a, instruction: "", status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [] };
  }

  const title = company || instruction.slice(0, 48) || "Goal";

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Compact header */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: "var(--fg)", margin: 0, lineHeight: 1.2 }}>{title}</h1>
          <span style={{
            fontSize: 11, letterSpacing: "0.08em", padding: "3px 10px", borderRadius: 999,
            color: done ? "#6DC98A" : error ? "#C97070" : connected ? "#8BA8C8" : "var(--fg-mute)",
            background: done ? "rgba(50,160,90,0.12)" : error ? "rgba(180,60,60,0.12)" : connected ? "rgba(30,106,255,0.12)" : "rgba(255,255,255,0.05)",
            border: `1px solid ${done ? "rgba(70,180,110,0.28)" : error ? "rgba(180,60,60,0.28)" : connected ? "rgba(30,106,255,0.28)" : "rgba(255,255,255,0.1)"}`,
          }}>
            {done ? "✦ complete" : error ? "error" : connected ? "running" : "connecting"}
          </span>
          <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{sessionId}</span>
        </div>

        {instruction && (
          <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: 0, lineHeight: 1.5, borderLeft: "2px solid rgba(30,106,255,0.3)", paddingLeft: 10 }}>
            {instruction.slice(0, 140)}{instruction.length > 140 ? "…" : ""}
          </p>
        )}

        {/* Progress bar */}
        {total > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 4, borderRadius: 999, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
              <div style={{
                height: "100%", borderRadius: 999, transition: "width 0.7s",
                width: `${(doneCount / total) * 100}%`,
                background: done ? "linear-gradient(90deg,#3EA870,#6DC98A)" : "linear-gradient(90deg,#1E6AFF,#5E9AE0)",
              }} />
            </div>
            <span style={{ fontSize: 12, color: "var(--fg-dim)", flexShrink: 0, fontFamily: "var(--font-mono)" }}>{doneCount}/{total}</span>
          </div>
        )}

        {/* Planning spinner */}
        {total === 0 && connected && !error && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--fg-mute)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#1E6AFF", flexShrink: 0 }} className="animate-pulse" />
            Planner breaking goal into tasks… (~30–60s)
          </div>
        )}

        {error && (
          <p style={{ borderRadius: 8, border: "1px solid rgba(180,60,60,0.35)", background: "rgba(80,20,20,0.3)", padding: "8px 14px", fontSize: 12, color: "#fca5a5", margin: 0 }}>{error}</p>
        )}
      </div>

      {/* Completion summary */}
      {done && <CompletionSummary agents={visibleAgents} instruction={instruction} />}

      {/* Plan preview — while running */}
      {planTasks.length > 0 && !done && <PlanPreview tasks={planTasks} />}

      {/* Agent grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
        {agentList.map((agent) => (
          <AgentCard key={agent} state={visibleAgents[agent]} />
        ))}
      </div>

      {/* Steer panel — live while running */}
      {connected && !error && (
        <SteerPanel sessionId={sessionId} isRunning={!done} />
      )}

      {/* Ask panel — follow-up after done */}
      {planTasks.length > 0 && (
        <AskPanel sessionId={sessionId} founderId={founderId} />
      )}
    </div>
  );
}
