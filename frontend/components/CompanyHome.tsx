"use client";

import { Fragment, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Brain, Calendar, Check, ChevronDown, ChevronLeft, ChevronRight, Circle, FileText, LayoutDashboard, Link2, Loader2, PanelRightClose, PanelRightOpen, Pencil, Save, ShieldCheck, Sparkles, Trash2, Users, X } from "lucide-react";
import AstraCopilotComposer from "@/components/AstraCopilotComposer";
import { useCompany } from "@/lib/company-context";
import { clearMessages, decideCompanyApproval, deleteArtifact, deleteInitiative, deleteMessage, deleteSquad, editMessage, getCompanyArtifact, getCompanyHomeData, retryTask, sendCopilotMessage, updateInitiative, type CompanyArtifactDetail, type CompanyHomeData, type CompanyHomeInitiative, type CompanyHomeSquad, type InitiativeBriefUpdate } from "@/lib/company-os";
import { ingestAttachment } from "@/lib/api";
import { readAttachment, type Attachment } from "@/lib/attachments";

const EMPTY: CompanyHomeData = { companyName: "Your company", northStar: "Set a clear company direction to focus the work.", initiatives: [], squads: [], approvals: [], brain: { summary: "Company knowledge is ready to ground each decision.", sourceCount: 0, recordCount: 0, artifacts: [] }, conversation: [] };
const STATUS_COLOR = { planned: "#8e8e8e", active: "var(--accent)", waiting: "#b45309", complete: "#15803d", blocked: "#b91c1c" };
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_BACKOFF_MS = 60000;
const STARTER_PROMPTS = ["What needs my attention?", "Summarize where things stand.", "What's blocked right now?"];

function InlineMarkdown({ text, inverse = false }: { text: string; inverse?: boolean }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\))/g);
  return <>{parts.map((part, index): ReactNode => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index} style={{ padding: "1px 4px", borderRadius: 4, background: inverse ? "rgba(255,255,255,.16)" : "rgba(15,23,42,.08)", fontSize: ".9em" }}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(part);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer" style={{ color: inverse ? "#fff" : "#2563eb", textDecoration: "underline", textUnderlineOffset: 2 }}>{link[1]}</a>;
    return <Fragment key={index}>{part}</Fragment>;
  })}</>;
}

function MarkdownDocument({ content, compact = false, inverse = false }: { content: string; compact?: boolean; inverse?: boolean }) {
  const textColor = inverse ? "#fff" : "#1e293b";
  const muted = inverse ? "rgba(255,255,255,.82)" : "#475569";
  return <>{content.split(/\n{2,}/).map((raw, index) => {
    const block = raw.trim();
    if (!block) return null;
    if (block.startsWith("# ")) return <h1 key={index} style={{ margin: "0 0 16px", color: textColor, fontSize: compact ? 19 : 30, lineHeight: 1.15, letterSpacing: "-.03em" }}><InlineMarkdown text={block.slice(2)} inverse={inverse} /></h1>;
    if (block.startsWith("## ")) return <h2 key={index} style={{ margin: index ? (compact ? "18px 0 7px" : "30px 0 12px") : "0 0 10px", paddingBottom: compact ? 0 : 8, borderBottom: compact ? 0 : "1px solid #dbe3ea", color: textColor, fontSize: compact ? 14 : 21, lineHeight: 1.25 }}><InlineMarkdown text={block.slice(3)} inverse={inverse} /></h2>;
    if (block.startsWith("### ")) return <h3 key={index} style={{ margin: "18px 0 7px", color: textColor, fontSize: compact ? 13 : 16 }}><InlineMarkdown text={block.slice(4)} inverse={inverse} /></h3>;
    const lines = block.split("\n");
    if (lines.length >= 2 && lines[0].includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[1])) {
      const cells = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
      const header = cells(lines[0]);
      return <div key={index} style={{ margin: "14px 0", overflowX: "auto", border: inverse ? "1px solid rgba(255,255,255,.2)" : "1px solid #dbe3ea", borderRadius: 9 }}><table style={{ width: "100%", minWidth: 540, borderCollapse: "collapse", fontSize: compact ? 12 : 13.5 }}><thead><tr>{header.map(cell => <th key={cell} style={{ padding: "9px 10px", color: textColor, background: inverse ? "rgba(255,255,255,.12)" : "#eef4f8", textAlign: "left", fontWeight: 700 }}><InlineMarkdown text={cell} inverse={inverse} /></th>)}</tr></thead><tbody>{lines.slice(2).filter(line => line.includes("|")).map((line, rowIndex) => <tr key={rowIndex}>{cells(line).map((cell, cellIndex) => <td key={cellIndex} style={{ padding: "9px 10px", verticalAlign: "top", color: muted, borderTop: inverse ? "1px solid rgba(255,255,255,.13)" : "1px solid #e2e8f0", lineHeight: 1.45 }}><InlineMarkdown text={cell} inverse={inverse} /></td>)}</tr>)}</tbody></table></div>;
    }
    if (lines.every(line => /^[-*]\s+/.test(line))) return <ul key={index} style={{ margin: "10px 0", paddingLeft: 20, color: muted, lineHeight: 1.65 }}>{lines.map((line, lineIndex) => <li key={lineIndex} style={{ paddingLeft: 2, marginBottom: 3 }}><InlineMarkdown text={line.replace(/^[-*]\s+/, "")} inverse={inverse} /></li>)}</ul>;
    if (lines.every(line => /^\d+\.\s+/.test(line))) return <ol key={index} style={{ margin: "10px 0", paddingLeft: 22, color: muted, lineHeight: 1.65 }}>{lines.map((line, lineIndex) => <li key={lineIndex} style={{ paddingLeft: 2, marginBottom: 3 }}><InlineMarkdown text={line.replace(/^\d+\.\s+/, "")} inverse={inverse} /></li>)}</ol>;
    return <p key={index} style={{ margin: "0 0 12px", color: muted, whiteSpace: "pre-wrap", fontSize: compact ? 13 : 15, lineHeight: compact ? 1.6 : 1.75 }}><InlineMarkdown text={block} inverse={inverse} /></p>;
  })}</>;
}

function ArtifactDocument({ content }: { content: string }) {
  return <article style={{ margin: "22px 0", padding: "clamp(18px, 4vw, 34px)", borderRadius: 14, background: "linear-gradient(135deg, #fffdf7, #f8fafc)", color: "#1e293b", boxShadow: "0 14px 40px rgba(15,23,42,.1)", fontFamily: "Georgia, 'Times New Roman', serif" }}><MarkdownDocument content={content} /></article>;
}

function SquadCard({ squad, deleting, onDelete, onOpenWorkbench }: { squad: CompanyHomeSquad; deleting: boolean; onDelete: () => void; onOpenWorkbench: () => void }) {
  const [open, setOpen] = useState(false);
  return <article className="dc company-home-squad-card" style={{ minWidth: 0, flex: "none", padding: 0, cursor: "default" }}>
    <div style={{ display: "flex", alignItems: "center" }}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} style={{ flex: 1, minWidth: 0, padding: "11px 4px 11px 12px", border: 0, background: "transparent", textAlign: "left", cursor: "pointer", display: "flex", gap: 10, alignItems: "center" }}>
        <span style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", color: "var(--accent)", background: "var(--bdim)", flexShrink: 0 }}><Users size={14} /></span>
        <span style={{ flex: 1, minWidth: 0 }}><b style={{ display: "block", color: "var(--fg)", fontSize: 12.5 }}>{squad.name}</b><small style={{ display: "block", marginTop: 2, color: "var(--fm)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{squad.activity}</small></span>
        <span className={`dc-badge ${squad.lifecycle.toLowerCase() === "working" ? "run" : squad.lifecycle.toLowerCase() === "done" ? "done" : "que"}`}>{squad.lifecycle}</span>
        <ChevronDown size={14} style={{ color: "var(--fm)", flexShrink: 0, transform: open ? "rotate(180deg)" : undefined, transition: "transform .18s" }} />
      </button>
      <button type="button" aria-label={`Open ${squad.name} workbench`} onClick={onOpenWorkbench} style={{ flexShrink: 0, width: 26, height: 26, marginRight: 4, display: "grid", placeItems: "center", border: 0, borderRadius: 6, background: "transparent", color: "var(--accent)", cursor: "pointer" }}><LayoutDashboard size={13} /></button>
      <button type="button" aria-label={`Delete ${squad.name}`} disabled={deleting} onClick={onDelete} className="company-home-initiative-delete" style={{ flexShrink: 0, width: 22, height: 22, marginRight: 8, display: "grid", placeItems: "center", border: 0, borderRadius: 5, background: "transparent", color: "var(--fm)", cursor: "pointer", opacity: deleting ? 0.5 : undefined }}><Trash2 size={11} /></button>
    </div>
    {open && <div style={{ padding: "0 12px 12px", borderTop: "1px solid var(--bd)" }}>{squad.tasks.map(task => <div key={task.id} style={{ display: "flex", gap: 8, paddingTop: 10, fontSize: 11.5 }}><span style={{ width: 6, height: 6, flexShrink: 0, borderRadius: "50%", marginTop: 4, background: STATUS_COLOR[task.status] }} /><span style={{ color: "var(--fg)", flex: 1, minWidth: 0 }}>{task.title}{task.note && <small style={{ display: "block", color: "var(--fm)", marginTop: 2 }}>{task.note}</small>}</span><small style={{ color: "var(--fm)", flexShrink: 0 }}>{task.status}</small></div>)}</div>}
  </article>;
}

const WORKBENCH_STATE = { complete: "done", active: "run", blocked: "err", waiting: "que", planned: "que" } as const;
const WORKBENCH_LABEL = { complete: "Done", active: "In progress", blocked: "Blocked", waiting: "Waiting on you", planned: "Queued" } as const;

function SquadWorkbench({ squad, onClose, onRetryTask, retryingTaskId }: { squad: CompanyHomeSquad; onClose: () => void; onRetryTask: (taskId: string) => void; retryingTaskId: string }) {
  const [selectedId, setSelectedId] = useState(() => squad.tasks.find(t => t.status === "active")?.id ?? squad.tasks[0]?.id ?? "");
  const selected = squad.tasks.find(t => t.id === selectedId) ?? squad.tasks[0] ?? null;
  return <div role="dialog" aria-modal="true" aria-label={`${squad.name} workbench`} onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 40, display: "grid", placeItems: "center", padding: 20, background: "rgba(2,6,23,.72)" }}>
    <section onClick={(e: MouseEvent) => e.stopPropagation()} style={{ width: "min(760px, 100%)", maxHeight: "86vh", display: "flex", flexDirection: "column", borderRadius: "var(--radius-lg)", overflow: "hidden", background: "var(--bg-surface)", border: "1px solid var(--bd)", boxShadow: "var(--shell-shadow)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "16px 20px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ minWidth: 0 }}>
          <div className="sec-label">Workbench</div>
          <h2 style={{ margin: "3px 0 0", fontSize: 16, fontWeight: 700, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{squad.name}</h2>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span className={`dc-badge ${squad.lifecycle.toLowerCase() === "working" ? "run" : squad.lifecycle.toLowerCase() === "done" ? "done" : "que"}`}>{squad.lifecycle}</span>
          <button type="button" className="btn sm" onClick={onClose}>Close</button>
        </div>
      </div>

      {squad.tasks.length === 0 ? (
        <div className="empty"><div className="empty-title">No tasks yet</div><p style={{ margin: 0, fontSize: 12 }}>This squad hasn&apos;t started work.</p></div>
      ) : <>
        <div className="depts">
          {squad.tasks.map(task => (
            <button key={task.id} type="button" onClick={() => setSelectedId(task.id)}
              className={`dc ${WORKBENCH_STATE[task.status]}${task.id === selected?.id ? " sel" : ""}`}
              style={{ textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit" }}>
              <div className="dc-top"><span className="dc-name" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</span></div>
              <span className={`dc-badge ${WORKBENCH_STATE[task.status]}`}>{WORKBENCH_LABEL[task.status]}</span>
            </button>
          ))}
        </div>
        <div className="dscroll" style={{ flex: 1 }}>
          {selected && <>
            <div className="sec-label" style={{ marginBottom: 8 }}>{selected.squad}</div>
            <h3 style={{ margin: "0 0 10px", fontSize: 15, color: "var(--fg)" }}>{selected.title}</h3>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className={`dc-badge ${WORKBENCH_STATE[selected.status]}`}>{WORKBENCH_LABEL[selected.status]}</span>
              {selected.status === "blocked" && (
                <button type="button" className="btn sm" disabled={retryingTaskId === selected.id} onClick={() => onRetryTask(selected.id)}>
                  {retryingTaskId === selected.id ? "Retrying…" : "Retry"}
                </button>
              )}
            </div>
            <p style={{ marginTop: 14, fontSize: 13, lineHeight: 1.7, color: "var(--fd)", whiteSpace: "pre-wrap" }}>{selected.note || "No additional detail recorded for this task yet."}</p>
          </>}
        </div>
      </>}
    </section>
  </div>;
}

function InitiativeWorkspace({ initiative, squads, artifacts, saving, onSave, onClose, onOpenSquad, onOpenArtifact }: { initiative: CompanyHomeInitiative; squads: CompanyHomeSquad[]; artifacts: CompanyHomeData["brain"]["artifacts"]; saving: boolean; onSave: (update: InitiativeBriefUpdate) => void; onClose: () => void; onOpenSquad: (id: string) => void; onOpenArtifact: (id: string) => void }) {
  const [draft, setDraft] = useState<InitiativeBriefUpdate>(() => ({ name: initiative.title, status: initiative.status, ...initiative.brief }));
  const field = (key: keyof InitiativeBriefUpdate, label: string, multiline = false) => <label style={{ display: "grid", gap: 5, minWidth: 0 }}><span className="sec-label" style={{ fontSize: 10 }}>{label}</span>{multiline ? <textarea className="f-ta" value={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.value })} style={{ minHeight: key === "successCriteria" ? 78 : 64, fontSize: 13 }} /> : <input className="f-input" value={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.value })} style={{ height: 34, fontSize: 13 }} />}</label>;
  const initiativeArtifacts = artifacts.filter(item => !item.initiativeId || item.initiativeId === initiative.id);

  return <div role="dialog" aria-modal="true" aria-label={`${initiative.title} initiative workspace`} onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 45, padding: "clamp(10px, 3vw, 28px)", background: "rgba(2,6,23,.72)", overflowY: "auto" }}>
    <section onClick={(event: MouseEvent) => event.stopPropagation()} style={{ width: "min(1120px, 100%)", margin: "auto", borderRadius: "var(--radius-lg)", overflow: "hidden", background: "var(--bg)", border: "1px solid var(--bd)", boxShadow: "var(--shell-shadow)" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, padding: "18px 22px", background: "var(--bg-surface)", borderBottom: "1px solid var(--bd)" }}><div><div className="sec-label">Initiative workspace</div><h2 style={{ margin: "4px 0 0", color: "var(--fg)", fontSize: 18 }}>{initiative.title}</h2></div><button type="button" className="btn sm" onClick={onClose}><X size={14} /> Close</button></header>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(290px, .8fr)", gap: 0 }}>
        <form onSubmit={event => { event.preventDefault(); onSave(draft); }} style={{ padding: "22px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 18 }}><div><div className="sec-label">Brief</div><p style={{ margin: "4px 0 0", color: "var(--fm)", fontSize: 12 }}>Keep the operating context current for every squad.</p></div><button type="submit" className="btn sm pri" disabled={saving || !draft.name.trim()}><Save size={13} /> {saving ? "Saving..." : "Save changes"}</button></div>
          <div style={{ display: "grid", gap: 14 }}>{field("name", "Initiative name")}{field("objective", "Objective", true)}{field("successCriteria", "Success criteria", true)}<div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}><label style={{ display: "grid", gap: 5 }}><span className="sec-label" style={{ fontSize: 10 }}>Priority</span><select className="f-input" value={draft.priority} onChange={event => setDraft({ ...draft, priority: event.target.value })} style={{ height: 34, fontSize: 13 }}><option>Low</option><option>Medium</option><option>High</option><option>Critical</option></select></label><label style={{ display: "grid", gap: 5 }}><span className="sec-label" style={{ fontSize: 10 }}>Status</span><select className="f-input" value={draft.status} onChange={event => setDraft({ ...draft, status: event.target.value })} style={{ height: 34, fontSize: 13 }}><option>Planned</option><option>Working</option><option>Review</option><option>Done</option></select></label>{field("owner", "Owner")}{field("budget", "Budget")}{field("dueDate", "Due date")}</div></div>
        </form>
        <aside style={{ padding: "22px", borderLeft: "1px solid var(--bd)", background: "var(--bg-sunken)", display: "grid", alignContent: "start", gap: 20 }}>
          <section><h3 className="sec-label" style={{ margin: "0 0 9px" }}><Users size={13} /> Squad roster</h3>{squads.length ? <div style={{ display: "grid", gap: 7 }}>{squads.map(squad => <button key={squad.id} type="button" onClick={() => onOpenSquad(squad.id)} style={{ padding: 10, textAlign: "left", border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-surface)", color: "var(--fg)", cursor: "pointer" }}><b style={{ display: "block", fontSize: 12 }}>{squad.name}</b><small style={{ display: "block", marginTop: 3, color: "var(--fm)" }}>{squad.members.length ? squad.members.join(" · ") : `${squad.tasks.length} tasks`}</small></button>)}</div> : <p style={{ margin: 0, color: "var(--fm)", fontSize: 12 }}>No squads assigned yet.</p>}</section>
          <section><h3 className="sec-label" style={{ margin: "0 0 9px" }}><Link2 size={13} /> Dependencies</h3>{initiative.dependencies.length ? <div style={{ display: "grid", gap: 7 }}>{initiative.dependencies.map(item => <div key={item.id} style={{ padding: 10, border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-surface)" }}><b style={{ display: "block", color: "var(--fg)", fontSize: 12 }}>{item.name}</b><small style={{ color: "var(--fm)", fontSize: 10.5 }}>{item.status}</small></div>)}</div> : <p style={{ margin: 0, color: "var(--fm)", fontSize: 12 }}>No dependencies recorded.</p>}</section>
          <section><h3 className="sec-label" style={{ margin: "0 0 9px" }}><FileText size={13} /> Consolidated artifacts</h3>{initiativeArtifacts.length ? <div style={{ display: "grid", gap: 7 }}>{initiativeArtifacts.map(item => <button key={item.id} type="button" onClick={() => onOpenArtifact(item.id)} style={{ padding: "9px 10px", textAlign: "left", border: "1px solid var(--bd)", borderRadius: 8, background: "var(--bg-surface)", color: "var(--fg)", cursor: "pointer" }}><b style={{ display: "block", fontSize: 12 }}>{item.title}</b><small style={{ color: "var(--fm)", fontSize: 10.5 }}>{item.source} · {item.updatedAt}</small></button>)}</div> : <p style={{ margin: 0, color: "var(--fm)", fontSize: 12 }}>No artifacts linked yet.</p>}</section>
        </aside>
      </div>
      <section style={{ padding: "20px 22px 24px", borderTop: "1px solid var(--bd)", background: "var(--bg-surface)" }}><h3 className="sec-label" style={{ margin: "0 0 12px" }}><Calendar size={13} /> Timeline</h3>{initiative.timeline.length ? <div style={{ display: "grid", gap: 8 }}>{initiative.timeline.map(item => <div key={item.id} style={{ display: "grid", gridTemplateColumns: "108px 1fr", gap: 12, padding: "9px 0", borderTop: "1px solid var(--bd)" }}><small style={{ color: "var(--fm)" }}>{item.occurredAt}</small><div><b style={{ color: "var(--fg)", fontSize: 12 }}>{item.title}</b>{item.detail && <p style={{ margin: "3px 0 0", color: "var(--fm)", fontSize: 11.5 }}>{item.detail}</p>}<small style={{ color: "var(--accent)", fontSize: 10 }}>{item.status}</small></div></div>)}</div> : <p style={{ margin: 0, color: "var(--fm)", fontSize: 12 }}>Activity will appear here as the initiative moves forward.</p>}</section>
    </section>
  </div>;
}

export default function CompanyHome() {
  const { founderId, companyId, activeCompany } = useCompany();
  const [home, setHome] = useState(EMPTY);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [sending, setSending] = useState(false);
  const [artifact, setArtifact] = useState<CompanyArtifactDetail | null>(null);
  const [artifactError, setArtifactError] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [retryingTaskId, setRetryingTaskId] = useState("");
  const [railOpen, setRailOpen] = useState(true);
  const [workbenchSquadId, setWorkbenchSquadId] = useState("");
  const [workspaceInitiativeId, setWorkspaceInitiativeId] = useState("");
  const [savingInitiative, setSavingInitiative] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState("");
  const [editingText, setEditingText] = useState("");
  const [messageBusyId, setMessageBusyId] = useState("");
  const [questionDrafts, setQuestionDrafts] = useState<Record<string, string>>({});
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attaching, setAttaching] = useState(false);
  const initiativesRailRef = useRef<HTMLDivElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const attachInputRef = useRef<HTMLInputElement | null>(null);

  // Exponential backoff on repeated failures instead of a fixed 3s interval
  // forever. Confirmed production incident: a corrupted Company OS event log
  // for one founder made this endpoint 500 on every call, and the fixed-interval
  // poll hammered the backend continuously with no backoff -- contributing to
  // "the VPS randomly hangs" reports. A single failure is often transient
  // (a deploy restart, a momentary network blip), so this doesn't back off
  // until failures repeat, and resets to the normal cadence the moment a
  // request succeeds again.
  useEffect(() => {
    let live = true;
    let timer = 0;
    let consecutiveFailures = 0;
    const refresh = () => {
      void getCompanyHomeData({ founderId, companyId })
        .then((data) => {
          if (!live) return;
          setHome(data);
          setNotice("");
          consecutiveFailures = 0;
          schedule(POLL_INTERVAL_MS);
        })
        .catch(() => {
          if (!live) return;
          setNotice("Company Home is ready while live data reconnects.");
          consecutiveFailures += 1;
          schedule(Math.min(POLL_INTERVAL_MS * 2 ** consecutiveFailures, POLL_MAX_BACKOFF_MS));
        });
    };
    const schedule = (delay: number) => { if (live) timer = window.setTimeout(refresh, delay); };
    refresh();
    return () => { live = false; window.clearTimeout(timer); };
  }, [founderId, companyId]);

  // Autoscroll to the newest message, like every real chat product does.
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [home.conversation.length]);

  const handleDeleteInitiative = async (initiativeId: string) => {
    setDeletingId(initiativeId);
    try {
      const data = await deleteInitiative({ founderId, companyId }, initiativeId);
      setHome(data);
    } catch {
      setNotice("Could not delete that initiative — try again.");
    } finally {
      setDeletingId("");
    }
  };

  const handleSaveInitiative = async (initiativeId: string, update: InitiativeBriefUpdate) => {
    setSavingInitiative(true);
    try {
      const data = await updateInitiative({ founderId, companyId }, initiativeId, update);
      setHome(data);
      setNotice("Initiative brief saved.");
    } catch {
      setNotice("Could not save that initiative — try again.");
    } finally {
      setSavingInitiative(false);
    }
  };

  const openArtifact = (artifactId: string) => {
    setArtifactError("");
    void getCompanyArtifact({ founderId, companyId }, artifactId).then(setArtifact).catch(() => setArtifactError("This artifact could not be opened."));
  };

  const handleDeleteSquad = async (squadId: string) => {
    setDeletingId(squadId);
    try {
      const data = await deleteSquad({ founderId, companyId }, squadId);
      setHome(data);
    } catch {
      setNotice("Could not delete that squad — try again.");
    } finally {
      setDeletingId("");
    }
  };

  const handleRetryTask = async (taskId: string) => {
    setRetryingTaskId(taskId);
    try {
      const data = await retryTask({ founderId, companyId }, taskId);
      setHome(data);
    } catch {
      setNotice("Could not retry that task — try again.");
    } finally {
      setRetryingTaskId("");
    }
  };

  const handleDeleteArtifact = async (artifactId: string, event: MouseEvent) => {
    event.stopPropagation();
    setDeletingId(artifactId);
    try {
      const data = await deleteArtifact({ founderId, companyId }, artifactId);
      setHome(data);
    } catch {
      setNotice("Could not delete that artifact — try again.");
    } finally {
      setDeletingId("");
    }
  };

  const scrollInitiatives = (direction: -1 | 1) => {
    initiativesRailRef.current?.scrollBy({ left: direction * 260, behavior: "smooth" });
  };

  const startEditingMessage = (turn: { id: string; message: string }) => {
    setEditingMessageId(turn.id);
    setEditingText(turn.message);
  };

  const cancelEditingMessage = () => { setEditingMessageId(""); setEditingText(""); };

  const saveEditedMessage = async () => {
    const value = editingText.trim();
    if (!value) return;
    setMessageBusyId(editingMessageId);
    try {
      const data = await editMessage({ founderId, companyId }, editingMessageId, value);
      setHome(data);
      cancelEditingMessage();
    } catch {
      setNotice("Could not save that edit — try again.");
    } finally {
      setMessageBusyId("");
    }
  };

  const handleDeleteMessage = async (messageId: string) => {
    setMessageBusyId(messageId);
    try {
      const data = await deleteMessage({ founderId, companyId }, messageId);
      setHome(data);
    } catch {
      setNotice("Could not delete that message — try again.");
    } finally {
      setMessageBusyId("");
    }
  };

  const handleClearChat = async () => {
    if (!home.conversation.length) return;
    if (typeof window !== "undefined" && !window.confirm("Clear the whole conversation? This can't be undone from here.")) return;
    setMessageBusyId("clear-chat");
    try {
      const data = await clearMessages({ founderId, companyId });
      setHome(data);
    } catch {
      setNotice("Could not clear the chat — try again.");
    } finally {
      setMessageBusyId("");
    }
  };

  const submitToCopilot = async (value: string) => {
    const pending = attachments;
    setMessage("");
    setAttachments([]);
    setSending(true);
    setNotice("Copilot is forming a squad and briefing the department lead...");
    // Echo the founder's own message immediately -- the real turn (classify +
    // dispatch) is a multi-second round trip, and without this the message
    // only appeared once that whole thing finished, making sending feel stuck.
    const echoId = `optimistic-${Date.now()}`;
    setHome(prev => ({ ...prev, conversation: [...prev.conversation, { id: echoId, author: "founder", message: value, kind: "chat", edited: false }] }));
    try {
      const result = await sendCopilotMessage({ founderId, companyId }, value, pending.filter(a => !a.error).map(a => ({ name: a.name, content: a.content })));
      setHome(result.data);
      setNotice(result.message);
    } catch {
      setHome(prev => ({ ...prev, conversation: prev.conversation.filter(turn => turn.id !== echoId) }));
      setNotice("Copilot could not reach Company OS. Your message was not lost locally.");
      setMessage(value);
      setAttachments(pending);
    } finally {
      setSending(false);
    }
  };

  const handlePickAttachments = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setAttaching(true);
    try {
      const read = await Promise.all(Array.from(files).map(async (file): Promise<Attachment> => {
        const result = founderId ? await ingestAttachment(founderId, file).catch(() => null) : null;
        if (result) return { name: result.filename, content: result.content, truncated: result.truncated, error: result.error };
        return readAttachment(file);
      }));
      setAttachments(prev => [...prev, ...read]);
    } finally {
      setAttaching(false);
      if (attachInputRef.current) attachInputRef.current.value = "";
    }
  };

  const tasks = home.squads.flatMap(squad => squad.tasks);
  const board = ["planned", "active", "waiting", "complete"] as const;
  const companyName = activeCompany?.name ?? home.companyName;
  const chatTurns = home.conversation.filter(turn => turn.kind !== "status");
  // @mention insertion writes this id as literal visible text into the
  // composer (AstraCopilotComposer.selectAgent) -- it must be a readable
  // slug of the squad's name, never the raw internal squad_id. A founder
  // who mentioned a squad once had "@squad_f00c7e5..." inserted verbatim,
  // which then got sent to the copilot as the actual message text and
  // corrupted classification/research-subject extraction downstream.
  const agentOptions = home.squads.map((s, index) => ({ id: s.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || `squad${index + 1}`, label: s.name, status: s.lifecycle.toLowerCase() }));
  const workbenchSquad = home.squads.find(s => s.id === workbenchSquadId) ?? null;
  const workspaceInitiative = home.initiatives.find(item => item.id === workspaceInitiativeId) ?? null;

  return <div style={{ display: "flex", height: "100%", minHeight: "100vh", background: "var(--bg)" }}>
    <style>{`
      .company-home-initiative-delete { opacity: 0; transition: opacity .14s, background .14s, color .14s; }
      .company-home-initiative-card:hover .company-home-initiative-delete,
      .company-home-artifact-row:hover .company-home-initiative-delete,
      .company-home-squad-card:hover .company-home-initiative-delete,
      .company-home-initiative-delete:focus-visible { opacity: 1; }
      .company-home-initiative-delete:hover { background: rgba(185, 28, 28, 0.1) !important; color: #b91c1c !important; }
      @media (hover: none) { .company-home-initiative-delete { opacity: 1; } }
      .company-home-artifact-row { transition: border-color .14s, background .14s; }
      .company-home-artifact-row:hover { border-color: var(--accent) !important; background: var(--bdim) !important; }
      .company-home-starter { transition: border-color .14s, background .14s, color .14s; }
      .company-home-starter:hover { border-color: var(--accent) !important; background: var(--bdim) !important; color: var(--fg) !important; }
      .company-home-rail-toggle:hover { border-color: var(--accent) !important; color: var(--accent) !important; }
      .company-home-initiative-card { transition: border-color .14s, transform .14s, box-shadow .14s; cursor: pointer; }
      .company-home-initiative-card:hover { border-color: var(--accent) !important; transform: translateY(-1px); box-shadow: 0 8px 18px rgba(15,23,42,.08); }
      @media (max-width: 860px) { .company-home-rail { display: none !important; } }
      .company-home-chat-actions { opacity: 0; transition: opacity .14s; }
      .company-home-chat-turn:hover .company-home-chat-actions, .company-home-chat-actions:focus-within { opacity: 1; }
      .company-home-chat-actions button:hover { background: var(--bdim) !important; color: var(--accent) !important; }
      @media (hover: none) { .company-home-chat-actions { opacity: 1; } }
    `}</style>

    {/* Chat column -- the primary surface. Header stays minimal, thread fills
        all remaining height, composer is pinned to the bottom like ChatGPT/
        Claude/Gemini instead of floating in a small box mid-page. */}
    <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "16px 24px", borderBottom: "1px solid var(--bd)" }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0, color: "var(--fg)", fontSize: 17, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{companyName}</h1>
          <p style={{ margin: "2px 0 0", color: "var(--fm)", fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{home.northStar}</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span className="pill green" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}><span className="live-dot" style={{ background: "var(--green)", boxShadow: "0 0 6px var(--gb)" }} /> Connected</span>
          {chatTurns.length > 0 && (
            <button type="button" className="btn sm" disabled={messageBusyId === "clear-chat"} onClick={() => void handleClearChat()}>
              {messageBusyId === "clear-chat" ? "Clearing…" : "Clear chat"}
            </button>
          )}
          <button type="button" aria-label={railOpen ? "Hide company status panel" : "Show company status panel"} onClick={() => setRailOpen(!railOpen)} className="company-home-rail-toggle btn sm" style={{ width: 32, height: 32, padding: 0, display: "grid", placeItems: "center" }}>
            {railOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
          </button>
        </div>
      </header>

      <div ref={threadRef} style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 20px 12px" }}>
          {chatTurns.length === 0 ? (
            <div style={{ minHeight: "50vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 18 }}>
              <span style={{ width: 44, height: 44, borderRadius: "50%", display: "grid", placeItems: "center", color: "var(--accent)", background: "var(--bdim)" }}><Sparkles size={20} /></span>
              <div>
                <h2 style={{ margin: 0, color: "var(--fg)", fontSize: 22, letterSpacing: "-.02em" }}>How&apos;s {companyName} doing?</h2>
                <p style={{ margin: "8px 0 0", color: "var(--fm)", fontSize: 13, maxWidth: 440 }}>{home.northStar}</p>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8 }}>
                {STARTER_PROMPTS.map(prompt => (
                  <button key={prompt} type="button" className="company-home-starter" onClick={() => setMessage(prompt)} style={{ padding: "9px 14px", border: "1px solid var(--bd)", borderRadius: 999, background: "var(--bg-surface)", color: "var(--fm)", fontSize: 12.5, cursor: "pointer" }}>{prompt}</button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {chatTurns.map(turn => {                    const isFounder = turn.author !== "copilot";
                    const editing = editingMessageId === turn.id;
                    const busy = messageBusyId === turn.id;
                    return (
                      <div key={turn.id} className={`ch-chat-row company-home-chat-turn ${isFounder ? "is-founder" : ""}`}>
                        {!isFounder && <span className="ch-chat-avatar"><Sparkles size={13} /></span>}
                        {isFounder && !editing && (
                          <span className="company-home-chat-actions" style={{ display: "flex", gap: 2, flexShrink: 0, alignSelf: "center" }}>
                            <button type="button" aria-label="Edit message" disabled={busy} onClick={() => startEditingMessage(turn)} style={{ width: 24, height: 24, display: "grid", placeItems: "center", border: 0, borderRadius: 6, background: "transparent", color: "rgba(255,255,255,0.78)", cursor: "pointer" }}><Pencil size={11} /></button>
                            <button type="button" aria-label="Delete message" disabled={busy} onClick={() => void handleDeleteMessage(turn.id)} style={{ width: 24, height: 24, display: "grid", placeItems: "center", border: 0, borderRadius: 6, background: "transparent", color: "rgba(255,255,255,0.78)", cursor: "pointer" }}><Trash2 size={11} /></button>
                          </span>
                        )}
                        {editing ? (
                          <div className="ch-chat-bubble" style={{ maxWidth: "min(560px, 84%)", borderRadius: 20, padding: 12 }}>
                            <textarea autoFocus value={editingText} onChange={e => setEditingText(e.target.value)}
                              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void saveEditedMessage(); } if (e.key === "Escape") cancelEditingMessage(); }}
                              className="f-ta" style={{ minHeight: 60, fontSize: 13, background: "transparent", border: 0, padding: 0, color: "inherit" }} />
                            <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 8 }}>
                              <button type="button" className="btn sm" onClick={cancelEditingMessage}><X size={11} /></button>
                              <button type="button" className="btn sm pri" disabled={busy || !editingText.trim()} onClick={() => void saveEditedMessage()}>{busy ? "Saving…" : "Save"}</button>
                            </div>
                          </div>
                        ) : turn.kind === "question" ? (
                          <div className="ch-chat-bubble" style={{ maxWidth: "min(420px, 84%)" }}>
                            <div style={{ fontSize: 13.5, color: "var(--fg)", marginBottom: 10 }}>{turn.question || turn.message}</div>
                            {turn.options && turn.options.length > 0 ? (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {turn.options.map(option => (
                                  <button key={option} type="button" disabled={sending} className="company-home-starter"
                                    onClick={() => void submitToCopilot(option)}
                                    style={{ padding: "8px 14px", border: "1px solid var(--apple-glass-border, rgba(255,255,255,0.10))", borderRadius: 999, background: "var(--apple-glass-bg-soft, rgba(255,255,255,0.045))", color: "var(--fg)", fontSize: 12.5, fontWeight: 500, cursor: sending ? "default" : "pointer", opacity: sending ? 0.6 : 1, boxShadow: "0 2px 8px rgba(0,0,0,0.10), inset 0 1px 0 rgba(255,255,255,0.10)" }}>
                                    {option}
                                  </button>
                                ))}
                              </div>
                            ) : (
                              <div style={{ display: "flex", gap: 6 }}>
                                <input value={questionDrafts[turn.id] ?? ""} disabled={sending}
                                  onChange={e => setQuestionDrafts(prev => ({ ...prev, [turn.id]: e.target.value }))}
                                  onKeyDown={e => {
                                    if (e.key !== "Enter") return;
                                    const draft = (questionDrafts[turn.id] ?? "").trim();
                                    if (!draft) return;
                                    void submitToCopilot(draft);
                                    setQuestionDrafts(prev => ({ ...prev, [turn.id]: "" }));
                                  }}
                                  placeholder="Type your answer..." className="f-ta" style={{ flex: 1, minHeight: "unset", fontSize: 13, padding: "7px 12px" }} />
                                <button type="button" className="btn sm pri" disabled={sending || !(questionDrafts[turn.id] ?? "").trim()}
                                  onClick={() => {
                                    const draft = (questionDrafts[turn.id] ?? "").trim();
                                    if (!draft) return;
                                    void submitToCopilot(draft);
                                    setQuestionDrafts(prev => ({ ...prev, [turn.id]: "" }));
                                  }}>Send</button>
                              </div>
                            )}
                          </div>
                        ) : turn.kind === "plan" && home.squads.find(s => s.id === turn.squadId) ? (
                          (() => {
                            const squad = home.squads.find(s => s.id === turn.squadId)!;
                            const searches = squad.tasks.reduce((sum, task) => sum + (task.searchCount ?? 0), 0);
                            const anyActive = squad.tasks.some(task => task.status === "active");
                            const allDone = squad.tasks.length > 0 && squad.tasks.every(task => task.status === "complete");
                            return (
                              <div className="ch-chat-bubble" style={{ maxWidth: "min(420px, 84%)" }}>
                                <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--fg)", marginBottom: 10, letterSpacing: "-0.005em" }}>{squad.name}</div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                                  {squad.tasks.map(task => (
                                    <div key={task.id} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                                      <span style={{ flexShrink: 0, marginTop: 1, color: task.status === "complete" ? "var(--green)" : task.status === "blocked" ? "var(--red)" : "var(--fm)" }}>
                                        {task.status === "complete" ? <Check size={15} /> : task.status === "active" ? <Loader2 size={15} className="company-home-spin" /> : <Circle size={13} />}
                                      </span>
                                      <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontSize: 13, color: "var(--fg)", textDecoration: task.status === "complete" ? "line-through" : "none", opacity: task.status === "complete" ? 0.7 : 1, letterSpacing: "-0.005em" }}>{task.title}</div>
                                        {task.note && <small style={{ display: "block", marginTop: 2, color: "var(--fm)", fontSize: 11 }}>{task.note}</small>}
                                        {task.status === "blocked" && (
                                          <button type="button" className="btn sm" disabled={retryingTaskId === task.id}
                                            onClick={() => void handleRetryTask(task.id)} style={{ marginTop: 5 }}>
                                            {retryingTaskId === task.id ? "Retrying…" : "Retry"}
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12, gap: 10 }}>
                                  <small style={{ color: "var(--fm)", fontSize: 11 }}>{allDone ? "Done" : anyActive ? "Researching…" : "Queued"}</small>
                                  {searches > 0 && <small style={{ color: "var(--fm)", fontSize: 11 }}>{searches} search{searches === 1 ? "" : "es"}</small>}
                                </div>
                                <div style={{ marginTop: 6, height: 3, borderRadius: 999, background: "var(--bd)", overflow: "hidden" }}>
                                  <div className={allDone ? undefined : anyActive ? "company-home-progress-indeterminate" : undefined}
                                    style={{ height: "100%", borderRadius: 999, background: "var(--accent)", width: allDone ? "100%" : anyActive ? "40%" : "4%" }} />
                                </div>
                              </div>
                            );
                          })()
                        ) : (
                          <div className="ch-chat-bubble" style={{ opacity: busy ? 0.6 : 1 }}>
                            <MarkdownDocument content={turn.message} compact inverse={isFounder} />
                            {turn.edited && <small style={{ display: "block", marginTop: 4, opacity: 0.7, fontSize: 10 }}>(edited)</small>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {sending && (
                    <div className="ch-chat-row">
                      <span className="ch-chat-avatar"><Sparkles size={13} /></span>
                      <div className="ch-chat-bubble" style={{ maxWidth: "min(180px, 60%)", padding: "12px 16px" }} aria-label="Copilot is thinking">
                        <span className="ch-thinking-dot" />
                        <span className="ch-thinking-dot" />
                        <span className="ch-thinking-dot" />
                      </div>
                    </div>
                  )}
            </div>
          )}
        </div>
      </div>

      {/* Composer dock: pinned to the bottom of the chat column, centered,
          matching the width of the thread above it -- not a small floating
          box mid-page. */}
      <div style={{ flexShrink: 0, borderTop: "1px solid var(--bd)", padding: "14px 20px" }}>
        <div style={{ maxWidth: 760, margin: "0 auto" }}>
          <input ref={attachInputRef} type="file" multiple style={{ display: "none" }}
            accept=".txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.htm,.css,.scss,.js,.jsx,.ts,.tsx,.py,.rb,.go,.rs,.java,.c,.cpp,.h,.sh,.sql,.env,.ini,.toml,.log,.pdf,.png,.jpg,.jpeg,.webp,.gif,text/*,application/json,application/pdf,image/*"
            onChange={e => void handlePickAttachments(e.target.files)} />
          {attachments.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              {attachments.map((a, i) => (
                <span key={`${a.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, padding: "3px 8px", borderRadius: 999, border: `1px solid ${a.error ? "#b91c1c" : "var(--bd)"}`, background: a.error ? "rgba(185,28,28,.08)" : "var(--bg-surface)", color: a.error ? "#b91c1c" : "var(--fm)" }}
                  title={a.error || (a.truncated ? "Truncated" : a.name)}>
                  {a.name}{a.truncated ? " ·trimmed" : ""}{a.error ? " ·error" : ""}
                  <button type="button" aria-label={`Remove ${a.name}`} onClick={() => setAttachments(prev => prev.filter((_, j) => j !== i))}
                    style={{ background: "none", border: 0, color: "inherit", cursor: "pointer", padding: 0, lineHeight: 1, fontSize: 12 }}>✕</button>
                </span>
              ))}
            </div>
          )}
          <AstraCopilotComposer
            value={message}
            onChange={setMessage}
            disabled={sending}
            onSubmit={submitToCopilot}
            agents={agentOptions}
            contextLabel={sending ? "Copilot is coordinating your squad" : "Grounded in Company Brain"}
            placeholder="Ask Astra to coordinate your company"
            onAttach={() => attachInputRef.current?.click()}
            attachmentCount={attachments.length}
          />
          {attaching && <p style={{ margin: "8px 2px 0", color: "var(--fm)", fontSize: 11.5 }}>Reading files…</p>}
          {notice && <p style={{ margin: "8px 2px 0", color: "var(--fm)", fontSize: 11.5 }}>{notice}</p>}
        </div>
      </div>
    </main>

    {/* Company status rail -- secondary to the chat, collapsible, quieter
        typography than a control-room dashboard would use. Everything that
        used to be full-width sections (Initiatives, Squad activity, Mission
        board, Approvals, Artifacts, Company Brain) lives here now. */}
    {railOpen && (
      <aside className="company-home-rail" style={{ width: 340, flexShrink: 0, height: "100vh", overflowY: "auto", borderLeft: "1px solid var(--bd)", padding: "20px 18px", background: "var(--bg-sunken)" }}>
        <section style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--fg)", fontWeight: 700, fontSize: 13 }}><Brain size={15} color="var(--accent)" /> Company Brain</div>
          <p style={{ color: "var(--fm)", fontSize: 11.5, lineHeight: 1.5, margin: "6px 0" }}>{home.brain.summary}</p>
          <div style={{ display: "flex", gap: 14, fontSize: 11 }}><span style={{ color: "var(--fd)" }}><b>{home.brain.recordCount}</b> records</span><span style={{ color: "var(--fd)" }}><b>{home.brain.sourceCount}</b> sources</span></div>
        </section>

        <section style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <h2 className="sec-label" style={{ margin: 0 }}>Initiatives {home.initiatives.length > 0 && <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>· {home.initiatives.length}</span>}</h2>
            {home.initiatives.length > 1 && (
              <div style={{ display: "flex", gap: 4 }}>
                <button type="button" aria-label="Scroll initiatives left" onClick={() => scrollInitiatives(-1)} style={{ width: 22, height: 22, display: "grid", placeItems: "center", border: "1px solid var(--bd)", borderRadius: 6, background: "var(--bg-surface)", color: "var(--fm)", cursor: "pointer" }}><ChevronLeft size={12} /></button>
                <button type="button" aria-label="Scroll initiatives right" onClick={() => scrollInitiatives(1)} style={{ width: 22, height: 22, display: "grid", placeItems: "center", border: "1px solid var(--bd)", borderRadius: 6, background: "var(--bg-surface)", color: "var(--fm)", cursor: "pointer" }}><ChevronRight size={12} /></button>
              </div>
            )}
          </div>
          {home.initiatives.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>No initiatives yet. Ask Copilot to kick one off.</p>
          ) : (
            <div ref={initiativesRailRef} style={{ display: "flex", gap: 8, overflowX: "auto", scrollSnapType: "x proximity", paddingBottom: 4 }}>
              {home.initiatives.map(item => (
                <article key={item.id} className="company-home-initiative-card" onClick={() => setWorkspaceInitiativeId(item.id)} style={{ position: "relative", flex: "0 0 auto", width: 180, scrollSnapAlign: "start", padding: 11, border: "1px solid var(--bd)", borderRadius: "var(--radius)", background: "var(--bg-surface)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "flex-start" }}>
                    <b style={{ color: "var(--fg)", fontSize: 11.5, lineHeight: 1.3 }}>{item.title}</b>
                    <button type="button" aria-label={`Delete ${item.title}`} disabled={deletingId === item.id} onClick={(event) => { event.stopPropagation(); void handleDeleteInitiative(item.id); }} className="company-home-initiative-delete" style={{ flexShrink: 0, width: 20, height: 20, display: "grid", placeItems: "center", border: 0, borderRadius: 5, background: "transparent", color: "var(--fm)", cursor: "pointer", opacity: deletingId === item.id ? 0.5 : undefined }}><Trash2 size={11} /></button>
                  </div>
                  <div style={{ height: 4, margin: "10px 0 6px", borderRadius: 8, background: "var(--bg-sunken)", overflow: "hidden" }}><div style={{ width: "100%", height: "100%", borderRadius: 8, background: "var(--accent)", transformOrigin: "left", transform: `scaleX(${item.progress / 100})`, transition: "transform .3s ease" }} /></div>
                  <small style={{ color: "var(--fm)", fontSize: 10 }}>{item.progress}% · {item.taskCount} tasks</small>
                </article>
              ))}
            </div>
          )}
        </section>

        <section style={{ marginBottom: 22 }}>
          <h2 className="sec-label" style={{ margin: "0 0 8px" }}>Squad activity</h2>
          {home.squads.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>No squads formed yet.</p>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>{home.squads.map(squad => <SquadCard key={squad.id} squad={squad} deleting={deletingId === squad.id} onDelete={() => void handleDeleteSquad(squad.id)} onOpenWorkbench={() => setWorkbenchSquadId(squad.id)} />)}</div>
          )}
        </section>

        <section style={{ marginBottom: 22 }}>
          <h2 className="sec-label" style={{ margin: "0 0 8px" }}>Mission board</h2>
          {tasks.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>No tasks yet.</p>
          ) : (
            <div style={{ border: "1px solid var(--bd)", borderRadius: "var(--radius)", background: "var(--bg-sunken)", overflow: "hidden" }}>
              {board.map((status, i) => {
                const columnTasks = tasks.filter(task => task.status === status);
                if (columnTasks.length === 0) return null;
                return (
                  <div key={status} style={{ padding: "9px 11px", borderTop: i > 0 ? "1px solid var(--bd)" : undefined }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: STATUS_COLOR[status] }} />
                      <b style={{ color: "var(--fd)", fontSize: 10.5, textTransform: "capitalize" }}>{status}</b>
                      <small style={{ color: "var(--fm)", fontSize: 10 }}>{columnTasks.length}</small>
                    </div>
                    {columnTasks.slice(0, 3).map(task => <div key={task.id} style={{ padding: "4px 0 4px 12px", color: "var(--fg)", fontSize: 10.5, lineHeight: 1.4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</div>)}
                    {columnTasks.length > 3 && <small style={{ display: "block", padding: "2px 0 0 12px", color: "var(--fm)", fontSize: 9.5 }}>+{columnTasks.length - 3} more</small>}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section style={{ marginBottom: 22 }}>
          <h2 className="sec-label" style={{ margin: "0 0 8px" }}>Approvals</h2>
          {home.approvals.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>Nothing waiting on you.</p>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>{home.approvals.map(item => <article key={item.id} style={{ padding: 11, border: "1px solid var(--ab)", borderRadius: "var(--radius)", background: "var(--adim)" }}><div style={{ display: "flex", gap: 6, color: "var(--amber)" }}><ShieldCheck size={13} /><b style={{ fontSize: 11.5, color: "var(--fg)" }}>{item.title}</b></div><p style={{ margin: "6px 0", fontSize: 10.5, color: "var(--fd)" }}>{item.detail}</p><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}><small style={{ color: "var(--amber)", fontSize: 10 }}>{item.squad}</small><button type="button" onClick={() => { void decideCompanyApproval({ founderId, companyId }, item.id, true).then(setHome).catch(error => setNotice(error instanceof Error ? error.message : "Approval failed.")); }} style={{ padding: "6px 9px", border: 0, borderRadius: 6, background: "var(--accent)", color: "#fff", cursor: "pointer", fontSize: 10 }}>Approve</button></div></article>)}</div>
          )}
        </section>

        <section>
          <h2 className="sec-label" style={{ margin: "0 0 8px" }}>Artifacts</h2>
          {home.brain.artifacts.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>Documents will show up here.</p>
          ) : (
            <div style={{ display: "grid", gap: 6 }}>{home.brain.artifacts.map(item => (
              <article key={item.id} className="company-home-artifact-row" style={{ display: "flex", alignItems: "center", gap: 2, padding: "2px 2px 2px 9px", border: "1px solid var(--bd)", borderRadius: "var(--radius)", background: "var(--bg-surface)" }}>
                <button type="button" onClick={() => openArtifact(item.id)} style={{ flex: 1, minWidth: 0, display: "flex", gap: 7, padding: "6px 0", color: "inherit", textAlign: "left", cursor: "pointer", border: 0, background: "transparent" }}>
                  <FileText size={13} color="var(--accent)" />
                  <span style={{ minWidth: 0 }}><b style={{ display: "block", color: "var(--fg)", fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</b><small style={{ color: "var(--fm)", fontSize: 9.5 }}>{item.source}</small></span>
                </button>
                <button type="button" aria-label={`Delete ${item.title}`} disabled={deletingId === item.id} onClick={(event) => void handleDeleteArtifact(item.id, event)} className="company-home-initiative-delete" style={{ flexShrink: 0, width: 22, height: 22, display: "grid", placeItems: "center", border: 0, borderRadius: 5, background: "transparent", color: "var(--fm)", cursor: "pointer", opacity: deletingId === item.id ? 0.5 : undefined }}><Trash2 size={11} /></button>
              </article>
            ))}</div>
          )}
        </section>
      </aside>
    )}

    {workbenchSquad && <SquadWorkbench squad={workbenchSquad} onClose={() => setWorkbenchSquadId("")} onRetryTask={(taskId) => void handleRetryTask(taskId)} retryingTaskId={retryingTaskId} />}
    {workspaceInitiative && <InitiativeWorkspace key={workspaceInitiative.id} initiative={workspaceInitiative} squads={home.squads.filter(squad => squad.initiativeId === workspaceInitiative.id)} artifacts={home.brain.artifacts} saving={savingInitiative} onSave={(update) => void handleSaveInitiative(workspaceInitiative.id, update)} onClose={() => setWorkspaceInitiativeId("")} onOpenSquad={(id) => { setWorkspaceInitiativeId(""); setWorkbenchSquadId(id); }} onOpenArtifact={(id) => { setWorkspaceInitiativeId(""); openArtifact(id); }} />}

    {(artifact || artifactError) && <div role="dialog" aria-modal="true" aria-label="Artifact preview" style={{ position: "fixed", inset: 0, zIndex: 30, display: "grid", placeItems: "center", padding: 20, background: "rgba(2,6,23,.68)" }}><section style={{ width: "min(820px, 100%)", maxHeight: "86vh", overflow: "auto", padding: 22, borderRadius: "var(--radius-lg)", background: "var(--bg-surface)", border: "1px solid var(--bd)" }}>{artifact ? <><div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "start" }}><div><h2 style={{ margin: 0, color: "var(--fg)", fontSize: 18 }}>{artifact.title}</h2><small style={{ color: "var(--fm)" }}>{artifact.source} · {artifact.updatedAt}</small></div><button type="button" onClick={() => setArtifact(null)} style={{ border: 0, background: "transparent", color: "var(--fm)", cursor: "pointer" }}>Close</button></div><ArtifactDocument content={artifact.content || "This artifact has no previewable text."} /><div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{artifact.url && <a href={artifact.url} target="_blank" rel="noreferrer" style={{ padding: "9px 13px", borderRadius: 7, background: "var(--panel)", color: "var(--fg)", textDecoration: "none", border: "1px solid var(--bd)" }}>Open hosted preview</a>}<button type="button" onClick={() => { const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/markdown" })); const link = document.createElement("a"); link.href = url; link.download = `${artifact.title.replaceAll(/[^a-z0-9]+/gi, "-").replaceAll(/(^-|-$)/g, "") || "artifact"}.md`; link.click(); URL.revokeObjectURL(url); }} style={{ padding: "9px 13px", border: 0, borderRadius: 7, background: "var(--accent)", color: "#fff", cursor: "pointer" }}>Download artifact</button></div></> : <><p style={{ color: "var(--fg)" }}>{artifactError}</p><button type="button" onClick={() => setArtifactError("")}>Close</button></>}</section></div>}

    <style>{`
      @keyframes companyHomeSpin { to { transform: rotate(360deg); } }
      @keyframes companyHomeProgressSlide { 0% { transform: translateX(-100%); } 100% { transform: translateX(250%); } }
      .company-home-spin { animation: companyHomeSpin 1s linear infinite; }
      .company-home-progress-indeterminate { width: 40% !important; animation: companyHomeProgressSlide 1.1s ease-in-out infinite; }
      @media (prefers-reduced-motion: reduce) {
        .company-home-spin { animation: none !important; }
        .company-home-progress-indeterminate { animation: none !important; width: 40% !important; transform: none !important; }
      }
    `}</style>
  </div>;
}
