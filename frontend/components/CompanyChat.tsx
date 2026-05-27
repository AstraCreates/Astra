"use client";

import { useEffect, useRef, useState } from "react";
import LiquidGlass from "@/components/LiquidGlass";
import { AGENT_LABELS } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AGENT_ICONS: Record<string, string> = {
  research: "🔬", research_competitors: "🏆", research_execution: "📋",
  web: "🌐", marketing: "📢", technical: "⚙️",
  legal: "⚖️", ops: "🚀", sales: "🤝", design: "🎨",
};

const SUGGESTIONS = [
  "Update the landing page with a pricing section",
  "Write 5 LinkedIn posts for launch week",
  "Add a blog and write the first post",
  "Build an admin dashboard with analytics",
  "Draft investor outreach for 10 seed funds",
  "Add Stripe payments and upgrade flows",
  "Write Terms of Service and Privacy Policy",
  "Plan a 30-day go-to-market campaign",
];

interface AgentRun {
  agent: string;
  status: "running" | "done" | "error";
  summary: string;
}

interface Message {
  id: string;
  role: "user" | "agents";
  text: string;
  timestamp: number;
  sessionId?: string;
  runs?: AgentRun[];
  done?: boolean;
}

export default function CompanyChat({
  priorSessionId,
  founderId,
  company,
}: {
  priorSessionId: string;
  founderId: string;
  company: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function updateRun(msgId: string, agent: string, patch: Partial<AgentRun>) {
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      const runs = (m.runs ?? []).map(r => r.agent === agent ? { ...r, ...patch } : r);
      if (!runs.find(r => r.agent === agent)) runs.push({ agent, status: "running", summary: "", ...patch });
      return { ...m, runs };
    }));
  }

  function markDone(msgId: string) {
    setMessages(prev => prev.map(m => m.id === msgId ? { ...m, done: true } : m));
    setBusy(false);
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", text, timestamp: Date.now() };
    const agentMsg: Message = { id: crypto.randomUUID(), role: "agents", text: "", timestamp: Date.now(), runs: [], done: false };
    setMessages(prev => [...prev, userMsg, agentMsg]);
    setInput("");
    setBusy(true);

    try {
      const res = await fetch(`${BASE}/goal/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: founderId, prior_session_id: priorSessionId, instruction: text }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { session_id } = await res.json();

      if (esRef.current) esRef.current.close();
      const es = new EventSource(`${BASE}/stream/${session_id}`);
      esRef.current = es;

      es.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.type === "agent_start") {
          updateRun(agentMsg.id, ev.agent, { status: "running", summary: ev.instruction?.slice(0, 120) ?? "" });
        } else if (ev.type === "agent_done" || ev.type === "goal_done") {
          if (ev.agent) updateRun(agentMsg.id, ev.agent, { status: "done" });
          if (ev.type === "goal_done") { markDone(agentMsg.id); es.close(); }
        } else if (ev.type === "agent_error") {
          updateRun(agentMsg.id, ev.agent, { status: "error", summary: ev.error ?? "" });
        }
      };
      es.onerror = () => { markDone(agentMsg.id); es.close(); };
    } catch (err) {
      setMessages(prev => prev.map(m => m.id === agentMsg.id
        ? { ...m, done: true, runs: [{ agent: "error", status: "error", summary: String(err) }] }
        : m
      ));
      setBusy(false);
    }
  }

  return (
    <LiquidGlass contentStyle={{ padding: "0", display: "flex", flexDirection: "column", height: 560 }}>
      {/* Header */}
      <div style={{ padding: "18px 24px 14px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 16 }}>💬</span>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{company || "Your company"}</div>
          <div style={{ fontSize: 11, color: "var(--text-2)" }}>Tell the team what to do next</div>
        </div>
      </div>

      {/* Thread */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        {messages.length === 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 8 }}>
            <p style={{ fontSize: 13, color: "var(--text-2)", margin: 0 }}>
              Your agents know everything they built. Tell them what to do next.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => send(s)} disabled={busy}
                  style={{ fontSize: 12, padding: "6px 14px", borderRadius: 999, border: "1px solid var(--line)", background: "transparent", cursor: "pointer", color: "var(--text-2)", textAlign: "left" }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 4 }}>
            {msg.role === "user" ? (
              <div style={{
                maxWidth: "72%", padding: "10px 16px", borderRadius: "18px 18px 4px 18px",
                background: "var(--action)", color: "var(--action-text)", fontSize: 14, lineHeight: 1.5,
              }}>
                {msg.text}
              </div>
            ) : (
              <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 8 }}>
                {(msg.runs ?? []).map(run => (
                  <div key={run.agent} style={{
                    display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 14px",
                    borderRadius: 12, border: "1px solid var(--line)",
                    background: run.status === "done" ? "rgba(61,158,95,0.05)" : run.status === "error" ? "rgba(192,57,43,0.05)" : "rgba(37,99,235,0.05)",
                  }}>
                    <span style={{ fontSize: 16, lineHeight: 1.2, flexShrink: 0 }}>{AGENT_ICONS[run.agent] ?? "⚙️"}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>
                          {AGENT_LABELS[run.agent] ?? run.agent}
                        </span>
                        <span style={{
                          fontSize: 10, padding: "1px 8px", borderRadius: 999,
                          color: run.status === "done" ? "#3D9E5F" : run.status === "error" ? "#C0392B" : "#2563EB",
                          background: run.status === "done" ? "rgba(61,158,95,0.12)" : run.status === "error" ? "rgba(192,57,43,0.12)" : "rgba(37,99,235,0.12)",
                        }}>
                          {run.status === "running" ? "working…" : run.status}
                        </span>
                      </div>
                      {run.summary && <p style={{ fontSize: 12, color: "var(--text-2)", margin: "3px 0 0", lineHeight: 1.5 }}>{run.summary}</p>}
                    </div>
                  </div>
                ))}
                {!msg.done && (msg.runs ?? []).length === 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
                    Dispatching agents…
                  </div>
                )}
                {msg.done && (msg.runs ?? []).length > 0 && (
                  <p style={{ fontSize: 11, color: "var(--text-2)", margin: 0 }}>
                    ✓ {(msg.runs ?? []).filter(r => r.status === "done").length} agent{(msg.runs ?? []).filter(r => r.status === "done").length !== 1 ? "s" : ""} completed
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "14px 20px", borderTop: "1px solid var(--line)" }}>
        <form onSubmit={e => { e.preventDefault(); send(input); }} style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder="Update the landing page, write blog posts, add payments…"
            rows={2}
            className="site-textarea"
            style={{ flex: 1, padding: "10px 14px", fontSize: 14, lineHeight: 1.5, resize: "none" }}
            disabled={busy}
          />
          <button type="submit" disabled={busy || !input.trim()} className="site-btn site-btn-primary" style={{ padding: "0 20px", height: 42, flexShrink: 0 }}>
            {busy ? "…" : "→"}
          </button>
        </form>
      </div>
    </LiquidGlass>
  );
}
