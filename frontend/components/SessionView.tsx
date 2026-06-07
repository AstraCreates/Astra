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
type Approval = { gate_key: string; title?: string; reason?: string; description?: string; triggered_by?: string; agent?: string; ts: number; is_phase_gate?: boolean; phase?: string; next_phase?: string; artifacts?: { key: string; title: string; agent: string }[] };

type SState = {
  status: string; goal: string; company: string; projectName: string; stackId: string;
  agents: Record<string, Agent>;
  artifacts: Artifact[]; approvals: Approval[]; decidedKeys: Set<string>;
  selDept: string | null; selArt: string | null; tab: string; paused: boolean;
  revisionGate: string | null; revisionNote: string;
};

function safeText(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch {} }
  return String(v);
}

function extractProjectName(goal: string): { projectName: string; cleanGoal: string } {
  let m = goal.match(/^Company name: (.+?)\.\s*\n+([\s\S]*)$/);
  if (m) return { projectName: m[1].trim(), cleanGoal: m[2].trim() };
  m = goal.match(/^Company\/project name: (.+?)\n+([\s\S]*)$/);
  if (m) return { projectName: m[1].trim(), cleanGoal: m[2].trim() };
  return { projectName: "", cleanGoal: goal };
}

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
// Actionable = an agent actually hit the gate and is blocked waiting on the founder.
// "armed" is NOT actionable: it's a pre-configured gate slot that exists from the
// moment the run starts — showing it as an approval card means "approve nothing".
const PENDING = new Set(["pending", "triggered", "waiting_approval"]);

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
    status: "loading", goal: "", company: "", projectName: "", stackId: "", agents: {}, artifacts: [], approvals: [],
    decidedKeys: new Set(), selDept: null, selArt: null, tab: "updates", paused: false,
    revisionGate: null, revisionNote: "",
  });
  const [, force] = useReducer((x: number) => x + 1, 0);
  const sseRef = useRef<EventSource | null>(null);
  const steerRef = useRef<HTMLInputElement>(null);

  const ensureAg = (key: string) => {
    if (!S.current.agents[key]) S.current.agents[key] = { key, status: "waiting", log: [], visitedUrls: [], currentTool: null, result: null, instruction: "" };
  };
  const addLog = (agentKey: string, type: string, text: unknown) => {
    ensureAg(agentKey);
    const str = safeText(text).slice(0, 500);
    const entry = { ts: Date.now(), type, text: str };
    const ag = S.current.agents[agentKey];
    ag.log.push(entry);
    if (ag.log.length > 300) ag.log.shift();
    const m = str.match(/https?:\/\/[^\s"',>)]+/);
    if (m && !ag.visitedUrls.includes(m[0])) ag.visitedUrls.push(m[0]);
  };

  const handleEvent = useCallback((ev: Record<string, any>) => {
    const st = S.current;
    switch (ev.type) {
      case "goal_start": {
        const rawGoal = ev.goal || ev.instruction || st.goal;
        const { projectName, cleanGoal } = extractProjectName(rawGoal);
        st.goal = cleanGoal;
        if (!st.projectName && projectName) st.projectName = projectName;
        st.status = "running"; break;
      }
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
        if (ev.agent) addLog(ev.agent, "result", safeText(ev.result || ev.output || ev.content || "").slice(0, 300)); break;
      case "agent_build": {
        // Technical build stream — fold into the technical agent log.
        const a = ev.agent || "technical"; ensureAg(a);
        const k = ev.kind;
        if (k === "file") addLog(a, "tool", `${ev.verb || "wrote"} ${ev.path} (${ev.size ?? 0}b)`);
        else if (k === "command") addLog(a, "tool", `$ ${ev.command || ""}`);
        else if (k === "output") addLog(a, "result", safeText(ev.text || "").slice(0, 300));
        else if (k === "error") addLog(a, "error", safeText(ev.text || "").slice(0, 300));
        else if (k === "phase" || k === "plan" || k === "build_start") addLog(a, "think", ev.text || ev.goal || "");
        break;
      }
      case "agent_done": {
        ensureAg(ev.agent); st.agents[ev.agent].status = "done"; st.agents[ev.agent].currentTool = null; st.agents[ev.agent].result = ev.result;
        const _r = ev.result as Record<string, unknown> | null;
        const _sum = (_r && typeof _r === "object")
          ? (String(_r.summary || _r.output_summary || _r.headline || _r.tldr || _r.text || _r.formatted_text || "")).trim().slice(0, 400)
          : "";
        addLog(ev.agent, "done", _sum || "Agent finished"); break;
      }
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
          is_phase_gate: raw.is_phase_gate || false,
          phase: raw.phase || "",
          next_phase: raw.next_phase || "",
          artifacts: raw.artifacts || [],
        };
        if (!apv.gate_key || st.decidedKeys.has(apv.gate_key)) break;
        // Replace existing gate with same key (e.g. after rejection re-fire)
        const existIdx = st.approvals.findIndex((a) => a.gate_key === apv.gate_key);
        if (existIdx >= 0) st.approvals[existIdx] = apv;
        else st.approvals.push(apv);
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
    S.current = { status: "loading", goal: "", company: "", projectName: "", stackId: "", agents: {}, artifacts: [], approvals: [], decidedKeys: new Set(), selDept: null, selArt: null, tab: "updates", paused: false, revisionGate: null, revisionNote: "" };
    force();

    (async () => {
      // goal + status from sessions list (state has no goal)
      try {
        const r = await apiFetch(`${API}/sessions?founder_id=${encodeURIComponent(founderId)}`);
        if (r.ok) {
          const d = await r.json();
          const meta = (d.sessions || d || []).find((s: any) => s.session_id === sessionId);
          if (meta && alive) {
            const rawGoal = meta.goal || meta.instruction || "";
            const { projectName, cleanGoal } = extractProjectName(rawGoal);
            S.current.goal = cleanGoal;
            S.current.projectName = projectName;
            S.current.status = meta.status || "running";
            S.current.company = meta.company_name || "";
            S.current.stackId = meta.stack_id || "";
          }
        }
      } catch {}
      // rich state (404 normal)
      try {
        const r = await apiFetch(`${API}/sessions/${sessionId}/state`);
        if (r.ok && alive) {
          const d = await r.json();
          if (!S.current.goal && d.instruction) {
            const { projectName, cleanGoal } = extractProjectName(d.instruction);
            S.current.goal = cleanGoal;
            if (!S.current.projectName) S.current.projectName = projectName;
          }
          if (d.stack_id) S.current.stackId = d.stack_id;
          else if (d.stack?.stack_id && !S.current.stackId) S.current.stackId = d.stack.stack_id;
          S.current.status = d.status || S.current.status;
          S.current.artifacts = Array.isArray(d.artifacts) ? d.artifacts : [];
          S.current.approvals = Array.isArray(d.approvals)
            ? d.approvals
                .filter((a: any) => PENDING.has(a.status) && (a.gate_key || a.key))
                .map((a: any) => ({ ...a, gate_key: a.gate_key || a.key }))
            : [];
          if (d.agents && typeof d.agents === "object") {
            for (const [k, ag] of Object.entries<any>(d.agents)) {
              const rawLog: any[] = ag.log || [];
              S.current.agents[k] = {
                key: k, status: ag.status || "waiting",
                log: rawLog.map((e) => ({ ts: e.ts ?? Date.now(), type: String(e.type || ""), text: safeText(e.text) })),
                visitedUrls: ag.visitedUrls || ag.visited_urls || [],
                currentTool: null, result: ag.result || null, instruction: ag.instruction || "",
              };
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

  const decide = async (key: string, decision: "approved" | "skipped" | "rejected", note?: string) => {
    if (!key) { alert("This approval is missing its gate key — refresh the page (Cmd+Shift+R) and try again."); return; }
    const snapshot = S.current.approvals;
    S.current.decidedKeys.add(key);
    S.current.approvals = S.current.approvals.filter((a) => a.gate_key !== key);
    S.current.revisionGate = null; S.current.revisionNote = "";
    force();
    try {
      await decideStackApproval(sessionId, key, decision as any, founderId, note);
    } catch (e) {
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
  const pauseToggle = async () => {
    const next = !S.current.paused;
    try {
      await apiFetch(`${API}/sessions/${sessionId}/${next ? "pause" : "resume"}`, { method: "POST" });
      S.current.paused = next; force();
    } catch {}
  };
  const sel = (dept: string | null, art: string | null) => { S.current.selDept = dept; S.current.selArt = art; S.current.tab = art ? "read" : "updates"; force(); };

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
        const ags = agents.filter((a) => ph.groups.some((g) => a.key === g || a.key.startsWith(g + "_")));
        const present = ags.length > 0;
        return { name: ph.name, present, allDone: present && ags.every((a) => a.status === "done"), anyRunning: ags.some((a) => a.status === "running") };
      });
      // Phase advances ONLY when agents actually start running (triggered by approval).
      // Never speculatively activate a phase — approvals are the gate.
      let activeSeen = false;
      phases = built.map((b) => {
        if (b.allDone) return ["done", b.name];
        if (!activeSeen && b.anyRunning) { activeSeen = true; return ["act", b.name]; }
        return ["", b.name]; // locked
      });
      // Approval pending: insert "⚠ Approval" as active step, keep next phases locked.
      // Do NOT activate next phase via fallback — approval gate controls when agents start.
      if (st.approvals.length) {
        const insertAt = phases.findIndex(([c]) => c === "");
        if (insertAt >= 0) phases.splice(insertAt, 0, ["act", "⚠ Approval"]);
        else phases.push(["act", "⚠ Approval"]);
      } else if (!activeSeen) {
        // Nothing running and no approvals pending: planning stage — make first phase active
        const i = phases.findIndex(([c]) => c !== "done");
        if (i >= 0) phases[i] = ["act", phases[i][1]];
      }
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
  const displayName = st.projectName || st.company || "";
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
        <div className="topbar-title" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{displayName || shortGoal}</div>
        {statusPill(st.status)}
        {(st.status === "running" || st.status === "loading") && <>
          <button className="btn sm" style={{ background: st.paused ? "var(--green)" : "var(--surface)", border: "1px solid var(--bd)", color: st.paused ? "#fff" : "var(--fg)" }} onClick={pauseToggle}>{st.paused ? "▶ Resume" : "⏸ Pause"}</button>
          <button className="btn danger sm" onClick={stop}>Stop</button>
        </>}
      </div>

      {/* urgent banner */}
      {st.approvals.length > 0 && (() => {
        const first = st.approvals[0];
        const isPhaseGate = first.is_phase_gate;
        const bg = isPhaseGate ? "var(--blue)" : "var(--red)";
        const headline = isPhaseGate
          ? `${(first.phase || "Phase").replace(/^\w/, c => c.toUpperCase())} phase complete — review deliverables`
          : "Action Required — Astra is waiting for you";
        const sub = isPhaseGate
          ? `Approve to continue to ${first.next_phase || "next phase"}, or request revisions`
          : (first.title || "An agent needs your approval.");
        return (
          <div style={{ background: bg, flexShrink: 0, animation: "astraSlideDown .25s ease both" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 18px" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#fff" }} className={isPhaseGate ? "" : "blink"} />
              <div>
                <div style={{ fontFamily: "var(--font-chakra)", fontSize: 12, fontWeight: 700, color: "#fff" }}>{headline}</div>
                <div style={{ fontSize: 9.5, color: "rgba(255,255,255,.7)" }}>{sub}</div>
              </div>
            </div>
          </div>
        );
      })()}

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
            {st.selArt
              ? <div className={`dtab${st.tab === "read" ? " on" : ""}`} onClick={() => { st.tab = "read"; force(); }}>Read it</div>
              : st.selDept ? <>
                  <div className={`dtab${st.tab === "updates" ? " on" : ""}`} onClick={() => { st.tab = "updates"; force(); }}>Updates</div>
                  <div className={`dtab${st.tab === "tech" ? " on" : ""}`} onClick={() => { st.tab = "tech"; force(); }}>Technical logs</div>
                  <div className={`dtab${st.tab === "sources" ? " on" : ""}`} onClick={() => { st.tab = "sources"; force(); }}>Sources</div>
                </>
              : <div className="dtab on">Updates</div>}
          </div>
          <div className="dscroll">
            {/* approval cards always first */}
            {st.approvals.map((ap) => ap.is_phase_gate ? (
              /* ── Phase checkpoint card ── */
              <div key={ap.gate_key} style={{ borderRadius: 12, border: "1.5px solid var(--blue)", background: "rgba(59,130,246,.06)", padding: "16px 16px 12px", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 18 }}>✅</span>
                  <div>
                    <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{ap.title}</div>
                    <div style={{ fontSize: 10, color: "var(--blue)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".08em" }}>Phase Checkpoint</div>
                  </div>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--fd)", lineHeight: 1.6, marginBottom: 10 }}>{ap.reason}</div>
                {ap.artifacts && ap.artifacts.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 5 }}>Deliverables to review</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {ap.artifacts.map((art, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 8px", borderRadius: 6, background: "var(--surface)", border: "1px solid var(--bd)", cursor: "pointer" }}
                          onClick={() => sel(null, art.key || null)}>
                          <span style={{ fontSize: 10, color: "var(--green)" }}>✓</span>
                          <span style={{ fontSize: 11, color: "var(--fg)", fontWeight: 500 }}>{art.title || art.key}</span>
                          <span style={{ fontSize: 9, color: "var(--fm)", marginLeft: "auto" }}>{art.agent}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {st.revisionGate === ap.gate_key ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                    <div style={{ fontSize: 10.5, color: "var(--fd)", fontWeight: 500 }}>What needs to be fixed?</div>
                    <textarea
                      value={st.revisionNote}
                      onChange={(e) => { st.revisionNote = e.target.value; force(); }}
                      placeholder={`Tell the ${ap.phase} team what to redo — be specific. E.g. "The ICP analysis missed SMB segment, focus on companies 10-50 employees."`}
                      style={{ width: "100%", minHeight: 72, padding: "8px 10px", borderRadius: 7, border: "1.5px solid var(--blue)", background: "var(--bg)", color: "var(--fg)", fontSize: 11.5, lineHeight: 1.55, resize: "vertical", fontFamily: "inherit", boxSizing: "border-box" }}
                    />
                    <div style={{ display: "flex", gap: 7 }}>
                      <button style={{ flex: 1, padding: "7px 0", borderRadius: 7, border: "1.5px solid var(--red)", background: "rgba(239,68,68,.08)", color: "var(--red)", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}
                        onClick={() => decide(ap.gate_key, "rejected", st.revisionNote)}>
                        Send revision request
                      </button>
                      <button style={{ padding: "7px 12px", borderRadius: 7, border: "1px solid var(--bd)", background: "var(--surface)", color: "var(--fm)", fontSize: 11, cursor: "pointer" }}
                        onClick={() => { st.revisionGate = null; st.revisionNote = ""; force(); }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "none", background: "var(--blue)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer" }}
                      onClick={() => decide(ap.gate_key, "approved")}>
                      Approve → Continue to {ap.next_phase || "next phase"}
                    </button>
                    <button style={{ padding: "9px 14px", borderRadius: 8, border: "1.5px solid var(--red)", background: "rgba(239,68,68,.07)", color: "var(--red)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                      onClick={() => { st.revisionGate = ap.gate_key; st.revisionNote = ""; force(); }}>
                      Request revisions
                    </button>
                  </div>
                )}
              </div>
            ) : (
              /* ── Action gate card (mid-phase SafeRun) ── */
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
              // Extract full content from the owning agent's result (backend only stores 360-char preview on the artifact itself)
              let fullContent: string | null = null;
              const ownerResult = art.owner_agent ? (st.agents[art.owner_agent]?.result as Record<string, unknown> | null) : null;
              if (ownerResult && typeof ownerResult === "object") {
                const r = ownerResult as Record<string, unknown>;
                const candidates = [art.key ? r[art.key] : null, r.summary, r.output_summary, r.formatted_text, r.report, r.text, r.url, r.html];
                for (const c of candidates) {
                  if (c && typeof c === "string" && c.length > 0) { fullContent = c; break; }
                }
                if (!fullContent) fullContent = JSON.stringify(ownerResult, null, 2);
              }
              const displayContent = fullContent || art.content || art.preview || art.description || null;
              return <>
                <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{art.title || art.key}</div>
                <div style={{ fontSize: 9, color: art.status === "ready" ? "var(--green)" : "var(--amber)", marginBottom: 10 }}>{art.status === "ready" ? "✓ ready" : "⋯ being written"}</div>
                {displayContent
                  ? <pre className="art-pre" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "none" }}>{displayContent}</pre>
                  : <div style={{ color: "var(--fm)", fontSize: 10.5, fontStyle: "italic" }}>Agent hasn't produced output yet — check back when it completes.</div>}
              </>;
            })()}

            {/* selected dept — updates / tech logs / sources */}
            {st.selDept && !st.selArt && (() => {
              const d = st.selDept === "__other" ? { ags: otherAgs } : DEPTS[st.selDept] || { ags: [] };
              const ags = (d.ags || []).filter((a) => st.agents[a]);
              const all: (LogEntry & { agent: string })[] = [];
              for (const k of ags) for (const e of st.agents[k].log) all.push({ ...e, agent: k });
              all.sort((a, b) => a.ts - b.ts);

              if (st.tab === "sources") {
                const urls: string[] = [];
                for (const k of ags) for (const u of st.agents[k].visitedUrls) if (!urls.includes(u)) urls.push(u);
                if (!urls.length) return <div style={{ color: "var(--fm)", fontSize: 10 }}>No sources logged yet.</div>;
                return <><div style={{ fontFamily: "var(--font-chakra)", fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".14em" }}>{urls.length} source{urls.length !== 1 ? "s" : ""} visited</div>
                  <div className="url-list" style={{ display: "flex", flexDirection: "column", gap: 3 }}>{urls.map((u) => { let dm = u; try { dm = new URL(u).hostname.replace(/^www\./, ""); } catch {} return <a key={u} className="url-item" href={u} target="_blank" rel="noreferrer">{dm} ↗</a>; })}</div></>;
              }

              if (st.tab === "tech") {
                if (!all.length) return <div style={{ color: "var(--fd)", fontSize: 10 }}>No activity yet.</div>;
                return <>
                  <div style={{ fontFamily: "var(--font-chakra)", fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".14em", marginBottom: 6 }}>Technical log · {all.length} entries</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    {all.map((l, i) => (
                      <div key={i} style={{ display: "flex", gap: 7, padding: "3px 0", borderBottom: "1px solid rgba(0,0,0,.04)", alignItems: "flex-start" }}>
                        <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 8.5, color: "var(--fm)", flexShrink: 0, marginTop: 1, minWidth: 42, textTransform: "uppercase", letterSpacing: ".06em" }}>{l.type}</span>
                        {ags.length > 1 && <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 8.5, color: "var(--blue)", flexShrink: 0, marginTop: 1 }}>{l.agent}</span>}
                        <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 9, color: "var(--fg)", lineHeight: 1.5, wordBreak: "break-all" }}>{l.text}</span>
                      </div>
                    ))}
                  </div>
                </>;
              }

              // "updates" tab — agent-level completions only (done / error), never raw tool results
              const updates = all.filter((l) => l.type === "done" || l.type === "error");
              if (!updates.length) {
                const isRunning = ags.some((a) => st.agents[a].status === "running");
                return <div style={{ color: "var(--fd)", fontSize: 10.5, lineHeight: 1.6 }}>{isRunning ? "Agents are working — summaries appear here when each one finishes." : "Waiting to start."}</div>;
              }
              return <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {updates.map((l, i) => {
                  if (l.type === "error") return (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "10px 12px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)" }}>
                      <span style={{ fontSize: 13, flexShrink: 0, marginTop: 2 }}>✗</span>
                      <div>
                        {ags.length > 1 && <div style={{ fontSize: 9, fontWeight: 700, color: "var(--red)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 3 }}>{l.agent}</div>}
                        <span style={{ fontSize: 11.5, color: "var(--red)", lineHeight: 1.5 }}>{l.text}</span>
                      </div>
                    </div>
                  );
                  // done — agent completed, show its summary
                  const summary = l.text && l.text !== "Agent finished" ? l.text : null;
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "12px 13px", borderRadius: 8, background: "rgba(52,211,153,.05)", border: "1px solid rgba(52,211,153,.2)" }}>
                      <span style={{ fontSize: 15, flexShrink: 0, marginTop: 1 }}>✓</span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--green)", marginBottom: summary ? 5 : 0 }}>
                          {l.agent.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())} finished
                        </div>
                        {summary && <div style={{ fontSize: 12, color: "var(--fg)", lineHeight: 1.65, wordBreak: "break-word" }}>{summary}</div>}
                      </div>
                    </div>
                  );
                })}
              </div>;
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
