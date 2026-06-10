"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { listWorkspaces, type Workspace } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

export interface CompanyChoice {
  companyId: string;
  name: string;
  status: string;
  workspace?: Workspace;
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

function companyName(workspace: Workspace): string {
  return workspace.company_name || workspace.name || "Untitled company";
}

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { userId, isLoading } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [companyId, setCompanyIdState] = useState("");
  const [loading, setLoading] = useState(true);

  const companies = useMemo<CompanyChoice[]>(() => {
    const sorted = workspaces
      .filter(workspace => workspace.status !== "archived")
      .sort((a, b) => (b.last_active || "").localeCompare(a.last_active || ""));

    // Deduplicate by company name — keep the most-recently-active workspace per name.
    const seen = new Set<string>();
    const deduped = sorted.filter(workspace => {
      const key = companyName(workspace).toLowerCase().trim();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    const active = deduped.map(workspace => ({
      companyId: workspace.company_id || workspace.workspace_id,
      name: companyName(workspace),
      status: workspace.status,
      workspace,
      isPrimary: false,
    }));

    // Only include the "primary" fallback if no real workspaces exist yet
    if (active.length === 0) {
      return [{
        companyId: founderId,
        name: "My company",
        status: "active",
        isPrimary: true,
      }];
    }
    return active;
  }, [founderId, workspaces]);

  const refreshCompanies = useCallback(async () => {
    if (isLoading || !founderId) return;
    setLoading(true);
    try {
      setWorkspaces(await listWorkspaces(founderId));
    } catch {
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, [founderId, isLoading]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshCompanies();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshCompanies]);

  useEffect(() => {
    if (loading || companies.length === 0) return;
    const storageKey = `astra_company_id:${founderId}`;
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("company") || params.get("workspace") || "";
    const stored = localStorage.getItem(storageKey) || "";
    const next = [requested, stored, companies[0].companyId, founderId]
      .find(candidate => companies.some(company => company.companyId === candidate))
      || founderId;
    const timer = window.setTimeout(() => {
      setCompanyIdState(next);
      localStorage.setItem(storageKey, next);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [companies, founderId, loading]);

  const setCompanyId = useCallback((nextCompanyId: string) => {
    if (!companies.some(company => company.companyId === nextCompanyId)) return;
    setCompanyIdState(nextCompanyId);
    localStorage.setItem(`astra_company_id:${founderId}`, nextCompanyId);
  }, [companies, founderId]);

  const activeCompany = companies.find(company => company.companyId === companyId) || companies[0] || null;

  return (
    <CompanyContext.Provider value={{
      founderId,
      companies,
      companyId: activeCompany?.companyId || founderId,
      activeCompany,
      loading,
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
