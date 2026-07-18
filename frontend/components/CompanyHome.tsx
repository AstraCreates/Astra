"use client";

import { useEffect, useRef, useState } from "react";
import { Brain, ChevronDown, ChevronLeft, ChevronRight, FileText, ShieldCheck, Sparkles, Trash2, Users } from "lucide-react";
import AstraCopilotComposer from "@/components/AstraCopilotComposer";
import { useCompany } from "@/lib/company-context";
import { deleteInitiative, getCompanyArtifact, getCompanyHomeData, sendCopilotMessage, type CompanyArtifactDetail, type CompanyHomeData, type CompanyHomeSquad } from "@/lib/company-os";

const EMPTY: CompanyHomeData = { companyName: "Your company", northStar: "Set a clear company direction to focus the work.", initiatives: [], squads: [], approvals: [], brain: { summary: "Company knowledge is ready to ground each decision.", sourceCount: 0, recordCount: 0, artifacts: [] }, conversation: [] };
const STATUS_COLOR = { planned: "#8e8e8e", active: "var(--accent)", waiting: "#b45309", complete: "#15803d", blocked: "#b91c1c" };
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_BACKOFF_MS = 60000;

function SquadCard({ squad }: { squad: CompanyHomeSquad }) {
  const [open, setOpen] = useState(false);
  return <article style={{ border: "1px solid var(--border)", borderRadius: "var(--r)", background: "var(--bg-surface)", overflow: "hidden" }}>
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} style={{ width: "100%", padding: "16px", border: 0, background: "transparent", textAlign: "left", cursor: "pointer", display: "flex", gap: 12, alignItems: "center" }}>
      <span style={{ width: 34, height: 34, borderRadius: "50%", display: "grid", placeItems: "center", color: "var(--accent)", background: "var(--accent-light)" }}><Users size={17} /></span>
      <span style={{ flex: 1, minWidth: 0 }}><b style={{ display: "block", color: "var(--text)", fontSize: 14 }}>{squad.name}</b><small style={{ display: "block", marginTop: 3, color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{squad.activity}</small></span>
      <span style={{ color: "var(--text-3)", fontSize: 10, textTransform: "uppercase", letterSpacing: ".08em" }}>{squad.lifecycle}</span><ChevronDown size={16} style={{ color: "var(--text-3)", transform: open ? "rotate(180deg)" : undefined, transition: "transform .18s" }} />
    </button>
    {open && <div style={{ padding: "0 16px 14px", borderTop: "1px solid var(--border)" }}>{squad.tasks.map(task => <div key={task.id} style={{ display: "flex", gap: 9, paddingTop: 12, fontSize: 12 }}><span style={{ width: 7, height: 7, flexShrink: 0, borderRadius: "50%", marginTop: 5, background: STATUS_COLOR[task.status] }} /><span style={{ color: "var(--text)", flex: 1 }}>{task.title}{task.note && <small style={{ display: "block", color: "var(--text-3)", marginTop: 2 }}>{task.note}</small>}</span><small style={{ color: "var(--text-3)" }}>{task.status}</small></div>)}</div>}
  </article>;
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
  const initiativesRailRef = useRef<HTMLDivElement | null>(null);

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

  const scrollInitiatives = (direction: -1 | 1) => {
    initiativesRailRef.current?.scrollBy({ left: direction * 320, behavior: "smooth" });
  };
  const tasks = home.squads.flatMap(squad => squad.tasks);
  const board = ["planned", "active", "waiting", "complete"] as const;

  return <main style={{ minHeight: "100%", padding: "clamp(20px, 4vw, 48px)", background: "radial-gradient(circle at 88% 0%, var(--accent-light), transparent 28%), var(--bg)" }}>
    <style>{`
      .company-home-initiative-delete { opacity: 0; transition: opacity .14s, background .14s, color .14s; }
      .company-home-initiative-card:hover .company-home-initiative-delete,
      .company-home-initiative-delete:focus-visible { opacity: 1; }
      .company-home-initiative-delete:hover { background: rgba(185, 28, 28, 0.1) !important; color: #b91c1c !important; }
      @media (hover: none) { .company-home-initiative-delete { opacity: 1; } }
    `}</style>
    <div style={{ maxWidth: 1440, margin: "0 auto" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 20, alignItems: "start", flexWrap: "wrap", marginBottom: 28 }}><div><p style={{ margin: 0, color: "var(--accent)", fontSize: 11, fontWeight: 700, letterSpacing: ".12em", textTransform: "uppercase" }}>Company Home</p><h1 style={{ margin: "7px 0", color: "var(--text)", fontSize: "clamp(28px, 4vw, 44px)", letterSpacing: "-.045em" }}>{activeCompany?.name ?? home.companyName}</h1><p style={{ maxWidth: 640, margin: 0, color: "var(--text-3)", lineHeight: 1.55 }}>{home.northStar}</p></div><div style={{ display: "flex", gap: 8, alignItems: "center", color: "var(--text-3)", fontSize: 12 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "#15803d" }} /> Company context connected</div></header>
      {notice && <p style={{ color: "#9a3412", fontSize: 12 }}>{notice}</p>}
      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.3fr) minmax(280px, .7fr)", gap: 18, marginBottom: 18 }}>
        <div style={{ padding: 18, borderRadius: "var(--r-lg)", background: "var(--bg-ink)", color: "var(--text-invert)" }}><div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 13, fontSize: 13 }}><Sparkles size={16} /> Permanent Copilot</div>{home.conversation.length > 0 && <div style={{ display: "grid", gap: 8, maxHeight: 180, overflowY: "auto", marginBottom: 14 }}>{home.conversation.map(turn => <p key={turn.id} style={{ margin: 0, fontSize: 12, lineHeight: 1.45, color: turn.author === "copilot" ? "var(--text-invert)" : "var(--text-3)" }}><b>{turn.author === "copilot" ? "Copilot" : "You"}: </b>{turn.message}</p>)}</div>}<AstraCopilotComposer value={message} onChange={setMessage} disabled={sending} onSubmit={async (value) => { setSending(true); setNotice("Copilot is forming a squad and briefing the department lead..."); try { const result = await sendCopilotMessage({ founderId, companyId }, value); setHome(result.data); setNotice(result.message); setMessage(""); } catch { setNotice("Copilot could not reach Company OS. Your message was not lost locally."); } finally { setSending(false); } }} agents={home.squads.map(s => ({ id: s.id.replace(/[^a-z0-9_]/gi, "_").toLowerCase(), label: s.name, status: s.lifecycle.toLowerCase() }))} contextLabel={sending ? "Copilot is coordinating your squad" : "Grounded in Company Brain"} placeholder="Ask Astra to coordinate your company" /></div>
        <aside style={{ padding: 18, border: "1px solid var(--border)", borderRadius: "var(--r-lg)", background: "var(--bg-surface)" }}><div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text)", fontWeight: 700 }}><Brain size={17} color="var(--accent)" /> Company Brain</div><p style={{ color: "var(--text-3)", fontSize: 12, lineHeight: 1.55 }}>{home.brain.summary}</p><div style={{ display: "flex", gap: 18, fontSize: 12 }}><span><b>{home.brain.recordCount}</b> records</span><span><b>{home.brain.sourceCount}</b> sources</span></div></aside>
      </section>
      <section style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ fontSize: 15, color: "var(--text)", margin: 0 }}>Initiatives {home.initiatives.length > 0 && <span style={{ color: "var(--text-3)", fontWeight: 400 }}>· {home.initiatives.length}</span>}</h2>
          {home.initiatives.length > 2 && (
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" aria-label="Scroll initiatives left" onClick={() => scrollInitiatives(-1)} style={{ width: 28, height: 28, display: "grid", placeItems: "center", border: "1px solid var(--border)", borderRadius: 7, background: "var(--bg-surface)", color: "var(--text-3)", cursor: "pointer" }}><ChevronLeft size={15} /></button>
              <button type="button" aria-label="Scroll initiatives right" onClick={() => scrollInitiatives(1)} style={{ width: 28, height: 28, display: "grid", placeItems: "center", border: "1px solid var(--border)", borderRadius: 7, background: "var(--bg-surface)", color: "var(--text-3)", cursor: "pointer" }}><ChevronRight size={15} /></button>
            </div>
          )}
        </div>
        {home.initiatives.length === 0 ? (
          <p style={{ margin: 0, padding: 16, border: "1px dashed var(--border)", borderRadius: "var(--r)", color: "var(--text-3)", fontSize: 12.5 }}>No initiatives yet. Ask Copilot to kick one off below.</p>
        ) : (
          <div ref={initiativesRailRef} style={{ display: "flex", gap: 12, overflowX: "auto", scrollSnapType: "x proximity", paddingBottom: 4 }}>
            {home.initiatives.map(item => (
              <article key={item.id} style={{ position: "relative", flex: "0 0 auto", width: 240, scrollSnapAlign: "start", padding: 15, border: "1px solid var(--border)", borderRadius: "var(--r)", background: "var(--bg-surface)" }} className="company-home-initiative-card">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                  <b style={{ color: "var(--text)", fontSize: 13, lineHeight: 1.35 }}>{item.title}</b>
                  <button
                    type="button"
                    aria-label={`Delete ${item.title}`}
                    disabled={deletingId === item.id}
                    onClick={() => void handleDeleteInitiative(item.id)}
                    className="company-home-initiative-delete"
                    style={{ flexShrink: 0, width: 24, height: 24, display: "grid", placeItems: "center", border: 0, borderRadius: 6, background: "transparent", color: "var(--text-3)", cursor: "pointer", opacity: deletingId === item.id ? 0.5 : undefined }}
                  ><Trash2 size={13} /></button>
                </div>
                <div style={{ height: 5, margin: "14px 0 8px", borderRadius: 8, background: "var(--bg-sunken)", overflow: "hidden" }}><div style={{ width: "100%", height: "100%", borderRadius: 8, background: "var(--accent)", transformOrigin: "left", transform: `scaleX(${item.progress / 100})`, transition: "transform .3s ease" }} /></div>
                <small style={{ color: "var(--text-3)" }}>{item.progress}% complete · {item.taskCount} tasks · {item.status}</small>
              </article>
            ))}
          </div>
        )}
      </section>
      <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(300px, .72fr)", gap: 18 }}><div><h2 style={{ fontSize: 15, color: "var(--text)" }}>Squad activity</h2><div style={{ display: "grid", gap: 10 }}>{home.squads.map(squad => <SquadCard key={squad.id} squad={squad} />)}</div><h2 style={{ fontSize: 15, color: "var(--text)", marginTop: 24 }}>Mission board</h2><div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(150px, 1fr))", gap: 9, overflowX: "auto" }}>{board.map(status => <div key={status} style={{ minWidth: 150, padding: 10, borderRadius: "var(--r)", background: "var(--bg-sunken)" }}><b style={{ color: "var(--text-2)", fontSize: 11, textTransform: "capitalize" }}>{status}</b>{tasks.filter(task => task.status === status).map(task => <div key={task.id} style={{ marginTop: 9, padding: 9, borderRadius: 6, background: "var(--bg-surface)", color: "var(--text)", fontSize: 11 }}>{task.title}<small style={{ display: "block", color: "var(--text-3)", marginTop: 4 }}>{task.squad}</small></div>)}</div>)}</div></div>
        <aside><h2 style={{ fontSize: 15, color: "var(--text)" }}>Approvals</h2><div style={{ display: "grid", gap: 10 }}>{home.approvals.map(item => <article key={item.id} style={{ padding: 14, border: "1px solid rgba(180,83,9,.35)", borderRadius: "var(--r)", background: "#fffaf0" }}><div style={{ display: "flex", gap: 8, color: "#92400e" }}><ShieldCheck size={16} /><b style={{ fontSize: 13 }}>{item.title}</b></div><p style={{ margin: "8px 0", fontSize: 12, color: "#78350f" }}>{item.detail}</p><small style={{ color: "#a16207" }}>{item.squad}</small></article>)}</div><h2 style={{ fontSize: 15, color: "var(--text)", marginTop: 24 }}>Artifacts</h2><div style={{ display: "grid", gap: 8 }}>{home.brain.artifacts.map(item => <button key={item.id} type="button" onClick={() => { setArtifactError(""); void getCompanyArtifact({ founderId, companyId }, item.id).then(setArtifact).catch(() => setArtifactError("This artifact could not be opened.")); }} style={{ display: "flex", gap: 9, padding: 11, color: "inherit", textAlign: "left", cursor: "pointer", border: "1px solid var(--border)", borderRadius: "var(--r)", background: "var(--bg-surface)" }}><FileText size={16} color="var(--accent)" /><span style={{ minWidth: 0 }}><b style={{ display: "block", color: "var(--text)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</b><small style={{ color: "var(--text-3)" }}>{item.source} · {item.updatedAt}</small></span></button>)}</div></aside>
      </section>
    </div>
    {(artifact || artifactError) && <div role="dialog" aria-modal="true" aria-label="Artifact preview" style={{ position: "fixed", inset: 0, zIndex: 30, display: "grid", placeItems: "center", padding: 20, background: "rgba(2,6,23,.68)" }}><section style={{ width: "min(820px, 100%)", maxHeight: "86vh", overflow: "auto", padding: 22, borderRadius: "var(--r-lg)", background: "var(--bg-surface)", border: "1px solid var(--border)" }}>{artifact ? <><div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "start" }}><div><h2 style={{ margin: 0, color: "var(--text)", fontSize: 18 }}>{artifact.title}</h2><small style={{ color: "var(--text-3)" }}>{artifact.source} · {artifact.updatedAt}</small></div><button type="button" onClick={() => setArtifact(null)} style={{ border: 0, background: "transparent", color: "var(--text-3)", cursor: "pointer" }}>Close</button></div><pre style={{ margin: "20px 0", padding: 16, whiteSpace: "pre-wrap", overflowWrap: "anywhere", borderRadius: "var(--r)", background: "var(--bg-sunken)", color: "var(--text)", fontFamily: "inherit", fontSize: 13, lineHeight: 1.6 }}>{artifact.content || "This artifact has no previewable text."}</pre><button type="button" onClick={() => { const url = URL.createObjectURL(new Blob([artifact.content], { type: "text/markdown" })); const link = document.createElement("a"); link.href = url; link.download = `${artifact.title.replaceAll(/[^a-z0-9]+/gi, "-").replaceAll(/(^-|-$)/g, "") || "artifact"}.md`; link.click(); URL.revokeObjectURL(url); }} style={{ padding: "9px 13px", border: 0, borderRadius: 7, background: "var(--accent)", color: "var(--text-invert)", cursor: "pointer" }}>Download artifact</button></> : <><p style={{ color: "var(--text)" }}>{artifactError}</p><button type="button" onClick={() => setArtifactError("")}>Close</button></>}</section></div>}
  </main>;
}
