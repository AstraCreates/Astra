"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, getCredits, AGENT_LABELS, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";
import AstraCopilotComposer, { extractAgentMentions, type CopilotAgentOption } from "./AstraCopilotComposer";
import { getRunSnapshot } from "@/lib/control-plane-api";

function sessionStatusFromRunStatus(status: string): SessionIndexEntry["status"] {
  const map: Record<string, SessionIndexEntry["status"]> = {
    queued: "running",
    running: "running",
    awaiting_approval: "stalled",
    cancelling: "running",
    cancelled: "killed",
    succeeded: "done",
    failed: "error",
  };
  return map[status] || status;
}

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

// Exact chip colors from reference HTML
const CHIP_COLORS: Record<string, string> = {
  running: "rgb(125, 143, 255)",
  done:    "rgb(195, 208, 238)",
  queued:  "rgb(169, 181, 255)",
  stalled: "rgb(255, 255, 166)",
  error:   "rgb(255, 255, 166)",
  killed:  "rgb(255, 166, 166)",
};
const DOT_COLORS: Record<string, string> = {
  running: "rgb(125, 143, 255)",
  done:    "rgb(74, 85, 104)",
  queued:  "rgb(169, 181, 255)",
  stalled: "rgb(255, 255, 166)",
  error:   "rgb(255, 255, 166)",
  killed:  "rgb(255, 107, 107)",
};
const CHIP_LABELS: Record<string, string> = {
  running: "Running",
  done:    "Done",
  queued:  "Queued",
  stalled: "Needs retry",
  error:   "Needs retry",
  killed:  "Stopped",
};

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
  const [viewMode, setViewMode] = useState<"populated" | "first-run">("populated");
  const [copilot, setCopilot] = useState<{ role: string; content: string; actions?: CopilotAction[] }[]>([]);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotSessionId, setCopilotSessionId] = useState("");
  const retriedRef = useRef(false);
  const prevStatusRef = useRef<Map<string, string>>(new Map());
  const copilotLoadedSession = useRef<string | null>(null);
  const [copilotInput, setCopilotInput] = useState("");
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
    setLaunchComplete({ companyName: company, founderName: fullName.split(" ")[0] || fullName, agentsRan: 0, artifactsCreated: 0 });
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const fullName = localStorage.getItem("astra_onboarding_name") || "";
      setFirstName(fullName.split(" ")[0] || fullName);
    }
    setGreeting(GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
  }, []);

  const del = useCallback(async (e: React.MouseEvent, s: SessionIndexEntry) => {
    e.stopPropagation(); e.preventDefault();
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
      // The list endpoint remains the discovery mechanism during migration, but
      // active cards take their state from the durable run projection whenever
      // the session has been backfilled. This avoids a second broad list API.
      const active = fetched.filter((session) => ["running", "stalled"].includes(session.status));
      void Promise.allSettled(active.map(async (session) => {
        const snapshot = await getRunSnapshot(session.session_id);
        return [session.session_id, sessionStatusFromRunStatus(snapshot.run.status)] as const;
      })).then((results) => {
        const statuses = new Map(
          results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []),
        );
        if (statuses.size === 0) return;
        setSessions((current) => current?.map((session) => {
          const status = statuses.get(session.session_id);
          return status && status !== session.status ? { ...session, status } : session;
        }) ?? current);
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSessions((p) => p ?? []);
    }
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
      const results = await Promise.allSettled(running.map(s => getSessionDigest(s.session_id).then(d => [s.session_id, d] as [string, SessionDigest])));
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
    if (!copilotSessionId || copilotLoadedSession.current === copilotSessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`);
        const d = await r.json();
        if (cancelled) return;
        if (Array.isArray(d.history)) {
          setCopilot((prev) => prev.length > 0 ? prev : d.history.map((item: any) => ({ role: item.role, content: item.content, actions: normalizeCopilotActions(item.actions) })));
        }
        copilotLoadedSession.current = copilotSessionId;
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [copilotSessionId]);

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
        setLaunchComplete({ companyName: s.company_name || "", founderName: firstName, agentsRan: digest?.counts.done_agents ?? 0, artifactsCreated: digest?.counts.ready_artifacts ?? 0, stackName: s.stack_id?.replace(/_/g, " ") });
        markLaunchCompleteShown();
        triggered = true;
      }
      prev.set(s.session_id, s.status);
    }
  }, [sessions, digests]);

  const runningCount = (sessions || []).filter((s) => s.status === "running").length;
  const regularSessions = (sessions || []).filter((s) => s.stack_id !== "custom");

  const copilotAgents: CopilotAgentOption[] = Object.entries(AGENT_LABELS).map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));

  const heroSubtitle = sessions === null
    ? "Loading your workspace…"
    : runningCount > 0
      ? `${runningCount} run${runningCount !== 1 ? "s" : ""} active · ${(sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length} completed today`
      : "Astra is ready when you are.";

  const sendCopilot = useCallback(async () => {
    const msg = copilotInput.trim();
    if (!msg || copilotBusy || !copilotSessionId) return;
    const mentionedAgents = extractAgentMentions(msg, copilotAgents);
    setCopilotInput("");
    setCopilot((current) => [...current, { role: "founder", content: msg }]);
    setCopilotBusy(true);
    try {
      const r = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/copilot/${copilotSessionId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, mentioned_agents: mentionedAgents }),
      });
      const d = await r.json();
      setCopilot((current) => [...current, { role: "copilot", content: d.reply || "(no reply)", actions: normalizeCopilotActions(d.actions) }]);
    } catch {
      setCopilot((current) => [...current, { role: "copilot", content: "Copilot error — try again." }]);
    } finally { setCopilotBusy(false); }
  }, [copilotBusy, copilotInput, copilotSessionId, copilotAgents]);

  const metaLine = (s: SessionIndexEntry) => {
    const t = ago(s.created_at);
    if (s.status === "running") return `Started ${t}`;
    if (s.status === "done") return `Completed ${t}`;
    if (s.status === "stalled" || s.status === "error") return `Failed ${t} · retry available`;
    if (s.status === "queued") return "Queued";
    return t;
  };

  const chip = (status: string) => (
    <span style={{ padding: "3px 9px", borderRadius: 20, fontSize: 10.5, fontWeight: 600, background: "rgba(255,255,255,0.06)", color: CHIP_COLORS[status] || "rgb(195,208,238)", whiteSpace: "nowrap", flexShrink: 0 }}>
      {CHIP_LABELS[status] || status}
    </span>
  );

  return (
    <>
      <style>{`
        @keyframes sc-shimmer { 0%,100%{opacity:1} 50%{opacity:.5} }
        @keyframes mascot-float { 0%,100%{transform:translateY(-50%)} 50%{transform:translateY(calc(-50% - 10px))} }
      `}</style>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>

        {/* ── Hero — exact from reference HTML ── */}
        <div style={{ position: "relative", height: 224, overflow: "hidden", background: "rgb(10, 27, 107)" }}>
          <img src="/hero-lineart.png" alt="" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "50% 25%" }} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(5,7,14,0.82) 0%, rgba(5,7,14,0.44) 42%, transparent 72%)" }} />
          <div style={{ position: "relative", zIndex: 2, padding: "28px 32px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "rgba(255,255,255,0.7)", fontWeight: 600, textTransform: "uppercase" }}>Dashboard</div>
              <h1 style={{ margin: "12px 0 4px", fontSize: 32, fontWeight: 700, letterSpacing: "-0.02em" }}>
                {greeting && firstName ? `${greeting}, ${firstName}.` : greeting ? `${greeting}.` : "Welcome back."}
              </h1>
              <div style={{ fontSize: 13.5, color: "rgba(255,255,255,0.78)" }}>{heroSubtitle}</div>
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <button data-tour="dash-new-run" onClick={() => router.push("/dashboard?new=1")}
                style={{ background: "#fff", color: "#002EFF", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: "inherit" }}>
                + New run
              </button>
              <button onClick={load}
                style={{ background: "rgba(255,255,255,0.14)", color: "#fff", border: "1px solid rgba(255,255,255,0.3)", borderRadius: 8, padding: "10px 18px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: "inherit" }}>
                Refresh
              </button>
            </div>
          </div>
        </div>

        {toastErr && (
          <div style={{ background: "rgba(255,80,80,0.08)", borderBottom: "1px solid rgba(255,80,80,.18)", padding: "6px 18px", display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: "#ff6b6b" }}>
            <span>✗</span><span style={{ flex: 1 }}>{toastErr}</span>
            <button onClick={() => setToastErr("")} style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, padding: 0 }}>✕</button>
          </div>
        )}

        {/* ── Body — exact padding from reference ── */}
        <div style={{ padding: "26px 30px", display: "flex", flexDirection: "column", gap: 22, flex: 1 }}>

          {/* TODAY */}
          <div style={{ fontSize: 11, letterSpacing: "0.08em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase" }}>Today</div>

          {/* Two-column layout */}
          <div style={{ display: "flex", gap: 18, alignItems: "stretch", flex: 1, minHeight: 0 }}>

            {/* Active Goal — exact from reference */}
            <div style={{ width: 330, flex: "0 0 auto", background: "rgb(10,13,23)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 20, display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase" }}>Active goal</div>
              {(() => {
                const active = regularSessions.find(s => s.status === "running" || s.status === "stalled") || regularSessions[0] || null;
                if (!active) return (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", flex: 1, gap: 12 }}>
                    <div style={{ position: "relative", width: 48, height: 48, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <div style={{ width: 40, height: 40, border: "1.5px solid rgba(125,143,255,0.45)", background: "rgba(125,143,255,0.06)", transform: "rotate(45deg)", borderRadius: 6, position: "absolute" }} />
                      <div style={{ width: 16, height: 16, background: "rgb(125,143,255)", transform: "rotate(45deg)", borderRadius: 3, position: "absolute" }} />
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>No active goals</div>
                    <div style={{ fontSize: 11.5, color: "rgb(111,123,152)" }}>Start a run and Astra will get to work.</div>
                  </div>
                );
                const digest = digests.get(active.session_id);
                const phasesDone = digest?.counts.phases_done ?? 0;
                const phasesTotal = digest?.counts.phases_total ?? 0;
                const phasesPending = digest?.counts.phases_pending ?? 0;
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const circumference = 157;
                const progress = phasesTotal > 0 ? phasesDone / phasesTotal : 0;
                const ringColor = isStalled ? "#FFFFA6" : "#7D8FFF";
                const creditsStr = phasesDone > 0 ? `${phasesDone} of ${phasesTotal} tasks done` : "";
                return (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
                      <div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{cleanTitle}</div>
                        <div style={{ fontSize: 12, color: "rgb(111,123,152)", marginTop: 4 }}>{creditsStr}</div>
                      </div>
                      <div style={{ position: "relative", width: 58, height: 58, flex: "0 0 auto" }}>
                        <svg width={58} height={58} viewBox="0 0 58 58">
                          <circle cx={29} cy={29} r={25} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth={5} />
                          <circle cx={29} cy={29} r={25} fill="none" stroke={ringColor} strokeWidth={5} strokeLinecap="round"
                            strokeDasharray={circumference} strokeDashoffset={phasesTotal > 0 ? circumference * (1 - progress) : circumference * 0.83}
                            transform="rotate(-90 29 29)" style={{ transition: "stroke-dashoffset .8s ease" }} />
                        </svg>
                        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1 }}>
                          <span style={{ fontSize: 15, fontWeight: 700 }}>{isDone ? "✓" : phasesDone}</span>
                          {phasesTotal > 0 && <span style={{ fontSize: 9, color: "rgb(111,123,152)" }}>/ {phasesTotal}</span>}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 14, fontSize: 11.5, color: "rgb(138,147,173)", marginTop: 10 }}>
                      <span>✓ <b style={{ color: "#EDF1FB" }}>{phasesDone}</b> done</span>
                      <span>○ <b style={{ color: "#EDF1FB" }}>{phasesPending}</b> queued</span>
                    </div>
                    <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
                      <button onClick={() => router.push(`/s/${active.session_id}`)}
                        style={{ flex: 1, background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "9px 0", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: "inherit" }}>
                        Run now
                      </button>
                      <button style={{ background: "transparent", color: "rgb(195,203,224)", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 8, padding: "9px 14px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: "inherit" }}>
                        Pause
                      </button>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* Recent Runs */}
            <div style={{ flex: 1, minWidth: 0, background: "rgb(10,13,23)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase" }}>Recent runs</div>
                <button onClick={() => setViewMode(v => v === "populated" ? "first-run" : "populated")}
                  style={{ fontSize: 12, color: "rgb(125,143,255)", background: "none", border: "none", cursor: "pointer", fontWeight: 600, fontFamily: "inherit" }}>
                  View all →
                </button>
              </div>

              {sessions === null ? (
                <div style={{ color: "rgb(111,123,152)", fontSize: 13 }}>Loading…</div>
              ) : error ? (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ fontSize: 12, color: "rgb(111,123,152)", marginBottom: 10 }}>{error}</div>
                  <button onClick={load} style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 8, fontFamily: "inherit" }}>Try again</button>
                </div>
              ) : !regularSessions.length ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "28px 16px", gap: 10 }}>
                  <div style={{ position: "relative", width: 48, height: 48, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 2 }}>
                    <div style={{ width: 40, height: 40, border: "1.5px solid rgba(125,143,255,0.45)", background: "rgba(125,143,255,0.06)", transform: "rotate(45deg)", borderRadius: 6, position: "absolute" }} />
                    <div style={{ width: 16, height: 16, background: "rgb(125,143,255)", transform: "rotate(45deg)", borderRadius: 3, position: "absolute" }} />
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>No runs yet</div>
                  <div style={{ fontSize: 11.5, color: "rgb(111,123,152)" }}>Start your first run and Astra will get to work.</div>
                  <button onClick={() => router.push("/dashboard?new=1")}
                    style={{ background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontWeight: 600, fontSize: 13, cursor: "pointer", fontFamily: "inherit", marginTop: 4 }}>
                    Start first run →
                  </button>
                </div>
              ) : (
                <>
                  {/* Stats grid — exact from reference */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
                    {[
                      { label: "Active", value: String(runningCount) },
                      { label: "Done today", value: String((sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length) },
                      { label: "Credits", value: credits !== null ? credits.toLocaleString() : "—" },
                      {
                        label: "Success", value: (() => {
                          const done = sessions.filter(s => s.status === "done").length;
                          const failed = sessions.filter(s => s.status === "error" || s.status === "killed").length;
                          const total = done + failed;
                          return total > 0 ? `${Math.round((done / total) * 100)}%` : "—";
                        })(),
                      },
                    ].map(({ label, value }) => (
                      <div key={label} style={{ background: "rgb(7,9,17)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 9, padding: 12 }}>
                        <div style={{ fontSize: 10.5, color: "rgb(111,123,152)" }}>{label}</div>
                        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 5 }}>{value}</div>
                      </div>
                    ))}
                  </div>

                  {/* Run rows — exact from reference */}
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

                      return visibleRows.map(({ s, child }) => (
                        <div key={s.session_id}
                          style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 4px", borderTop: "1px solid rgba(255,255,255,0.06)", marginLeft: child ? 12 : 0, cursor: "pointer" }}
                          onClick={() => router.push(`/s/${s.session_id}`)}>
                          <span style={{ width: 7, height: 7, borderRadius: "50%", flex: "0 0 auto", background: DOT_COLORS[s.status] || "rgb(74,85,104)" }} />
                          <div style={{ flex: "1 1 0%", minWidth: 0 }}>
                            <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                              {child && <span style={{ fontSize: 9, color: "rgb(125,143,255)", marginRight: 4 }}>↳</span>}
                              {extractGoalTitle(s.goal || "Untitled run")}
                            </div>
                            <div style={{ fontSize: 11, color: "rgb(111,123,152)", marginTop: 2 }}>{metaLine(s)}</div>
                          </div>
                          {chip(s.status)}
                          <button
                            title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                            disabled={deleting.has(s.session_id)}
                            onClick={e => del(e, s)}
                            onPointerDown={e => e.stopPropagation()}
                            style={{ width: pendingDel.has(s.session_id) ? "auto" : 20, height: 20, padding: pendingDel.has(s.session_id) ? "0 5px" : 0, display: "flex", alignItems: "center", justifyContent: "center", background: pendingDel.has(s.session_id) ? "rgba(255,80,80,.1)" : "transparent", border: pendingDel.has(s.session_id) ? "1px solid rgba(255,80,80,.3)" : "none", color: pendingDel.has(s.session_id) ? "#ff6b6b" : "rgba(237,241,251,.2)", cursor: "pointer", fontSize: pendingDel.has(s.session_id) ? 8 : 10, borderRadius: 5, opacity: deleting.has(s.session_id) ? 0.4 : 1, flexShrink: 0, fontWeight: 700, fontFamily: "inherit" }}
                          >{deleting.has(s.session_id) ? "…" : pendingDel.has(s.session_id) ? "DEL?" : "✕"}</button>
                        </div>
                      ));
                    })()}
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Automations — exact from reference */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 18px", background: "rgb(10,13,23)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12 }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase" }}>Automations</div>
              <div style={{ fontSize: 13, color: "rgb(195,203,224)", marginTop: 6 }}>
                No automations yet.{" "}
                <a href="#" onClick={(e) => { e.preventDefault(); router.push("/automations"); }}
                  style={{ color: "rgb(125,143,255)", textDecoration: "none", fontWeight: 600 }}>Create one →</a>
              </div>
            </div>
            <a href="#" onClick={(e) => { e.preventDefault(); router.push("/automations"); }}
              style={{ fontSize: 12.5, color: "rgb(125,143,255)", textDecoration: "none", fontWeight: 600 }}>
              Manage automations →
            </a>
          </div>

          {/* Copilot thread */}
          {copilot.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 200, overflowY: "auto" }}>
              {copilot.map((message, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", justifyContent: message.role === "founder" ? "flex-end" : "flex-start" }}>
                  {message.role !== "founder" && (
                    <img src="/astra-mascot.png" alt="" style={{ width: 22, height: 22, objectFit: "contain", borderRadius: 4, imageRendering: "pixelated", flexShrink: 0 }} />
                  )}
                  <div style={{ maxWidth: "85%", padding: "8px 10px", borderRadius: 10, background: message.role === "founder" ? "#002EFF" : "rgba(255,255,255,0.06)", color: "#EDF1FB", fontSize: 11, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                    {message.content}
                  </div>
                </div>
              ))}
              {copilotBusy && (
                <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <img src="/astra-mascot.png" alt="" style={{ width: 22, height: 22, objectFit: "contain", borderRadius: 4, imageRendering: "pixelated", flexShrink: 0 }} />
                  <div style={{ display: "inline-flex", gap: 4, alignItems: "center", padding: "8px 10px", borderRadius: 10, background: "rgba(255,255,255,0.06)" }}>
                    {[0, 120, 240].map(d => <span key={d} style={{ width: 5, height: 5, borderRadius: "50%", background: "rgb(125,143,255)", opacity: 0.4, animation: `sc-shimmer 1s ease-in-out ${d}ms infinite` }} />)}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Copilot bar — full-width pill, oversized mascot floats over left edge */}
          <div style={{ display: "flex", flexDirection: "column", gap: 9, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "rgb(111,123,152)", fontWeight: 700, textTransform: "uppercase", paddingLeft: 2 }}>Copilot</div>
            <div style={{ position: "relative" }}>
              {/* Mascot: over pill, anchored to left, floats up/down */}
              <div style={{ position: "absolute", left: 0, top: "50%", width: 100, height: 100, animation: "mascot-float 3s ease-in-out infinite", zIndex: 2, pointerEvents: "none" }}>
                <img src="/astra-mascot.png" alt="" style={{ width: "100%", height: "100%", objectFit: "contain", imageRendering: "pixelated" }} />
              </div>
              {/* Pill spans full width, left padding clears astronaut */}
              <div style={{ display: "flex", alignItems: "center", gap: 11, background: "rgb(10,13,23)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 16, padding: "7px 7px 7px 96px", boxShadow: "rgba(0,0,0,0.6) 0px 10px 26px -16px" }}>
                <input
                  value={copilotInput}
                  onChange={e => setCopilotInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendCopilot(); } }}
                  placeholder={copilotSessionId ? "Ask Astra to start a run, draft copy, or find leads…" : "Start a run to enable copilot"}
                  disabled={copilotBusy || !copilotSessionId}
                  style={{ flex: "1 1 0%", background: "transparent", border: "none", outline: "none", color: "rgb(237,241,251)", fontSize: 13.5, fontFamily: "'Hanken Grotesk', inherit" }}
                />
                <button onClick={sendCopilot} disabled={copilotBusy || !copilotInput.trim() || !copilotSessionId}
                  style={{ width: 36, height: 36, borderRadius: 10, background: "#002EFF", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flex: "0 0 auto", opacity: (!copilotInput.trim() || !copilotSessionId) ? 0.5 : 1 }}>
                  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 19V5M5 12l7-7 7 7" />
                  </svg>
                </button>
              </div>
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
