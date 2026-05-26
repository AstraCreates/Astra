// Client-side session history — persisted in localStorage

export interface SessionRecord {
  sessionId: string;
  founderId: string;
  companyName: string;
  instruction: string;
  startedAt: number;
  status: "running" | "done" | "error";
  artifacts: { label: string; value: string; href?: string; icon: string }[];
}

const KEY = "astra_sessions";
const SESSION_CHANGE_EVENT = "astra:sessions-changed";
const EMPTY_SESSIONS: SessionRecord[] = [];
let cachedRaw: string | null = null;
let cachedSessions: SessionRecord[] = EMPTY_SESSIONS;

function readSessionsSnapshot(): SessionRecord[] {
  if (typeof window === "undefined") return EMPTY_SESSIONS;
  try {
    const raw = localStorage.getItem(KEY) ?? "[]";
    if (raw === cachedRaw) return cachedSessions;
    cachedRaw = raw;
    cachedSessions = JSON.parse(raw);
    return cachedSessions;
  } catch {
    cachedRaw = null;
    cachedSessions = EMPTY_SESSIONS;
    return EMPTY_SESSIONS;
  }
}

function emitSessionsChange(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(SESSION_CHANGE_EVENT));
}

export function getSessions(): SessionRecord[] {
  return readSessionsSnapshot();
}

export function getSessionSnapshot(): SessionRecord[] {
  return readSessionsSnapshot();
}

export function subscribeSessions(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handleChange = () => callback();
  window.addEventListener("storage", handleChange);
  window.addEventListener(SESSION_CHANGE_EVENT, handleChange);
  return () => {
    window.removeEventListener("storage", handleChange);
    window.removeEventListener(SESSION_CHANGE_EVENT, handleChange);
  };
}

export function saveSession(record: SessionRecord): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().filter(s => s.sessionId !== record.sessionId);
  sessions.unshift(record);
  const next = sessions.slice(0, 50);
  const raw = JSON.stringify(next);
  localStorage.setItem(KEY, raw);
  cachedRaw = raw;
  cachedSessions = next;
  emitSessionsChange();
}

export function updateSession(sessionId: string, patch: Partial<SessionRecord>): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().map(s =>
    s.sessionId === sessionId ? { ...s, ...patch } : s
  );
  const raw = JSON.stringify(sessions);
  localStorage.setItem(KEY, raw);
  cachedRaw = raw;
  cachedSessions = sessions;
  emitSessionsChange();
}

export function deleteSession(sessionId: string): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().filter(s => s.sessionId !== sessionId);
  const raw = JSON.stringify(sessions);
  localStorage.setItem(KEY, raw);
  cachedRaw = raw;
  cachedSessions = sessions;
  emitSessionsChange();
}
