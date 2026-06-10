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

/* ─── constants ─── */

const SOURCE_ORDER = [
  "discord", "slack", "github", "linear", "notion",
  "google_drive", "google_workspace", "gmail",
  "confluence", "zendesk", "granola", "astra_vault",
];

const SOURCE_ICONS: Record<string, string> = {
  discord: "💬", slack: "💬", github: "🐙", linear: "📋", notion: "📝",
  google_drive: "📁", google_workspace: "📁", gmail: "📧",
  confluence: "📚", zendesk: "🎧", granola: "🎙", astra_vault: "🗄",
};

const SUGGESTED_QUESTIONS = [
  "What should the team prioritize this week?",
  "What decisions have we made recently?",
  "What do we know about our customers?",
  "Where is the product roadmap headed?",
];

type Tab = "ask" | "knowledge" | "map" | "settings";

function statusColor(status: string): string {
  if (status === "connected" || status === "oauth_ready") return "#16a34a";
  if (status === "planned") return "#d97706";
  return "var(--fm)";
}

function isConnected(s: BrainSource) {
  return s.status === "connected" || s.status === "oauth_ready";
}

/* ─── small shared pieces ─── */

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      border: "1px solid var(--bd)", background: "var(--surface)",
      borderRadius: 12, ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 2, lineHeight: 1.5 }}>{sub}</div>}
    </div>
  );
}

/* ─── record card ─── */

function RecordCard({ record }: { record: BrainRecord }) {
  const [open, setOpen] = useState(false);
  const body = record.snippet ?? record.content;
  return (
    <Card style={{ padding: "13px 16px", cursor: body.length > 180 ? "pointer" : "default" }}>
      <div onClick={() => setOpen(v => !v)}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
          <span style={{ fontSize: 13 }}>{SOURCE_ICONS[record.source] ?? "📌"}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {record.title}
          </span>
          {record.canonical && (
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: "#16a34a", background: "rgba(22,163,74,.09)", border: "1px solid rgba(22,163,74,.22)", padding: "2px 8px", borderRadius: 999, flexShrink: 0 }}>
              Source of truth
            </span>
          )}
        </div>
        <p style={{ color: "var(--fd)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>
          {open ? body : body.slice(0, 180) + (body.length > 180 ? "…" : "")}
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 7, fontSize: 10.5, color: "var(--fm)" }}>
          <span>{record.source}</span>
          {record.domain && <span>· {record.domain}</span>}
          {record.url && (
            <a href={record.url.startsWith("/") ? undefined : record.url} target="_blank" rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              style={{ color: "var(--blue)", marginLeft: "auto", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 240 }}>
              Open link →
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ─── source connect modal ─── */

function ConnectModal({
  source, values, saving, onChange, onSave, onClose,
}: {
  source: BrainSource;
  values: Record<string, string>;
  saving: boolean;
  onChange: (field: string, value: string) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const fields = source.credential_fields ?? [];
  const canSave = fields.length > 0 && fields.every(f => values[f]?.trim());
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 200, background: "rgba(17,16,24,0.40)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: "100%", maxWidth: 460, background: "var(--surface)",
        border: "1px solid var(--bd2)", borderRadius: 16, overflow: "hidden",
        boxShadow: "0 24px 60px rgba(17,16,24,0.18)",
      }}>
        <div style={{ padding: "18px 22px 14px", borderBottom: "1px solid var(--bd)", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>{SOURCE_ICONS[source.key] ?? "🔌"}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>{source.label}</div>
            <div style={{ fontSize: 11, color: isConnected(source) ? "#16a34a" : "var(--fm)", marginTop: 1 }}>
              {isConnected(source) ? "✓ Connected" : source.status === "planned" ? "Coming soon" : "Not connected"}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 18, color: "var(--fm)", cursor: "pointer", padding: 4 }}>✕</button>
        </div>

        <div style={{ padding: "16px 22px 20px", display: "grid", gap: 12 }}>
          <p style={{ color: "var(--fd)", fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>
            {source.notes || source.setup_hint || "Add your credentials to start syncing."}
          </p>
          {source.setup_hint && source.notes !== source.setup_hint && (
            <p style={{ color: "var(--fm)", fontSize: 11.5, lineHeight: 1.5, margin: 0 }}>{source.setup_hint}</p>
          )}
          {source.setup_url && (
            <a href={source.setup_url} target="_blank" rel="noopener noreferrer"
              style={{ color: "var(--blue)", fontSize: 12, width: "fit-content", fontWeight: 500 }}>
              Where do I find this? →
            </a>
          )}
          {fields.length > 0 ? (
            <div style={{ display: "grid", gap: 9 }}>
              {fields.map(field => (
                <input
                  key={field}
                  className="f-input"
                  value={values[field] ?? ""}
                  onChange={e => onChange(field, e.target.value)}
                  placeholder={field.replace(/_/g, " ")}
                  type={field.includes("token") || field.includes("key") || field.includes("secret") ? "password" : "text"}
                />
              ))}
              <button type="button" onClick={onSave} disabled={saving || !canSave} className="btn pri" style={{ minHeight: 38, fontSize: 13 }}>
                {saving ? "Connecting…" : "Connect"}
              </button>
            </div>
          ) : source.importer === false ? (
            <div style={{ color: "var(--fm)", fontSize: 12, padding: "10px 14px", background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: 9 }}>
              This source isn&apos;t available yet — but you can still reference it in manual notes.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ─── suggestion (proposal) card ─── */

function SuggestionCard({
  proposal, recordsById, onUpdate,
}: {
  proposal: BrainProposal;
  recordsById: Map<string, BrainRecord>;
  onUpdate: (id: string, status: "resolved" | "dismissed") => void;
}) {
  const linked = proposal.record_ids.map(id => recordsById.get(id)).filter(Boolean) as BrainRecord[];
  return (
    <Card style={{ padding: "14px 16px", display: "grid", gap: 8, borderColor: "rgba(217,119,6,0.30)", background: "rgba(217,119,6,0.04)" }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{proposal.title}</div>
      <p style={{ color: "var(--fd)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>{proposal.reason}</p>
      <p style={{ color: "var(--fm)", fontSize: 11.5, lineHeight: 1.5, margin: 0, fontStyle: "italic" }}>
        Suggested: {proposal.suggested_update}
      </p>
      {linked.length > 0 && (
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
          {linked.map(r => (
            <span key={r.id} className="pill" style={{ letterSpacing: 0 }}>{r.title.slice(0, 30)}</span>
          ))}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 2 }}>
        <button type="button" onClick={() => onUpdate(proposal.id, "dismissed")} className="btn" style={{ minHeight: 30, fontSize: 11 }}>
          Ignore
        </button>
        <button type="button" onClick={() => onUpdate(proposal.id, "resolved")} className="btn pri" style={{ minHeight: 30, fontSize: 11 }}>
          Done — resolved
        </button>
      </div>
    </Card>
  );
}

/* ─── knowledge map ─── */

const GRAPH_COLORS = ["#002EFF", "#16a34a", "#d97706", "#B45EA4", "#0F766E", "#DC2626", "#7C3AED", "#64748B"];

function KnowledgeMap({
  graph, loading, rebuilding, onReload, onRebuild,
}: {
  graph: GraphRagVisualization | null;
  loading: boolean;
  rebuilding: boolean;
  onReload: () => void;
  onRebuild: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <SectionTitle
          title="Knowledge map"
          sub={`How the people, products, and decisions in your brain connect. ${nodes.length} entities · ${edges.length} connections.`}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onReload} disabled={loading || rebuilding} className="btn" style={{ minHeight: 32, fontSize: 11 }}>
            {loading ? "Loading…" : "Refresh"}
          </button>
          <button type="button" onClick={onRebuild} disabled={rebuilding} className="btn pri" style={{ minHeight: 32, fontSize: 11 }}>
            {rebuilding ? "Rebuilding…" : "Rebuild map"}
          </button>
        </div>
      </div>

      <Card style={{ overflow: "hidden" }}>
        {visibleNodes.length === 0 ? (
          <div style={{ minHeight: 280, display: "grid", placeItems: "center", padding: 18, color: "var(--fm)", fontSize: 12.5, textAlign: "center", lineHeight: 1.6 }}>
            Nothing to map yet.<br />Add knowledge first, then hit &ldquo;Rebuild map&rdquo;.
          </div>
        ) : (
          <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="Knowledge map"
            style={{ width: "100%", height: 340, display: "block", cursor: panRef.current ? "grabbing" : "grab", touchAction: "none" }}
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
                    <text x={pos.radius + 5} y={4} fill="var(--fg)" fontSize="9" fontFamily="var(--font-code)">
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
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", padding: "6px 8px", borderTop: "1px solid var(--bd)", fontFamily: "var(--font-code)", fontSize: 10, color: "var(--fm)" }}>
            <span style={{ marginRight: "auto" }}>scroll to zoom · drag to pan</span>
            <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.min(4, v.scale * 1.2) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>+</button>
            <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.max(0.4, v.scale * 0.83) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>−</button>
            <button type="button" onClick={() => setView({ scale: 1, tx: 0, ty: 0 })} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>Reset</button>
          </div>
        )}
      </Card>

      {visibleNodes.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Card style={{ padding: "13px 15px", minHeight: 88 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", marginBottom: 7, textTransform: "uppercase", letterSpacing: ".06em" }}>Selected</div>
            {selected ? (
              <div style={{ display: "grid", gap: 5 }}>
                <div style={{ color: "var(--fg)", fontSize: 13, fontWeight: 600 }}>{selected.name}</div>
                <div style={{ color: "var(--fd)", fontSize: 11.5, lineHeight: 1.45 }}>{selected.description || selected.type}</div>
              </div>
            ) : (
              <div style={{ color: "var(--fm)", fontSize: 12 }}>Click a dot to inspect it.</div>
            )}
          </Card>
          <Card style={{ padding: "13px 15px" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", marginBottom: 8, textTransform: "uppercase", letterSpacing: ".06em" }}>Most important</div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
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
          </Card>
        </div>
      )}
    </div>
  );
}

/* ─── main page ─── */

export default function CompanyBrainPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;

  /* ── state (all original features preserved) ── */
  const [tab, setTab] = useState<Tab>("ask");
  const [brain, setBrain] = useState<CompanyBrain | null>(null);
  const [selectedSources, setSelectedSources] = useState<string[]>(["github", "notion", "linear", "gmail", "google_drive", "slack", "discord"]);
  const [query, setQuery] = useState("");
  const [askQuestion, setAskQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [askConfidence, setAskConfidence] = useState<number | null>(null);
  const [askCitations, setAskCitations] = useState<BrainAnswerCitation[]>([]);
  const [asking, setAsking] = useState(false);
  const [results, setResults] = useState<BrainRecord[]>([]);
  const [searched, setSearched] = useState(false);
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
  const [connectKey, setConnectKey] = useState<string | null>(null);
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
  const connectSource = sources.find(s => s.key === connectKey) ?? null;
  const recordsById = useMemo(() => new Map(records.map(r => [r.id, r])), [records]);
  const openProposals = useMemo(() => (brain?.proposals ?? []).filter(p => p.status === "open"), [brain]);
  const connected = sources.filter(isConnected).length;
  const shownRecords = searched && results.length >= 0 && query.trim() ? results : records;

  /* ── actions (all original handlers preserved) ── */
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

  async function saveConnectCredential() {
    if (!connectSource) return;
    setSavingCredential(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, connectSource.key, credentialValues[connectSource.key] ?? {});
      setCredentialValues(v => ({ ...v, [connectSource.key]: {} }));
      await syncCompanyBrain(founderId, [connectSource.key]);
      await loadBrain();
      setConnectKey(null);
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
    if (!query.trim()) { setResults([]); setSearched(false); return; }
    setLoading(true);
    setError(null);
    try {
      const data = await searchCompanyBrain(founderId, query.trim(), 10);
      setResults(data.results);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function ask(question?: string, e?: React.FormEvent) {
    e?.preventDefault();
    const q = (question ?? askQuestion).trim();
    if (!q) return;
    if (question) setAskQuestion(question);
    setAsking(true);
    setError(null);
    try {
      const data = await askCompanyBrain(founderId, q, 8);
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
      setError(err instanceof Error ? err.message : "Health check failed.");
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
      setError(err instanceof Error ? err.message : "Map rebuild failed.");
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
      setError(err instanceof Error ? err.message : "Could not update suggestion.");
    }
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: "ask", label: "Ask" },
    { key: "knowledge", label: "Knowledge" },
    { key: "map", label: "Map" },
    { key: "settings", label: "Settings" },
  ];

  /* ─── render ─── */
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* ── page header ── */}
      <div style={{ flexShrink: 0 }}>
        <PageHeader
          title="Company Brain"
          subtitle="Everything your company knows — searchable by you and your agents"
          stats={[
            { label: "Records", value: String(records.length) },
            { label: "Sources", value: `${connected} connected` },
          ]}
          actions={
            <Link href="/" style={{
              display: "inline-flex", alignItems: "center", padding: "8px 18px",
              fontSize: 12, fontWeight: 600, color: "#002EFF",
              background: "#fff", border: "none", textDecoration: "none", borderRadius: 8,
            }}>
              Run agents
            </Link>
          }
        />

        {/* Tab bar */}
        <div style={{ borderBottom: "1px solid var(--bd)", background: "var(--surface)", paddingInline: 24, display: "flex", gap: 2 }}>
          {TABS.map(t => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={{
                padding: "11px 14px", fontSize: 13,
                fontWeight: tab === t.key ? 600 : 450,
                color: tab === t.key ? "var(--blue)" : "var(--fm)",
                background: "transparent", border: "none", cursor: "pointer",
                borderBottom: tab === t.key ? "2px solid var(--blue)" : "2px solid transparent",
                marginBottom: -1, display: "flex", alignItems: "center", gap: 6,
              }}
            >
              {t.label}
              {t.key === "settings" && openProposals.length > 0 && (
                <span style={{ fontSize: 9, fontWeight: 700, color: "#fff", background: "#d97706", borderRadius: 999, padding: "1px 6px" }}>
                  {openProposals.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── error banner ── */}
      {error && (
        <div style={{ flexShrink: 0, padding: "10px 24px", borderBottom: "1px solid rgba(192,57,43,0.22)", background: "rgba(192,57,43,0.07)", color: "#c0392b", fontSize: 12, display: "flex", alignItems: "center" }}>
          <span style={{ flex: 1 }}>{error}</span>
          <button type="button" onClick={() => setError(null)} style={{ color: "inherit", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>✕</button>
        </div>
      )}

      {/* ── suggestions banner (visible from any tab) ── */}
      {openProposals.length > 0 && tab !== "settings" && (
        <div style={{ flexShrink: 0, padding: "9px 24px", borderBottom: "1px solid rgba(217,119,6,0.25)", background: "rgba(217,119,6,0.06)", display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "#b45309" }}>
          <span>💡</span>
          <span style={{ flex: 1 }}>
            {openProposals.length} suggestion{openProposals.length > 1 ? "s" : ""} to keep your brain accurate
          </span>
          <button type="button" onClick={() => setTab("settings")} style={{ background: "none", border: "none", color: "inherit", fontWeight: 600, cursor: "pointer", fontSize: 12, textDecoration: "underline", padding: 0 }}>
            Review →
          </button>
        </div>
      )}

      {/* ── tab content ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "26px 24px 40px" }}>

        {/* ━━━ ASK ━━━ */}
        {tab === "ask" && (
          <div style={{ maxWidth: 720, margin: "0 auto", display: "grid", gap: 20 }}>
            <div style={{ textAlign: "center", marginTop: 18 }}>
              <div style={{ fontSize: 26, fontWeight: 600, color: "var(--fg)", letterSpacing: "-0.02em" }}>
                Ask your company anything
              </div>
              <div style={{ fontSize: 13, color: "var(--fm)", marginTop: 6 }}>
                Answers come from your synced tools and pinned notes, with sources cited.
              </div>
            </div>

            <form onSubmit={e => ask(undefined, e)} style={{ display: "flex", gap: 8 }}>
              <input
                className="f-input"
                value={askQuestion}
                onChange={e => setAskQuestion(e.target.value)}
                placeholder="e.g. What did we decide about pricing?"
                style={{ fontSize: 15, padding: "14px 18px", borderRadius: 12 }}
                autoFocus
              />
              <button type="submit" disabled={asking || !askQuestion.trim()} className="btn pri"
                style={{ minHeight: 50, fontSize: 14, paddingInline: 26, borderRadius: 12, flexShrink: 0 }}>
                {asking ? "Thinking…" : "Ask"}
              </button>
            </form>

            {/* suggested questions */}
            {!askAnswer && !asking && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                {SUGGESTED_QUESTIONS.map(q => (
                  <button key={q} type="button" onClick={() => ask(q)}
                    style={{
                      fontSize: 12, color: "var(--fd)", background: "var(--surface)",
                      border: "1px solid var(--bd2)", borderRadius: 999, padding: "8px 16px",
                      cursor: "pointer",
                    }}>
                    {q}
                  </button>
                ))}
              </div>
            )}

            {/* answer */}
            {askAnswer && (
              <Card style={{ padding: "20px 22px" }}>
                <div style={{ color: "var(--fg)", fontSize: 14, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                  {askAnswer}
                </div>
                {askConfidence !== null && (
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16 }}>
                    <div style={{ flex: 1, maxWidth: 160, height: 4, background: "var(--bd)", borderRadius: 999, overflow: "hidden" }}>
                      <div style={{
                        height: "100%", width: `${Math.round(askConfidence * 100)}%`, borderRadius: 999,
                        background: askConfidence > 0.7 ? "#16a34a" : askConfidence > 0.4 ? "#d97706" : "#dc2626",
                      }} />
                    </div>
                    <span style={{ fontSize: 11, color: "var(--fm)" }}>
                      {Math.round(askConfidence * 100)}% confident
                    </span>
                  </div>
                )}
                {askCitations.length > 0 && (
                  <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--bd)", display: "grid", gap: 6 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                      Sources
                    </div>
                    {askCitations.slice(0, 6).map(cit => (
                      <div key={cit.record_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--fd)" }}>
                        <span style={{ flexShrink: 0, fontSize: 12 }}>{SOURCE_ICONS[cit.source] ?? "📌"}</span>
                        {cit.url ? (
                          <a href={cit.url} target="_blank" rel="noopener noreferrer"
                            style={{ color: "var(--blue)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {cit.title}
                          </a>
                        ) : (
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cit.title}</span>
                        )}
                        {cit.canonical && <span style={{ color: "#16a34a", flexShrink: 0, fontSize: 10 }}>✓ source of truth</span>}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            )}

            {records.length === 0 && !askAnswer && (
              <div style={{ textAlign: "center", color: "var(--fm)", fontSize: 12.5, lineHeight: 1.7, marginTop: 8 }}>
                Your brain is empty so far.{" "}
                <button type="button" onClick={() => setTab("knowledge")} style={{ background: "none", border: "none", color: "var(--blue)", cursor: "pointer", fontSize: 12.5, padding: 0, fontWeight: 600, textDecoration: "underline" }}>
                  Connect a source or add a note →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ━━━ KNOWLEDGE (memory + sources) ━━━ */}
        {tab === "knowledge" && (
          <div style={{ maxWidth: 860, margin: "0 auto", display: "grid", gap: 28 }}>

            {/* connected sources strip */}
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
                <SectionTitle
                  title="Connected sources"
                  sub="Click a source to connect it. Selected sources are included when you sync."
                />
                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" onClick={importSources} disabled={importing} className="btn" style={{ minHeight: 34, fontSize: 12 }}>
                    {importing ? "Importing…" : "Import records"}
                  </button>
                  <button type="button" onClick={sync} disabled={syncing} className="btn pri" style={{ minHeight: 34, fontSize: 12 }}>
                    {syncing ? "Syncing…" : "Sync now"}
                  </button>
                </div>
              </div>

              {importSummary && (
                <div style={{ fontSize: 12, color: "var(--fd)", padding: "9px 14px", border: "1px solid var(--bd)", borderRadius: 9, background: "var(--s2)", marginBottom: 12 }}>
                  {importSummary}
                </div>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
                {sources.map(source => {
                  const sel = selectedSources.includes(source.key);
                  const conn = isConnected(source);
                  return (
                    <div key={source.key} style={{
                      border: `1px solid ${sel ? "var(--bb)" : "var(--bd)"}`,
                      background: sel ? "var(--bdim)" : "var(--surface)",
                      borderRadius: 11, padding: "11px 12px",
                      display: "flex", flexDirection: "column", gap: 7,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <span style={{ fontSize: 15 }}>{SOURCE_ICONS[source.key] ?? "🔌"}</span>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {source.label}
                        </span>
                        <span style={{ width: 7, height: 7, borderRadius: 999, background: statusColor(source.status), flexShrink: 0 }} />
                      </div>
                      <div style={{ fontSize: 10.5, color: "var(--fm)" }}>
                        {conn ? `${source.record_count} records` : source.status === "planned" ? "Coming soon" : "Not connected"}
                      </div>
                      <div style={{ display: "flex", gap: 5, marginTop: "auto" }}>
                        <button
                          type="button"
                          onClick={() => setSelectedSources(prev => sel ? prev.filter(s => s !== source.key) : [...prev, source.key])}
                          style={{
                            flex: 1, fontSize: 10, fontWeight: 600, padding: "4px 0", borderRadius: 6,
                            border: `1px solid ${sel ? "var(--blue)" : "var(--bd2)"}`,
                            background: sel ? "var(--blue)" : "transparent",
                            color: sel ? "#fff" : "var(--fm)", cursor: "pointer",
                          }}>
                          {sel ? "✓ In sync" : "Include"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConnectKey(source.key)}
                          style={{
                            fontSize: 10, fontWeight: 600, padding: "4px 9px", borderRadius: 6,
                            border: "1px solid var(--bd2)", background: "transparent",
                            color: conn ? "#16a34a" : "var(--blue)", cursor: "pointer",
                          }}>
                          {conn ? "✓" : "Connect"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* records */}
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
                <SectionTitle
                  title={`Saved knowledge (${records.length})`}
                  sub="Decisions, facts, and notes — everything agents can reference."
                />
                <button
                  type="button"
                  onClick={() => setPinOpen(v => !v)}
                  className={`btn${pinOpen ? "" : " pri"}`}
                  style={{ minHeight: 34, fontSize: 12, flexShrink: 0 }}
                >
                  {pinOpen ? "Cancel" : "+ Add note"}
                </button>
              </div>

              {pinOpen && (
                <form onSubmit={addRecord}
                  style={{ border: "1px solid var(--bb)", background: "var(--bdim)", borderRadius: 12, padding: 16, display: "grid", gap: 10, marginBottom: 14 }}>
                  <input
                    className="f-input"
                    value={draft.title}
                    onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
                    placeholder="Title — e.g. Pricing decision, March"
                    style={{ fontSize: 13 }}
                    autoFocus
                  />
                  <textarea
                    className="f-input f-ta"
                    value={draft.content}
                    onChange={e => setDraft(d => ({ ...d, content: e.target.value }))}
                    placeholder="What should everyone — including your agents — know?"
                    rows={4}
                    style={{ resize: "none", minHeight: 100, fontSize: 12.5 }}
                  />
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 12, color: "var(--fd)" }}>
                      <input
                        type="checkbox"
                        checked={draft.canonical}
                        onChange={e => setDraft(d => ({ ...d, canonical: e.target.checked }))}
                        style={{ accentColor: "var(--blue)" }}
                      />
                      This is the official source of truth
                    </label>
                    <button
                      type="submit"
                      disabled={loading || !draft.title.trim() || !draft.content.trim()}
                      className="btn pri"
                      style={{ minHeight: 34, fontSize: 12 }}
                    >
                      {loading ? "Saving…" : "Save note"}
                    </button>
                  </div>
                </form>
              )}

              <form onSubmit={search} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input
                  className="f-input"
                  value={query}
                  onChange={e => { setQuery(e.target.value); if (!e.target.value.trim()) { setResults([]); setSearched(false); } }}
                  placeholder="Search your knowledge…"
                  style={{ fontSize: 12.5 }}
                />
                <button type="submit" disabled={loading || !query.trim()} className="btn" style={{ minHeight: 38, fontSize: 12, flexShrink: 0 }}>
                  {loading ? "…" : "Search"}
                </button>
              </form>

              <div style={{ display: "grid", gap: 8 }}>
                {shownRecords.length === 0 && (
                  <div style={{ color: "var(--fm)", fontSize: 12.5, padding: "24px 0", textAlign: "center", lineHeight: 1.6 }}>
                    {searched && query.trim()
                      ? "Nothing matched that search."
                      : "Nothing saved yet. Connect a source above, or add your first note."}
                  </div>
                )}
                {shownRecords.map(r => <RecordCard key={r.id} record={r} />)}
              </div>
            </div>
          </div>
        )}

        {/* ━━━ MAP ━━━ */}
        {tab === "map" && (
          <div style={{ maxWidth: 980, margin: "0 auto" }}>
            <KnowledgeMap
              graph={graph}
              loading={graphLoading}
              rebuilding={graphRebuilding}
              onReload={loadGraph}
              onRebuild={rebuildGraph}
            />
          </div>
        )}

        {/* ━━━ SETTINGS ━━━ */}
        {tab === "settings" && (
          <div style={{ maxWidth: 720, margin: "0 auto", display: "grid", gap: 20 }}>

            {/* suggestions */}
            <div>
              <SectionTitle
                title={openProposals.length > 0 ? `Suggestions (${openProposals.length})` : "Suggestions"}
                sub="Astra flags stale records, contradictions, and gaps — review them here."
              />
              {openProposals.length > 0 ? (
                <div style={{ display: "grid", gap: 10 }}>
                  {openProposals.slice(0, 6).map(p => (
                    <SuggestionCard key={p.id} proposal={p} recordsById={recordsById} onUpdate={updateProposal} />
                  ))}
                </div>
              ) : (
                <Card style={{ padding: "16px 18px", color: "var(--fm)", fontSize: 12.5 }}>
                  ✓ All clear — no open suggestions.
                </Card>
              )}
              <button type="button" onClick={maintain} disabled={maintaining} className="btn" style={{ minHeight: 34, fontSize: 12, marginTop: 10 }}>
                {maintaining ? "Checking…" : "Run health check now"}
              </button>
              {(brain?.maintenance?.stale_count || brain?.maintenance?.contradiction_count) ? (
                <div style={{ fontSize: 11.5, color: "var(--fm)", marginTop: 7 }}>
                  Last check: {brain?.maintenance?.stale_count ?? 0} stale record{(brain?.maintenance?.stale_count ?? 0) !== 1 ? "s" : ""},{" "}
                  {brain?.maintenance?.contradiction_count ?? 0} contradiction{(brain?.maintenance?.contradiction_count ?? 0) !== 1 ? "s" : ""}.
                </div>
              ) : null}
            </div>

            {/* auto-sync */}
            <div>
              <SectionTitle
                title="Automatic sync"
                sub="Keep the brain fresh by pulling from your sources on a schedule."
              />
              <Card style={{ padding: "16px 18px", display: "grid", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => configureContinuousSync(!(brain?.sync?.enabled))}
                    disabled={continuousSyncing}
                    style={{
                      width: 44, height: 24, borderRadius: 999, border: "none", cursor: "pointer",
                      background: brain?.sync?.enabled ? "var(--blue)" : "var(--bd2)",
                      position: "relative", transition: "background .18s", flexShrink: 0,
                    }}
                    aria-label="Toggle automatic sync"
                  >
                    <span style={{
                      position: "absolute", top: 3, left: brain?.sync?.enabled ? 23 : 3,
                      width: 18, height: 18, borderRadius: 999, background: "#fff",
                      transition: "left .18s", boxShadow: "0 1px 3px rgba(0,0,0,.2)",
                    }} />
                  </button>
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>
                    {brain?.sync?.enabled ? "On" : "Off"}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--fm)" }}>· every</span>
                  <input
                    type="number" min={5} max={1440}
                    value={syncInterval}
                    onChange={e => setSyncInterval(Number(e.target.value))}
                    className="f-input"
                    style={{ width: 72 }}
                    aria-label="Sync interval minutes"
                  />
                  <span style={{ fontSize: 12, color: "var(--fm)" }}>minutes</span>
                  <button type="button" onClick={runContinuousSyncNow}
                    disabled={continuousSyncing} className="btn" style={{ minHeight: 32, fontSize: 11, marginLeft: "auto" }}>
                    {continuousSyncing ? "Running…" : "Run once now"}
                  </button>
                </div>

                <div style={{ fontSize: 11.5, color: "var(--fm)", lineHeight: 1.6 }}>
                  {brain?.sync?.last_run_at ? `Last run ${brain.sync.last_run_at}.` : "Hasn't run yet."}
                  {brain?.sync?.next_run_at ? ` Next run ${brain.sync.next_run_at}.` : ""}
                  {scheduler ? ` Scheduler ${scheduler.running ? "running" : "stopped"}.` : ""}
                </div>

                {brain?.sync?.last_error && (
                  <div style={{ border: "1px solid rgba(192,57,43,0.25)", background: "rgba(192,57,43,0.06)", borderRadius: 9, padding: "9px 12px", color: "#c0392b", fontSize: 12 }}>
                    {brain.sync.last_error}
                  </div>
                )}

                {(brain?.sync?.history?.length ?? 0) > 0 && (
                  <div style={{ borderTop: "1px solid var(--bd)", paddingTop: 10, display: "grid", gap: 5 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 3 }}>
                      Recent runs
                    </div>
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
              </Card>
            </div>

          </div>
        )}
      </div>

      {/* ── connect modal ── */}
      {connectSource && (
        <ConnectModal
          source={connectSource}
          values={credentialValues[connectSource.key] ?? {}}
          saving={savingCredential}
          onChange={(field, value) => {
            setCredentialValues(prev => ({
              ...prev,
              [connectSource.key]: { ...(prev[connectSource.key] ?? {}), [field]: value },
            }));
          }}
          onSave={saveConnectCredential}
          onClose={() => setConnectKey(null)}
        />
      )}
    </div>
  );
}
