"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, listSessions, deleteSessionRemote, killSession, getSessionDigest, getCredits, type SessionIndexEntry, type SessionDigest } from "@/lib/api";
import { deleteSession as deleteLocalSession } from "@/lib/history";
import { useDevUser } from "@/lib/use-dev-user";
import EmptyState from "@/components/EmptyState";
import CopilotDock from "@/components/CopilotDock";
import PageHeader, { HeaderPrimaryBtn, HeaderSecondaryBtn } from "@/components/PageHeader";
import StatusChip from "@/components/StatusChip";
import { extractGoalTitle, relativeTime } from "@/lib/format";
import Skeleton from "@/components/Skeleton";
import LaunchCompleteScreen, { shouldShowLaunchComplete, markLaunchCompleteShown, consumePreviewSignal } from "./LaunchCompleteScreen";

const GREETINGS = [
  "Welcome back",
  "Let's get to work",
  "Ready to build",
  "Good to see you",
  "Let's keep building",
];

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
        @keyframes sc-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        .dv-run-row { display: flex; align-items: center; gap: 12px; padding: 8px 4px; border-top: 1px solid rgba(255,255,255,.06); cursor: pointer; transition: background .12s; }
        .dv-run-row:first-child { border-top: none; }
        .dv-run-row:hover { background: rgba(255,255,255,0.03); }
        .sc-progress-track { height: 3px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-top: 6px; }
        .sc-progress-fill { height: 100%; width: 100%; border-radius: 3px; transform-origin: left; transition: transform 0.8s ease; }
        .sc-progress-indeterminate { height: 100%; width: 35%; border-radius: 3px; animation: sc-indeterminate 1.4s ease-in-out infinite; }
        @media (max-width: 700px) { .dv-body { flex-direction: column !important; } .dv-goal-col { flex: none !important; width: 100% !important; } }
      `}</style>

      <div style={{ flex: 1, overflowY: "auto", background: "var(--bg)", fontFamily: "var(--font-sans)" }}>
        <PageHeader
          title={headline || "Welcome back."}
          subtitle={sessions !== null
            ? `${running > 0 ? `${running} run${running !== 1 ? "s" : ""} active` : "No active runs"} · ${(sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length} completed today`
            : "Loading…"}
          badge={stalled > 0 ? { label: `${stalled} stalled`, color: "amber" } : undefined}
          stats={[
            { label: "Active", value: String(running) },
            { label: "Done today", value: String((sessions || []).filter(s => s.status === "done" && s.created_at && (Date.now() - new Date(s.created_at).getTime()) < 86400000).length) },
            { label: "Credits", value: credits !== null ? credits.toLocaleString() : "—" },
          ]}
          actions={
            <>
              <HeaderPrimaryBtn label="+ New run" onClick={() => router.push("/dashboard?new=1")} />
              <HeaderSecondaryBtn label="Refresh" onClick={() => { void load(); }} />
            </>
          }
        />

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
                if (!active) {
                  return (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px 20px", gap: 14, flex: 1 }}>
                      <EmptyState title="No active goals" hint="Start a run and Astra will get to work." />
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
                const ringColor = isStalled ? "#FFFFA6" : "var(--accent)";

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
                <div style={{ display: "grid", gap: 10 }}>
                  <Skeleton height={16} width="30%" />
                  <Skeleton height={48} />
                  <Skeleton height={48} />
                </div>
              ) : error ? (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ fontSize: 12, color: "#6f7b98", marginBottom: 10 }}>{error}</div>
                  <button style={{ padding: "8px 18px", fontSize: 12, fontWeight: 600, color: "#fff", background: "#002EFF", border: "none", cursor: "pointer", borderRadius: 8 }} onClick={load}>Try again</button>
                </div>
              ) : !regularSessions.length ? (
                <EmptyState title="No runs yet" hint="Start your first run and Astra will get to work." cta={<button onClick={() => router.push("/dashboard?new=1")} className="btn pri">Start first run →</button>} />
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

                      const meta = (s: SessionIndexEntry) => {
                        const t = relativeTime(s.created_at);
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
                              {s.kind === "scheduled" && (
                                <span style={{ fontSize: 8, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,.08)", border: "1px solid rgba(245,158,11,.28)", padding: "2px 6px", letterSpacing: ".06em", textTransform: "uppercase", borderRadius: 4, flexShrink: 0, whiteSpace: "nowrap" }}>Auto</span>
                              )}
                              <StatusChip tone={s.status === "killed" ? "error" : (s.status as "running" | "done" | "error" | "stalled")} label={s.status === "killed" ? "Stopped" : undefined} />
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
            <CopilotDock
              open={copilotOpen}
              busy={copilotBusy}
              messages={copilot}
              inputRef={copilotInputRef}
              placeholder="Ask Astra to start a run, draft copy, or find leads…"
              emptyText={copilotSession ? `Copilot attached to "${copilotTitle}". Ask anything about run state, approvals, or next steps.` : "Start a run to enable copilot context."}
              onToggle={() => setCopilotOpen((v) => !v)}
              onFocus={() => setCopilotOpen(true)}
              onSend={() => { setCopilotOpen(true); void sendCopilot(); }}
            />
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
