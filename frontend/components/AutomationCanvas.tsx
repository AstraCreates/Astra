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
import { useIsMobile } from "@/lib/use-is-mobile";
import { apiFetch, waitForAuthReady } from "@/lib/api";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type NodeType =
  | "trigger"
  | "agent"
  | "prompt"
  | "action"
  | "delay"
  | "condition"
  | "slack"
  | "email"
  | "gmail"
  | "slack_bot"
  | "github_issue"
  | "github_pr"
  | "linear_issue"
  | "notion_page"
  | "stripe_payment_link";

type NodeConfig = {
  agent_name?: string;
  instruction?: string;
  system_prompt?: string;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  // Record shape for action-node JSON bodies, plain string for the email node's body text.
  body?: Record<string, unknown> | string;
  windmill_flow_path?: string;
  seconds?: number;
  contains?: string;
  webhook_url?: string;
  message?: string;
  to?: string;
  subject?: string;
  from?: string;
  repo?: string;
  owner?: string;
  title?: string;
  description?: string;
  channel?: string;
  head?: string;
  base?: string;
  parent_id?: string;
  amount?: number;
  currency?: string;
  interval?: string;
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
  group: "logic" | "integration";
};

const NODE_META: Record<NodeType, NodeMeta> = {
  trigger: {
    icon: "▶", label: "Manual trigger", short: "Trigger",
    description: "Starts the flow when you click Run. Scheduled and webhook triggers are coming later.",
    color: "#5B8DEF", bg: "rgba(150,190,255,0.10)", border: "rgba(150,190,255,0.45)", group: "logic",
  },
  agent: {
    icon: "✺", label: "Run agent", short: "Agent",
    description: "Runs one of Astra's specialists with full tool access — web search, file generation, browsing. Use for research, building, or anything that needs real tools.",
    color: "#0F8A4B", bg: "rgba(124,255,198,0.10)", border: "rgba(124,255,198,0.45)", group: "logic",
  },
  prompt: {
    icon: "✎", label: "Quick reply", short: "Prompt",
    description: "A fast, tool-free LLM reply — good for rewriting, summarizing, or formatting text. It cannot browse, search, or use files. Use Agent for that.",
    color: "#B45309", bg: "rgba(255,180,50,0.10)", border: "rgba(255,180,50,0.45)", group: "logic",
  },
  action: {
    icon: "⌘", label: "HTTP request", short: "Action",
    description: "Calls any external URL (or an existing Windmill flow) and passes the response downstream.",
    color: "#7C3AED", bg: "rgba(200,150,255,0.10)", border: "rgba(200,150,255,0.45)", group: "logic",
  },
  delay: {
    icon: "◷", label: "Delay", short: "Delay",
    description: "Pauses for a fixed number of seconds before continuing.",
    color: "#0891B2", bg: "rgba(103,232,249,0.10)", border: "rgba(103,232,249,0.45)", group: "logic",
  },
  condition: {
    icon: "◈", label: "Condition", short: "Condition",
    description: "Checks the upstream output for text. If it doesn't match, this branch stops here — everything after it is skipped.",
    color: "#BE185D", bg: "rgba(251,182,206,0.14)", border: "rgba(251,182,206,0.5)", group: "logic",
  },
  slack: {
    icon: "#", label: "Slack message", short: "Slack",
    description: "Posts to a Slack incoming webhook — paste the webhook URL Slack gives you, no login needed.",
    color: "#611F69", bg: "rgba(97,31,105,0.08)", border: "rgba(97,31,105,0.35)", group: "integration",
  },
  email: {
    icon: "✉", label: "Send email", short: "Email",
    description: "Sends via your own connected SendGrid account (Integrations page) — never a shared key.",
    color: "#1D4ED8", bg: "rgba(29,78,216,0.08)", border: "rgba(29,78,216,0.35)", group: "integration",
  },
  gmail: {
    icon: "✉", label: "Gmail send", short: "Gmail",
    description: "Sends from the founder's connected Gmail account using Astra's native OAuth connection.",
    color: "#EA4335", bg: "rgba(234,67,53,0.08)", border: "rgba(234,67,53,0.28)", group: "integration",
  },
  slack_bot: {
    icon: "#", label: "Slack bot post", short: "Slack",
    description: "Posts to a connected Slack workspace using Astra's stored bot token.",
    color: "#611F69", bg: "rgba(97,31,105,0.08)", border: "rgba(97,31,105,0.35)", group: "integration",
  },
  github_issue: {
    icon: "●", label: "GitHub issue", short: "GitHub",
    description: "Creates a GitHub issue in a connected repository using the founder's GitHub token.",
    color: "#111827", bg: "rgba(17,24,39,0.08)", border: "rgba(17,24,39,0.18)", group: "integration",
  },
  github_pr: {
    icon: "⇄", label: "GitHub PR", short: "GitHub",
    description: "Opens a pull request in a connected repository using the founder's GitHub token.",
    color: "#111827", bg: "rgba(17,24,39,0.08)", border: "rgba(17,24,39,0.18)", group: "integration",
  },
  linear_issue: {
    icon: "◈", label: "Linear issue", short: "Linear",
    description: "Creates a Linear issue in the founder's connected workspace.",
    color: "#5E6AD2", bg: "rgba(94,106,210,0.08)", border: "rgba(94,106,210,0.24)", group: "integration",
  },
  notion_page: {
    icon: "▷", label: "Notion page", short: "Notion",
    description: "Creates a Notion page in the connected workspace or logs the intent locally if Notion is not connected yet.",
    color: "#111111", bg: "rgba(17,17,17,0.06)", border: "rgba(17,17,17,0.18)", group: "integration",
  },
  stripe_payment_link: {
    icon: "$", label: "Stripe payment link", short: "Stripe",
    description: "Creates a Stripe product, price, and payment link using the founder's connected Stripe account.",
    color: "#635BFF", bg: "rgba(99,91,255,0.08)", border: "rgba(99,91,255,0.24)", group: "integration",
  },
};

const NODE_ORDER: NodeType[] = [
  "trigger",
  "agent",
  "prompt",
  "action",
  "delay",
  "condition",
  "slack",
  "email",
  "gmail",
  "slack_bot",
  "github_issue",
  "github_pr",
  "linear_issue",
  "notion_page",
  "stripe_payment_link",
];

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
      minWidth: 155, maxWidth: 185, borderRadius: 10, padding: "8px 10px",
      background: "var(--surface)", border: `1.5px solid ${selected ? meta.color : meta.border}`,
      boxShadow: selected ? `0 0 0 3px ${meta.bg}, 0 2px 8px rgba(0,0,0,0.06)` : "0 1px 4px rgba(0,0,0,0.07)",
      position: "relative", opacity: dimmed ? 0.5 : 1,
      transition: "box-shadow 0.15s ease, opacity 0.2s ease",
    }}>
      <Handle type="target" position={Position.Left} style={{ background: meta.color, width: 7, height: 7, border: "2px solid var(--surface)" }} />
      <Handle type="source" position={Position.Right} style={{ background: meta.color, width: 7, height: 7, border: "2px solid var(--surface)" }} />
      {statusColor && (
        <div style={{
          position: "absolute", top: -5, right: -5, width: 12, height: 12, borderRadius: "50%",
          background: statusColor, border: "2px solid var(--surface)", boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          animation: data.status === "running" ? "astra-pulse 1s ease-in-out infinite" : undefined,
        }} />
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{
          width: 18, height: 18, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, background: meta.bg, color: meta.color, flexShrink: 0,
        }}>
          {meta.icon}
        </span>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: meta.color,
        }}>
          {meta.short}
        </span>
      </div>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {data.label}
      </div>
      {data.output && (
        <div style={{
          marginTop: 5, fontSize: 10, color: "var(--fm)", maxHeight: 36, overflow: "hidden",
          borderTop: "1px solid var(--bd)", paddingTop: 5, lineHeight: 1.4,
        }}>
          {data.output.slice(0, 120)}
        </div>
      )}
    </div>
  );
}

const nodeTypes = Object.fromEntries(NODE_ORDER.map((t) => [t, CanvasNode]));

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
    case "slack": return { webhook_url: "", message: "" };
    case "email": return { to: "", subject: "", body: "" };
    case "gmail": return { to: "", subject: "", body: "" };
    case "slack_bot": return { channel: "", message: "" };
    case "github_issue": return { repo: "", owner: "", title: "", body: "" };
    case "github_pr": return { repo: "", owner: "", title: "", body: "", head: "", base: "main" };
    case "linear_issue": return { title: "", description: "" };
    case "notion_page": return { title: "", body: "", parent_id: "" };
    case "stripe_payment_link": return { title: "", description: "", amount: 99, currency: "usd", interval: "one_time" };
  }
}

export default function AutomationCanvas({ flowId }: { flowId: string }) {
  const router = useRouter();
  const { userId } = useDevUser();
  const isMobile = useIsMobile();
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
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
      position: isMobile
        ? { x: 40, y: 40 + nodes.length * 90 }
        : { x: 100 + (nodes.length % 4) * 60, y: 100 + nodes.length * 70 },
      data: { label: labelFor(nodeType, config), nodeType, config },
    };
    setNodes((nds) => [...nds, node]);
    setSelectedNodeId(id);
    setPaletteOpen(false);
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

  async function buildFromPrompt() {
    if (!userId || userId === "anon" || !draftPrompt.trim()) return;
    setDrafting(true);
    setRunError("");
    try {
      const res = await apiFetch(`${BASE}/automations/flows/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId, prompt: draftPrompt }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const draft = await res.json();
      setFlowName(draft.name || "Draft automation");
      setSavedFlowId("");
      setNodes((draft.nodes || []).map((n: { id: string; type: NodeType; position?: { x: number; y: number }; config?: NodeConfig }) => ({
        id: n.id,
        type: n.type,
        position: n.position || { x: 0, y: 0 },
        data: { label: labelFor(n.type, n.config || {}), nodeType: n.type, config: n.config || {} },
      })));
      setEdges((draft.edges || []).map((e: { source: string; target: string }, i: number) => ({
        id: `d${i}_${e.source}_${e.target}`, source: e.source, target: e.target,
        type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed },
      })));
      setSelectedNodeId(null);
      setDraftOpen(false);
    } catch {
      setRunError("Could not draft automation from that description.");
    } finally {
      setDrafting(false);
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

  const paletteBody = (
    <>
      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fm)", marginBottom: 4, marginTop: 4 }}>Logic</div>
      {NODE_ORDER.filter((t) => NODE_META[t].group === "logic").map((t) => <PaletteButton key={t} type={t} onClick={() => addNode(t)} />)}
      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fm)", marginBottom: 4, marginTop: 10 }}>Integrations</div>
      {NODE_ORDER.filter((t) => NODE_META[t].group === "integration").map((t) => <PaletteButton key={t} type={t} onClick={() => addNode(t)} />)}
    </>
  );

  const configBody = selectedNode && (
    <>
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
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button onClick={deleteSelected} className="m-tap" style={{ fontSize: 11, color: "#DC2626", background: "none", border: "none", cursor: "pointer" }}>Delete</button>
          {isMobile && <button onClick={() => setSelectedNodeId(null)} className="m-tap" style={{ fontSize: 11, color: "var(--fm)", background: "none", border: "none", cursor: "pointer" }}>Done</button>}
        </div>
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
          <UpstreamHint ids={upstreamOfSelected} />
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
          <UpstreamHint ids={upstreamOfSelected} note="in the URL or body" />
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

      {selectedNode.data.nodeType === "slack" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Slack webhook URL</label>
          <input
            value={selectedNode.data.config.webhook_url || ""}
            onChange={(e) => updateSelectedConfig({ webhook_url: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10, fontFamily: "var(--font-code)" }}
            placeholder="https://hooks.slack.com/services/..."
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Message</label>
          <textarea
            value={selectedNode.data.config.message || ""}
            onChange={(e) => updateSelectedConfig({ message: e.target.value })}
            rows={3}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "email" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>To</label>
          <input
            value={selectedNode.data.config.to || ""}
            onChange={(e) => updateSelectedConfig({ to: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="someone@example.com"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Subject</label>
          <input
            value={selectedNode.data.config.subject || ""}
            onChange={(e) => updateSelectedConfig({ subject: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Body</label>
          <textarea
            value={typeof selectedNode.data.config.body === "string" ? selectedNode.data.config.body : ""}
            onChange={(e) => updateSelectedConfig({ body: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "gmail" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>To</label>
          <input
            value={selectedNode.data.config.to || ""}
            onChange={(e) => updateSelectedConfig({ to: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="someone@example.com"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Subject</label>
          <input
            value={selectedNode.data.config.subject || ""}
            onChange={(e) => updateSelectedConfig({ subject: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Body</label>
          <textarea
            value={typeof selectedNode.data.config.body === "string" ? selectedNode.data.config.body : ""}
            onChange={(e) => updateSelectedConfig({ body: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "slack_bot" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Channel</label>
          <input
            value={selectedNode.data.config.channel || ""}
            onChange={(e) => updateSelectedConfig({ channel: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="#ops or C12345678"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Message</label>
          <textarea
            value={selectedNode.data.config.message || ""}
            onChange={(e) => updateSelectedConfig({ message: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "github_issue" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Repository</label>
          <input
            value={selectedNode.data.config.repo || ""}
            onChange={(e) => updateSelectedConfig({ repo: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="Astra"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Owner (optional)</label>
          <input
            value={selectedNode.data.config.owner || ""}
            onChange={(e) => updateSelectedConfig({ owner: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="AstraCreates"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Issue title</label>
          <input
            value={selectedNode.data.config.title || ""}
            onChange={(e) => updateSelectedConfig({ title: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Issue body</label>
          <textarea
            value={typeof selectedNode.data.config.body === "string" ? selectedNode.data.config.body : ""}
            onChange={(e) => updateSelectedConfig({ body: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "github_pr" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Repository</label>
          <input
            value={selectedNode.data.config.repo || ""}
            onChange={(e) => updateSelectedConfig({ repo: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="Astra"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Owner (optional)</label>
          <input
            value={selectedNode.data.config.owner || ""}
            onChange={(e) => updateSelectedConfig({ owner: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="AstraCreates"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>PR title</label>
          <input
            value={selectedNode.data.config.title || ""}
            onChange={(e) => updateSelectedConfig({ title: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Head branch</label>
          <input
            value={selectedNode.data.config.head || ""}
            onChange={(e) => updateSelectedConfig({ head: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
            placeholder="feature/my-branch"
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Base branch</label>
          <input
            value={selectedNode.data.config.base || "main"}
            onChange={(e) => updateSelectedConfig({ base: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>PR body</label>
          <textarea
            value={typeof selectedNode.data.config.body === "string" ? selectedNode.data.config.body : ""}
            onChange={(e) => updateSelectedConfig({ body: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "linear_issue" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Issue title</label>
          <input
            value={selectedNode.data.config.title || ""}
            onChange={(e) => updateSelectedConfig({ title: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Description</label>
          <textarea
            value={selectedNode.data.config.description || ""}
            onChange={(e) => updateSelectedConfig({ description: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "notion_page" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Page title</label>
          <input
            value={selectedNode.data.config.title || ""}
            onChange={(e) => updateSelectedConfig({ title: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Parent page ID (optional)</label>
          <input
            value={selectedNode.data.config.parent_id || ""}
            onChange={(e) => updateSelectedConfig({ parent_id: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10, fontFamily: "var(--font-code)" }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Notes</label>
          <textarea
            value={typeof selectedNode.data.config.body === "string" ? selectedNode.data.config.body : ""}
            onChange={(e) => updateSelectedConfig({ body: e.target.value })}
            rows={4}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 8, fontFamily: "inherit" }}
          />
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "stripe_payment_link" && (
        <>
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Product name</label>
          <input
            value={selectedNode.data.config.title || ""}
            onChange={(e) => updateSelectedConfig({ title: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Description</label>
          <textarea
            value={selectedNode.data.config.description || ""}
            onChange={(e) => updateSelectedConfig({ description: e.target.value })}
            rows={3}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", resize: "vertical", marginBottom: 10, fontFamily: "inherit" }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Amount</label>
          <input
            type="number"
            min={1}
            value={selectedNode.data.config.amount ?? 99}
            onChange={(e) => updateSelectedConfig({ amount: Number(e.target.value) })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Currency</label>
          <input
            value={selectedNode.data.config.currency || "usd"}
            onChange={(e) => updateSelectedConfig({ currency: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 10 }}
          />
          <label style={{ fontSize: 11, color: "var(--fm)", display: "block", marginBottom: 4 }}>Billing</label>
          <select
            value={selectedNode.data.config.interval || "one_time"}
            onChange={(e) => updateSelectedConfig({ interval: e.target.value })}
            style={{ width: "100%", padding: "7px 8px", fontSize: 12, borderRadius: 6, border: "1px solid var(--bd)", marginBottom: 8 }}
          >
            <option value="one_time">One-time</option>
            <option value="month">Monthly</option>
            <option value="year">Yearly</option>
          </select>
          <UpstreamHint ids={upstreamOfSelected} />
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
    </>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <style>{`
        @keyframes astra-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.3); opacity: 0.7; } }
        @keyframes astra-sheet-up { from { transform: translateY(100%); } to { transform: translateY(0); } }
        .astra-palette-btn:hover { filter: brightness(0.97); transform: translateY(-1px); }
      `}</style>
      <PageHeader
        title=""
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {runError && <span style={{ fontSize: 12, color: "#FF8080" }}>{runError}</span>}
            {savedTick && <span style={{ fontSize: 12, color: "#7CFFC6" }}>✓ Saved</span>}
            <HeaderSecondaryBtn label="Build with AI" onClick={() => setDraftOpen(true)} />
            <HeaderSecondaryBtn label={saving ? "Saving…" : "Save"} onClick={() => { void saveFlow(); }} disabled={saving} />
            <HeaderPrimaryBtn label={running ? "Running…" : "▶ Run"} onClick={() => { void runFlow(); }} disabled={running || nodes.length === 0} />
          </div>
        }
      />
      <div style={{ padding: "10px 24px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10 }}>
        <button onClick={() => router.push("/automations")} className="m-tap" style={{ fontSize: 12, color: "var(--fm)", background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0 }}>
          ← Automations
        </button>
        <input
          value={flowName}
          onChange={(e) => setFlowName(e.target.value)}
          style={{ fontSize: 15, fontWeight: 600, border: "none", outline: "none", background: "transparent", color: "var(--fg)", flex: 1, minWidth: 60 }}
        />
      </div>
      <div style={{ display: "flex", flex: 1, minHeight: 0, position: "relative" }}>
        {/* Node palette — persistent column on desktop, bottom sheet on mobile */}
        {!isMobile && (
          <div style={{ width: 176, borderRight: "1px solid var(--bd)", padding: "10px 10px", overflowY: "auto", flexShrink: 0, background: "var(--s2)" }}>
            {paletteBody}
          </div>
        )}

        {/* Canvas */}
        <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
          {nodes.length === 0 && (
            <div style={{
              position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
              flexDirection: "column", gap: 6, color: "var(--fm)", zIndex: 5, pointerEvents: "none", padding: 24, textAlign: "center",
            }}>
              <div style={{ fontSize: 28, opacity: 0.4 }}>⚡</div>
              <div style={{ fontSize: 13 }}>{isMobile ? "Tap + to add a block" : "Add a block from the left to get started"}</div>
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
            panOnScroll={isMobile}
            zoomOnPinch
          >
            <Background gap={18} color="var(--bd)" />
            <Controls showInteractive={false} />
            {!isMobile && (
              <MiniMap pannable zoomable style={{ background: "var(--s2)" }} nodeColor={(n) => NODE_META[(n.data as AutomationNodeData).nodeType]?.color || "#888"} />
            )}
          </ReactFlow>

          {/* Mobile: floating add button */}
          {isMobile && (
            <button
              onClick={() => setPaletteOpen(true)}
              className="m-tap"
              style={{
                position: "absolute", bottom: 20, right: 20, width: 52, height: 52, borderRadius: "50%",
                background: "#002EFF", color: "#fff", border: "none", fontSize: 24, lineHeight: 1,
                boxShadow: "0 4px 14px rgba(0,46,255,0.35)", cursor: "pointer", zIndex: 10,
              }}
            >
              +
            </button>
          )}
        </div>

        {/* Config panel — persistent column on desktop, bottom sheet on mobile */}
        {!isMobile && selectedNode && (
          <div style={{ width: 256, borderLeft: "1px solid var(--bd)", padding: "14px 16px", overflowY: "auto", flexShrink: 0 }}>
            {configBody}
          </div>
        )}
        {isMobile && selectedNode && (
          <div style={{ position: "fixed", inset: 0, zIndex: 30, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.35)" }} onClick={() => setSelectedNodeId(null)} />
            <div style={{
              position: "relative", background: "var(--surface)", borderTopLeftRadius: 18, borderTopRightRadius: 18,
              padding: 18, paddingBottom: 28, maxHeight: "80vh", overflowY: "auto",
              animation: "astra-sheet-up 0.22s cubic-bezier(0.22,1,0.36,1)",
              boxShadow: "0 -4px 24px rgba(0,0,0,0.18)",
            }}>
              <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--bd)", margin: "0 auto 14px" }} />
              {configBody}
            </div>
          </div>
        )}

        {/* Mobile: palette bottom sheet */}
        {isMobile && paletteOpen && (
          <div style={{ position: "fixed", inset: 0, zIndex: 30, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.35)" }} onClick={() => setPaletteOpen(false)} />
            <div style={{
              position: "relative", background: "var(--surface)", borderTopLeftRadius: 18, borderTopRightRadius: 18,
              padding: 18, paddingBottom: 28, maxHeight: "75vh", overflowY: "auto",
              animation: "astra-sheet-up 0.22s cubic-bezier(0.22,1,0.36,1)",
              boxShadow: "0 -4px 24px rgba(0,0,0,0.18)",
            }}>
              <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--bd)", margin: "0 auto 14px" }} />
              {paletteBody}
            </div>
          </div>
        )}

        {draftOpen && (
          <div style={{ position: "fixed", inset: 0, zIndex: 35, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.35)" }} onClick={() => setDraftOpen(false)} />
            <div style={{ position: "relative", width: "min(720px, 100%)", borderRadius: 18, background: "var(--surface)", border: "1px solid var(--bd)", boxShadow: "0 16px 48px rgba(0,0,0,0.18)", padding: 20, display: "grid", gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--fm)" }}>Natural language builder</div>
                <div style={{ marginTop: 6, fontSize: 20, fontWeight: 700, color: "var(--fg)" }}>Describe the automation you want</div>
              </div>
              <textarea
                value={draftPrompt}
                onChange={(e) => setDraftPrompt(e.target.value)}
                rows={6}
                placeholder="Example: When I summarize a new support complaint, post the summary in Slack, create a Linear issue, and email me the final triage."
                style={{ width: "100%", padding: "12px 14px", fontSize: 14, borderRadius: 12, border: "1px solid var(--bd)", resize: "vertical", fontFamily: "inherit", background: "#fff" }}
              />
              <div style={{ fontSize: 12, color: "var(--fm)", lineHeight: 1.5 }}>
                Astra will draft a native flow using the blocks already available in your workspace. You can edit everything before saving or running it.
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <HeaderSecondaryBtn label="Cancel" onClick={() => setDraftOpen(false)} />
                <HeaderPrimaryBtn label={drafting ? "Drafting…" : "Generate draft"} onClick={() => { void buildFromPrompt(); }} disabled={drafting || !draftPrompt.trim()} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PaletteButton({ type, onClick }: { type: NodeType; onClick: () => void }) {
  const meta = NODE_META[type];
  return (
    <button
      onClick={onClick}
      className="m-tap astra-palette-btn"
      style={{
        width: "100%", textAlign: "left", padding: "6px 9px", marginBottom: 4, borderRadius: 8,
        border: `1px solid ${meta.border}`, background: meta.bg, cursor: "pointer",
        transition: "transform 0.12s ease, filter 0.12s ease",
        display: "flex", alignItems: "center", gap: 7,
      }}
    >
      <span style={{ fontSize: 12, color: meta.color, flexShrink: 0 }}>{meta.icon}</span>
      <span style={{ fontSize: 11.5, fontWeight: 600, color: meta.color }}>{meta.label}</span>
    </button>
  );
}

function UpstreamHint({ ids, note }: { ids: string[]; note?: string }) {
  if (ids.length === 0) return null;
  return (
    <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.5 }}>
      Reference upstream output {note || ""} with: {ids.map((id) => (
        <code key={id} style={{ background: "var(--s2)", padding: "1px 5px", borderRadius: 4, marginRight: 4 }}>{`{{${id}.output}}`}</code>
      ))}
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
  if (nodeType === "slack") return "Post to Slack";
  if (nodeType === "email") return config.to ? `Email ${config.to}` : "Send email";
  if (nodeType === "gmail") return config.to ? `Gmail ${config.to}` : "Gmail send";
  if (nodeType === "slack_bot") return config.channel ? `Slack ${config.channel}` : "Slack bot post";
  if (nodeType === "github_issue") return config.repo ? `Issue in ${config.repo}` : "GitHub issue";
  if (nodeType === "github_pr") return config.repo ? `PR in ${config.repo}` : "GitHub PR";
  if (nodeType === "linear_issue") return config.title ? `Linear: ${config.title}` : "Linear issue";
  if (nodeType === "notion_page") return config.title ? `Notion: ${config.title}` : "Notion page";
  if (nodeType === "stripe_payment_link") return config.title ? `Stripe: ${config.title}` : "Stripe payment link";
  if (nodeType === "action" && config.url) {
    try { return new URL(config.url).hostname; } catch { return NODE_META.action.label; }
  }
  return NODE_META[nodeType].label;
}
