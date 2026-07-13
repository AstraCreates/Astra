"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, getCredits, AGENT_LABELS, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";
import AstraCopilotComposer, { type CopilotAgentOption, extractAgentMentions } from "./AstraCopilotComposer";

const GREETINGS = [
  "Good to see you",
  "Welcome back",
  "Let's get to work",
  "Ready to build",
  "Let's keep building",
];

function extractGoalTitle(raw: string): string {
  return raw
    .replace(/^FOLLOW-UP RUN for GOAL:\s*/i, "")
    .replace(/^GOAL:\s*/i, "")
    .replace(/\s*An earlier run already completed[\s\S]*$/i, "")
    .replace(/\s*Work together to complete these major tasks[\s\S]*$/i, "")
    .replace(/\s*Each agent: deliver[\s\S]*$/i, "")
    .replace(/\s*Finish ONLY the \d+[\s\S]*$/i, "")
    .trim() || raw;
}

function ago(ts: string | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now"; if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

type CopilotAction = { tool: string; label: string; detail?: string; tone?: "info" | "success" | "warn" };

function titleCaseTool(raw: string): string {
  return raw.split("_").filter(Boolean).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function normalizeCopilotActions(actions: any): CopilotAction[] {
  if (!Array.isArray(actions)) return [];
  return actions.map((action: any) => {
    if (typeof action === "string") return { tool: action, label: titleCaseTool(action), tone: "info" as const };
    const tool = String(action?.tool || action?.name || "").trim();
    if (!tool) return null;
    return {
      tool,
      label: String(action?.label || titleCaseTool(tool)),
      detail: typeof action?.detail === "string" ? action.detail : undefined,
      tone: action?.tone === "success" || action?.tone === "warn" ? action.tone : "info",
    };
  }).filter(Boolean) as CopilotAction[];
}

function pickCopilotSession(sessions: SessionIndexEntry[]): SessionIndexEntry | null {
  if (!sessions.length) return null;
  return sessions.find((s) => s.status === "stalled") || sessions.find((s) => s.status === "running") || sessions[0] || null;
}

// Constellation SVG for hero banner
function HeroIllustration() {
  return (
    <svg width="320" height="200" viewBox="0 0 320 200" fill="none" style={{ position: "absolute", right: 0, top: 0, height: "100%", width: "auto", opacity: 0.55, pointerEvents: "none" }}>
      <g stroke="white" strokeWidth="0.8" strokeLinecap="round">
        {/* Central star burst */}
        <line x1="220" y1="80" x2="220" y2="20" />
        <line x1="220" y1="80" x2="220" y2="140" />
        <line x1="220" y1="80" x2="160" y2="80" />
        <line x1="220" y1="80" x2="280" y2="80" />
        <line x1="220" y1="80" x2="177" y2="37" />
        <line x1="220" y1="80" x2="263" y2="37" />
        <line x1="220" y1="80" x2="177" y2="123" />
        <line x1="220" y1="80" x2="263" y2="123" />
        {/* Extended rays */}
        <line x1="220" y1="20" x2="220" y2="2" opacity="0.4" />
        <line x1="220" y1="140" x2="220" y2="165" opacity="0.3" />
        <line x1="280" y1="80" x2="310" y2="80" opacity="0.35" />
        <line x1="160" y1="80" x2="130" y2="80" opacity="0.3" />
        <line x1="263" y1="37" x2="290" y2="10" opacity="0.3" />
        <line x1="177" y1="37" x2="148" y2="8" opacity="0.25" />
        <line x1="263" y1="123" x2="292" y2="152" opacity="0.25" />
        <line x1="177" y1="123" x2="150" y2="150" opacity="0.2" />
        {/* Scattered dots */}
        <circle cx="100" cy="30" r="1.5" fill="white" opacity="0.6" />
        <circle cx="290" cy="160" r="1" fill="white" opacity="0.5" />
        <circle cx="60" cy="110" r="1" fill="white" opacity="0.4" />
        <circle cx="305" cy="50" r="1.2" fill="white" opacity="0.5" />
        <circle cx="140" cy="170" r="1" fill="white" opacity="0.35" />
        <circle cx="80" cy="60" r="0.8" fill="white" opacity="0.45" />
        <circle cx="250" cy="175" r="1.5" fill="white" opacity="0.4" />
        {/* Connecting constellation lines */}
        <line x1="100" y1="30" x2="80" y2="60" opacity="0.2" />
        <line x1="80" y1="60" x2="60" y2="110" opacity="0.18" />
        <line x1="305" y1="50" x2="290" y2="160" opacity="0.15" />
        {/* Star center diamond */}
        <polygon points="220,68 228,80 220,92 212,80" fill="white" opacity="0.9" stroke="none" />
        <polygon points="220,72 225,80 220,88 215,80" fill="white" opacity="0.4" stroke="none" />
      </g>
    </svg>
  );
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [pendingDel, setPendingDel] = useState<Set<string>>(new Set());
  const deletedIdsRef = useRef<Set<string>>(new Set());
  const [toastErr, setToastErr] = useState("");
  const showErr = (msg: string) => { setToastErr(msg); setTimeout(() => setToastErr(""), 6000); };
  const [firstName, setFirstName] = useState("");
  const [greeting, setGreeting] = useState("");
  const [digests, setDigests] = useState<Map<string, SessionDigest>>(new Map());
  const [showCompleted, setShowCompleted] = useState(false);
  const [copilot, setCopilot] = useState<{ role: string; content: string; actions?: CopilotAction[] }[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState("");
  const retriedRef = useRef(false);
  const prevStatusRef = useRef<Map<string, string>>(new Map());
  const copilotLoadedSession = useRef<string | null>(null);
  const [copilotInput, setCopilotInput] = useState("");
  const [launchComplete, setLaunchComplete] = useState<{ companyName: string; founderName: string; agentsRan: number; artifactsCreated: number; stackName?: string } | null>(null);
  const [credits, setCredits] = useState<number | null>(null);
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => {
    if (!userId) return;
    getCredits(userId).then(b => setCredits(b.balance)).catch(() => {});
  }, [userId]);

  useEffect(() => {
    if (!consumePreviewSignal()) return;
    const company = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_company") || localStorage.getItem("astra_onboarding_name") || "") : "";
    const fullName = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_name") || "") : "";
    const founder = fullName.split(" ")[0] || fullName;
    setLaunchComplete({ companyName: company, founderName: founder, agentsRan: 0, artifactsCreated: 0 });
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const fullName = localStorage.getItem("astra_onboarding_name") || "";
      setFirstName(fullName.split(" ")[0] || fullName);
    }
    setGreeting(GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
  }, []);

  const del = useCallback(async (e: React.MouseEvent, s: SessionIndexEntry) => {
    e.stopPropagation();
    e.preventDefault();
    if (!pendingDel.has(s.session_id)) {
      setPendingDel((p) => new Set(p).add(s.session_id));
      setTimeout(() => setPendingDel((p) => { const n = new Set(p); n.delete(s.session_id); return n; }), 3000);
      return;
    }
    setPendingDel((p) => { const n = new Set(p); n.delete(s.session_id); return n; });
    setDeleting((p) => new Set(p).add(s.session_id));
    deletedIdsRef.current.add(s.session_id);
    deleteLocalSession(s.session_id);
    setSessions((prev) => (prev || []).filter((x) => x.session_id !== s.session_id));
    try {
      await killSession(s.session_id).catch(() => {});
      const ok = await deleteSessionRemote(s.session_id);
      if (!ok) { showErr("Could not delete this run on the server — it may reappear on refresh."); }
    } finally {
      setDeleting((p) => { const n = new Set(p); n.delete(s.session_id); return n; });
    }
  }, [pendingDel]);

  const load = useCallback(async () => {
    if (!userId) return;
    setError("");
    try {
      const fetched = await listSessions(userId, 50);
      setSessions(fetched.filter((x) => !deletedIdsRef.current.has(x.session_id)));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setSessions((p) => p ?? []); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (sessions === null || sessions.length > 0 || retriedRef.current) return;
    retriedRef.current = true;
    const t = setTimeout(() => void load(), 2000);
    return () => clearTimeout(t);
  }, [sessions, load]);

  useEffect(() => {
    if (!userId) return;
    const refreshIfVisible = () => { if (document.visibilityState === "visible") void load(); };
    const interval = window.setInterval(refreshIfVisible, 15000);
    window.addEventListener("focus", refreshIfVisible);
    document.addEventListener("visibilitychange", refreshIfVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshIfVisible);
      document.removeEventListener("visibilitychange", refreshIfVisible);
    };
  }, [userId, load]);

  useEffect(() => {
    if (!sessions) return;
    const running = sessions.filter(s => s.status === "running");
    if (!running.length) return;
    const fetchAll = async () => {
      const results = await Promise.allSettled(
        running.map(s => getSessionDigest(s.session_id).then(d => [s.session_id, d] as [string, SessionDigest]))
      );
      setDigests(prev => {
        const next = new Map(prev);
        for (const r of results) { if (r.status === "fulfilled") next.set(r.value[0], r.value[1]); }
        return next;
      });
    };
    void fetchAll();
    const t = setInterval(fetchAll, 15_000);
    return () => clearInterval(t);
  }, [sessions]);

  useEffect(() => {
    if (!sessions?.length) { setCopilotSessionId(""); return; }
    const preferred = pickCopilotSession(sessions);
    if (!preferred) return;
    setCopilotSessionId((current) => {
      if (current && sessions.some((s) => s.session_id === current)) return current;
      return preferred.session_id;
    });
  }, [sessions]);

  useEffect(() => {
    if (!copilotOpen || !copilotSessionId || copilotLoadedSession.current === copilotSessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`);
        const d = await r.json();
        if (cancelled) return;
        if (Array.isArray(d.history)) {
          setCopilot((prev) => {
            if (prev.length > 0) return prev;
            return d.history.map((item: any) => ({ role: item.role, content: item.content, actions: normalizeCopilotActions(item.actions) }));
          });
        }
        copilotLoadedSession.current = copilotSessionId;
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [copilotOpen, copilotSessionId]);

  useEffect(() => { copilotLoadedSession.current = null; setCopilot([]); }, [copilotSessionId]);

  useEffect(() => {
    if (!sessions) return;
    const prev = prevStatusRef.current;
    const isFirstLoad = prev.size === 0;
    const canShow = shouldShowLaunchComplete();
    let triggered = false;
    for (const s of sessions) {
      if (s.stack_id === "custom") continue;
      const wasRunning = prev.get(s.session_id) === "running";
      const nowDone = s.status === "done";
      if (canShow && !triggered && (wasRunning && nowDone || isFirstLoad && nowDone)) {
        const digest = digests.get(s.session_id);
        setLaunchComplete({
          companyName: s.company_name || "",
          founderName: firstName,
          agentsRan: digest?.counts.done_agents ?? 0,
          artifactsCreated: digest?.counts.ready_artifacts ?? 0,
          stackName: s.stack_id ? s.stack_id.replace(/_/g, " ") : undefined,
        });
        markLaunchCompleteShown();
        triggered = true;
      }
      prev.set(s.session_id, s.status);
    }
  }, [sessions, digests]);

  const running = (sessions || []).filter((s) => s.status === "running").length;
  const customSessions = (sessions || []).filter((s) => s.stack_id === "custom");
  const regularSessions = (sessions || []).filter((s) => s.stack_id !== "custom");
  const copilotSession = (sessions || []).find((s) => s.session_id === copilotSessionId) || null;
  const copilotTitle = copilotSession ? extractGoalTitle(copilotSession.goal || "Current run") : "";
  const copilotAgents: CopilotAgentOption[] = Object.entries(AGENT_LABELS)
    .map(([id, label]) => ({ id, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  const heroSubtitle = sessions === null
    ? "Loading your workspace…"
    : running > 0
      ? `${running} run${running !== 1 ? "s" : ""} active${sessions.filter(s => s.status === "done").length > 0 ? ` · ${sessions.filter(s => s.status === "done").length} completed today` : ""}`
      : "Astra is ready when you are.";

  const sendCopilot = useCallback(async (message?: string, mentionedAgents: string[] = []) => {
    const msg = (message ?? copilotInput).trim();
    if (!msg || copilotBusy || !copilotSessionId) return;
    setCopilotInput("");
    setCopilotOpen(true);
    setCopilot((current) => [...current, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const r = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, mentioned_agents: mentionedAgents }),
      });
      const d = await r.json();
      setCopilot((current) => [...current, { role: "copilot", content: d.reply || "(no reply)", actions: normalizeCopilotActions(d.actions) }]);
    } catch {
      setCopilot((current) => [...current, { role: "copilot", content: "Copilot error — try again." }]);
    } finally {
      setCopilotBusy(false);
    }
  }, [copilotBusy, copilotInput, copilotSessionId]);

  return (
    <>
      <style>{`
        @keyframes dv-fade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes sc-shimmer { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
        @keyframes sc-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        @keyframes mascot-float { 0%,100% { transform: translateY(0px); } 50% { transform: translateY(-4px); } }

        /* Hero */
        .dv-hero { position: relative; overflow: hidden; background: linear-gradient(110deg, #04070f 0%, #071030 50%, #0a1850 100%); min-height: 140px; padding: 22px 28px 24px; display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid rgba(255,255,255,.07); }
        .dv-hero-breadcrumb { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: #7cffc6; margin-bottom: 4px; }
        .dv-hero-title { font-size: 30px; font-weight: 700; color: #edf1fb; letter-spacing: -.3px; line-height: 1.15; }
        .dv-hero-sub { font-size: 12px; color: rgba(237,241,251,.5); margin-top: 2px; }
        .dv-hero-btns { display: flex; gap: 8px; margin-top: 14px; }
        .dv-hero-btn { min-height: 32px; padding: 0 14px; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.06); color: #edf1fb; }
        .dv-hero-btn.primary { background: #002EFF; border-color: #002EFF; color: #fff; }
        .dv-hero-btn.primary:hover { background: #1a44ff; }

        /* Today header */
        .dv-today-row { display: flex; align-items: center; justify-content: space-between; }
        .dv-today-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #6f7b98; }
        .dv-today-tabs { display: flex; gap: 2px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 7px; padding: 2px; }
        .dv-today-tab { min-height: 24px; padding: 0 10px; border: none; border-radius: 5px; background: transparent; color: #6f7b98; font-size: 10.5px; font-weight: 600; cursor: pointer; font-family: inherit; transition: background .12s, color .12s; }
        .dv-today-tab.active { background: rgba(255,255,255,.09); color: #edf1fb; }

        /* Run rows */
        .dv-run-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-top: 1px solid rgba(255,255,255,.06); cursor: pointer; transition: background .12s; }
        .dv-run-row:first-child { border-top: none; }
        .dv-run-row:hover { background: rgba(255,255,255,0.03); }

        /* Goal col */
        .dv-goal-col { width: 280px; flex: none; background: #0A0D17; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 18px; }

        /* Automations strip */
        .dv-automations { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: rgba(255,255,255,.02); border: 1px solid rgba(255,255,255,.06); border-radius: 10px; }
        .dv-automations-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #6f7b98; flex-shrink: 0; }
        .dv-automations-msg { font-size: 12px; color: #6f7b98; flex: 1; }
        .dv-automations-link { font-size: 11px; color: #7d8fff; background: none; border: none; cursor: pointer; font-weight: 600; font-family: inherit; flex-shrink: 0; }

        /* Copilot bar */
        .dv-copilot-bar { border-top: 1px solid rgba(255,255,255,.08); background: #070911; }
        .dv-copilot-bar-label { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: #6f7b98; padding: 10px 18px 0; }
        .dv-copilot-inner { display: flex; align-items: flex-start; gap: 12px; padding: 8px 16px 14px; }
        .dv-mascot { width: 44px; height: 44px; flex-shrink: 0; object-fit: contain; image-rendering: pixelated; animation: mascot-float 3s ease-in-out infinite; margin-top: 2px; }
        .dv-copilot-composer { flex: 1; min-width: 0; }

        /* Copilot thread (expandable above the bar) */
        .dv-copilot-thread { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px 18px 4px; }
        .dv-copilot-row { display: flex; gap: 8px; align-items: flex-start; }
        .dv-copilot-row.is-founder { justify-content: flex-end; }
        .dv-copilot-avatar { width: 22px; height: 22px; border-radius: 999px; background: linear-gradient(135deg, #002EFF, #7CFFC6); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; }
        .dv-copilot-bubble { max-width: min(520px,85%); padding: 8px 10px; border-radius: 10px; background: rgba(255,255,255,0.06); color: #EDF1FB; font-size: 11px; line-height: 1.6; white-space: pre-wrap; }
        .dv-copilot-row.is-founder .dv-copilot-bubble { background: #002EFF; }
        .dv-copilot-thinking { display: inline-flex; gap: 4px; align-items: center; padding: 8px 10px; border-radius: 10px; background: rgba(255,255,255,0.06); }
        .dv-copilot-thinking span { width: 5px; height: 5px; border-radius: 999px; background: #7CFFC6; opacity: .4; animation: sc-shimmer 1s ease-in-out infinite; }
        .dv-copilot-thinking span:nth-child(2) { animation-delay: .12s; }
        .dv-copilot-thinking span:nth-child(3) { animation-delay: .24s; }

        /* Secondary nav */
        .dashboard-secondary-links { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
        .dashboard-secondary-links button { min-height: 30px; padding: 0 9px; border: 0; background: transparent; color: #6f7b98; font-size: 10.5px; cursor: pointer; font-family: inherit; }
        .dashboard-secondary-links button:hover { color: #aab5ff; }

        .dv-goal-title { max-height: 120px; overflow-y: auto; padding-right: 8px; color: #edf1fb; font-size: 15px; font-weight: 700; line-height: 1.42; overflow-wrap: anywhere; scrollbar-color: rgba(125,143,255,.5) transparent; }
        .dv-goal-title::-webkit-scrollbar { width: 4px; }
        .dv-goal-title::-webkit-scrollbar-thumb { background: rgba(125,143,255,.5); border-radius: 4px; }

        @media (max-width: 700px) {
          .dv-hero-title { font-size: 22px; }
          .dv-body { flex-direction: column !important; }
          .dv-goal-col { width: 100% !important; }
        }
      `}</style>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>

        {/* ── Hero banner ── */}
        <div className="dv-hero">
          <HeroIllustration />
          <div className="dv-hero-breadcrumb">Dashboard</div>
          <div className="dv-hero-title">
            {greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "Welcome back."}
          </div>
          <div className="dv-hero-sub">{heroSubtitle}</div>
          <div className="dv-hero-btns">
            <button className="dv-hero-btn primary" data-tour="dash-new-run" onClick={() => router.push("/dashboard?new=1")}>+ New run</button>
            <button className="dv-hero-btn" onClick={load}>Refresh</button>
          </div>
        </div>

        {toastErr && (
          <div style={{ background: "rgba(255,80,80,0.08)", borderBottom: "1px solid rgba(255,80,80,0.18)", padding: "6px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#ff6b6b" }}>
            <span>✗</span>
            <span style={{ flex: 1 }}>{toastErr}</span>
            <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0 }}>✕</button>
          </div>
        )}

        {/* ── Main content ── */}
        <div style={{ flex: 1, padding: "18px 24px", display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Today label + tabs */}
          <div className="dv-today-row">
            <div className="dv-today-label">Today</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div className="dv-today-tabs">
                <button className={`dv-today-tab${!showCompleted ? " active" : ""}`} onClick={() => setShowCompleted(false)}>Populated</button>
                <button className={`dv-today-tab${showCompleted ? " active" : ""}`} onClick={() => setShowCompleted(true)}>View all</button>
              </div>
              <div className="dashboard-secondary-links">
                <button type="button" onClick={() => router.push("/automations")}>Automations</button>
                <button type="button" onClick={() => router.push("/goals")}>Goals</button>
                <button type="button" onClick={() => router.push("/agents")}>Agent team</button>
              </div>
            </div>
          </div>

          {/* Two columns */}
          <div className="dv-body" style={{ display: "flex", gap: 16, alignItems: "stretch" }}>

            {/* ── Active Goal card ── */}
            <div className="dv-goal-col">
              <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Active goal</div>

              {(() => {
                const active = regularSessions.find(s => s.status === "running" || s.status === "stalled") || regularSessions[0] || null;
                const accentColor = "#7D8FFF";
                if (!active) return (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "32px 16px", gap: 12, flex: 1 }}>
                    <div style={{ width: 40, height: 40, border: "1px solid rgba(255,255,255,.16)", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", transform: "rotate(45deg)" }}>
                      <div style={{ width: 12, height: 12, background: accentColor, borderRadius: 3 }} />
                    </div>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 700 }}>No active goals</div>
                      <div style={{ fontSize: 12, color: "#6f7b98", marginTop: 4 }}>Start a run and Astra will get to work.</div>
                    </div>
                  </div>
                );
                const digest = digests.get(active.session_id);
                const phasesDone = digest?.counts.phases_done ?? 0;
                const phasesTotal = digest?.counts.phases_total ?? 0;
                const phasesPending = digest?.counts.phases_pending ?? 0;
                const progress = phasesTotal > 0 ? phasesDone / phasesTotal : 0;
                const circumference = 157;
                const dashOffset = circumference * (1 - progress);
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const ringColor = isStalled ? "#FFFFA6" : accentColor;
                return (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
                      <div style={{ flex: 1, minWidth: 0, paddingRight: 10 }}>
                        <div className="dv-goal-title" title={cleanTitle}>{cleanTitle}</div>
                        <div style={{ fontSize: 11, color: "#6f7b98", marginTop: 4 }}>
                          {phasesDone > 0 || phasesTotal > 0 ? `${phasesDone} of ${phasesTotal} tasks done` : isStalled ? "Needs attention" : "Running…"}
                        </div>
                      </div>
                      <div style={{ position: "relative", width: 52, height: 52, flex: "none" }}>
                        <svg width={52} height={52} viewBox="0 0 52 52">
                          <circle cx={26} cy={26} r={22} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={4} />
                          <circle cx={26} cy={26} r={22} fill="none" stroke={ringColor} strokeWidth={4} strokeLinecap="round" strokeDasharray={138} strokeDashoffset={phasesTotal > 0 ? circumference * (1 - progress) : 115} transform="rotate(-90 26 26)" style={{ transition: "stroke-dashoffset 0.8s ease" }} />
                        </svg>
                        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1 }}>
                          <span style={{ fontSize: 13, fontWeight: 700 }}>{isDone ? "✓" : phasesDone}</span>
                          <span style={{ fontSize: 8, color: "#6f7b98" }}>/ {phasesTotal || "?"}</span>
                        </div>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 12, marginTop: 12, fontSize: 11, color: "#8A93AD" }}>
                      <span>✓ <b style={{ color: "#EDF1FB" }}>{phasesDone}</b> done</span>
                      <span>○ <b style={{ color: "#EDF1FB" }}>{phasesPending}</b> queued</span>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                      <button onClick={() => router.push(`/s/${active.session_id}`)} style={{ flex: 1, background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "9px 0", fontWeight: 600, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>▶ Run now</button>
                      <button style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "9px 14px", fontWeight: 600, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>Pause</button>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* ── Recent Runs card ── */}
            <div style={{ flex: 1, minWidth: 0, background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 18, display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ fontSize: 10, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Recent runs</div>
                <button onClick={() => setShowCompleted(v => !v)} style={{ fontSize: 11, color: "#7d8fff", background: "none", border: "none", cursor: "pointer", fontWeight: 600, fontFamily: "inherit" }}>View all →</button>
              </div>

              {sessions === null ? (
                <div style={{ color: "#6f7b98", fontSize: 13 }}>Loading…</div>
              ) : error ? (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 10 }}>{error}</div>
                  <button style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 8, fontFamily: "inherit" }} onClick={load}>Try again</button>
                </div>
              ) : !regularSessions.length ? (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "32px 16px", gap: 12 }}>
                  <div style={{ width: 40, height: 40, border: "1px solid rgba(255,255,255,.16)", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", transform: "rotate(45deg)" }}>
                    <div style={{ width: 12, height: 12, background: "#7D8FFF", borderRadius: 3 }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700 }}>No runs yet</div>
                    <div style={{ fontSize: 12, color: "#6f7b98", marginTop: 4 }}>Start your first run and Astra will get to work.</div>
                  </div>
                  <button onClick={() => router.push("/dashboard?new=1")} style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 600, fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>Start first run →</button>
                </div>
              ) : (
                <>
                  {/* 4-stat grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 14 }}>
                    {[
                      { label: "Active", value: String(running) },
                      { label: "Done today", value: String((sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length) },
                      { label: "Credits", value: credits !== null ? credits.toLocaleString() : "—" },
                      {
                        label: "Success",
                        value: (() => {
                          const done = sessions.filter(s => s.status === "done").length;
                          const failed = sessions.filter(s => s.status === "error" || s.status === "killed").length;
                          const total = done + failed;
                          return total > 0 ? `${Math.round((done / total) * 100)}%` : "—";
                        })(),
                      },
                    ].map(({ label, value }) => (
                      <div key={label} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.06)", borderRadius: 8, padding: "10px 12px" }}>
                        <div style={{ fontSize: 10, color: "#6f7b98" }}>{label}</div>
                        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{value}</div>
                      </div>
                    ))}
                  </div>

                  {/* Run list */}
                  <div data-tour="dash-sessions" style={{ display: "flex", flexDirection: "column" }}>
                    {(() => {
                      const ids = new Set(regularSessions.map(x => x.session_id));
                      const kids: Record<string, SessionIndexEntry[]> = {};
                      const roots: SessionIndexEntry[] = [];
                      for (const s of regularSessions) {
                        const p = s.parent_session_id;
                        if (p && ids.has(p)) (kids[p] ||= []).push(s);
                        else roots.push(s);
                      }
                      const allRows: { s: SessionIndexEntry; child: boolean }[] = [];
                      for (const r of roots) {
                        allRows.push({ s: r, child: false });
                        for (const k of kids[r.session_id] || []) allRows.push({ s: k, child: true });
                      }
                      const dotStyle = (status: string): React.CSSProperties => {
                        const colors: Record<string, string> = { running: "#7CFFC6", done: "#6f7b98", stalled: "#FFFFA6", error: "#FF6B6B", killed: "#FF6B6B" };
                        return { width: 7, height: 7, borderRadius: "50%", background: colors[status] || "#6f7b98", flexShrink: 0 };
                      };
                      const chip = (status: string) => {
                        const map: Record<string, { label: string; color: string; bg: string; border: string }> = {
                          running: { label: "Running", color: "#7CFFC6", bg: "rgba(124,255,198,.08)", border: "rgba(124,255,198,.2)" },
                          done: { label: "Done", color: "#8A93AD", bg: "transparent", border: "rgba(138,147,173,.2)" },
                          stalled: { label: "Needs retry", color: "#FFFFA6", bg: "rgba(255,255,166,.06)", border: "rgba(255,255,166,.2)" },
                          error: { label: "Error", color: "#FF6B6B", bg: "rgba(255,107,107,.06)", border: "rgba(255,107,107,.2)" },
                          killed: { label: "Stopped", color: "#FF6B6B", bg: "rgba(255,107,107,.06)", border: "rgba(255,107,107,.2)" },
                        };
                        const c = map[status] || { label: status, color: "#8A93AD", bg: "transparent", border: "rgba(138,147,173,.2)" };
                        return <span style={{ fontSize: 10, fontWeight: 600, color: c.color, background: c.bg, border: `1px solid ${c.border}`, padding: "2px 8px", borderRadius: 5, flexShrink: 0, whiteSpace: "nowrap" }}>{c.label}</span>;
                      };
                      const meta = (s: SessionIndexEntry) => {
                        const t = ago(s.created_at);
                        if (s.status === "running") return `Started ${t}`;
                        if (s.status === "done") return `Completed ${t}`;
                        if (s.status === "stalled" || s.status === "error") return `Failed ${t} · retry available`;
                        return t;
                      };
                      const doneCount = allRows.filter(r => r.s.status === "done").length;
                      const nonDone = allRows.filter(r => r.s.status !== "done");
                      const doneRows = allRows.filter(r => r.s.status === "done");
                      const visibleRows = showCompleted ? allRows : [...nonDone, ...doneRows.slice(0, 5)];
                      const hiddenDone = !showCompleted && doneCount > 5;
                      return (
                        <>
                          {visibleRows.map(({ s, child }) => (
                            <div key={s.session_id} className="dv-run-row" style={{ marginLeft: child ? 12 : 0, width: `calc(100% - ${child ? 12 : 0}px)` }}>
                              <button type="button" aria-label={`Open run: ${extractGoalTitle(s.goal || "Untitled run")}`} onClick={() => router.push(`/s/${s.session_id}`)} style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, border: "none", padding: 0, textAlign: "left", font: "inherit", color: "inherit", background: "transparent", cursor: "pointer" }}>
                                <span style={dotStyle(s.status)} />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                    {child && <span style={{ fontSize: 9, color: "#7D8FFF", marginRight: 4 }}>↳</span>}
                                    {extractGoalTitle(s.goal || "Untitled run")}
                                  </div>
                                  <div style={{ fontSize: 10.5, color: "#6f7b98", marginTop: 1 }}>{meta(s)}</div>
                                </div>
                                {s.kind === "user" && <span style={{ fontSize: 8, fontWeight: 700, color: "#7d8fff", background: "rgba(125,143,255,.08)", border: "1px solid rgba(125,143,255,.28)", padding: "2px 5px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0 }}>User</span>}
                                {s.kind === "scheduled" && <span style={{ fontSize: 8, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,.08)", border: "1px solid rgba(245,158,11,.28)", padding: "2px 5px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0 }}>Auto</span>}
                                {chip(s.status)}
                              </button>
                              <button
                                title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                                disabled={deleting.has(s.session_id)}
                                onClick={e => del(e, s)}
                                onPointerDown={e => e.stopPropagation()}
                                style={{ width: pendingDel.has(s.session_id) ? "auto" : 20, height: 20, padding: pendingDel.has(s.session_id) ? "0 5px" : 0, display: "flex", alignItems: "center", justifyContent: "center", background: pendingDel.has(s.session_id) ? "rgba(255,80,80,.1)" : "transparent", border: pendingDel.has(s.session_id) ? "1px solid rgba(255,80,80,.3)" : "none", color: pendingDel.has(s.session_id) ? "#ff6b6b" : "rgba(237,241,251,.18)", cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 8 : 10, borderRadius: 5, opacity: deleting.has(s.session_id) ? 0.4 : 1, flexShrink: 0, fontWeight: 700, whiteSpace: "nowrap", fontFamily: "inherit" }}
                              >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DEL?" : "✕"}</button>
                            </div>
                          ))}
                          {hiddenDone && (
                            <button onClick={() => setShowCompleted(true)} style={{ padding: "6px 4px", background: "transparent", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 11, textAlign: "left", marginTop: 2, fontFamily: "inherit" }}>
                              Show {doneCount} completed runs
                            </button>
                          )}
                          {showCompleted && doneCount > 0 && (
                            <button onClick={() => setShowCompleted(false)} style={{ padding: "5px 4px", background: "transparent", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 11, textAlign: "left", marginTop: 2, fontFamily: "inherit" }}>
                              Hide completed
                            </button>
                          )}
                        </>
                      );
                    })()}
                  </div>
                </>
              )}
            </div>
          </div>

          {/* ── Automations strip ── */}
          <div className="dv-automations">
            <div className="dv-automations-label">Automations</div>
            <div className="dv-automations-msg">No automations set up yet.</div>
            <button className="dv-automations-link" onClick={() => router.push("/automations")}>Create one →</button>
            <button className="dv-automations-link" style={{ marginLeft: 8 }} onClick={() => router.push("/automations")}>Manage automations →</button>
          </div>

        </div>

        {/* ── Copilot thread (expandable) ── */}
        {copilotOpen && copilot.length > 0 && (
          <div className="dv-copilot-thread">
            {copilot.map((message, index) => (
              <div key={index} className={`dv-copilot-row ${message.role === "founder" ? "is-founder" : "is-astra"}`}>
                {message.role !== "founder" && <span className="dv-copilot-avatar">A</span>}
                <div className="dv-copilot-bubble">{message.content}</div>
              </div>
            ))}
            {copilotBusy && (
              <div className="dv-copilot-row is-astra">
                <span className="dv-copilot-avatar">A</span>
                <div className="dv-copilot-thinking"><span /><span /><span /></div>
              </div>
            )}
          </div>
        )}

        {/* ── Copilot bar (bottom) ── */}
        <div className="dv-copilot-bar">
          <div className="dv-copilot-bar-label">Copilot</div>
          <div className="dv-copilot-inner">
            <img src="/astra-mascot.png" alt="Astra" className="dv-mascot" />
            <div className="dv-copilot-composer">
              <AstraCopilotComposer
                value={copilotInput}
                onChange={setCopilotInput}
                onSubmit={sendCopilot}
                agents={copilotAgents}
                disabled={copilotBusy || !copilotSessionId}
                placeholder={copilotSessionId ? "Ask Astra to start a run, draft copy, or find leads…" : "Start a run to enable copilot"}
                contextLabel={copilotSession ? copilotTitle : undefined}
              />
            </div>
          </div>
        </div>

      </div>

      {launchComplete && (
        <LaunchCompleteScreen
          companyName={launchComplete.companyName}
          founderName={launchComplete.founderName}
          agentsRan={launchComplete.agentsRan}
          artifactsCreated={launchComplete.artifactsCreated}
          stackName={launchComplete.stackName}
          onComplete={() => setLaunchComplete(null)}
        />
      )}
    </>
  );
}
