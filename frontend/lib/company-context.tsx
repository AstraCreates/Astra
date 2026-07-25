"use client";

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { createChatThread, deleteChatThread, type CompanyChatThread } from "@/lib/company-os";

export interface CompanyChoice {
  companyId: string;
  name: string;
  status: string;
  isPrimary: boolean;
}

interface CompanyContextValue {
  founderId: string;
  companies: CompanyChoice[];
  companyId: string;
  activeCompany: CompanyChoice | null;
  loading: boolean;
  setCompanyId: (companyId: string) => void;
  refreshCompanies: () => Promise<void>;
  chats: CompanyChatThread[];
  chatsLoaded: boolean;
  setChats: (chats: CompanyChatThread[], source?: "mutation" | "poll") => void;
  activeThreadId: string;
  setActiveThreadId: (threadId: string) => void;
  createChat: () => Promise<void>;
  deleteChat: (threadId: string) => Promise<void>;
  // Sending a message needs the REAL thread_id, never the local
  // "optimistic-<ts>" placeholder createChat shows immediately -- the
  // backend has no record of that id, so a message sent under it (and any
  // squad/task work the copilot dispatches from it) gets permanently
  // orphaned the moment the real id swaps in. Resolves immediately for an
  // already-real id; awaits the in-flight create for a placeholder.
  resolveActiveThreadId: () => Promise<string>;
}

const CompanyContext = createContext<CompanyContextValue | null>(null);

// "default" used to be a safe, always-there fallback target. It no longer
// is -- the default/"General" chat is deletable now, and stays deleted
// (the backend only self-heals it back when it's the founder's LAST
// remaining chat) whenever another chat still exists. Falling back to the
// literal string "default" after that point lands on another archived,
// sidebar-invisible thread whose legacy messages (every message sent
// before chat threads existed backfills onto thread_id "default") are
// still real and still render -- the founder sees a chat with no sidebar
// entry, exactly the bug this fixes. Prefer "default" only while it's
// still actually a live, visible chat; otherwise pick any real one.
function pickFallbackThreadId(list: CompanyChatThread[], excludeId?: string): string {
  const candidates = list.filter(chat => chat.id !== excludeId);
  if (candidates.some(chat => chat.id === "default")) return "default";
  return candidates[0]?.id ?? "default";
}

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { userId, isLoading } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const companyId = founderId;
  const setCompanyId = useCallback(() => {}, []);
  const refreshCompanies = useCallback(async () => {}, []);

  const [chats, setChatsState] = useState<CompanyChatThread[]>([]);
  const [chatsLoaded, setChatsLoaded] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState("default");
  // Chat mutations and the Home polling loop are independent writers. Keep
  // a newly-created real id pinned until a poll has observed it, so an older
  // in-flight poll cannot make the optimistic chat briefly disappear.
  const pendingServerConfirmationThreadIdsRef = useRef<Set<string>>(new Set());

  // Optimistic creates need to resolve a real backend thread before messages
  // can be sent against them.
  const pendingCreateRef = useRef<Map<string, Promise<string>>>(new Map());

  // Track thread_ids currently being deleted client-side. If a stale poll
  // response arrives after deleteChat's optimistic removal, the poll's
  // setChats call should not resurrect the just-deleted thread.
  const pendingDeleteThreadIdsRef = useRef<Set<string>>(new Set());

  const setChats = useCallback((next: CompanyChatThread[], source: "mutation" | "poll" = "mutation") => {
    // Filter out any chats currently pending deletion so that a stale poll
    // response can't resurrect a just-deleted thread.
    const filtered = next.filter(chat => !pendingDeleteThreadIdsRef.current.has(chat.id));

    if (source === "poll" && pendingServerConfirmationThreadIdsRef.current.size > 0) {
      for (const threadId of Array.from(pendingServerConfirmationThreadIdsRef.current)) {
        if (filtered.some(chat => chat.id === threadId)) {
          pendingServerConfirmationThreadIdsRef.current.delete(threadId);
        }
      }

      // This response was started before the create mutation committed. Wait
      // for the next poll that contains every just-created real thread.
      if (pendingServerConfirmationThreadIdsRef.current.size > 0) {
        setChatsLoaded(true);
        return;
      }
    }

    setChatsState(filtered);
    setChatsLoaded(true);
  }, []);

  useEffect(() => {
    if (!companyId) return;
    const saved = window.localStorage.getItem(`astra-active-thread-${companyId}`);
    if (saved) setActiveThreadId(saved);
  }, [companyId]);

  useEffect(() => {
    if (!companyId) return;
    window.localStorage.setItem(`astra-active-thread-${companyId}`, activeThreadId);
  }, [companyId, activeThreadId]);

  // If the active thread got deleted (this tab or another), fall back to the
  // default thread instead of showing an empty feed for a chat that's gone.
  useEffect(() => {
    if (chats.length && !chats.some(chat => chat.id === activeThreadId)) {
      setActiveThreadId(pickFallbackThreadId(chats));
    }
  }, [chats, activeThreadId]);

  const createChat = useCallback(async () => {
    const tempId = `optimistic-${Date.now()}`;
    setChatsState(prev => [...prev, { id: tempId, title: "New chat", updatedAt: new Date().toISOString() }]);
    setActiveThreadId(tempId);
    const creation = (async () => {
      const result = await createChatThread({ founderId, companyId });
      pendingServerConfirmationThreadIdsRef.current.add(result.threadId);
      setChats(result.data.chats);
      setActiveThreadId(current => (current === tempId ? result.threadId : current));
      return result.threadId;
    })();
    pendingCreateRef.current.set(tempId, creation);
    try {
      await creation;
    } catch {
      setChatsState(prev => prev.filter(chat => chat.id !== tempId));
      setActiveThreadId(current => (current === tempId ? pickFallbackThreadId(chats, tempId) : current));
    } finally {
      pendingCreateRef.current.delete(tempId);
    }
  }, [founderId, companyId]);

  const resolveActiveThreadId = useCallback(async () => {
    const pending = pendingCreateRef.current.get(activeThreadId);
    return pending ? pending : activeThreadId;
  }, [activeThreadId]);

  const deleteChat = useCallback(async (threadId: string) => {
    const previous = chats;
    pendingDeleteThreadIdsRef.current.add(threadId);
    setChatsState(prev => prev.filter(chat => chat.id !== threadId));
    if (activeThreadId === threadId) setActiveThreadId(pickFallbackThreadId(previous, threadId));
    try {
      const data = await deleteChatThread({ founderId, companyId }, threadId);
      setChats(data.chats);
    } catch {
      setChatsState(previous);
    } finally {
      pendingDeleteThreadIdsRef.current.delete(threadId);
    }
  }, [founderId, companyId, chats, activeThreadId]);

  return (
    <CompanyContext.Provider value={{
      founderId,
      companies: [],
      companyId,
      activeCompany: null,
      loading: isLoading,
      setCompanyId,
      refreshCompanies,
      chats,
      chatsLoaded,
      setChats,
      activeThreadId,
      setActiveThreadId,
      createChat,
      deleteChat,
      resolveActiveThreadId,
    }}>
      {children}
    </CompanyContext.Provider>
  );
}

export function useCompany() {
  const value = useContext(CompanyContext);
  if (!value) throw new Error("useCompany must be used within CompanyProvider");
  return value;
}
