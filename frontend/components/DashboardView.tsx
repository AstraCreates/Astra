"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, getCredits, AGENT_LABELS, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";
import AstraCopilotComposer, { type CopilotAgentOption } from "./AstraCopilotComposer";

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
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
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

// Comet illustration — curved sweeping arcs from a top-right star point
function HeroIllustration() {
  return (
    <svg viewBox="0 0 480 200" fill="none" preserveAspectRatio="xMaxYMid meet"
      style={{ position: "absolute", right: 0, top: 0, height: "100%", width: "55%", pointerEvents: "none", opacity: 0.9 }}>
      {/* Star point */}
      <g stroke="white" strokeLinecap="round">
        <line x1="340" y1="28" x2="340" y2="18" strokeWidth="1.5" opacity="0.9" />
        <line x1="340" y1="38" x2="340" y2="48" strokeWidth="1.5" opacity="0.9" />
        <line x1="330" y1="33" x2="320" y2="33" strokeWidth="1.5" opacity="0.9" />
        <line x1="350" y1="33" x2="360" y2="33" strokeWidth="1.5" opacity="0.9" />
        <line x1="333" y1="26" x2="326" y2="19" strokeWidth="1" opacity="0.7" />
        <line x1="347" y1="26" x2="354" y2="19" strokeWidth="1" opacity="0.7" />
        <line x1="333" y1="40" x2="326" y2="47" strokeWidth="1" opacity="0.7" />
        <line x1="347" y1="40" x2="354" y2="47" strokeWidth="1" opacity="0.7" />
        {/* Star center */}
        <circle cx="340" cy="33" r="2.5" fill="white" stroke="none" opacity="1" />
      </g>
      {/* Comet arcs — curved sweeping lines from star down-left */}
      <g fill="none" strokeLinecap="round">
        <path d="M 340 33 Q 310 80 220 160" stroke="white" strokeWidth="1.1" opacity="0.75" />
        <path d="M 340 33 Q 320 90 240 175" stroke="white" strokeWidth="1.0" opacity="0.60" />
        <path d="M 340 33 Q 330 95 265 180" stroke="white" strokeWidth="0.9" opacity="0.48" />
        <path d="M 340 33 Q 340 100 290 182" stroke="white" strokeWidth="0.8" opacity="0.38" />
        <path d="M 340 33 Q 350 100 315 182" stroke="white" strokeWidth="0.7" opacity="0.28" />
        <path d="M 340 33 Q 360 95 345 180" stroke="white" strokeWidth="0.6" opacity="0.20" />
        <path d="M 340 33 Q 295 70 190 140" stroke="white" strokeWidth="1.2" opacity="0.65" />
        <path d="M 340 33 Q 280 65 160 120" stroke="white" strokeWidth="1.0" opacity="0.45" />
        <path d="M 340 33 Q 265 60 130 105" stroke="white" strokeWidth="0.8" opacity="0.28" />
        <path d="M 340 33 Q 250 55 100 90" stroke="white" strokeWidth="0.6" opacity="0.18" />
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
  // "first-run" tab shows only today's non-done; "populated" shows active + recent done
  const [viewMode, setViewMode] = useState<"populated" | "first-run">("populated");
  const [copilot, setCopilot] = useState<{ role: string; content: string; actions?: CopilotAction[] }[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState("");
  const retriedRef = useRef(false);
  const prevStatusRef = useRef<Map<string, string>>(new Map());
  const copilotLoadedSession = useRef<string | null>(null);
  const [copilotInput, setCopilotInput] = useState("");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [launchComplete, setLaunchComplete] = useState<{ companyName: string; founderName: string; agentsRan: number; artifactsCreated: number; stackName?: string } | null>(null);
  const [credits, setCredits] = useState<number | null>(null);

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
      if (!ok) showErr("Could not delete this run on the server — it may reappear on refresh.");
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
  const regularSessions = (sessions || []).filter((s) => s.stack_id !== "custom");
  const copilotSession = (sessions || []).find((s) => s.session_id === copilotSessionId) || null;
  const copilotTitle = copilotSession ? extractGoalTitle(copilotSession.goal || "Current run") : "";
  const copilotAgents: CopilotAgentOption[] = Object.entries(AGENT_LABELS)
    .map(([id, label]) => ({ id, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  const heroSubtitle = sessions === null
    ? "Loading your workspace…"
    : running > 0
      ? `${running} run${running !== 1 ? "s" : ""} active${sessions.filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length > 0 ? ` · ${sessions.filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length} completed today` : ""}`
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

  // Status chip — solid dark pill matching reference
  const chip = (status: string) => {
    const map: Record<string, { label: string; color: string; bg: string }> = {
      running:  { label: "Running",    color: "#7CFFC6", bg: "rgba(124,255,198,.12)" },
      done:     { label: "Done",       color: "#8A93AD", bg: "rgba(138,147,173,.1)"  },
      stalled:  { label: "Needs retry",color: "#FFFFA6", bg: "rgba(255,255,166,.1)"  },
      error:    { label: "Needs retry",color: "#FFFFA6", bg: "rgba(255,255,166,.1)"  },
      killed:   { label: "Stopped",    color: "#FF6B6B", bg: "rgba(255,107,107,.1)"  },
      queued:   { label: "Queued",     color: "#7D8FFF", bg: "rgba(125,143,255,.1)"  },
    };
    const c = map[status] || { label: status, color: "#8A93AD", bg: "rgba(138,147,173,.1)" };
    return (
      <span style={{
        fontSize: 11, fontWeight: 600, color: c.color, background: c.bg,
        padding: "4px 10px", borderRadius: 6, flexShrink: 0, whiteSpace: "nowrap",
      }}>{c.label}</span>
    );
  };

  const dotColor = (status: string) => {
    const m: Record<string, string> = { running: "#7CFFC6", done: "#4B5263", stalled: "#FFFFA6", error: "#FFFFA6", killed: "#FF6B6B", queued: "#7D8FFF" };
    return m[status] || "#4B5263";
  };

  const metaLine = (s: SessionIndexEntry) => {
    const t = ago(s.created_at);
    if (s.status === "running") return `Started ${t}`;
    if (s.status === "done") return `Completed ${t}`;
    if (s.status === "stalled" || s.status === "error") return `Failed ${t} · retry available`;
    if (s.status === "queued") return `Queued`;
    return t;
  };

  return (
    <>
      <style>{`
        @keyframes mascot-float { 0%,100% { transform: translateY(0px); } 50% { transform: translateY(-4px); } }
        @keyframes sc-shimmer { 0%,100% { opacity:1; } 50% { opacity:.5; } }

        .dv-hero {
          position: relative; overflow: hidden;
          background: linear-gradient(105deg, #060c1a 0%, #0a1840 42%, #1130a0 100%);
          padding: 22px 24px 20px; border-bottom: 1px solid rgba(255,255,255,.07);
          min-height: 136px;
        }
        .dv-hero-breadcrumb { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing:.12em; color: #7cffc6; margin-bottom: 6px; }
        .dv-hero-title { font-size: 28px; font-weight: 700; color: #edf1fb; letter-spacing: -.3px; line-height: 1.15; }
        .dv-hero-sub { font-size: 11.5px; color: rgba(237,241,251,.55); margin-top: 3px; }
        .dv-hero-btns { display: flex; gap: 8px; margin-top: 14px; }
        .dv-hero-btn { min-height: 30px; padding: 0 14px; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; border: 1px solid rgba(255,255,255,.15); background: rgba(255,255,255,.07); color: #edf1fb; transition: background .12s; }
        .dv-hero-btn.primary { background: #1a44ff; border-color: #1a44ff; color: #fff; }
        .dv-hero-btn.primary:hover { background: #2a54ff; }

        .dv-body { display: flex; gap: 14px; align-items: stretch; }
        @media (max-width: 700px) { .dv-body { flex-direction: column; } .dv-goal-col { width: 100% !important; } }

        .dv-card { background: #0A0D17; border: 1px solid rgba(255,255,255,.08); border-radius: 14px; padding: 18px 20px; }
        .dv-card-label { font-size: 9.5px; letter-spacing: .08em; color: #6f7b98; font-weight: 700; text-transform: uppercase; margin-bottom: 14px; }

        .dv-run-row { display: flex; align-items: center; gap: 10px; padding: 11px 0; border-top: 1px solid rgba(255,255,255,.05); }
        .dv-run-row:first-child { border-top: none; }
        .dv-run-row:hover { cursor: pointer; }

        .dv-stat-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; margin-bottom: 14px; }
        .dv-stat { background: #070911; border: 1px solid rgba(255,255,255,.05); border-radius: 9px; padding: 10px 12px; }
        .dv-stat-label { font-size: 10px; color: #6f7b98; }
        .dv-stat-value { font-size: 22px; font-weight: 700; margin-top: 3px; color: #edf1fb; }

        .dv-today-row { display: flex; align-items: center; justify-content: space-between; }
        .dv-today-label { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #6f7b98; }
        .dv-tabs { display: flex; gap: 2px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 7px; padding: 2px; }
        .dv-tab { min-height: 24px; padding: 0 11px; border: none; border-radius: 5px; background: transparent; color: #6f7b98; font-size: 10.5px; font-weight: 600; cursor: pointer; font-family: inherit; transition: background .12s, color .12s; }
        .dv-tab.active { background: rgba(255,255,255,.1); color: #edf1fb; }

        .dv-automations { display: flex; align-items: center; gap: 0; padding: 12px 18px; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.07); border-radius: 10px; }
        .dv-automations-kicker { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #6f7b98; margin-right: 14px; flex-shrink: 0; }
        .dv-automations-msg { font-size: 12px; color: #6f7b98; flex: 1; }
        .dv-automations-msg a { color: #7d8fff; text-decoration: none; font-weight: 600; cursor: pointer; }
        .dv-manage-link { font-size: 11.5px; color: #7d8fff; font-weight: 600; background: none; border: none; cursor: pointer; font-family: inherit; flex-shrink: 0; white-space: nowrap; }

        .dv-copilot-bar { border-top: 1px solid rgba(255,255,255,.07); background: #070911; }
        .dv-copilot-kicker { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #6f7b98; padding: 10px 20px 0; }
        .dv-copilot-inner { display: flex; align-items: flex-start; gap: 10px; padding: 8px 16px 14px; }
        .dv-mascot { width: 40px; height: 40px; flex-shrink: 0; object-fit: contain; image-rendering: pixelated; animation: mascot-float 3s ease-in-out infinite; margin-top: 4px; }
        .dv-copilot-composer { flex: 1; min-width: 0; }

        .dv-copilot-thread { max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px 20px 4px; }
        .dv-bubble-row { display: flex; gap: 8px; align-items: flex-start; }
        .dv-bubble-row.founder { justify-content: flex-end; }
        .dv-avatar { width: 22px; height: 22px; border-radius: 50%; background: linear-gradient(135deg,#002EFF,#7CFFC6); color:#fff; display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:700; flex-shrink:0; }
        .dv-bubble { max-width:min(500px,85%); padding:8px 10px; border-radius:10px; background:rgba(255,255,255,.06); color:#EDF1FB; font-size:11px; line-height:1.6; white-space:pre-wrap; }
        .dv-bubble-row.founder .dv-bubble { background:#002EFF; }
        .dv-thinking { display:inline-flex; gap:4px; align-items:center; padding:8px 10px; border-radius:10px; background:rgba(255,255,255,.06); }
        .dv-thinking span { width:5px; height:5px; border-radius:50%; background:#7CFFC6; opacity:.4; animation:sc-shimmer 1s ease-in-out infinite; }
        .dv-thinking span:nth-child(2) { animation-delay:.12s; }
        .dv-thinking span:nth-child(3) { animation-delay:.24s; }

        .dv-goal-title { font-size: 15px; font-weight: 700; color: #edf1fb; line-height: 1.4; overflow-wrap: anywhere; }
        .dv-goal-credits { font-size: 11px; color: #6f7b98; margin-top: 2px; }
        .dv-goal-counts { display: flex; gap: 14px; font-size: 11px; color: #8A93AD; margin-top: 10px; }
      `}</style>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>

        {/* ── Hero ── */}
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
          <div style={{ background: "rgba(255,80,80,0.08)", borderBottom: "1px solid rgba(255,80,80,.18)", padding: "6px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#ff6b6b" }}>
            <span>✗</span><span style={{ flex: 1 }}>{toastErr}</span>
            <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0 }}>✕</button>
          </div>
        )}

        <div style={{ flex: 1, padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>

          {/* ── TODAY row ── */}
          <div className="dv-today-row">
            <div className="dv-today-label">Today</div>
            <div className="dv-tabs">
              <button className={`dv-tab${viewMode === "populated" ? " active" : ""}`} onClick={() => setViewMode("populated")}>Populated</button>
              <button className={`dv-tab${viewMode === "first-run" ? " active" : ""}`} onClick={() => setViewMode("first-run")}>First run</button>
            </div>
          </div>

          {/* ── Two columns ── */}
          <div className="dv-body">

            {/* Active Goal */}
            <div className="dv-card dv-goal-col" style={{ width: 240, flex: "none" }}>
              <div className="dv-card-label">Active goal</div>
              {(() => {
                const active = regularSessions.find(s => s.status === "running" || s.status === "stalled") || regularSessions[0] || null;
                if (!active) return (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", padding: "28px 10px", gap: 10 }}>
                    <div style={{ width: 36, height: 36, border: "1px solid rgba(255,255,255,.16)", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", transform: "rotate(45deg)" }}>
                      <div style={{ width: 10, height: 10, background: "#7D8FFF", borderRadius: 2 }} />
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>No active goals</div>
                    <div style={{ fontSize: 11, color: "#6f7b98" }}>Start a run and Astra will get to work.</div>
                  </div>
                );

                const digest = digests.get(active.session_id);
                const phasesDone = digest?.counts.phases_done ?? 0;
                const phasesTotal = digest?.counts.phases_total ?? 0;
                const phasesPending = digest?.counts.phases_pending ?? 0;
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const circumference = 138;
                const progress = phasesTotal > 0 ? phasesDone / phasesTotal : 0;
                const ringColor = isStalled ? "#FFFFA6" : "#4F7FFF";

                return (
                  <>
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="dv-goal-title">{cleanTitle}</div>
                        <div className="dv-goal-credits">
                          {phasesDone > 0 || phasesTotal > 0 ? `${phasesDone} of ${phasesTotal} tasks` : isStalled ? "Needs attention" : "Running…"}
                        </div>
                      </div>
                      <div style={{ position: "relative", width: 48, height: 48, flex: "none" }}>
                        <svg width={48} height={48} viewBox="0 0 48 48">
                          <circle cx={24} cy={24} r={22} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth={4} />
                          <circle cx={24} cy={24} r={22} fill="none" stroke={ringColor} strokeWidth={4} strokeLinecap="round"
                            strokeDasharray={circumference} strokeDashoffset={phasesTotal > 0 ? circumference * (1 - progress) : circumference * 0.8}
                            transform="rotate(-90 24 24)" style={{ transition: "stroke-dashoffset .8s ease" }} />
                        </svg>
                        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <span style={{ fontSize: 13, fontWeight: 700 }}>{isDone ? "✓" : phasesDone}</span>
                        </div>
                      </div>
                    </div>

                    <div className="dv-goal-counts">
                      <span>✓ <b style={{ color: "#EDF1FB" }}>{phasesDone}</b> done</span>
                      <span>○ <b style={{ color: "#EDF1FB" }}>{phasesPending}</b> queued</span>
                    </div>

                    <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                      <button onClick={() => router.push(`/s/${active.session_id}`)}
                        style={{ flex: 1, background: "#1a44ff", color: "#fff", border: "none", borderRadius: 8, padding: "9px 0", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: "inherit" }}>
                        ▶ Run now
                      </button>
                      <button style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "9px 12px", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: "inherit" }}>
                        Pause
                      </button>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* Recent Runs */}
            <div className="dv-card" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <div className="dv-card-label" style={{ marginBottom: 0 }}>Recent runs</div>
                <button onClick={() => setViewMode(v => v === "populated" ? "first-run" : "populated")}
                  style={{ fontSize: 11.5, color: "#7d8fff", background: "none", border: "none", cursor: "pointer", fontWeight: 600, fontFamily: "inherit" }}>
                  View all →
                </button>
              </div>

              {sessions === null ? (
                <div style={{ color: "#6f7b98", fontSize: 13 }}>Loading…</div>
              ) : error ? (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 10 }}>{error}</div>
                  <button onClick={load} style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#1a44ff", border: "none", cursor: "pointer", borderRadius: 8, fontFamily: "inherit" }}>Try again</button>
                </div>
              ) : !regularSessions.length ? (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "28px 16px", gap: 10 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>No runs yet</div>
                  <div style={{ fontSize: 11.5, color: "#6f7b98" }}>Start your first run and Astra will get to work.</div>
                  <button onClick={() => router.push("/dashboard?new=1")}
                    style={{ background: "#1a44ff", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontWeight: 600, fontSize: 12.5, cursor: "pointer", fontFamily: "inherit", marginTop: 4 }}>
                    Start first run →
                  </button>
                </div>
              ) : (
                <>
                  {/* Stats */}
                  <div className="dv-stat-grid">
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
                      <div key={label} className="dv-stat">
                        <div className="dv-stat-label">{label}</div>
                        <div className="dv-stat-value">{value}</div>
                      </div>
                    ))}
                  </div>

                  {/* Run rows */}
                  <div data-tour="dash-sessions">
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

                      const nonDone = allRows.filter(r => r.s.status !== "done");
                      const doneRows = allRows.filter(r => r.s.status === "done");
                      const visibleRows = viewMode === "first-run"
                        ? nonDone.slice(0, 5)
                        : [...nonDone, ...doneRows.slice(0, Math.max(0, 8 - nonDone.length))];

                      return (
                        <>
                          {visibleRows.map(({ s, child }) => (
                            <div key={s.session_id} className="dv-run-row"
                              style={{ marginLeft: child ? 12 : 0, width: `calc(100% - ${child ? 12 : 0}px)` }}
                              onClick={() => router.push(`/s/${s.session_id}`)}>
                              <span style={{ width: 8, height: 8, borderRadius: "50%", background: dotColor(s.status), flexShrink: 0, display: "inline-block" }} />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: "#edf1fb", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {child && <span style={{ fontSize: 9, color: "#7D8FFF", marginRight: 4 }}>↳</span>}
                                  {extractGoalTitle(s.goal || "Untitled run")}
                                </div>
                                <div style={{ fontSize: 10.5, color: "#6f7b98", marginTop: 1 }}>{metaLine(s)}</div>
                              </div>
                              {s.kind === "user" && <span style={{ fontSize: 8, fontWeight: 700, color: "#7d8fff", background: "rgba(125,143,255,.08)", border: "1px solid rgba(125,143,255,.25)", padding: "2px 5px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0 }}>User</span>}
                              {s.kind === "scheduled" && <span style={{ fontSize: 8, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,.08)", border: "1px solid rgba(245,158,11,.25)", padding: "2px 5px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0 }}>Auto</span>}
                              {chip(s.status)}
                              <button
                                title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                                disabled={deleting.has(s.session_id)}
                                onClick={e => del(e, s)}
                                onPointerDown={e => e.stopPropagation()}
                                style={{ width: pendingDel.has(s.session_id) ? "auto" : 20, height: 20, padding: pendingDel.has(s.session_id) ? "0 5px" : 0, display: "flex", alignItems: "center", justifyContent: "center", background: pendingDel.has(s.session_id) ? "rgba(255,80,80,.1)" : "transparent", border: pendingDel.has(s.session_id) ? "1px solid rgba(255,80,80,.3)" : "none", color: pendingDel.has(s.session_id) ? "#ff6b6b" : "rgba(237,241,251,.2)", cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 8 : 10, borderRadius: 5, opacity: deleting.has(s.session_id) ? 0.4 : 1, flexShrink: 0, fontWeight: 700, fontFamily: "inherit" }}
                              >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DEL?" : "✕"}</button>
                            </div>
                          ))}
                          {viewMode === "populated" && doneRows.length > Math.max(0, 8 - nonDone.length) && (
                            <button onClick={() => setViewMode("first-run")}
                              style={{ padding: "6px 0", background: "transparent", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 11, fontFamily: "inherit", marginTop: 2 }}>
                              + {doneRows.length - Math.max(0, 8 - nonDone.length)} more completed runs
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

          {/* ── Automations ── */}
          <div className="dv-automations">
            <div className="dv-automations-kicker">Automations</div>
            <div className="dv-automations-msg">
              No automations yet.{" "}
              <a onClick={() => router.push("/automations")}>Create one →</a>
            </div>
            <button className="dv-manage-link" onClick={() => router.push("/automations")}>Manage automations →</button>
          </div>

        </div>

        {/* ── Copilot thread ── */}
        {copilotOpen && copilot.length > 0 && (
          <div className="dv-copilot-thread">
            {copilot.map((message, i) => (
              <div key={i} className={`dv-bubble-row ${message.role === "founder" ? "founder" : ""}`}>
                {message.role !== "founder" && <span className="dv-avatar">A</span>}
                <div className="dv-bubble">{message.content}</div>
              </div>
            ))}
            {copilotBusy && (
              <div className="dv-bubble-row">
                <span className="dv-avatar">A</span>
                <div className="dv-thinking"><span /><span /><span /></div>
              </div>
            )}
          </div>
        )}

        {/* ── Copilot bar ── */}
        <div className="dv-copilot-bar">
          <div className="dv-copilot-kicker">Copilot</div>
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
