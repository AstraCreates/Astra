// Client-side session history — persisted in localStorage

export interface SessionRecord {
  sessionId: string;
  founderId: string;
  companyName: string;
  instruction: string;
  startedAt: number;
  status: "running" | "done" | "error" | "stalled";
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

// ── Server-synced sessions (cross-device, for signed-in accounts) ──────────────
// Populated by setServerSessions() from the backend /sessions index. Merged with
// the local localStorage list so the sidebar shows the same history on any device.
let serverSessions: SessionRecord[] = EMPTY_SESSIONS;
let serverVersion = 0;
let mergedCache: SessionRecord[] = EMPTY_SESSIONS;
let mergedKey = "";

function computeMerged(): SessionRecord[] {
  const local = readSessionsSnapshot();
  const key = `${cachedRaw}|${serverVersion}`;
  if (key === mergedKey) return mergedCache;
  const byId = new Map<string, SessionRecord>();
  // Server first; local overrides because it carries richer data (artifacts, company name).
  for (const s of serverSessions) byId.set(s.sessionId, s);
  for (const s of local) byId.set(s.sessionId, { ...byId.get(s.sessionId), ...s });
  mergedCache = Array.from(byId.values()).sort((a, b) => b.startedAt - a.startedAt);
  mergedKey = key;
  return mergedCache;
}

/** Replace the server-synced session list and notify subscribers. */
export function setServerSessions(records: SessionRecord[]): void {
  serverSessions = records;
  serverVersion += 1;
  emitSessionsChange();
}

/** Drop a single server-synced session from the in-memory list (after a remote delete). */
export function removeServerSession(sessionId: string): void {
  if (!serverSessions.some(s => s.sessionId === sessionId)) return;
  serverSessions = serverSessions.filter(s => s.sessionId !== sessionId);
  serverVersion += 1;
  emitSessionsChange();
}

export function getSessionSnapshot(): SessionRecord[] {
  return computeMerged();
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

// Write the session list to localStorage without ever throwing. Artifact values
// can be large (copy, base64), so 50 of them easily blow the storage quota — which
// previously threw QuotaExceededError and broke unrelated callers (e.g. the
// onboarding launch button). Trim oversized values, then prune the oldest entries
// and retry until it fits; give up to an empty list rather than throw.
function persist(sessions: SessionRecord[]): SessionRecord[] {
  const trimmed = sessions.slice(0, 50).map(s => ({
    ...s,
    artifacts: (s.artifacts || []).slice(0, 12).map(a => ({
      ...a,
      value: typeof a.value === "string" && a.value.length > 2000 ? a.value.slice(0, 2000) + "…" : a.value,
    })),
  }));
  for (let limit = trimmed.length; ; limit = Math.floor(limit / 2)) {
    const slice = trimmed.slice(0, Math.max(limit, 0));
    try {
      const raw = JSON.stringify(slice);
      localStorage.setItem(KEY, raw);
      cachedRaw = raw;
      cachedSessions = slice;
      return slice;
    } catch {
      if (limit <= 0) {
        try { localStorage.removeItem(KEY); } catch { /* ignore */ }
        cachedRaw = "[]";
        cachedSessions = EMPTY_SESSIONS;
        return cachedSessions;
      }
    }
  }
}

export function saveSession(record: SessionRecord): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().filter(s => s.sessionId !== record.sessionId);
  sessions.unshift(record);
  persist(sessions);
  emitSessionsChange();
}

export function updateSession(sessionId: string, patch: Partial<SessionRecord>): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().map(s =>
    s.sessionId === sessionId ? { ...s, ...patch } : s
  );
  persist(sessions);
  emitSessionsChange();
}

export function deleteSession(sessionId: string): void {
  if (typeof window === "undefined") return;
  const sessions = getSessions().filter(s => s.sessionId !== sessionId);
  persist(sessions);
  emitSessionsChange();
}

export function clearAllSessions(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(KEY);
  cachedRaw = "[]";
  cachedSessions = EMPTY_SESSIONS;
  emitSessionsChange();
}
