"use client";

import { useMemo, useRef, useState } from "react";
import {
  forceSimulation, forceManyBody, forceLink, forceCenter, forceCollide,
  type SimulationNodeDatum, type SimulationLinkDatum,
} from "d3-force";
import type { CompanyHomeSquad, CompanyHomeBrain } from "@/lib/company-os";

const BRAIN_NODE_ID = "__brain__";

const LIFECYCLE_COLOR: Record<string, string> = {
  active: "var(--accent)", working: "var(--accent)",
  done: "var(--green)", complete: "var(--green)",
  blocked: "var(--red)", waiting: "var(--amber)", review: "var(--amber)",
};

function lifecycleColor(lifecycle: string): string {
  return LIFECYCLE_COLOR[lifecycle.toLowerCase()] ?? "var(--fm)";
}

type GraphNode = { id: string; label: string; radius: number; color: string; isBrain: boolean; x: number; y: number };
type GraphEdge = { id: string; source: string; target: string; weight: number };

export default function SquadGraph({
  squads, brain, selectedSquadId, onSelectSquad,
}: {
  squads: CompanyHomeSquad[];
  brain: CompanyHomeBrain;
  selectedSquadId: string;
  onSelectSquad: (squadId: string) => void;
}) {
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const panRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setView(v => ({ ...v, scale: Math.min(4, Math.max(0.4, v.scale * (e.deltaY < 0 ? 1.12 : 0.89))) }));
  };
  const onDown = (e: React.MouseEvent) => { panRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty }; };
  const onMove = (e: React.MouseEvent) => {
    if (!panRef.current) return;
    setView(v => ({ ...v, tx: panRef.current!.tx + (e.clientX - panRef.current!.x), ty: panRef.current!.ty + (e.clientY - panRef.current!.y) }));
  };
  const onUp = () => { panRef.current = null; };

  const hasBrainLinks = brain.squadLinks.length > 0;

  // Real force-directed layout (d3-force), same technique already proven in
  // CompanyBrainPage.tsx's KnowledgeMap for the GraphRAG entity graph -- run
  // to convergence once and freeze positions, not a continuously-animating
  // physics loop, since this is a page people glance at repeatedly rather
  // than drag-to-rearrange.
  const layout = useMemo(() => {
    const width = Math.max(640, Math.round(140 * Math.sqrt(Math.max(1, squads.length + 1))));
    const height = Math.round(width * 0.6);

    type SimNode = GraphNode & SimulationNodeDatum;
    const simNodes: SimNode[] = squads.map((squad, i) => {
      const seedAngle = (i / Math.max(1, squads.length)) * Math.PI * 2;
      return {
        id: squad.id, label: squad.name, isBrain: false,
        color: lifecycleColor(squad.lifecycle),
        radius: 34,
        x: width / 2 + Math.cos(seedAngle) * (width * 0.28),
        y: height / 2 + Math.sin(seedAngle) * (height * 0.28),
      };
    });
    if (hasBrainLinks) {
      simNodes.push({ id: BRAIN_NODE_ID, label: "Company Brain", isBrain: true, color: "var(--accent)", radius: 44, x: width / 2, y: height / 2 });
    }

    const nodeIds = new Set(simNodes.map(n => n.id));
    const simEdges: GraphEdge[] = [];
    for (const squad of squads) {
      for (const fromId of squad.handoffFromSquadIds) {
        if (nodeIds.has(fromId)) simEdges.push({ id: `handoff-${fromId}-${squad.id}`, source: fromId, target: squad.id, weight: 1 });
      }
    }
    if (hasBrainLinks) {
      for (const link of brain.squadLinks) {
        if (nodeIds.has(link.squadId)) simEdges.push({ id: `brain-${link.squadId}`, source: link.squadId, target: BRAIN_NODE_ID, weight: link.recordCount });
      }
    }

    const degree = new Map<string, number>();
    for (const edge of simEdges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }

    const simulation = forceSimulation(simNodes as unknown as SimulationNodeDatum[])
      .force("link", forceLink(simEdges as unknown as SimulationLinkDatum<SimulationNodeDatum>[])
        .id((d: any) => d.id)
        .distance(130))
      .force("charge", forceManyBody().strength((d: any) => -420 - (degree.get(d.id) || 0) * 20))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide((d: any) => d.radius + 24))
      .stop();
    for (let i = 0; i < 350; i++) simulation.tick();

    // The physics has no knowledge of the viewBox -- with few nodes and a
    // weak forceCenter vs. strong charge repulsion, the converged layout can
    // drift (or a single/degenerate case can sit dead-center) well outside
    // width/height and get clipped. Re-fit the whole result into the frame
    // (with room for radius + label) instead of trusting raw sim coordinates.
    const pad = 70;
    const xs = simNodes.map(n => n.x ?? 0);
    const ys = simNodes.map(n => n.y ?? 0);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = maxX - minX, spanY = maxY - minY;
    const availW = Math.max(1, width - pad * 2), availH = Math.max(1, height - pad * 2);
    const fitScale = Math.min(1, spanX > 0 ? availW / spanX : 1, spanY > 0 ? availH / spanY : 1);
    const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
    for (const node of simNodes) {
      node.x = width / 2 + (( node.x ?? 0) - midX) * fitScale;
      node.y = height / 2 + ((node.y ?? 0) - midY) * fitScale;
    }

    const positions = new Map<string, GraphNode>();
    for (const node of simNodes) positions.set(node.id, node);
    return { width, height, positions, edges: simEdges };
  }, [squads, brain.squadLinks, hasBrainLinks]);

  if (squads.length === 0) {
    return (
      <div className="empty" style={{ minHeight: 280 }}>
        <div className="empty-title">No squads yet</div>
        <p style={{ margin: 0, fontSize: 12 }}>Squads will appear here once the copilot dispatches work.</p>
      </div>
    );
  }

  return (
    <div style={{ border: "1px solid var(--bd)", borderRadius: "var(--radius-lg)", background: "var(--bg-surface)", overflow: "hidden" }}>
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="Squad graph"
        style={{ width: "100%", height: 380, display: "block", cursor: panRef.current ? "grabbing" : "grab", touchAction: "none" }}
        onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
        <rect width={layout.width} height={layout.height} fill="rgba(0,0,0,0.02)" />
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
          {layout.edges.map(edge => {
            const src = layout.positions.get(edge.source);
            const tgt = layout.positions.get(edge.target);
            if (!src || !tgt) return null;
            const active = selectedSquadId === edge.source || selectedSquadId === edge.target;
            return (
              <line key={edge.id} x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={active ? "rgba(0,46,255,0.55)" : "rgba(0,0,0,0.12)"}
                strokeWidth={active ? Math.min(3.5, 1.4 + edge.weight * 0.4) : Math.min(2.5, 0.8 + edge.weight * 0.3)} />
            );
          })}
          {Array.from(layout.positions.values()).map(node => {
            const active = selectedSquadId === node.id;
            return (
              <g key={node.id} transform={`translate(${node.x} ${node.y})`}
                onClick={() => !node.isBrain && onSelectSquad(node.id)}
                style={{ cursor: node.isBrain ? "default" : "pointer" }}>
                <circle r={node.radius + (active ? 6 : 3)} fill={active ? "rgba(0,46,255,0.12)" : "rgba(0,0,0,0.04)"} />
                <circle r={node.radius} fill="var(--bg-surface)" stroke={active ? "#002EFF" : node.color} strokeWidth={active ? 2.5 : 1.5} />
                <text y={-4} textAnchor="middle" fill="var(--fg)" fontSize={node.isBrain ? 11 : 10.5} fontWeight={700}
                  style={{ paintOrder: "stroke", stroke: "var(--bg-surface)", strokeWidth: 3 }}>
                  {node.isBrain ? "🧠" : node.label.slice(0, 16)}
                </text>
                {!node.isBrain && <text y={10} textAnchor="middle" fill="var(--fm)" fontSize={9}
                  style={{ paintOrder: "stroke", stroke: "var(--bg-surface)", strokeWidth: 3 }}>
                  {node.label.length > 16 ? `${node.label.slice(0, 16)}…` : ""}
                </text>}
              </g>
            );
          })}
        </g>
      </svg>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "8px 12px", borderTop: "1px solid var(--bd)", fontSize: 10.5, color: "var(--fm)" }}>
        <span>scroll to zoom · drag to pan · click a squad to select it</span>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.min(4, v.scale * 1.2) }))} className="btn sm">+</button>
          <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.max(0.4, v.scale * 0.83) }))} className="btn sm">−</button>
          <button type="button" onClick={() => setView({ scale: 1, tx: 0, ty: 0 })} className="btn sm">Reset</button>
        </div>
      </div>
    </div>
  );
}
