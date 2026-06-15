"use client";

/**
 * Focused session view for custom agent runs (stack_id: "custom").
 * Shows a live log feed, agent name, status, and kill control.
 * Much simpler than the full company SessionView.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, killSession } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Status = "running" | "done" | "error";

type LogLine = {
  id: number;
  kind: "info" | "think" | "tool" | "result" | "done" | "error" | "artifact";
  text: string;
};

interface Props {
  sessionId: string;
  agentName: string;
  goal: string;
  initialStatus: Status;
}

let _idSeq = 0;
function mkId() { return ++_idSeq; }

function safeStr(v: unknown, limit = 400): string {
  if (typeof v === "string") return v.slice(0, limit);
  if (v == null) return "";
  try { return JSON.stringify(v).slice(0, limit); } catch { return ""; }
}

export default function CustomAgentSessionView({ sessionId, agentName, goal, initialStatus }: Props) {
  const router = useRouter();
  const [status, setStatus] = useState<Status>(initialStatus);
  const [log, setLog] = useState<LogLine[]>([]);
  const [killing, setKilling] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll as log grows
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log.length]);

  function push(kind: LogLine["kind"], text: string) {
    if (!text.trim()) return;
    setLog(prev => [...prev, { id: mkId(), kind, text }]);
  }

  useEffect(() => {
    // Don't open SSE for sessions that already finished before this mount.
    if (initialStatus !== "running") return;

    const es = new EventSource(`${API}/stream/${sessionId}`);

    es.onmessage = (e) => {
      let ev: Record<string, unknown>;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.type === "ping") return;

      switch (ev.type) {
        case "goal_start":
          push("info", "Agent started");
          break;

        case "agent_start":
          push("info", safeStr(ev.instruction || "Running…"));
          break;

        case "agent_thinking":
        case "reasoning":
          push("think", safeStr(ev.text || ev.reasoning || ev.content));
          break;

        case "agent_tool_call":
        case "agent_action":
        case "tool_use": {
          const name = safeStr(ev.tool || ev.action || ev.function || ev.name || "tool");
          const args = ev.args || ev.input || ev.parameters || {};
          const argsStr = (typeof args === "string" ? args : JSON.stringify(args)).slice(0, 200);
          push("tool", `${name}(${argsStr})`);
          break;
        }

        case "agent_action_result":
        case "tool_result":
          push("result", safeStr(ev.result || ev.output || ev.content));
          break;

        case "agent_done": {
          const r = ev.result as Record<string, unknown> | null;
          const summary = r
            ? safeStr(r.summary || r.output_summary || r.headline || r.tldr || r.text || r.formatted_text)
            : "";
          push("done", summary || "Agent finished");
          break;
        }

        case "agent_error":
          push("error", safeStr(ev.error || ev.message || "Error"));
          break;

        case "stack_artifact":
        case "artifact": {
          const art = (ev.artifact || ev) as Record<string, unknown>;
          if (art.title) push("artifact", `Created: ${art.title}`);
          break;
        }

        case "goal_done":
          push("done", "Run complete");
          setStatus("done");
          es.close();
          break;

        case "goal_error":
          push("error", safeStr(ev.error || "Run failed"));
          setStatus("error");
          es.close();
          break;
      }
    };

    es.onerror = () => {
      // Connection closes when run ends — not an error we surface.
    };

    return () => { es.close(); };
  }, [sessionId, initialStatus]);

  async function handleKill() {
    setKilling(true);
    await killSession(sessionId).catch(() => {});
    setStatus("done");
    setKilling(false);
  }

  const statusLabel =
    status === "running" ? "Running…"
    : status === "done" ? "Completed"
    : "Failed";

  const statusDot =
    status === "running" ? "bg-blue-500 animate-pulse"
    : status === "done" ? "bg-green-500"
    : "bg-red-500";

  return (
    <div className="h-full flex flex-col bg-white">
      <PageHeader
        title={agentName || "Custom Agent"}
        subtitle={goal || ""}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => router.push("/agents")}
              className="text-xs font-medium text-white/80 hover:text-white px-3 py-1.5 rounded-lg hover:bg-white/10 transition-colors"
            >
              ← Agents
            </button>
            {status === "running" && (
              <button
                onClick={handleKill}
                disabled={killing}
                className="text-xs font-medium bg-white text-[#001AFF] px-3 py-1.5 rounded-lg hover:bg-blue-50 disabled:opacity-50 transition-colors"
              >
                {killing ? "Stopping…" : "Stop"}
              </button>
            )}
          </div>
        }
      />

      {/* Status bar */}
      <div className="flex items-center gap-2 px-6 py-2.5 border-b border-gray-100 bg-gray-50 text-xs text-gray-500 shrink-0">
        <div className={`w-2 h-2 rounded-full ${statusDot}`} />
        {statusLabel}
        <span className="mx-2 text-gray-300">·</span>
        <span className="font-mono text-[10px] text-gray-400 truncate">{sessionId}</span>
      </div>

      {/* Log feed */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-1.5 font-mono text-[12px]">
        {log.length === 0 && status === "running" && (
          <div className="text-gray-400 flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            Waiting for agent output…
          </div>
        )}

        {log.length === 0 && status !== "running" && (
          <div className="text-gray-400 text-sm font-sans">No log available for this run.</div>
        )}

        {log.map((line) => (
          <LogRow key={line.id} line={line} />
        ))}

        {status === "running" && log.length > 0 && (
          <div className="flex items-center gap-1.5 text-gray-400 pt-1">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
            <span>Running…</span>
          </div>
        )}

        {status === "done" && (
          <div className="mt-4 pt-4 border-t border-gray-100 font-sans">
            <span className="text-green-600 font-medium text-sm">✓ Run completed.</span>
            <button
              onClick={() => router.push("/agents")}
              className="ml-4 text-sm text-blue-600 hover:underline"
            >
              Back to Custom Agents →
            </button>
          </div>
        )}

        {status === "error" && (
          <div className="mt-4 pt-4 border-t border-gray-100 font-sans">
            <span className="text-red-600 font-medium text-sm">✗ Run failed.</span>
            <button
              onClick={() => router.push("/agents")}
              className="ml-4 text-sm text-blue-600 hover:underline"
            >
              Back to Custom Agents →
            </button>
          </div>
        )}

        <div ref={logEndRef} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Log row
// ---------------------------------------------------------------------------

const ROW_STYLES: Record<LogLine["kind"], { color: string; prefix: string }> = {
  info:     { color: "text-blue-500",   prefix: "·" },
  think:    { color: "text-gray-400 italic", prefix: "···" },
  tool:     { color: "text-amber-700",  prefix: "⚙" },
  result:   { color: "text-gray-600",   prefix: "→" },
  done:     { color: "text-green-600",  prefix: "✓" },
  error:    { color: "text-red-600",    prefix: "✗" },
  artifact: { color: "text-purple-600", prefix: "📄" },
};

function LogRow({ line }: { line: LogLine }) {
  const { color, prefix } = ROW_STYLES[line.kind];
  return (
    <div className={`${color} leading-relaxed flex gap-2`}>
      <span className="shrink-0 w-5 text-right opacity-60">{prefix}</span>
      <span className="break-words min-w-0">{line.text}</span>
    </div>
  );
}
