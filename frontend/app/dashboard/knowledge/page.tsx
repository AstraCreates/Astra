"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useUser } from "@clerk/nextjs";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AGENT_COLORS: Record<string, string> = {
  research: "#5BE49B", web: "#38BDF8", marketing: "#FB923C",
  technical: "#A78BFA", legal: "#F87171", ops: "#FBBF24",
  sales: "#34D399", design: "#E879F9",
};
const AGENT_ICONS: Record<string, string> = {
  research: "🔬", web: "🌐", marketing: "📢", technical: "⚙️",
  legal: "⚖️", ops: "🚀", sales: "🤝", design: "🎨",
};

interface AgentNote { agent: string; summary: string; output_keys: string[]; }
interface VaultSession { session_id: string; goal: string; agents: AgentNote[]; note_count: number; }

interface GNode {
  id: string; type: "session" | "agent";
  label: string; sublabel?: string;
  agent?: string; sessionId?: string; summary?: string;
  x: number; y: number; vx: number; vy: number; r: number;
}
interface GEdge { source: string; target: string; cross: boolean; }

function buildGraph(sessions: VaultSession[], w: number, h: number): { nodes: GNode[]; edges: GEdge[] } {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const agentNodes: Record<string, string[]> = {};
  const cx = w / 2, cy = h / 2;
  const ringR = Math.min(w, h) * (sessions.length <= 1 ? 0 : sessions.length <= 3 ? 0.22 : 0.28);

  sessions.forEach((s, si) => {
    const angle = sessions.length === 1
      ? -Math.PI / 2
      : (si / sessions.length) * Math.PI * 2 - Math.PI / 2;
    const sx = cx + Math.cos(angle) * ringR + (Math.random() - 0.5) * 8;
    const sy = cy + Math.sin(angle) * ringR + (Math.random() - 0.5) * 8;
    const label = (s.goal || s.session_id).slice(0, 22) + ((s.goal?.length ?? 0) > 22 ? "…" : "");

    nodes.push({ id: s.session_id, type: "session", label, sublabel: `${s.note_count} notes`, x: sx, y: sy, vx: 0, vy: 0, r: 26 });

    s.agents.forEach((a, ai) => {
      const spread = Math.min(s.agents.length * 0.35, 1.4);
      const aAngle = angle + (s.agents.length > 1 ? (ai / (s.agents.length - 1) - 0.5) * spread : 0);
      const aR = 88 + (s.agents.length > 4 ? ai % 2 * 20 : 0);
      const nodeId = `${s.session_id}:${a.agent}`;
      nodes.push({
        id: nodeId, type: "agent", agent: a.agent, sessionId: s.session_id,
        label: AGENT_ICONS[a.agent] ?? "📄", sublabel: a.agent, summary: a.summary,
        x: sx + Math.cos(aAngle) * aR + (Math.random() - 0.5) * 6,
        y: sy + Math.sin(aAngle) * aR + (Math.random() - 0.5) * 6,
        vx: 0, vy: 0, r: 16,
      });
      edges.push({ source: s.session_id, target: nodeId, cross: false });
      if (!agentNodes[a.agent]) agentNodes[a.agent] = [];
      agentNodes[a.agent].push(nodeId);
    });
  });

  for (const ids of Object.values(agentNodes)) {
    for (let i = 0; i < ids.length - 1; i++) {
      edges.push({ source: ids[i], target: ids[i + 1], cross: true });
    }
  }
  return { nodes, edges };
}

function tick(nodes: GNode[], edges: GEdge[], w: number, h: number, pinned: string | null) {
  const cx = w / 2, cy = h / 2;
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if (a.id === pinned) continue;
    const grav = a.type === "session" ? 0.0025 : 0.0008;
    a.vx += (cx - a.x) * grav;
    a.vy += (cy - a.y) * grav;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      if (b.id === pinned) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx * dx + dy * dy || 1;
      const d = Math.sqrt(d2);
      const minD = (a.r + b.r) * 3;
      const f = d < minD ? (minD - d) / d * 0.55 : 900 / d2;
      a.vx -= dx * f * 0.5; a.vy -= dy * f * 0.5;
      b.vx += dx * f * 0.5; b.vy += dy * f * 0.5;
    }
  }
  for (const e of edges) {
    const a = nodeMap.get(e.source), b = nodeMap.get(e.target);
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const target = e.cross ? 160 : 90;
    const f = (d - target) / d * (e.cross ? 0.018 : 0.055);
    if (a.id !== pinned) { a.vx += dx * f; a.vy += dy * f; }
    if (b.id !== pinned) { b.vx -= dx * f; b.vy -= dy * f; }
  }
  for (const n of nodes) {
    if (n.id === pinned) continue;
    n.vx *= 0.80; n.vy *= 0.80;
    n.x = Math.max(n.r + 12, Math.min(w - n.r - 12, n.x + n.vx));
    n.y = Math.max(n.r + 12, Math.min(h - n.r - 12, n.y + n.vy));
  }
}

function drawGraph(ctx: CanvasRenderingContext2D, nodes: GNode[], edges: GEdge[], sel: string | null, hov: string | null, t: number) {
  const { width: cw, height: ch } = ctx.canvas;
  ctx.clearRect(0, 0, cw, ch);

  // Dot grid background
  ctx.fillStyle = "rgba(255,255,255,0.025)";
  const gs = 28;
  for (let x = gs / 2; x < cw; x += gs) {
    for (let y = gs / 2; y < ch; y += gs) {
      ctx.beginPath(); ctx.arc(x, y, 1, 0, Math.PI * 2); ctx.fill();
    }
  }

  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  // Edges
  ctx.setLineDash([]);
  for (const e of edges) {
    const a = nodeMap.get(e.source), b = nodeMap.get(e.target);
    if (!a || !b) continue;
    const active = a.id === sel || b.id === sel || a.id === hov || b.id === hov;
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - (e.cross ? 0 : 18);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo(mx, my, b.x, b.y);
    if (e.cross) {
      ctx.setLineDash([3, 7]);
      ctx.strokeStyle = active ? "rgba(139,168,200,0.45)" : "rgba(139,168,200,0.10)";
      ctx.lineWidth = 1;
    } else {
      ctx.setLineDash([]);
      ctx.strokeStyle = active ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.07)";
      ctx.lineWidth = active ? 1.8 : 1.2;
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Nodes
  for (const n of nodes) {
    const isSel = n.id === sel, isHov = n.id === hov;
    const color = n.type === "session" ? "#3B82F6" : (AGENT_COLORS[n.agent ?? ""] ?? "#94A3B8");
    const pulse = isSel ? Math.sin(t * 0.05) * 4 : 0;

    // Outer glow ring
    if (isSel || isHov) {
      const glowR = n.r + 14 + pulse;
      const grd = ctx.createRadialGradient(n.x, n.y, n.r - 2, n.x, n.y, glowR + 6);
      grd.addColorStop(0, color + "55");
      grd.addColorStop(1, "transparent");
      ctx.beginPath(); ctx.arc(n.x, n.y, glowR + 6, 0, Math.PI * 2);
      ctx.fillStyle = grd; ctx.fill();
    }

    // Node body gradient
    const grad = ctx.createRadialGradient(n.x - n.r * 0.3, n.y - n.r * 0.3, 1, n.x, n.y, n.r + pulse);
    grad.addColorStop(0, color + (isSel ? "ff" : isHov ? "dd" : "bb"));
    grad.addColorStop(1, color + (isSel ? "cc" : isHov ? "99" : "55"));
    ctx.beginPath(); ctx.arc(n.x, n.y, n.r + pulse, 0, Math.PI * 2);
    ctx.fillStyle = grad; ctx.fill();

    // Border
    ctx.strokeStyle = color + (isSel ? "ff" : isHov ? "cc" : "66");
    ctx.lineWidth = isSel ? 2 : 1.5;
    ctx.stroke();

    // Inner highlight
    ctx.beginPath(); ctx.arc(n.x - n.r * 0.25, n.y - n.r * 0.3, n.r * 0.35, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.12)"; ctx.fill();

    // Label
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    if (n.type === "agent") {
      ctx.font = `${Math.round(n.r * 1.05)}px sans-serif`;
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillText(n.label, n.x, n.y);
    } else {
      const words = n.label.split(" ");
      const half = Math.ceil(words.length / 2);
      const l1 = words.slice(0, half).join(" "), l2 = words.slice(half).join(" ");
      ctx.font = `600 ${Math.max(8, n.r * 0.52)}px system-ui`;
      ctx.fillStyle = "rgba(255,255,255,0.95)";
      if (l2) { ctx.fillText(l1, n.x, n.y - 6); ctx.fillText(l2, n.x, n.y + 7); }
      else ctx.fillText(l1, n.x, n.y);
    }

    // Sublabel on hover/select
    if ((isHov || isSel) && n.sublabel) {
      ctx.font = `10px system-ui`;
      ctx.fillStyle = "rgba(255,255,255,0.45)";
      ctx.fillText(n.sublabel, n.x, n.y + n.r + pulse + 13);
    }
  }
}

export default function KnowledgePage() {
  const { user } = useUser();
  const [sessions, setSessions] = useState<VaultSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"graph" | "notes">("graph");
  const [selected, setSelected] = useState<{ node: GNode; content?: string } | null>(null);
  const [loadingNote, setLoadingNote] = useState(false);
  const [activeListSession, setActiveListSession] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<GNode[]>([]);
  const edgesRef = useRef<GEdge[]>([]);
  const selIdRef = useRef<string | null>(null);
  const hovIdRef = useRef<string | null>(null);
  const pinnedIdRef = useRef<string | null>(null);
  const dragRef = useRef<{ id: string; startX: number; startY: number } | null>(null);
  const rafRef = useRef<number>(0);
  const frameRef = useRef(0);
  const dimRef = useRef({ w: 0, h: 0 });

  const founderId = user?.id ?? "founder_001";

  const loadVault = useCallback(async (isRefresh = false) => {
    if (!user) return;
    if (isRefresh) setRefreshing(true); else setLoading(true);
    try {
      const d = await fetch(`${BASE}/vault/${founderId}`).then(r => r.json());
      setSessions(d.sessions ?? []);
    } catch { /* ignore */ }
    finally { setLoading(false); setRefreshing(false); }
  }, [user, founderId]);

  useEffect(() => { loadVault(); }, [loadVault]);

  const initGraph = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || sessions.length === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width, h = rect.height;
    dimRef.current = { w, h };
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.getContext("2d")!.scale(dpr, dpr);
    const { nodes, edges } = buildGraph(sessions, w, h);
    nodesRef.current = nodes; edgesRef.current = edges;
    frameRef.current = 0;
  }, [sessions]);

  useEffect(() => {
    if (tab !== "graph") return;
    initGraph();
  }, [tab, sessions, initGraph]);

  useEffect(() => {
    if (tab !== "graph") { cancelAnimationFrame(rafRef.current); return; }
    const canvas = canvasRef.current;
    if (!canvas) return;

    function loop() {
      const ctx = canvas!.getContext("2d");
      if (!ctx) return;
      const { w, h } = dimRef.current;
      if (frameRef.current < 280) {
        tick(nodesRef.current, edgesRef.current, w, h, pinnedIdRef.current);
        frameRef.current++;
      }
      drawGraph(ctx, nodesRef.current, edgesRef.current, selIdRef.current, hovIdRef.current, frameRef.current);
      rafRef.current = requestAnimationFrame(loop);
    }
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [tab, sessions]);

  function getNodeAt(x: number, y: number): GNode | null {
    for (const n of [...nodesRef.current].reverse()) {
      const dx = n.x - x, dy = n.y - y;
      if (dx * dx + dy * dy <= (n.r + 6) * (n.r + 6)) return n;
    }
    return null;
  }

  async function selectNode(n: GNode) {
    selIdRef.current = n.id;
    frameRef.current = Math.max(frameRef.current, 200); // keep pulse running
    if (n.type === "agent" && n.sessionId && n.agent) {
      setLoadingNote(true);
      setSelected({ node: n });
      try {
        const r = await fetch(`${BASE}/vault/${founderId}/note?session_id=${n.sessionId}&agent=${n.agent}`);
        if (r.ok) { const d = await r.json(); setSelected({ node: n, content: d.content }); }
      } catch { /* keep node selected */ }
      finally { setLoadingNote(false); }
    } else {
      setSelected({ node: n });
    }
  }

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    if (dragRef.current) {
      const n = nodesRef.current.find(n => n.id === dragRef.current!.id);
      if (n) { n.x = x; n.y = y; n.vx = 0; n.vy = 0; frameRef.current = 0; }
      return;
    }
    const n = getNodeAt(x, y);
    hovIdRef.current = n?.id ?? null;
    (e.target as HTMLCanvasElement).style.cursor = n ? "pointer" : "grab";
  }

  function onMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    const n = getNodeAt(x, y);
    if (n) {
      dragRef.current = { id: n.id, startX: x, startY: y };
      pinnedIdRef.current = n.id;
    }
  }

  function onMouseUp(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!dragRef.current) return;
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    const wasDrag = Math.abs(x - dragRef.current.startX) > 5 || Math.abs(y - dragRef.current.startY) > 5;
    if (!wasDrag) {
      const n = getNodeAt(x, y);
      if (n) selectNode(n);
    }
    dragRef.current = null;
    pinnedIdRef.current = null;
  }

  function clearSelection() {
    setSelected(null); selIdRef.current = null;
  }

  const totalNotes = sessions.reduce((s, ss) => s + ss.note_count, 0);

  return (
    <div style={{ height: "calc(100vh - 64px)", display: "flex", flexDirection: "column", gap: 0 }}>
      {/* Header */}
      <div style={{ paddingBottom: 14, display: "flex", alignItems: "center", gap: 14, flexShrink: 0 }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Knowledge</h1>
          <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: "2px 0 0" }}>
            {sessions.length} sessions · {totalNotes} agent notes
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => loadVault(true)}
            disabled={refreshing}
            style={{
              padding: "5px 12px", borderRadius: 7, border: "1px solid rgba(255,255,255,0.10)",
              background: "rgba(255,255,255,0.04)", color: refreshing ? "rgba(255,255,255,0.25)" : "rgba(255,255,255,0.55)",
              fontSize: 11, cursor: refreshing ? "default" : "pointer", display: "flex", alignItems: "center", gap: 5,
            }}
          >
            <span style={{ display: "inline-block", animation: refreshing ? "spin 1s linear infinite" : "none" }}>↻</span>
            Sync vault
          </button>
          <div style={{ display: "flex", gap: 3, padding: "3px", borderRadius: 7, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}>
            {(["graph", "notes"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                padding: "4px 12px", borderRadius: 5, border: "none", cursor: "pointer",
                fontSize: 11, fontWeight: 500, textTransform: "capitalize" as const,
                background: tab === t ? "rgba(255,255,255,0.10)" : "transparent",
                color: tab === t ? "var(--fg)" : "var(--fg-mute)", transition: "all 0.15s",
              }}>{t}</button>
            ))}
          </div>
        </div>
      </div>

      {(loading) && (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(255,255,255,0.18)", fontSize: 13 }}>
          <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "#3B82F6", marginRight: 10, animation: "pulse 1.2s ease-in-out infinite" }} />
          Loading vault…
        </div>
      )}

      {!loading && sessions.length === 0 && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, color: "rgba(255,255,255,0.15)" }}>
          <span style={{ fontSize: 32 }}>🕸</span>
          <p style={{ margin: 0, fontSize: 13 }}>No knowledge yet — run a goal to populate the graph.</p>
        </div>
      )}

      {/* Graph */}
      {!loading && sessions.length > 0 && tab === "graph" && (
        <div style={{ flex: 1, display: "flex", gap: 12, minHeight: 0 }}>
          <div style={{
            flex: 1, position: "relative", borderRadius: 16, overflow: "hidden",
            border: "1px solid rgba(255,255,255,0.07)",
            background: "rgba(8,10,18,0.85)",
          }}>
            {/* Legend */}
            <div style={{ position: "absolute", top: 12, left: 14, display: "flex", flexWrap: "wrap", gap: "6px 14px", zIndex: 10, maxWidth: "60%" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "rgba(255,255,255,0.35)" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#3B82F6", display: "inline-block", flexShrink: 0 }} />
                session
              </span>
              {Object.entries(AGENT_COLORS).map(([a, c]) => (
                <span key={a} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "rgba(255,255,255,0.30)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: c, display: "inline-block", flexShrink: 0 }} />
                  {a}
                </span>
              ))}
            </div>
            {/* Hint */}
            <div style={{ position: "absolute", bottom: 12, left: 0, right: 0, textAlign: "center", fontSize: 10, color: "rgba(255,255,255,0.12)", pointerEvents: "none" }}>
              drag · click to inspect · dashed lines = cross-session agent continuity
            </div>
            <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block", cursor: "grab" }}
              onMouseMove={onMouseMove} onMouseDown={onMouseDown} onMouseUp={onMouseUp}
              onMouseLeave={() => { hovIdRef.current = null; dragRef.current = null; pinnedIdRef.current = null; }} />
          </div>

          {/* Detail panel */}
          {selected && (
            <div style={{
              width: 296, flexShrink: 0, borderRadius: 16,
              border: "1px solid rgba(255,255,255,0.10)",
              background: "rgba(10,13,22,0.96)",
              backdropFilter: "blur(40px) saturate(180%)",
              display: "flex", flexDirection: "column", overflow: "hidden",
              boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
            }}>
              {/* Panel header */}
              <div style={{ padding: "13px 15px", borderBottom: "1px solid rgba(255,255,255,0.07)", display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{
                  width: 32, height: 32, borderRadius: 9, flexShrink: 0,
                  background: selected.node.type === "agent"
                    ? (AGENT_COLORS[selected.node.agent ?? ""] ?? "#94A3B8") + "22"
                    : "#3B82F622",
                  border: `1px solid ${selected.node.type === "agent" ? (AGENT_COLORS[selected.node.agent ?? ""] ?? "#94A3B8") : "#3B82F6"}33`,
                  display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16,
                }}>
                  {selected.node.type === "agent" ? (AGENT_ICONS[selected.node.agent ?? ""] ?? "📄") : "🎯"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {selected.node.type === "agent" ? selected.node.agent : "Session"}
                  </p>
                  <p style={{ margin: "1px 0 0", fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {selected.node.sessionId?.slice(0, 12) ?? selected.node.id.slice(0, 12)}
                  </p>
                </div>
                <button onClick={clearSelection} style={{ background: "none", border: "none", color: "rgba(255,255,255,0.25)", fontSize: 15, cursor: "pointer", padding: "2px 4px", lineHeight: 1 }}>✕</button>
              </div>

              <div style={{ flex: 1, overflowY: "auto", padding: "12px 15px", display: "flex", flexDirection: "column", gap: 10 }}>
                {loadingNote && (
                  <p style={{ fontSize: 11, color: "rgba(255,255,255,0.25)", margin: 0 }}>Loading note…</p>
                )}

                {/* Session: list agents */}
                {selected.node.type === "session" && (() => {
                  const sess = sessions.find(s => s.session_id === selected.node.id);
                  return sess ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      <p style={{ margin: "0 0 4px", fontSize: 11, color: "var(--fg-mute)", fontWeight: 500 }}>Goal</p>
                      <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--fg)", lineHeight: 1.5 }}>{sess.goal}</p>
                      <p style={{ margin: "0 0 4px", fontSize: 11, color: "var(--fg-mute)", fontWeight: 500 }}>Agents</p>
                      {sess.agents.map(a => (
                        <button key={a.agent}
                          onClick={() => { const n = nodesRef.current.find(n => n.id === `${sess.session_id}:${a.agent}`); if (n) selectNode(n); }}
                          style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 10px", borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", cursor: "pointer", textAlign: "left" }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: AGENT_COLORS[a.agent] ?? "#888", flexShrink: 0 }} />
                          <span style={{ fontSize: 11, color: "var(--fg)", flex: 1 }}>{AGENT_ICONS[a.agent]} {a.agent}</span>
                          <span style={{ fontSize: 9, color: "rgba(255,255,255,0.2)" }}>view ↗</span>
                        </button>
                      ))}
                    </div>
                  ) : null;
                })()}

                {/* Agent: summary + note */}
                {selected.node.type === "agent" && !selected.content && selected.node.summary && (
                  <div>
                    <p style={{ margin: "0 0 6px", fontSize: 11, color: "var(--fg-mute)", fontWeight: 500 }}>Summary</p>
                    <p style={{ margin: 0, fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.6 }}>{selected.node.summary}</p>
                  </div>
                )}
                {selected.content && (
                  <div>
                    <p style={{ margin: "0 0 6px", fontSize: 11, color: "var(--fg-mute)", fontWeight: 500 }}>Session note</p>
                    <pre style={{ margin: 0, fontSize: 10, color: "var(--fg-dim)", lineHeight: 1.75, whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", wordBreak: "break-word" }}>
                      {selected.content}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Notes list */}
      {!loading && sessions.length > 0 && tab === "notes" && (
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          {sessions.map(session => {
            const isOpen = activeListSession === session.session_id;
            return (
              <div key={session.session_id} style={{
                borderRadius: 12, overflow: "hidden",
                border: "1px solid rgba(255,255,255,0.07)",
                background: "rgba(255,255,255,0.03)",
              }}>
                <button onClick={() => setActiveListSession(isOpen ? null : session.session_id)}
                  style={{ width: "100%", display: "flex", alignItems: "center", gap: 12, padding: "11px 16px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
                  <span style={{ fontSize: 10, color: isOpen ? "#8BA8C8" : "rgba(255,255,255,0.2)", fontFamily: "var(--font-mono)" }}>{isOpen ? "▾" : "▸"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {session.goal || session.session_id}
                    </p>
                    <p style={{ margin: "1px 0 0", fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{session.session_id}</p>
                  </div>
                  <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 999, background: "rgba(255,255,255,0.05)", color: "var(--fg-mute)", border: "1px solid rgba(255,255,255,0.07)", fontFamily: "var(--font-mono)", flexShrink: 0 }}>
                    {session.note_count}
                  </span>
                </button>
                {isOpen && (
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", padding: "8px 12px", display: "flex", flexDirection: "column", gap: 5 }}>
                    {session.agents.map(note => (
                      <div key={note.agent}
                        onClick={() => { setTab("graph"); setTimeout(() => { const n = nodesRef.current.find(n => n.id === `${session.session_id}:${note.agent}`); if (n) selectNode(n); }, 50); }}
                        style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 11px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer" }}>
                        <span style={{ fontSize: 15, flexShrink: 0, lineHeight: 1.2 }}>{AGENT_ICONS[note.agent] ?? "📄"}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ fontSize: 11, fontWeight: 500, color: "var(--fg)" }}>{note.agent}</span>
                          {note.summary && <p style={{ margin: "2px 0 0", fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as const, overflow: "hidden" }}>{note.summary}</p>}
                        </div>
                        <span style={{ fontSize: 9, color: "rgba(255,255,255,0.18)", flexShrink: 0, paddingTop: 2 }}>graph ↗</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } } @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }`}</style>
    </div>
  );
}
