"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, AGENT_LABELS, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import DashboardCanvas from "./DashboardCanvas";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";

const GREETINGS = [
  "Welcome back",
  "Let's get to work",
  "Ready to build",
  "Good to see you",
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
  return raw
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeCopilotActions(actions: any): CopilotAction[] {
  if (!Array.isArray(actions)) return [];
  return actions
    .map((action: any) => {
      if (typeof action === "string") {
        return { tool: action, label: titleCaseTool(action), tone: "info" as const };
      }
      const tool = String(action?.tool || action?.name || "").trim();
      if (!tool) return null;
      return {
        tool,
        label: String(action?.label || titleCaseTool(tool)),
        detail: typeof action?.detail === "string" ? action.detail : undefined,
        tone: action?.tone === "success" || action?.tone === "warn" ? action.tone : "info",
      };
    })
    .filter(Boolean) as CopilotAction[];
}

function pickCopilotSession(sessions: SessionIndexEntry[]): SessionIndexEntry | null {
  if (!sessions.length) return null;
  return (
    sessions.find((session) => session.status === "stalled") ||
    sessions.find((session) => session.status === "running") ||
    sessions[0] ||
    null
  );
}

function StatusPill({ status }: { status: string }) {
  if (status === "running") return <span className="pill blue">● Running</span>;
  if (status === "done") return <span className="pill green">✓ Done</span>;
  if (status === "error") return <span className="pill red">✗ Error</span>;
  if (status === "killed") return <span className="pill red">✗ Stopped</span>;
  if (status === "stalled") return <span className="pill amber">⚠ Needs attention</span>;
  return <span className="pill">{status}</span>;
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [pendingDel, setPendingDel] = useState<Set<string>>(new Set());
  const [toastErr, setToastErr] = useState("");
  const showErr = (msg: string) => { setToastErr(msg); setTimeout(() => setToastErr(""), 6000); };
  const [firstName, setFirstName] = useState("");
  const [greeting, setGreeting] = useState("");
  const [digests, setDigests] = useState<Map<string, SessionDigest>>(new Map());
  const [showCompleted, setShowCompleted] = useState(false);
  const [copilot, setCopilot] = useState<{ role: string; content: string; actions?: CopilotAction[] }[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState("");
  const retriedRef = useRef(false);
  const prevStatusRef = useRef<Map<string, string>>(new Map());
  const copilotLoadedSession = useRef<string | null>(null);
  const copilotInputRef = useRef<HTMLInputElement>(null);
  const [launchComplete, setLaunchComplete] = useState<{ companyName: string; founderName: string; agentsRan: number; artifactsCreated: number; stackName?: string } | null>(null);

  // Settings preview: fire immediately on mount without needing session data.
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
    // Optimistically drop from the UI immediately so it feels instant.
    deleteLocalSession(s.session_id);
    setSessions((prev) => (prev || []).filter((x) => x.session_id !== s.session_id));
    try {
      // Kill first — a live run would otherwise keep re-persisting itself to the
      // index and reappear on the next refresh.
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
    // Don't reset sessions to null on refresh — keeps existing count visible while refetching
    try { setSessions(await listSessions(userId, 50)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setSessions((p) => p ?? []); }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  // If first load returns empty, retry once after 2s — handles the race between
  // submitGoal completing and the session index being updated after onboarding.
  useEffect(() => {
    if (sessions === null || sessions.length > 0 || retriedRef.current) return;
    retriedRef.current = true;
    const t = setTimeout(() => void load(), 2000);
    return () => clearTimeout(t);
  }, [sessions, load]);

  useEffect(() => {
    if (!userId) return;
    const refreshIfVisible = () => {
      if (document.visibilityState === "visible") {
        void load();
      }
    };
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
        for (const r of results) {
          if (r.status === "fulfilled") next.set(r.value[0], r.value[1]);
        }
        return next;
      });
    };
    void fetchAll();
    const t = setInterval(fetchAll, 15_000);
    return () => clearInterval(t);
  }, [sessions]);

  useEffect(() => {
    if (!sessions?.length) {
      setCopilotSessionId("");
      return;
    }
    const preferred = pickCopilotSession(sessions);
    if (!preferred) return;
    setCopilotSessionId((current) => {
      if (current && sessions.some((session) => session.session_id === current)) return current;
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
            return d.history.map((item: any) => ({
              role: item.role,
              content: item.content,
              actions: normalizeCopilotActions(item.actions),
            }));
          });
        }
        copilotLoadedSession.current = copilotSessionId;
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [copilotOpen, copilotSessionId]);

  useEffect(() => {
    copilotLoadedSession.current = null;
    setCopilot([]);
  }, [copilotSessionId]);

  // Detect running→done transition OR settings-triggered replay once sessions load.
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
  const stalled = (sessions || []).filter((s) => s.status === "stalled").length;
  const customSessions = (sessions || []).filter((s) => s.stack_id === "custom");
  const regularSessions = (sessions || []).filter((s) => s.stack_id !== "custom");
  const copilotSession = (sessions || []).find((session) => session.session_id === copilotSessionId) || null;
  const copilotTitle = copilotSession ? extractGoalTitle(copilotSession.goal || "Current run") : "";

  const headline = greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "";

  const sendCopilot = useCallback(async () => {
    const msg = copilotInputRef.current?.value.trim();
    if (!msg || copilotBusy || !copilotSessionId) return;
    if (copilotInputRef.current) copilotInputRef.current.value = "";
    setCopilot((current) => [...current, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const r = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      const d = await r.json();
      setCopilot((current) => [...current, { role: "copilot", content: d.reply || "(no reply)", actions: normalizeCopilotActions(d.actions) }]);
    } catch {
      setCopilot((current) => [...current, { role: "copilot", content: "Copilot error — try again." }]);
    } finally {
      setCopilotBusy(false);
    }
  }, [copilotBusy, copilotSessionId]);

  return (
    <>
      <style>{`
        @keyframes dv-fade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes sc-shimmer { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
        @keyframes sc-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        .dv-run-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 6px; cursor: pointer; transition: background .12s; }
        .dv-run-row:hover { background: rgba(255,255,255,0.04); }
        .sc-progress-track { height: 3px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-top: 6px; }
        .sc-progress-fill { height: 100%; width: 100%; border-radius: 3px; transform-origin: left; transition: transform 0.8s ease; }
        .sc-progress-indeterminate { height: 100%; width: 35%; border-radius: 3px; animation: sc-indeterminate 1.4s ease-in-out infinite; }
        .dash-copilot { position: sticky; bottom: 18px; margin: 0 18px 18px; border: 1px solid rgba(255,255,255,0.08); background: rgba(10,13,23,0.96); backdrop-filter: blur(14px); box-shadow: 0 18px 48px rgba(0,0,0,.3); border-radius: 14px; z-index: 20; overflow: hidden; }
        .dash-copilot-thread { max-height: 240px; overflow-y: auto; padding: 12px 12px 0; display: flex; flex-direction: column; gap: 8px; }
        .dash-copilot-row { display: flex; gap: 8px; align-items: flex-start; }
        .dash-copilot-row.is-founder { justify-content: flex-end; }
        .dash-copilot-avatar { width: 22px; height: 22px; border-radius: 999px; background: linear-gradient(135deg, #002EFF, #7CFFC6); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; }
        .dash-copilot-bubble { max-width: min(600px,100%); padding: 8px 10px; border-radius: 10px; background: rgba(255,255,255,0.06); color: #EDF1FB; font-size: 11px; line-height: 1.6; white-space: pre-wrap; }
        .dash-copilot-row.is-founder .dash-copilot-bubble { background: #002EFF; }
        .dash-copilot-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
        .dash-copilot-action { padding: 6px 8px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.04); }
        .dash-copilot-action.is-success { border-color: rgba(16,185,129,.3); }
        .dash-copilot-action.is-warn { border-color: rgba(245,158,11,.3); }
        .dash-copilot-action-label { font-size: 10px; font-weight: 600; color: #EDF1FB; }
        .dash-copilot-action-detail { font-size: 9px; color: rgba(237,241,251,0.5); margin-top: 2px; line-height: 1.5; }
        .dash-copilot-thinking { display: inline-flex; gap: 4px; align-items: center; padding: 8px 10px; border-radius: 10px; background: rgba(255,255,255,0.06); }
        .dash-copilot-thinking span { width: 5px; height: 5px; border-radius: 999px; background: #7CFFC6; opacity: .4; animation: sc-shimmer 1s ease-in-out infinite; }
        .dash-copilot-thinking span:nth-child(2) { animation-delay: .12s; }
        .dash-copilot-thinking span:nth-child(3) { animation-delay: .24s; }
        .dash-copilot-bar { display: flex; align-items: center; gap: 8px; padding: 10px 12px 12px; }
        .dash-copilot-ctx { font-size: 10px; color: rgba(237,241,251,0.4); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; flex-shrink: 1; }
        .dash-copilot-input { flex: 1; min-width: 0; height: 34px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #EDF1FB; padding: 0 11px; font-size: 11px; outline: none; font-family: inherit; }
        .dash-copilot-input::placeholder { color: rgba(237,241,251,0.3); }
        .dash-copilot-input:focus { border-color: rgba(0,46,255,0.5); }
        .dash-copilot-btn { height: 34px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #EDF1FB; padding: 0 11px; cursor: pointer; font-size: 11px; font-weight: 600; white-space: nowrap; font-family: inherit; }
        .dash-copilot-btn.primary { background: #002EFF; border-color: #002EFF; width: 34px; padding: 0; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .dash-copilot-btn:disabled { opacity: 0.4; cursor: default; }
        @media (max-width: 700px) { .dv-body { flex-direction: column !important; } .dv-goal-col { flex: none !important; width: 100% !important; } }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>

        {/* ── Hero: lineart variant ── */}
        <div style={{ position: "relative", height: 156, overflow: "hidden", background: "#0a1b6b" }}>
          {/* Blueprint grid lines */}
          <div style={{
            position: "absolute", inset: 0,
            backgroundImage: "linear-gradient(rgba(124,255,198,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(124,255,198,0.07) 1px, transparent 1px)",
            backgroundSize: "32px 32px",
            maskImage: "linear-gradient(90deg, transparent 25%, rgba(0,0,0,0.5) 55%, rgba(0,0,0,1) 100%)",
            WebkitMaskImage: "linear-gradient(90deg, transparent 25%, rgba(0,0,0,0.5) 55%, rgba(0,0,0,1) 100%)",
          }} />
          {/* Left fade */}
          <div style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: "60%", background: "linear-gradient(90deg, #0a1b6b 50%, transparent)", pointerEvents: "none" }} />
          {/* Content */}
          <div style={{ position: "relative", zIndex: 2, padding: "22px 18px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", gap: 5 }}>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".15em", color: "rgba(255,255,255,0.3)", textTransform: "uppercase" }}>Dashboard</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#fff", lineHeight: 1.1, letterSpacing: "-0.02em" }}>{headline || "Welcome back."}</div>
            {sessions !== null && (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {running > 0 && <span style={{ fontSize: 11, color: "#7CFFC6", fontWeight: 600 }}>● {running} running</span>}
                {stalled > 0 && <span style={{ fontSize: 11, color: "#FFFFA6", fontWeight: 600 }}>⚠ {stalled} stalled</span>}
                {running === 0 && stalled === 0 && sessions.length > 0 && <span style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>{sessions.length} run{sessions.length !== 1 ? "s" : ""} total</span>}
              </div>
            )}
            <div style={{ display: "flex", gap: 7, marginTop: 3 }}>
              <button
                data-tour="dash-new-run"
                onClick={() => router.push("/dashboard?new=1")}
                style={{ padding: "7px 16px", fontSize: 11, fontWeight: 600, color: "#002EFF", background: "#fff", border: "none", cursor: "pointer", borderRadius: 7 }}
              >+ New run</button>
              <button
                onClick={load}
                style={{ padding: "7px 14px", fontSize: 11, fontWeight: 500, color: "rgba(255,255,255,0.7)", background: "rgba(255,255,255,0.1)", border: "1px solid rgba(255,255,255,0.18)", cursor: "pointer", borderRadius: 7 }}
              >Refresh</button>
            </div>
          </div>
        </div>

        {toastErr && (
          <div style={{ background: "rgba(255,80,80,0.08)", borderBottom: "1px solid rgba(255,80,80,0.18)", padding: "6px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#ff6b6b" }}>
            <span>✗</span>
            <span style={{ flex: 1 }}>{toastErr}</span>
            <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0, lineHeight: 1 }}>✕</button>
          </div>
        )}

        {/* ── Body: two-column layout ── */}
        <div className="dv-body" style={{ display: "flex", gap: 16, padding: "18px", alignItems: "flex-start" }}>

          {/* ── Active Goal card (330px) ── */}
          <div className="dv-goal-col" style={{ flex: "0 0 330px", minWidth: 0 }}>
            <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, padding: "16px" }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".12em", color: "rgba(237,241,251,0.3)", textTransform: "uppercase", marginBottom: 14 }}>Active Goal</div>

              {(() => {
                const active = regularSessions.find(s => s.status === "running" || s.status === "stalled") || regularSessions[0] || null;
                if (!active) {
                  return (
                    <div style={{ textAlign: "center", padding: "28px 0" }}>
                      <div style={{ fontSize: 28, opacity: 0.1, marginBottom: 12 }}>◈</div>
                      <div style={{ fontSize: 12, color: "rgba(237,241,251,0.3)", marginBottom: 14 }}>No active runs</div>
                      <button onClick={() => router.push("/dashboard?new=1")} style={{ padding: "8px 18px", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 7 }}>
                        Start first run →
                      </button>
                    </div>
                  );
                }

                const digest = digests.get(active.session_id);
                const phasesDone = digest?.counts.phases_done ?? 0;
                const phasesTotal = digest?.counts.phases_total ?? 0;
                const progress = phasesTotal > 0 ? phasesDone / phasesTotal : 0;
                const circumference = 157;
                const dashOffset = circumference * (1 - progress);
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isRunning = active.status === "running";
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const currentAgents = (digest?.running_agents ?? []).map((a: string) => AGENT_LABELS[a as keyof typeof AGENT_LABELS] ?? a);
                const accentColor = isStalled ? "#FFFFA6" : isDone ? "#7CFFC6" : "#7CFFC6";

                return (
                  <div>
                    <div style={{ display: "flex", gap: 14, alignItems: "flex-start", marginBottom: 14 }}>
                      {/* SVG donut ring */}
                      <svg width={58} height={58} viewBox="0 0 58 58" style={{ flexShrink: 0 }}>
                        <circle cx={29} cy={29} r={25} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={5} />
                        <circle cx={29} cy={29} r={25} fill="none"
                          stroke={accentColor}
                          strokeWidth={5}
                          strokeLinecap="round"
                          strokeDasharray={circumference}
                          strokeDashoffset={phasesTotal > 0 ? dashOffset : circumference * 0.83}
                          transform="rotate(-90 29 29)"
                          style={{ transition: "stroke-dashoffset 0.8s ease" }}
                        />
                        <text x={29} y={33} textAnchor="middle" fill={accentColor} fontSize={10} fontWeight={700} fontFamily="inherit">
                          {isDone ? "✓" : phasesTotal > 0 ? `${Math.round(progress * 100)}%` : "…"}
                        </text>
                      </svg>

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "#EDF1FB", lineHeight: 1.45, marginBottom: 6, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                          {cleanTitle}
                        </div>
                        <div style={{ display: "flex", gap: 10, fontSize: 10, color: "rgba(237,241,251,0.4)" }}>
                          {phasesDone > 0 && <span style={{ color: "#7CFFC6" }}>✓ {phasesDone} done</span>}
                          {(digest?.counts.phases_pending ?? 0) > 0 && <span>{digest?.counts.phases_pending} queued</span>}
                          {(digest?.counts.phases_total ?? 0) === 0 && isRunning && <span style={{ color: "#7D8FFF" }}>Initializing…</span>}
                        </div>
                      </div>
                    </div>

                    {isRunning && currentAgents.length > 0 && (
                      <div style={{ fontSize: 10, color: "#7CFFC6", marginBottom: 12, display: "flex", alignItems: "center", gap: 5 }}>
                        <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#7CFFC6", flexShrink: 0, animation: "sc-shimmer 1.5s ease-in-out infinite" }} />
                        {currentAgents.join(" · ")}
                      </div>
                    )}
                    {isStalled && (
                      <div style={{ fontSize: 10, color: "#FFFFA6", marginBottom: 12 }}>⚠ Needs your attention — approval may be required.</div>
                    )}

                    <div style={{ display: "flex", gap: 7 }}>
                      <button
                        onClick={() => router.push(`/s/${active.session_id}`)}
                        style={{ flex: 1, padding: "8px 0", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 7 }}
                      >{isStalled ? "Review →" : "View run →"}</button>
                      <button
                        onClick={() => router.push("/dashboard?new=1")}
                        style={{ padding: "8px 12px", fontSize: 11, fontWeight: 500, color: "rgba(237,241,251,0.55)", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.07)", cursor: "pointer", borderRadius: 7 }}
                      >+ New</button>
                    </div>

                    {phasesTotal > 0 && (
                      <div style={{ marginTop: 12, height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: "100%", background: accentColor, borderRadius: 3, transformOrigin: "left", transform: `scaleX(${progress})`, transition: "transform 0.8s ease" }} />
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>

          {/* ── Recent Runs (flex:1) ── */}
          <div style={{ flex: 1, minWidth: 0 }}>

            {/* 4-stat grid */}
            {sessions !== null && sessions.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 16 }}>
                {[
                  { label: "Active", value: running > 0 ? String(running) : "0", accent: running > 0 ? "#7CFFC6" : undefined },
                  { label: "Done today", value: String((sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length) },
                  { label: "Total runs", value: String(sessions.length) },
                  {
                    label: "Success rate",
                    value: (() => {
                      const done = sessions.filter(s => s.status === "done").length;
                      const failed = sessions.filter(s => s.status === "error" || s.status === "killed").length;
                      const total = done + failed;
                      return total > 0 ? `${Math.round((done / total) * 100)}%` : "—";
                    })(),
                  },
                ].map(({ label, value, accent }) => (
                  <div key={label} style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, padding: "11px 13px" }}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".1em", textTransform: "uppercase", color: "rgba(237,241,251,0.3)", marginBottom: 5 }}>{label}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: accent || "#EDF1FB", lineHeight: 1 }}>{value}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Stalled banner */}
            {stalled > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", border: "1px solid rgba(255,255,166,0.2)", background: "rgba(255,255,166,0.04)", borderRadius: 8, marginBottom: 12, fontSize: 11, color: "#FFFFA6" }}>
                <span>⚠</span>
                <span style={{ flex: 1 }}>
                  {stalled} run{stalled > 1 ? "s need" : " needs"} your attention.{" "}
                  <button style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: 600, textDecoration: "underline", padding: 0, fontSize: 11 }}
                    onClick={() => { const first = (sessions || []).find(s => s.status === "stalled"); if (first) router.push(`/s/${first.session_id}`); }}>
                    Review →
                  </button>
                </span>
              </div>
            )}

            {/* Run list header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".12em", textTransform: "uppercase", color: "rgba(237,241,251,0.3)" }}>Recent runs</div>
              {regularSessions.length > 0 && <span style={{ fontSize: 9, color: "rgba(237,241,251,0.2)" }}>{regularSessions.length} total</span>}
            </div>

            {/* Run list */}
            {sessions === null ? (
              <div style={{ color: "rgba(237,241,251,0.3)", fontSize: 11, padding: "10px 0" }}>Loading…</div>
            ) : error ? (
              <div style={{ padding: "20px 0", textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "rgba(237,241,251,0.3)", marginBottom: 10 }}>{error}</div>
                <button style={{ padding: "7px 14px", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 7 }} onClick={load}>Try again</button>
              </div>
            ) : !regularSessions.length ? (
              <div style={{ padding: "28px 0", textAlign: "center" }}>
                <div style={{ fontSize: 28, opacity: 0.08, marginBottom: 10 }}>◈</div>
                <div style={{ fontSize: 12, color: "rgba(237,241,251,0.3)", marginBottom: 14 }}>No runs yet</div>
                <button style={{ padding: "8px 18px", fontSize: 11, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 7 }} onClick={() => router.push("/dashboard?new=1")}>
                  Start first run →
                </button>
              </div>
            ) : (
              <div data-tour="dash-sessions" style={{ display: "flex", flexDirection: "column", gap: 1 }}>
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

                  const dotColor = (status: string) => {
                    if (status === "running") return "#7CFFC6";
                    if (status === "done") return "#8A93AD";
                    if (status === "stalled") return "#FFFFA6";
                    if (status === "error" || status === "killed") return "#FF6B6B";
                    return "#8A93AD";
                  };

                  const chip = (status: string) => {
                    const map: Record<string, { label: string; color: string; bg: string }> = {
                      running: { label: "Running", color: "#7CFFC6", bg: "rgba(124,255,198,0.1)" },
                      done: { label: "Done", color: "#8A93AD", bg: "rgba(138,147,173,0.07)" },
                      stalled: { label: "Attention", color: "#FFFFA6", bg: "rgba(255,255,166,0.07)" },
                      error: { label: "Error", color: "#FF6B6B", bg: "rgba(255,107,107,0.07)" },
                      killed: { label: "Stopped", color: "#FF6B6B", bg: "rgba(255,107,107,0.07)" },
                    };
                    const c = map[status] || { label: status, color: "#8A93AD", bg: "rgba(138,147,173,0.07)" };
                    return <span style={{ fontSize: 9, fontWeight: 600, color: c.color, background: c.bg, padding: "2px 7px", borderRadius: 20, letterSpacing: ".04em", flexShrink: 0 }}>{c.label}</span>;
                  };

                  const doneCount = allRows.filter(r => r.s.status === "done").length;
                  const nonDone = allRows.filter(r => r.s.status !== "done");
                  const doneRows = allRows.filter(r => r.s.status === "done");
                  const visibleRows = showCompleted ? allRows : [...nonDone, ...doneRows.slice(0, 3)];
                  const hiddenDone = !showCompleted && doneCount > 3;

                  return (
                    <>
                      {visibleRows.map(({ s, child }) => (
                        <div
                          key={s.session_id}
                          className="dv-run-row"
                          style={{ marginLeft: child ? 12 : 0 }}
                          onClick={() => router.push(`/s/${s.session_id}`)}
                        >
                          <span style={{ width: 7, height: 7, borderRadius: "50%", background: dotColor(s.status), flexShrink: 0, animation: s.status === "running" ? "sc-shimmer 1.5s ease-in-out infinite" : undefined }} />
                          <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: "#EDF1FB", fontWeight: s.status === "running" ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {child && <span style={{ fontSize: 9, color: "#7D8FFF", marginRight: 5, fontWeight: 700 }}>↳</span>}
                            {extractGoalTitle(s.goal || "Untitled run")}
                          </span>
                          {chip(s.status)}
                          <span style={{ fontSize: 10, color: "rgba(237,241,251,0.22)", flexShrink: 0 }}>{ago(s.created_at)}</span>
                          <button
                            title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                            disabled={deleting.has(s.session_id)}
                            onClick={e => del(e, s)}
                            onPointerDown={e => e.stopPropagation()}
                            style={{
                              width: pendingDel.has(s.session_id) ? "auto" : 20, height: 20,
                              padding: pendingDel.has(s.session_id) ? "0 5px" : 0,
                              display: "flex", alignItems: "center", justifyContent: "center",
                              background: pendingDel.has(s.session_id) ? "rgba(255,80,80,0.1)" : "transparent",
                              border: pendingDel.has(s.session_id) ? "1px solid rgba(255,80,80,0.3)" : "none",
                              color: pendingDel.has(s.session_id) ? "#ff6b6b" : "rgba(237,241,251,0.18)",
                              cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 8 : 10, borderRadius: 5,
                              opacity: deleting.has(s.session_id) ? 0.4 : 1, flexShrink: 0, fontWeight: 700, whiteSpace: "nowrap",
                            }}
                          >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DEL?" : "✕"}</button>
                        </div>
                      ))}
                      {hiddenDone && (
                        <button
                          onClick={() => setShowCompleted(true)}
                          style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", padding: "7px 10px", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: 6, cursor: "pointer", color: "rgba(237,241,251,0.35)", fontSize: 10, fontWeight: 600, marginTop: 4 }}
                        >
                          <span style={{ fontSize: 9 }}>▶</span> Show {doneCount} completed runs
                        </button>
                      )}
                      {showCompleted && doneCount > 0 && (
                        <button
                          onClick={() => setShowCompleted(false)}
                          style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", background: "transparent", border: "none", cursor: "pointer", color: "rgba(237,241,251,0.25)", fontSize: 10, marginTop: 2 }}
                        >
                          Hide completed
                        </button>
                      )}
                    </>
                  );
                })()}
              </div>
            )}
          </div>
        </div>

        {/* ── Custom agent runs banner ── */}
        <div style={{ padding: "0 18px 16px" }}>
          <div style={{ background: "#0A0D17", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, padding: "12px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: customSessions.length > 0 ? 10 : 0 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: ".12em", textTransform: "uppercase", color: "rgba(237,241,251,0.3)" }}>
                Custom agent runs{customSessions.length > 0 ? ` · ${customSessions.length}` : ""}
              </div>
              <button onClick={() => router.push("/agents")} style={{ fontSize: 11, color: "#002EFF", background: "none", border: "none", cursor: "pointer", fontWeight: 600 }}>
                Manage agents →
              </button>
            </div>

            {customSessions.length === 0 ? (
              <div style={{ fontSize: 11, color: "rgba(237,241,251,0.25)" }}>
                No custom agent runs yet.{" "}
                <button onClick={() => router.push("/agents")} style={{ background: "none", border: "none", color: "#002EFF", cursor: "pointer", padding: 0, fontWeight: 600, fontSize: 11 }}>
                  Create one →
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                {customSessions.slice(0, 8).map(s => {
                  const title = s.company_name || extractGoalTitle(s.goal || "Custom agent run");
                  return (
                    <div key={s.session_id} className="dv-run-row" onClick={() => router.push(`/s/${s.session_id}`)}>
                      <span style={{ width: 7, height: 7, borderRadius: "50%", background: s.status === "running" ? "#7CFFC6" : s.status === "done" ? "#8A93AD" : "#FFFFA6", flexShrink: 0 }} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: "#EDF1FB", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</span>
                      <span style={{ fontSize: 10, color: "rgba(237,241,251,0.22)" }}>{ago(s.created_at)}</span>
                      <button onClick={e => del(e, s)} onPointerDown={e => e.stopPropagation()} style={{ background: "transparent", border: "none", color: "rgba(237,241,251,0.18)", cursor: "pointer", fontSize: 10, padding: "0 2px" }}>✕</button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* DashboardCanvas */}
        <div style={{ padding: "0 18px 40px" }}>
          <DashboardCanvas founderId={userId} />
        </div>

        {/* ── Copilot ── */}
        <div className="dash-copilot">
          {copilotOpen && (
            <div className="dash-copilot-thread">
              {copilot.length === 0 && (
                <div className="dash-copilot-bubble">
                  {copilotSession
                    ? `Ask Astra from the dashboard. Copilot is attached to "${copilotTitle}" and can inspect run state, approvals, deployment issues, company brain context, and steer the active agents from here.`
                    : "Start a run to activate dashboard copilot context."}
                </div>
              )}
              {copilot.map((message, index) => (
                <div key={index} className={`dash-copilot-row ${message.role === "founder" ? "is-founder" : "is-astra"}`}>
                  {message.role !== "founder" && <span className="dash-copilot-avatar">A</span>}
                  <div className="dash-copilot-bubble">
                    {message.content}
                    {message.actions && message.actions.length > 0 && (
                      <div className="dash-copilot-actions" aria-label="Copilot actions">
                        {message.actions.map((action, actionIndex) => (
                          <div key={`${action.tool}-${actionIndex}`} className={`dash-copilot-action is-${action.tone || "info"}`}>
                            <div className="dash-copilot-action-label">{action.label}</div>
                            {action.detail && <div className="dash-copilot-action-detail">{action.detail}</div>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {copilotBusy && (
                <div className="dash-copilot-row is-astra">
                  <span className="dash-copilot-avatar">A</span>
                  <div className="dash-copilot-thinking"><span /><span /><span /></div>
                </div>
              )}
            </div>
          )}
          <div className="dash-copilot-bar">
            <div
              style={{ width: 26, height: 26, borderRadius: "50%", background: "linear-gradient(135deg, #002EFF, #7CFFC6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0, cursor: "pointer" }}
              onClick={() => setCopilotOpen(v => !v)}
            >A</div>
            {copilotSession && <span className="dash-copilot-ctx">{copilotTitle}</span>}
            <input
              ref={copilotInputRef}
              className="dash-copilot-input"
              placeholder={copilotSession ? 'Ask Astra — "what needs attention?"' : "Start a run to enable copilot"}
              disabled={!copilotSession || copilotBusy}
              onFocus={() => setCopilotOpen(true)}
              onKeyDown={event => {
                if (event.key === "Enter") { event.preventDefault(); void sendCopilot(); }
              }}
            />
            <button
              className="dash-copilot-btn primary"
              disabled={!copilotSession || copilotBusy}
              onClick={() => { setCopilotOpen(true); void sendCopilot(); }}
              title="Send"
            >
              <svg width={13} height={13} viewBox="0 0 13 13" fill="none">
                <path d="M6.5 1.5L6.5 11.5M6.5 1.5L2.5 5.5M6.5 1.5L10.5 5.5" stroke="white" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
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
