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
  setChats: (chats: CompanyChatThread[]) => void;
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

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { userId, isLoading } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const companyId = founderId;
  const setCompanyId = useCallback(() => {}, []);
  const refreshCompanies = useCallback(async () => {}, []);

  const [chats, setChatsState] = useState<CompanyChatThread[]>([]);
  const [chatsLoaded, setChatsLoaded] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState("default");
  const setChats = useCallback((next: CompanyChatThread[]) => {
    // Filter out any chats currently pending deletion so that a stale poll
    // response can't resurrect a just-deleted thread.
    const filtered = next.filter(chat => !pendingDeleteThreadIdsRef.current.has(chat.id));
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
      setActiveThreadId("default");
    }
  }, [chats, activeThreadId]);

  // Optimistic: show the new chat immediately (matches the founder's own
  // message echo pattern in CompanyHome) rather than waiting on the round
  // trip -- ensure_company_operations/ensure_default_chat_thread run on
  // every request this hits, so on a busy company the real response can
  // take a beat even though the actual create is a single small write.
  const pendingCreateRef = useRef<Map<string, Promise<string>>>(new Map());

  // Track thread_ids currently being deleted client-side. If a stale poll
  // response arrives after deleteChat's optimistic removal, the poll's
  // setChats call should not resurrect the just-deleted thread. The poll
  // timer and deleteChat are independent writers to the same chats state;
  // this ref allows setChats to filter out any ids that are mid-delete.
  const pendingDeleteThreadIdsRef = useRef<Set<string>>(new Set());

  const createChat = useCallback(async () => {
    const tempId = `optimistic-${Date.now()}`;
    setChatsState(prev => [...prev, { id: tempId, title: "New chat", updatedAt: new Date().toISOString() }]);
    setActiveThreadId(tempId);
    const creation = (async () => {
      const result = await createChatThread({ founderId, companyId });
      setChats(result.data.chats);
      setActiveThreadId(current => (current === tempId ? result.threadId : current));
      return result.threadId;
    })();
    pendingCreateRef.current.set(tempId, creation);
    try {
      await creation;
    } catch {
      setChatsState(prev => prev.filter(chat => chat.id !== tempId));
      setActiveThreadId(current => (current === tempId ? "default" : current));
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
    if (activeThreadId === threadId) setActiveThreadId("default");
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
