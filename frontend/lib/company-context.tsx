"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
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
  setChats: (chats: CompanyChatThread[]) => void;
  activeThreadId: string;
  setActiveThreadId: (threadId: string) => void;
  createChat: () => Promise<void>;
  deleteChat: (threadId: string) => Promise<void>;
}

const CompanyContext = createContext<CompanyContextValue | null>(null);

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { userId, isLoading } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const companyId = founderId;
  const setCompanyId = useCallback(() => {}, []);
  const refreshCompanies = useCallback(async () => {}, []);

  const [chats, setChats] = useState<CompanyChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState("default");

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
  const createChat = useCallback(async () => {
    const tempId = `optimistic-${Date.now()}`;
    setChats(prev => [...prev, { id: tempId, title: "New chat", updatedAt: new Date().toISOString() }]);
    setActiveThreadId(tempId);
    try {
      const result = await createChatThread({ founderId, companyId });
      setChats(result.data.chats);
      setActiveThreadId(result.threadId);
    } catch {
      setChats(prev => prev.filter(chat => chat.id !== tempId));
      setActiveThreadId("default");
    }
  }, [founderId, companyId]);

  const deleteChat = useCallback(async (threadId: string) => {
    const previous = chats;
    setChats(prev => prev.filter(chat => chat.id !== threadId));
    if (activeThreadId === threadId) setActiveThreadId("default");
    try {
      const data = await deleteChatThread({ founderId, companyId }, threadId);
      setChats(data.chats);
    } catch {
      setChats(previous);
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
      setChats,
      activeThreadId,
      setActiveThreadId,
      createChat,
      deleteChat,
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
