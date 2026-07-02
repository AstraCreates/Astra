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

type NodeType = "trigger" | "agent" | "prompt" | "action";

type NodeConfig = {
  agent_name?: string;
  instruction?: string;
  system_prompt?: string;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  windmill_flow_path?: string;
};

type AutomationNodeData = {
  label: string;
  nodeType: NodeType;
  config: NodeConfig;
  status?: "idle" | "running" | "done" | "error";
  output?: string;
};

type AutomationNode = Node<AutomationNodeData>;

type AgentCatalogEntry = { id: string; name: string; description: string };

const NODE_COLORS: Record<NodeType, { bg: string; border: string; label: string }> = {
  trigger: { bg: "rgba(150,190,255,0.10)", border: "rgba(150,190,255,0.4)", label: "#5B8DEF" },
  agent: { bg: "rgba(124,255,198,0.10)", border: "rgba(124,255,198,0.4)", label: "#0F8A4B" },
  prompt: { bg: "rgba(255,180,50,0.10)", border: "rgba(255,180,50,0.4)", label: "#B45309" },
  action: { bg: "rgba(200,150,255,0.10)", border: "rgba(200,150,255,0.4)", label: "#7C3AED" },
};

const STATUS_COLORS: Record<string, string> = {
  running: "#3B82F6",
  done: "#16A34A",
  error: "#DC2626",
};

function CanvasNode({ data, selected }: NodeProps<AutomationNode>) {
  const colors = NODE_COLORS[data.nodeType];
  const statusColor = data.status ? STATUS_COLORS[data.status] : undefined;
  return (
    <div style={{
      minWidth: 200, maxWidth: 240, borderRadius: 12, padding: "10px 14px",
      background: "#fff", border: `1.5px solid ${selected ? colors.label : colors.border}`,
      boxShadow: selected ? `0 0 0 3px ${colors.bg}` : "0 1px 3px rgba(0,0,0,0.08)",
      position: "relative",
    }}>
      <Handle type="target" position={Position.Left} style={{ background: colors.label, width: 8, height: 8 }} />
      <Handle type="source" position={Position.Right} style={{ background: colors.label, width: 8, height: 8 }} />
      {statusColor && (
        <div style={{
          position: "absolute", top: -6, right: -6, width: 14, height: 14, borderRadius: "50%",
          background: statusColor, border: "2px solid #fff",
          animation: data.status === "running" ? "pulse 1s ease-in-out infinite" : undefined,
        }} />
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase",
          color: colors.label, background: colors.bg, padding: "2px 6px", borderRadius: 4,
        }}>
          {data.nodeType}
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#111", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {data.label}
      </div>
      {data.output && (
        <div style={{ marginTop: 6, fontSize: 11, color: "#666", maxHeight: 40, overflow: "hidden", textOverflow: "ellipsis" }}>
          {data.output.slice(0, 120)}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { trigger: CanvasNode, agent: CanvasNode, prompt: CanvasNode, action: CanvasNode };

let nextId = 1;
function genId() { return `node_${Date.now()}_${nextId++}`; }

function defaultConfigFor(nodeType: NodeType): NodeConfig {
  switch (nodeType) {
    case "trigger": return {};
    case "agent": return { agent_name: "research", instruction: "" };
    case "prompt": return { instruction: "" };
    case "action": return { method: "GET", url: "" };
  }
}

function defaultLabelFor(nodeType: NodeType): string {
  switch (nodeType) {
    case "trigger": return "Manual trigger";
    case "agent": return "Run agent";
    case "prompt": return "Prompt";
    case "action": return "HTTP request";
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
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string>("");
  const pollRef = useRef<number | null>(null);

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) || null, [nodes, selectedNodeId]);

  // Load agent catalog for the node palette + agent-node config dropdown.
  useEffect(() => {
    waitForAuthReady().then(() =>
      apiFetch(`${BASE}/agents/catalog`).then((r) => (r.ok ? r.json() : { agents: [] }))
    ).then((data) => setAgentCatalog(data.agents || [])).catch(() => {});
  }, []);

  // Load existing flow, if editing one.
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
          data: { label: (n.config?.agent_name ? `Run ${n.config.agent_name}` : defaultLabelFor(n.type)), nodeType: n.type, config: n.config || {} },
        })));
        setEdges((flow.edges || []).map((e: { source: string; target: string }, i: number) => ({ id: `e${i}_${e.source}_${e.target}`, source: e.source, target: e.target })));
        setStatus("ready");
      })
      .catch(() => setStatus("ready"));
    return () => { cancelled = true; };
  }, [flowId, isNew, userId]);

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds) as AutomationNode[]), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((conn: Connection) => setEdges((eds) => addEdge(conn, eds)), []);

  function addNode(nodeType: NodeType) {
    const id = genId();
    const node: AutomationNode = {
      id,
      type: nodeType,
      position: { x: 80 + nodes.length * 40, y: 80 + (nodes.length % 5) * 90 },
      data: { label: defaultLabelFor(nodeType), nodeType, config: defaultConfigFor(nodeType) },
    };
    setNodes((nds) => [...nds, node]);
    setSelectedNodeId(id);
  }

  function updateSelectedConfig(patch: Partial<NodeConfig>) {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.map((n) => {
      if (n.id !== selectedNodeId) return n;
      const config = { ...n.data.config, ...patch };
      const label = n.data.nodeType === "agent" && config.agent_name ? `Run ${config.agent_name}` : n.data.label;
      return { ...n, data: { ...n.data, config, label } };
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
      pollRun(id, run_id);
    } catch {
      setRunError("Failed to start run.");
      setRunning(false);
    }
  }

  function pollRun(flowIdArg: string, runId: string) {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PageHeader
        title=""
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {runError && <span style={{ fontSize: 12, color: "#FF8080" }}>{runError}</span>}
            <HeaderSecondaryBtn label={saving ? "Saving…" : "Save"} onClick={() => { void saveFlow(); }} disabled={saving} />
            <HeaderPrimaryBtn label={running ? "Running…" : "Run"} onClick={() => { void runFlow(); }} disabled={running || nodes.length === 0} />
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
        <div style={{ width: 200, borderRight: "1px solid var(--bd)", padding: 14, overflowY: "auto", flexShrink: 0 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fm)", marginBottom: 10 }}>Add node</div>
          {(["trigger", "agent", "prompt", "action"] as NodeType[]).map((t) => (
            <button
              key={t}
              onClick={() => addNode(t)}
              className="m-tap"
              style={{
                width: "100%", textAlign: "left", padding: "8px 10px", marginBottom: 6, borderRadius: 8,
                border: `1px solid ${NODE_COLORS[t].border}`, background: NODE_COLORS[t].bg,
                fontSize: 12, fontWeight: 600, color: NODE_COLORS[t].label, cursor: "pointer",
              }}
            >
              + {defaultLabelFor(t)}
            </button>
          ))}
        </div>

        {/* Canvas */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            onNodeClick={(_, n) => setSelectedNodeId(n.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            fitView
          >
            <Background gap={16} />
            <Controls />
            <MiniMap pannable zoomable style={{ background: "var(--s2)" }} />
          </ReactFlow>
        </div>

        {/* Config panel */}
        {selectedNode && (
          <div style={{ width: 300, borderLeft: "1px solid var(--bd)", padding: 16, overflowY: "auto", flexShrink: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--fg)" }}>{selectedNode.data.nodeType} node</div>
              <button onClick={deleteSelected} className="m-tap" style={{ fontSize: 11, color: "#DC2626", background: "none", border: "none", cursor: "pointer" }}>Delete</button>
            </div>

            {selectedNode.data.nodeType === "agent" && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Agent</label>
                <select
                  value={selectedNode.data.config.agent_name || ""}
                  onChange={(e) => updateSelectedConfig({ agent_name: e.target.value })}
                  style={{ width: "100%", padding: "6px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 12 }}
                >
                  {agentCatalog.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </>
            )}

            {(selectedNode.data.nodeType === "agent" || selectedNode.data.nodeType === "prompt") && (
              <>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>
                  Instruction {edgesInto(selectedNode.id, edges).length > 0 && <span style={{ opacity: 0.6 }}>— use {"{{"}<i>node_id</i>{".output}}"}</span>}
                </label>
                <textarea
                  value={selectedNode.data.config.instruction || ""}
                  onChange={(e) => updateSelectedConfig({ instruction: e.target.value })}
                  rows={6}
                  style={{ width: "100%", padding: "6px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8 }}
                  placeholder={edgesInto(selectedNode.id, edges).map((id) => `{{${id}.output}}`).join(" ") || "What should this node do?"}
                />
                {edgesInto(selectedNode.id, edges).length > 0 && (
                  <div style={{ fontSize: 10, color: "var(--fm)", marginBottom: 12 }}>
                    Upstream: {edgesInto(selectedNode.id, edges).map((id) => `{{${id}.output}}`).join(", ")}
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
                  style={{ width: "100%", padding: "6px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
                >
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>URL</label>
                <input
                  value={selectedNode.data.config.url || ""}
                  onChange={(e) => updateSelectedConfig({ url: e.target.value })}
                  style={{ width: "100%", padding: "6px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 12 }}
                  placeholder="https://api.example.com/..."
                />
              </>
            )}

            {selectedNode.data.nodeType === "trigger" && (
              <div style={{ fontSize: 12, color: "var(--fm)" }}>Manual trigger — click Run to start this flow. Scheduled/webhook triggers are coming later.</div>
            )}

            {selectedNode.data.status && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--bd)" }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: "var(--fm)", marginBottom: 6 }}>
                  {selectedNode.data.status}
                </div>
                {selectedNode.data.output && (
                  <div style={{ fontSize: 12, color: "var(--fg)", whiteSpace: "pre-wrap", background: "var(--s2)", borderRadius: 6, padding: 8 }}>
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
