"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import SessionView from "@/components/SessionView";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";
import {
  apiFetch,
  deleteSessionRemote,
  getCredits,
  getSessionDigest,
  killSession,
  listSessions,
  type SessionDigest,
  type SessionIndexEntry,
} from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";

const GREETINGS = [
  "Welcome back",
  "Astra is ready",
  "Let’s keep building",
  "Your workspace is ready",
  "Let’s move this forward",
];

type CopilotAction = { tool: string; label: string; detail?: string; tone?: "info" | "success" | "warn" };
type CopilotMessage = { role: string; content: string; actions?: CopilotAction[] };
type RawCopilotAction = string | { tool?: string; name?: string; label?: string; detail?: string; tone?: string };
type RawCopilotHistoryItem = { role: string; content: string; actions?: RawCopilotAction[] };

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

function titleCaseTool(raw: string): string {
  return raw
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeCopilotActions(actions: RawCopilotAction[] | undefined): CopilotAction[] {
  if (!Array.isArray(actions)) return [];
  return actions
    .map((action) => {
      if (typeof action === "string") return { tool: action, label: titleCaseTool(action), tone: "info" as const };
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

function pickWorkspaceSession(sessions: SessionIndexEntry[]): SessionIndexEntry | null {
  return (
    sessions.find((session) => session.status === "stalled") ||
    sessions.find((session) => session.status === "running") ||
    sessions[0] ||
    null
  );
}

function shouldEscalateToMonitor(session: SessionIndexEntry | null, digest?: SessionDigest | null): boolean {
  if (!session || session.status !== "running" || !digest) return false;
  const counts = digest.counts;
  const manyAgents = counts.running_agents >= 3 || counts.planned_agents >= 6;
  const manyApprovals = counts.pending_approvals >= 2 || counts.triggered_approvals >= 2;
  const heavyArtifacts = counts.ready_artifacts >= 6 || counts.outcome_events >= 8;
  const manyErrors = counts.errors >= 2;
  return manyAgents || manyApprovals || heavyArtifacts || manyErrors;
}

function buildWorkspaceStatus(session: SessionIndexEntry | null, digest?: SessionDigest | null): string {
  if (!session) return "Start a run and Astra will build the plan, coordinate agents, and keep the work moving.";
  if (session.status === "stalled") return "Astra needs your attention before this run can continue.";
  if (session.status === "done") return "This run is complete. Review the outputs, then prompt Astra for the next step.";
  if (!digest) return "Astra is loading the live state for your active run.";
  if (digest.approval_focus.length > 0) return digest.approval_focus[0]?.title || "Astra is waiting on an approval.";
  if (digest.next_actions.length > 0) return digest.next_actions[0] || "Astra is moving the run forward.";
  if (digest.running_agents.length > 0) return `${digest.running_agents[0].replace(/_/g, " ")} is actively working.`;
  return digest.summary || "Astra is coordinating the active run.";
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [digests, setDigests] = useState<Map<string, SessionDigest>>(new Map());
  const [error, setError] = useState("");
  const [toastErr, setToastErr] = useState("");
  const [credits, setCredits] = useState<number | null>(null);
  const [firstName] = useState(() => {
    if (typeof window === "undefined") return "";
    const fullName = localStorage.getItem("astra_onboarding_name") || "";
    return fullName.split(" ")[0] || fullName;
  });
  const [greeting] = useState(() => GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
  const [copilot, setCopilot] = useState<CopilotMessage[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState<string | null>(null);
  const [manualMonitorSessionId, setManualMonitorSessionId] = useState("");
  const [showArchive, setShowArchive] = useState(false);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [pendingDel, setPendingDel] = useState<Set<string>>(new Set());
  const [launchComplete, setLaunchComplete] = useState<{ companyName: string; founderName: string; agentsRan: number; artifactsCreated: number; stackName?: string } | null>(() => {
    if (!consumePreviewSignal()) return null;
    const company = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_company") || localStorage.getItem("astra_onboarding_name") || "") : "";
    const fullName = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_name") || "") : "";
    const founder = fullName.split(" ")[0] || fullName;
    return { companyName: company, founderName: founder, agentsRan: 0, artifactsCreated: 0 };
  });
  const [todayStart] = useState(() => {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    return now.getTime();
  });
  const retriedRef = useRef(false);
  const prevStatusRef = useRef<Map<string, string>>(new Map());
  const copilotLoadedSession = useRef<string | null>(null);
  const copilotInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setError("");
    try {
      setSessions(await listSessions(userId, 50));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSessions((prev) => prev ?? []);
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) return;
    getCredits(userId).then((balance) => setCredits(balance.balance)).catch(() => {});
  }, [userId]);

  useEffect(() => {
    const t = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(t);
  }, [load]);

  useEffect(() => {
    if (sessions === null || sessions.length > 0 || retriedRef.current) return;
    retriedRef.current = true;
    const t = setTimeout(() => void load(), 2000);
    return () => clearTimeout(t);
  }, [sessions, load]);

  useEffect(() => {
    if (!userId) return;
    const refreshIfVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    const interval = window.setInterval(refreshIfVisible, 15000);
    window.addEventListener("focus", refreshIfVisible);
    document.addEventListener("visibilitychange", refreshIfVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshIfVisible);
      document.removeEventListener("visibilitychange", refreshIfVisible);
    };
  }, [load, userId]);

  useEffect(() => {
    if (!sessions) return;
    const running = sessions.filter((s) => s.status === "running" || s.status === "stalled");
    if (!running.length) return;
    const fetchAll = async () => {
      const results = await Promise.allSettled(
        running.map((session) => getSessionDigest(session.session_id).then((digest) => [session.session_id, digest] as [string, SessionDigest])),
      );
      setDigests((prev) => {
        const next = new Map(prev);
        for (const result of results) {
          if (result.status === "fulfilled") next.set(result.value[0], result.value[1]);
        }
        return next;
      });
    };
    void fetchAll();
    const t = window.setInterval(fetchAll, 15000);
    return () => window.clearInterval(t);
  }, [sessions]);

  const regularSessions = useMemo(() => (sessions || []).filter((session) => session.stack_id !== "custom"), [sessions]);
  const effectiveCopilotSessionId = useMemo(() => {
    if (!regularSessions.length) return "";
    if (copilotSessionId && regularSessions.some((session) => session.session_id === copilotSessionId)) return copilotSessionId;
    return pickWorkspaceSession(regularSessions)?.session_id || "";
  }, [copilotSessionId, regularSessions]);

  useEffect(() => {
    if (!effectiveCopilotSessionId || copilotLoadedSession.current === effectiveCopilotSessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${effectiveCopilotSessionId}`);
        const data = await response.json();
        if (cancelled) return;
        if (Array.isArray(data.history)) {
          setCopilot(data.history.map((item: RawCopilotHistoryItem) => ({
            role: item.role,
            content: item.content,
            actions: normalizeCopilotActions(item.actions),
          })));
        } else {
          setCopilot([]);
        }
        copilotLoadedSession.current = effectiveCopilotSessionId;
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [effectiveCopilotSessionId]);

  useEffect(() => {
    if (!sessions) return;
    const prev = prevStatusRef.current;
    const isFirstLoad = prev.size === 0;
    const canShow = shouldShowLaunchComplete();
    let triggered = false;
    for (const session of sessions) {
      if (session.stack_id === "custom") continue;
      const wasRunning = prev.get(session.session_id) === "running";
      const nowDone = session.status === "done";
      if (canShow && !triggered && ((wasRunning && nowDone) || (isFirstLoad && nowDone))) {
        const digest = digests.get(session.session_id);
        setLaunchComplete({
          companyName: session.company_name || "",
          founderName: firstName,
          agentsRan: digest?.counts.done_agents ?? 0,
          artifactsCreated: digest?.counts.ready_artifacts ?? 0,
          stackName: session.stack_id ? session.stack_id.replace(/_/g, " ") : undefined,
        });
        markLaunchCompleteShown();
        triggered = true;
      }
      prev.set(session.session_id, session.status);
    }
  }, [digests, firstName, sessions]);

  const activeSessions = useMemo(() => regularSessions.filter((session) => session.status === "running" || session.status === "stalled"), [regularSessions]);
  const completedSessions = useMemo(() => regularSessions.filter((session) => session.status === "done"), [regularSessions]);
  const selectedSession = useMemo(() => regularSessions.find((session) => session.session_id === effectiveCopilotSessionId) || pickWorkspaceSession(regularSessions), [effectiveCopilotSessionId, regularSessions]);
  const selectedDigest = selectedSession ? digests.get(selectedSession.session_id) || null : null;
  const suggestedMonitor = shouldEscalateToMonitor(selectedSession || null, selectedDigest || null);
  const headline = greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "Workspace";
  const completedToday = completedSessions.filter((session) => session.created_at && new Date(session.created_at).getTime() >= todayStart).length;
  const runningCount = activeSessions.filter((session) => session.status === "running").length;
  const autoMonitorSessionId = suggestedMonitor && selectedSession ? selectedSession.session_id : "";
  const monitorSessionId = manualMonitorSessionId || autoMonitorSessionId;
  const monitorSession = monitorSessionId ? regularSessions.find((session) => session.session_id === monitorSessionId) || null : null;
  const showCompleted = showArchive;
  const setShowCompleted = setShowArchive;
  const copilotSession = selectedSession;
  const copilotTitle = copilotSession ? extractGoalTitle(copilotSession.goal || "Current run") : "";

  const showErr = (message: string) => {
    setToastErr(message);
    window.setTimeout(() => setToastErr(""), 6000);
  };

  const sendCopilot = useCallback(async () => {
    const msg = copilotInputRef.current?.value.trim();
    if (!msg || copilotBusy || !effectiveCopilotSessionId) return;
    if (copilotInputRef.current) copilotInputRef.current.value = "";
    setCopilot((current) => [...current, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const response = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${effectiveCopilotSessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      const data = await response.json();
      setCopilot((current) => [...current, { role: "copilot", content: data.reply || "(no reply)", actions: normalizeCopilotActions(data.actions) }]);
    } catch {
      setCopilot((current) => [...current, { role: "copilot", content: "Copilot error — try again." }]);
    } finally {
      setCopilotBusy(false);
    }
  }, [copilotBusy, effectiveCopilotSessionId]);

  const confirmDelete = useCallback(async (e: React.MouseEvent, session: SessionIndexEntry) => {
    e.stopPropagation();
    e.preventDefault();
    if (!pendingDel.has(session.session_id)) {
      setPendingDel((prev) => new Set(prev).add(session.session_id));
      window.setTimeout(() => setPendingDel((prev) => {
        const next = new Set(prev);
        next.delete(session.session_id);
        return next;
      }), 3000);
      return;
    }
    setPendingDel((prev) => {
      const next = new Set(prev);
      next.delete(session.session_id);
      return next;
    });
    setDeleting((prev) => new Set(prev).add(session.session_id));
    deleteLocalSession(session.session_id);
    setSessions((prev) => (prev || []).filter((item) => item.session_id !== session.session_id));
    try {
      await killSession(session.session_id).catch(() => {});
      const ok = await deleteSessionRemote(session.session_id);
      if (!ok) showErr("Could not delete this run on the server — it may reappear on refresh.");
    } finally {
      setDeleting((prev) => {
        const next = new Set(prev);
        next.delete(session.session_id);
        return next;
      });
    }
  }, [pendingDel]);

  if (monitorSession) {
    const auto = !manualMonitorSessionId;
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "#060912" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, padding: "12px 18px", borderBottom: "1px solid rgba(255,255,255,.08)", background: "rgba(8,11,19,.96)" }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: ".09em", textTransform: "uppercase", color: "#7E8BA6", fontWeight: 700 }}>
              {auto ? "Workspace + auto-switched monitor" : "Workspace + focused monitor"}
            </div>
            <div style={{ fontSize: 15, color: "#F4F7FF", fontWeight: 650, marginTop: 4, maxWidth: 900, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {monitorSession.company_name || extractGoalTitle(monitorSession.goal || "Active run")}
            </div>
            <div style={{ fontSize: 12, color: "#9AA6BF", marginTop: 4 }}>
              {auto ? "Astra switched here because this run got busy enough to need the deeper monitor view." : "Deep inspection mode is open for this run."}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button
              onClick={() => router.push("/dashboard?new=1")}
              style={{ borderRadius: 10, border: "1px solid rgba(255,255,255,.12)", background: "rgba(255,255,255,.03)", color: "#E6EBF7", padding: "10px 14px", fontWeight: 600, cursor: "pointer" }}
            >
              Start another run
            </button>
            <button
              onClick={() => {
                setManualMonitorSessionId("");
              }}
              style={{ borderRadius: 10, border: "1px solid rgba(0,46,255,.28)", background: "#002EFF", color: "#fff", padding: "10px 16px", fontWeight: 700, cursor: "pointer" }}
            >
              Return to workspace
            </button>
          </div>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <SessionView key={monitorSession.session_id} sessionId={monitorSession.session_id} />
        </div>
      </div>
    );
  }

  return (
    <>
      <style>{`
        @keyframes sc-shimmer { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
        @keyframes sc-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        .dv-run-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-top: 1px solid rgba(255,255,255,.06); cursor: pointer; transition: background .12s; }
        .dv-run-row:first-child { border-top: none; }
        .dv-run-row:hover { background: rgba(255,255,255,0.03); }
        .sc-progress-track { height: 3px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-top: 6px; }
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
        @media (max-width: 700px) { .dv-body { flex-direction: column !important; } .dv-goal-col { flex: none !important; width: 100% !important; } }
      `}</style>
      <div style={{ flex: 1, overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>
        <div style={{ position: "relative", height: 208, overflow: "hidden", background: "#0a1b6b" }}>
          <img alt="" src="/hero-lineart.png" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "50% 25%" } as React.CSSProperties} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg,rgba(5,7,14,.84) 0%,rgba(5,7,14,.48) 42%,transparent 72%)" }} />
          <div style={{ position: "relative", zIndex: 2, padding: "28px 32px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: ".1em", color: "rgba(255,255,255,.7)", fontWeight: 600, textTransform: "uppercase" }}>Workspace</div>
              <h1 style={{ margin: "12px 0 4px", fontSize: 32, fontWeight: 700, letterSpacing: "-.02em", color: "#fff" }}>{headline || "Welcome back."}</h1>
              <div style={{ fontSize: 13.5, color: "rgba(255,255,255,.78)", maxWidth: 780 }}>
                {selectedSession ? buildWorkspaceStatus(selectedSession, selectedDigest) : "Start a run and Astra will build the plan, coordinate agents, and keep the work moving."}
              </div>
            </div>
            <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
              <button
                data-tour="dash-new-run"
                onClick={() => router.push("/dashboard?new=1")}
                style={{ background: "#fff", color: "#002EFF", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 700, fontSize: 13, cursor: "pointer" }}
              >+ Start task</button>
              <button
                onClick={load}
                style={{ background: "rgba(255,255,255,.14)", color: "#fff", border: "1px solid rgba(255,255,255,.3)", borderRadius: 8, padding: "10px 18px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
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

        <div style={{ padding: "18px 30px", display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 11, letterSpacing: ".08em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Today</div>

          <div className="dv-body" style={{ display: "flex", gap: 18, alignItems: "stretch" }}>
            <div className="dv-goal-col" style={{ width: 330, flex: "none", background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 20 }}>
              <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Active goal</div>

              {(() => {
                const active = regularSessions.find(s => s.status === "running" || s.status === "stalled") || regularSessions[0] || null;
                const accentColor = "#7D8FFF";

                if (!active) {
                  return (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px 20px", gap: 14, flex: 1 }}>
                      <div style={{ width: 44, height: 44, border: "1px solid rgba(255,255,255,.16)", borderRadius: 11, display: "flex", alignItems: "center", justifyContent: "center", transform: "rotate(45deg)" }}>
                        <div style={{ width: 13, height: 13, background: accentColor, borderRadius: 3 }} />
                      </div>
                      <div>
                        <div style={{ fontSize: 16, fontWeight: 700 }}>No active goals</div>
                        <div style={{ fontSize: 12.5, color: "#6f7b98", marginTop: 5 }}>Start a run and Astra will get to work.</div>
                      </div>
                    </div>
                  );
                }

                const digest = digests.get(active.session_id);
                const phasesDone = digest?.counts.phases_done ?? 0;
                const phasesTotal = digest?.counts.phases_total ?? 0;
                const phasesPending = digest?.counts.phases_pending ?? 0;
                const progress = phasesTotal > 0 ? phasesDone / phasesTotal : 0;
                const dashOffset = 157 * (1 - progress);
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const ringColor = isStalled ? "#FFFFA6" : accentColor;

                return (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
                      <div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{cleanTitle}</div>
                        <div style={{ fontSize: 12, color: "#6f7b98", marginTop: 4 }}>
                          {phasesDone > 0 || phasesTotal > 0 ? `${phasesDone} of ${phasesTotal} tasks done` : isStalled ? "Needs attention" : "Running…"}
                        </div>
                      </div>
                      <div style={{ position: "relative", width: 58, height: 58, flex: "none" }}>
                        <svg width={58} height={58} viewBox="0 0 58 58">
                          <circle cx={29} cy={29} r={25} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={5} />
                          <circle cx={29} cy={29} r={25} fill="none" stroke={ringColor} strokeWidth={5} strokeLinecap="round" strokeDasharray={157} strokeDashoffset={phasesTotal > 0 ? dashOffset : 130} transform="rotate(-90 29 29)" style={{ transition: "stroke-dashoffset 0.8s ease" }} />
                        </svg>
                        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1 }}>
                          <span style={{ fontSize: 15, fontWeight: 700 }}>{isDone ? "✓" : phasesDone}</span>
                          <span style={{ fontSize: 9, color: "#6f7b98" }}>/ {phasesTotal || "?"}</span>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 16, marginTop: 16, fontSize: 12, color: "#8A93AD" }}>
                      <span>✓ <b style={{ color: "#EDF1FB" }}>{phasesDone}</b> done</span>
                      <span>○ <b style={{ color: "#EDF1FB" }}>{phasesPending}</b> queued</span>
                    </div>

                    <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
                      <button
                        onClick={() => router.push(`/s/${active.session_id}`)}
                        style={{ flex: 1, background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: 10, fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >{suggestedMonitor && active.session_id === selectedSession?.session_id ? "Open monitor" : "Open run"}</button>
                      <button
                        onClick={() => {
                          copilotLoadedSession.current = null;
                          setCopilot([]);
                          setCopilotSessionId(active.session_id);
                          setCopilotOpen(true);
                        }}
                        style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "10px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >Copilot</button>
                    </div>
                  </>
                );
              })()}
            </div>

            <div style={{ flex: 1, minWidth: 0, background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, padding: 20, display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Recent runs</div>
                <button onClick={() => setShowCompleted(v => !v)} style={{ fontSize: 12, color: "#7d8fff", background: "none", border: "none", cursor: "pointer", fontWeight: 600, textDecoration: "none" }}>View all →</button>
              </div>

              {sessions === null ? (
                <div style={{ color: "#6f7b98", fontSize: 13 }}>Loading…</div>
              ) : error ? (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 10 }}>{error}</div>
                  <button style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 8 }} onClick={load}>Try again</button>
                </div>
              ) : !regularSessions.length ? (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px 20px", gap: 14 }}>
                  <div style={{ width: 44, height: 44, border: "1px solid rgba(255,255,255,.16)", borderRadius: 11, display: "flex", alignItems: "center", justifyContent: "center", transform: "rotate(45deg)" }}>
                    <div style={{ width: 13, height: 13, background: "#7D8FFF", borderRadius: 3 }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>No runs yet</div>
                    <div style={{ fontSize: 12.5, color: "#6f7b98", marginTop: 5 }}>Start your first run and Astra will get to work.</div>
                  </div>
                  <button onClick={() => router.push("/dashboard?new=1")} style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "11px 22px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Start first run →</button>
                </div>
              ) : (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
                    {[
                      { label: "Active", value: String(runningCount) },
                      { label: "Done today", value: String(completedToday) },
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
                      <div key={label} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.06)", borderRadius: 9, padding: 12 }}>
                        <div style={{ fontSize: 10.5, color: "#6f7b98" }}>{label}</div>
                        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 5 }}>{value}</div>
                      </div>
                    ))}
                  </div>

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
                        return { width: 8, height: 8, borderRadius: "50%", background: colors[status] || "#6f7b98", flexShrink: 0, display: "inline-block" };
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
                        return <span style={{ fontSize: 11, fontWeight: 600, color: c.color, background: c.bg, border: `1px solid ${c.border}`, padding: "3px 9px", borderRadius: 6, flexShrink: 0, whiteSpace: "nowrap" }}>{c.label}</span>;
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
                            <div
                              key={s.session_id}
                              className="dv-run-row"
                              style={{ marginLeft: child ? 12 : 0 }}
                              onClick={() => router.push(`/s/${s.session_id}`)}
                            >
                              <span style={dotStyle(s.status)} />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {child && <span style={{ fontSize: 9, color: "#7D8FFF", marginRight: 5 }}>↳</span>}
                                  {extractGoalTitle(s.goal || "Untitled run")}
                                </div>
                                <div style={{ fontSize: 11, color: "#6f7b98", marginTop: 2 }}>{meta(s)}</div>
                              </div>
                              {s.kind === "user" && (
                                <span style={{ fontSize: 8, fontWeight: 700, color: "#7d8fff", background: "rgba(125,143,255,.08)", border: "1px solid rgba(125,143,255,.28)", padding: "2px 6px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0, whiteSpace: "nowrap" }}>User</span>
                              )}
                              {s.kind === "scheduled" && (
                                <span style={{ fontSize: 8, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,.08)", border: "1px solid rgba(245,158,11,.28)", padding: "2px 6px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0, whiteSpace: "nowrap" }}>Auto</span>
                              )}
                              {chip(s.status)}
                              <button
                                title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                                disabled={deleting.has(s.session_id)}
                                onClick={e => confirmDelete(e, s)}
                                onPointerDown={e => e.stopPropagation()}
                                style={{ width: pendingDel.has(s.session_id) ? "auto" : 20, height: 20, padding: pendingDel.has(s.session_id) ? "0 5px" : 0, display: "flex", alignItems: "center", justifyContent: "center", background: pendingDel.has(s.session_id) ? "rgba(255,80,80,.1)" : "transparent", border: pendingDel.has(s.session_id) ? "1px solid rgba(255,80,80,.3)" : "none", color: pendingDel.has(s.session_id) ? "#ff6b6b" : "rgba(237,241,251,.18)", cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 8 : 10, borderRadius: 5, opacity: deleting.has(s.session_id) ? 0.4 : 1, flexShrink: 0, fontWeight: 700, whiteSpace: "nowrap" }}
                              >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DEL?" : "✕"}</button>
                            </div>
                          ))}
                          {hiddenDone && (
                            <button onClick={() => setShowCompleted(true)} style={{ padding: "7px 4px", background: "transparent", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 11, textAlign: "left", marginTop: 4 }}>
                              Show {doneCount} completed runs
                            </button>
                          )}
                          {showCompleted && doneCount > 0 && (
                            <button onClick={() => setShowCompleted(false)} style={{ padding: "5px 4px", background: "transparent", border: "none", cursor: "pointer", color: "#6f7b98", fontSize: 11, textAlign: "left", marginTop: 2 }}>
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

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 18px", background: "#0A0D17", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12 }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Automations</div>
              <div style={{ fontSize: 13, color: "#c3cbe0", marginTop: 6 }}>
                No automations yet.{" "}
                <button onClick={() => router.push("/automations")} style={{ background: "none", border: "none", color: "#7d8fff", cursor: "pointer", padding: 0, fontWeight: 600, fontSize: 13 }}>Create one →</button>
              </div>
            </div>
            <button onClick={() => router.push("/automations")} style={{ fontSize: 12.5, color: "#7d8fff", background: "none", border: "none", cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" }}>Manage automations →</button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,.06)" }}>
            <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase", paddingLeft: 2 }}>Copilot</div>
            <div style={{ display: "flex", alignItems: "center", gap: 11, background: "#0A0D17", border: "1px solid rgba(255,255,255,.1)", borderRadius: 16, padding: "7px 7px 7px 16px", boxShadow: "0 10px 26px -16px rgba(0,0,0,.6)" }}>
              <img src="/logo.png" alt="" style={{ width: 17, height: 17, objectFit: "contain", opacity: 0.75, flexShrink: 0, cursor: "pointer" } as React.CSSProperties} onClick={() => setCopilotOpen(v => !v)} />
              <input
                ref={copilotInputRef}
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#EDF1FB", fontSize: 13.5, fontFamily: "var(--font-instrument), sans-serif" }}
                placeholder="Ask Astra to start a run, draft copy, or find leads…"
                disabled={copilotBusy}
                onFocus={() => setCopilotOpen(true)}
                onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); void sendCopilot(); } }}
              />
              <button
                disabled={copilotBusy}
                onClick={() => { setCopilotOpen(true); void sendCopilot(); }}
                style={{ width: 36, height: 36, borderRadius: 10, background: "#002EFF", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}
              >
                <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            </div>
            {copilotOpen && (
              <div className="dash-copilot-thread">
                {copilot.length === 0 && (
                  <div className="dash-copilot-bubble">
                    {copilotSession ? `Copilot attached to "${copilotTitle}". Ask anything about run state, approvals, or next steps.` : "Start a run to enable copilot context."}
                  </div>
                )}
                {copilot.map((message, index) => (
                  <div key={index} className={`dash-copilot-row ${message.role === "founder" ? "is-founder" : "is-astra"}`}>
                    {message.role !== "founder" && <span className="dash-copilot-avatar">A</span>}
                    <div className="dash-copilot-bubble">
                      {message.content}
                      {message.actions && message.actions.length > 0 && (
                        <div className="dash-copilot-actions">
                          {message.actions.map((action, ai) => (
                            <div key={`${action.tool}-${ai}`} className={`dash-copilot-action is-${action.tone || "info"}`}>
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
