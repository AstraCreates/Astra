"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Brain, ChevronDown, ChevronLeft, ChevronRight, FileText, LayoutDashboard, PanelRightClose, PanelRightOpen, ShieldCheck, Sparkles, Trash2, Users } from "lucide-react";
import AstraCopilotComposer from "@/components/AstraCopilotComposer";
import { useCompany } from "@/lib/company-context";
import { deleteArtifact, deleteInitiative, deleteSquad, getCompanyArtifact, getCompanyHomeData, sendCopilotMessage, type CompanyArtifactDetail, type CompanyHomeData, type CompanyHomeSquad } from "@/lib/company-os";

const EMPTY: CompanyHomeData = { companyName: "Your company", northStar: "Set a clear company direction to focus the work.", initiatives: [], squads: [], approvals: [], brain: { summary: "Company knowledge is ready to ground each decision.", sourceCount: 0, recordCount: 0, artifacts: [] }, conversation: [] };
const STATUS_COLOR = { planned: "#8e8e8e", active: "var(--accent)", waiting: "#b45309", complete: "#15803d", blocked: "#b91c1c" };
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_BACKOFF_MS = 60000;
const STARTER_PROMPTS = ["What needs my attention?", "Summarize where things stand.", "What's blocked right now?"];

function ArtifactDocument({ content }: { content: string }) {
  return <article style={{ margin: "22px 0", padding: "clamp(18px, 4vw, 34px)", borderRadius: 14, background: "linear-gradient(135deg, #fffdf7, #f8fafc)", color: "#1e293b", boxShadow: "0 14px 40px rgba(15,23,42,.1)", fontFamily: "Georgia, 'Times New Roman', serif" }}>{content.split(/\n{2,}/).map((block, index) => {
    const text = block.trim();
    if (!text) return null;
    if (text.startsWith("## ")) return <h2 key={index} style={{ margin: index ? "30px 0 12px" : "0 0 12px", paddingBottom: 8, borderBottom: "1px solid #dbe3ea", color: "#0f172a", fontSize: 21 }}>{text.slice(3)}</h2>;
    if (text.startsWith("# ")) return <h1 key={index} style={{ margin: "0 0 16px", color: "#0f172a", fontSize: 28 }}>{text.slice(2)}</h1>;
    if (text.split("\n").every(line => line.startsWith("- "))) return <ul key={index} style={{ margin: "12px 0", paddingLeft: 22, lineHeight: 1.75 }}>{text.split("\n").map(line => <li key={line}>{line.slice(2)}</li>)}</ul>;
    return <p key={index} style={{ margin: "0 0 15px", whiteSpace: "pre-wrap", fontSize: 15, lineHeight: 1.75 }}>{text}</p>;
  })}</article>;
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

function SquadWorkbench({ squad, onClose }: { squad: CompanyHomeSquad; onClose: () => void }) {
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
        <div className="empty"><div className="empty-title">No tasks yet</div><p style={{ margin: 0, fontSize: 12 }}>This squad hasn't started work.</p></div>
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
            <span className={`dc-badge ${WORKBENCH_STATE[selected.status]}`}>{WORKBENCH_LABEL[selected.status]}</span>
            <p style={{ marginTop: 14, fontSize: 13, lineHeight: 1.7, color: "var(--fd)", whiteSpace: "pre-wrap" }}>{selected.note || "No additional detail recorded for this task yet."}</p>
          </>}
        </div>
      </>}
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
  const [railOpen, setRailOpen] = useState(true);
  const [workbenchSquadId, setWorkbenchSquadId] = useState("");
  const initiativesRailRef = useRef<HTMLDivElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

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

  const submitToCopilot = async (value: string) => {
    setSending(true);
    setNotice("Copilot is forming a squad and briefing the department lead...");
    try {
      const result = await sendCopilotMessage({ founderId, companyId }, value);
      setHome(result.data);
      setNotice(result.message);
      setMessage("");
    } catch {
      setNotice("Copilot could not reach Company OS. Your message was not lost locally.");
    } finally {
      setSending(false);
    }
  };

  const tasks = home.squads.flatMap(squad => squad.tasks);
  const board = ["planned", "active", "waiting", "complete"] as const;
  const companyName = activeCompany?.name ?? home.companyName;
  const chatTurns = home.conversation.filter(turn => turn.kind !== "status");
  const agentOptions = home.squads.map(s => ({ id: s.id.replace(/[^a-z0-9_]/gi, "_").toLowerCase(), label: s.name, status: s.lifecycle.toLowerCase() }));
  const workbenchSquad = home.squads.find(s => s.id === workbenchSquadId) ?? null;

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
      @media (max-width: 860px) { .company-home-rail { display: none !important; } }
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
                <h2 style={{ margin: 0, color: "var(--fg)", fontSize: 22, letterSpacing: "-.02em" }}>How's {companyName} doing?</h2>
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
              {chatTurns.map(turn => {
                const isFounder = turn.author !== "copilot";
                return (
                  <div key={turn.id} style={{ display: "flex", alignItems: "flex-start", gap: 9, justifyContent: isFounder ? "flex-end" : "flex-start" }}>
                    {!isFounder && <span style={{ width: 26, height: 26, flexShrink: 0, borderRadius: 7, display: "grid", placeItems: "center", background: "var(--accent)", color: "#fff" }}><Sparkles size={13} /></span>}
                    <div style={{ maxWidth: "84%", padding: "10px 13px", borderRadius: 10, fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap", background: isFounder ? "var(--accent)" : "var(--bg-surface)", color: isFounder ? "#fff" : "var(--fg)", border: isFounder ? "none" : "1px solid var(--bd)" }}>{turn.message}</div>
                  </div>
                );
              })}
              {sending && (
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ width: 26, height: 26, flexShrink: 0, borderRadius: 7, display: "grid", placeItems: "center", background: "var(--accent)", color: "#fff" }}><Sparkles size={13} /></span>
                  <div style={{ display: "inline-flex", gap: 4, alignItems: "center", padding: "10px 13px", borderRadius: 10, background: "var(--bg-surface)", border: "1px solid var(--bd)" }}>
                    {[0, 150, 300].map(d => <span key={d} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--fm)", opacity: 0.5, animation: `chatDotPulse 1s ease-in-out ${d}ms infinite` }} />)}
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
          <AstraCopilotComposer
            value={message}
            onChange={setMessage}
            disabled={sending}
            onSubmit={submitToCopilot}
            agents={agentOptions}
            contextLabel={sending ? "Copilot is coordinating your squad" : "Grounded in Company Brain"}
            placeholder="Ask Astra to coordinate your company"
          />
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
                <article key={item.id} className="company-home-initiative-card" style={{ position: "relative", flex: "0 0 auto", width: 180, scrollSnapAlign: "start", padding: 11, border: "1px solid var(--bd)", borderRadius: "var(--radius)", background: "var(--bg-surface)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "flex-start" }}>
                    <b style={{ color: "var(--fg)", fontSize: 11.5, lineHeight: 1.3 }}>{item.title}</b>
                    <button type="button" aria-label={`Delete ${item.title}`} disabled={deletingId === item.id} onClick={() => void handleDeleteInitiative(item.id)} className="company-home-initiative-delete" style={{ flexShrink: 0, width: 20, height: 20, display: "grid", placeItems: "center", border: 0, borderRadius: 5, background: "transparent", color: "var(--fm)", cursor: "pointer", opacity: deletingId === item.id ? 0.5 : undefined }}><Trash2 size={11} /></button>
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
            <div style={{ display: "grid", gap: 8 }}>{home.approvals.map(item => <article key={item.id} style={{ padding: 11, border: "1px solid var(--ab)", borderRadius: "var(--radius)", background: "var(--adim)" }}><div style={{ display: "flex", gap: 6, color: "var(--amber)" }}><ShieldCheck size={13} /><b style={{ fontSize: 11.5, color: "var(--fg)" }}>{item.title}</b></div><p style={{ margin: "6px 0", fontSize: 10.5, color: "var(--fd)" }}>{item.detail}</p><small style={{ color: "var(--amber)", fontSize: 10 }}>{item.squad}</small></article>)}</div>
          )}
        </section>

        <section>
          <h2 className="sec-label" style={{ margin: "0 0 8px" }}>Artifacts</h2>
          {home.brain.artifacts.length === 0 ? (
            <p style={{ margin: 0, padding: 12, border: "1px dashed var(--bd)", borderRadius: "var(--radius)", color: "var(--fm)", fontSize: 11.5 }}>Documents will show up here.</p>
          ) : (
            <div style={{ display: "grid", gap: 6 }}>{home.brain.artifacts.map(item => (
              <article key={item.id} className="company-home-artifact-row" style={{ display: "flex", alignItems: "center", gap: 2, padding: "2px 2px 2px 9px", border: "1px solid var(--bd)", borderRadius: "var(--radius)", background: "var(--bg-surface)" }}>
                <button type="button" onClick={() => { setArtifactError(""); void getCompanyArtifact({ founderId, companyId }, item.id).then(setArtifact).catch(() => setArtifactError("This artifact could not be opened.")); }} style={{ flex: 1, minWidth: 0, display: "flex", gap: 7, padding: "6px 0", color: "inherit", textAlign: "left", cursor: "pointer", border: 0, background: "transparent" }}>
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

    {workbenchSquad && <SquadWorkbench squad={workbenchSquad} onClose={() => setWorkbenchSquadId("")} />}

    {(artifact || artifactError) && <div role="dialog" aria-modal="true" aria-label="Artifact preview" style={{ position: "fixed", inset: 0, zIndex: 30, display: "grid", placeItems: "center", padding: 20, background: "rgba(2,6,23,.68)" }}><section style={{ width: "min(820px, 100%)", maxHeight: "86vh", overflow: "auto", padding: 22, borderRadius: "var(--radius-lg)", background: "var(--bg-surface)", border: "1px solid var(--bd)" }}>{artifact ? <><div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "start" }}><div><h2 style={{ margin: 0, color: "var(--fg)", fontSize: 18 }}>{artifact.title}</h2><small style={{ color: "var(--fm)" }}>{artifact.source} · {artifact.updatedAt}</small></div><button type="button" onClick={() => setArtifact(null)} style={{ border: 0, background: "transparent", color: "var(--fm)", cursor: "pointer" }}>Close</button></div><ArtifactDocument content={artifact.content || "This artifact has no previewable text."} /><button type="button" onClick={() => { const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/markdown" })); const link = document.createElement("a"); link.href = url; link.download = `${artifact.title.replaceAll(/[^a-z0-9]+/gi, "-").replaceAll(/(^-|-$)/g, "") || "artifact"}.md`; link.click(); URL.revokeObjectURL(url); }} style={{ padding: "9px 13px", border: 0, borderRadius: 7, background: "var(--accent)", color: "#fff", cursor: "pointer" }}>Download artifact</button></> : <><p style={{ color: "var(--fg)" }}>{artifactError}</p><button type="button" onClick={() => setArtifactError("")}>Close</button></>}</section></div>}

    <style>{`
      @keyframes chatDotPulse { 0%, 100% { opacity: .3; transform: scale(.8); } 50% { opacity: 1; transform: scale(1); } }
      @media (prefers-reduced-motion: reduce) {
        [style*="chatDotPulse"] { animation: none !important; }
      }
    `}</style>
  </div>;
}
