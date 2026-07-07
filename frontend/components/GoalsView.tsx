"use client";

import { useCallback, useEffect, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { listSessions, type SessionIndexEntry } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

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

type StatusKind = "running" | "done" | "error" | "other";

function statusKind(s: string): StatusKind {
  if (s === "running") return "running";
  if (s === "done") return "done";
  if (s === "error" || s === "killed") return "error";
  return "other";
}

const STATUS_META: Record<StatusKind, { label: string; color: string; dot: string }> = {
  running: { label: "Running", color: "var(--blue)",  dot: "var(--blue)"  },
  done:    { label: "Done",    color: "var(--green)", dot: "var(--green)" },
  error:   { label: "Failed",  color: "var(--red)",   dot: "var(--red)"   },
  other:   { label: "Stalled", color: "var(--amber)", dot: "var(--amber)" },
};

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, letterSpacing: ".08em",
      textTransform: "uppercase", color: "var(--fd)",
      fontFamily: "var(--font-code)", marginBottom: 10,
    }}>
      {children}
    </div>
  );
}

function ChildRow({ session }: { session: SessionIndexEntry }) {
  const kind = statusKind(session.status);
  const meta = STATUS_META[kind];
  const title = extractGoalTitle(session.goal || "Untitled");
  return (
    <div
      onClick={e => { e.stopPropagation(); window.location.assign(`/s/${session.session_id}`); }}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 16px 8px 0",
        cursor: "pointer",
        borderBottom: "1px solid var(--bd)",
        opacity: kind === "done" ? 0.6 : 1,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: meta.dot }} />
      <span style={{ flex: 1, fontSize: 12, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {title}
      </span>
      <span style={{ fontSize: 9, fontFamily: "var(--font-code)", color: meta.color, fontWeight: 700, flexShrink: 0, textTransform: "uppercase" }}>
        {meta.label}
      </span>
      {(session.kind === "operating" || session.kind === "scheduled") && (
        <span style={{ fontSize: 8, fontFamily: "var(--font-code)", fontWeight: 700, color: "var(--amber)", background: "var(--adim)", border: "1px solid var(--ab)", padding: "1px 5px", letterSpacing: ".06em", textTransform: "uppercase", flexShrink: 0 }}>Auto</span>
      )}
    </div>
  );
}

function GoalCard({ session, childSessions }: { session: SessionIndexEntry; childSessions: SessionIndexEntry[] }) {
  const kind = statusKind(session.status);
  const meta = STATUS_META[kind];
  const title = extractGoalTitle(session.goal || "Untitled");
  const isRunning = kind === "running";

  return (
    <div
      onClick={() => window.location.assign(`/s/${session.session_id}`)}
      style={{
        border: "1px solid var(--bd2)",
        borderRadius: 10,
        background: "var(--surface)",
        cursor: "pointer",
        overflow: "hidden",
        transition: "border-color 0.12s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--blue)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "var(--bd2)"; }}
    >
      <div style={{ padding: "14px 16px", display: "flex", alignItems: "flex-start", gap: 12 }}>
        <span style={{
          marginTop: 5, width: 8, height: 8, borderRadius: "50%",
          flexShrink: 0, background: meta.dot,
          ...(isRunning ? { animation: "gl-pulse 1.5s ease-in-out infinite" } : {}),
        }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13.5, fontWeight: 600, color: "var(--fg)", lineHeight: 1.4,
            overflow: "hidden", display: "-webkit-box",
            WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          }}>
            {title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
            {session.company_name && (
              <span style={{ fontSize: 10.5, color: "var(--fm)", fontWeight: 500 }}>{session.company_name}</span>
            )}
            {session.stack_id && (
              <span style={{ fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-code)" }}>
                {session.stack_id.replace(/_/g, " ")}
              </span>
            )}
            <span style={{ fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-code)", marginLeft: "auto" }}>
              {ago(session.created_at)}
            </span>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0, marginTop: 2 }}>
          <span style={{
            fontSize: 10, fontWeight: 700,
            color: meta.color, fontFamily: "var(--font-code)",
            textTransform: "uppercase", letterSpacing: ".05em",
          }}>
            {meta.label}
          </span>
          {(session.kind === "operating" || session.kind === "scheduled") && (
            <span style={{ fontSize: 8, fontFamily: "var(--font-code)", fontWeight: 700, color: "var(--amber)", background: "var(--adim)", border: "1px solid var(--ab)", padding: "1px 5px", letterSpacing: ".06em", textTransform: "uppercase" }}>Auto</span>
          )}
        </div>
      </div>

      {childSessions.length > 0 && (
        <div style={{ borderTop: "1px solid var(--bd)", paddingLeft: 28 }}>
          {childSessions.map(c => <ChildRow key={c.session_id} session={c} />)}
        </div>
      )}
    </div>
  );
}

export default function GoalsView() {
  const { userId } = useDevUser();
  const [sessions, setSessions] = useState<SessionIndexEntry[] | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      setSessions(await listSessions(userId, 100));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [userId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, [load]);

  const allSessions = sessions ?? [];
  const statusById = new Map(allSessions.map(s => [s.session_id, s.status]));

  const isActive = (st: string) => st === "running" || st === "stalled";

  // Promote a sub-run to top-level when it's active but its parent is done.
  // Without this, running operating sessions are hidden inside a "Completed" parent card.
  const isPromoted = (s: SessionIndexEntry): boolean => {
    if (!s.parent_session_id) return false;
    return isActive(s.status) && !isActive(statusById.get(s.parent_session_id) ?? "");
  };

  const tops = allSessions.filter(s => !s.parent_session_id || isPromoted(s));

  // Only nest children whose parent is itself active (running/stalled).
  // Done sub-runs under done parents remain nested; active sub-runs are promoted above.
  const childMap = new Map<string, SessionIndexEntry[]>();
  for (const s of allSessions) {
    if (s.parent_session_id && !isPromoted(s)) {
      const arr = childMap.get(s.parent_session_id) ?? [];
      arr.push(s);
      childMap.set(s.parent_session_id, arr);
    }
  }

  const running = tops.filter(s => s.status === "running");
  const stalled = tops.filter(s => s.status === "stalled");
  const completed = tops.filter(s => !isActive(s.status));

  const activeCount = running.length + stalled.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <style>{`@keyframes gl-pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:0.5; transform:scale(0.75); } }`}</style>

      <PageHeader
        title="Goals"
        badge={
          activeCount > 0
            ? { label: `${activeCount} active`, color: "blue" }
            : { label: "all clear", color: "green" }
        }
        stats={[
          { label: "Active",    value: String(activeCount) },
          { label: "Completed", value: String(completed.length) },
          { label: "Total",     value: String(tops.length) },
        ]}
      />

      <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px 56px" }}>
        {err && <p style={{ fontSize: 12, color: "var(--red)", margin: "0 0 16px" }}>{err}</p>}

        {sessions === null && (
          <p style={{ fontSize: 13, color: "var(--fd)" }}>Loading…</p>
        )}

        {sessions !== null && tops.length === 0 && (
          <div style={{
            border: "1px dashed var(--bd2)", borderRadius: 10,
            padding: "40px 20px", textAlign: "center",
          }}>
            <p style={{ fontSize: 13, color: "var(--fm)", margin: 0 }}>
              No goals yet. Hit <strong>New run</strong> to get started.
            </p>
          </div>
        )}

        {running.length > 0 && (
          <section style={{ marginBottom: 28 }}>
            <GroupLabel>Active</GroupLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {running.map(s => <GoalCard key={s.session_id} session={s} childSessions={childMap.get(s.session_id) ?? []} />)}
            </div>
          </section>
        )}

        {stalled.length > 0 && (
          <section style={{ marginBottom: 28 }}>
            <GroupLabel>Needs attention</GroupLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {stalled.map(s => <GoalCard key={s.session_id} session={s} childSessions={childMap.get(s.session_id) ?? []} />)}
            </div>
          </section>
        )}

        {completed.length > 0 && (
          <section>
            <GroupLabel>Completed</GroupLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {completed.map(s => <GoalCard key={s.session_id} session={s} childSessions={childMap.get(s.session_id) ?? []} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
