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

function normalizeCopilotActions(actions: any): CopilotAction[] {
  if (!Array.isArray(actions)) return [];
  return actions
    .map((action: any) => {
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

function statusTone(status: string) {
  if (status === "running") return { label: "Running", color: "#7CFFC6", bg: "rgba(124,255,198,.1)", border: "rgba(124,255,198,.18)" };
  if (status === "done") return { label: "Complete", color: "#A7B0C5", bg: "rgba(167,176,197,.08)", border: "rgba(167,176,197,.16)" };
  if (status === "stalled") return { label: "Needs attention", color: "#F7D774", bg: "rgba(247,215,116,.1)", border: "rgba(247,215,116,.18)" };
  return { label: status, color: "#FF7C7C", bg: "rgba(255,124,124,.08)", border: "rgba(255,124,124,.16)" };
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

function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section style={{ background: "linear-gradient(180deg, rgba(12,16,28,.98), rgba(8,11,19,.98))", border: "1px solid rgba(255,255,255,.08)", borderRadius: 18, padding: 18, boxShadow: "0 18px 40px rgba(0,0,0,.18)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
        <div style={{ fontSize: 11, letterSpacing: ".09em", textTransform: "uppercase", color: "#7E8BA6", fontWeight: 700 }}>{title}</div>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function DashboardView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [digests, setDigests] = useState<Map<string, SessionDigest>>(new Map());
  const [error, setError] = useState("");
  const [toastErr, setToastErr] = useState("");
  const [credits, setCredits] = useState<number | null>(null);
  const [firstName, setFirstName] = useState("");
  const [greeting, setGreeting] = useState("");
  const [copilot, setCopilot] = useState<CopilotMessage[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState("");
  const [monitorSessionId, setMonitorSessionId] = useState("");
  const [monitorMode, setMonitorMode] = useState<"manual" | "auto" | null>(null);
  const [showArchive, setShowArchive] = useState(false);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [pendingDel, setPendingDel] = useState<Set<string>>(new Set());
  const [launchComplete, setLaunchComplete] = useState<{ companyName: string; founderName: string; agentsRan: number; artifactsCreated: number; stackName?: string } | null>(null);
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
    if (typeof window !== "undefined") {
      const fullName = localStorage.getItem("astra_onboarding_name") || "";
      setFirstName(fullName.split(" ")[0] || fullName);
    }
    setGreeting(GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
  }, []);

  useEffect(() => { void load(); }, [load]);

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

  useEffect(() => {
    if (!sessions?.length) {
      setCopilotSessionId("");
      return;
    }
    const preferred = pickWorkspaceSession(sessions);
    if (!preferred) return;
    setCopilotSessionId((current) => {
      if (current && sessions.some((session) => session.session_id === current)) return current;
      return preferred.session_id;
    });
  }, [sessions]);

  useEffect(() => {
    if (!copilotSessionId || copilotLoadedSession.current === copilotSessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`);
        const data = await response.json();
        if (cancelled) return;
        if (Array.isArray(data.history)) {
          setCopilot(data.history.map((item: any) => ({
            role: item.role,
            content: item.content,
            actions: normalizeCopilotActions(item.actions),
          })));
        }
        copilotLoadedSession.current = copilotSessionId;
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [copilotSessionId]);

  useEffect(() => {
    copilotLoadedSession.current = null;
    setCopilot([]);
  }, [copilotSessionId]);

  useEffect(() => {
    if (!consumePreviewSignal()) return;
    const company = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_company") || localStorage.getItem("astra_onboarding_name") || "") : "";
    const fullName = typeof window !== "undefined" ? (localStorage.getItem("astra_onboarding_name") || "") : "";
    const founder = fullName.split(" ")[0] || fullName;
    setLaunchComplete({ companyName: company, founderName: founder, agentsRan: 0, artifactsCreated: 0 });
  }, []);

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

  const regularSessions = useMemo(() => (sessions || []).filter((session) => session.stack_id !== "custom"), [sessions]);
  const activeSessions = useMemo(() => regularSessions.filter((session) => session.status === "running" || session.status === "stalled"), [regularSessions]);
  const stalledSessions = useMemo(() => regularSessions.filter((session) => session.status === "stalled"), [regularSessions]);
  const completedSessions = useMemo(() => regularSessions.filter((session) => session.status === "done"), [regularSessions]);
  const selectedSession = useMemo(() => regularSessions.find((session) => session.session_id === copilotSessionId) || pickWorkspaceSession(regularSessions), [copilotSessionId, regularSessions]);
  const selectedDigest = selectedSession ? digests.get(selectedSession.session_id) || null : null;
  const suggestedMonitor = shouldEscalateToMonitor(selectedSession || null, selectedDigest || null);
  const headline = greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "Workspace";
  const completedToday = completedSessions.filter((session) => session.created_at && (Date.now() - new Date(session.created_at).getTime()) < 86400000).length;
  const monitorSession = monitorMode === "manual" && monitorSessionId
    ? regularSessions.find((session) => session.session_id === monitorSessionId) || null
    : null;

  const showErr = (message: string) => {
    setToastErr(message);
    window.setTimeout(() => setToastErr(""), 6000);
  };

  const sendCopilot = useCallback(async () => {
    const msg = copilotInputRef.current?.value.trim();
    if (!msg || copilotBusy || !copilotSessionId) return;
    if (copilotInputRef.current) copilotInputRef.current.value = "";
    setCopilot((current) => [...current, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const response = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`, {
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
  }, [copilotBusy, copilotSessionId]);

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

  const workspaceActionCards = [
    {
      title: stalledSessions.length ? "Resolve blocked work" : "Review latest brief",
      detail: stalledSessions.length
        ? `${stalledSessions.length} run${stalledSessions.length === 1 ? "" : "s"} need your approval or a retry.`
        : selectedDigest?.ready_artifacts[0]?.title || "Open the latest deliverable and keep refining it with Astra.",
      onClick: () => {
        if (stalledSessions[0]) setCopilotSessionId(stalledSessions[0].session_id);
        else if (selectedSession) setCopilotSessionId(selectedSession.session_id);
      },
    },
    {
      title: selectedSession ? `Resume ${selectedSession.company_name || "active run"}` : "Start a new run",
      detail: selectedSession
        ? `Astra is tracking ${selectedSession.company_name || extractGoalTitle(selectedSession.goal)}.`
        : "Describe the work in plain English and Astra will route the right agents.",
      onClick: () => router.push("/dashboard?new=1"),
    },
    {
      title: "Open full monitor",
      detail: selectedSession
        ? "Deep inspection mode for technical logs, phases, and detailed agent activity."
        : "Available once a run is active.",
      onClick: () => {
        if (!selectedSession) return;
        setMonitorSessionId(selectedSession.session_id);
        setMonitorMode("manual");
      },
    },
  ];

  if (monitorSession) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: "#060912" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,.08)", background: "rgba(8,11,19,.96)" }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: ".09em", textTransform: "uppercase", color: "#7E8BA6", fontWeight: 700 }}>
              Workspace + focused monitor
            </div>
            <div style={{ fontSize: 15, color: "#F4F7FF", fontWeight: 650, marginTop: 4 }}>
              {extractGoalTitle(monitorSession.goal || "Active run")}
            </div>
            <div style={{ fontSize: 12.5, color: "#9AA6BF", marginTop: 4 }}>
              Deep inspection mode is open for this run. Return to workspace whenever you want the calmer view again.
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
                setMonitorSessionId("");
                setMonitorMode(null);
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
        @keyframes workspacePulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .55; transform: scale(.88); } }
        .workspace-scroll::-webkit-scrollbar { width: 10px; height: 10px; }
        .workspace-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,.09); border-radius: 999px; }
        .workspace-copilot-msg { max-width: min(680px, 100%); border-radius: 16px; padding: 13px 15px; font-size: 13px; line-height: 1.65; white-space: pre-wrap; }
        .workspace-copilot-msg.founder { background: #002EFF; color: #fff; margin-left: auto; }
        .workspace-copilot-msg.astra { background: rgba(255,255,255,.04); color: #EAF0FF; border: 1px solid rgba(255,255,255,.08); }
        .workspace-chip { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 6px 10px; border: 1px solid rgba(255,255,255,.09); background: rgba(255,255,255,.03); font-size: 11px; color: #B3BED4; }
        .workspace-action-card:hover { border-color: rgba(0,46,255,.26); transform: translateY(-1px); }
        .workspace-run-row:hover { background: rgba(255,255,255,.03); }
        @media (max-width: 1100px) {
          .workspace-grid { grid-template-columns: 1fr !important; }
          .workspace-side { order: 3; }
          .workspace-center { order: 1; }
          .workspace-rail { order: 2; }
        }
      `}</style>
      <div className="workspace-scroll" style={{ height: "100%", overflowY: "auto", background: "radial-gradient(circle at top left, rgba(0,46,255,.12), transparent 0 30%), linear-gradient(180deg, #060912 0%, #05070E 100%)", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>
        <div style={{ padding: "24px 24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
          <section style={{ padding: "22px 24px", borderRadius: 22, border: "1px solid rgba(255,255,255,.08)", background: "linear-gradient(135deg, rgba(10,17,32,.98), rgba(7,10,18,.92))", boxShadow: "0 22px 48px rgba(0,0,0,.22)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
              <div style={{ maxWidth: 760 }}>
                <div style={{ fontSize: 11, letterSpacing: ".1em", textTransform: "uppercase", color: "#8B97B1", fontWeight: 700 }}>Workspace</div>
                <h1 style={{ margin: "10px 0 8px", fontSize: 34, lineHeight: 1.05, color: "#F8FAFF", letterSpacing: "-.03em" }}>{headline}</h1>
                <div style={{ fontSize: 15, color: "#AAB5CB", lineHeight: 1.65, maxWidth: 760 }}>
                  {buildWorkspaceStatus(selectedSession || null, selectedDigest || null)}
                </div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 16 }}>
                  <span className="workspace-chip">{activeSessions.length} active</span>
                  <span className="workspace-chip">{completedToday} completed today</span>
                  <span className="workspace-chip">{credits !== null ? `${credits.toLocaleString()} credits` : "Credits loading"}</span>
                  <span className="workspace-chip">{selectedSession ? (selectedSession.company_name || selectedSession.stack_id.replace(/_/g, " ")) : "No active run selected"}</span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  onClick={() => router.push("/dashboard?new=1")}
                  style={{ background: "#002EFF", color: "#fff", border: "1px solid rgba(0,46,255,.4)", borderRadius: 12, padding: "12px 18px", fontWeight: 700, cursor: "pointer", boxShadow: "0 14px 30px rgba(0,46,255,.18)" }}
                >
                  Start task
                </button>
                <button
                  onClick={() => load()}
                  style={{ background: "rgba(255,255,255,.03)", color: "#E6EBF7", border: "1px solid rgba(255,255,255,.1)", borderRadius: 12, padding: "12px 16px", fontWeight: 600, cursor: "pointer" }}
                >
                  Refresh
                </button>
              </div>
            </div>
          </section>

          {toastErr && (
            <div style={{ background: "rgba(255,80,80,0.08)", border: "1px solid rgba(255,80,80,0.16)", borderRadius: 14, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: "#FF8585" }}>
              <span>✗</span>
              <span style={{ flex: 1 }}>{toastErr}</span>
              <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14 }}>✕</button>
            </div>
          )}

          <div className="workspace-grid" style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr) 320px", gap: 18, alignItems: "start" }}>
            <div className="workspace-rail" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <SectionCard title="Runs" action={<button onClick={() => router.push("/goals")} style={{ background: "none", border: "none", color: "#7F8EAF", cursor: "pointer", fontWeight: 600, fontSize: 12 }}>Open runs</button>}>
                {error ? (
                  <div style={{ fontSize: 12.5, color: "#FF8F8F" }}>{error}</div>
                ) : sessions === null ? (
                  <div style={{ fontSize: 12.5, color: "#9AA6BF" }}>Loading your runs…</div>
                ) : regularSessions.length === 0 ? (
                  <div style={{ fontSize: 12.5, color: "#9AA6BF", lineHeight: 1.6 }}>
                    No runs yet. Start with a plain-English prompt and Astra will build the right workflow.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {activeSessions.slice(0, 4).map((session) => {
                      const tone = statusTone(session.status);
                      const active = session.session_id === selectedSession?.session_id;
                      return (
                        <button
                          key={session.session_id}
                          className="workspace-run-row"
                          onClick={() => setCopilotSessionId(session.session_id)}
                          style={{ textAlign: "left", border: active ? "1px solid rgba(0,46,255,.28)" : "1px solid rgba(255,255,255,.08)", background: active ? "rgba(0,46,255,.08)" : "rgba(255,255,255,.02)", borderRadius: 14, padding: "12px 13px", cursor: "pointer" }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                            <div style={{ fontSize: 12.5, fontWeight: 650, color: "#F0F4FF", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {session.company_name || extractGoalTitle(session.goal || "Untitled run")}
                            </div>
                            <span style={{ fontSize: 10.5, color: tone.color, background: tone.bg, border: `1px solid ${tone.border}`, borderRadius: 999, padding: "3px 8px", whiteSpace: "nowrap" }}>
                              {tone.label}
                            </span>
                          </div>
                          <div style={{ fontSize: 11.5, color: "#91A0BC", marginTop: 6, lineHeight: 1.5 }}>
                            {extractGoalTitle(session.goal || "Untitled run")}
                          </div>
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginTop: 8, fontSize: 10.5, color: "#7F8EAB" }}>
                            <span>{ago(session.created_at)}</span>
                            <span>{digests.get(session.session_id)?.counts.ready_artifacts ?? 0} artifacts</span>
                          </div>
                        </button>
                      );
                    })}
                    {completedSessions.length > 0 && (
                      <button
                        onClick={() => setShowArchive((current) => !current)}
                        style={{ marginTop: 4, border: "none", background: "none", color: "#7D8FFF", cursor: "pointer", fontWeight: 600, fontSize: 12, textAlign: "left", padding: "0 2px" }}
                      >
                        {showArchive ? "Hide archive" : `Show archive (${completedSessions.length})`}
                      </button>
                    )}
                    {showArchive && completedSessions.slice(0, 6).map((session) => (
                      <div key={session.session_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 2px 8px", borderBottom: "1px solid rgba(255,255,255,.06)" }}>
                        <button onClick={() => setCopilotSessionId(session.session_id)} style={{ flex: 1, background: "none", border: "none", textAlign: "left", cursor: "pointer", padding: 0 }}>
                          <div style={{ fontSize: 12.5, color: "#D5DCEC", fontWeight: 600 }}>{session.company_name || extractGoalTitle(session.goal || "Untitled run")}</div>
                          <div style={{ fontSize: 11, color: "#7F8EAB", marginTop: 4 }}>{ago(session.created_at)}</div>
                        </button>
                        <button
                          title={pendingDel.has(session.session_id) ? "Click again to confirm" : "Delete"}
                          disabled={deleting.has(session.session_id)}
                          onClick={(e) => void confirmDelete(e, session)}
                          style={{ width: pendingDel.has(session.session_id) ? "auto" : 22, height: 22, padding: pendingDel.has(session.session_id) ? "0 6px" : 0, borderRadius: 6, border: pendingDel.has(session.session_id) ? "1px solid rgba(255,107,107,.28)" : "none", background: pendingDel.has(session.session_id) ? "rgba(255,107,107,.1)" : "transparent", color: pendingDel.has(session.session_id) ? "#FF7C7C" : "rgba(234,240,255,.26)", cursor: "pointer", fontSize: pendingDel.has(session.session_id) ? 8 : 11, fontWeight: 700 }}
                        >
                          {deleting.has(session.session_id) ? "…" : pendingDel.has(session.session_id) ? "DEL?" : "✕"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Suggested next steps">
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {workspaceActionCards.map((item) => (
                    <button
                      key={item.title}
                      className="workspace-action-card"
                      onClick={item.onClick}
                      style={{ textAlign: "left", border: "1px solid rgba(255,255,255,.08)", borderRadius: 14, background: "rgba(255,255,255,.02)", padding: "14px 14px 13px", cursor: "pointer", transition: "transform .14s ease, border-color .14s ease" }}
                    >
                      <div style={{ fontSize: 12.5, color: "#F1F5FF", fontWeight: 650 }}>{item.title}</div>
                      <div style={{ fontSize: 11.5, color: "#93A0B8", lineHeight: 1.55, marginTop: 5 }}>{item.detail}</div>
                    </button>
                  ))}
                </div>
              </SectionCard>
            </div>

            <div className="workspace-center" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <SectionCard
                title="Astra Copilot"
                action={selectedSession ? <span style={{ fontSize: 11.5, color: "#8EA0C2" }}>Attached to {selectedSession.company_name || selectedSession.stack_id.replace(/_/g, " ")}</span> : undefined}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: 280 }}>
                    {copilot.length === 0 ? (
                      <div className="workspace-copilot-msg astra">
                        {selectedSession
                          ? `Ask Astra to steer "${extractGoalTitle(selectedSession.goal || "this run")}", summarize what matters, or open the right execution context.`
                          : "Start a run or choose one from the rail, then ask Astra what to do next."}
                      </div>
                    ) : (
                      copilot.map((message, index) => (
                        <div key={`${message.role}-${index}`}>
                          <div className={`workspace-copilot-msg ${message.role === "founder" ? "founder" : "astra"}`}>
                            {message.content}
                            {message.actions && message.actions.length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
                                {message.actions.map((action, actionIndex) => (
                                  <div key={`${action.tool}-${actionIndex}`} style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,.08)", background: action.tone === "success" ? "rgba(124,255,198,.08)" : action.tone === "warn" ? "rgba(247,215,116,.08)" : "rgba(255,255,255,.04)", padding: "8px 10px", minWidth: 120 }}>
                                    <div style={{ fontSize: 10.5, color: "#F4F7FF", fontWeight: 700 }}>{action.label}</div>
                                    {action.detail && <div style={{ fontSize: 10.5, color: "#9EACC6", lineHeight: 1.45, marginTop: 4 }}>{action.detail}</div>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                    {copilotBusy && (
                      <div className="workspace-copilot-msg astra" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#7CFFC6", animation: "workspacePulse 1s infinite" }} />
                        Astra is thinking…
                      </div>
                    )}
                  </div>

                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {(selectedDigest?.next_actions.length ? selectedDigest.next_actions : ["Review approvals", "Summarize the run", "Open the latest deliverable"]).slice(0, 4).map((action) => (
                      <button
                        key={action}
                        onClick={() => {
                          if (copilotInputRef.current) copilotInputRef.current.value = action;
                          void sendCopilot();
                        }}
                        style={{ borderRadius: 999, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "#D8E0F0", padding: "8px 12px", fontSize: 11.5, cursor: "pointer" }}
                      >
                        {action}
                      </button>
                    ))}
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 10, borderRadius: 16, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.025)", padding: "10px 10px 10px 14px" }}>
                    <input
                      ref={copilotInputRef}
                      placeholder="Ask Astra to plan, steer, summarize, or continue the work…"
                      disabled={copilotBusy}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void sendCopilot();
                        }
                      }}
                      style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", color: "#ECF1FF", fontSize: 14, fontFamily: "inherit" }}
                    />
                    <button
                      disabled={copilotBusy || !selectedSession}
                      onClick={() => void sendCopilot()}
                      style={{ width: 40, height: 40, borderRadius: 12, border: "1px solid rgba(0,46,255,.28)", background: "#002EFF", color: "#fff", cursor: "pointer", fontSize: 16, fontWeight: 700 }}
                    >
                      ↑
                    </button>
                  </div>
                </div>
              </SectionCard>

              <SectionCard title="Current focus" action={selectedSession ? <button onClick={() => router.push(`/s/${selectedSession.session_id}`)} style={{ background: "none", border: "none", color: "#7D8FFF", cursor: "pointer", fontWeight: 600, fontSize: 12 }}>Open shareable run</button> : undefined}>
                {!selectedSession ? (
                  <div style={{ fontSize: 13, color: "#99A7C0", lineHeight: 1.65 }}>
                    No run is selected yet. Choose one from the rail or start a new task to see approvals, deliverables, and current workstreams here.
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 12 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
                      {[
                        { label: "Progress", value: selectedDigest ? `${selectedDigest.counts.phases_done}/${selectedDigest.counts.phases_total || "?"}` : "—", hint: "phases complete" },
                        { label: "Agents running", value: selectedDigest?.counts.running_agents ?? 0, hint: "currently active" },
                        { label: "Artifacts ready", value: selectedDigest?.counts.ready_artifacts ?? 0, hint: "deliverables" },
                        { label: "Approvals", value: selectedDigest?.counts.pending_approvals ?? 0, hint: "waiting on you" },
                      ].map((stat) => (
                        <div key={stat.label} style={{ borderRadius: 14, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", padding: "14px 15px" }}>
                          <div style={{ fontSize: 10.5, color: "#8090AB", textTransform: "uppercase", letterSpacing: ".07em", fontWeight: 700 }}>{stat.label}</div>
                          <div style={{ fontSize: 24, color: "#F5F8FF", fontWeight: 700, marginTop: 7 }}>{stat.value}</div>
                          <div style={{ fontSize: 11, color: "#8EA0BE", marginTop: 5 }}>{stat.hint}</div>
                        </div>
                      ))}
                    </div>

                    <div style={{ borderRadius: 16, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", padding: 16 }}>
                      <div style={{ fontSize: 12.5, color: "#F2F6FF", fontWeight: 650, marginBottom: 8 }}>What Astra is doing now</div>
                      <div style={{ fontSize: 13, color: "#9AA7BF", lineHeight: 1.65 }}>
                        {selectedDigest?.summary || buildWorkspaceStatus(selectedSession, selectedDigest)}
                      </div>
                      {selectedDigest?.running_agents && selectedDigest.running_agents.length > 0 && (
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                          {selectedDigest.running_agents.slice(0, 5).map((agent) => (
                            <span key={agent} className="workspace-chip">{agent.replace(/_/g, " ")}</span>
                          ))}
                        </div>
                      )}
                    </div>

                    {suggestedMonitor && (
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderRadius: 16, border: "1px solid rgba(247,215,116,.2)", background: "rgba(247,215,116,.08)", padding: 15 }}>
                        <div>
                          <div style={{ fontSize: 12.5, color: "#FFF0C3", fontWeight: 700 }}>This run is getting dense</div>
                          <div style={{ fontSize: 12.5, color: "#E8DCA9", marginTop: 4, lineHeight: 1.55 }}>
                            Astra recommends deep monitor mode for full technical logs, multi-agent progress, and approval detail.
                          </div>
                        </div>
                        <button
                          onClick={() => {
                            setMonitorSessionId(selectedSession.session_id);
                            setMonitorMode("manual");
                          }}
                          style={{ borderRadius: 10, border: "1px solid rgba(247,215,116,.28)", background: "rgba(255,255,255,.04)", color: "#FFF0C3", padding: "10px 14px", fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}
                        >
                          Open monitor
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </SectionCard>
            </div>

            <div className="workspace-side" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <SectionCard title="Needs your attention">
                {!selectedSession ? (
                  <div style={{ fontSize: 12.5, color: "#99A7C0" }}>Choose a run to see approvals and founder actions.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {(selectedDigest?.approval_focus?.length ? selectedDigest.approval_focus : [{ title: "No approvals waiting", reason: "Astra can continue without founder input right now." }]).slice(0, 4).map((approval, index) => (
                      <div key={`${approval.title}-${index}`} style={{ borderRadius: 14, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", padding: "13px 14px" }}>
                        <div style={{ fontSize: 12.5, color: "#F0F5FF", fontWeight: 650 }}>{approval.title || "Approval required"}</div>
                        <div style={{ fontSize: 11.5, color: "#93A0B8", lineHeight: 1.55, marginTop: 5 }}>
                          {approval.reason || "Open the run monitor to review the exact evidence and continue."}
                        </div>
                      </div>
                    ))}
                    {selectedSession && (
                      <button
                        onClick={() => {
                          setMonitorSessionId(selectedSession.session_id);
                          setMonitorMode("manual");
                        }}
                        style={{ borderRadius: 12, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "#E5EBF8", padding: "10px 12px", fontWeight: 600, cursor: "pointer" }}
                      >
                        Review in focused monitor
                      </button>
                    )}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Recent outputs">
                {!selectedDigest?.ready_artifacts?.length ? (
                  <div style={{ fontSize: 12.5, color: "#99A7C0", lineHeight: 1.6 }}>
                    Deliverables will show up here as Astra completes research, strategy, technical, and launch work.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {selectedDigest.ready_artifacts.slice(0, 5).map((artifact, index) => (
                      <div key={`${artifact.title || "artifact"}-${index}`} style={{ borderRadius: 14, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", padding: "12px 14px" }}>
                        <div style={{ fontSize: 12.5, color: "#F0F5FF", fontWeight: 650 }}>{artifact.title || "Untitled output"}</div>
                        <div style={{ fontSize: 10.5, color: "#7E8CA8", marginTop: 4 }}>{artifact.owner_agent?.replace(/_/g, " ") || "Astra"}</div>
                        {artifact.preview && <div style={{ fontSize: 11.5, color: "#93A0B8", lineHeight: 1.55, marginTop: 7 }}>{artifact.preview}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Quick access">
                <div style={{ display: "grid", gap: 10 }}>
                  {[
                    { label: "Company Brain", href: "/brain", detail: "Search connected knowledge and synced docs" },
                    { label: "Outreach", href: "/outreach", detail: "Review campaigns, sequences, and lead work" },
                    { label: "Integrations", href: "/integrations", detail: "Connect or repair systems Astra depends on" },
                    { label: "Payments", href: "/payments", detail: "Check credit balance and billing state" },
                  ].map((item) => (
                    <button
                      key={item.href}
                      onClick={() => router.push(item.href)}
                      style={{ textAlign: "left", borderRadius: 14, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", padding: "13px 14px", cursor: "pointer" }}
                    >
                      <div style={{ fontSize: 12.5, color: "#F2F6FF", fontWeight: 650 }}>{item.label}</div>
                      <div style={{ fontSize: 11.5, color: "#93A0B8", lineHeight: 1.5, marginTop: 4 }}>{item.detail}</div>
                    </button>
                  ))}
                </div>
              </SectionCard>
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
