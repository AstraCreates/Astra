"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import Link from "next/link";
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
const Card = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => (
  <div style={{ background: "var(--surface)", border: "1px solid var(--bd)", padding: 18, display: "grid", gap: 14, ...style }}>
    {children}
  </div>
);

const DEFAULT_QUERY = "decisions product roadmap code customers";

const SOURCE_ORDER = [
  "discord",
  "slack",
  "github",
  "linear",
  "notion",
  "google_drive",
  "google_workspace",
  "gmail",
  "confluence",
  "zendesk",
  "granola",
  "astra_vault",
];

function statusColor(status: string): string {
  if (status === "connected") return "#3D9E5F";
  if (status === "oauth_ready") return "#002EFF";
  if (status === "planned") return "#C58B37";
  return "var(--fg-mute)";
}

function formatStatus(status: string): string {
  return status.replace(/_/g, " ");
}

function SourceCard({ source, active, onToggle }: { source: BrainSource; active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        minHeight: 106,
        textAlign: "left",
        borderRadius: 8,
        border: active ? "1px solid rgba(180,205,228,0.36)" : "1px solid var(--line)",
        background: active ? "rgba(180,205,228,0.12)" : "rgba(255,255,255,0.03)",
        padding: "12px 13px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        color: "var(--fg)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{source.label}</span>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: statusColor(source.status), flexShrink: 0 }} />
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span className="site-pill" style={{ letterSpacing: 0 }}>{source.kind}</span>
        <span className="site-pill" style={{ letterSpacing: 0 }}>{source.record_count} records</span>
      </div>
      <p style={{ margin: "auto 0 0", color: "var(--fg-mute)", fontSize: 11, lineHeight: 1.45 }}>
        {formatStatus(source.status)}{source.importer === false ? " · planned" : ""}
      </p>
    </button>
  );
}

function SourceConnectionPanel({
  source,
  values,
  saving,
  onChange,
  onSave,
}: {
  source: BrainSource | null;
  values: Record<string, string>;
  saving: boolean;
  onChange: (field: string, value: string) => void;
  onSave: () => void;
}) {
  if (!source) {
    return (
      <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "12px 13px", color: "var(--fg-mute)", fontSize: 12 }}>
        Select a source to see connection requirements.
      </div>
    );
  }
  const fields = source.credential_fields ?? [];
  const canSave = fields.length > 0 && fields.every(field => values[field]?.trim());
  return (
    <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "12px 13px", display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{source.label}</span>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: statusColor(source.status) }} />
        <span style={{ color: "var(--fg-mute)", fontSize: 11 }}>{formatStatus(source.status)}</span>
      </div>
      <p style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.5, margin: 0 }}>
        {source.notes || source.setup_hint || "Ready to connect."}
      </p>
      {source.setup_hint && source.notes !== source.setup_hint && (
        <p style={{ color: "var(--fg-mute)", fontSize: 11, lineHeight: 1.45, margin: 0 }}>{source.setup_hint}</p>
      )}
      {source.setup_url && (
        <a href={source.setup_url} target="_blank" rel="noopener noreferrer" style={{ color: "#7EA6E8", fontSize: 11, width: "fit-content" }}>
          Setup docs
        </a>
      )}
      {fields.length > 0 && (
        <div style={{ display: "grid", gap: 8 }}>
          {fields.map(field => (
            <input
              key={field}
              className="site-input"
              value={values[field] ?? ""}
              onChange={e => onChange(field, e.target.value)}
              placeholder={field}
              type={field.includes("token") || field.includes("key") ? "password" : "text"}
              style={{ padding: "8px 10px", fontSize: 12, fontFamily: "var(--font-jetbrains-mono)" }}
            />
          ))}
          <button type="button" onClick={onSave} disabled={saving || !canSave} className="site-btn site-btn-primary" style={{ minHeight: 34, fontSize: 12 }}>
            {saving ? "Saving..." : "Save credentials"}
          </button>
        </div>
      )}
      {fields.length === 0 && source.importer === false && (
        <div style={{ color: "var(--fg-mute)", fontSize: 11 }}>Direct import is not implemented yet; manual records can still use this source.</div>
      )}
    </div>
  );
}

function RecordRow({ record }: { record: BrainRecord }) {
  return (
    <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "12px 14px", display: "grid", gap: 7 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="site-pill" style={{ letterSpacing: 0 }}>{record.source}</span>
        <span style={{ color: record.canonical ? "#3D9E5F" : "var(--fg-mute)", fontSize: 11 }}>{record.canonical ? "canonical" : record.kind}</span>
        {record.domain && <span style={{ color: "var(--fg-mute)", fontSize: 11 }}>{record.domain}</span>}
        <span style={{ marginLeft: "auto", color: "var(--fg-mute)", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}>{record.stale_risk} drift</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{record.title}</div>
      <p style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>
        {(record.snippet ?? record.content).slice(0, 460)}
      </p>
      {record.url && (
        <a href={record.url.startsWith("/") ? undefined : record.url} target="_blank" rel="noopener noreferrer" style={{ color: "#7EA6E8", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {record.url}
        </a>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  recordsById,
  onUpdate,
}: {
  proposal: BrainProposal;
  recordsById: Map<string, BrainRecord>;
  onUpdate: (proposalId: string, status: "resolved" | "dismissed") => void;
}) {
  const linked = proposal.record_ids.map(id => recordsById.get(id)).filter(Boolean) as BrainRecord[];
  return (
    <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "12px 14px", display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="site-pill" style={{ letterSpacing: 0 }}>{proposal.kind.replace(/_/g, " ")}</span>
        <span style={{ color: "#C58B37", fontSize: 11 }}>{proposal.status}</span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--fg)" }}>{proposal.title}</div>
      <p style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>{proposal.reason}</p>
      <p style={{ color: "var(--fg-mute)", fontSize: 11, lineHeight: 1.5, margin: 0 }}>{proposal.suggested_update}</p>
      {linked.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {linked.map(record => <span key={record.id} className="site-pill" style={{ letterSpacing: 0 }}>{record.source}: {record.title.slice(0, 28)}</span>)}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button type="button" onClick={() => onUpdate(proposal.id, "dismissed")} className="site-btn site-btn-ghost" style={{ minHeight: 30, fontSize: 11 }}>Dismiss</button>
        <button type="button" onClick={() => onUpdate(proposal.id, "resolved")} className="site-btn site-btn-primary" style={{ minHeight: 30, fontSize: 11 }}>Mark resolved</button>
      </div>
    </div>
  );
}

const GRAPH_COLORS = ["#002EFF", "#3D9E5F", "#C58B37", "#B45EA4", "#0F766E", "#DC2626", "#7C3AED", "#64748B"];

function GraphRagPanel({
  graph,
  loading,
  rebuilding,
  onReload,
  onRebuild,
}: {
  graph: GraphRagVisualization | null;
  loading: boolean;
  rebuilding: boolean;
  onReload: () => void;
  onRebuild: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = useMemo(() => graph?.edges ?? [], [graph]);
  const visibleNodes = useMemo(() => nodes.slice(0, 80), [nodes]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map(node => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target)).slice(0, 180),
    [edges, visibleIds]
  );
  const selected = visibleNodes.find(node => node.id === selectedId) ?? visibleNodes[0] ?? null;
  const layout = useMemo(() => {
    const width = 720;
    const height = 360;
    const centerX = width / 2;
    const centerY = height / 2;
    const communities = Array.from(new Set(visibleNodes.map(node => node.community_id || "unassigned")));
    const positions = new Map<string, { x: number; y: number; color: string; radius: number }>();
    visibleNodes.forEach((node, index) => {
      const communityIndex = Math.max(0, communities.indexOf(node.community_id || "unassigned"));
      const bandAngle = (communityIndex / Math.max(1, communities.length)) * Math.PI * 2;
      const localAngle = bandAngle + ((index % 13) - 6) * 0.105 + (Math.floor(index / 13) * 0.035);
      const ring = 78 + (communityIndex % 3) * 54 + (index % 5) * 10;
      const importance = Number(node.importance || 1);
      positions.set(node.id, {
        x: centerX + Math.cos(localAngle) * ring,
        y: centerY + Math.sin(localAngle) * ring * 0.72,
        color: GRAPH_COLORS[communityIndex % GRAPH_COLORS.length],
        radius: Math.max(5, Math.min(15, 5 + importance * 1.4)),
      });
    });
    return { width, height, positions };
  }, [visibleNodes]);
  const topEntities = useMemo(
    () => [...nodes].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0)).slice(0, 8),
    [nodes]
  );

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>GraphRAG v2 map</div>
          <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>
            {nodes.length} entities, {edges.length} SQL relationships, {new Set(nodes.map(node => node.community_id || "unassigned")).size} communities
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onReload} disabled={loading || rebuilding} className="site-btn site-btn-ghost" style={{ minHeight: 34, fontSize: 12 }}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button type="button" onClick={onRebuild} disabled={rebuilding} className="site-btn site-btn-primary" style={{ minHeight: 34, fontSize: 12 }}>
            {rebuilding ? "Rebuilding..." : "Rebuild graph"}
          </button>
        </div>
      </div>

      <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", overflow: "hidden" }}>
        {visibleNodes.length === 0 ? (
          <div style={{ minHeight: 310, display: "grid", placeItems: "center", padding: 18, color: "var(--fg-mute)", fontSize: 12, textAlign: "center" }}>
            Add records, then rebuild the graph to create the SQLite entity map.
          </div>
        ) : (
          <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="GraphRAG entity relationship map" style={{ width: "100%", height: 360, display: "block" }}>
            <rect width={layout.width} height={layout.height} fill="rgba(11,18,32,0.18)" />
            {visibleEdges.map(edge => {
              const source = layout.positions.get(edge.source);
              const target = layout.positions.get(edge.target);
              if (!source || !target) return null;
              const active = selectedId === edge.source || selectedId === edge.target;
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={active ? "rgba(255,255,255,0.74)" : "rgba(180,205,228,0.20)"}
                  strokeWidth={active ? Math.min(4, 1.2 + Number(edge.weight || 1)) : Math.min(2.8, 0.6 + Number(edge.weight || 1) * 0.35)}
                />
              );
            })}
            {visibleNodes.map(node => {
              const pos = layout.positions.get(node.id);
              if (!pos) return null;
              const active = selected?.id === node.id;
              return (
                <g key={node.id} transform={`translate(${pos.x} ${pos.y})`} onClick={() => setSelectedId(node.id)} style={{ cursor: "pointer" }}>
                  <circle r={pos.radius + (active ? 6 : 2)} fill={active ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.06)"} />
                  <circle r={pos.radius} fill={pos.color} stroke={active ? "#FFFFFF" : "rgba(255,255,255,0.55)"} strokeWidth={active ? 2 : 1} />
                  {(active || Number(node.importance || 0) >= 3) && (
                    <text x={pos.radius + 6} y={4} fill="var(--fg)" fontSize="10" fontFamily="var(--font-jetbrains-mono)">
                      {node.name.slice(0, 24)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "11px 12px", minHeight: 94 }}>
          <div style={{ color: "var(--fg-mute)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 7 }}>Selected entity</div>
          {selected ? (
            <div style={{ display: "grid", gap: 5 }}>
              <div style={{ color: "var(--fg)", fontSize: 13, fontWeight: 650 }}>{selected.name}</div>
              <div style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.45 }}>{selected.description || selected.type}</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span className="site-pill" style={{ letterSpacing: 0 }}>{selected.type}</span>
                <span className="site-pill" style={{ letterSpacing: 0 }}>importance {Math.round(Number(selected.importance || 0))}</span>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--fg-mute)", fontSize: 12 }}>No entity selected.</div>
          )}
        </div>
        <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "11px 12px" }}>
          <div style={{ color: "var(--fg-mute)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Top entities</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {topEntities.length === 0 && <span style={{ color: "var(--fg-mute)", fontSize: 12 }}>None yet.</span>}
            {topEntities.map(node => (
              <button
                type="button"
                key={node.id}
                onClick={() => setSelectedId(node.id)}
                className="site-pill"
                style={{ letterSpacing: 0, cursor: "pointer", borderColor: selected?.id === node.id ? "rgba(255,255,255,0.42)" : undefined }}
              >
                {node.name.slice(0, 26)}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function CompanyBrainPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
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
  const [focusedSourceKey, setFocusedSourceKey] = useState("github");
  const [credentialValues, setCredentialValues] = useState<Record<string, Record<string, string>>>({});

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
    const timer = window.setTimeout(() => {
      void loadBrain();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadBrain]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadGraph();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadGraph]);

  const sources = useMemo(() => {
    const values = Object.values(brain?.sources ?? {});
    return values.sort((a, b) => {
      const ai = SOURCE_ORDER.indexOf(a.key);
      const bi = SOURCE_ORDER.indexOf(b.key);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi) || a.label.localeCompare(b.label);
    });
  }, [brain]);

  const records = useMemo(() => brain?.records ?? [], [brain]);
  const focusedSource = sources.find(source => source.key === focusedSourceKey) ?? sources[0] ?? null;
  const recordsById = useMemo(() => new Map(records.map(record => [record.id, record])), [records]);
  const openProposals = useMemo(() => (brain?.proposals ?? []).filter(p => p.status === "open"), [brain]);
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
      setCredentialValues(values => ({ ...values, [focusedSource.key]: {} }));
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
      await configureCompanyBrainSync(founderId, {
        enabled,
        sources: selectedSources,
        interval_minutes: syncInterval,
      });
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

  const displayResults = results.length ? results : records.slice(0, 8);
  const connected = sources.filter(s => s.status === "connected" || s.status === "oauth_ready").length;

  return (
    <div style={{ width: "100%", maxWidth: 1180, margin: "0 auto", display: "grid", gap: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className="site-label">Company brain</span>
          <h1 style={{ marginTop: 4, fontSize: 30 }}>Live context layer for people and agents</h1>
        </div>
        <Link href="/integrations" className="site-btn site-btn-ghost" style={{ minHeight: 36, fontSize: 12 }}>Connect tools</Link>
        <Link href="/" className="site-btn site-btn-primary" style={{ minHeight: 36, fontSize: 12 }}>Run agents</Link>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
        {[
          ["Records", String(records.length)],
          ["Open proposals", String(openProposals.length)],
          ["Stale", String(brain?.maintenance?.stale_count ?? 0)],
          ["Conflicts", String(brain?.maintenance?.contradiction_count ?? 0)],
        ].map(([label, value]) => (
          <div key={label} style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "10px 12px" }}>
            <div style={{ color: "var(--fg-mute)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
            <div style={{ color: "var(--fg)", fontSize: 20, fontWeight: 700, fontFamily: "var(--font-jetbrains-mono)", lineHeight: 1.2 }}>{value}</div>
          </div>
        ))}
      </div>

      {error && (
        <div style={{ borderRadius: 8, border: "1px solid rgba(192,57,43,0.32)", background: "rgba(192,57,43,0.10)", padding: "10px 12px", color: "#fca5a5", fontSize: 12 }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.25fr 0.75fr", gap: 18 }}>
        <Card style={{ gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>Sources</div>
              <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>{connected} ready, {records.length} records, {brain?.relationships.length ?? 0} relationships</div>
            </div>
            <button type="button" onClick={sync} disabled={syncing} className="site-btn site-btn-primary" style={{ minHeight: 36, fontSize: 12 }}>
              {syncing ? "Syncing..." : "Sync selected"}
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button type="button" onClick={importSources} disabled={importing} className="site-btn site-btn-ghost" style={{ minHeight: 34, fontSize: 12 }}>
              {importing ? "Importing..." : "Import connected records"}
            </button>
            {importSummary && <span style={{ color: "var(--fg-mute)", fontSize: 12 }}>{importSummary}</span>}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(154px, 1fr))", gap: 10 }}>
            {sources.map(source => (
              <SourceCard
                key={source.key}
                source={source}
                active={selectedSources.includes(source.key)}
                onToggle={() => {
                  setFocusedSourceKey(source.key);
                  setSelectedSources(prev => prev.includes(source.key) ? prev.filter(s => s !== source.key) : [...prev, source.key]);
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
        </Card>

        <Card style={{ gap: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>Manual memory</div>
            <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>Pin decisions, facts, customer notes, or architecture context.</div>
          </div>
          <form onSubmit={addRecord} style={{ display: "grid", gap: 9 }}>
            <input className="site-input" value={draft.source} onChange={e => setDraft(d => ({ ...d, source: e.target.value }))} placeholder="source" style={{ padding: "9px 12px", fontSize: 12 }} />
            <input className="site-input" value={draft.title} onChange={e => setDraft(d => ({ ...d, title: e.target.value }))} placeholder="Decision title" style={{ padding: "9px 12px", fontSize: 12 }} />
            <textarea className="site-textarea" value={draft.content} onChange={e => setDraft(d => ({ ...d, content: e.target.value }))} placeholder="What should everyone and every agent know?" rows={5} style={{ padding: "10px 12px", fontSize: 12, resize: "none" }} />
            <label style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--fg-dim)", fontSize: 12 }}>
              <input type="checkbox" checked={draft.canonical} onChange={e => setDraft(d => ({ ...d, canonical: e.target.checked }))} />
              Canonical source of truth
            </label>
            <button type="submit" disabled={loading || !draft.title.trim() || !draft.content.trim()} className="site-btn site-btn-primary" style={{ minHeight: 36, fontSize: 12 }}>
              Save to brain
            </button>
          </form>
        </Card>
      </div>

      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>Continuous sync</div>
            <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>
              Last {brain?.sync?.last_status ?? "idle"}{brain?.sync?.last_run_at ? ` at ${brain.sync.last_run_at}` : ""}{brain?.sync?.next_run_at ? ` · next ${brain.sync.next_run_at}` : ""}
            </div>
            <div style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 3 }}>
              Scheduler {scheduler?.running ? "running" : "stopped"}{scheduler?.last_tick_at ? ` · tick ${scheduler.last_tick_at}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="number"
              min={5}
              max={1440}
              value={syncInterval}
              onChange={e => setSyncInterval(Number(e.target.value))}
              className="site-input"
              style={{ width: 92, padding: "7px 10px", fontSize: 12 }}
              aria-label="Sync interval minutes"
            />
            <span style={{ color: "var(--fg-mute)", fontSize: 12 }}>minutes</span>
            <button type="button" onClick={() => configureContinuousSync(!(brain?.sync?.enabled))} disabled={continuousSyncing} className="site-btn site-btn-ghost" style={{ minHeight: 34, fontSize: 12 }}>
              {brain?.sync?.enabled ? "Pause" : "Enable"}
            </button>
            <button type="button" onClick={runContinuousSyncNow} disabled={continuousSyncing} className="site-btn site-btn-primary" style={{ minHeight: 34, fontSize: 12 }}>
              {continuousSyncing ? "Running..." : "Run now"}
            </button>
          </div>
        </div>
        {brain?.sync?.last_error && (
          <div style={{ borderRadius: 8, border: "1px solid rgba(192,57,43,0.32)", background: "rgba(192,57,43,0.10)", padding: "9px 11px", color: "#fca5a5", fontSize: 12 }}>
            {brain.sync.last_error}
          </div>
        )}
        {(brain?.sync?.history?.length ?? 0) > 0 && (
          <div style={{ display: "grid", gap: 6 }}>
            {brain!.sync.history.slice(0, 4).map((entry, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--fg-mute)", borderTop: i === 0 ? "none" : "1px solid var(--line)", paddingTop: i === 0 ? 0 : 6 }}>
                <span className="site-pill" style={{ letterSpacing: 0 }}>{String(entry.status ?? "run")}</span>
                <span>{String(entry.finished_at ?? entry.started_at ?? "")}</span>
                <span style={{ marginLeft: "auto" }}>{Array.isArray(entry.imported_sources) ? `imported ${(entry.imported_sources as string[]).join(", ") || "none"}` : ""}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>Maintenance</div>
            <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>
              Detect stale records, contradictory source material, and missing canonical docs.
            </div>
          </div>
          <button type="button" onClick={maintain} disabled={maintaining} className="site-btn site-btn-primary" style={{ minHeight: 36, fontSize: 12 }}>
            {maintaining ? "Scanning..." : "Run scan"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
          {openProposals.length === 0 && <p style={{ color: "var(--fg-mute)", fontSize: 12 }}>No open maintenance proposals.</p>}
          {openProposals.slice(0, 6).map(proposal => (
            <ProposalCard key={proposal.id} proposal={proposal} recordsById={recordsById} onUpdate={updateProposal} />
          ))}
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Card>
          <form onSubmit={search} style={{ display: "flex", gap: 10 }}>
            <input className="site-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Ask across Slack, GitHub, Notion, Google, and agent memory" style={{ padding: "10px 13px", fontSize: 13 }} />
            <button type="submit" disabled={loading || !query.trim()} className="site-btn site-btn-primary" style={{ minHeight: 40, fontSize: 12 }}>
              {loading ? "..." : "Search"}
            </button>
          </form>
          <div style={{ display: "grid", gap: 10 }}>
            {displayResults.length === 0 && <p style={{ color: "var(--fg-mute)", fontSize: 12 }}>Sync sources or add a manual memory to start the graph.</p>}
            {displayResults.map(record => <RecordRow key={record.id} record={record} />)}
          </div>
        </Card>

        <GraphRagPanel
          graph={graph}
          loading={graphLoading}
          rebuilding={graphRebuilding}
          onReload={loadGraph}
          onRebuild={rebuildGraph}
        />
      </div>

      <Card style={{ gap: 12 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 650, color: "var(--fg)" }}>Ask the brain</div>
          <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>Returns an answer grounded in synced records with citations.</div>
        </div>
        <form onSubmit={ask} style={{ display: "flex", gap: 10 }}>
          <input className="site-input" value={askQuestion} onChange={e => setAskQuestion(e.target.value)} placeholder="What do we know about onboarding strategy?" style={{ padding: "10px 13px", fontSize: 13 }} />
          <button type="submit" disabled={asking || !askQuestion.trim()} className="site-btn site-btn-primary" style={{ minHeight: 40, fontSize: 12 }}>
            {asking ? "..." : "Ask"}
          </button>
        </form>
        {askAnswer && (
          <div style={{ borderRadius: 8, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", padding: "11px 12px", display: "grid", gap: 8 }}>
            <div style={{ color: "var(--fg)", fontSize: 13, lineHeight: 1.5 }}>{askAnswer}</div>
            <div style={{ color: "var(--fg-mute)", fontSize: 11 }}>
              Confidence: {askConfidence !== null ? `${Math.round(askConfidence * 100)}%` : "n/a"} · Citations: {askCitations.length}
            </div>
            {askCitations.length > 0 && (
              <div style={{ display: "grid", gap: 6 }}>
                {askCitations.slice(0, 6).map(citation => (
                  <div key={citation.record_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11, color: "var(--fg-dim)" }}>
                    <span className="site-pill" style={{ letterSpacing: 0 }}>[{citation.index}] {citation.source}</span>
                    {citation.url ? (
                      <a href={citation.url} target="_blank" rel="noopener noreferrer" style={{ color: "#7EA6E8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {citation.title}
                      </a>
                    ) : (
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{citation.title}</span>
                    )}
                    {citation.canonical && <span style={{ color: "#3D9E5F" }}>canonical</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

