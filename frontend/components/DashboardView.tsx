"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, getCredits, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
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
  const [credits, setCredits] = useState<number | null>(null);

  useEffect(() => {
    if (!userId) return;
    getCredits(userId).then(b => setCredits(b.balance)).catch(() => {});
  }, [userId]);

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
        .dv-run-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-top: 1px solid rgba(255,255,255,.06); cursor: pointer; transition: background .12s; }
        .dv-run-row:first-child { border-top: none; }
        .dv-run-row:hover { background: rgba(255,255,255,0.03); }
        .sc-progress-track { height: 3px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-top: 6px; }
        .sc-progress-fill { height: 100%; width: 100%; border-radius: 3px; transform-origin: left; transition: transform 0.8s ease; }
        .sc-progress-indeterminate { height: 100%; width: 35%; border-radius: 3px; animation: sc-indeterminate 1.4s ease-in-out infinite; }
        .dash-copilot { border: 1px solid rgba(255,255,255,.1); background: #0A0D17; border-radius: 16px; overflow: hidden; }
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
        .dash-copilot-bar { display: flex; align-items: center; gap: 8px; padding: 7px 7px 7px 16px; }
        .dash-copilot-ctx { font-size: 10px; color: rgba(237,241,251,0.4); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; flex-shrink: 1; }
        .dash-copilot-input { flex: 1; min-width: 0; background: transparent; border: none; color: #EDF1FB; padding: 0 8px; font-size: 13.5px; outline: none; font-family: inherit; }
        .dash-copilot-input::placeholder { color: rgba(237,241,251,0.3); }
        .dash-copilot-btn { height: 36px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #EDF1FB; padding: 0 11px; cursor: pointer; font-size: 11px; font-weight: 600; white-space: nowrap; font-family: inherit; }
        .dash-copilot-btn.primary { background: #002EFF; border-color: #002EFF; width: 36px; padding: 0; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .dash-copilot-btn:disabled { opacity: 0.4; cursor: default; }
        @media (max-width: 700px) { .dv-body { flex-direction: column !important; } .dv-goal-col { flex: none !important; width: 100% !important; } }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto", background: "#05070E", fontFamily: "'Hanken Grotesk', var(--font-geist-sans), sans-serif" }}>

        {/* ── Hero: lineart variant ── */}
        <div style={{ position: "relative", height: 224, overflow: "hidden", background: "#0a1b6b" }}>
          <img src="/hero-lineart.png" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "50% 25%" } as React.CSSProperties} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg,rgba(5,7,14,.82) 0%,rgba(5,7,14,.44) 42%,transparent 72%)" }} />
          <div style={{ position: "relative", zIndex: 2, padding: "28px 32px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: ".1em", color: "rgba(255,255,255,.7)", fontWeight: 600, textTransform: "uppercase" }}>Dashboard</div>
              <h1 style={{ margin: "12px 0 4px", fontSize: 32, fontWeight: 700, letterSpacing: "-.02em", color: "#fff" }}>{headline || "Welcome back."}</h1>
              <div style={{ fontSize: 13.5, color: "rgba(255,255,255,.78)" }}>
                {sessions !== null
                  ? `${running > 0 ? `${running} run${running !== 1 ? "s" : ""} active` : "No active runs"} · ${(sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length} completed today`
                  : "Loading…"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
              <button
                data-tour="dash-new-run"
                onClick={() => router.push("/dashboard?new=1")}
                style={{ background: "#fff", color: "#002EFF", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              >+ New run</button>
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

        {/* ── Main content: flex column, gap:16 — mirrors HTML spec ── */}
        <div style={{ padding: "18px 30px", display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Today header */}
          <div style={{ fontSize: 11, letterSpacing: ".08em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase" }}>Today</div>

          {/* Two columns */}
          <div className="dv-body" style={{ display: "flex", gap: 18, alignItems: "stretch" }}>

            {/* ── Active Goal card (330px) ── */}
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
                const circumference = 157;
                const dashOffset = circumference * (1 - progress);
                const cleanTitle = extractGoalTitle(active.goal || "Untitled run");
                const isStalled = active.status === "stalled";
                const isDone = active.status === "done";
                const ringColor = isStalled ? "#FFFFA6" : accentColor;

                return (
                  <>
                    {/* Title row + donut */}
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

                    {/* Done + queued counts */}
                    <div style={{ display: "flex", gap: 16, marginTop: 16, fontSize: 12, color: "#8A93AD" }}>
                      <span>✓ <b style={{ color: "#EDF1FB" }}>{phasesDone}</b> done</span>
                      <span>○ <b style={{ color: "#EDF1FB" }}>{phasesPending}</b> queued</span>
                    </div>

                    {/* Buttons */}
                    <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
                      <button
                        onClick={() => router.push(`/s/${active.session_id}`)}
                        style={{ flex: 1, background: "#002EFF", color: "#fff", border: "none", borderRadius: 8, padding: 10, fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >▶ Run now</button>
                      <button
                        style={{ background: "transparent", color: "#c3cbe0", border: "1px solid rgba(255,255,255,.14)", borderRadius: 8, padding: "10px 16px", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
                      >Pause</button>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* ── Recent Runs card (flex:1) ── */}
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
                  {/* 4-stat grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
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
                      <div key={label} style={{ background: "#070911", border: "1px solid rgba(255,255,255,.06)", borderRadius: 9, padding: 12 }}>
                        <div style={{ fontSize: 10.5, color: "#6f7b98" }}>{label}</div>
                        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 5 }}>{value}</div>
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
                          {visibleRows.map(({ s, child }, i) => (
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
                              {(s.kind === "operating" || s.kind === "scheduled") && (
                                <span style={{ fontSize: 8, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,.08)", border: "1px solid rgba(245,158,11,.28)", padding: "2px 6px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0, whiteSpace: "nowrap" }}>Auto</span>
                              )}
                              {chip(s.status)}
                              <button
                                title={pendingDel.has(s.session_id) ? "Click again to confirm" : "Delete"}
                                disabled={deleting.has(s.session_id)}
                                onClick={e => del(e, s)}
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

          {/* ── Automations banner ── */}
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

          {/* ── Copilot ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 9, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,.06)" }}>
            <div style={{ fontSize: 11, letterSpacing: ".06em", color: "#6f7b98", fontWeight: 700, textTransform: "uppercase", paddingLeft: 2 }}>Copilot</div>
            <div style={{ display: "flex", alignItems: "center", gap: 11, background: "#0A0D17", border: "1px solid rgba(255,255,255,.1)", borderRadius: 16, padding: "7px 7px 7px 16px", boxShadow: "0 10px 26px -16px rgba(0,0,0,.6)" }}>
              <img src="/logo.png" alt="" style={{ width: 17, height: 17, objectFit: "contain", opacity: 0.75, flexShrink: 0, cursor: "pointer" } as React.CSSProperties} onClick={() => setCopilotOpen(v => !v)} />
              {copilotOpen && copilot.length > 0 && (
                <div className="dash-copilot-thread" style={{ position: "absolute", bottom: "100%", left: 0, right: 0, marginBottom: 8 }}>
                  {/* thread is shown inline below */}
                </div>
              )}
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
            {/* Copilot thread (below bar when open) */}
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
