"use client";

import { use, useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { streamGoal, AGENT_LABELS, AGENT_ORDER, TOOL_DESCRIPTIONS } from "@/lib/api";

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
}

interface LogEntry {
  ts: number;
  type: string;
  text: string;
}

const AGENT_ICONS: Record<string, string> = {
  research: "🔬",
  web: "🌐",
  marketing: "📢",
  technical: "⚙️",
  legal: "⚖️",
  ops: "🚀",
  sales: "🤝",
  design: "🎨",
};

function humanizeToolLog(action: string, tool?: string | null, args?: Record<string, unknown> | null): string {
  if (action === "tool" && tool) {
    const desc = TOOL_DESCRIPTIONS[tool];
    if (desc) return desc;
    // fallback: prettify tool name
    return tool.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }
  if (action === "computer_use") {
    const a = (args as Record<string, unknown> | null)?.action ?? "";
    const url = (args as Record<string, unknown> | null)?.url ?? (args as Record<string, unknown> | null)?.selector ?? "";
    return `Browser: ${a} ${url}`.trim();
  }
  if (action === "delegate") {
    return `Delegating to ${(args as Record<string, unknown> | null)?.target ?? "agent"}`;
  }
  return action;
}

// ── Artifact extractor ─────────────────────────────────────────────────────
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
      const repo = r.repo_url;
      if (repo && typeof repo === "string") arts.push({ label: "Web Repo", value: repo, href: repo, icon: "🐙" });
    }

    if (agentName === "legal") {
      const path = r.path ?? r.filename;
      if (path && typeof path === "string") arts.push({ label: "Legal Doc", value: String(path), icon: "⚖️" });
    }

    if (agentName === "ops") {
      const pdf = r.pdf_path ?? r.output_path;
      if (pdf && typeof pdf === "string") arts.push({ label: "Pitch Deck", value: String(pdf), icon: "📄" });
    }

    if (agentName === "research") {
      const tam = r.tam ?? r.market_size;
      if (tam) arts.push({ label: "Market Size (TAM)", value: String(tam), icon: "📊" });
    }
  }

  return arts;
}

// ── Result card per agent ──────────────────────────────────────────────────
function ResultView({ agent, result }: { agent: string; result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(([, v]) => v !== null && v !== undefined && v !== "");

  function fmt(v: unknown, max = 180): string {
    if (!v && v !== 0) return "";
    if (typeof v === "string") return v.slice(0, max);
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    if (Array.isArray(v)) {
      const strs = v.map(i =>
        typeof i === "object" && i ? ((i as Record<string, unknown>).name ?? (i as Record<string, unknown>).title ?? JSON.stringify(i).slice(0, 60)) : String(i)
      );
      return strs.slice(0, 3).join(", ") + (v.length > 3 ? ` +${v.length - 3}` : "");
    }
    return JSON.stringify(v).slice(0, max);
  }

  // Technical — show repo + deploy as links first
  if (agent === "technical") {
    const repo = result.repo_url ?? result.github_url;
    const deploy = result.deployment_url ?? result.project_url;
    return (
      <div className="flex flex-col gap-3 text-sm">
        {repo && typeof repo === "string" && (
          <a href={repo} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-indigo-300 hover:text-indigo-200 hover:border-indigo-500/40 transition-colors">
            <span>🐙</span>
            <span className="font-mono text-xs truncate">{repo}</span>
            <span className="ml-auto text-xs opacity-60">↗</span>
          </a>
        )}
        {deploy && typeof deploy === "string" && (
          <a href={deploy} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-[rgba(99,102,241,0.3)] bg-[rgba(99,102,241,0.08)] px-3 py-2 text-indigo-300 hover:text-indigo-200 hover:border-indigo-500/50 transition-colors">
            <span>🚀</span>
            <span className="font-mono text-xs truncate">{deploy}</span>
            <span className="ml-auto text-xs opacity-60">↗</span>
          </a>
        )}
        {entries
          .filter(([k]) => !["repo_url","github_url","deployment_url","project_url"].includes(k))
          .slice(0, 3)
          .map(([k, v]) => (
            <div key={k}>
              <span className="site-label">{k.replace(/_/g, " ")}: </span>
              <span className="text-[var(--fg)]">{fmt(v)}</span>
            </div>
          ))}
      </div>
    );
  }

  // Web — show live URL
  if (agent === "web") {
    const url = result.url ?? result.site_url ?? result.deployment_url;
    return (
      <div className="flex flex-col gap-2">
        {url && typeof url === "string" && (
          <a href={url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-[rgba(99,102,241,0.3)] bg-[rgba(99,102,241,0.08)] px-3 py-2 text-indigo-300 hover:text-indigo-200 transition-colors">
            <span>🌐</span>
            <span className="font-mono text-xs">{url}</span>
            <span className="ml-auto text-xs opacity-60">↗</span>
          </a>
        )}
      </div>
    );
  }

  // Research — key metrics
  if (agent === "research") {
    return (
      <div className="flex flex-col gap-2 text-sm">
        {entries.slice(0, 5).map(([k, v]) => (
          <div key={k}>
            <span className="site-label">{k.replace(/_/g, " ")}: </span>
            <span className="text-[var(--fg)]">{fmt(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  // Legal — doc path + type
  if (agent === "legal") {
    return (
      <div className="flex flex-col gap-2 text-sm">
        {entries.filter(([k]) => ["generated","path","filename","doc_type","error"].includes(k)).map(([k, v]) => (
          <div key={k}>
            <span className="site-label">{k.replace(/_/g, " ")}: </span>
            <span className={k === "error" ? "text-red-400" : "text-[var(--fg)]"}>{fmt(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  // Default — compact key/value
  return (
    <div className="flex flex-col gap-2 text-sm">
      {entries.slice(0, 4).map(([k, v]) => (
        <div key={k}>
          <span className="site-label">{k.replace(/_/g, " ")}: </span>
          <span className="text-[var(--fg)]">{fmt(v)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Agent card ─────────────────────────────────────────────────────────────
function AgentCard({ state }: { state: AgentState }) {
  const label = AGENT_LABELS[state.agent] ?? state.agent;
  const icon = AGENT_ICONS[state.agent] ?? "🤖";
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [state.log.length]);

  const borderColor =
    state.status === "done"    ? "border-green-700/50" :
    state.status === "running" ? "border-indigo-500/60" :
    state.status === "error"   ? "border-red-700/50" :
                                 "border-[var(--glass-border)]";

  const dotColor =
    state.status === "done"    ? "bg-green-400" :
    state.status === "running" ? "bg-indigo-400 animate-pulse" :
    state.status === "error"   ? "bg-red-400" :
                                 "bg-zinc-600";

  return (
    <article className={`site-card p-5 flex flex-col gap-4 transition-all duration-300 ${borderColor}`}>
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`} />
          <span className="text-lg">{icon}</span>
          <h3 className="text-lg text-white">{label}</h3>
        </div>
        <span className={`site-pill px-2 py-1 ${
          state.status === "done"    ? "text-green-400 bg-green-950/40 border-green-800/50" :
          state.status === "running" ? "text-indigo-300 bg-indigo-950/40 border-indigo-700/50" :
          state.status === "error"   ? "text-red-400 bg-red-950/40 border-red-800/50" :
                                       ""
        }`}>
          {state.status}
        </span>
      </div>

      {state.instruction && (
        <p className="text-sm leading-6 text-[var(--fg-dim)] line-clamp-2">{state.instruction}</p>
      )}

      {state.status === "running" && state.currentAction && (
        <div className="flex items-center gap-2 rounded-xl border border-indigo-800/40 bg-indigo-950/20 px-3 py-2 text-sm text-indigo-200">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse flex-shrink-0" />
          <span className="truncate">
            {humanizeToolLog(state.currentAction, state.currentTool)}
            {state.reasoning ? ` — ${state.reasoning.slice(0, 60)}` : ""}
          </span>
        </div>
      )}

      {state.log.length > 0 && (
        <div ref={logRef} className="max-h-36 overflow-y-auto rounded-xl border border-[var(--line)] bg-[rgba(0,0,10,0.55)] p-3 flex flex-col gap-1">
          {state.log.map((entry, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className="font-mono flex-shrink-0 text-[var(--fg-mute)]">
                {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className={
                entry.type === "error"   ? "text-red-400" :
                entry.type === "result"  ? "text-green-400" :
                entry.type === "browser" ? "text-blue-400" :
                                           "text-zinc-400"
              }>
                {entry.text}
              </span>
            </div>
          ))}
        </div>
      )}

      {state.status === "done" && state.result && (
        <div className="border-t border-[var(--line)] pt-4">
          <ResultView agent={state.agent} result={state.result} />
        </div>
      )}
    </article>
  );
}

// ── Completion summary ─────────────────────────────────────────────────────
function CompletionSummary({ agents, instruction }: { agents: Record<string, AgentState>; instruction: string }) {
  const artifacts = extractArtifacts(agents);
  const doneAgents = Object.values(agents).filter(a => a.status === "done").length;

  return (
    <div className="site-card p-6 sm:p-8 flex flex-col gap-6">
      {/* Inner highlight already handled by .site-card::before */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <span className="text-2xl">✦</span>
          <div>
            <h2 className="text-2xl sm:text-3xl text-white" style={{ fontFamily: "var(--font-display)" }}>
              Your company is live.
            </h2>
            <p className="mt-1 text-sm text-[var(--fg-dim)]">
              {doneAgents} agents completed — {artifacts.length} artifacts ready.
            </p>
          </div>
        </div>
        {instruction && (
          <p className="text-sm text-[var(--fg-mute)] italic border-l-2 border-indigo-600/50 pl-3">
            &ldquo;{instruction.slice(0, 120)}{instruction.length > 120 ? "…" : ""}&rdquo;
          </p>
        )}
      </div>

      {artifacts.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {artifacts.map((art, i) => (
            art.href ? (
              <a key={i} href={art.href} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.04)] px-4 py-3 hover:border-indigo-500/40 hover:bg-[rgba(99,102,241,0.08)] transition-all group">
                <span className="text-xl flex-shrink-0">{art.icon}</span>
                <div className="flex flex-col min-w-0">
                  <span className="text-xs text-[var(--fg-mute)] uppercase tracking-wider">{art.label}</span>
                  <span className="text-sm text-indigo-300 group-hover:text-indigo-200 truncate font-mono">{art.value}</span>
                </div>
                <span className="ml-auto text-[var(--fg-mute)] group-hover:text-indigo-300 transition-colors flex-shrink-0">↗</span>
              </a>
            ) : (
              <div key={i} className="flex items-center gap-3 rounded-xl border border-[rgba(255,255,255,0.07)] bg-[rgba(255,255,255,0.025)] px-4 py-3">
                <span className="text-xl flex-shrink-0">{art.icon}</span>
                <div className="flex flex-col min-w-0">
                  <span className="text-xs text-[var(--fg-mute)] uppercase tracking-wider">{art.label}</span>
                  <span className="text-sm text-[var(--fg)] truncate">{art.value}</span>
                </div>
              </div>
            )
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-3 pt-2 border-t border-[var(--line)]">
        <Link href="/" className="site-btn site-btn-primary px-5">
          New goal →
        </Link>
        <Link href="/setup" className="site-btn site-btn-ghost px-5">
          Manage accounts
        </Link>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function GoalPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = use(params);
  const searchParams = useSearchParams();
  const instruction = searchParams.get("instruction") ?? "";

  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [planTasks, setPlanTasks] = useState<AgentTask[]>([]);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const everConnected = useRef(false);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined") return;
    const es = streamGoal(sessionId);
    es.onopen = () => { setConnected(true); everConnected.current = true; };
    es.onerror = () => {
      setConnected(false);
      if (everConnected.current) {
        setError("Connection lost. Goal may still be running — refresh to reconnect.");
      } else {
        setError("Could not connect to backend. Is the server running?");
      }
    };

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ping") return;

      setAgents((prev) => {
        const next = { ...prev };

        if (event.type === "goal_start") return next;

        if (event.type === "plan_done") {
          setPlanTasks(event.tasks);
          for (const t of event.tasks) {
            next[t.agent] = {
              task_id: t.id,
              agent: t.agent,
              instruction: t.instruction,
              status: "waiting",
              currentAction: null,
              currentTool: null,
              reasoning: null,
              result: null,
              log: [],
            };
          }
          return next;
        }

        const agent = event.agent;
        if (!agent) return next;

        const cur = next[agent] ?? {
          task_id: "",
          agent,
          instruction: "",
          status: "waiting" as const,
          currentAction: null,
          currentTool: null,
          reasoning: null,
          result: null,
          log: [],
        };

        const addLog = (type: string, text: string): LogEntry[] =>
          [...cur.log, { ts: Date.now(), type, text }];

        if (event.type === "agent_start") {
          next[agent] = { ...cur, status: "running", instruction: event.instruction ?? cur.instruction, task_id: event.task_id ?? cur.task_id, log: addLog("info", `Started`) };
        } else if (event.type === "agent_action") {
          const text = humanizeToolLog(event.action, event.tool, event.detail ?? event.args);
          next[agent] = { ...cur, currentAction: event.action, currentTool: event.tool ?? null, reasoning: event.reasoning ?? null, log: addLog("action", text) };
        } else if (event.type === "agent_action_result") {
          const ok = !event.result?.error;
          const text = ok
            ? `✓ ${TOOL_DESCRIPTIONS[event.tool] ?? (event.tool ?? "Done")}`
            : `✗ ${event.tool ?? "error"}: ${event.result?.error ?? "failed"}`;
          next[agent] = { ...cur, log: addLog(ok ? "result" : "error", text) };
        } else if (event.type === "agent_thinking") {
          next[agent] = { ...cur, log: addLog("info", `Thinking… (step ${event.iteration})`) };
        } else if (event.type === "agent_done") {
          next[agent] = { ...cur, status: "done", currentAction: null, currentTool: null, result: event.result ?? {}, log: addLog("result", "Complete") };
        } else if (event.type === "agent_error") {
          next[agent] = { ...cur, status: "error", log: addLog("error", event.error ?? "Error") };
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

  const agentList = planTasks.length > 0
    ? [...new Set(planTasks.map((t) => t.agent))]
    : AGENT_ORDER;

  const doneCount = Object.values(agents).filter((a) => a.status === "done").length;
  const total = agentList.length;

  const visibleAgents: Record<string, AgentState> = { ...agents };
  for (const a of agentList) {
    if (!visibleAgents[a]) {
      visibleAgents[a] = {
        task_id: "", agent: a, instruction: "", status: "waiting",
        currentAction: null, currentTool: null, reasoning: null, result: null, log: [],
      };
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
        <div className="flex flex-col gap-5">
          <div className="eyebrow">Goal stream</div>
          <h1 className="max-w-4xl text-[clamp(44px,5.4vw,88px)] leading-[0.95]">
            Astra is building<br />
            <span className="display-italic">your company.</span>
          </h1>
          {instruction && (
            <p className="lede max-w-2xl italic text-[var(--fg-mute)] border-l-2 border-indigo-600/40 pl-4">
              &ldquo;{instruction}&rdquo;
            </p>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <span className={`site-pill px-3 py-2 ${
              done  ? "text-green-400 border-green-800 bg-green-950/30" :
              error ? "text-red-400 border-red-800 bg-red-950/30" :
                      "text-indigo-300 border-indigo-800 bg-indigo-950/30"
            }`}>
              {done ? "✦ complete" : error ? "error" : connected ? "running" : "connecting"}
            </span>
            <span className="site-label break-all font-mono text-xs">{sessionId}</span>
          </div>

          {total > 0 && (
            <div className="flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgba(246,246,248,0.05)]">
                <div
                  className="h-1.5 rounded-full transition-all duration-700"
                  style={{
                    width: `${(doneCount / total) * 100}%`,
                    background: done
                      ? "linear-gradient(90deg, #22c55e, #4ade80)"
                      : "linear-gradient(90deg, #6366f1, #8b5cf6)",
                  }}
                />
              </div>
              <span className="flex-shrink-0 text-sm text-[var(--fg-dim)]">{doneCount}/{total} agents</span>
            </div>
          )}

          {!connected && !error && (
            <div className="flex items-center gap-2 text-sm text-[var(--fg-dim)]">
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
              Connecting to agent stream…
            </div>
          )}

          {error && (
            <p className="rounded-2xl border border-red-900/70 bg-red-950/25 px-4 py-3 text-sm text-red-300">{error}</p>
          )}
        </div>

        <div className="site-card p-5">
          <div className="flex items-center justify-between border-b border-[var(--line)] pb-4">
            <div>
              <p className="site-label">Runtime</p>
              <p className="mt-2 text-sm text-[var(--fg-dim)]">
                Live view of every agent as it works through your goal.
              </p>
            </div>
            <span className="site-pill">{connected ? "stream live" : "stream idle"}</span>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="site-card-soft p-4 rounded-xl">
              <p className="site-label">Done</p>
              <p className="mt-3 text-3xl text-white">{doneCount}</p>
            </div>
            <div className="site-card-soft p-4 rounded-xl">
              <p className="site-label">Total</p>
              <p className="mt-3 text-3xl text-white">{total}</p>
            </div>
          </div>
        </div>
      </section>

      {/* Completion summary — appears when all agents done */}
      {done && (
        <CompletionSummary agents={visibleAgents} instruction={instruction} />
      )}

      {total === 0 && connected && !error && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3 text-sm text-[var(--fg-dim)]">
            <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
            Planner is breaking your goal into tasks… (~30–60s)
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-[rgba(246,246,248,0.05)]">
            <div className="h-1 w-full animate-pulse rounded-full bg-indigo-500/50" />
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {agentList.map((agent) => (
          <AgentCard key={agent} state={visibleAgents[agent]} />
        ))}
      </div>

      {/* New goal footer CTA */}
      {done && (
        <div className="flex flex-wrap gap-3 pb-4">
          <Link href="/" className="site-btn site-btn-primary px-6">
            Launch another goal →
          </Link>
          <Link href="/setup" className="site-btn site-btn-ghost px-5">
            Manage integrations
          </Link>
        </div>
      )}
    </div>
  );
}
