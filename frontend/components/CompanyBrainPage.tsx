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
  const [addType, setAddType] = useState<"fact" | "doc" | "source" | "brand">("fact");
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

  const TABS: { key: Tab; label: string }[] = [
    { key: "ask", label: "Ask" },
    { key: "knowledge", label: "Knowledge" },
    { key: "map", label: "Map" },
    { key: "settings", label: "Settings" },
  ];

  /* ─── render ─── */
  const HG = "var(--font-hanken), 'Hanken Grotesk', sans-serif";
  const ACCENT = "#7CFFC6";
  const healthScore = brain
    ? Math.max(0, 100 - ((brain.maintenance?.stale_count ?? 0) * 5 + (brain.maintenance?.contradiction_count ?? 0) * 10 + (brain.maintenance?.missing_canonical_count ?? 0) * 3))
    : null;
  const circumference = 2 * Math.PI * 16;
  const dashOffset = healthScore !== null ? circumference * (1 - healthScore / 100) : circumference * 0.08;
  const factRecords = records.filter(r => r.source === "manual" || r.kind === "note").slice(0, 6);
  const docRecords = records.filter(r => r.url || r.kind === "document" || (r.source !== "manual" && r.source !== "astra_vault")).slice(0, 5);
  const SUGGESTIONS = ["What should I do next?", "Summarize our ICP", "What's missing?"];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", fontFamily: HG }}>

      {/* error banner */}
      {error && (
        <div style={{ flexShrink: 0, padding: "10px 24px", borderBottom: "1px solid rgba(192,57,43,0.22)", background: "rgba(192,57,43,0.07)", color: "#c0392b", fontSize: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ flex: 1 }}>{error}</span>
          <button type="button" onClick={() => setError(null)} style={{ color: "inherit", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>✕</button>
        </div>
      )}

      {/* ── map view ── */}
      {tab === "map" ? (
        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <main style={{ flex: 1, overflow: "auto", padding: "22px 26px", display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <button type="button" onClick={() => setTab("ask")} style={{ background: "none", border: "none", padding: 0, fontSize: 11, color: "#7d8fff", cursor: "pointer", fontWeight: 600, fontFamily: HG }}>← Company Brain</button>
                <h1 style={{ margin: "6px 0 0", fontSize: 20, fontWeight: 700, letterSpacing: "-.01em", color: "#EDF1FB" }}>Knowledge map</h1>
              </div>
              <button type="button" onClick={() => setPinOpen(true)} style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "9px 15px", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: HG }}>+ Add knowledge</button>
            </div>
            <KnowledgeMap graph={graph} loading={graphLoading} rebuilding={graphRebuilding} onReload={loadGraph} onRebuild={rebuildGraph} />
          </main>
          <div style={{ width: 270, flexShrink: 0, background: "#080A12", borderLeft: "1px solid rgba(255,255,255,.07)", padding: 20, display: "flex", flexDirection: "column", gap: 14, overflowY: "auto" }}>
            <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Selected · Facts</div>
            {factRecords.map(f => (
              <div key={f.id} style={{ padding: "8px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
                <div style={{ fontSize: 10.5, color: "#6f7b98" }}>{f.title.slice(0, 30)}</div>
                <div style={{ fontSize: 12.5, color: "#EDF1FB", marginTop: 2 }}>{(f.snippet || f.content).slice(0, 60)}</div>
              </div>
            ))}
            {factRecords.length === 0 && <div style={{ fontSize: 12, color: "#6f7b98" }}>No facts yet.</div>}
            <button type="button" onClick={() => setPinOpen(true)} style={{ marginTop: "auto", textAlign: "center", background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: 10, fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: HG }}>+ Add a fact</button>
          </div>
        </div>
      ) : (

      /* ── main view ── */
      <div style={{ flex: 1, overflowY: "auto", padding: "22px 28px", display: "flex", flexDirection: "column", gap: 14 }}>

        {/* header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 21, fontWeight: 700, letterSpacing: "-.01em", color: "#EDF1FB" }}>Company Brain</h1>
            <div style={{ fontSize: 12, color: "#8A93AD", marginTop: 4 }}>Ask anything, or browse what Astra knows below.</div>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button type="button" onClick={() => setTab("map")} style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "9px 15px", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: HG }}>View knowledge map</button>
            <button type="button" onClick={() => setPinOpen(true)} style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "9px 15px", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: HG }}>+ Add knowledge</button>
          </div>
        </div>

        {/* ask bar */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <form onSubmit={e => ask(undefined, e)} style={{ width: "100%", maxWidth: 600, display: "flex", alignItems: "center", gap: 10, background: "#0A0D17", border: "1px solid rgba(255,255,255,.12)", borderRadius: 13, padding: "11px 8px 11px 18px" }}>
            <input
              value={askQuestion}
              onChange={e => setAskQuestion(e.target.value)}
              placeholder="What should I do next?"
              style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#EDF1FB", fontSize: 13.5, fontFamily: HG }}
            />
            <button type="submit" disabled={asking || !askQuestion.trim()} style={{ width: 32, height: 32, borderRadius: 9, background: "#002EFF", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, opacity: asking || !askQuestion.trim() ? 0.6 : 1 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
            </button>
          </form>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
            {SUGGESTIONS.map(s => (
              <span key={s} onClick={() => ask(s)} style={{ fontSize: 11, color: "#8A93AD", background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", padding: "5px 11px", borderRadius: 20, cursor: "pointer" }}>{s}</span>
            ))}
          </div>
        </div>

        {/* answer / example */}
        <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: "12px 16px" }}>
          <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase", marginBottom: 5 }}>{askAnswer ? "Answer" : "Example answer"}</div>
          {asking ? (
            <div style={{ fontSize: 12, color: "#c3cbe0", lineHeight: 1.55 }}>Thinking…</div>
          ) : askAnswer ? (
            <div style={{ fontSize: 12, color: "#c3cbe0", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>{askAnswer}</div>
          ) : (
            <div style={{ fontSize: 12, color: "#c3cbe0", lineHeight: 1.55 }}>Based on your ICP and last week's outreach results, focus on Series A SaaS founders in fintech — they had a 3x higher reply rate. Your pricing facts are current, but the brain has no info on competitors yet.</div>
          )}
        </div>

        {/* knowledge health */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: "12px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ position: "relative", width: 38, height: 38, flexShrink: 0 }}>
              <svg width="38" height="38" viewBox="0 0 38 38">
                <circle cx="19" cy="19" r="16" fill="none" stroke="rgba(255,255,255,.1)" strokeWidth="4" />
                <circle cx="19" cy="19" r="16" fill="none" stroke={ACCENT} strokeWidth="4" strokeLinecap="round" strokeDasharray={String(circumference)} strokeDashoffset={String(dashOffset)} transform="rotate(-90 19 19)" />
              </svg>
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9.5, fontWeight: 700, color: "#EDF1FB" }}>{healthScore !== null ? `${healthScore}%` : "–"}</div>
            </div>
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "#EDF1FB" }}>Knowledge health</div>
              <div style={{ fontSize: 10.5, color: "#6f7b98", marginTop: 1 }}>{(brain?.maintenance?.stale_count ?? 0) + (brain?.maintenance?.missing_canonical_count ?? 0)} gaps found</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(brain?.maintenance?.stale_count ?? 0) > 0 && <span style={{ fontSize: 10.5, color: "#FFFFA6", background: "rgba(255,255,166,.08)", padding: "5px 11px", borderRadius: 20, fontWeight: 600 }}>Missing: stale records</span>}
            {(brain?.maintenance?.missing_canonical_count ?? 0) > 0 && <span style={{ fontSize: 10.5, color: "#FFFFA6", background: "rgba(255,255,166,.08)", padding: "5px 11px", borderRadius: 20, fontWeight: 600 }}>Missing: canonical facts</span>}
            {(brain?.maintenance?.stale_count ?? 0) === 0 && (brain?.maintenance?.missing_canonical_count ?? 0) === 0 && records.length === 0 && <span style={{ fontSize: 10.5, color: "#FFFFA6", background: "rgba(255,255,166,.08)", padding: "5px 11px", borderRadius: 20, fontWeight: 600 }}>Add your first facts</span>}
          </div>
        </div>

        {/* 4-column grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, flex: 1, minHeight: 0 }}>

          {/* Facts */}
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: 14, display: "flex", flexDirection: "column", gap: 8, overflow: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Facts · {factRecords.length}</div>
              <button type="button" onClick={() => { setAddType("fact"); setPinOpen(true); }} style={{ background: "none", border: "none", padding: 0, color: "#7d8fff", fontSize: 10.5, fontWeight: 600, cursor: "pointer", fontFamily: HG }}>+ Add</button>
            </div>
            {factRecords.map(f => (
              <div key={f.id} style={{ padding: "6px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
                <div style={{ fontSize: 9.5, color: "#6f7b98" }}>{f.title.slice(0, 30)}</div>
                <div style={{ fontSize: 11.5, color: "#EDF1FB", marginTop: 1 }}>{(f.snippet || f.content).slice(0, 60)}</div>
              </div>
            ))}
            {factRecords.length === 0 && <div style={{ fontSize: 11, color: "#6f7b98", paddingTop: 4 }}>No facts yet.</div>}
          </div>

          {/* Documents */}
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: 14, display: "flex", flexDirection: "column", gap: 8, overflow: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Documents · {docRecords.length}</div>
              <button type="button" onClick={() => { setAddType("doc"); setPinOpen(true); }} style={{ background: "none", border: "none", padding: 0, color: "#7d8fff", fontSize: 10.5, fontWeight: 600, cursor: "pointer", fontFamily: HG }}>+ Add</button>
            </div>
            {docRecords.map(d => (
              <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#7d8fff" strokeWidth="2" style={{ flexShrink: 0 }}><path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/></svg>
                <div style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#EDF1FB" }}>{d.title}</div>
              </div>
            ))}
            {docRecords.length === 0 && <div style={{ fontSize: 11, color: "#6f7b98", paddingTop: 4 }}>No documents yet.</div>}
          </div>

          {/* Brand voice */}
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: 14, display: "flex", flexDirection: "column", gap: 8, overflow: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Brand voice</div>
              <button type="button" onClick={() => { setAddType("brand"); setPinOpen(true); }} style={{ background: "none", border: "none", padding: 0, color: "#7d8fff", fontSize: 10.5, fontWeight: 600, cursor: "pointer", fontFamily: HG }}>Edit</button>
            </div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {["Confident", "Clear", "No jargon", "Warm but direct"].map(t => (
                <span key={t} style={{ fontSize: 10, fontWeight: 600, color: ACCENT, background: "rgba(255,255,255,.05)", padding: "4px 9px", borderRadius: 20 }}>{t}</span>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "#8A93AD", lineHeight: 1.55, marginTop: 2 }}>&ldquo;Speak like a knowledgeable teammate, not a brochure.&rdquo;</div>
          </div>

          {/* Connections */}
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 11, padding: 14, display: "flex", flexDirection: "column", gap: 8, overflow: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Connections · {connected}</div>
              <button type="button" onClick={() => { setAddType("source"); setPinOpen(true); }} style={{ background: "none", border: "none", padding: 0, color: "#7d8fff", fontSize: 10.5, fontWeight: 600, cursor: "pointer", fontFamily: HG }}>+ Add</button>
            </div>
            {sources.slice(0, 6).map(s => (
              <div key={s.key} style={{ padding: "6px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: "#EDF1FB" }}>{s.label}</div>
                <div style={{ fontSize: 10, color: "#6f7b98", marginTop: 1 }}>{isConnected(s) ? "Connected" : s.status === "planned" ? "Coming soon" : "Not connected"}</div>
              </div>
            ))}
            {sources.length === 0 && <div style={{ fontSize: 11, color: "#6f7b98", paddingTop: 4 }}>No connections yet.</div>}
          </div>
        </div>

      </div>
      )}

      {/* ── add knowledge modal ── */}
      {pinOpen && (
        <div onClick={() => setPinOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(2,3,8,.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200 }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 560, background: "#0A0D17", border: "1px solid rgba(255,255,255,.12)", borderRadius: 16, padding: 26, display: "flex", flexDirection: "column", gap: 18, boxShadow: "0 40px 90px -30px rgba(0,0,0,.8)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#EDF1FB" }}>Add to Company Brain</div>
              <button type="button" onClick={() => setPinOpen(false)} style={{ background: "none", border: "none", fontSize: 18, color: "#6f7b98", cursor: "pointer", lineHeight: 1, padding: 0 }}>×</button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {([
                { key: "doc" as const, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={addType === "doc" ? ACCENT : "#8A93AD"} strokeWidth="1.8"><path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/></svg>, title: "Upload document", sub: "PDF, DOCX, TXT" },
                { key: "fact" as const, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={addType === "fact" ? ACCENT : "#8A93AD"} strokeWidth="1.8"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/></svg>, title: "Add a fact", sub: "A single piece of company info" },
                { key: "source" as const, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={addType === "source" ? ACCENT : "#8A93AD"} strokeWidth="1.8"><path d="M9 2v4M15 2v4M6 10h12l-1 4a5 5 0 0 1-10 0l-1-4ZM10 22v-4M14 22v-4"/></svg>, title: "Connect a source", sub: "Notion, Drive, website" },
                { key: "brand" as const, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={addType === "brand" ? ACCENT : "#8A93AD"} strokeWidth="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 4 5.5 4 9s-1.5 6.5-4 9c-2.5-2.5-4-5.5-4-9s1.5-6.5 4-9Z"/></svg>, title: "Brand guideline", sub: "Tone, do's and don'ts" },
              ] as Array<{ key: "doc"|"fact"|"source"|"brand"; icon: React.ReactNode; title: string; sub: string }>).map(({ key, icon, title, sub }) => (
                <div key={key} onClick={() => setAddType(key)} style={{ border: `1.5px solid ${addType === key ? ACCENT : "rgba(255,255,255,.12)"}`, borderRadius: 10, padding: 14, display: "flex", flexDirection: "column", gap: 6, cursor: "pointer", background: addType === key ? "rgba(124,255,198,.06)" : "transparent" }}>
                  {icon}
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#EDF1FB" }}>{title}</div>
                  <div style={{ fontSize: 10.5, color: "#6f7b98" }}>{sub}</div>
                </div>
              ))}
            </div>
            {addType === "fact" && (
              <form onSubmit={addRecord} style={{ display: "flex", flexDirection: "column", gap: 10, borderTop: "1px solid rgba(255,255,255,.08)", paddingTop: 16 }}>
                <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>New fact</div>
                <input placeholder="Label — e.g. Refund policy" value={draft.title} onChange={e => setDraft(d => ({ ...d, title: e.target.value }))} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, padding: "10px 12px", color: "#EDF1FB", fontSize: 13, fontFamily: HG, outline: "none" }} />
                <input placeholder="Value — what should Astra know?" value={draft.content} onChange={e => setDraft(d => ({ ...d, content: e.target.value }))} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, padding: "10px 12px", color: "#EDF1FB", fontSize: 13, fontFamily: HG, outline: "none" }} />
              </form>
            )}
            {addType === "doc" && (
              <div style={{ borderTop: "1px solid rgba(255,255,255,.08)", paddingTop: 16, border: "1.5px dashed rgba(255,255,255,.16)", borderRadius: 10, padding: 24, textAlign: "center", color: "#8A93AD", fontSize: 12.5 }}>Drop a file here, or click to browse</div>
            )}
            {addType === "source" && (
              <div style={{ borderTop: "1px solid rgba(255,255,255,.08)", paddingTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
                <input placeholder="Paste a Notion, Drive, or website link…" style={{ background: "#070911", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, padding: "10px 12px", color: "#EDF1FB", fontSize: 13, fontFamily: HG, outline: "none" }} />
              </div>
            )}
            {addType === "brand" && (
              <div style={{ borderTop: "1px solid rgba(255,255,255,.08)", paddingTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
                <input placeholder="e.g. Confident, no jargon, warm but direct" value={draft.content} onChange={e => setDraft(d => ({ ...d, title: "Brand voice", content: e.target.value }))} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, padding: "10px 12px", color: "#EDF1FB", fontSize: 13, fontFamily: HG, outline: "none" }} />
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button type="button" onClick={() => setPinOpen(false)} style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "10px 18px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: HG }}>Cancel</button>
              <button type="button" onClick={addType === "fact" || addType === "brand" ? addRecord as unknown as React.MouseEventHandler<HTMLButtonElement> : () => setPinOpen(false)} disabled={loading} style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "10px 18px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: HG, opacity: loading ? 0.6 : 1 }}>Save to brain</button>
            </div>
          </div>
        </div>
      )}

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
