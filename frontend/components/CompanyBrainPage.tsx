"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ServiceLogo from "@/components/ServiceLogo";
import { useCompany } from "@/lib/company-context";
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
  discord: "◎", slack: "◎", github: "●", linear: "◈", notion: "▷",
  google_drive: "△", google_workspace: "△", gmail: "◻",
  confluence: "▦", zendesk: "◈", granola: "◎", astra_vault: "◇",
};

const SUGGESTED_QUESTIONS = [
  "What should the team prioritize this week?",
  "What decisions have we made recently?",
  "What do we know about our customers?",
  "Where is the product roadmap headed?",
];

type BrainView = "main" | "map" | "settings";

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
          <ServiceLogo serviceKey={record.source} label={record.source} size={16} fallback={SOURCE_ICONS[record.source] ?? "◇"} />
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
    <div onClick={onClose} className="astra-modal-backdrop" style={{ zIndex: 200 }}>
      <div onClick={e => e.stopPropagation()} className="astra-modal-shell" style={{ maxWidth: 500 }}>
        <div className="astra-modal-panel">
          <div className="astra-modal-header">
            <div className="astra-modal-header-row">
              <div>
                <div className="astra-modal-eyebrow">knowledge source</div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <ServiceLogo serviceKey={source.key} label={source.label} size={26} fallback={SOURCE_ICONS[source.key] ?? "◇"} />
                  <div>
                    <h2 className="astra-modal-title" style={{ fontSize: 24 }}>{source.label}</h2>
                    <div style={{ fontSize: 11, color: isConnected(source) ? "#16a34a" : "var(--fm)", marginTop: 4 }}>
                      {isConnected(source) ? "✓ Connected" : source.status === "planned" ? "Coming soon" : "Not connected"}
                    </div>
                  </div>
                </div>
                <p className="astra-modal-sub">{source.notes || source.setup_hint || "Add your credentials to start syncing."}</p>
              </div>
              <button onClick={onClose} className="astra-modal-close" aria-label="Close source modal">×</button>
            </div>
          </div>

          <div className="astra-modal-body">
            {source.setup_hint && source.notes !== source.setup_hint && (
              <p style={{ color: "var(--fm)", fontSize: 11.5, lineHeight: 1.5, margin: 0 }}>{source.setup_hint}</p>
            )}
            {source.setup_url && (
              <a
                href={source.setup_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--blue)", fontSize: 12, width: "fit-content", fontWeight: 500 }}
              >
                Where do I find this? →
              </a>
            )}
            {fields.length > 0 ? (
              <div className="astra-modal-card" style={{ padding: 18, display: "grid", gap: 10 }}>
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
                <div className="astra-modal-actions" style={{ paddingTop: 12 }}>
                  <button type="button" onClick={onClose} className="btn" style={{ minHeight: 38, fontSize: 13 }}>
                    Cancel
                  </button>
                  <button type="button" onClick={onSave} disabled={saving || !canSave} className="btn pri" style={{ minHeight: 38, fontSize: 13 }}>
                    {saving ? "Connecting…" : "Connect"}
                  </button>
                </div>
              </div>
            ) : source.importer === false ? (
              <div className="astra-modal-card" style={{ color: "var(--fm)", fontSize: 12, padding: "14px 16px" }}>
                This source isn&apos;t available yet — but you can still reference it in manual notes.
              </div>
            ) : null}
          </div>
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
  const communities = useMemo(
    () => Array.from(new Set(visibleNodes.map(n => n.community_id || "unassigned"))),
    [visibleNodes]
  );
  const layout = useMemo(() => {
    const width = 720;
    const height = 360;
    const cx = width / 2;
    const cy = height / 2;
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
  }, [visibleNodes, communities]);
  // Legend: each color group named after its most important entity.
  const legend = useMemo(() =>
    communities.slice(0, 8).map((cid, ci) => {
      const members = visibleNodes.filter(n => (n.community_id || "unassigned") === cid);
      const top = [...members].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0))[0];
      return {
        id: cid,
        color: GRAPH_COLORS[ci % GRAPH_COLORS.length],
        label: top ? top.name.slice(0, 22) : "Other",
        count: members.length,
      };
    }),
    [communities, visibleNodes]
  );
  // Entities directly connected to the selected node — the "why is this here" answer.
  const neighbors = useMemo(() => {
    if (!selected) return [];
    const ids = new Set<string>();
    for (const e of visibleEdges) {
      if (e.source === selected.id) ids.add(e.target);
      if (e.target === selected.id) ids.add(e.source);
    }
    return visibleNodes.filter(n => ids.has(n.id)).slice(0, 10);
  }, [selected, visibleEdges, visibleNodes]);
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
                  {(active || Number(node.importance || 0) >= 2) && (
                    <text x={pos.radius + 6} y={4} fill="var(--fg)" fontSize="10"
                      fontFamily="var(--font-instrument), sans-serif" fontWeight={active ? 600 : 400}
                      style={{ paintOrder: "stroke", stroke: "rgba(255,255,255,0.85)", strokeWidth: 3 }}>
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
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 12px", borderTop: "1px solid var(--bd)", fontSize: 11, color: "var(--fm)", flexWrap: "wrap" }}>
            {/* legend — color groups named after their main entity */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", flex: 1, minWidth: 0 }}>
              {legend.map(g => (
                <span key={g.id} style={{ display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap" }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: g.color, flexShrink: 0 }} />
                  <span style={{ color: "var(--fd)", fontWeight: 500 }}>{g.label}</span>
                  <span style={{ color: "var(--fm)" }}>({g.count})</span>
                </span>
              ))}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
              <span style={{ fontSize: 10 }}>scroll to zoom · drag to pan</span>
              <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.min(4, v.scale * 1.2) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>+</button>
              <button type="button" onClick={() => setView(v => ({ ...v, scale: Math.max(0.4, v.scale * 0.83) }))} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>−</button>
              <button type="button" onClick={() => setView({ scale: 1, tx: 0, ty: 0 })} className="btn" style={{ minHeight: 24, fontSize: 11, padding: "0 8px" }}>Reset</button>
            </div>
          </div>
        )}
      </Card>

      {/* how to read this */}
      {visibleNodes.length > 0 && (
        <div style={{ fontSize: 11.5, color: "var(--fm)", lineHeight: 1.6, padding: "0 2px" }}>
          Each dot is a person, product, or concept found in your knowledge. Bigger dots matter more,
          lines show how they&apos;re related, and colors group related topics. Click any dot to see its connections.
        </div>
      )}

      {visibleNodes.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Card style={{ padding: "13px 15px", minHeight: 88 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", marginBottom: 7, textTransform: "uppercase", letterSpacing: ".06em" }}>Selected</div>
            {selected ? (
              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ color: "var(--fg)", fontSize: 13, fontWeight: 600 }}>{selected.name}</div>
                <div style={{ color: "var(--fd)", fontSize: 11.5, lineHeight: 1.45 }}>{selected.description || selected.type}</div>
                {neighbors.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, color: "var(--fm)", marginBottom: 4 }}>Connected to:</div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {neighbors.map(n => (
                        <button type="button" key={n.id} onClick={() => setSelectedId(n.id)}
                          className="pill" style={{ letterSpacing: 0, cursor: "pointer" }}>
                          {n.name.slice(0, 20)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
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
  const { founderId, companyId, activeCompany } = useCompany();

  /* ── state (all original features preserved) ── */
  const [view, setView] = useState<BrainView>("main");
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
      const data = await getCompanyBrain(founderId, "", companyId);
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
  }, [companyId, founderId]);

  const loadGraph = useCallback(async () => {
    setGraphLoading(true);
    try {
      const data = await getGraphRagVisualization(founderId, companyId);
      setGraph(data);
    } catch {
      setGraph(null);
    } finally {
      setGraphLoading(false);
    }
  }, [companyId, founderId]);

  useEffect(() => {
    const t = window.setTimeout(() => { void loadBrain(); }, 0);
    return () => window.clearTimeout(t);
  }, [loadBrain]);

  useEffect(() => {
    const t = window.setTimeout(() => { void loadGraph(); }, 0);
    return () => window.clearTimeout(t);
  }, [loadGraph]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setResults([]);
      setSearched(false);
      setAskAnswer(null);
      setAskCitations([]);
      setImportSummary(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [companyId]);

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
  const shownRecords = searched && query.trim() ? results : records;

  /* ── actions (all original handlers preserved) ── */
  async function sync() {
    setSyncing(true);
    setError(null);
    try {
      await syncCompanyBrain(founderId, selectedSources, companyId);
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
      const result = await importCompanyBrainSources(founderId, selectedSources, 20, companyId);
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
      await syncCompanyBrain(founderId, [connectSource.key], companyId);
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
      await configureCompanyBrainSync(
        founderId,
        { enabled, sources: selectedSources, interval_minutes: syncInterval },
        companyId,
      );
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
      await runCompanyBrainSync(founderId, selectedSources, companyId);
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
      const data = await searchCompanyBrain(founderId, query.trim(), 10, "", companyId);
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
      const data = await askCompanyBrain(founderId, q, 8, companyId);
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
      }, companyId);
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
      await maintainCompanyBrain(founderId, companyId);
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
      await syncGraphRag(founderId, companyId);
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
      await updateBrainProposal(founderId, proposalId, status, companyId);
      await loadBrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update suggestion.");
    }
  }

  /* ─── record categories ─── */
  const factRecords = useMemo(() => records.filter(r => r.kind === "fact"), [records]);
  const docRecords = useMemo(() => records.filter(r => r.kind === "document" || r.kind === "file"), [records]);
  const voiceRecords = useMemo(() => records.filter(r => r.kind === "brand_voice" || r.kind === "voice"), [records]);
  const connectedSources = useMemo(() => sources.filter(isConnected), [sources]);

  /* ─── knowledge health ─── */
  const healthPct = useMemo(() => {
    if (sources.length === 0) return 0;
    return Math.round((connectedSources.length / sources.length) * 100);
  }, [sources, connectedSources]);

  /* ─── render ─── */
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* ── header: title + subtitle + actions ── */}
      <div style={{ flexShrink: 0, borderBottom: "1px solid var(--border)", background: "var(--bg)" }}>
        <div style={{ padding: "20px 24px 16px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
          <div>
            {view !== "main" && (
              <button type="button" onClick={() => setView("main")} style={{ background: "none", border: "none", color: "var(--text-3)", fontSize: 12, cursor: "pointer", padding: "0 0 6px", display: "flex", alignItems: "center", gap: 4 }}>
                ← Company Brain
              </button>
            )}
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.01em", margin: 0, lineHeight: 1.2 }}>
              {view === "map" ? "Knowledge Map" : view === "settings" ? "Settings" : "Company Brain"}
            </h1>
            {view === "main" && (
              <p style={{ margin: "3px 0 0", fontSize: 13, color: "var(--text-3)" }}>
                Ask anything, or browse what Astra knows below.
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexShrink: 0, paddingTop: 2 }}>
            {view === "main" && (
              <>
                <button type="button" onClick={() => setView("map")}
                  style={{ fontSize: 12, fontWeight: 500, padding: "7px 14px", border: "1px solid var(--border)", background: "transparent", color: "var(--text-2)", borderRadius: 8, cursor: "pointer" }}>
                  View knowledge map
                </button>
                <button type="button" onClick={() => setPinOpen(true)}
                  style={{ fontSize: 12, fontWeight: 600, padding: "7px 14px", border: "none", background: "#002EFF", color: "#fff", borderRadius: 8, cursor: "pointer" }}>
                  + Add knowledge
                </button>
                <button type="button" onClick={() => setView("settings")}
                  style={{ fontSize: 12, fontWeight: 500, padding: "7px 14px", border: "1px solid var(--border)", background: "transparent", color: "var(--text-2)", borderRadius: 8, cursor: "pointer", position: "relative" }}>
                  ⚙{openProposals.length > 0 && <span style={{ position: "absolute", top: -4, right: -4, width: 8, height: 8, borderRadius: 999, background: "#d97706" }} />}
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── error banner ── */}
      {error && (
        <div style={{ flexShrink: 0, padding: "10px 24px", borderBottom: "1px solid rgba(192,57,43,0.22)", background: "rgba(192,57,43,0.07)", color: "#c0392b", fontSize: 12, display: "flex", alignItems: "center" }}>
          <span style={{ flex: 1 }}>{error}</span>
          <button type="button" onClick={() => setError(null)} style={{ color: "inherit", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>✕</button>
        </div>
      )}

      {/* ── suggestions banner ── */}
      {openProposals.length > 0 && view !== "settings" && (
        <div style={{ flexShrink: 0, padding: "9px 24px", borderBottom: "1px solid rgba(217,119,6,0.25)", background: "rgba(217,119,6,0.06)", display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "#b45309" }}>
          <span>◈</span>
          <span style={{ flex: 1 }}>
            {openProposals.length} suggestion{openProposals.length > 1 ? "s" : ""} to keep your brain accurate
          </span>
          <button type="button" onClick={() => setView("settings")} style={{ background: "none", border: "none", color: "inherit", fontWeight: 600, cursor: "pointer", fontSize: 12, textDecoration: "underline", padding: 0 }}>
            Review →
          </button>
        </div>
      )}

      {/* ── content ── */}
      <div style={{ flex: 1, overflowY: "auto" }}>

        {/* ━━━ MAP VIEW ━━━ */}
        {view === "map" && (
          <div style={{ padding: "24px", maxWidth: 980, margin: "0 auto" }}>
            <KnowledgeMap graph={graph} loading={graphLoading} rebuilding={graphRebuilding} onReload={loadGraph} onRebuild={rebuildGraph} />
          </div>
        )}

        {/* ━━━ SETTINGS VIEW ━━━ */}
        {view === "settings" && (
          <div style={{ padding: "24px", maxWidth: 720, margin: "0 auto", display: "grid", gap: 20 }}>
            <div>
              <SectionTitle title={openProposals.length > 0 ? `Suggestions (${openProposals.length})` : "Suggestions"} sub="Astra flags stale records, contradictions, and gaps." />
              {openProposals.length > 0 ? (
                <div style={{ display: "grid", gap: 10 }}>
                  {openProposals.slice(0, 6).map(p => <SuggestionCard key={p.id} proposal={p} recordsById={recordsById} onUpdate={updateProposal} />)}
                </div>
              ) : (
                <Card style={{ padding: "16px 18px", color: "var(--fm)", fontSize: 12.5 }}>✓ All clear — no open suggestions.</Card>
              )}
              <button type="button" onClick={maintain} disabled={maintaining} className="btn" style={{ minHeight: 34, fontSize: 12, marginTop: 10 }}>
                {maintaining ? "Checking…" : "Run health check now"}
              </button>
              {(brain?.maintenance?.stale_count || brain?.maintenance?.contradiction_count) ? (
                <div style={{ fontSize: 11.5, color: "var(--fm)", marginTop: 7 }}>
                  Last check: {brain?.maintenance?.stale_count ?? 0} stale, {brain?.maintenance?.contradiction_count ?? 0} contradictions.
                </div>
              ) : null}
            </div>
            <div>
              <SectionTitle title="Automatic sync" sub="Keep the brain fresh on a schedule." />
              <Card style={{ padding: "16px 18px", display: "grid", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <button type="button" onClick={() => configureContinuousSync(!(brain?.sync?.enabled))} disabled={continuousSyncing}
                    style={{ width: 44, height: 24, borderRadius: 999, border: "none", cursor: "pointer", background: brain?.sync?.enabled ? "var(--blue)" : "var(--bd2)", position: "relative", transition: "background .18s", flexShrink: 0 }}
                    aria-label="Toggle automatic sync">
                    <span style={{ position: "absolute", top: 3, left: brain?.sync?.enabled ? 23 : 3, width: 18, height: 18, borderRadius: 999, background: "#fff", transition: "left .18s", boxShadow: "0 1px 3px rgba(0,0,0,.2)" }} />
                  </button>
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>{brain?.sync?.enabled ? "On" : "Off"}</span>
                  <span style={{ fontSize: 12, color: "var(--fm)" }}>· every</span>
                  <input type="number" min={5} max={1440} value={syncInterval} onChange={e => setSyncInterval(Number(e.target.value))} className="f-input" style={{ width: 72 }} aria-label="Sync interval minutes" />
                  <span style={{ fontSize: 12, color: "var(--fm)" }}>minutes</span>
                  <button type="button" onClick={runContinuousSyncNow} disabled={continuousSyncing} className="btn" style={{ minHeight: 32, fontSize: 11, marginLeft: "auto" }}>
                    {continuousSyncing ? "Running…" : "Run once now"}
                  </button>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--fm)", lineHeight: 1.6 }}>
                  {brain?.sync?.last_run_at ? `Last run ${brain.sync.last_run_at}.` : "Hasn't run yet."}
                  {brain?.sync?.next_run_at ? ` Next run ${brain.sync.next_run_at}.` : ""}
                </div>
                {brain?.sync?.last_error && (
                  <div style={{ border: "1px solid rgba(192,57,43,0.25)", background: "rgba(192,57,43,0.06)", borderRadius: 9, padding: "9px 12px", color: "#c0392b", fontSize: 12 }}>{brain.sync.last_error}</div>
                )}
              </Card>
            </div>
          </div>
        )}

        {/* ━━━ MAIN VIEW ━━━ */}
        {view === "main" && (
          <>
            {/* search + ask */}
            <div style={{ padding: "32px 24px 28px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ maxWidth: 680, margin: "0 auto" }}>
                <form onSubmit={e => ask(undefined, e)} style={{ position: "relative" }}>
                  <input className="f-input" value={askQuestion} onChange={e => setAskQuestion(e.target.value)}
                    placeholder="What should I do next?" autoFocus
                    style={{ fontSize: 15, padding: "16px 56px 16px 20px", borderRadius: 14, width: "100%", boxSizing: "border-box", border: "1px solid var(--border)" }} />
                  <button type="submit" disabled={asking || !askQuestion.trim()}
                    style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", width: 34, height: 34, borderRadius: "50%", background: askQuestion.trim() ? "#002EFF" : "var(--bg-sunken)", border: "none", cursor: askQuestion.trim() ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", transition: "background .15s" }}>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M7 12V2M2 7l5-5 5 5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </button>
                </form>
                {!askAnswer && !asking && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 14 }}>
                    {SUGGESTED_QUESTIONS.map(q => (
                      <button key={q} type="button" onClick={() => ask(q)}
                        style={{ fontSize: 12, color: "var(--text-3)", background: "transparent", border: "1px solid var(--border)", borderRadius: 999, padding: "7px 16px", cursor: "pointer" }}>
                        {q}
                      </button>
                    ))}
                  </div>
                )}
                {asking && <div style={{ textAlign: "center", color: "var(--text-3)", fontSize: 13, marginTop: 20 }}>Thinking…</div>}
                {askAnswer && (
                  <Card style={{ padding: "20px 22px", marginTop: 20 }}>
                    <div style={{ color: "var(--fg)", fontSize: 14, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{askAnswer}</div>
                    {askConfidence !== null && (
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16 }}>
                        <div style={{ flex: 1, maxWidth: 160, height: 4, background: "var(--bd)", borderRadius: 999, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${Math.round(askConfidence * 100)}%`, borderRadius: 999, background: askConfidence > 0.7 ? "#16a34a" : askConfidence > 0.4 ? "#d97706" : "#dc2626" }} />
                        </div>
                        <span style={{ fontSize: 11, color: "var(--fm)" }}>{Math.round(askConfidence * 100)}% confident</span>
                      </div>
                    )}
                    {askCitations.length > 0 && (
                      <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--bd)", display: "grid", gap: 6 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".06em" }}>Sources</div>
                        {askCitations.slice(0, 6).map(cit => (
                          <div key={cit.record_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--fd)" }}>
                            <span style={{ flexShrink: 0 }}>{SOURCE_ICONS[cit.source] ?? "📌"}</span>
                            {cit.url ? <a href={cit.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--blue)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cit.title}</a>
                              : <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cit.title}</span>}
                            {cit.canonical && <span style={{ color: "#16a34a", flexShrink: 0, fontSize: 10 }}>✓ source of truth</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                )}
              </div>
            </div>

            {/* knowledge health */}
            <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 16 }}>
              <svg width={44} height={44} viewBox="0 0 44 44" style={{ flexShrink: 0 }}>
                <circle cx={22} cy={22} r={17} fill="none" stroke="rgba(202,210,228,0.12)" strokeWidth={5} />
                <circle cx={22} cy={22} r={17} fill="none" stroke="#2F55FF" strokeWidth={5}
                  strokeDasharray={`${(healthPct / 100) * 2 * Math.PI * 17} ${2 * Math.PI * 17}`}
                  strokeLinecap="round" transform="rotate(-90 22 22)" />
                <text x={22} y={27} textAnchor="middle" fontSize={11} fontWeight={700} fill="var(--text)">{healthPct}%</text>
              </svg>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>Knowledge health</div>
                <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 1 }}>
                  {connectedSources.length} of {sources.length} sources connected · {records.length} records
                </div>
              </div>
              {openProposals.length > 0 && (
                <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                  {openProposals.slice(0, 2).map(p => (
                    <button key={p.id} type="button" onClick={() => setView("settings")}
                      style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(217,119,6,0.4)", background: "rgba(217,119,6,0.1)", color: "#d97706", cursor: "pointer" }}>
                      {p.title?.slice(0, 28) ?? "Suggestion"}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* add note form */}
            {pinOpen && (
              <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--border)", background: "var(--bg-sunken)" }}>
                <form onSubmit={addRecord} style={{ maxWidth: 680, margin: "0 auto", display: "grid", gap: 10 }}>
                  <input className="f-input" value={draft.title} onChange={e => setDraft(d => ({ ...d, title: e.target.value }))} placeholder="Title — e.g. Pricing decision, March" style={{ fontSize: 13 }} autoFocus />
                  <textarea className="f-input f-ta" value={draft.content} onChange={e => setDraft(d => ({ ...d, content: e.target.value }))} placeholder="What should everyone — including your agents — know?" rows={3} style={{ resize: "none", fontSize: 12.5 }} />
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 12, color: "var(--text-2)" }}>
                      <input type="checkbox" checked={draft.canonical} onChange={e => setDraft(d => ({ ...d, canonical: e.target.checked }))} style={{ accentColor: "var(--accent)" }} />
                      Source of truth
                    </label>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button type="button" onClick={() => setPinOpen(false)} className="btn" style={{ minHeight: 32, fontSize: 12 }}>Cancel</button>
                      <button type="submit" disabled={loading || !draft.title.trim() || !draft.content.trim()} className="btn pri" style={{ minHeight: 32, fontSize: 12 }}>
                        {loading ? "Saving…" : "Save"}
                      </button>
                    </div>
                  </div>
                </form>
              </div>
            )}

            {/* 4-column knowledge grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", minHeight: 400 }}>

              {/* ── FACTS ── */}
              <div style={{ borderRight: "1px solid var(--border)", padding: "20px 20px 32px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                    Facts {factRecords.length > 0 && `· ${factRecords.length}`}
                  </span>
                  <button type="button" onClick={() => setPinOpen(true)}
                    style={{ fontSize: 11, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>+ Add</button>
                </div>
                {factRecords.length === 0 && records.length > 0 && (
                  <div style={{ display: "grid", gap: 0 }}>
                    {records.slice(0, 6).map((r, i) => (
                      <div key={r.id} style={{ padding: "10px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 2 }}>{r.source}</div>
                        <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>{r.title}</div>
                      </div>
                    ))}
                  </div>
                )}
                {factRecords.length > 0 && (
                  <div style={{ display: "grid", gap: 0 }}>
                    {factRecords.slice(0, 8).map((r, i) => (
                      <div key={r.id} style={{ padding: "10px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 2 }}>{r.source}</div>
                        <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>{r.title}</div>
                      </div>
                    ))}
                  </div>
                )}
                {records.length === 0 && (
                  <div style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>No facts yet. Add your company's key facts like ICP, pricing, and mission.</div>
                )}
              </div>

              {/* ── DOCUMENTS ── */}
              <div style={{ borderRight: "1px solid var(--border)", padding: "20px 20px 32px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                    Documents {docRecords.length > 0 && `· ${docRecords.length}`}
                  </span>
                  <button type="button" onClick={() => setPinOpen(true)}
                    style={{ fontSize: 11, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>+ Add</button>
                </div>
                {docRecords.length > 0 ? (
                  <div style={{ display: "grid", gap: 0 }}>
                    {docRecords.slice(0, 8).map((r, i) => (
                      <div key={r.id} style={{ padding: "10px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none", display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13, color: "var(--text-3)", flexShrink: 0 }}>□</span>
                        <div style={{ overflow: "hidden" }}>
                          {r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13, color: "var(--text)", fontWeight: 500, textDecoration: "none", display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.title}</a>
                            : <span style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>{r.title}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>No documents yet. Connect Google Drive, Notion, or add files manually.</div>
                )}
              </div>

              {/* ── BRAND VOICE ── */}
              <div style={{ borderRight: "1px solid var(--border)", padding: "20px 20px 32px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>Brand Voice</span>
                  <button type="button" onClick={() => setPinOpen(true)}
                    style={{ fontSize: 11, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>Edit</button>
                </div>
                {voiceRecords.length > 0 ? (
                  <div style={{ display: "grid", gap: 10 }}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {voiceRecords.slice(0, 5).map(r => (
                        <span key={r.id} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, border: "1px solid var(--border)", color: "var(--text-2)", background: "var(--bg-sunken)" }}>{r.title}</span>
                      ))}
                    </div>
                    {voiceRecords[0]?.snippet && <p style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.6, margin: 0, fontStyle: "italic" }}>"{voiceRecords[0].snippet}"</p>}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>No brand voice defined yet. Add tone guidelines so agents write consistently.</div>
                )}
              </div>

              {/* ── CONNECTIONS ── */}
              <div style={{ padding: "20px 20px 32px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                    Connections {connectedSources.length > 0 && `· ${connectedSources.length}`}
                  </span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="button" onClick={sync} disabled={syncing}
                      style={{ fontSize: 11, color: "var(--text-3)", background: "none", border: "none", cursor: syncing ? "default" : "pointer", padding: 0 }}>
                      {syncing ? "Syncing…" : "Sync"}
                    </button>
                  </div>
                </div>
                <div style={{ display: "grid", gap: 0 }}>
                  {connectedSources.length === 0 && (
                    <div style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>No sources connected. Connect Notion, GitHub, or Google Drive to start syncing.</div>
                  )}
                  {connectedSources.slice(0, 8).map((s, i) => (
                    <div key={s.key} style={{ padding: "10px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none", display: "flex", alignItems: "center", gap: 10 }}>
                      <ServiceLogo serviceKey={s.key} label={s.label} size={14} />
                      <div style={{ flex: 1, overflow: "hidden" }}>
                        <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>{s.label}</div>
                        <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                          {s.last_synced_at ? `Synced ${s.last_synced_at}` : `${s.record_count} records`}
                        </div>
                      </div>
                      <button type="button" onClick={() => setConnectKey(s.key)}
                        style={{ fontSize: 10, padding: "3px 8px", borderRadius: 5, border: "1px solid var(--border)", background: "none", color: "var(--text-3)", cursor: "pointer" }}>
                        Edit
                      </button>
                    </div>
                  ))}
                  {sources.filter(s => !isConnected(s) && s.status !== "planned").slice(0, 3).map((s, i) => (
                    <div key={s.key} style={{ padding: "10px 0", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
                      <ServiceLogo serviceKey={s.key} label={s.label} size={14} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, color: "var(--text-3)" }}>{s.label}</div>
                        <div style={{ fontSize: 11, color: "var(--text-3)", opacity: 0.6 }}>Not connected</div>
                      </div>
                      <button type="button" onClick={() => setConnectKey(s.key)}
                        style={{ fontSize: 10, padding: "3px 8px", borderRadius: 5, border: "1px solid rgba(47,85,255,0.35)", background: "rgba(47,85,255,0.08)", color: "#7d8fff", cursor: "pointer" }}>
                        Connect
                      </button>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          </>
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
