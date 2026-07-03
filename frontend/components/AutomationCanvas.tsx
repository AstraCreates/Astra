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
import { draftAutomationLocally } from "@/lib/automation-draft";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Core logic types have bespoke behavior/config UI. Every external service
// (Slack/GitHub/Stripe/Twilio/etc — 38 of them) is ONE type, "integration",
// driven entirely by the backend registry (backend/tools/automation_blocks.py)
// fetched at /automations/integration-catalog — adding a new integration
// block never requires a frontend change.
type NodeType =
  | "trigger" | "agent" | "prompt" | "action" | "delay" | "condition"
  | "condition_equals" | "merge" | "json_extract" | "text_transform" | "set_text" | "current_time"
  | "switch" | "code"
  | "integration";

type ParamField = { key: string; label: string; type: string; placeholder?: string };
type IntegrationBlockMeta = { key: string; label: string; category: string; scope: "founder" | "astra"; params: ParamField[] };

type NodeConfig = {
  agent_name?: string;
  instruction?: string;
  system_prompt?: string;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  body?: Record<string, unknown> | string;
  windmill_flow_path?: string;
  seconds?: number;
  contains?: string;
  equals?: string;
  separator?: string;
  path?: string;
  operation?: string;
  text?: string;
  block_key?: string;
  params?: Record<string, string>;
  output_schema?: string;
  value?: string;
  cases?: string[];
  expression?: string;
};

type NodeStatus = "idle" | "running" | "done" | "error" | "skipped";

type AutomationNodeData = {
  label: string;
  nodeType: NodeType;
  config: NodeConfig;
  status?: NodeStatus;
  output?: string;
  // Snapshot of the integration block's category, cached on the node itself —
  // CanvasNode renders standalone (React Flow doesn't thread extra props into
  // custom node types), so it can't look up the live catalog by block_key.
  category?: string;
};

type AutomationNode = Node<AutomationNodeData>;
type AgentCatalogEntry = { id: string; name: string; description: string };

type NodeMeta = { icon: string; label: string; short: string; description: string; color: string; bg: string; border: string; group: "logic" | "utility" };

const CORE_META: Record<Exclude<NodeType, "integration">, NodeMeta> = {
  trigger: { icon: "▶", label: "Manual trigger", short: "Trigger", description: "Starts the flow when you click Run.", color: "#5B8DEF", bg: "rgba(150,190,255,0.10)", border: "rgba(150,190,255,0.45)", group: "logic" },
  agent: { icon: "✺", label: "Run agent", short: "Agent", description: "Runs one of Astra's specialists with full tool access — web search, file generation, browsing. Use for research, building, or anything that needs real tools.", color: "#0F8A4B", bg: "rgba(124,255,198,0.10)", border: "rgba(124,255,198,0.45)", group: "logic" },
  prompt: { icon: "✎", label: "Quick reply", short: "Prompt", description: "A fast, tool-free LLM reply — good for rewriting, summarizing, formatting. Cannot browse, search, or use files. Use Agent for that.", color: "#B45309", bg: "rgba(255,180,50,0.10)", border: "rgba(255,180,50,0.45)", group: "logic" },
  action: { icon: "⌘", label: "HTTP request", short: "Action", description: "Calls any external URL (or an existing Windmill flow) and passes the response downstream.", color: "#7C3AED", bg: "rgba(200,150,255,0.10)", border: "rgba(200,150,255,0.45)", group: "logic" },
  delay: { icon: "◷", label: "Delay", short: "Delay", description: "Pauses for a fixed number of seconds before continuing.", color: "#0891B2", bg: "rgba(103,232,249,0.10)", border: "rgba(103,232,249,0.45)", group: "logic" },
  condition: { icon: "◈", label: "Condition (contains)", short: "Condition", description: "If the upstream output doesn't contain this text, this branch stops here — everything after it is skipped.", color: "#BE185D", bg: "rgba(251,182,206,0.14)", border: "rgba(251,182,206,0.5)", group: "logic" },
  condition_equals: { icon: "=", label: "Condition (equals)", short: "Equals", description: "Same as Condition, but requires an exact match instead of just containing the text.", color: "#BE185D", bg: "rgba(251,182,206,0.14)", border: "rgba(251,182,206,0.5)", group: "utility" },
  merge: { icon: "⋈", label: "Merge", short: "Merge", description: "Explicit join point — passes combined upstream output through unchanged. Useful when a node has multiple incoming connections.", color: "#4B5563", bg: "rgba(75,85,99,0.08)", border: "rgba(75,85,99,0.25)", group: "utility" },
  json_extract: { icon: "{}", label: "Extract JSON field", short: "JSON", description: "Pulls one field out of upstream JSON output using a dot-path, e.g. data.0.id.", color: "#4B5563", bg: "rgba(75,85,99,0.08)", border: "rgba(75,85,99,0.25)", group: "utility" },
  text_transform: { icon: "Aa", label: "Transform text", short: "Text", description: "Uppercase, lowercase, or trim the upstream output.", color: "#4B5563", bg: "rgba(75,85,99,0.08)", border: "rgba(75,85,99,0.25)", group: "utility" },
  set_text: { icon: "T", label: "Set text", short: "Text", description: "A constant text value — useful as a flow's starting input.", color: "#4B5563", bg: "rgba(75,85,99,0.08)", border: "rgba(75,85,99,0.25)", group: "utility" },
  current_time: { icon: "⏱", label: "Current time", short: "Time", description: "Outputs the current UTC timestamp.", color: "#4B5563", bg: "rgba(75,85,99,0.08)", border: "rgba(75,85,99,0.25)", group: "utility" },
  switch: { icon: "⑂", label: "Switch / Router", short: "Switch", description: "Routes to a different branch by matching the upstream value against a list of cases — everything except the matching branch (and Default) is skipped.", color: "#0E7490", bg: "rgba(14,116,144,0.08)", border: "rgba(14,116,144,0.3)", group: "logic" },
  code: { icon: "</>", label: "Code (expression)", short: "Code", description: "Evaluates one restricted Python expression against the upstream output (as `input`). No imports, no file/network access — a safe escape hatch, not a full script sandbox.", color: "#1E293B", bg: "rgba(30,41,59,0.06)", border: "rgba(30,41,59,0.2)", group: "utility" },
};

const CORE_ORDER: Exclude<NodeType, "integration">[] = [
  "trigger", "agent", "prompt", "action", "delay", "condition",
  "condition_equals", "switch", "merge", "json_extract", "text_transform", "set_text", "current_time", "code",
];

// Per-category color for integration blocks (fetched dynamically, so these are
// keyed by category name rather than the fixed enum the core types use).
const CATEGORY_META: Record<string, { icon: string; color: string; bg: string; border: string }> = {
  Slack: { icon: "#", color: "#611F69", bg: "rgba(97,31,105,0.08)", border: "rgba(97,31,105,0.35)" },
  Email: { icon: "✉", color: "#1D4ED8", bg: "rgba(29,78,216,0.08)", border: "rgba(29,78,216,0.35)" },
  Gmail: { icon: "✉", color: "#EA4335", bg: "rgba(234,67,53,0.08)", border: "rgba(234,67,53,0.28)" },
  GitHub: { icon: "●", color: "#111827", bg: "rgba(17,24,39,0.08)", border: "rgba(17,24,39,0.18)" },
  Linear: { icon: "◈", color: "#5E6AD2", bg: "rgba(94,106,210,0.08)", border: "rgba(94,106,210,0.24)" },
  Notion: { icon: "▷", color: "#111111", bg: "rgba(17,17,17,0.06)", border: "rgba(17,17,17,0.18)" },
  LinkedIn: { icon: "in", color: "#0A66C2", bg: "rgba(10,102,194,0.08)", border: "rgba(10,102,194,0.28)" },
  Calendar: { icon: "▦", color: "#0F766E", bg: "rgba(15,118,110,0.08)", border: "rgba(15,118,110,0.28)" },
  Stripe: { icon: "$", color: "#635BFF", bg: "rgba(99,91,255,0.08)", border: "rgba(99,91,255,0.24)" },
  Twilio: { icon: "☎", color: "#F22F46", bg: "rgba(242,47,70,0.08)", border: "rgba(242,47,70,0.24)" },
  Klaviyo: { icon: "◆", color: "#000000", bg: "rgba(0,0,0,0.06)", border: "rgba(0,0,0,0.18)" },
  Square: { icon: "■", color: "#000000", bg: "rgba(0,0,0,0.06)", border: "rgba(0,0,0,0.18)" },
  Yelp: { icon: "★", color: "#D32323", bg: "rgba(211,35,35,0.08)", border: "rgba(211,35,35,0.24)" },
  Printful: { icon: "▧", color: "#EA5B0C", bg: "rgba(234,91,12,0.08)", border: "rgba(234,91,12,0.24)" },
  "Lemon Squeezy": { icon: "◔", color: "#FFC233", bg: "rgba(255,194,51,0.14)", border: "rgba(255,194,51,0.4)" },
};

function metaFor(nodeType: NodeType, category: string | undefined, label?: string, scope?: "founder" | "astra") {
  if (nodeType !== "integration") return CORE_META[nodeType];
  const cat = category ? CATEGORY_META[category] : undefined;
  return {
    icon: cat?.icon || "⌘", label: label || "Integration", short: category || "Integration",
    description: category ? `${category} — ${scope === "founder" ? "uses your connected account" : "uses Astra's configured account for this service"}.` : "",
    color: cat?.color || "#7C3AED", bg: cat?.bg || "rgba(200,150,255,0.10)", border: cat?.border || "rgba(200,150,255,0.45)",
    group: "logic" as const,
  };
}

const STATUS_COLORS: Record<string, string> = { running: "#3B82F6", done: "#16A34A", error: "#DC2626", skipped: "#94A3B8" };

function CanvasNode({ data, selected }: NodeProps<AutomationNode>) {
  const meta = metaFor(data.nodeType, data.category, data.label);
  const statusColor = data.status && data.status !== "idle" ? STATUS_COLORS[data.status] : undefined;
  const dimmed = data.status === "skipped";
  return (
    <div style={{
      minWidth: 210, maxWidth: 250, borderRadius: 14, padding: "12px 14px",
      background: "var(--surface)", border: `1.5px solid ${selected ? meta.color : meta.border}`,
      boxShadow: selected ? `0 0 0 3px ${meta.bg}, 0 2px 8px rgba(0,0,0,0.06)` : "0 1px 4px rgba(0,0,0,0.07)",
      position: "relative", opacity: dimmed ? 0.5 : 1, transition: "box-shadow 0.15s ease, opacity 0.2s ease",
    }}>
      <Handle type="target" position={Position.Left} style={{ background: meta.color, width: 9, height: 9, border: "2px solid var(--surface)" }} />
      {data.nodeType === "switch" ? null : (
        <Handle type="source" position={Position.Right} style={{ background: meta.color, width: 9, height: 9, border: "2px solid var(--surface)" }} />
      )}
      {statusColor && (
        <div style={{
          position: "absolute", top: -7, right: -7, width: 15, height: 15, borderRadius: "50%",
          background: statusColor, border: "2px solid var(--surface)", boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          animation: data.status === "running" ? "astra-pulse 1s ease-in-out infinite" : undefined,
        }} />
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
        <span style={{ width: 22, height: 22, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, background: meta.bg, color: meta.color, flexShrink: 0 }}>
          {meta.icon}
        </span>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: meta.color }}>{meta.short}</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.label}</div>
      {data.nodeType === "switch" && (
        <div style={{ marginTop: 6 }}>
          {(data.config.cases || []).map((c, i) => (
            <div key={i} style={{ position: "relative", fontSize: 10.5, color: "var(--fm)", padding: "4px 10px 4px 0", borderTop: "1px solid var(--bd)" }}>
              {c || `Case ${i + 1}`}
              <Handle type="source" position={Position.Right} id={`case_${i}`} style={{ background: meta.color, width: 8, height: 8, border: "2px solid var(--surface)", top: "50%" }} />
            </div>
          ))}
          <div style={{ position: "relative", fontSize: 10.5, color: "var(--fm)", padding: "4px 10px 4px 0", borderTop: "1px solid var(--bd)" }}>
            Default
            <Handle type="source" position={Position.Right} id="default" style={{ background: "#94A3B8", width: 8, height: 8, border: "2px solid var(--surface)", top: "50%" }} />
          </div>
        </div>
      )}
      {data.output && (
        <div style={{ marginTop: 7, fontSize: 11, color: "var(--fm)", maxHeight: 44, overflow: "hidden", borderTop: "1px solid var(--bd)", paddingTop: 6, lineHeight: 1.4 }}>
          {data.output.slice(0, 140)}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { trigger: CanvasNode, agent: CanvasNode, prompt: CanvasNode, action: CanvasNode, delay: CanvasNode, condition: CanvasNode, condition_equals: CanvasNode, merge: CanvasNode, json_extract: CanvasNode, text_transform: CanvasNode, set_text: CanvasNode, current_time: CanvasNode, switch: CanvasNode, code: CanvasNode, integration: CanvasNode };

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
    case "condition_equals": return { equals: "" };
    case "merge": return { separator: "\n\n" };
    case "json_extract": return { path: "" };
    case "text_transform": return { operation: "trim" };
    case "set_text": return { text: "" };
    case "current_time": return {};
    case "switch": return { value: "", cases: ["", ""] };
    case "code": return { expression: "" };
    case "integration": return { block_key: "", params: {} };
  }
}

export default function AutomationCanvas({ flowId }: { flowId: string }) {
  const router = useRouter();
  const { userId } = useDevUser();
  const isMobile = useIsMobile();
  const isNew = flowId === "new";

  const [flowName, setFlowName] = useState("Untitled automation");
  const [savedFlowId, setSavedFlowId] = useState<string>(isNew ? "" : flowId);
  const [webhookToken, setWebhookToken] = useState("");
  const [nodes, setNodes] = useState<AutomationNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [agentCatalog, setAgentCatalog] = useState<AgentCatalogEntry[]>([]);
  const [integrationCatalog, setIntegrationCatalog] = useState<IntegrationBlockMeta[]>([]);
  const [status, setStatus] = useState<"loading" | "ready">(isNew ? "ready" : "loading");
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string>("");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteTab, setPaletteTab] = useState<"logic" | "integrations">("logic");
  const [paletteFilter, setPaletteFilter] = useState("");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const [outputOpen, setOutputOpen] = useState(false);
  const pollRef = useRef<number | null>(null);

  const blockByKey = useMemo(() => Object.fromEntries(integrationCatalog.map((b) => [b.key, b])), [integrationCatalog]);

  // Labels/categories for integration nodes are looked up live from the fetched
  // catalog at render time rather than baked into node state — avoids a
  // setState-in-effect backfill (and the stale-label window it'd otherwise have)
  // for integration nodes loaded from a saved flow before the catalog arrives.
  const displayNodes = useMemo(() => nodes.map((n) => {
    if (n.data.nodeType !== "integration") return n;
    const block = blockByKey[n.data.config.block_key || ""];
    return { ...n, data: { ...n.data, label: block?.label || "Integration", category: block?.category } };
  }), [nodes, blockByKey]);

  // Terminal nodes — nothing downstream — are the flow's "final output".
  const leafIds = useMemo(() => {
    const sources = new Set(edges.map((e) => e.source));
    return new Set(nodes.filter((n) => !sources.has(n.id)).map((n) => n.id));
  }, [nodes, edges]);

  const ranNodes = useMemo(() => displayNodes.filter((n) => n.data.status && n.data.status !== "idle"), [displayNodes]);

  const selectedNode = useMemo(() => displayNodes.find((n) => n.id === selectedNodeId) || null, [displayNodes, selectedNodeId]);
  const selectedBlock = selectedNode?.data.nodeType === "integration" ? blockByKey[selectedNode.data.config.block_key || ""] : undefined;

  const integrationsByCategory = useMemo(() => {
    const groups: Record<string, IntegrationBlockMeta[]> = {};
    for (const b of integrationCatalog) {
      if (paletteFilter && !`${b.category} ${b.label}`.toLowerCase().includes(paletteFilter.toLowerCase())) continue;
      (groups[b.category] ||= []).push(b);
    }
    return groups;
  }, [integrationCatalog, paletteFilter]);

  useEffect(() => {
    waitForAuthReady().then(() => Promise.all([
      apiFetch(`${BASE}/agents/catalog`).then((r) => (r.ok ? r.json() : { agents: [] })),
      apiFetch(`${BASE}/automations/integration-catalog`).then((r) => (r.ok ? r.json() : { blocks: [] })),
    ])).then(([agentsData, blocksData]) => {
      setAgentCatalog(agentsData.agents || []);
      setIntegrationCatalog(blocksData.blocks || []);
    }).catch(() => {});
  }, []);

  const decorateNode = useCallback((nodeType: NodeType, config: NodeConfig, catalog: IntegrationBlockMeta[]): { label: string; category?: string } => {
    if (nodeType === "integration") {
      const block = catalog.find((b) => b.key === config.block_key);
      return { label: block?.label || "Integration", category: block?.category };
    }
    if (nodeType === "agent" && config.agent_name) return { label: `Run ${config.agent_name}` };
    if (nodeType === "delay") return { label: `Wait ${config.seconds ?? 5}s` };
    if (nodeType === "condition") return { label: config.contains ? `If contains "${config.contains}"` : "Condition" };
    if (nodeType === "condition_equals") return { label: config.equals ? `If equals "${config.equals}"` : "Equals" };
    if (nodeType === "json_extract") return { label: config.path ? `Extract ${config.path}` : "Extract JSON field" };
    if (nodeType === "text_transform") return { label: `Transform (${config.operation || "trim"})` };
    if (nodeType === "set_text") return { label: config.text ? `"${config.text.slice(0, 24)}"` : "Set text" };
    if (nodeType === "switch") return { label: `Switch (${(config.cases || []).filter(Boolean).length} cases)` };
    if (nodeType === "code") return { label: config.expression ? config.expression.slice(0, 28) : "Code (expression)" };
    if (nodeType === "action" && config.url) {
      try { return { label: new URL(config.url).hostname }; } catch { return { label: CORE_META.action.label }; }
    }
    return { label: CORE_META[nodeType as Exclude<NodeType, "integration">]?.label || nodeType };
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
        setWebhookToken(flow.webhook_token || "");
        setNodes((flow.nodes || []).map((n: { id: string; type: NodeType; position?: { x: number; y: number }; config?: NodeConfig }) => {
          const decorated = decorateNode(n.type, n.config || {}, []);
          return { id: n.id, type: n.type, position: n.position || { x: 0, y: 0 }, data: { ...decorated, nodeType: n.type, config: n.config || {} } };
        }));
        setEdges((flow.edges || []).map((e: { source: string; target: string; source_handle?: string }, i: number) => ({
          id: `e${i}_${e.source}_${e.target}`, source: e.source, target: e.target, sourceHandle: e.source_handle, type: "default", markerEnd: { type: MarkerType.ArrowClosed },
        })));
        setStatus("ready");
      })
      .catch(() => setStatus("ready"));
    return () => { cancelled = true; };
  }, [flowId, isNew, userId, decorateNode]);

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds) as AutomationNode[]), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback((conn: Connection) => setEdges((eds) => addEdge({ ...conn, type: "default", markerEnd: { type: MarkerType.ArrowClosed } }, eds)), []);

  function addNode(nodeType: NodeType, blockKey?: string) {
    const id = genId();
    const config = nodeType === "integration" ? { block_key: blockKey || "", params: {} } : defaultConfigFor(nodeType);
    const node: AutomationNode = {
      id, type: nodeType,
      position: isMobile ? { x: 40, y: 40 + nodes.length * 90 } : { x: 100 + (nodes.length % 4) * 60, y: 100 + nodes.length * 70 },
      data: { ...decorateNode(nodeType, config, integrationCatalog), nodeType, config },
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
      return { ...n, data: { ...n.data, config, ...decorateNode(n.data.nodeType, config, integrationCatalog) } };
    }));
  }

  function updateSelectedParam(paramKey: string, value: string) {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.map((n) => {
      if (n.id !== selectedNodeId) return n;
      const params = { ...(n.data.config.params || {}), [paramKey]: value };
      return { ...n, data: { ...n.data, config: { ...n.data.config, params } } };
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
        founder_id: userId, name: flowName, flow_id: savedFlowId,
        nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, position: n.position, config: n.data.config })),
        edges: edges.map((e) => ({ source: e.source, target: e.target, source_handle: e.sourceHandle || undefined })),
      };
      const res = await apiFetch(`${BASE}/automations/flows`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(String(res.status));
      const saved = await res.json();
      setSavedFlowId(saved.id);
      setWebhookToken(saved.webhook_token || "");
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
    const id = await saveFlow();
    if (!id) { setRunError("Could not save flow before running."); return; }
    setRunning(true);
    setOutputOpen(true);
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: "idle" as const, output: undefined } })));
    try {
      const res = await apiFetch(`${BASE}/automations/flows/${id}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ founder_id: userId }) });
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
    const applyDraft = (draft: { name?: string; nodes: { id: string; type: NodeType; position?: { x: number; y: number }; config?: NodeConfig }[]; edges: { source: string; target: string }[] }) => {
      setFlowName(draft.name || "Draft automation");
      setSavedFlowId("");
      setNodes(draft.nodes.map((n) => {
        const config = n.config || {};
        return { id: n.id, type: n.type, position: n.position || { x: 0, y: 0 }, data: { ...decorateNode(n.type, config, integrationCatalog), nodeType: n.type, config } };
      }));
      setEdges(draft.edges.map((e, i) => ({
        id: `d${i}_${e.source}_${e.target}`, source: e.source, target: e.target,
        type: "default", markerEnd: { type: MarkerType.ArrowClosed },
      })));
      setSelectedNodeId(null);
      setDraftOpen(false);
    };
    try {
      await waitForAuthReady();
      const res = await apiFetch(`${BASE}/automations/flows/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: userId, prompt: draftPrompt }),
      });
      if (!res.ok) {
        applyDraft(draftAutomationLocally(draftPrompt) as unknown as { name?: string; nodes: { id: string; type: NodeType; config?: NodeConfig }[]; edges: { source: string; target: string }[] });
        setRunError("Build with AI used a local fallback draft because the server draft route was unavailable.");
      } else {
        applyDraft(await res.json());
      }
    } catch {
      applyDraft(draftAutomationLocally(draftPrompt) as unknown as { name?: string; nodes: { id: string; type: NodeType; config?: NodeConfig }[]; edges: { source: string; target: string }[] });
      setRunError("Build with AI fell back to a local draft. You can still edit and save it normally.");
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
      <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
        <button onClick={() => setPaletteTab("logic")} className="m-tap" style={tabStyle(paletteTab === "logic")}>Logic</button>
        <button onClick={() => setPaletteTab("integrations")} className="m-tap" style={tabStyle(paletteTab === "integrations")}>Integrations ({integrationCatalog.length})</button>
      </div>
      {paletteTab === "logic" && (
        <>
          <div style={sectionLabelStyle}>Logic</div>
          {CORE_ORDER.filter((t) => CORE_META[t].group === "logic").map((t) => <CorePaletteButton key={t} type={t} onClick={() => addNode(t)} />)}
          <div style={{ ...sectionLabelStyle, marginTop: 14 }}>Utility</div>
          {CORE_ORDER.filter((t) => CORE_META[t].group === "utility").map((t) => <CorePaletteButton key={t} type={t} onClick={() => addNode(t)} />)}
        </>
      )}
      {paletteTab === "integrations" && (
        <>
          <input
            value={paletteFilter}
            onChange={(e) => setPaletteFilter(e.target.value)}
            placeholder="Search integrations…"
            className="f-input" style={{ marginBottom: 10, fontSize: 12, padding: "7px 9px" }}
          />
          {Object.keys(integrationsByCategory).length === 0 && (
            <div style={{ fontSize: 11.5, color: "var(--fm)" }}>{integrationCatalog.length === 0 ? "Loading…" : "No matches."}</div>
          )}
          {Object.entries(integrationsByCategory).map(([category, blocks]) => {
            const cat = CATEGORY_META[category] || CATEGORY_META.Email;
            return (
              <div key={category} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                  <span style={{ fontSize: 11 }}>{cat.icon}</span>
                  <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: cat.color }}>{category}</span>
                </div>
                {blocks.map((b) => (
                  <button key={b.key} onClick={() => addNode("integration", b.key)} className="m-tap astra-palette-btn" style={{
                    width: "100%", textAlign: "left", padding: "8px 10px", marginBottom: 5, borderRadius: 8,
                    border: `1px solid ${cat.border}`, background: cat.bg, cursor: "pointer", fontSize: 12, fontWeight: 600, color: cat.color,
                  }}>
                    {b.label}
                  </button>
                ))}
              </div>
            );
          })}
        </>
      )}
    </>
  );

  const selectedMeta = selectedNode ? metaFor(selectedNode.data.nodeType, selectedBlock?.category, selectedBlock?.label, selectedBlock?.scope) : null;

  const configBody = selectedNode && selectedMeta && (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 24, height: 24, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, background: selectedMeta.bg, color: selectedMeta.color }}>
            {selectedMeta.icon}
          </span>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{selectedMeta.label}</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button onClick={deleteSelected} className="btn danger sm">Delete</button>
          {isMobile && <button onClick={() => setSelectedNodeId(null)} className="btn sm">Done</button>}
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--fm)", lineHeight: 1.5, marginBottom: 16 }}>{selectedMeta.description}</div>

      {selectedNode.data.nodeType === "integration" && (
        <>
          <label className="f-label">Which {selectedBlock?.category || "service"} action</label>
          <select
            value={selectedNode.data.config.block_key || ""}
            onChange={(e) => updateSelectedConfig({ block_key: e.target.value, params: {} })}
            className="f-input" style={{ marginBottom: 12 }}
          >
            <option value="">Select…</option>
            {Object.entries(integrationsByCategoryAll(integrationCatalog)).map(([cat, blocks]) => (
              <optgroup key={cat} label={cat}>
                {blocks.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
              </optgroup>
            ))}
          </select>
          {selectedBlock && selectedBlock.params.map((p) => (
            <div key={p.key} style={{ marginBottom: 10 }}>
              <label className="f-label">{p.label}</label>
              {p.type === "textarea" ? (
                <textarea rows={3} value={selectedNode.data.config.params?.[p.key] || ""} onChange={(e) => updateSelectedParam(p.key, e.target.value)} placeholder={p.placeholder} className="f-ta" />
              ) : (
                <input type={p.type === "number" ? "number" : "text"} value={selectedNode.data.config.params?.[p.key] || ""} onChange={(e) => updateSelectedParam(p.key, e.target.value)} placeholder={p.placeholder} className="f-input" />
              )}
            </div>
          ))}
          <UpstreamHint ids={upstreamOfSelected} />
        </>
      )}

      {selectedNode.data.nodeType === "agent" && (
        <>
          <label className="f-label">Agent</label>
          <select value={selectedNode.data.config.agent_name || ""} onChange={(e) => updateSelectedConfig({ agent_name: e.target.value })} className="f-input" style={{ marginBottom: 6 }}>
            {agentCatalog.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          {agentCatalog.find((a) => a.id === selectedNode.data.config.agent_name) && (
            <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.4 }}>{agentCatalog.find((a) => a.id === selectedNode.data.config.agent_name)?.description}</div>
          )}
        </>
      )}

      {(selectedNode.data.nodeType === "agent" || selectedNode.data.nodeType === "prompt") && (
        <>
          <label className="f-label">Instruction</label>
          <textarea value={selectedNode.data.config.instruction || ""} onChange={(e) => updateSelectedConfig({ instruction: e.target.value })} rows={6} className="f-ta" style={{ marginBottom: 10 }} placeholder="What should this node do?" />
          <UpstreamHint ids={upstreamOfSelected} />
          <label className="f-label">Structured output (optional)</label>
          <textarea
            value={selectedNode.data.config.output_schema || ""}
            onChange={(e) => updateSelectedConfig({ output_schema: e.target.value })}
            rows={2} className="f-ta" style={{ marginBottom: 6 }}
            placeholder='e.g. {"category": "string", "priority": "low|medium|high"}'
          />
          <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.4 }}>
            If set, the model is asked to return only JSON matching this shape — pair with an Extract JSON field node downstream.
          </div>
        </>
      )}

      {selectedNode.data.nodeType === "action" && (
        <>
          <label className="f-label">Method</label>
          <select value={selectedNode.data.config.method || "GET"} onChange={(e) => updateSelectedConfig({ method: e.target.value })} className="f-input" style={{ marginBottom: 12 }}>
            {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <label className="f-label">URL</label>
          <input value={selectedNode.data.config.url || ""} onChange={(e) => updateSelectedConfig({ url: e.target.value })} className="f-input" style={{ marginBottom: 14, fontFamily: "var(--font-code)" }} placeholder="https://api.example.com/..." />
          <UpstreamHint ids={upstreamOfSelected} note="in the URL or body" />
        </>
      )}

      {selectedNode.data.nodeType === "delay" && (
        <>
          <label className="f-label">Wait (seconds)</label>
          <input type="number" min={0} max={3600} value={selectedNode.data.config.seconds ?? 5} onChange={(e) => updateSelectedConfig({ seconds: Number(e.target.value) })} className="f-input" style={{ marginBottom: 14 }} />
        </>
      )}

      {selectedNode.data.nodeType === "condition" && (
        <>
          <label className="f-label">Continue only if upstream output contains</label>
          <input value={selectedNode.data.config.contains || ""} onChange={(e) => updateSelectedConfig({ contains: e.target.value })} className="f-input" style={{ marginBottom: 14 }} placeholder="e.g. yes, approved, error" />
        </>
      )}

      {selectedNode.data.nodeType === "condition_equals" && (
        <>
          <label className="f-label">Continue only if upstream output exactly equals</label>
          <input value={selectedNode.data.config.equals || ""} onChange={(e) => updateSelectedConfig({ equals: e.target.value })} className="f-input" style={{ marginBottom: 14 }} />
        </>
      )}

      {selectedNode.data.nodeType === "switch" && (
        <>
          <label className="f-label">Value to match (optional)</label>
          <input
            value={selectedNode.data.config.value || ""}
            onChange={(e) => updateSelectedConfig({ value: e.target.value })}
            className="f-input" style={{ marginBottom: 6, fontFamily: "var(--font-code)" }}
            placeholder="Defaults to the upstream output — e.g. {{node_1.output}}"
          />
          <UpstreamHint ids={upstreamOfSelected} />
          <label className="f-label" style={{ marginTop: 6 }}>Cases</label>
          {(selectedNode.data.config.cases || []).map((c, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
              <input
                value={c}
                onChange={(e) => {
                  const cases = [...(selectedNode.data.config.cases || [])];
                  cases[i] = e.target.value;
                  updateSelectedConfig({ cases });
                }}
                className="f-input" placeholder={`Case ${i + 1} value`}
              />
              <button
                onClick={() => updateSelectedConfig({ cases: (selectedNode.data.config.cases || []).filter((_, j) => j !== i) })}
                className="btn danger sm"
              >×</button>
            </div>
          ))}
          <button
            onClick={() => updateSelectedConfig({ cases: [...(selectedNode.data.config.cases || []), ""] })}
            className="btn sm" style={{ marginBottom: 12 }}
          >+ Add case</button>
          <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.4 }}>
            Anything that doesn&apos;t match a case follows the Default branch. Drag a connection from each row on the node to wire up its branch.
          </div>
        </>
      )}

      {selectedNode.data.nodeType === "code" && (
        <>
          <label className="f-label">Expression</label>
          <textarea
            value={selectedNode.data.config.expression || ""}
            onChange={(e) => updateSelectedConfig({ expression: e.target.value })}
            rows={4} className="f-ta" style={{ marginBottom: 6, fontFamily: "var(--font-code)" }}
            placeholder='e.g. input["items"][0]["name"].upper()'
          />
          <div style={{ fontSize: 10.5, color: "var(--fm)", marginBottom: 12, lineHeight: 1.4 }}>
            One expression only — `input` is the upstream output (JSON-parsed if possible). No imports, no file or network access.
          </div>
        </>
      )}

      {selectedNode.data.nodeType === "merge" && (
        <>
          <label className="f-label">Separator</label>
          <input value={selectedNode.data.config.separator ?? "\n\n"} onChange={(e) => updateSelectedConfig({ separator: e.target.value })} className="f-input" style={{ marginBottom: 14 }} />
        </>
      )}

      {selectedNode.data.nodeType === "json_extract" && (
        <>
          <label className="f-label">Field path</label>
          <input value={selectedNode.data.config.path || ""} onChange={(e) => updateSelectedConfig({ path: e.target.value })} className="f-input" style={{ marginBottom: 14 }} placeholder="e.g. data.0.id" />
        </>
      )}

      {selectedNode.data.nodeType === "text_transform" && (
        <>
          <label className="f-label">Operation</label>
          <select value={selectedNode.data.config.operation || "trim"} onChange={(e) => updateSelectedConfig({ operation: e.target.value })} className="f-input" style={{ marginBottom: 14 }}>
            {["trim", "uppercase", "lowercase"].map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </>
      )}

      {selectedNode.data.nodeType === "set_text" && (
        <>
          <label className="f-label">Text</label>
          <textarea rows={3} value={selectedNode.data.config.text || ""} onChange={(e) => updateSelectedConfig({ text: e.target.value })} className="f-ta" style={{ marginBottom: 10 }} />
        </>
      )}

      {selectedNode.data.nodeType === "current_time" && (
        <div style={{ fontSize: 12, color: "var(--fm)" }}>No configuration needed.</div>
      )}

      {selectedNode.data.nodeType === "trigger" && (
        <>
          <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 12 }}>Runs when you click Run above.</div>
          <label className="f-label">Webhook URL</label>
          {savedFlowId && webhookToken ? (
            <>
              <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                <input readOnly value={`${BASE}/automations/hooks/${userId}/${savedFlowId}/${webhookToken}`} className="f-input" style={{ fontFamily: "var(--font-code)", fontSize: 11 }} onFocus={(e) => e.currentTarget.select()} />
                <button
                  onClick={() => { void navigator.clipboard.writeText(`${BASE}/automations/hooks/${userId}/${savedFlowId}/${webhookToken}`); }}
                  className="btn sm"
                >Copy</button>
              </div>
              <div style={{ fontSize: 10.5, color: "var(--fm)", lineHeight: 1.4 }}>
                POST any JSON here to start a run without opening the canvas. The payload is this trigger&apos;s output — read it downstream with {`{{${selectedNode.id}.output}}`}.
              </div>
            </>
          ) : (
            <div style={{ fontSize: 11.5, color: "var(--fm)" }}>Save the flow to get a webhook URL.</div>
          )}
        </>
      )}

      {selectedNode.data.status && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--bd)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: STATUS_COLORS[selectedNode.data.status] || "var(--fm)" }} />
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: "var(--fm)" }}>{selectedNode.data.status}</span>
          </div>
          {selectedNode.data.output && (
            <div style={{ fontSize: 12, color: "var(--fg)", whiteSpace: "pre-wrap", background: "var(--s2)", borderRadius: 8, padding: 10, lineHeight: 1.5 }}>{selectedNode.data.output}</div>
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
        .canvas-config .f-ta { min-height: 80px; }
        .canvas-config .f-input, .canvas-config .f-ta { font-size: 12px; padding: 7px 10px; }
        @media (prefers-reduced-motion: reduce) {
          .astra-palette-btn { transition: none !important; }
        }
      `}</style>
      <PageHeader
        title=""
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {runError && <span style={{ fontSize: 12, color: "var(--red)" }}>{runError}</span>}
            {savedTick && <span style={{ fontSize: 12, color: "var(--green)" }}>✓ Saved</span>}
            <HeaderSecondaryBtn label="Build with AI" onClick={() => setDraftOpen(true)} />
            <HeaderSecondaryBtn label={outputOpen ? "Hide output" : "Output"} onClick={() => setOutputOpen((o) => !o)} disabled={ranNodes.length === 0} />
            <HeaderSecondaryBtn label={saving ? "Saving…" : "Save"} onClick={() => { void saveFlow(); }} disabled={saving} />
            <HeaderPrimaryBtn label={running ? "Running…" : "▶ Run"} onClick={() => { void runFlow(); }} disabled={running || nodes.length === 0} />
          </div>
        }
      />
      <div style={{ padding: "8px 20px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 8, background: "var(--surface)" }}>
        <button onClick={() => router.push("/automations")} className="btn sm" style={{ flexShrink: 0, color: "var(--fm)" }}>← Automations</button>
        <span style={{ color: "var(--bd2)", fontSize: 14, flexShrink: 0 }}>/</span>
        <input value={flowName} onChange={(e) => setFlowName(e.target.value)} placeholder="Untitled automation" style={{ fontSize: 13, fontWeight: 600, border: "none", outline: "none", background: "transparent", color: "var(--fg)", flex: 1, minWidth: 60 }} />
      </div>
      <div style={{ display: "flex", flex: 1, minHeight: 0, position: "relative" }}>
        {!isMobile && (
          <div style={{ width: 260, borderRight: "1px solid var(--bd)", padding: 14, overflowY: "auto", flexShrink: 0, background: "var(--s2)" }}>
            {paletteBody}
          </div>
        )}

        <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
          {nodes.length === 0 && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 6, color: "var(--fm)", zIndex: 5, pointerEvents: "none", padding: 24, textAlign: "center" }}>
              <div style={{ fontSize: 28, opacity: 0.4 }}>⚡</div>
              <div style={{ fontSize: 13 }}>{isMobile ? "Tap + to add a block" : "Add a block from the left to get started"}</div>
            </div>
          )}
          <ReactFlow
            nodes={displayNodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            nodeTypes={nodeTypes} onNodeClick={(_, n) => setSelectedNodeId(n.id)} onPaneClick={() => setSelectedNodeId(null)}
            defaultEdgeOptions={{ type: "default", markerEnd: { type: MarkerType.ArrowClosed } }} fitView panOnScroll={isMobile} zoomOnPinch
          >
            <Background gap={18} color="var(--bd)" />
            <Controls showInteractive={false} />
            {!isMobile && <MiniMap pannable zoomable style={{ background: "var(--s2)" }} nodeColor={(n) => metaFor((n.data as AutomationNodeData).nodeType, (n.data as AutomationNodeData).category).color} />}
          </ReactFlow>
          {isMobile && (
            <button onClick={() => setPaletteOpen(true)} className="m-tap" style={{ position: "absolute", bottom: 20, right: 20, width: 52, height: 52, borderRadius: "50%", background: "var(--blue)", color: "#fff", border: "none", fontSize: 24, lineHeight: 1, boxShadow: "0 4px 14px rgba(0,46,255,0.35)", cursor: "pointer", zIndex: 10 }}>+</button>
          )}
          {outputOpen && (
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, maxHeight: "45%", background: "var(--surface)", borderTop: "1px solid var(--bd)", boxShadow: "0 -4px 16px rgba(0,0,0,0.08)", zIndex: 15, display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--fm)" }}>Run output</span>
                <button onClick={() => setOutputOpen(false)} className="btn sm">Close</button>
              </div>
              <div style={{ overflowY: "auto", padding: "10px 14px" }}>
                {ranNodes.length === 0 && <div style={{ fontSize: 12, color: "var(--fm)" }}>Run the flow to see what each block produced.</div>}
                {ranNodes.map((n) => (
                  <div key={n.id} style={{ marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <span style={{ width: 7, height: 7, borderRadius: "50%", background: STATUS_COLORS[n.data.status || ""] || "var(--fm)", flexShrink: 0 }} />
                      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--fg)" }}>{n.data.label}</span>
                      {leafIds.has(n.id) && <span className="pill blue">Final</span>}
                    </div>
                    {n.data.output ? (
                      <div style={{ fontSize: 12, color: "var(--fg)", whiteSpace: "pre-wrap", background: "var(--s2)", borderRadius: 8, padding: 10, lineHeight: 1.5 }}>{n.data.output}</div>
                    ) : (
                      <div style={{ fontSize: 11.5, color: "var(--fm)" }}>{n.data.status === "running" ? "Running…" : "No output."}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {!isMobile && selectedNode && (
          <div className="canvas-config" style={{ width: 256, borderLeft: "1px solid var(--bd)", padding: "14px 16px", overflowY: "auto", flexShrink: 0, background: "var(--s2)" }}>{configBody}</div>
        )}
        {isMobile && selectedNode && (
          <div style={{ position: "fixed", inset: 0, zIndex: 30, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.35)" }} onClick={() => setSelectedNodeId(null)} />
            <div className="canvas-config" style={{ position: "relative", background: "var(--surface)", borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 18, paddingBottom: 28, maxHeight: "80vh", overflowY: "auto", animation: "astra-sheet-up 0.22s cubic-bezier(0.22,1,0.36,1)", boxShadow: "0 -4px 24px rgba(0,0,0,0.18)" }}>
              <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--bd)", margin: "0 auto 14px" }} />
              {configBody}
            </div>
          </div>
        )}
        {isMobile && paletteOpen && (
          <div style={{ position: "fixed", inset: 0, zIndex: 30, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.35)" }} onClick={() => setPaletteOpen(false)} />
            <div style={{ position: "relative", background: "var(--surface)", borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 18, paddingBottom: 28, maxHeight: "75vh", overflowY: "auto", animation: "astra-sheet-up 0.22s cubic-bezier(0.22,1,0.36,1)", boxShadow: "0 -4px 24px rgba(0,0,0,0.18)" }}>
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
                className="f-ta"
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

const sectionLabelStyle: React.CSSProperties = { fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--fm)", marginBottom: 4 };
function tabStyle(active: boolean): React.CSSProperties {
  return {
    flex: 1, padding: "6px 8px", fontSize: 11, fontWeight: 600, borderRadius: 7, cursor: "pointer",
    border: active ? "1px solid #002EFF" : "1px solid var(--bd)",
    background: active ? "rgba(0,46,255,0.08)" : "transparent", color: active ? "#002EFF" : "var(--fm)",
  };
}

function CorePaletteButton({ type, onClick }: { type: Exclude<NodeType, "integration">; onClick: () => void }) {
  const meta = CORE_META[type];
  return (
    <button onClick={onClick} className="m-tap astra-palette-btn" style={{ width: "100%", textAlign: "left", padding: "10px 12px", marginBottom: 8, borderRadius: 10, border: `1px solid ${meta.border}`, background: meta.bg, cursor: "pointer", transition: "transform 0.12s ease, filter 0.12s ease" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 3 }}>
        <span style={{ fontSize: 13 }}>{meta.icon}</span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: meta.color }}>{meta.label}</span>
      </div>
      <div style={{ fontSize: 10.5, color: "var(--fm)", lineHeight: 1.4 }}>{meta.description}</div>
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

function integrationsByCategoryAll(catalog: IntegrationBlockMeta[]): Record<string, IntegrationBlockMeta[]> {
  const groups: Record<string, IntegrationBlockMeta[]> = {};
  for (const b of catalog) (groups[b.category] ||= []).push(b);
  return groups;
}
