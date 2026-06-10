"use client";

import React, { createContext, useCallback, useContext } from "react";
import { useDevUser } from "@/lib/use-dev-user";

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
}

const CompanyContext = createContext<CompanyContextValue | null>(null);

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { userId, isLoading } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const companyId = founderId;
  const setCompanyId = useCallback(() => {}, []);
  const refreshCompanies = useCallback(async () => {}, []);

  return (
    <CompanyContext.Provider value={{
      founderId,
      companies: [],
      companyId,
      activeCompany: null,
      loading: isLoading,
      setCompanyId,
      refreshCompanies,
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
