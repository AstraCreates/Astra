"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { killSession, getSessionState, openEventStream, type StreamSubscription } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { extractFilePaths, PdfEmbed, EmailDeliverableButton } from "@/components/GoalWorkspace";

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
  founderId?: string;
}

let _idSeq = 0;
function mkId() { return ++_idSeq; }

function safeStr(v: unknown, limit = 400): string {
  if (typeof v === "string") return v.slice(0, limit);
  if (v == null) return "";
  try { return JSON.stringify(v).slice(0, limit); } catch { return ""; }
}

const LINE_COLOR: Record<LogLine["kind"], string> = {
  info:     "var(--blue)",
  think:    "var(--fm)",
  tool:     "#d97706",
  result:   "var(--fd)",
  done:     "var(--green)",
  error:    "var(--red)",
  artifact: "#7c3aed",
};

const LINE_PREFIX: Record<LogLine["kind"], string> = {
  info:     "·",
  think:    "···",
  tool:     "⚙",
  result:   "→",
  done:     "✓",
  error:    "✗",
  artifact: "◈",
};

export default function CustomAgentSessionView({
  sessionId, agentName, goal, initialStatus, founderId,
}: Props) {
  const router = useRouter();
  const [status, setStatus] = useState<Status>(initialStatus);
  const [log, setLog] = useState<LogLine[]>([]);
  const [killing, setKilling] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<StreamSubscription | null>(null);

  // Pull structured result once run finishes (for deliverables).
  useEffect(() => {
    if (status === "running") return;
    let cancelled = false;
    getSessionState(sessionId).then(state => {
      if (cancelled) return;
      const agents = state.agents ?? {};
      const customKey = Object.keys(agents).find(k => k.startsWith("custom_"));
      const agentState = (customKey ? agents[customKey] : Object.values(agents)[0]) as Record<string, unknown> | undefined;
      setResult((agentState?.result as Record<string, unknown>) ?? null);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId, status]);

  const deliverablePaths = useMemo(() => extractFilePaths(result ?? {}), [result]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log.length]);

  function push(kind: LogLine["kind"], text: string) {
    if (!text.trim()) return;
    setLog(prev => [...prev, { id: mkId(), kind, text }]);
  }

  useEffect(() => {
    if (initialStatus !== "running") return;

    // lastEventId=0 forces the backend's "replay everything since this id"
    // branch instead of its sparse "fresh connect" state-only replay (which
    // assumes a localStorage log cache this view doesn't have) — without it,
    // reloading mid-run wipes the visible log back to "waiting," looking like
    // the run restarted even though it never did.
    const es = openEventStream(`${API}/stream/${sessionId}`, { lastEventId: 0 });
    streamRef.current = es;

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

    return () => {
      streamRef.current?.close();
      streamRef.current = null;
    };
  }, [sessionId, initialStatus]);

  async function handleKill() {
    setKilling(true);
    await killSession(sessionId).catch(() => {});
    setStatus("done");
    setKilling(false);
  }

  const statusColor =
    status === "running" ? "var(--blue)"
    : status === "done" ? "var(--green)"
    : "var(--red)";

  const statusLabel =
    status === "running" ? "Running"
    : status === "done" ? "Done"
    : "Failed";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden", background: "var(--bg)" }}>

      {/* ── Topbar ── */}
      <div style={{
        height: 48, display: "flex", alignItems: "center", padding: "0 18px",
        gap: 12, borderBottom: "1px solid var(--bd)",
        background: "var(--surface)", flexShrink: 0,
      }}>
        <button
          onClick={() => router.push("/agents")}
          style={{
            display: "flex", alignItems: "center", gap: 5, background: "none",
            border: "none", cursor: "pointer", color: "var(--fm)", fontSize: 12,
            fontFamily: "var(--font-instrument), sans-serif", padding: "4px 8px",
            borderRadius: 6, transition: "color .12s, background .12s",
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--fg)"; (e.currentTarget as HTMLButtonElement).style.background = "var(--s3)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--fm)"; (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
        >
          ← Agents
        </button>

        <div style={{ width: 1, height: 20, background: "var(--bd)", flexShrink: 0 }} />

        {/* Status dot */}
        <div style={{
          width: 7, height: 7, borderRadius: "50%", background: statusColor, flexShrink: 0,
          boxShadow: status === "running" ? `0 0 0 3px color-mix(in srgb, ${statusColor} 20%, transparent)` : undefined,
        }} />

        {/* Agent name */}
        <div style={{
          fontSize: 13, fontWeight: 700, color: "var(--fg)",
          fontFamily: "var(--font-instrument), sans-serif",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          flex: 1,
        }}>
          {agentName || "Custom Agent"}
        </div>

        <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-code)", flexShrink: 0 }}>
          {statusLabel}
        </div>

        {status === "running" && (
          <button
            onClick={handleKill}
            disabled={killing}
            style={{
              fontSize: 11, fontWeight: 600, color: "var(--red)",
              background: "var(--rdim)", border: "1px solid var(--rb)",
              borderRadius: 6, padding: "4px 12px", cursor: "pointer",
              opacity: killing ? 0.5 : 1, transition: "opacity .15s",
              fontFamily: "var(--font-instrument), sans-serif",
            }}
          >
            {killing ? "Stopping…" : "Stop"}
          </button>
        )}
      </div>

      {/* ── Goal strip ── */}
      {goal && (
        <div style={{
          padding: "9px 18px", borderBottom: "1px solid var(--bd)",
          background: "var(--s2)", flexShrink: 0,
        }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--fm)", fontFamily: "var(--font-code)", marginBottom: 2 }}>
            Goal
          </div>
          <div style={{ fontSize: 12, color: "var(--fd)", lineHeight: 1.5, fontFamily: "var(--font-instrument), sans-serif" }}>
            {goal}
          </div>
        </div>
      )}

      {/* ── Deliverables (shown once done) ── */}
      {status !== "running" && (
        <div style={{
          padding: "14px 18px", borderBottom: "1px solid var(--bd)",
          background: "var(--surface)", flexShrink: 0,
        }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--fm)", fontFamily: "var(--font-code)", marginBottom: 10 }}>
            Deliverables{deliverablePaths.length > 0 ? ` · ${deliverablePaths.length}` : ""}
          </div>
          {deliverablePaths.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--fm)", fontFamily: "var(--font-instrument), sans-serif" }}>
              No files generated by this run.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {deliverablePaths.map(p => (
                <div key={p} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <PdfEmbed path={p} height={300} />
                  {founderId && <EmailDeliverableButton founderId={founderId} path={p} />}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Log feed ── */}
      <div style={{
        flex: 1, overflowY: "auto", padding: "16px 18px",
        display: "flex", flexDirection: "column", gap: 3,
        minHeight: 0,
      }}>
        {log.length === 0 && status === "running" && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            color: "var(--fm)", fontSize: 11,
            fontFamily: "var(--font-code)",
          }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)", animation: "sc-shimmer 1.5s ease-in-out infinite" }} />
            Waiting for agent output…
          </div>
        )}

        {log.length === 0 && status !== "running" && (
          <div style={{ fontSize: 12, color: "var(--fm)", fontFamily: "var(--font-instrument), sans-serif" }}>
            No log available for this run.
          </div>
        )}

        {log.map(line => (
          <div
            key={line.id}
            style={{
              display: "flex", gap: 10, alignItems: "flex-start",
              fontSize: 11.5, lineHeight: 1.6,
              fontFamily: "var(--font-code)",
              color: line.kind === "think" ? "var(--fm)" : undefined,
              fontStyle: line.kind === "think" ? "italic" : undefined,
            }}
          >
            <span style={{ color: LINE_COLOR[line.kind], flexShrink: 0, width: 14, textAlign: "right", opacity: 0.7, marginTop: 1 }}>
              {LINE_PREFIX[line.kind]}
            </span>
            <span style={{ color: LINE_COLOR[line.kind], wordBreak: "break-word", minWidth: 0 }}>
              {line.text}
            </span>
          </div>
        ))}

        {status === "running" && log.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 7, color: "var(--fm)", fontSize: 11, fontFamily: "var(--font-code)", marginTop: 4 }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--blue)", animation: "sc-shimmer 1.5s ease-in-out infinite" }} />
            Running…
          </div>
        )}

        {status === "done" && (
          <div style={{
            marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--bd)",
            display: "flex", alignItems: "center", gap: 16,
            fontFamily: "var(--font-instrument), sans-serif",
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--green)" }}>✓ Run completed</span>
            <button
              onClick={() => router.push("/agents")}
              style={{ fontSize: 12, color: "var(--blue)", background: "none", border: "none", cursor: "pointer", padding: 0, fontWeight: 600, fontFamily: "inherit" }}
            >
              Back to Agents →
            </button>
          </div>
        )}

        {status === "error" && (
          <div style={{
            marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--bd)",
            display: "flex", alignItems: "center", gap: 16,
            fontFamily: "var(--font-instrument), sans-serif",
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--red)" }}>✗ Run failed</span>
            <button
              onClick={() => router.push("/agents")}
              style={{ fontSize: 12, color: "var(--blue)", background: "none", border: "none", cursor: "pointer", padding: 0, fontWeight: 600, fontFamily: "inherit" }}
            >
              Back to Agents →
            </button>
          </div>
        )}

        <div ref={logEndRef} />
      </div>
    </div>
  );
}
