"use client";

import { use, useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { streamGoal, AGENT_LABELS, AGENT_ORDER } from "@/lib/api";

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
};

function AgentCard({ state }: { state: AgentState }) {
  const label = AGENT_LABELS[state.agent] ?? state.agent;
  const icon = AGENT_ICONS[state.agent] ?? "🤖";
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [state.log.length]);

  const borderColor =
    state.status === "done" ? "border-green-800" :
    state.status === "running" ? "border-violet-600" :
    state.status === "error" ? "border-red-800" :
    "border-zinc-800";

  const dotColor =
    state.status === "done" ? "bg-green-400" :
    state.status === "running" ? "bg-violet-400 animate-pulse" :
    state.status === "error" ? "bg-red-400" :
    "bg-zinc-600";

  return (
    <div className={`rounded-xl border ${borderColor} bg-zinc-900 p-5 flex flex-col gap-3 transition-all duration-300`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`} />
          <span className="text-lg">{icon}</span>
          <h3 className="font-semibold text-zinc-200">{label}</h3>
        </div>
        <span className={`text-xs font-mono uppercase px-2 py-0.5 rounded ${
          state.status === "done" ? "text-green-400 bg-green-950/40" :
          state.status === "running" ? "text-violet-300 bg-violet-950/40" :
          state.status === "error" ? "text-red-400 bg-red-950/40" :
          "text-zinc-500 bg-zinc-800"
        }`}>
          {state.status}
        </span>
      </div>

      {state.instruction && (
        <p className="text-zinc-500 text-xs leading-relaxed line-clamp-2">{state.instruction}</p>
      )}

      {state.status === "running" && state.currentAction && (
        <div className="flex items-center gap-2 text-sm text-violet-300 bg-violet-950/20 rounded-lg px-3 py-2">
          <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse flex-shrink-0" />
          <span className="truncate">
            {state.currentTool ? `Using ${state.currentTool}` : state.currentAction}
            {state.reasoning ? ` — ${state.reasoning}` : ""}
          </span>
        </div>
      )}

      {state.log.length > 0 && (
        <div ref={logRef} className="bg-zinc-950 rounded-lg p-3 max-h-36 overflow-y-auto flex flex-col gap-1">
          {state.log.map((entry, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className="text-zinc-600 font-mono flex-shrink-0">
                {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className={
                entry.type === "error" ? "text-red-400" :
                entry.type === "result" ? "text-green-400" :
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
        <div className="border-t border-zinc-800 pt-3">
          <ResultView agent={state.agent} result={state.result} />
        </div>
      )}
    </div>
  );
}

function formatValue(v: unknown, maxLen = 160): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v.slice(0, maxLen);
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) {
    const items = v.map((item) =>
      typeof item === "object" && item !== null
        ? (item as Record<string, unknown>).name ?? (item as Record<string, unknown>).title ?? (item as Record<string, unknown>).text ?? JSON.stringify(item).slice(0, 60)
        : String(item)
    );
    return items.slice(0, 3).join(", ") + (v.length > 3 ? ` +${v.length - 3} more` : "");
  }
  return JSON.stringify(v).slice(0, maxLen);
}

function ResultView({ agent, result }: { agent: string; result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(([, v]) => v !== null && v !== undefined && v !== "");

  if (agent === "research") {
    return (
      <div className="flex flex-col gap-2 text-sm">
        {entries.slice(0, 5).map(([k, v]) => (
          <div key={k}>
            <span className="text-zinc-500 text-xs uppercase">{k.replace(/_/g, " ")}: </span>
            <span className="text-zinc-300">{formatValue(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  if (agent === "web" && result.site_url) {
    return (
      <a href={String(result.site_url)} target="_blank" rel="noopener noreferrer"
        className="text-violet-400 hover:underline text-sm font-mono">
        {String(result.site_url)} ↗
      </a>
    );
  }

  if (agent === "legal") {
    return (
      <div className="flex flex-col gap-2 text-sm">
        {entries.filter(([k]) => ["generated", "path", "filename", "doc_type", "error"].includes(k)).map(([k, v]) => (
          <div key={k}>
            <span className="text-zinc-500 text-xs uppercase">{k.replace(/_/g, " ")}: </span>
            <span className={k === "error" ? "text-red-400" : "text-zinc-300"}>{formatValue(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  if (agent === "marketing") {
    return (
      <div className="flex flex-col gap-2 text-sm">
        {entries.filter(([k]) => !["script", "caption", "visual_notes"].includes(k)).slice(0, 4).map(([k, v]) => (
          <div key={k}>
            <span className="text-zinc-500 text-xs uppercase">{k.replace(/_/g, " ")}: </span>
            <span className="text-zinc-300">{formatValue(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <pre className="text-xs text-zinc-400 overflow-auto max-h-32 whitespace-pre-wrap">
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}

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
        setError("Connection lost. The goal may still be running — refresh to reconnect.");
      } else {
        setError("Could not connect to backend. Is the server running?");
      }
    };

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ping") return;

      setAgents((prev) => {
        const next = { ...prev };

        if (event.type === "goal_start") {
        return next; // just confirms connection is alive
      }

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
          next[agent] = { ...cur, status: "running", instruction: event.instruction ?? cur.instruction, task_id: event.task_id ?? cur.task_id, log: addLog("info", `Started: ${event.instruction ?? ""}`) };
        } else if (event.type === "agent_action") {
          const text = event.action === "tool"
            ? `Tool: ${event.tool}(${JSON.stringify(event.args ?? {}).slice(0, 80)})`
            : event.action === "computer_use"
            ? `Browser: ${event.detail?.action ?? ""} ${event.detail?.url ?? event.detail?.selector ?? ""}`
            : event.action === "delegate"
            ? `Delegate → ${event.target}: ${(event.task ?? "").slice(0, 60)}`
            : event.action;
          next[agent] = { ...cur, currentAction: event.action, currentTool: event.tool ?? null, reasoning: event.reasoning ?? null, log: addLog("action", text) };
        } else if (event.type === "agent_action_result") {
          const ok = !event.result?.error;
          const text = event.action === "computer_use"
            ? `Browser → ${event.url ?? "?"}`
            : ok
            ? `✓ ${event.tool ?? "result"} OK`
            : `✗ ${event.tool ?? "error"}: ${event.result?.error ?? "failed"}`;
          next[agent] = { ...cur, log: addLog(ok ? "result" : "error", text) };
        } else if (event.type === "agent_thinking") {
          next[agent] = { ...cur, log: addLog("info", `Thinking… (attempt ${event.iteration})`) };
        } else if (event.type === "agent_done") {
          next[agent] = { ...cur, status: "done", currentAction: null, currentTool: null, result: event.result ?? {}, log: addLog("result", "Done") };
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
    ? planTasks.map((t) => t.agent)
    : AGENT_ORDER;

  const doneCount = Object.values(agents).filter((a) => a.status === "done").length;
  const total = agentList.length;

  // Fill in placeholder states for agents not yet seen from SSE
  const visibleAgents: Record<string, AgentState> = { ...agents };
  for (const a of agentList) {
    if (!visibleAgents[a]) {
      visibleAgents[a] = {
        task_id: "",
        agent: a,
        instruction: "",
        status: "waiting",
        currentAction: null,
        currentTool: null,
        reasoning: null,
        result: null,
        log: [],
      };
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white truncate max-w-2xl">
            {instruction || "Running goal…"}
          </h1>
          <span className={`text-xs font-mono px-2 py-0.5 rounded border flex-shrink-0 ${
            done ? "text-green-400 border-green-800 bg-green-950/30" :
            error ? "text-red-400 border-red-800 bg-red-950/30" :
            "text-yellow-400 border-yellow-800 bg-yellow-950/30"
          }`}>
            {done ? "done" : error ? "error" : connected ? "running" : "connecting…"}
          </span>
        </div>

        <p className="text-zinc-600 text-xs font-mono">{sessionId}</p>

        {total > 0 && (
          <div className="flex items-center gap-3">
            <div className="flex-1 h-1.5 rounded-full bg-zinc-800">
              <div
                className="h-1.5 rounded-full bg-violet-500 transition-all duration-700"
                style={{ width: `${(doneCount / total) * 100}%` }}
              />
            </div>
            <span className="text-zinc-400 text-sm flex-shrink-0">{doneCount}/{total} agents</span>
          </div>
        )}

        {!connected && !error && (
          <div className="flex items-center gap-2 text-zinc-500 text-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-pulse" />
            Connecting to agent stream…
          </div>
        )}

        {error && (
          <p className="text-red-400 text-sm bg-red-950/20 border border-red-800 rounded-lg px-4 py-2">{error}</p>
        )}
      </div>

      {total === 0 && connected && !error && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3 text-zinc-400 text-sm">
            <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
            Planner is breaking your goal into tasks… (takes ~30-60s for local model)
          </div>
          <div className="h-1 w-full rounded-full bg-zinc-800 overflow-hidden">
            <div className="h-1 bg-violet-500/50 rounded-full animate-pulse w-full" />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {agentList.map((agent) => (
          <AgentCard key={agent} state={visibleAgents[agent]} />
        ))}
      </div>
    </div>
  );
}
