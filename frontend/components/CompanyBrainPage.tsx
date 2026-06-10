"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import {
  addCompanyBrainRecord,
  askCompanyBrain,
  configureCompanyBrainSync,
  getCompanyBrain,
  getCompanyBrainSchedulerStatus,
  getGraphRagVisualization,
  importCompanyBrainSources,
  maintainCompanyBrain,
  runCompanyBrainSync,
  saveServiceCredential,
  searchCompanyBrain,
  syncCompanyBrain,
  syncGraphRag,
  updateBrainProposal,
  type BrainProposal,
  type BrainRecord,
  type BrainAnswerCitation,
  type BrainSchedulerState,
  type BrainSource,
  type CompanyBrain,
  type GraphRagVisualization,
} from "@/lib/api";

/* ─── helpers ─── */

const DEFAULT_QUERY = "decisions product roadmap code customers";

const SOURCE_ORDER = [
  "discord", "slack", "github", "linear", "notion",
  "google_drive", "google_workspace", "gmail",
  "confluence", "zendesk", "granola", "astra_vault",
];

type Tab = "ask" | "graph" | "sources" | "memory" | "settings";

function statusColor(status: string): string {
  if (status === "connected") return "#3D9E5F";
  if (status === "oauth_ready") return "#002EFF";
  if (status === "planned") return "#C58B37";
  return "var(--fm)";
}

function formatStatus(status: string): string {
  return status.replace(/_/g, " ");
}

/* ─── sub-components ─── */

function SourceCard({
  source, active, focused, onToggle,
}: {
  source: BrainSource;
  active: boolean;
  focused: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        minHeight: 100,
        textAlign: "left",
        border: focused
          ? "1px solid var(--blue)"
          : active
            ? "1px solid rgba(124,255,198,0.35)"
            : "1px solid var(--bd2)",
        background: focused
          ? "rgba(0,46,255,0.07)"
          : active
            ? "rgba(124,255,198,0.06)"
            : "var(--surface)",
        padding: "12px 13px",
        display: "flex",
        flexDirection: "column",
        gap: 7,
        color: "var(--fg)",
        cursor: "pointer",
        transition: "all .12s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {source.label}
        </span>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: statusColor(source.status), flexShrink: 0 }} />
      </div>
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        <span className="pill" style={{ letterSpacing: 0 }}>{source.kind}</span>
        <span className="pill" style={{ letterSpacing: 0 }}>{source.record_count}</span>
      </div>
      <p style={{ margin: "auto 0 0", color: "var(--fm)", fontSize: 10, lineHeight: 1.4 }}>
        {formatStatus(source.status)}{source.importer === false ? " · planned" : ""}
      </p>
    </button>
  );
}

function SourceConnectionPanel({
  source, values, saving, onChange, onSave,
}: {
  source: BrainSource | null;
  values: Record<string, string>;
  saving: boolean;
  onChange: (field: string, value: string) => void;
  onSave: () => void;
}) {
  if (!source) {
    return (
      <div style={{ border: "1px solid var(--bd)", background: "var(--s2)", padding: "14px 16px", color: "var(--fm)", fontSize: 12 }}>
        Select a source to configure its connection.
      </div>
    );
  }
  const fields = source.credential_fields ?? [];
  const canSave = fields.length > 0 && fields.every(f => values[f]?.trim());
  return (
    <div style={{ border: "1px solid var(--bd2)", background: "var(--s2)", padding: "16px", display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{source.label}</span>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: statusColor(source.status) }} />
        <span style={{ color: "var(--fm)", fontSize: 11 }}>{formatStatus(source.status)}</span>
        {(source.status === "connected" || source.status === "oauth_ready") && (
          <span style={{ marginLeft: "auto", color: "#3D9E5F", fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Connected
          </span>
        )}
      </div>
      <p style={{ color: "var(--fd)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>
        {source.notes || source.setup_hint || "Ready to connect."}
      </p>
      {source.setup_hint && source.notes !== source.setup_hint && (
        <p style={{ color: "var(--fm)", fontSize: 11, lineHeight: 1.45, margin: 0 }}>{source.setup_hint}</p>
      )}
      {source.setup_url && (
        <a href={source.setup_url} target="_blank" rel="noopener noreferrer"
          style={{ color: "var(--blue)", fontSize: 11, width: "fit-content" }}>
          Setup docs →
        </a>
      )}
      {fields.length > 0 && (
        <div style={{ display: "grid", gap: 8 }}>
          {fields.map(field => (
            <input
              key={field}
              className="f-input"
              value={values[field] ?? ""}
              onChange={e => onChange(field, e.target.value)}
              placeholder={field}
              type={field.includes("token") || field.includes("key") || field.includes("secret") ? "password" : "text"}
            />
          ))}
          <button type="button" onClick={onSave} disabled={saving || !canSave} className="btn pri" style={{ minHeight: 34, fontSize: 12 }}>
            {saving ? "Saving..." : "Save credentials"}
          </button>
        </div>
      )}
      {fields.length === 0 && source.importer === false && (
        <div style={{ color: "var(--fm)", fontSize: 11, padding: "10px 12px", background: "var(--surface)", border: "1px solid var(--bd)" }}>
          Direct import is not implemented yet for this source. Manual records can still reference it.
        </div>
      )}
    </div>
  );
}

function RecordRow({ record }: { record: BrainRecord }) {
  return (
    <div style={{ border: "1px solid var(--bd)", background: "var(--surface)", padding: "12px 14px", display: "grid", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <span className="pill" style={{ letterSpacing: 0 }}>{record.source}</span>
        <span style={{ color: record.canonical ? "#3D9E5F" : "var(--fm)", fontSize: 10, fontWeight: record.canonical ? 700 : 400 }}>
          {record.canonical ? "canonical" : record.kind}
        </span>
        {record.domain && <span style={{ color: "var(--fm)", fontSize: 10 }}>{record.domain}</span>}
        <span style={{ marginLeft: "auto", color: "var(--fm)", fontSize: 10 }}>{record.stale_risk} drift</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{record.title}</div>
      <p style={{ color: "var(--fd)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>
        {(record.snippet ?? record.content).slice(0, 360)}
      </p>
      {record.url && (
        <a href={record.url.startsWith("/") ? undefined : record.url} target="_blank" rel="noopener noreferrer"
          style={{ color: "var(--blue)", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {record.url}
        </a>
      )}
    </div>
  );
}

function ProposalCard({
  proposal, recordsById, onUpdate,
}: {
  proposal: BrainProposal;
  recordsById: Map<string, BrainRecord>;
  onUpdate: (id: string, status: "resolved" | "dismissed") => void;
}) {
  const linked = proposal.record_ids.map(id => recordsById.get(id)).filter(Boolean) as BrainRecord[];
  return (
    <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", padding: "13px 14px", display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="pill" style={{ letterSpacing: 0 }}>{proposal.kind.replace(/_/g, " ")}</span>
        <span style={{ color: "#C58B37", fontSize: 10, fontWeight: 700 }}>{proposal.status}</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{proposal.title}</div>
      <p style={{ color: "var(--fd)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>{proposal.reason}</p>
      <p style={{ color: "var(--fm)", fontSize: 11, lineHeight: 1.45, margin: 0 }}>{proposal.suggested_update}</p>
      {linked.length > 0 && (
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
          {linked.map(r => (
            <span key={r.id} className="pill" style={{ letterSpacing: 0 }}>{r.source}: {r.title.slice(0, 26)}</span>
          ))}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 7 }}>
        <button type="button" onClick={() => onUpdate(proposal.id, "dismissed")} className="btn" style={{ minHeight: 30, fontSize: 11 }}>Dismiss</button>
        <button type="button" onClick={() => onUpdate(proposal.id, "resolved")} className="btn pri" style={{ minHeight: 30, fontSize: 11 }}>Mark resolved</button>
      </div>
    </div>
  );
}

const GRAPH_COLORS = ["#002EFF", "#3D9E5F", "#C58B37", "#B45EA4", "#0F766E", "#DC2626", "#7C3AED", "#64748B"];

function GraphRagPanel({
  graph, loading, rebuilding, onReload, onRebuild,
}: {
  graph: GraphRagVisualization | null;
  loading: boolean;
  rebuilding: boolean;
  onReload: () => void;
  onRebuild: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Zoom / pan view transform for an interactive map.
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
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = useMemo(() => graph?.edges ?? [], [graph]);
  const visibleNodes = useMemo(() => nodes.slice(0, 80), [nodes]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map(n => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter(e => visibleIds.has(e.source) && visibleIds.has(e.target)).slice(0, 180),
    [edges, visibleIds]
  );
  const selected = visibleNodes.find(n => n.id === selectedId) ?? visibleNodes[0] ?? null;
  const layout = useMemo(() => {
    const width = 720;
    const height = 360;
    const cx = width / 2;
    const cy = height / 2;
    const communities = Array.from(new Set(visibleNodes.map(n => n.community_id || "unassigned")));
    const positions = new Map<string, { x: number; y: number; color: string; radius: number }>();
    visibleNodes.forEach((node, i) => {
      const ci = Math.max(0, communities.indexOf(node.community_id || "unassigned"));
      const ba = (ci / Math.max(1, communities.length)) * Math.PI * 2;
      const la = ba + ((i % 13) - 6) * 0.105 + (Math.floor(i / 13) * 0.035);
      const ring = 78 + (ci % 3) * 54 + (i % 5) * 10;
      const imp = Number(node.importance || 1);
      positions.set(node.id, {
        x: cx + Math.cos(la) * ring,
        y: cy + Math.sin(la) * ring * 0.72,
        color: GRAPH_COLORS[ci % GRAPH_COLORS.length],
        radius: Math.max(5, Math.min(15, 5 + imp * 1.4)),
      });
    });
    return { width, height, positions };
  }, [visibleNodes]);
  const topEntities = useMemo(
    () => [...nodes].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0)).slice(0, 8),
    [nodes]
  );

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 650, color: "var(--fg)" }}>GraphRAG entity map</div>
          <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 2 }}>
            {nodes.length} entities · {edges.length} relationships · {new Set(nodes.map(n => n.community_id || "unassigned")).size} communities
          </div>
        </div>
        <div style={{ display: "flex", gap: 7 }}>
          <button type="button" onClick={onReload} disabled={loading || rebuilding} className="btn" style={{ minHeight: 32, fontSize: 11 }}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button type="button" onClick={onRebuild} disabled={rebuilding} className="btn pri" style={{ minHeight: 32, fontSize: 11 }}>
            {rebuilding ? "Rebuilding..." : "Rebuild graph"}
          </button>
        </div>
      </div>

      <div style={{ border: "1px solid var(--bd)", background: "var(--surface)", overflow: "hidden" }}>
        {visibleNodes.length === 0 ? (
          <div style={{ minHeight: 280, display: "grid", placeItems: "center", padding: 18, color: "var(--fm)", fontSize: 12, textAlign: "center" }}>
            Add records, then rebuild to create the entity map.
          </div>
        ) : (
          <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="GraphRAG entity map"
            style={{ width: "100%", height: 320, display: "block", cursor: panRef.current ? "grabbing" : "grab", touchAction: "none" }}
            onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
            <rect width={layout.width} height={layout.height} fill="rgba(0,0,0,0.02)" />
            <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
            {visibleEdges.map(edge => {
              const src = layout.positions.get(edge.source);
              const tgt = layout.positions.get(edge.target);
              if (!src || !tgt) return null;
              const active = selectedId === edge.source || selectedId === edge.target;
              return (
                <line key={edge.id}
                  x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                  stroke={active ? "rgba(0,46,255,0.6)" : "rgba(0,0,0,0.10)"}
                  strokeWidth={active ? Math.min(3, 1.2 + Number(edge.weight || 1)) : Math.min(2, 0.6 + Number(edge.weight || 1) * 0.35)}
                />
              );
            })}
            {visibleNodes.map(node => {
              const pos = layout.positions.get(node.id);
              if (!pos) return null;
              const active = selected?.id === node.id;
              return (
                <g key={node.id} transform={`translate(${pos.x} ${pos.y})`}
                  onClick={() => setSelectedId(node.id)} style={{ cursor: "pointer" }}>
                  <circle r={pos.radius + (active ? 5 : 2)} fill={active ? "rgba(0,46,255,0.12)" : "rgba(0,0,0,0.04)"} />
                  <circle r={pos.radius} fill={pos.color}
                    stroke={active ? "#002EFF" : "rgba(255,255,255,0.8)"} strokeWidth={active ? 2 : 1} />
                  {(active || Number(node.importance || 0) >= 3) && (
                    <text x={pos.radius + 5} y={4} fill="var(--fg)" fontSize="9" fontFamily="var(--font-ibm-mono)">
                      {node.name.slice(0, 22)}
                    </text>
                  )}
                </g>
              );
            })}
            </g>
          </svg>
        )}
        {visibleNodes.length > 0 && (
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", padding: "6px 8px", borderTop: "1px solid var(--bd)", fontFamily: "var(--font-ibm-mono)", fontSize: 10, color: "var(--fm)" }}>
            <span style={{ marginRight: "auto" }}>scroll to zoom · drag to pan</span>
            <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.min(4, v.scale * 1.2) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>+</button>
            <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.max(0.4, v.scale * 0.83) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>−</button>
            <button type="button" onClick={() => setView({ scale: 1, tx: 0, ty: 0 })} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>Reset</button>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={{ border: "1px solid var(--bd)", background: "var(--s2)", padding: "12px 13px", minHeight: 88 }}>
          <div className="sec-label" style={{ marginBottom: 7 }}>Selected entity</div>
          {selected ? (
            <div style={{ display: "grid", gap: 5 }}>
              <div style={{ color: "var(--fg)", fontSize: 13, fontWeight: 650 }}>{selected.name}</div>
              <div style={{ color: "var(--fd)", fontSize: 11, lineHeight: 1.45 }}>{selected.description || selected.type}</div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                <span className="pill" style={{ letterSpacing: 0 }}>{selected.type}</span>
                <span className="pill" style={{ letterSpacing: 0 }}>importance {Math.round(Number(selected.importance || 0))}</span>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--fm)", fontSize: 12 }}>Click a node to inspect it.</div>
          )}
        </div>
        <div style={{ border: "1px solid var(--bd)", background: "var(--s2)", padding: "12px 13px" }}>
          <div className="sec-label" style={{ marginBottom: 8 }}>Top entities</div>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {topEntities.length === 0 && <span style={{ color: "var(--fm)", fontSize: 12 }}>None yet.</span>}
            {topEntities.map(node => (
              <button type="button" key={node.id}
                onClick={() => setSelectedId(node.id)}
                className="pill"
                style={{
                  letterSpacing: 0, cursor: "pointer",
                  borderColor: selected?.id === node.id ? "var(--blue)" : undefined,
                  background: selected?.id === node.id ? "rgba(0,46,255,0.07)" : undefined,
                }}>
                {node.name.slice(0, 24)}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── main page ─── */

export default function CompanyBrainPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;

  /* ── state ── */
  const [tab, setTab] = useState<Tab>("ask");
  const [brain, setBrain] = useState<CompanyBrain | null>(null);
  const [selectedSources, setSelectedSources] = useState<string[]>(["github", "notion", "linear", "gmail", "google_drive", "slack", "discord"]);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [askQuestion, setAskQuestion] = useState("What should the team prioritize this week?");
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [askConfidence, setAskConfidence] = useState<number | null>(null);
  const [askCitations, setAskCitations] = useState<BrainAnswerCitation[]>([]);
  const [asking, setAsking] = useState(false);
  const [results, setResults] = useState<BrainRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [continuousSyncing, setContinuousSyncing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [maintaining, setMaintaining] = useState(false);
  const [savingCredential, setSavingCredential] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const [syncInterval, setSyncInterval] = useState(60);
  const [scheduler, setScheduler] = useState<BrainSchedulerState | null>(null);
  const [graph, setGraph] = useState<GraphRagVisualization | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphRebuilding, setGraphRebuilding] = useState(false);
  const [draft, setDraft] = useState({ source: "manual", title: "", content: "", canonical: true });
  const [pinOpen, setPinOpen] = useState(false);
  const [focusedSourceKey, setFocusedSourceKey] = useState("github");
  const [credentialValues, setCredentialValues] = useState<Record<string, Record<string, string>>>({});

  /* ── data loaders ── */
  const loadBrain = useCallback(async () => {
    setError(null);
    try {
      const data = await getCompanyBrain(founderId);
      setBrain(data);
      if (data.sync?.interval_minutes) setSyncInterval(data.sync.interval_minutes);
      try {
        const sched = await getCompanyBrainSchedulerStatus();
        setScheduler(sched.scheduler);
      } catch {
        setScheduler(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load company brain.");
    }
  }, [founderId]);

  const loadGraph = useCallback(async () => {
    setGraphLoading(true);
    try {
      const data = await getGraphRagVisualization(founderId);
      setGraph(data);
    } catch {
      setGraph(null);
    } finally {
      setGraphLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    const t = window.setTimeout(() => { void loadBrain(); }, 0);
    return () => window.clearTimeout(t);
  }, [loadBrain]);

  useEffect(() => {
    const t = window.setTimeout(() => { void loadGraph(); }, 0);
    return () => window.clearTimeout(t);
  }, [loadGraph]);

  /* ── derived ── */
  const sources = useMemo(() => {
    const vals = Object.values(brain?.sources ?? {});
    return vals.sort((a, b) => {
      const ai = SOURCE_ORDER.indexOf(a.key);
      const bi = SOURCE_ORDER.indexOf(b.key);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi) || a.label.localeCompare(b.label);
    });
  }, [brain]);

  const records = useMemo(() => brain?.records ?? [], [brain]);
  const focusedSource = sources.find(s => s.key === focusedSourceKey) ?? sources[0] ?? null;
  const recordsById = useMemo(() => new Map(records.map(r => [r.id, r])), [records]);
  const openProposals = useMemo(() => (brain?.proposals ?? []).filter(p => p.status === "open"), [brain]);
  const connected = sources.filter(s => s.status === "connected" || s.status === "oauth_ready").length;
  const displayResults = results.length ? results : records.slice(0, 8);

  /* ── actions ── */
  async function sync() {
    setSyncing(true);
    setError(null);
    try {
      await syncCompanyBrain(founderId, selectedSources);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  async function importSources() {
    setImporting(true);
    setError(null);
    setImportSummary(null);
    try {
      const result = await importCompanyBrainSources(founderId, selectedSources, 20);
      const imported = result.imported_sources.length ? result.imported_sources.join(", ") : "none";
      const failed = result.failed_sources.length ? ` Failed: ${result.failed_sources.join(", ")}.` : "";
      setImportSummary(`Imported: ${imported}.${failed}`);
      await loadBrain();
      await loadGraph();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  }

  async function saveFocusedCredential() {
    if (!focusedSource) return;
    setSavingCredential(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, focusedSource.key, credentialValues[focusedSource.key] ?? {});
      setCredentialValues(v => ({ ...v, [focusedSource.key]: {} }));
      await syncCompanyBrain(founderId, [focusedSource.key]);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save credentials.");
    } finally {
      setSavingCredential(false);
    }
  }

  async function configureContinuousSync(enabled: boolean) {
    setContinuousSyncing(true);
    setError(null);
    try {
      await configureCompanyBrainSync(founderId, { enabled, sources: selectedSources, interval_minutes: syncInterval });
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update sync settings.");
    } finally {
      setContinuousSyncing(false);
    }
  }

  async function runContinuousSyncNow() {
    setContinuousSyncing(true);
    setError(null);
    try {
      await runCompanyBrainSync(founderId, selectedSources);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Continuous sync run failed.");
    } finally {
      setContinuousSyncing(false);
    }
  }

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchCompanyBrain(founderId, query.trim(), 10);
      setResults(data.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function ask(e?: React.FormEvent) {
    e?.preventDefault();
    if (!askQuestion.trim()) return;
    setAsking(true);
    setError(null);
    try {
      const data = await askCompanyBrain(founderId, askQuestion.trim(), 8);
      setAskAnswer(data.answer);
      setAskConfidence(data.confidence);
      setAskCitations(data.citations ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed.");
    } finally {
      setAsking(false);
    }
  }

  async function addRecord(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.title.trim() || !draft.content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await addCompanyBrainRecord(founderId, {
        source: draft.source.trim() || "manual",
        title: draft.title.trim(),
        content: draft.content.trim(),
        canonical: draft.canonical,
        kind: "note",
        stale_risk: draft.canonical ? "low" : "medium",
      });
      setDraft({ source: "manual", title: "", content: "", canonical: true });
      setPinOpen(false);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save record.");
    } finally {
      setLoading(false);
    }
  }

  async function maintain() {
    setMaintaining(true);
    setError(null);
    try {
      await maintainCompanyBrain(founderId);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Maintenance scan failed.");
    } finally {
      setMaintaining(false);
    }
  }

  async function rebuildGraph() {
    setGraphRebuilding(true);
    setError(null);
    try {
      await syncGraphRag(founderId);
      await loadGraph();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Graph rebuild failed.");
    } finally {
      setGraphRebuilding(false);
    }
  }

  async function updateProposal(proposalId: string, status: "resolved" | "dismissed") {
    setError(null);
    try {
      await updateBrainProposal(founderId, proposalId, status);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update proposal.");
    }
  }

  /* ─── render ─── */
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* ── page header ── */}
      <div style={{ flexShrink: 0 }}>
        <PageHeader
          title="Company Brain"
          stats={[
            { label: "Records",   value: String(records.length) },
            { label: "Sources",   value: `${connected} connected` },
            { label: "Proposals", value: String(openProposals.length) },
            { label: "Stale",     value: String(brain?.maintenance?.stale_count ?? 0) },
          ]}
          actions={
            <>
              <Link href="/integrations" style={{
                display: "inline-flex", alignItems: "center", padding: "8px 14px",
                fontSize: 12, color: "rgba(255,255,255,0.88)",
                background: "rgba(255,255,255,0.13)", border: "1px solid rgba(255,255,255,0.28)",
                textDecoration: "none",
              }}>
                Integrations
              </Link>
              <Link href="/" style={{
                display: "inline-flex", alignItems: "center", padding: "8px 18px",
                fontSize: 12, fontWeight: 600, color: "#002EFF",
                background: "#fff", border: "none", textDecoration: "none",
              }}>
                Run agents
              </Link>
            </>
          }
        />

        {/* Tab bar */}
        <div style={{ borderBottom: "1px solid var(--bd)", background: "var(--surface)", paddingInline: 24 }}>
          <div className="dtabs" style={{ padding: 0, borderBottom: "none" }}>
            {(["ask", "graph", "sources", "memory", "settings"] as Tab[]).map(t => (
              <button
                key={t}
                type="button"
                className={`dtab${tab === t ? " on" : ""}`}
                onClick={() => setTab(t)}
              >
                {t === "ask" ? "Ask" : t === "graph" ? "Graph" : t === "sources" ? "Sources" : t === "memory" ? "Memory" : "Settings"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── error banner ── */}
      {error && (
        <div style={{ flexShrink: 0, padding: "10px 24px", borderBottom: "1px solid rgba(192,57,43,0.22)", background: "rgba(192,57,43,0.07)", color: "#c0392b", fontSize: 12 }}>
          {error}
          <button type="button" onClick={() => setError(null)} style={{ marginLeft: 10, color: "inherit", background: "none", border: "none", cursor: "pointer", fontSize: 11 }}>×</button>
        </div>
      )}

      {/* ── tab content ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px 32px" }}>

        {/* ━━━ ASK TAB ━━━ */}
        {tab === "ask" && (
          <div style={{ display: "grid", gap: 18, maxWidth: 860 }}>
            <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", padding: "20px 20px 16px" }}>
              <div className="sec-label" style={{ marginBottom: 10 }}>Ask the brain</div>
              <form onSubmit={ask} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <input
                  className="f-input"
                  value={askQuestion}
                  onChange={e => setAskQuestion(e.target.value)}
                  placeholder="What do we know about onboarding strategy?"
                  style={{ fontSize: 14, padding: "11px 14px" }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button type="submit" disabled={asking || !askQuestion.trim()} className="btn pri" style={{ minHeight: 36, fontSize: 12, paddingInline: 22 }}>
                    {asking ? "Thinking..." : "Ask"}
                  </button>
                </div>
              </form>

              {askAnswer && (
                <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
                  <div style={{ borderTop: "1px solid var(--bd)", paddingTop: 14, color: "var(--fg)", fontSize: 13, lineHeight: 1.65 }}>
                    {askAnswer}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="pill" style={{ letterSpacing: 0 }}>
                      {askConfidence !== null ? `${Math.round(askConfidence * 100)}% confidence` : "confidence n/a"}
                    </span>
                    {askCitations.length > 0 && (
                      <span style={{ color: "var(--fm)", fontSize: 11 }}>{askCitations.length} citations</span>
                    )}
                  </div>
                  {askCitations.length > 0 && (
                    <div style={{ display: "grid", gap: 5 }}>
                      {askCitations.slice(0, 6).map(cit => (
                        <div key={cit.record_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11, color: "var(--fd)" }}>
                          <span className="pill" style={{ letterSpacing: 0, flexShrink: 0 }}>[{cit.index}] {cit.source}</span>
                          {cit.url ? (
                            <a href={cit.url} target="_blank" rel="noopener noreferrer"
                              style={{ color: "var(--blue)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {cit.title}
                            </a>
                          ) : (
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cit.title}</span>
                          )}
                          {cit.canonical && <span style={{ color: "#3D9E5F", flexShrink: 0 }}>canonical</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* semantic search */}
            <div>
              <div className="sec-label" style={{ marginBottom: 8 }}>Search records</div>
              <form onSubmit={search} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input
                  className="f-input"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="decisions, roadmap, customers..."
                  style={{ fontSize: 12 }}
                />
                <button type="submit" disabled={loading || !query.trim()} className="btn" style={{ minHeight: 36, fontSize: 12, whiteSpace: "nowrap", flexShrink: 0 }}>
                  {loading ? "..." : "Search"}
                </button>
              </form>
              <div style={{ display: "grid", gap: 8 }}>
                {displayResults.length === 0 && (
                  <div style={{ color: "var(--fm)", fontSize: 12, padding: "14px 0" }}>
                    No records yet. Sync sources or pin a note in the Memory tab.
                  </div>
                )}
                {displayResults.map(r => <RecordRow key={r.id} record={r} />)}
              </div>
            </div>
          </div>
        )}

        {/* ━━━ SOURCES TAB ━━━ */}
        {tab === "graph" && (
          <GraphRagPanel
            graph={graph}
            loading={graphLoading}
            rebuilding={graphRebuilding}
            onReload={loadGraph}
            onRebuild={rebuildGraph}
          />
        )}

        {tab === "sources" && (
          <div style={{ display: "grid", gap: 18 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>
                  {connected} connected · {records.length} records · {brain?.relationships.length ?? 0} relationships
                </div>
                <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 3 }}>
                  Select sources, then sync or import their records.
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" onClick={importSources} disabled={importing} className="btn" style={{ minHeight: 34, fontSize: 12 }}>
                  {importing ? "Importing..." : "Import records"}
                </button>
                <button type="button" onClick={sync} disabled={syncing} className="btn pri" style={{ minHeight: 34, fontSize: 12 }}>
                  {syncing ? "Syncing..." : "Sync selected"}
                </button>
              </div>
            </div>

            {importSummary && (
              <div style={{ fontSize: 12, color: "var(--fd)", padding: "9px 12px", border: "1px solid var(--bd)", background: "var(--s2)" }}>
                {importSummary}
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, alignItems: "start" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(148px, 1fr))", gap: 8 }}>
                {sources.map(source => (
                  <SourceCard
                    key={source.key}
                    source={source}
                    active={selectedSources.includes(source.key)}
                    focused={focusedSource?.key === source.key}
                    onToggle={() => {
                      setFocusedSourceKey(source.key);
                      setSelectedSources(prev =>
                        prev.includes(source.key)
                          ? prev.filter(s => s !== source.key)
                          : [...prev, source.key]
                      );
                    }}
                  />
                ))}
              </div>

              <SourceConnectionPanel
                source={focusedSource}
                values={focusedSource ? credentialValues[focusedSource.key] ?? {} : {}}
                saving={savingCredential}
                onChange={(field, value) => {
                  if (!focusedSource) return;
                  setCredentialValues(prev => ({
                    ...prev,
                    [focusedSource.key]: { ...(prev[focusedSource.key] ?? {}), [field]: value },
                  }));
                }}
                onSave={saveFocusedCredential}
              />
            </div>
          </div>
        )}

        {/* ━━━ MEMORY TAB ━━━ */}
        {tab === "memory" && (
          <div style={{ display: "grid", gap: 16, maxWidth: 780 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>
                  {records.length} {records.length === 1 ? "record" : "records"}
                </div>
                <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 2 }}>
                  Decisions, facts, and customer context.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setPinOpen(v => !v)}
                className={`btn${pinOpen ? "" : " pri"}`}
                style={{ minHeight: 34, fontSize: 12 }}
              >
                {pinOpen ? "Cancel" : "+ Pin a note"}
              </button>
            </div>

            {/* pin a note form */}
            {pinOpen && (
              <form onSubmit={addRecord}
                style={{ border: "1px solid var(--bd2)", background: "var(--s2)", padding: 16, display: "grid", gap: 10 }}>
                <div className="sec-label">New note</div>
                <input
                  className="f-input"
                  value={draft.title}
                  onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
                  placeholder="Give it a title..."
                  style={{ fontSize: 13 }}
                  autoFocus
                />
                <textarea
                  className="f-input f-ta"
                  value={draft.content}
                  onChange={e => setDraft(d => ({ ...d, content: e.target.value }))}
                  placeholder="What should everyone and every agent know?"
                  rows={4}
                  style={{ resize: "none", minHeight: 100, fontSize: 12 }}
                />
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 12, color: "var(--fd)" }}>
                    <input
                      type="checkbox"
                      checked={draft.canonical}
                      onChange={e => setDraft(d => ({ ...d, canonical: e.target.checked }))}
                      style={{ accentColor: "var(--blue)" }}
                    />
                    Canonical source of truth
                  </label>
                  <button
                    type="submit"
                    disabled={loading || !draft.title.trim() || !draft.content.trim()}
                    className="btn pri"
                    style={{ minHeight: 34, fontSize: 12 }}
                  >
                    {loading ? "Saving..." : "Pin to brain"}
                  </button>
                </div>
              </form>
            )}

            {/* search */}
            <form onSubmit={search} style={{ display: "flex", gap: 8 }}>
              <input
                className="f-input"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search records..."
                style={{ fontSize: 12 }}
              />
              <button type="submit" disabled={loading || !query.trim()} className="btn" style={{ minHeight: 36, fontSize: 12, flexShrink: 0 }}>
                {loading ? "..." : "Search"}
              </button>
            </form>

            {/* records */}
            <div style={{ display: "grid", gap: 8 }}>
              {displayResults.length === 0 && (
                <div style={{ color: "var(--fm)", fontSize: 12, padding: "12px 0" }}>
                  No records yet. Pin a note above or sync a source.
                </div>
              )}
              {displayResults.map(r => <RecordRow key={r.id} record={r} />)}
            </div>
          </div>
        )}

        {/* ━━━ SETTINGS TAB ━━━ */}
        {tab === "settings" && (
          <div style={{ display: "grid", gap: 18, maxWidth: 900 }}>

            {/* continuous sync */}
            <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", padding: 18, display: "grid", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)", marginBottom: 3 }}>Continuous sync</div>
                  <div style={{ fontSize: 11, color: "var(--fm)" }}>
                    Status: {brain?.sync?.last_status ?? "idle"}
                    {brain?.sync?.last_run_at ? ` · last run ${brain.sync.last_run_at}` : ""}
                    {brain?.sync?.next_run_at ? ` · next ${brain.sync.next_run_at}` : ""}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 2 }}>
                    Scheduler {scheduler?.running ? "running" : "stopped"}
                    {scheduler?.last_tick_at ? ` · tick ${scheduler.last_tick_at}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                  <input
                    type="number" min={5} max={1440}
                    value={syncInterval}
                    onChange={e => setSyncInterval(Number(e.target.value))}
                    className="f-input"
                    style={{ width: 80 }}
                    aria-label="Sync interval minutes"
                  />
                  <span style={{ color: "var(--fm)", fontSize: 12 }}>min</span>
                  <button type="button" onClick={() => configureContinuousSync(!(brain?.sync?.enabled))}
                    disabled={continuousSyncing} className="btn" style={{ minHeight: 32, fontSize: 11 }}>
                    {brain?.sync?.enabled ? "Pause" : "Enable"}
                  </button>
                  <button type="button" onClick={runContinuousSyncNow}
                    disabled={continuousSyncing} className="btn pri" style={{ minHeight: 32, fontSize: 11 }}>
                    {continuousSyncing ? "Running..." : "Run now"}
                  </button>
                </div>
              </div>

              {brain?.sync?.last_error && (
                <div style={{ border: "1px solid rgba(192,57,43,0.25)", background: "rgba(192,57,43,0.06)", padding: "9px 12px", color: "#c0392b", fontSize: 12 }}>
                  {brain.sync.last_error}
                </div>
              )}

              {(brain?.sync?.history?.length ?? 0) > 0 && (
                <div style={{ borderTop: "1px solid var(--bd)", paddingTop: 10, display: "grid", gap: 5 }}>
                  <div className="sec-label" style={{ marginBottom: 5 }}>Recent runs</div>
                  {brain!.sync.history.slice(0, 4).map((entry, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--fm)" }}>
                      <span className="pill" style={{ letterSpacing: 0 }}>{String(entry.status ?? "run")}</span>
                      <span>{String(entry.finished_at ?? entry.started_at ?? "")}</span>
                      <span style={{ marginLeft: "auto" }}>
                        {Array.isArray(entry.imported_sources)
                          ? `imported ${(entry.imported_sources as string[]).join(", ") || "none"}`
                          : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* maintenance */}
            <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", padding: 18, display: "grid", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)", marginBottom: 3 }}>Maintenance scan</div>
                  <div style={{ fontSize: 11, color: "var(--fm)" }}>
                    Detects stale records, contradictions, and missing canonical docs.
                    {brain?.maintenance?.stale_count ? ` ${brain.maintenance.stale_count} stale,` : ""}
                    {brain?.maintenance?.contradiction_count ? ` ${brain.maintenance.contradiction_count} conflicts.` : ""}
                  </div>
                </div>
                <button type="button" onClick={maintain} disabled={maintaining} className="btn pri" style={{ minHeight: 34, fontSize: 12 }}>
                  {maintaining ? "Scanning..." : "Run scan"}
                </button>
              </div>

              {openProposals.length > 0 && (
                <div>
                  <div className="sec-label" style={{ marginBottom: 8 }}>
                    Open proposals ({openProposals.length})
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
                    {openProposals.slice(0, 6).map(p => (
                      <ProposalCard key={p.id} proposal={p} recordsById={recordsById} onUpdate={updateProposal} />
                    ))}
                  </div>
                </div>
              )}

              {openProposals.length === 0 && (
                <div style={{ color: "var(--fm)", fontSize: 12 }}>No open maintenance proposals.</div>
              )}
            </div>

            {/* graphrag */}
            <div style={{ border: "1px solid var(--bd2)", background: "var(--surface)", padding: 18 }}>
              <GraphRagPanel
                graph={graph}
                loading={graphLoading}
                rebuilding={graphRebuilding}
                onReload={loadGraph}
                onRebuild={rebuildGraph}
              />
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
