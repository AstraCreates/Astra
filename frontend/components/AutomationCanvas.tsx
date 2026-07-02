"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  MarkerType,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, waitForAuthReady } from "@/lib/api";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type NodeType = "trigger" | "agent" | "prompt" | "action" | "delay" | "condition";

type NodeConfig = {
  agent_name?: string;
  instruction?: string;
  system_prompt?: string;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  windmill_flow_path?: string;
  seconds?: number;
  contains?: string;
};

type NodeStatus = "idle" | "running" | "done" | "error" | "skipped";

type AutomationNodeData = {
  label: string;
  nodeType: NodeType;
  config: NodeConfig;
  status?: NodeStatus;
  output?: string;
};

type AutomationNode = Node<AutomationNodeData>;

type AgentCatalogEntry = { id: string; name: string; description: string };

type NodeMeta = {
  icon: string;
  label: string;
  short: string;
  description: string;
  color: string;
  bg: string;
  border: string;
};

const NODE_META: Record<NodeType, NodeMeta> = {
  trigger: {
    icon: "▶", label: "Manual trigger", short: "Trigger",
    description: "Starts the flow when you click Run. Scheduled and webhook triggers are coming later.",
    color: "#5B8DEF", bg: "rgba(150,190,255,0.10)", border: "rgba(150,190,255,0.45)",
  },
  agent: {
    icon: "✺", label: "Run agent", short: "Agent",
    description: "Runs one of Astra's specialists with full tool access — web search, file generation, browsing. Use for research, building, or anything that needs real tools.",
    color: "#0F8A4B", bg: "rgba(124,255,198,0.10)", border: "rgba(124,255,198,0.45)",
  },
  prompt: {
    icon: "✎", label: "Quick reply", short: "Prompt",
    description: "A fast, tool-free LLM reply — good for rewriting, summarizing, or formatting text. It cannot browse, search, or use files. Use Agent for that.",
    color: "#B45309", bg: "rgba(255,180,50,0.10)", border: "rgba(255,180,50,0.45)",
  },
  action: {
    icon: "⌘", label: "HTTP request", short: "Action",
    description: "Calls an external URL (or an existing Windmill flow) and passes the response downstream.",
    color: "#7C3AED", bg: "rgba(200,150,255,0.10)", border: "rgba(200,150,255,0.45)",
  },
  delay: {
    icon: "◷", label: "Delay", short: "Delay",
    description: "Pauses for a fixed number of seconds before continuing.",
    color: "#0891B2", bg: "rgba(103,232,249,0.10)", border: "rgba(103,232,249,0.45)",
  },
  condition: {
    icon: "◈", label: "Condition", short: "Condition",
    description: "Checks the upstream output for text. If it doesn't match, this branch stops here — everything after it is skipped.",
    color: "#BE185D", bg: "rgba(251,182,206,0.14)", border: "rgba(251,182,206,0.5)",
  },
};

const NODE_ORDER: NodeType[] = ["trigger", "agent", "prompt", "action", "delay", "condition"];

const STATUS_COLORS: Record<string, string> = {
  running: "#3B82F6",
  done: "#16A34A",
  error: "#DC2626",
  skipped: "#94A3B8",
};

function CanvasNode({ data, selected }: NodeProps<AutomationNode>) {
  const meta = NODE_META[data.nodeType];
  const statusColor = data.status && data.status !== "idle" ? STATUS_COLORS[data.status] : undefined;
  const dimmed = data.status === "skipped";
  return (
    <div style={{
      minWidth: 210, maxWidth: 250, borderRadius: 14, padding: "12px 14px",
      background: "#fff", border: `1.5px solid ${selected ? meta.color : meta.border}`,
      boxShadow: selected ? `0 0 0 3px ${meta.bg}, 0 2px 8px rgba(0,0,0,0.06)` : "0 1px 4px rgba(0,0,0,0.07)",
      position: "relative", opacity: dimmed ? 0.5 : 1,
      transition: "box-shadow 0.15s ease, opacity 0.2s ease",
    }}>
      <Handle type="target" position={Position.Left} style={{ background: meta.color, width: 9, height: 9, border: "2px solid #fff" }} />
      <Handle type="source" position={Position.Right} style={{ background: meta.color, width: 9, height: 9, border: "2px solid #fff" }} />
      {statusColor && (
        <div style={{
          position: "absolute", top: -7, right: -7, width: 15, height: 15, borderRadius: "50%",
          background: statusColor, border: "2px solid #fff", boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          animation: data.status === "running" ? "astra-pulse 1s ease-in-out infinite" : undefined,
        }} />
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
        <span style={{
          width: 22, height: 22, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 12, background: meta.bg, color: meta.color, flexShrink: 0,
        }}>
          {meta.icon}
        </span>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: meta.color,
        }}>
          {meta.short}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#111", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {data.label}
      </div>
      {data.output && (
        <div style={{
          marginTop: 7, fontSize: 11, color: "#666", maxHeight: 44, overflow: "hidden",
          borderTop: "1px solid #eee", paddingTop: 6, lineHeight: 1.4,
        }}>
          {data.output.slice(0, 140)}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { trigger: CanvasNode, agent: CanvasNode, prompt: CanvasNode, action: CanvasNode, delay: CanvasNode, condition: CanvasNode };

let nextId = 1;
function genId() { return `node_${Date.now()}_${nextId++}`; }

function defaultConfigFor(nodeType: NodeType): NodeConfig {
  switch (nodeType) {
    case "trigger": return {};
    case "agent": return { agent_name: "research", instruction: "" };
    case "prompt": return { instruction: "" };
    case "action": return { method: "GET", url: "" };
    case "delay": return { seconds: 5 };
    case "condition": return { contains: "" };
  }
}

export default function AutomationCanvas({ flowId }: { flowId: string }) {
  const router = useRouter();
  const { userId } = useDevUser();
  const isNew = flowId === "new";

  const [flowName, setFlowName] = useState("Untitled automation");
  const [savedFlowId, setSavedFlowId] = useState<string>(isNew ? "" : flowId);
  const [nodes, setNodes] = useState<AutomationNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [agentCatalog, setAgentCatalog] = useState<AgentCatalogEntry[]>([]);
  const [status, setStatus] = useState<"loading" | "ready">(isNew ? "ready" : "loading");
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string>("");
  const pollRef = useRef<number | null>(null);

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) || null, [nodes, selectedNodeId]);

  useEffect(() => {
    waitForAuthReady().then(() =>
      apiFetch(`${BASE}/agents/catalog`).then((r) => (r.ok ? r.json() : { agents: [] }))
    ).then((data) => setAgentCatalog(data.agents || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (isNew || !userId || userId === "anon") return;
    let cancelled = false;
    waitForAuthReady()
      .then(() => apiFetch(`${BASE}/automations/flows/${flowId}?founder_id=${encodeURIComponent(userId)}`))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((flow) => {
        if (cancelled) return;
        setFlowName(flow.name || "Untitled automation");
        setSavedFlowId(flow.id);
        setNodes((flow.nodes || []).map((n: { id: string; type: NodeType; position?: { x: number; y: number }; config?: NodeConfig }) => ({
          id: n.id,
          type: n.type,
          position: n.position || { x: 0, y: 0 },
          data: { label: labelFor(n.type, n.config || {}), nodeType: n.type, config: n.config || {} },
        })));
        setEdges((flow.edges || []).map((e: { source: string; target: string }, i: number) => ({
          id: `e${i}_${e.source}_${e.target}`, source: e.source, target: e.target,
          type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed },
        })));
        setStatus("ready");
      })
      .catch(() => setStatus("ready"));
    return () => { cancelled = true; };
  }, [flowId, isNew, userId]);

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds) as AutomationNode[]), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((conn: Connection) => setEdges((eds) => addEdge({ ...conn, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } }, eds)), []);

  function addNode(nodeType: NodeType) {
    const id = genId();
    const config = defaultConfigFor(nodeType);
    const node: AutomationNode = {
      id,
      type: nodeType,
      position: { x: 100 + (nodes.length % 4) * 60, y: 100 + nodes.length * 70 },
      data: { label: labelFor(nodeType, config), nodeType, config },
    };
    setNodes((nds) => [...nds, node]);
    setSelectedNodeId(id);
  }

  function updateSelectedConfig(patch: Partial<NodeConfig>) {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.map((n) => {
      if (n.id !== selectedNodeId) return n;
      const config = { ...n.data.config, ...patch };
      return { ...n, data: { ...n.data, config, label: labelFor(n.data.nodeType, config) } };
    }));
  }

  function deleteSelected() {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) => eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId));
    setSelectedNodeId(null);
  }

  async function saveFlow(): Promise<string | null> {
    if (!userId || userId === "anon") return null;
    setSaving(true);
    try {
      const body = {
        founder_id: userId,
        name: flowName,
        flow_id: savedFlowId,
        nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, position: n.position, config: n.data.config })),
        edges: edges.map((e) => ({ source: e.source, target: e.target })),
      };
      const res = await apiFetch(`${BASE}/automations/flows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(String(res.status));
      const saved = await res.json();
      setSavedFlowId(saved.id);
      if (isNew) router.replace(`/automations/canvas/${saved.id}`);
      setSavedTick(true);
      window.setTimeout(() => setSavedTick(false), 1600);
      return saved.id as string;
    } catch {
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function runFlow() {
    if (!userId || userId === "anon") return;
    setRunError("");
    const id = savedFlowId || await saveFlow();
    if (!id) { setRunError("Could not save flow before running."); return; }
    setRunning(true);
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: "idle" as const, output: undefined } })));
    try {
      const res = await apiFetch(`${BASE}/automations/flows/${id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const { run_id } = await res.json();
      pollRun(run_id);
    } catch {
      setRunError("Failed to start run.");
      setRunning(false);
    }
  }

  function pollRun(runId: string) {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const res = await apiFetch(`${BASE}/automations/runs/${runId}?founder_id=${encodeURIComponent(userId)}`);
        if (!res.ok) return;
        const run = await res.json();
        const results = run.node_results || {};
        setNodes((nds) => nds.map((n) => {
          const r = results[n.id];
          if (!r) return n;
          return { ...n, data: { ...n.data, status: r.status, output: r.output?.summary || (r.output?.error ? `Error: ${r.output.error}` : "") } };
        }));
        if (run.status === "done" || run.status === "error") {
          if (pollRef.current) window.clearInterval(pollRef.current);
          setRunning(false);
          if (run.status === "error") setRunError(run.error || "Run failed.");
        }
      } catch {
        // transient — next tick retries
      }
    }, 1500);
  }

  if (status === "loading") {
    return <div style={{ padding: 40, color: "var(--fm)" }}>Loading…</div>;
  }

  const upstreamOfSelected = selectedNode ? edgesInto(selectedNode.id, edges) : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <style>{`
        @keyframes astra-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.3); opacity: 0.7; } }
        .astra-palette-btn:hover { filter: brightness(0.97); transform: translateY(-1px); }
      `}</style>
      <PageHeader
        title=""
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {runError && <span style={{ fontSize: 12, color: "#FF8080" }}>{runError}</span>}
            {savedTick && <span style={{ fontSize: 12, color: "#7CFFC6" }}>✓ Saved</span>}
            <HeaderSecondaryBtn label={saving ? "Saving…" : "Save"} onClick={() => { void saveFlow(); }} disabled={saving} />
            <HeaderPrimaryBtn label={running ? "Running…" : "▶ Run"} onClick={() => { void runFlow(); }} disabled={running || nodes.length === 0} />
          </div>
        }
      />
      <div style={{ padding: "10px 24px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10 }}>
        <button onClick={() => router.push("/automations")} className="m-tap" style={{ fontSize: 12, color: "var(--fm)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
          ← Automations
        </button>
        <input
          value={flowName}
          onChange={(e) => setFlowName(e.target.value)}
          style={{ fontSize: 15, fontWeight: 600, border: "none", outline: "none", background: "transparent", color: "var(--fg)", flex: 1, minWidth: 120 }}
        />
      </div>
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Node palette */}
        <div style={{ width: 232, borderRight: "1px solid var(--bd)", padding: 14, overflowY: "auto", flexShrink: 0, background: "var(--s2)" }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fm)", marginBottom: 10 }}>Add a block</div>
          {NODE_ORDER.map((t) => {
            const meta = NODE_META[t];
            return (
              <button
                key={t}
                onClick={() => addNode(t)}
                className="m-tap astra-palette-btn"
                style={{
                  width: "100%", textAlign: "left", padding: "10px 12px", marginBottom: 8, borderRadius: 10,
                  border: `1px solid ${meta.border}`, background: meta.bg, cursor: "pointer",
                  transition: "transform 0.12s ease, filter 0.12s ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 3 }}>
                  <span style={{ fontSize: 13 }}>{meta.icon}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: meta.color }}>{meta.label}</span>
                </div>
                <div style={{ fontSize: 10.5, color: "var(--fm)", lineHeight: 1.4 }}>{meta.description}</div>
              </button>
            );
          })}
        </div>

        {/* Canvas */}
        <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
          {nodes.length === 0 && (
            <div style={{
              position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
              flexDirection: "column", gap: 6, color: "var(--fm)", zIndex: 5, pointerEvents: "none",
            }}>
              <div style={{ fontSize: 28, opacity: 0.4 }}>⚡</div>
              <div style={{ fontSize: 13 }}>Add a block from the left to get started</div>
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            onNodeClick={(_, n) => setSelectedNodeId(n.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            defaultEdgeOptions={{ type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } }}
            fitView
          >
            <Background gap={18} color="var(--bd)" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable style={{ background: "var(--s2)" }} nodeColor={(n) => NODE_META[(n.data as AutomationNodeData).nodeType]?.color || "#888"} />
          </ReactFlow>
        </div>

        {/* Config panel */}
        {selectedNode && (
          <div style={{ width: 310, borderLeft: "1px solid var(--bd)", padding: 18, overflowY: "auto", flexShrink: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{
                  width: 24, height: 24, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, background: NODE_META[selectedNode.data.nodeType].bg, color: NODE_META[selectedNode.data.nodeType].color,
                }}>
                  {NODE_META[selectedNode.data.nodeType].icon}
                </span>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{NODE_META[selectedNode.data.nodeType].label}</div>
              </div>
              <button onClick={deleteSelected} className="m-tap" style={{ fontSize: 11, color: "#DC2626", background: "none", border: "none", cursor: "pointer" }}>Delete</button>
            </div>
            <div style={{ fontSize: 11.5, color: "var(--fm)", lineHeight: 1.5, marginBottom: 16 }}>
              {NODE_META[selectedNode.data.nodeType].description}
            </div>

            {selectedNode.data.nodeType === "agent" && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Agent</label>
                <select
                  value={selectedNode.data.config.agent_name || ""}
                  onChange={(e) => updateSelectedConfig({ agent_name: e.target.value })}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 4 }}
                >
                  {agentCatalog.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
                {agentCatalog.find((a) => a.id === selectedNode.data.config.agent_name) && (
                  <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.4 }}>
                    {agentCatalog.find((a) => a.id === selectedNode.data.config.agent_name)?.description}
                  </div>
                )}
              </>
            )}

            {(selectedNode.data.nodeType === "agent" || selectedNode.data.nodeType === "prompt") && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Instruction</label>
                <textarea
                  value={selectedNode.data.config.instruction || ""}
                  onChange={(e) => updateSelectedConfig({ instruction: e.target.value })}
                  rows={6}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
                  placeholder="What should this node do?"
                />
                {upstreamOfSelected.length > 0 && (
                  <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.5 }}>
                    Reference upstream output with: {upstreamOfSelected.map((id) => (
                      <code key={id} style={{ background: "var(--s2)", padding: "1px 5px", borderRadius: 4, marginRight: 4 }}>{`{{${id}.output}}`}</code>
                    ))}
                  </div>
                )}
              </>
            )}

            {selectedNode.data.nodeType === "action" && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Method</label>
                <select
                  value={selectedNode.data.config.method || "GET"}
                  onChange={(e) => updateSelectedConfig({ method: e.target.value })}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
                >
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>URL</label>
                <input
                  value={selectedNode.data.config.url || ""}
                  onChange={(e) => updateSelectedConfig({ url: e.target.value })}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 12, fontFamily: "var(--font-code)" }}
                  placeholder="https://api.example.com/..."
                />
                {upstreamOfSelected.length > 0 && (
                  <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 4, lineHeight: 1.5 }}>
                    Reference upstream output in the URL or body with: {upstreamOfSelected.map((id) => (
                      <code key={id} style={{ background: "var(--s2)", padding: "1px 5px", borderRadius: 4, marginRight: 4 }}>{`{{${id}.output}}`}</code>
                    ))}
                  </div>
                )}
              </>
            )}

            {selectedNode.data.nodeType === "delay" && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Wait (seconds)</label>
                <input
                  type="number" min={0} max={3600}
                  value={selectedNode.data.config.seconds ?? 5}
                  onChange={(e) => updateSelectedConfig({ seconds: Number(e.target.value) })}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 12 }}
                />
              </>
            )}

            {selectedNode.data.nodeType === "condition" && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Continue only if upstream output contains</label>
                <input
                  value={selectedNode.data.config.contains || ""}
                  onChange={(e) => updateSelectedConfig({ contains: e.target.value })}
                  style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 12 }}
                  placeholder="e.g. yes, approved, error"
                />
              </>
            )}

            {selectedNode.data.nodeType === "trigger" && (
              <div style={{ fontSize: 12, color: "var(--fm)" }}>No configuration needed — click Run above to start this flow.</div>
            )}

            {selectedNode.data.status && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--bd)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: STATUS_COLORS[selectedNode.data.status] || "var(--fm)" }} />
                  <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: "var(--fm)" }}>
                    {selectedNode.data.status}
                  </span>
                </div>
                {selectedNode.data.output && (
                  <div style={{ fontSize: 12, color: "var(--fg)", whiteSpace: "pre-wrap", background: "var(--s2)", borderRadius: 8, padding: 10, lineHeight: 1.5 }}>
                    {selectedNode.data.output}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function edgesInto(nodeId: string, edges: Edge[]): string[] {
  return edges.filter((e) => e.target === nodeId).map((e) => e.source);
}

function labelFor(nodeType: NodeType, config: NodeConfig): string {
  if (nodeType === "agent" && config.agent_name) return `Run ${config.agent_name}`;
  if (nodeType === "delay") return `Wait ${config.seconds ?? 5}s`;
  if (nodeType === "condition") return config.contains ? `If contains "${config.contains}"` : "Condition";
  if (nodeType === "action" && config.url) {
    try { return new URL(config.url).hostname; } catch { return NODE_META.action.label; }
  }
  return NODE_META[nodeType].label;
}
