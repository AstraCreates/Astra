"use client";

/* Redesigned session monitor — ported from mockup/app/index.html (#v-sess).
   Self-contained: own SSE + state, wired to the real backend via apiFetch.
   Layout: phase bar → status bar → dept cards → vault | detail → steer bar. */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, killSession, decideStackApproval, deleteSessionRemote, submitGoal, getSessionImages, getSessionMeta, AGENT_LABELS, sortAgentNamesByOrder, type SessionImages } from "@/lib/api";
import AgentSwarm, { placeAgents, VB_W, VB_H, type SwarmAgent } from "@/components/AgentSwarm";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import { signIn } from "next-auth/react";
import dynamic from "next/dynamic";
import SessionTour from "@/components/SessionTour";

// xterm touches `window`; load the takeover terminal client-only.
const TerminalPane = dynamic(() => import("@/components/TerminalPane"), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type LogEntry = { ts: number; type: string; text: string };
// Raw openclaude (claude-code CLI) stream lines for the technical/web terminal.
// kind: command | output | error | file | log | plan | tool | phase | deploy
type TermEntry = { ts: number; kind: string; text: string; agent: string };
type Agent = { key: string; status: string; log: LogEntry[]; term: TermEntry[]; visitedUrls: string[]; currentTool: string | null; result: unknown; instruction: string };
type Artifact = { key?: string; title?: string; status?: string; preview?: string; content?: string; description?: string; owner_agent?: string };
type Approval = { gate_key: string; title?: string; reason?: string; description?: string; triggered_by?: string; agent?: string; ts: number; is_phase_gate?: boolean; phase?: string; next_phase?: string; artifacts?: { key: string; title: string; agent: string; preview?: string }[] };

type SState = {
  status: string; goal: string; company: string; projectName: string; stackId: string;
  agents: Record<string, Agent>;
  artifacts: Artifact[]; approvals: Approval[]; decidedKeys: Set<string>;
  selDept: string | null; selArt: string | null; tab: string; paused: boolean;
  revisionGate: string | null; revisionNote: string;
  liveUrl: string;
  operating: { count: number; summary: string } | null;
  parentId: string;
  startedAt: number;
  credits: number;
};

function fmtElapsed(ms: number): string {
  if (ms <= 0) return "0:00";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

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
  research:  { n: "Research",  ic: "◉", ags: ["research", "research_competitors", "research_market", "research_execution", "research_financial", "research_regulatory"] },
  design:    { n: "Design",    ic: "◈", ags: ["design"] },
  technical: { n: "Technical", ic: "⊞", ags: ["technical", "technical_scaffold", "technical_infra", "technical_data", "web", "web_navigator"] },
  marketing: { n: "Marketing", ic: "◎", ags: ["marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid"] },
  legal:     { n: "Legal",     ic: "⊡", ags: ["legal", "legal_docs", "legal_entity", "legal_ip"] },
  sales:     { n: "Sales",     ic: "◇", ags: ["sales", "sales_pipeline", "sales_enablement", "ops"] },
  finance:   { n: "Finance",   ic: "◆", ags: ["finance_model", "finance_fundraise"] },
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

// ── Lightweight inline markdown renderer for deliverable previews ──────────────
// Parses **bold**, `code`, and [text](url) inside a line into styled spans.
function inlineFmt(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(<strong key={`${keyBase}-b${i}`} style={{ fontWeight: 700, color: "var(--fg)" }}>{m[1]}</strong>);
    else if (m[2]) out.push(<code key={`${keyBase}-c${i}`} style={{ fontFamily: "var(--font-code)", fontSize: "0.92em", background: "var(--s2)", padding: "1px 4px" }}>{m[2]}</code>);
    else if (m[3]) out.push(<a key={`${keyBase}-l${i}`} href={m[4]} target="_blank" rel="noreferrer" style={{ color: "var(--blue)" }}>{m[3]}</a>);
    last = re.lastIndex; i++;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Render markdown-ish deliverable content as clean, styled blocks (no <pre> dump).
function RichText({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: React.ReactNode[] = [];
  let list: { items: string[]; ordered: boolean } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    const cur = list;
    blocks.push(
      <Tag key={`l${blocks.length}`} style={{ margin: "4px 0 8px", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 3 }}>
        {cur.items.map((it, i) => <li key={i} style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--fd)" }}>{inlineFmt(it, `li${blocks.length}-${i}`)}</li>)}
      </Tag>
    );
    list = null;
  };
  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    const t = line.trim();
    if (!t) { flush(); return; }
    let m: RegExpMatchArray | null;
    if (/^(={3,}|-{3,}|─{3,}|—{3,})$/.test(t)) { flush(); blocks.push(<div key={`hr${idx}`} style={{ height: 1, background: "var(--bd)", margin: "8px 0" }} />); return; }
    if ((m = t.match(/^(#{1,6})\s+(.*)$/))) {
      flush();
      const lvl = m[1].length;
      const size = lvl <= 1 ? 16 : lvl === 2 ? 13.5 : 12;
      blocks.push(<div key={`h${idx}`} style={{ fontFamily: "var(--font-chakra),sans-serif", fontWeight: 700, fontSize: size, color: "var(--fg)", margin: blocks.length ? "12px 0 5px" : "0 0 5px", letterSpacing: ".01em" }}>{inlineFmt(m[2], `h${idx}`)}</div>);
      return;
    }
    if ((m = t.match(/^\d+[.)]\s+(.*)$/))) { if (!list || !list.ordered) { flush(); list = { items: [], ordered: true }; } list.items.push(m[1]); return; }
    if ((m = t.match(/^[-*•]\s+(.*)$/))) { if (!list || list.ordered) { flush(); list = { items: [], ordered: false }; } list.items.push(m[1]); return; }
    flush();
    blocks.push(<p key={`p${idx}`} style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--fd)", margin: "0 0 7px" }}>{inlineFmt(t, `p${idx}`)}</p>);
  });
  flush();
  return <div style={{ background: "var(--surface)", border: "1px solid var(--bd)", padding: "14px 16px", maxHeight: 460, overflowY: "auto" }}>{blocks}</div>;
}

// Per-session client cache so the updates panel (agent logs, selected tab,
// artifacts) survives navigating between sidebar pages / agent tabs WITHOUT
// re-streaming from the server. The cached object is the same reference held by
// S.current, so in-place updates from the live SSE stream are reflected
// automatically. Capped to a few sessions to bound memory.
const SV_CACHE = new Map<string, SState>();
const SV_CACHE_MAX = 8;
function cacheSession(id: string, state: SState) {
  SV_CACHE.set(id, state);
  while (SV_CACHE.size > SV_CACHE_MAX) {
    const oldest = SV_CACHE.keys().next().value;
    if (oldest === undefined) break;
    SV_CACHE.delete(oldest);
  }
}

export default function SessionView({ sessionId }: { sessionId: string }) {
  const { userId, isSignedIn, isLoading: authLoading } = useDevUser();
  const founderId = userId;
  // Founder resolved from the session's own meta (so a /s/<id> link works without
  // login / without the founder in the URL). Falls back to the logged-in user.
  const sessFounder = useRef<string>("");
  const router = useRouter();
  const S = useRef<SState>({
    status: "loading", goal: "", company: "", projectName: "", stackId: "", agents: {}, artifacts: [], approvals: [],
    decidedKeys: new Set(), selDept: null, selArt: null, tab: "updates", paused: false,
    revisionGate: null, revisionNote: "", liveUrl: "", operating: null, parentId: "", startedAt: 0, credits: 0,
  });
  const [, force] = useReducer((x: number) => x + 1, 0);
  const sseRef = useRef<EventSource | null>(null);
  const steerRef = useRef<HTMLInputElement>(null);
  const [copilot, setCopilot] = useState<{ role: string; content: string; actions?: string[] }[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const copilotLoaded = useRef(false);
  useEffect(() => {
    if (!copilotOpen || copilotLoaded.current || !sessionId) return;
    copilotLoaded.current = true;
    (async () => {
      try {
        const r = await apiFetch(`${API}/copilot/${sessionId}`);
        const d = await r.json();
        if (Array.isArray(d.history)) setCopilot(d.history.map((h: any) => ({ role: h.role, content: h.content, actions: h.actions })));
      } catch {}
    })();
  }, [copilotOpen, sessionId]);
  const [showSessionTour, setShowSessionTour] = useState(false);
  const [designImages, setDesignImages] = useState<SessionImages>({ logos: {}, brand_images: [] });
  const [accessDenied, setAccessDenied] = useState(false);
  const [toastErr, setToastErr] = useState("");
  const [restartConfirm, setRestartConfirm] = useState(false);
  const [takeover, setTakeover] = useState(false);
  const [showSwarm, setShowSwarm] = useState(true);
  const swarmContainerRef = useRef<HTMLDivElement | null>(null);
  const deptRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  type Beam = { key: string; x1: number; y1: number; x2: number; y2: number };
  const [beams, setBeams] = useState<Beam[]>([]);
  const showErr = (msg: string) => { setToastErr(msg); setTimeout(() => setToastErr(""), 6000); };
  const imgsFetched = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const isMobile = window.matchMedia("(max-width: 768px)").matches;
    if (isMobile) { try { localStorage.setItem("astra_session_tour_done", "1"); } catch {} return; }
    if (localStorage.getItem("astra_onboarding_done") !== "1") return;
    if (localStorage.getItem("astra_session_tour_done")) return;

    let t: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => { t = setTimeout(() => setShowSessionTour(true), 1200); };

    if (localStorage.getItem("astra_tour_done")) {
      // Workspace tour already finished — start session tour normally
      schedule();
      return () => { if (t) clearTimeout(t); };
    }

    // Workspace tour still in progress — wait for it to finish first
    const onWorkspaceDone = () => schedule();
    window.addEventListener("astra:workspace-tour-done", onWorkspaceDone);
    return () => {
      window.removeEventListener("astra:workspace-tour-done", onWorkspaceDone);
      if (t) clearTimeout(t);
    };
  }, []);

  const ensureAg = (key: string) => {
    if (!S.current.agents[key]) S.current.agents[key] = { key, status: "waiting", log: [], term: [], visitedUrls: [], currentTool: null, result: null, instruction: "" };
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
  // Raw terminal buffer for the technical/web openclaude stream. Keeps fuller
  // text than addLog (4k vs 500) so the terminal view shows real command output.
  const pushTerm = (agentKey: string, kind: string, text: unknown) => {
    ensureAg(agentKey);
    const ag = S.current.agents[agentKey];
    if (!ag.term) ag.term = [];
    ag.term.push({ ts: Date.now(), kind, text: safeText(text).slice(0, 4000), agent: agentKey });
    if (ag.term.length > 400) ag.term.shift();
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
        // Technical build stream — fold into the agent log (Updates) AND keep the
        // raw lines in the terminal buffer (full text) for the technical terminal.
        const a = ev.agent || "technical"; ensureAg(a);
        const k = ev.kind;
        if (k === "deploy" && ev.url) { st.liveUrl = String(ev.url); addLog(a, "result", `Deployed → ${ev.url}`); pushTerm(a, "deploy", `Deployed → ${ev.url}`); }
        else if (k === "file") { addLog(a, "tool", `${ev.verb || "wrote"} ${ev.path} (${ev.size ?? 0}b)`); pushTerm(a, "file", `${ev.verb || "wrote"} ${ev.path} (${ev.size ?? 0}b)`); }
        else if (k === "command") { addLog(a, "tool", `$ ${ev.command || ""}`); pushTerm(a, "command", `${ev.command || ""}${ev.desc ? `  # ${ev.desc}` : ""}`); }
        else if (k === "output") { addLog(a, "result", safeText(ev.text || "").slice(0, 300)); pushTerm(a, "output", ev.text || ""); }
        else if (k === "error") { addLog(a, "error", safeText(ev.text || "").slice(0, 300)); pushTerm(a, "error", ev.text || ""); }
        else if (k === "log") pushTerm(a, "log", ev.text || "");
        else if (k === "tool") pushTerm(a, "tool", `${ev.tool || ""}${ev.target ? ` ${ev.target}` : ""}`);
        else if (k === "phase" || k === "plan" || k === "build_start") { addLog(a, "think", ev.text || ev.goal || ""); pushTerm(a, "phase", ev.text || ev.goal || ""); }
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
        st.status = "done";
        st.operating = { count: Number(ev.mission_count || (ev.missions?.length ?? 0)), summary: String(ev.summary || "") };
        break;
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
    if (!sessionId || !isSignedIn) return;
    let alive = true;
    setAccessDenied(false);
    // Restore from cache (keeps logs + selected agent across nav) — else start fresh.
    const cached = SV_CACHE.get(sessionId);
    const fromCache = !!cached;
    if (cached) {
      S.current = cached;
    } else {
      S.current = { status: "loading", goal: "", company: "", projectName: "", stackId: "", agents: {}, artifacts: [], approvals: [], decidedKeys: new Set(), selDept: null, selArt: null, tab: "updates", paused: false, revisionGate: null, revisionNote: "", liveUrl: "", operating: null, parentId: "", startedAt: 0, credits: 0 };
      cacheSession(sessionId, S.current);
    }
    force();

    (async () => {
      // Session header by id (auth-gated). meta is null when the server denies access
      // (not your session) or it doesn't exist → block and don't open the stream, so
      // you can only ever view your OWN sessions.
      let meta = null;
      try { meta = await getSessionMeta(sessionId); } catch {}
      if (!alive) return;
      const myFounder = (sessFounder.current || founderId || "").toString();
      if (!meta || (meta.founder_id && myFounder && meta.founder_id !== myFounder)) {
        setAccessDenied(true);
        return;
      }
      if (meta.founder_id) sessFounder.current = meta.founder_id;
      {
        const rawGoal = meta.goal || "";
        const { projectName, cleanGoal } = extractProjectName(rawGoal);
        S.current.goal = cleanGoal;
        S.current.projectName = projectName;
        S.current.status = meta.status || "running";
        S.current.company = meta.company_name || "";
        S.current.credits = Number(meta.credits_used || 0);
        S.current.stackId = meta.stack_id || "";
        S.current.parentId = meta.parent_session_id || "";
        if (meta.created_at) { const t = Date.parse(meta.created_at); if (!Number.isNaN(t)) S.current.startedAt = t; }
      }
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
          if (d.previewUrl) S.current.liveUrl = d.previewUrl;
          S.current.status = d.status || S.current.status;
          if (Array.isArray(d.artifacts) && d.artifacts.length) S.current.artifacts = d.artifacts;
          else if (!fromCache) S.current.artifacts = [];
          if (Array.isArray(d.approvals)) {
            S.current.approvals = d.approvals
              .filter((a: any) => PENDING.has(a.status) && (a.gate_key || a.key))
              .map((a: any) => ({ ...a, gate_key: a.gate_key || a.key }));
          }
          if (d.agents && typeof d.agents === "object") {
            for (const [k, ag] of Object.entries<any>(d.agents)) {
              const rawLog: any[] = ag.log || [];
              const mapped = rawLog.map((e) => ({ ts: e.ts ?? Date.now(), type: String(e.type || ""), text: safeText(e.text) }));
              const existing = S.current.agents[k];
              // When restoring from cache, the cached log may already hold live
              // updates newer than the snapshot — keep whichever is longer so we
              // never drop streamed lines on remount.
              const log = (fromCache && existing && existing.log.length >= mapped.length) ? existing.log : mapped;
              S.current.agents[k] = {
                key: k, status: ag.status || existing?.status || "waiting",
                log,
                term: existing?.term || [],
                visitedUrls: ag.visitedUrls || ag.visited_urls || existing?.visitedUrls || [],
                currentTool: existing?.currentTool ?? null, result: ag.result || existing?.result || null,
                instruction: ag.instruction || existing?.instruction || "",
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
  }, [sessionId, founderId, handleEvent, isSignedIn]);

  // Run timer — tick every second while running so the elapsed clock counts up.
  useEffect(() => {
    const id = setInterval(() => {
      const cur = S.current;
      if ((cur.status === "running" || cur.status === "loading") && cur.startedAt > 0) force();
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const decide = async (key: string, decision: "approved" | "skipped" | "rejected", note?: string) => {
    if (!key) { showErr("Approval missing gate key — refresh the page and try again."); return; }
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
      showErr(`Approval failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const sendCopilot = async () => {
    const msg = steerRef.current?.value.trim(); if (!msg || copilotBusy) return;
    if (steerRef.current) steerRef.current.value = "";
    setCopilot((c) => [...c, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const r = await apiFetch(`${API}/copilot/${sessionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg }) });
      const d = await r.json();
      setCopilot((c) => [...c, { role: "copilot", content: d.reply || "(no reply)", actions: (d.actions || []).map((a: any) => a.tool) }]);
    } catch (e) {
      setCopilot((c) => [...c, { role: "copilot", content: "Copilot error — try again." }]);
    } finally { setCopilotBusy(false); }
  };
  const sendSteer = async () => {
    const msg = steerRef.current?.value.trim(); if (!msg) return;
    if (steerRef.current) steerRef.current.value = "";
    try { await apiFetch(`${API}/steer/${sessionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg }) }); } catch {}
  };
  // No window.confirm — mobile in-app webviews suppress it (returns false), which
  // made Stop/Restart silently no-op. Optimistic UI + fire the request.
  const stop = async () => { S.current.status = "killed"; sseRef.current?.close(); force(); await killSession(sessionId).catch(() => {}); };
  // TEMP: kill this run, delete it server+local, resubmit the same goal as a fresh run.
  const killClearRestart = async () => {
    const goal = S.current.goal;
    const company = S.current.company || S.current.projectName;
    const stack = S.current.stackId || "idea_to_revenue";
    if (!goal) { showErr("Original goal hasn't loaded yet — try again in a moment."); return; }
    // No window.confirm — suppressed in mobile webviews.
    S.current.status = "killed"; force();
    try {
      sseRef.current?.close();
      await killSession(sessionId).catch(() => {});
      await deleteSessionRemote(sessionId).catch(() => {});
      deleteLocalSession(sessionId);
      const instruction = company ? `Company/project name: ${company}\n\n${goal}` : goal;
      const data = await submitGoal(founderId, instruction, {}, stack);
      if (!data.session_id) throw new Error("No session_id returned");
      window.location.assign(`/s/${data.session_id}`);
    } catch (e) {
      showErr(`Restart failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const pauseToggle = async () => {
    const next = !S.current.paused;
    try {
      await apiFetch(`${API}/sessions/${sessionId}/${next ? "pause" : "resume"}`, { method: "POST" });
      S.current.paused = next; force();
    } catch {}
  };
  const sel = (dept: string | null, art: string | null) => { S.current.selDept = dept; S.current.selArt = art; S.current.tab = art ? "read" : (dept === "technical" ? "terminal" : "updates"); force(); };

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

  // Live founding-team constellation feed — sorted by canonical agent order.
  const swarmAgents: SwarmAgent[] = sortAgentNamesByOrder(Object.keys(st.agents)).map((k) => ({
    key: k,
    label: AGENT_LABELS[k as keyof typeof AGENT_LABELS] ?? k,
    status: st.agents[k].status,
    currentTool: st.agents[k].currentTool,
  }));

  // Beam computation: running agent node → its dept card. Re-runs when running
  // agent set changes (keyed by stable string so effect doesn't fire every render).
  const _runningKeys = swarmAgents.filter(a => a.status === "running").map(a => a.key).sort().join(",");
  useEffect(() => {
    if (!showSwarm || !swarmContainerRef.current) { setBeams([]); return; }
    const cr = swarmContainerRef.current.getBoundingClientRect();
    if (!cr.width || !cr.height) return;
    const placedAll = placeAgents(swarmAgents);
    const next: { key: string; x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const ag of swarmAgents) {
      if (ag.status !== "running") continue;
      const deptKey = agToDept(ag.key);
      if (!deptKey) continue;
      const deptEl = deptRefsMap.current.get(deptKey);
      if (!deptEl) continue;
      const p = placedAll.find(pl => pl.key === ag.key);
      if (!p) continue;
      const dr = deptEl.getBoundingClientRect();
      next.push({
        key: ag.key,
        x1: cr.left + (p.x / VB_W) * cr.width,
        y1: cr.top + (p.y / VB_H) * cr.height,
        x2: dr.left + dr.width / 2,
        y2: dr.top + dr.height / 2,
      });
    }
    setBeams(next);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [_runningKeys, showSwarm]);

  const displayName = st.projectName || st.company || "";
  const shortGoal = st.goal ? st.goal.slice(0, 70) + (st.goal.length > 70 ? "…" : "") : `Session ${sessionId.slice(0, 8)}`;
  const ICONS: Record<string, string> = { think: "◈", tool: "◎", result: "→", done: "✓", error: "✗", start: "↳" };
  const LABELS: Record<string, string> = { think: "Thinking", tool: "Searching", result: "Found", done: "Done", error: "Error", start: "Started" };

  const statusPill = (s: string) => {
    const map: Record<string, [string, string]> = { running: ["blue", "● Running"], done: ["green", "✓ Done"], error: ["red", "✗ Error"], killed: ["red", "■ Stopped"], loading: ["blue", "● Running"] };
    const [cls, txt] = map[s] || ["", s];
    return <span className={`pill ${cls}`}>{txt}</span>;
  };

  // Sessions require login — no anonymous access by URL.
  if (!authLoading && !isSignedIn) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 16, background: "var(--bg)", padding: 24, textAlign: "center" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)" }}>Sign in to view this session</div>
        <div style={{ fontSize: 13, color: "var(--fd)", maxWidth: 360 }}>Sessions are private to your account. Sign in to continue.</div>
        <button className="btn" onClick={() => signIn("google", { callbackUrl: typeof window !== "undefined" ? window.location.href : "/" })}
          style={{ padding: "10px 20px" }}>Sign in with Google</button>
      </div>
    );
  }

  // You can only view your own sessions.
  if (accessDenied) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 14, background: "var(--bg)", padding: 24, textAlign: "center" }}>
        <div style={{ fontSize: 30 }}>🔒</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)" }}>You don&apos;t have access to this session</div>
        <div style={{ fontSize: 13, color: "var(--fd)", maxWidth: 360 }}>It belongs to another account, or it doesn&apos;t exist.</div>
        <a href="/" className="btn" style={{ padding: "10px 20px", textDecoration: "none" }}>← Back to dashboard</a>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "var(--bg)" }}>
      {/* topbar */}
      <div style={{ height: 44, display: "flex", alignItems: "center", gap: 7, padding: "0 14px 0 18px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0 }}>
        <div className="topbar-title" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{displayName || shortGoal}</div>
        {st.parentId && (
          <a href={`/s/${st.parentId}`} className="btn sm" title="View parent session"
             style={{ flexShrink: 0, textDecoration: "none" }}>
            ↩ Parent
          </a>
        )}
        {st.liveUrl && (
          <a href={st.liveUrl} target="_blank" rel="noopener noreferrer" className="btn sm"
             title={st.liveUrl}
             style={{ flexShrink: 0, textDecoration: "none", background: "var(--green)", border: "1px solid var(--green)", color: "#fff", display: "inline-flex", alignItems: "center", gap: 4 }}>
            ↗ Live
          </a>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0 }}>
          {st.credits > 0 && (
            <span title="Credits used by this session" style={{ fontFamily: "var(--font-code)", fontSize: 10, color: "var(--fm)", fontVariantNumeric: "tabular-nums" }}>
              ◈ {st.credits.toLocaleString()}
            </span>
          )}
          {(st.status === "running" || st.status === "loading") && st.startedAt > 0 && (
            <span style={{ fontFamily: "var(--font-code)", fontSize: 10, color: "var(--fm)", fontVariantNumeric: "tabular-nums" }}>
              {fmtElapsed(Date.now() - st.startedAt)}
            </span>
          )}
          {statusPill(st.status)}
        </div>
        {(st.status === "running" || st.status === "loading") && (
          <div style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0, borderLeft: "1px solid var(--bd)", paddingLeft: 7 }}>
            <button className="btn sm" aria-label={st.paused ? "Resume run" : "Pause run"}
              style={{ touchAction: "manipulation", background: st.paused ? "var(--green)" : "var(--surface)", border: "1px solid var(--bd)", color: st.paused ? "#fff" : "var(--fg)", padding: "4px 8px" }}
              onClick={pauseToggle}>{st.paused ? "▶" : "⏸"}</button>
            <button className="btn danger sm" aria-label="Stop run"
              style={{ touchAction: "manipulation" }} onClick={stop}>Stop</button>
          </div>
        )}
        {restartConfirm ? (
          <>
            <button className="btn sm danger" aria-label="Confirm restart run"
              style={{ flexShrink: 0, touchAction: "manipulation" }}
              onClick={() => { setRestartConfirm(false); killClearRestart(); }}>Confirm restart</button>
            <button className="btn sm" aria-label="Cancel restart"
              style={{ flexShrink: 0, touchAction: "manipulation" }}
              onClick={() => setRestartConfirm(false)}>✕</button>
          </>
        ) : (
          <button className="btn sm" title="Restart this run" aria-label="Restart run"
            style={{ flexShrink: 0, touchAction: "manipulation" }}
            onClick={() => { setRestartConfirm(true); setTimeout(() => setRestartConfirm(false), 5000); }}>↻ Restart</button>
        )}
      </div>

      {/* inline error toast — replaces all alert() calls */}
      {toastErr && (
        <div style={{ background: "var(--rdim)", borderBottom: "1px solid var(--rb)", padding: "7px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "var(--red)", fontFamily: "var(--font-code)", flexShrink: 0, animation: "astraSlideDown 0.22s var(--ease-out-quint, cubic-bezier(0.22,1,0.36,1)) both" }}>
          <span>✗</span>
          <span style={{ flex: 1 }}>{toastErr}</span>
          <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1 }}>✕</button>
        </div>
      )}

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

      {/* done / operating banner */}
      {st.status === "done" && (
        st.operating ? (
          <div className="done-bar" style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div className="done-title">◎ Now operating — {st.operating.count} mission{st.operating.count !== 1 ? "s" : ""} running</div>
              <div className="done-sub">{st.operating.summary || "Departments keep working the next milestone toward your north star. Approve milestones to mark them complete."}</div>
            </div>
            <a href="/goals" className="btn sm" style={{ flexShrink: 0, textDecoration: "none", background: "var(--blue)", border: "1px solid var(--blue)", color: "#fff" }}>View missions →</a>
          </div>
        ) : (
          <div className="done-bar"><div><div className="done-title">✓ Run complete</div><div className="done-sub">All agents finished. Deliverables are in the vault.</div></div></div>
        )
      )}

      {/* phase bar */}
      <div data-tour="session-phasebar" className="phasebar">
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

      {/* live founding-team constellation */}
      {swarmAgents.length > 0 && (
        <div style={{ flexShrink: 0, padding: "8px 14px 0" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: showSwarm ? 6 : 0 }}>
            <button
              onClick={() => setShowSwarm((v) => !v)}
              style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", padding: 0, color: "var(--fm)" }}
              aria-label={showSwarm ? "Hide founding team" : "Show founding team"}
            >
              <span style={{ fontSize: 9, transform: showSwarm ? "rotate(90deg)" : "rotate(0deg)", display: "inline-block", transition: "transform .2s" }}>▶</span>
              <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", fontFamily: "var(--font-code)" }}>Founding team</span>
            </button>
          </div>
          {showSwarm && (
            <div style={{ maxWidth: 500 }}>
              <AgentSwarm
                agents={swarmAgents}
                coreLabel={displayName || "Astra"}
                coreSub={st.status === "done" ? "operating" : st.approvals.length ? "awaiting you" : run > 0 ? "building" : "planning"}
                containerRef={swarmContainerRef}
              />
            </div>
          )}
        </div>
      )}

      {/* dept cards */}
      <div data-tour="session-depts" className="depts">
        {activeDepts.length === 0 ? <div style={{ padding: 6, fontSize: 9.5, color: "var(--fm)" }}>Waiting for agents…</div>
        : activeDepts.map(([dk, d]) => {
          const s = deptSt(d.inS);
          const prog = d.inS.length ? Math.round(d.inS.filter((a) => st.agents[a].status === "done").length / d.inS.length * 100) : 0;
          const bc = s === "done" ? "var(--green)" : s === "run" ? "var(--blue)" : s === "err" ? "var(--red)" : "var(--fm)";
          const badge = s === "run" ? "Working" : s === "done" ? "Done" : s === "err" ? "Error" : "Queued";
          return (
            <div key={dk}
              ref={el => { if (el) deptRefsMap.current.set(dk, el); else deptRefsMap.current.delete(dk); }}
              className={`dc ${s}${st.selDept === dk ? " sel" : ""}`} title={d.n} aria-label={`${d.n} department — ${badge}`} onClick={() => sel(dk, null)}>
              <div className="dc-top"><div className="dc-ico">{d.ic}</div><div className="dc-name">{d.n}</div><div className={`dc-badge ${s}`}>{badge}</div></div>
              <div className="dc-what">{deptWhat(d.inS)}</div>
              <div className="dc-prog"><div className="dc-bar" style={{ transform: `scaleX(${prog / 100})`, background: bc }} /></div>
            </div>
          );
        })}
      </div>

      {/* workspace: vault | detail */}
      <div className="sess-ws">
        {/* vault */}
        <div data-tour="session-vault" className="vault">
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
        <div data-tour="session-detail" className="detail">
          <div className="dtabs">
            {st.selArt
              ? <div className={`dtab${st.tab === "read" ? " on" : ""}`} onClick={() => { st.tab = "read"; force(); }}>Read it</div>
              : st.selDept ? <>
                  {st.selDept === "technical"
                    ? <div className={`dtab${st.tab === "terminal" ? " on" : ""}`} onClick={() => { st.tab = "terminal"; force(); }}>Terminal</div>
                    : <div className={`dtab${st.tab === "updates" ? " on" : ""}`} onClick={() => { st.tab = "updates"; force(); }}>Updates</div>}
                  <div className={`dtab${st.tab === "tech" ? " on" : ""}`} onClick={() => { st.tab = "tech"; force(); }}>Technical logs</div>
                  <div className={`dtab${st.tab === "sources" ? " on" : ""}`} onClick={() => { st.tab = "sources"; force(); }}>Sources</div>
                </>
              : <div className="dtab on">Updates</div>}
          </div>
          <div className="dscroll">
            {/* approval cards always first */}
            {st.approvals.map((ap) => ap.is_phase_gate ? (
              /* ── Phase checkpoint card ── */
              <div key={ap.gate_key} style={{ border: "1.5px solid var(--blue)", background: "rgba(59,130,246,.06)", padding: "16px 16px 12px", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 18 }}>✓</span>
                  <div>
                    <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{ap.title}</div>
                    <div style={{ fontSize: 10, color: "var(--blue)", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".08em" }}>Phase Checkpoint</div>
                  </div>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--fd)", lineHeight: 1.6, marginBottom: 10 }}>{ap.reason}</div>
                {ap.artifacts && ap.artifacts.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 5 }}>Deliverables to review</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {ap.artifacts.map((art, i) => (
                        <div key={i} style={{ background: "var(--surface)", border: "1px solid var(--bd)", overflow: "hidden" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 8px", cursor: "pointer" }}
                            onClick={() => sel(null, art.key || null)}>
                            <span style={{ fontSize: 10, color: "var(--green)" }}>✓</span>
                            <span style={{ fontSize: 11, color: "var(--fg)", fontWeight: 600 }}>{art.title || art.key}</span>
                            <span style={{ fontSize: 9, color: "var(--blue)", marginLeft: "auto" }}>View full ↗</span>
                          </div>
                          {art.preview && (
                            <div style={{ padding: "0 8px 8px", borderTop: "1px solid var(--bd)", paddingTop: 6 }}>
                              <RichText text={art.preview} />
                            </div>
                          )}
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
                      style={{ width: "100%", minHeight: 72, padding: "8px 10px", border: "1.5px solid var(--blue)", background: "var(--bg)", color: "var(--fg)", fontSize: 11.5, lineHeight: 1.55, resize: "vertical", fontFamily: "inherit", boxSizing: "border-box" }}
                    />
                    <div style={{ display: "flex", gap: 7 }}>
                      <button style={{ flex: 1, padding: "7px 0", border: "1.5px solid var(--red)", background: "rgba(239,68,68,.08)", color: "var(--red)", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}
                        onClick={() => decide(ap.gate_key, "rejected", st.revisionNote)}>
                        Send revision request
                      </button>
                      <button style={{ padding: "7px 12px", border: "1px solid var(--bd)", background: "var(--surface)", color: "var(--fm)", fontSize: 11, cursor: "pointer" }}
                        onClick={() => { st.revisionGate = null; st.revisionNote = ""; force(); }}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button style={{ flex: 1, padding: "9px 0", border: "none", background: "var(--blue)", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer" }}
                      onClick={() => decide(ap.gate_key, "approved")}>
                      Approve → Continue to {ap.next_phase || "next phase"}
                    </button>
                    <button style={{ padding: "9px 14px", border: "1.5px solid var(--red)", background: "rgba(239,68,68,.07)", color: "var(--red)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
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
              // Extract full content from the owning agent's result
              let fullContent: string | null = null;
              const tryExtract = (r: Record<string, unknown>): string | null => {
                // Try summary variant first (agents often put content in {key}_summary, not {key})
                const candidates = [
                  art.key ? r[`${art.key}_summary`] : null,
                  art.key ? r[art.key] : null,
                  r.summary, r.output_summary, r.formatted_text, r.report, r.text, r.url, r.html,
                ];
                for (const c of candidates) {
                  if (c && typeof c === "string" && c.length > 30) return c;
                }
                // Fallback: format the result as readable markdown sections (never raw JSON)
                const SKIP = new Set(["handoff", "mirror_verdict", "mirror_critique", "agent", "status", "task_id", "session_id", "sources_list", "artifacts_produced", "documents"]);
                const sections: string[] = [];
                const fmtVal = (sv: unknown): string => typeof sv === "object" && sv !== null ? JSON.stringify(sv) : String(sv);
                for (const [k, v] of Object.entries(r)) {
                  if (SKIP.has(k) || v === null || v === undefined || v === "") continue;
                  const label = k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                  if (typeof v === "string" && v.length > 5) sections.push(`## ${label}\n${v}`);
                  else if (typeof v === "number" || typeof v === "boolean") sections.push(`**${label}:** ${v}`);
                  else if (Array.isArray(v)) sections.push(`## ${label}\n${(v as unknown[]).map((x) => `- ${fmtVal(x)}`).join("\n")}`);
                  else if (typeof v === "object") {
                    const sub = Object.entries(v as Record<string, unknown>).filter(([, sv]) => sv !== null && sv !== "").map(([sk, sv]) => `- **${sk.replace(/_/g, " ")}:** ${fmtVal(sv)}`).join("\n");
                    if (sub) sections.push(`## ${label}\n${sub}`);
                  }
                }
                return sections.join("\n\n") || null;
              };
              // Try owner agent first, then scan all agents (owner_agent may be unset or mismatched)
              const ownerResult = art.owner_agent ? (st.agents[art.owner_agent]?.result as Record<string, unknown> | null) : null;
              if (ownerResult && typeof ownerResult === "object") {
                fullContent = tryExtract(ownerResult as Record<string, unknown>);
              }
              if (!fullContent) {
                for (const ag of Object.values(st.agents)) {
                  if (!ag.result || typeof ag.result !== "object") continue;
                  const extracted = tryExtract(ag.result as Record<string, unknown>);
                  if (extracted && extracted.length > 50) { fullContent = extracted; break; }
                }
              }
              const displayContent = fullContent || art.content || (art.preview && art.preview.length > 30 ? art.preview : null) || art.description || null;
              // Collect any generated files (PDFs, images, docs) from agent results so
              // the founder can open the actual documents an agent produced.
              const files = new Map<string, string>();
              const scanFiles = (val: unknown) => {
                if (typeof val === "string") {
                  // Real generated deliverables live under the /files/ dir. Link those
                  // (or a bare logical filename the endpoint can resolve) — but NOT
                  // source URLs, READMEs, repo files, or session .md notes, which aren't
                  // downloadable and 404 ("File not found").
                  const m = val.match(/[\w./\-]+\.(?:pdf|png|jpe?g|docx?|pptx?|csv|xlsx?)\b/gi);
                  if (m) for (const tok of m) {
                    const base = tok.split("/").pop();
                    if (!base || base.toLowerCase().startsWith("readme")) continue;
                    const hasSlash = tok.includes("/");
                    if (hasSlash && !tok.includes("/files/")) continue; // URL or other path
                    files.set(base, `${API}/files/${encodeURIComponent(base)}`);
                  }
                } else if (Array.isArray(val)) { val.forEach(scanFiles); }
                else if (val && typeof val === "object") { Object.values(val as Record<string, unknown>).forEach(scanFiles); }
              };
              for (const ag of Object.values(st.agents)) if (ag.result) scanFiles(ag.result);
              const fileList = Array.from(files.entries());
              // Design showcase: palette swatches + generated logos/brand images.
              const isDesign = art.owner_agent === "design" || /palette|logo|brand|design|color|visual|wordmark/i.test((art.key || "") + (art.title || ""));
              if (isDesign && !imgsFetched.current) { imgsFetched.current = true; getSessionImages(sessionId).then(setDesignImages).catch(() => {}); }
              const palette: { hex: string; name?: string }[] = [];
              if (isDesign) {
                const seen = new Set<string>();
                const blob = JSON.stringify(st.agents["design"]?.result ?? {}) + (art.content || "") + (art.preview || "");
                const hexes = blob.match(/#[0-9a-fA-F]{6}\b/g) || [];
                for (const h of hexes) { const u = h.toUpperCase(); if (!seen.has(u)) { seen.add(u); palette.push({ hex: u }); } }
              }
              const logoEntries = isDesign ? Object.entries(designImages.logos || {}) : [];
              const brandImgs = isDesign ? (designImages.brand_images || []) : [];
              return <>
                <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{art.title || art.key}</div>
                <div style={{ fontSize: 9, color: art.status === "ready" ? "var(--green)" : "var(--amber)", marginBottom: 10 }}>{art.status === "ready" ? "✓ ready" : "⋯ being written"}</div>
                {fileList.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 12 }}>
                    {fileList.map(([name, url]) => (
                      <a key={name} href={url} target="_blank" rel="noreferrer" style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 10px", border: "1px solid var(--bd)", background: "var(--surface)", color: "var(--blue)", fontSize: 11, textDecoration: "none", fontFamily: "var(--font-ibm-mono)" }}>📄 {name} ↗</a>
                    ))}
                  </div>
                )}
                {palette.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 9, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 6 }}>Color palette</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {palette.slice(0, 12).map((c) => (
                        <div key={c.hex} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                          <div style={{ width: 46, height: 46, background: c.hex, border: "1px solid var(--bd)", borderRadius: 6 }} />
                          <div style={{ fontSize: 8.5, color: "var(--fd)", fontFamily: "var(--font-ibm-mono)" }}>{c.hex}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {(logoEntries.length > 0 || brandImgs.length > 0) && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 9, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 6 }}>Logos & brand</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                      {logoEntries.map(([name, b64]) => (
                        <div key={name} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                          <img src={`data:image/png;base64,${b64}`} alt={name} style={{ width: 96, height: 96, objectFit: "contain", border: "1px solid var(--bd)", borderRadius: 8, background: "#fff", padding: 4 }} />
                          <div style={{ fontSize: 8.5, color: "var(--fm)" }}>{name}</div>
                        </div>
                      ))}
                      {brandImgs.slice(0, 6).map((b, i) => (
                        <img key={i} src={`data:image/png;base64,${b.base64}`} alt={b.prompt || "brand"} title={b.prompt} style={{ width: 130, height: 96, objectFit: "cover", border: "1px solid var(--bd)", borderRadius: 8 }} />
                      ))}
                    </div>
                  </div>
                )}
                {displayContent
                  ? <RichText text={displayContent} />
                  : fileList.length === 0 && palette.length === 0 && logoEntries.length === 0 && brandImgs.length === 0 && <div style={{ color: "var(--fm)", fontSize: 10.5, fontStyle: "italic" }}>Agent hasn't produced output yet — check back when it completes.</div>}
              </>;
            })()}

            {/* selected dept — updates / tech logs / sources */}
            {st.selDept && !st.selArt && (() => {
              const d = st.selDept === "__other" ? { ags: otherAgs } : DEPTS[st.selDept] || { ags: [] };
              const ags = (d.ags || []).filter((a) => st.agents[a]);
              const all: (LogEntry & { agent: string })[] = [];
              for (const k of ags) for (const e of st.agents[k].log) all.push({ ...e, agent: k });
              all.sort((a, b) => a.ts - b.ts);

              // Terminal tab — raw openclaude (claude-code CLI) stream for the
              // technical/web build. Only the technical dept arms it; if the tab
              // is stale after switching depts, fall through to Updates below.
              if (st.tab === "terminal" && st.selDept === "technical") {
                // Live interactive takeover — user drives the agent's openclaude session.
                if (takeover) {
                  return <TerminalPane sessionId={sessionId} founderId={founderId || ""} onClose={() => setTakeover(false)} />;
                }
                const term: TermEntry[] = [];
                for (const k of ags) for (const e of (st.agents[k].term || [])) term.push(e);
                term.sort((a, b) => a.ts - b.ts);
                const isRunning = ags.some((a) => st.agents[a].status === "running");
                const takeoverBtn = (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <button
                      onClick={() => setTakeover(true)}
                      title="Resume the agent's openclaude session and drive it yourself"
                      style={{ fontSize: 10.5, fontFamily: "var(--font-mono, monospace)", fontWeight: 700, color: "#0c0d10", background: "#7dd3fc", border: "none", borderRadius: 6, padding: "5px 12px", cursor: "pointer" }}
                    >
                      ⚡ Take over session
                    </button>
                    <span style={{ fontSize: 9, color: "var(--fm)" }}>pauses the agent · you type into the live openclaude</span>
                  </div>
                );
                if (!term.length) {
                  return <>
                    {takeoverBtn}
                    <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 10.5, color: "var(--fm)", padding: "10px 12px", background: "#0c0d10", borderRadius: 8, lineHeight: 1.6 }}>
                      {isRunning ? "▌ Waiting for the build agent to start its terminal…" : "No terminal output yet — start a build run, or take over now."}
                    </div>
                  </>;
                }
                const C: Record<string, string> = { command: "#7dd3fc", output: "#d4d4d8", error: "#fca5a5", file: "#86efac", log: "#e4e4e7", plan: "#fcd34d", tool: "#a5b4fc", phase: "#fcd34d", deploy: "#86efac" };
                return <>
                  {takeoverBtn}
                  <div style={{ background: "#0c0d10", borderRadius: 8, padding: "10px 12px", maxHeight: "60vh", overflowY: "auto", fontFamily: "var(--font-mono, monospace)", fontSize: 10.5, lineHeight: 1.55 }}>
                    {term.map((e, i) => {
                      const color = C[e.kind] || "#d4d4d8";
                      const prefix = e.kind === "command" ? "$ " : e.kind === "error" ? "✗ " : e.kind === "file" ? "✎ " : e.kind === "phase" ? "▸ " : e.kind === "deploy" ? "→ " : "";
                      return <div key={i} style={{ display: "flex", gap: 6, padding: "1px 0", alignItems: "flex-start" }}>
                        {ags.length > 1 && <span style={{ color: "#6b7280", flexShrink: 0, fontSize: 9, minWidth: 70 }}>{e.agent}</span>}
                        <pre style={{ margin: 0, color, whiteSpace: "pre-wrap", wordBreak: "break-word", flex: 1 }}>{prefix}{e.text}</pre>
                      </div>;
                    })}
                    {isRunning && <div style={{ color: "#7dd3fc" }}>▌</div>}
                  </div>
                </>;
              }

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

              // "updates" tab — tool actions + thinking + completions + errors
              // think: only fires if model emits reasoning tokens (not always)
              // tool: fires for every tool call — reformatted as plain English
              const updates = all.filter((l) => l.type === "think" || l.type === "tool" || l.type === "done" || l.type === "error" || l.type === "start");
              if (!updates.length) {
                const isRunning = ags.some((a) => st.agents[a].status === "running");
                return <div style={{ color: "var(--fd)", fontSize: 10.5, lineHeight: 1.6 }}>{isRunning ? "Agents are working — updates appear here as they act." : "Waiting to start."}</div>;
              }

              // Reformat a tool log entry into a human-readable action string
              const TOOL_VERBS: Record<string, string> = {
                web_search: "Searching", search: "Searching", google_search: "Searching",
                read_url: "Reading", fetch_url: "Reading", browse: "Reading", get_url: "Reading",
                analyze: "Analyzing", analyze_market: "Analyzing market",
                obsidian_log: "Saving notes", write_note: "Saving notes",
                create_file: "Creating file", write_file: "Writing file", save_file: "Saving file",
                generate_pdf: "Generating PDF", create_pdf: "Generating PDF",
                send_email: "Sending email", draft_email: "Drafting email",
                find_leads: "Finding leads", enrich_lead: "Enriching lead",
                claude_code: "Building", deploy: "Deploying", git_push: "Pushing code",
                create_repo: "Creating repo", create_design: "Creating design",
              };
              const fmtTool = (text: string): string => {
                const ci = text.indexOf(": ");
                const name = ci > 0 ? text.slice(0, ci) : text;
                const argsRaw = ci > 0 ? text.slice(ci + 2) : "";
                const verb = TOOL_VERBS[name] || `Using ${name.replace(/_/g, " ")}`;
                try {
                  const args = JSON.parse(argsRaw);
                  const q = args.query || args.url || args.path || args.topic || args.subject || args.keyword || args.name || "";
                  if (q && typeof q === "string") return `${verb}: ${q.slice(0, 90)}`;
                } catch {}
                return verb;
              };

              // First sentence from think text
              const thinkSnippet = (raw: string): string => {
                const clean = raw.replace(/\s+/g, " ").trim();
                const seps = [". ", "! ", "? ", "\n"];
                let end = 9999;
                for (const sep of seps) { const i = clean.indexOf(sep); if (i > 15) { end = Math.min(end, i + 1); } }
                return (end < 9999 ? clean.slice(0, end) : clean).slice(0, 160).trim();
              };

              return <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {updates.map((l, i) => {
                  if (l.type === "error") return (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "10px 12px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", marginTop: 6 }}>
                      <span style={{ fontSize: 13, flexShrink: 0, marginTop: 2 }}>✗</span>
                      <div>
                        {ags.length > 1 && <div style={{ fontSize: 9, fontWeight: 700, color: "var(--red)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 3 }}>{l.agent}</div>}
                        <span style={{ fontSize: 11.5, color: "var(--red)", lineHeight: 1.5 }}>{l.text}</span>
                      </div>
                    </div>
                  );
                  if (l.type === "done") {
                    const summary = l.text && l.text !== "Agent finished" ? l.text : null;
                    return (
                      <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "12px 13px", borderRadius: 8, background: "rgba(52,211,153,.05)", border: "1px solid rgba(52,211,153,.2)", marginTop: 6 }}>
                        <span style={{ fontSize: 15, flexShrink: 0, marginTop: 1 }}>✓</span>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--green)", marginBottom: summary ? 5 : 0 }}>
                            {l.agent.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())} finished
                          </div>
                          {summary && <div style={{ fontSize: 12, color: "var(--fg)", lineHeight: 1.65, wordBreak: "break-word" }}>{summary}</div>}
                        </div>
                      </div>
                    );
                  }
                  if (l.type === "start") return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, padding: "4px 0", opacity: 0.65 }}>
                      <span style={{ fontSize: 10, color: "var(--blue)" }}>▶</span>
                      <span style={{ fontSize: 11, color: "var(--fd)" }}>
                        {l.agent.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())} started
                      </span>
                    </div>
                  );
                  if (l.type === "tool") {
                    const action = fmtTool(l.text);
                    return (
                      <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "4px 0" }}>
                        {ags.length > 1 && <span style={{ fontSize: 9, color: "var(--blue)", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", flexShrink: 0, marginTop: 2, minWidth: 54 }}>{l.agent.split("_")[0]}</span>}
                        <span style={{ fontSize: 11.5, color: "var(--fg)", lineHeight: 1.5 }}>{action}</span>
                      </div>
                    );
                  }
                  // think — only shows if reasoning tokens emitted
                  const snippet = thinkSnippet(l.text);
                  if (!snippet) return null;
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "3px 0" }}>
                      {ags.length > 1 && <span style={{ fontSize: 9, color: "var(--blue)", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", flexShrink: 0, marginTop: 2, minWidth: 54 }}>{l.agent.split("_")[0]}</span>}
                      <span style={{ fontSize: 11.5, color: "var(--fd)", lineHeight: 1.55, fontStyle: "italic" }}>{snippet}</span>
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

      {/* copilot chat bar */}
      <div data-tour="session-steerbar" className={`steerbar copilot-dock ${copilotOpen ? "is-open" : ""}`}>
        {copilotOpen && (
          <div className="copilot-thread">
            {copilot.length === 0 && (
              <div className="copilot-empty">
                Ask or direct Astra. The copilot can answer from your company brain, read &amp; approve goals, steer the running agents, and run a cycle. Try “what’s our current goal?”, “tell the team to focus on pricing”, or “approve the next goal”.
              </div>
            )}
            {copilot.map((m, i) => (
              <div key={i} className={`copilot-row ${m.role === "founder" ? "is-founder" : "is-astra"}`}>
                {m.role !== "founder" && <span className="copilot-avatar">A</span>}
                <div className="copilot-bubble">
                  {m.content}
                  {m.actions && m.actions.length > 0 && (
                    <div className="copilot-actions">⚙ {m.actions.join(" · ")}</div>
                  )}
                </div>
              </div>
            ))}
            {copilotBusy && (
              <div className="copilot-row is-astra">
                <span className="copilot-avatar">A</span>
                <div className="copilot-thinking"><span /><span /><span /></div>
              </div>
            )}
          </div>
        )}
        <div className="steer-wrap">
          <button className="steer-send copilot-toggle" aria-label="Toggle copilot" title="Copilot chat" onClick={() => setCopilotOpen((v) => !v)}>{copilotOpen ? "▾" : "✦"}</button>
          <input ref={steerRef} className="steer-inp" aria-label="Ask or direct Astra"
            placeholder='Ask or direct Astra — "what’s our goal?" · "focus on pricing" · "approve next goal"'
            onFocus={() => setCopilotOpen(true)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); setCopilotOpen(true); sendCopilot(); } }} />
          <button className="steer-send copilot-submit" aria-label="Send" onClick={() => { setCopilotOpen(true); sendCopilot(); }}>↑</button>
        </div>
      </div>

      {showSessionTour && (
        <SessionTour onDone={() => { localStorage.setItem("astra_session_tour_done", "1"); setShowSessionTour(false); }} />
      )}

      {/* Node → dept-card beams: fixed SVG overlay, pointer-events none */}
      {beams.length > 0 && (
        <svg
          style={{ position: "fixed", inset: 0, width: "100vw", height: "100vh", pointerEvents: "none", zIndex: 997 }}
          aria-hidden="true"
        >
          <defs>
            <style>{`
              @keyframes sv-beam-flow { from { stroke-dashoffset: 80; } to { stroke-dashoffset: 0; } }
            `}</style>
          </defs>
          {beams.map(b => {
            const len = Math.hypot(b.x2 - b.x1, b.y2 - b.y1);
            return (
              <g key={b.key}>
                {/* faint static path — shows the connection */}
                <line x1={b.x1} y1={b.y1} x2={b.x2} y2={b.y2}
                  stroke="var(--blue)" strokeWidth={0.75} strokeOpacity={0.18} />
                {/* flowing dashes — animate offset to make them travel node → card */}
                <line x1={b.x1} y1={b.y1} x2={b.x2} y2={b.y2}
                  stroke="var(--blue)" strokeWidth={1} strokeOpacity={0.55}
                  strokeDasharray="5 9" strokeLinecap="round">
                  <animate attributeName="stroke-dashoffset"
                    from={String(len)} to="0"
                    dur="1.1s" repeatCount="indefinite" />
                </line>
                {/* leading dot at node origin */}
                <circle cx={b.x1} cy={b.y1} r={2.5} fill="var(--mint)" opacity={0.85} />
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
