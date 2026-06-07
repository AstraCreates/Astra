"use client";

/* Redesigned session monitor — ported from mockup/app/index.html (#v-sess).
   Self-contained: own SSE + state, wired to the real backend via apiFetch.
   Layout: phase bar → status bar → dept cards → vault | detail → steer bar. */

import { useCallback, useEffect, useReducer, useRef } from "react";
import { apiFetch, killSession, decideStackApproval } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type LogEntry = { ts: number; type: string; text: string };
type Agent = { key: string; status: string; log: LogEntry[]; visitedUrls: string[]; currentTool: string | null; result: unknown; instruction: string };
type Artifact = { key?: string; title?: string; status?: string; preview?: string; content?: string; description?: string; owner_agent?: string };
type Approval = { gate_key: string; title?: string; reason?: string; description?: string; triggered_by?: string; agent?: string; ts: number };

type SState = {
  status: string; goal: string; company: string; stackId: string;
  agents: Record<string, Agent>;
  artifacts: Artifact[]; approvals: Approval[]; decidedKeys: Set<string>;
  selDept: string | null; selArt: string | null; tab: string;
};

// Named phases per stack (agent prefixes per phase). Drives the top phase bar.
const PHASE_PLANS: Record<string, { name: string; groups: string[] }[]> = {
  idea_to_revenue: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Design", groups: ["design", "technical"] },
    { name: "Deploy", groups: ["web", "marketing", "sales"] },
    { name: "Govern", groups: ["legal"] },
    { name: "Operate", groups: ["ops"] },
  ],
  sales: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Deploy", groups: ["sales", "marketing"] },
    { name: "Operate", groups: ["ops"] },
  ],
  marketing: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Design", groups: ["design"] },
    { name: "Deploy", groups: ["marketing", "web"] },
    { name: "Operate", groups: ["ops"] },
  ],
  founder_ops: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Design", groups: ["technical"] },
    { name: "Govern", groups: ["legal"] },
    { name: "Operate", groups: ["ops"] },
  ],
  support: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Deploy", groups: ["ops", "marketing"] },
    { name: "Design", groups: ["technical"] },
  ],
  product: [
    { name: "Diagnose", groups: ["research"] },
    { name: "Design", groups: ["design", "technical", "ops"] },
  ],
};

const DEPTS: Record<string, { n: string; ic: string; ags: string[] }> = {
  research:  { n: "Research",  ic: "🔬", ags: ["research", "research_competitors", "research_market", "research_execution", "research_financial", "research_regulatory"] },
  design:    { n: "Design",    ic: "🎨", ags: ["design"] },
  technical: { n: "Technical", ic: "⚙️", ags: ["technical", "technical_scaffold", "technical_infra", "technical_data", "web", "web_navigator"] },
  marketing: { n: "Marketing", ic: "📣", ags: ["marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid"] },
  legal:     { n: "Legal",     ic: "⚖️", ags: ["legal", "legal_docs", "legal_entity", "legal_ip"] },
  sales:     { n: "Sales",     ic: "💼", ags: ["sales", "sales_pipeline", "sales_enablement", "ops"] },
  finance:   { n: "Finance",   ic: "💰", ags: ["finance_model", "finance_fundraise"] },
};
const PENDING = new Set(["pending", "triggered", "armed", "waiting_approval"]);

function agToDept(k: string): string | null {
  for (const [dk, d] of Object.entries(DEPTS)) if (d.ags.includes(k)) return dk;
  return null;
}
function ago(ts: number | string | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - (typeof ts === "number" ? ts : new Date(ts).getTime());
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now"; if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function SessionView({ sessionId }: { sessionId: string }) {
  const { userId } = useDevUser();
  const founderId = userId;
  const S = useRef<SState>({
    status: "loading", goal: "", company: "", stackId: "", agents: {}, artifacts: [], approvals: [],
    decidedKeys: new Set(), selDept: null, selArt: null, tab: "log",
  });
  const [, force] = useReducer((x: number) => x + 1, 0);
  const sseRef = useRef<EventSource | null>(null);
  const steerRef = useRef<HTMLInputElement>(null);

  const ensureAg = (key: string) => {
    if (!S.current.agents[key]) S.current.agents[key] = { key, status: "waiting", log: [], visitedUrls: [], currentTool: null, result: null, instruction: "" };
  };
  const addLog = (agentKey: string, type: string, text: string) => {
    ensureAg(agentKey);
    const entry = { ts: Date.now(), type, text: String(text || "").slice(0, 500) };
    const ag = S.current.agents[agentKey];
    ag.log.push(entry);
    if (ag.log.length > 300) ag.log.shift();
    const m = text && text.match(/https?:\/\/[^\s"',>)]+/);
    if (m && !ag.visitedUrls.includes(m[0])) ag.visitedUrls.push(m[0]);
  };

  const handleEvent = useCallback((ev: Record<string, any>) => {
    const st = S.current;
    switch (ev.type) {
      case "goal_start":
        st.goal = ev.goal || ev.instruction || st.goal; st.status = "running"; break;
      case "plan_done":
        if (Array.isArray(ev.tasks)) ev.tasks.forEach((t: any) => t.agent && ensureAg(t.agent));
        if (Array.isArray(ev.agents)) ev.agents.forEach((a: string) => ensureAg(a));
        break;
      case "company_genome": case "company_name":
        if (ev.company_name || ev.name) st.company = ev.company_name || ev.name; break;
      case "agent_start":
        ensureAg(ev.agent); st.agents[ev.agent].status = "running";
        if (ev.instruction) st.agents[ev.agent].instruction = ev.instruction;
        addLog(ev.agent, "start", ev.instruction || "Started"); break;
      case "agent_thinking": case "reasoning":
        if (ev.agent) addLog(ev.agent, "think", ev.text || ev.reasoning || ev.content || ""); break;
      case "agent_tool_call": case "agent_action": case "tool_use": {
        if (!ev.agent) break;
        const tn = ev.tool || ev.action || ev.function || ev.name || "tool";
        const ta = ev.args || ev.input || ev.parameters || {};
        addLog(ev.agent, "tool", `${tn}: ${(typeof ta === "string" ? ta : JSON.stringify(ta)).slice(0, 150)}`);
        st.agents[ev.agent].currentTool = tn; break;
      }
      case "agent_action_result": case "tool_result":
        if (ev.agent) addLog(ev.agent, "result", String(ev.result || ev.output || ev.content || "").slice(0, 300)); break;
      case "agent_build": {
        // Technical build stream — fold into the technical agent log.
        const a = ev.agent || "technical"; ensureAg(a);
        const k = ev.kind;
        if (k === "file") addLog(a, "tool", `${ev.verb || "wrote"} ${ev.path} (${ev.size ?? 0}b)`);
        else if (k === "command") addLog(a, "tool", `$ ${ev.command || ""}`);
        else if (k === "output") addLog(a, "result", String(ev.text || "").slice(0, 300));
        else if (k === "error") addLog(a, "error", String(ev.text || "").slice(0, 300));
        else if (k === "phase" || k === "plan" || k === "build_start") addLog(a, "think", ev.text || ev.goal || "");
        break;
      }
      case "agent_done":
        ensureAg(ev.agent); st.agents[ev.agent].status = "done"; st.agents[ev.agent].currentTool = null; st.agents[ev.agent].result = ev.result;
        addLog(ev.agent, "done", "Completed"); break;
      case "agent_error":
        ensureAg(ev.agent); st.agents[ev.agent].status = "error"; st.agents[ev.agent].currentTool = null;
        addLog(ev.agent, "error", ev.error || ev.message || "Error"); break;
      case "stack_artifact": case "artifact": {
        const art = ev.artifact || ev;
        if (!art.key && !art.title) break;
        const idx = st.artifacts.findIndex((a) => a.key === art.key);
        if (idx >= 0) st.artifacts[idx] = { ...st.artifacts[idx], ...art };
        else st.artifacts.push(art);
        break;
      }
      case "approval_request": case "stack_approval_queue": case "saferun_action": {
        const raw = ev.request || ev;
        const apv: Approval = {
          gate_key: raw.gate_key || raw.key || ev.approval_gate || raw.id || "",
          title: raw.title || (ev.approval_gate || "").replace(/_/g, " "),
          reason: raw.reason || ev.reason || "",
          triggered_by: raw.action_id || raw.triggered_by || ev.agent || ev.tool || "",
          agent: raw.agent || ev.agent || "", ts: Date.now(),
        };
        if (!apv.gate_key || st.decidedKeys.has(apv.gate_key)) break;
        if (!st.approvals.find((a) => a.gate_key === apv.gate_key)) st.approvals.push(apv);
        break;
      }
      case "stack_approval_decision":
        if (ev.gate_key) st.decidedKeys.add(ev.gate_key);
        st.approvals = st.approvals.filter((a) => a.gate_key !== ev.gate_key); break;
      case "company_operating":
        st.status = "done"; break;
      case "goal_done":
        st.status = "done"; sseRef.current?.close(); break;
      case "goal_error":
        st.status = "error"; sseRef.current?.close(); break;
      default: return; // ignore pings/unknown without re-render
    }
    force();
  }, []);

  // Load meta + state, then connect SSE.
  useEffect(() => {
    if (!sessionId || !founderId) return;
    let alive = true;
    S.current = { status: "loading", goal: "", company: "", stackId: "", agents: {}, artifacts: [], approvals: [], decidedKeys: new Set(), selDept: null, selArt: null, tab: "log" };
    force();

    (async () => {
      // goal + status from sessions list (state has no goal)
      try {
        const r = await apiFetch(`${API}/sessions?founder_id=${encodeURIComponent(founderId)}`);
        if (r.ok) {
          const d = await r.json();
          const meta = (d.sessions || d || []).find((s: any) => s.session_id === sessionId);
          if (meta && alive) { S.current.goal = meta.goal || meta.instruction || ""; S.current.status = meta.status || "running"; S.current.company = meta.company_name || ""; S.current.stackId = meta.stack_id || ""; }
        }
      } catch {}
      // rich state (404 normal)
      try {
        const r = await apiFetch(`${API}/sessions/${sessionId}/state`);
        if (r.ok && alive) {
          const d = await r.json();
          if (!S.current.goal) S.current.goal = d.instruction || "";
          if (d.stack_id) S.current.stackId = d.stack_id;
          S.current.status = d.status || S.current.status;
          S.current.artifacts = Array.isArray(d.artifacts) ? d.artifacts : [];
          S.current.approvals = Array.isArray(d.approvals) ? d.approvals.filter((a: any) => PENDING.has(a.status)) : [];
          if (d.agents && typeof d.agents === "object") {
            for (const [k, ag] of Object.entries<any>(d.agents)) {
              S.current.agents[k] = { key: k, status: ag.status || "waiting", log: ag.log || [], visitedUrls: ag.visitedUrls || ag.visited_urls || [], currentTool: null, result: ag.result || null, instruction: ag.instruction || "" };
            }
          }
        }
      } catch {}
      if (!alive) return;
      if (S.current.status === "loading") S.current.status = "running";
      force();

      const es = new EventSource(`${API}/stream/${sessionId}`);
      sseRef.current = es;
      es.onmessage = (e) => { try { const ev = JSON.parse(e.data); if (ev.type !== "ping") handleEvent(ev); } catch {} };
    })();

    return () => { alive = false; sseRef.current?.close(); sseRef.current = null; };
  }, [sessionId, founderId, handleEvent]);

  const decide = async (key: string, decision: "approved" | "skipped" | "rejected") => {
    const snapshot = S.current.approvals;
    S.current.decidedKeys.add(key);
    S.current.approvals = S.current.approvals.filter((a) => a.gate_key !== key);
    force();
    try {
      await decideStackApproval(sessionId, key, decision as "approved" | "skipped", founderId);
    } catch (e) {
      // Restore so the founder can retry — don't pretend it was accepted.
      S.current.decidedKeys.delete(key);
      S.current.approvals = snapshot;
      force();
      alert(`Approval failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const sendSteer = async () => {
    const msg = steerRef.current?.value.trim(); if (!msg) return;
    if (steerRef.current) steerRef.current.value = "";
    try { await apiFetch(`${API}/steer/${sessionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg }) }); } catch {}
  };
  const stop = async () => { if (!confirm("Stop this run?")) return; await killSession(sessionId); S.current.status = "killed"; sseRef.current?.close(); force(); };
  const sel = (dept: string | null, art: string | null) => { S.current.selDept = dept; S.current.selArt = art; S.current.tab = art ? "read" : "log"; force(); };

  // ── Derived render data ──
  const st = S.current;
  const agents = Object.values(st.agents);
  const total = agents.length, run = agents.filter((a) => a.status === "running").length,
    done = agents.filter((a) => a.status === "done").length, err = agents.filter((a) => a.status === "error").length;
  const artReady = st.artifacts.filter((a) => a.status === "ready").length;

  const plan = PHASE_PLANS[st.stackId];
  let phases: [string, string][];
  if (plan) {
    if (st.status === "done") {
      phases = [...plan.map((p) => ["done", p.name] as [string, string]), ["act", "Complete"]];
    } else {
      const built = plan.map((ph) => {
        const ags = agents.filter((a) => ph.groups.some((g) => a.key === g || a.key.startsWith(g + "_") || a.key === g));
        const present = ags.length > 0;
        return { name: ph.name, allDone: present && ags.every((a) => a.status === "done"), anyRun: ags.some((a) => a.status === "running") };
      });
      let frontier = false;
      phases = built.map((b) => {
        if (b.allDone) return ["done", b.name];
        if (b.anyRun) { frontier = true; return ["act", b.name]; }
        return ["", b.name];
      });
      if (!frontier) { const i = phases.findIndex(([c]) => c !== "done"); if (i >= 0) phases[i] = ["act", phases[i][1]]; }
      phases.push(["", "Complete"]);
    }
  } else {
    phases = st.status === "done"
      ? [["done", "Planning"], ["done", "Execution"], ["act", "Complete"]]
      : !total ? [["act", "Planning"], ["", "Execution"], ["", "Complete"]]
      : st.approvals.length ? [["done", "Planning"], ["act", "Execution"], ["act", "Approval"], ["", "Complete"]]
      : [["done", "Planning"], ["act", "Execution"], ["", "Complete"]];
  }

  // active depts
  const activeDepts: [string, { n: string; ic: string; ags: string[]; inS: string[] }][] = [];
  for (const [dk, d] of Object.entries(DEPTS)) {
    const inS = d.ags.filter((a) => st.agents[a]);
    if (inS.length) activeDepts.push([dk, { ...d, inS }]);
  }
  const otherAgs = Object.keys(st.agents).filter((k) => !agToDept(k));
  if (otherAgs.length) activeDepts.push(["__other", { n: "Other", ic: "🤖", ags: otherAgs, inS: otherAgs }]);

  const deptSt = (inS: string[]) => {
    if (!inS.length) return "que";
    const sts = inS.map((a) => st.agents[a].status);
    if (sts.includes("running")) return "run";
    if (sts.every((s) => s === "done")) return "done";
    if (sts.includes("error")) return "err";
    return "que";
  };
  const deptWhat = (inS: string[]) => {
    const running = inS.find((a) => st.agents[a].status === "running");
    if (running) {
      const ag = st.agents[running];
      if (ag.currentTool) return `Using: ${ag.currentTool}`;
      const last = ag.log[ag.log.length - 1];
      return (last ? last.text : ag.instruction || "Working…").slice(0, 80);
    }
    const d = inS.filter((a) => st.agents[a].status === "done").length;
    if (d === inS.length && inS.length) return `All ${d} agent${d > 1 ? "s" : ""} done`;
    if (d) return `${d}/${inS.length} done`;
    return "Waiting to start";
  };

  const ready = st.artifacts.filter((a) => a.status === "ready");
  const live = st.artifacts.filter((a) => a.status !== "ready");
  const shortGoal = st.goal ? st.goal.slice(0, 70) + (st.goal.length > 70 ? "…" : "") : `Session ${sessionId.slice(0, 8)}`;
  const ICONS: Record<string, string> = { think: "💭", tool: "🔍", result: "→", done: "✓", error: "✗", start: "↳" };
  const LABELS: Record<string, string> = { think: "Thinking", tool: "Searching", result: "Found", done: "Done", error: "Error", start: "Started" };

  const statusPill = (s: string) => {
    const map: Record<string, [string, string]> = { running: ["blue", "● Running"], done: ["green", "✓ Done"], error: ["red", "✗ Error"], killed: ["red", "■ Stopped"], loading: ["blue", "● Running"] };
    const [cls, txt] = map[s] || ["", s];
    return <span className={`pill ${cls}`}>{txt}</span>;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "var(--bg)" }}>
      {/* topbar */}
      <div style={{ height: 44, display: "flex", alignItems: "center", gap: 10, padding: "0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
        <div className="topbar-title" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{st.company ? `${st.company} — ${shortGoal}` : shortGoal}</div>
        {statusPill(st.status)}
        {(st.status === "running" || st.status === "loading") && <button className="btn danger sm" onClick={stop}>Stop</button>}
      </div>

      {/* urgent banner */}
      {st.approvals.length > 0 && (
        <div style={{ background: "var(--red)", flexShrink: 0, animation: "astraSlideDown .25s ease both" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 18px" }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#fff" }} className="blink" />
            <div>
              <div style={{ fontFamily: "var(--font-chakra)", fontSize: 12, fontWeight: 700, color: "#fff" }}>Action Required — Astra is waiting for you</div>
              <div style={{ fontSize: 9.5, color: "rgba(255,255,255,.7)" }}>{st.approvals[0].title || "An agent needs your approval."}</div>
            </div>
          </div>
        </div>
      )}

      {/* done banner */}
      {st.status === "done" && (
        <div className="done-bar"><div><div className="done-title">✓ Run complete</div><div className="done-sub">All agents finished. Deliverables are in the vault.</div></div></div>
      )}

      {/* phase bar */}
      <div className="phasebar">
        {phases.map(([cls, lbl], i) => (
          <span key={i} style={{ display: "contents" }}>
            <div className={`ph ${cls}`}><div className="ph-dot" />{lbl}</div>
            {i < phases.length - 1 && <div className="ph-div" />}
          </span>
        ))}
      </div>

      {/* status bar */}
      <div className="sbar">
        {st.status === "done" ? <><span className="sv g">✓</span> Complete · <span className="sv g">{done}</span> agents · <span className="sv g">{artReady}</span> deliverable{artReady !== 1 ? "s" : ""}</>
        : st.status === "error" ? <><span className="sv r">✗</span> Failed · <span className="sv r">{err}</span> error{err !== 1 ? "s" : ""}</>
        : !total ? <><div className="live-dot" /><span style={{ color: "var(--fd)" }}>Planning your goal…</span></>
        : st.approvals.length ? <><span className="sv r">⚠</span> Approval needed — run paused <div className="s-sep" /> <span className="sv g">{done}</span> done</>
        : <>
            {run > 0 && <><div className="live-dot" /><span className="sv b">{run}</span> working</>}
            {done > 0 && <><div className="s-sep" /><span className="sv g">{done}</span> done</>}
            {err > 0 && <><div className="s-sep" /><span className="sv r">{err}</span> error{err !== 1 ? "s" : ""}</>}
            {artReady > 0 && <><div className="s-sep" /><span className="sv g">{artReady}</span> deliverable{artReady !== 1 ? "s" : ""}</>}
          </>}
      </div>

      {/* dept cards */}
      <div className="depts">
        {activeDepts.length === 0 ? <div style={{ padding: 6, fontSize: 9.5, color: "var(--fm)" }}>Waiting for agents…</div>
        : activeDepts.map(([dk, d]) => {
          const s = deptSt(d.inS);
          const prog = d.inS.length ? Math.round(d.inS.filter((a) => st.agents[a].status === "done").length / d.inS.length * 100) : 0;
          const bc = s === "done" ? "var(--green)" : s === "run" ? "var(--blue)" : s === "err" ? "var(--red)" : "var(--fm)";
          const badge = s === "run" ? "Working" : s === "done" ? "Done" : s === "err" ? "Error" : "Queued";
          return (
            <div key={dk} className={`dc ${s}${st.selDept === dk ? " sel" : ""}`} onClick={() => sel(dk, null)}>
              <div className="dc-top"><div className="dc-ico">{d.ic}</div><div className="dc-name">{d.n}</div><div className={`dc-badge ${s}`}>{badge}</div></div>
              <div className="dc-what">{deptWhat(d.inS)}</div>
              <div className="dc-prog"><div className="dc-bar" style={{ width: `${prog}%`, background: bc }} /></div>
            </div>
          );
        })}
      </div>

      {/* workspace: vault | detail */}
      <div className="sess-ws">
        {/* vault */}
        <div className="vault">
          <div className="v-sec">Deliverables</div>
          {st.artifacts.length === 0 ? <div style={{ padding: "10px 8px", fontSize: 9.5, color: "var(--fm)", lineHeight: 1.55 }}>{st.status === "running" ? "Agents working — deliverables appear here when ready." : "Nothing yet."}</div>
          : <>
            {ready.length > 0 && <><div style={{ fontSize: 9, color: "var(--fm)", padding: "3px 8px", display: "flex", alignItems: "center", gap: 4 }}><span className="v-dot ready" /> Ready</div>
              {ready.map((a) => <div key={a.key} className={`v-art${st.selArt === a.key ? " sel" : ""}`} onClick={() => sel(null, a.key || null)}>{a.title || a.key}</div>)}</>}
            {live.length > 0 && <><div style={{ fontSize: 9, color: "var(--fm)", padding: "3px 8px", display: "flex", alignItems: "center", gap: 4 }}><span className="v-dot live" /> Writing</div>
              {live.map((a) => <div key={a.key} className={`v-art${st.selArt === a.key ? " sel" : ""}`} onClick={() => sel(null, a.key || null)}>{a.title || a.key}</div>)}</>}
          </>}
        </div>

        {/* detail */}
        <div className="detail">
          <div className="dtabs">
            {st.selArt ? <><div className={`dtab${st.tab === "read" ? " on" : ""}`} onClick={() => { st.tab = "read"; force(); }}>Read it</div></>
            : st.selDept ? <>
                <div className={`dtab${st.tab === "log" ? " on" : ""}`} onClick={() => { st.tab = "log"; force(); }}>What happened</div>
                <div className={`dtab${st.tab === "sources" ? " on" : ""}`} onClick={() => { st.tab = "sources"; force(); }}>Sources</div>
              </>
            : <div className="dtab on">What happened</div>}
          </div>
          <div className="dscroll">
            {/* approval cards always first */}
            {st.approvals.map((ap) => (
              <div key={ap.gate_key} className="apv">
                <div className="apv-hd"><div className="apv-ht">🔒 {ap.title || "Action requires your approval"}</div><div className="apv-mt">{ap.triggered_by || ap.agent || "Agent"} · {ago(ap.ts)}</div></div>
                <div className="apv-body">
                  <div className="apv-reason">{ap.reason || ap.description || "An agent wants to take a significant action and needs your go-ahead."}</div>
                  <div className="apv-acts">
                    <button className="btn-ok" onClick={() => decide(ap.gate_key, "approved")}>✓ Approve</button>
                    <button className="btn-skip" onClick={() => decide(ap.gate_key, "skipped")}>Skip</button>
                    <button className="btn-reject" onClick={() => decide(ap.gate_key, "rejected")}>✗ Reject</button>
                  </div>
                </div>
              </div>
            ))}

            {/* selected artifact */}
            {st.selArt && (() => {
              const art = st.artifacts.find((a) => a.key === st.selArt);
              if (!art) return null;
              return <>
                <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{art.title || art.key}</div>
                <div style={{ fontSize: 9, color: art.status === "ready" ? "var(--green)" : "var(--amber)", marginBottom: 6 }}>{art.status === "ready" ? "✓ ready" : "⋯ being written"}</div>
                <pre className="art-pre">{art.preview || art.content || art.description || "(No preview yet)"}</pre>
              </>;
            })()}

            {/* selected dept log / sources */}
            {st.selDept && !st.selArt && (() => {
              const d = st.selDept === "__other" ? { ags: otherAgs } : DEPTS[st.selDept] || { ags: [] };
              const ags = (d.ags || []).filter((a) => st.agents[a]);
              if (st.tab === "sources") {
                const urls: string[] = [];
                for (const k of ags) for (const u of st.agents[k].visitedUrls) if (!urls.includes(u)) urls.push(u);
                if (!urls.length) return <div style={{ color: "var(--fm)", fontSize: 10 }}>No sources logged yet.</div>;
                return <><div style={{ fontFamily: "var(--font-chakra)", fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".14em" }}>{urls.length} source{urls.length !== 1 ? "s" : ""} visited</div>
                  <div className="url-list" style={{ display: "flex", flexDirection: "column", gap: 3 }}>{urls.map((u) => { let dm = u; try { dm = new URL(u).hostname.replace(/^www\./, ""); } catch {} return <a key={u} className="url-item" href={u} target="_blank" rel="noreferrer">{dm} ↗</a>; })}</div></>;
              }
              const all: (LogEntry & { agent: string })[] = [];
              for (const k of ags) for (const e of st.agents[k].log) all.push({ ...e, agent: k });
              all.sort((a, b) => a.ts - b.ts);
              if (!all.length) return <div style={{ color: "var(--fd)", fontSize: 10 }}>{ags.map((a) => st.agents[a].status === "running" ? "Working…" : "Waiting to start").join(" / ") || "No agents active yet."}</div>;
              return <><div style={{ fontFamily: "var(--font-chakra)", fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".14em", marginBottom: 4 }}>Activity log</div>
                {all.slice(-120).map((l, i) => (
                  <div key={i} className={`le ${l.type}`}>
                    <div className="le-ic">{ICONS[l.type] || "·"}</div>
                    <div><div style={{ fontFamily: "var(--font-chakra)", fontSize: 7.5, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".1em" }}>{LABELS[l.type] || l.type}{ags.length > 1 ? ` · ${l.agent}` : ""}</div><div className="le-txt">{l.text}</div></div>
                  </div>
                ))}</>;
            })()}

            {/* empty */}
            {!st.selDept && !st.selArt && st.approvals.length === 0 && (
              <div className="empty"><div style={{ fontSize: 34, opacity: .12 }}>◈</div><div className="empty-title">Select a department</div><div className="empty-sub" style={{ fontSize: 10.5, maxWidth: 260, lineHeight: 1.6 }}>Click a card above to see what that team is working on.</div></div>
            )}
          </div>
        </div>
      </div>

      {/* steer bar */}
      <div className="steerbar">
        <div className="steer-wrap">
          <input ref={steerRef} className="steer-inp" placeholder='Steer Astra — "focus more on pricing" · "skip legal" · "make it B2B"'
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendSteer(); } }} />
          <button className="steer-send" onClick={sendSteer}>↑</button>
        </div>
      </div>
    </div>
  );
}
